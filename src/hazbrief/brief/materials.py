"""The materials resolver: properties for any material, the seeded pack first, then
CAMEO Chemicals, then PubChem (HB-119; DN-020 ADDENDUM-02 section 2 items 2 and 6;
DN-009 E2, "a cache seeded from the modelled set, a cache miss fetching PubChem and
CAMEO and storing the record with its provenance hash").

`resolve(ref)` returns `Properties` or `Unresolved`:

1. **The seed** (`packs/materials_properties.json`, HB-66, HB-109, HB-124):
   `provenance: held`, every value with its held page.
2. **The runtime cache** (`materials.yaml` `cache_path`, gitignored, separate
   from the committed seed so a run never rewrites it): an entry fetched before,
   `provenance: fetched`, until its sources' horizon passes.
3. **A fetch.** PubChem identifies the compound (PUG REST by name, then by CAS); its PUG
   View record names CAMEO Chemicals' datasheet when CAMEO holds one. CAMEO's values are
   taken first, as the seed's read order takes them (HB-109); PubChem's experimental
   values fill what CAMEO does not print. CAMEO is reached through PubChem's reference
   because the only CAMEO path from a UN number or a name to a datasheet is its search,
   which its robots.txt disallows for every agent and which the project counts a
   manners violation (HB-01 RESULT section 8; the HB-119 evidence).

Every HTTP call goes through the one upstream client (`hazbrief.utils.fetch_json`,
`fetch_bytes`), recorded and replayed like every exchange; PubChem's are gated by its
held limits (`RateGate`). Each exchange is written to the evidence store with its
source, url, retrieval time and content hash, and so is the resolution record that
names them all (DN-009 C2); the cache entry carries that record's hash.

A value a source does not print is absent, named, never defaulted (standards s4). Every
fetched value carries the label "properties fetched at <time> from <source>, not
benchmark-validated" (DN-009 C1); the source term reads the entry exactly as it reads
the seed's (`source_term.material_from_pack`), and the label travels with the value.

Thresholds (HB-119 step 4, ADDENDUM-00): a toxic level from the EPA's compiled AEGL
table by CAS or name, else the NIOSH Pocket Guide's IDLH, both parsed once with the page
of every row (`scripts/build_packs.py thresholds`); the LFL from the resolved properties
with the ALOHA fraction the seed carries; oxygen deficiency from 29 CFR 1910.134 as the
seed carries it. The dense-gas channel picks the block its class names.

The server never imports this module (DN-001 invariant 3;
test_container_image.py).
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import cache
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

import yaml

from hazbrief.config import REPO_ROOT, settings
from hazbrief.models import (
    CrossCheck,
    HeldValue,
    LevelOfConcern,
    Thermodynamics,
)
from hazbrief.utils import Exchange, UpstreamServiceError, fetch_bytes, fetch_json

CONFIG_FILE = Path(__file__).with_name("materials.yaml")
CONFIG_KEYS = (
    "label",
    "sources",
    "paths",
    "pubchem_not_found_status",
    "cameo_reference_source_name",
    "name_rules",
    "thresholds",
    "activity",
    "cache_path",
    "cache_env",
)


@cache
def config() -> dict:
    """`materials.yaml`, every key required (a missing one is a broken install)."""
    cfg = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8")) or {}
    missing = [k for k in CONFIG_KEYS if k not in cfg]
    if missing:
        raise RuntimeError(f"{CONFIG_FILE} is missing {missing}")
    return cfg


# ── the request and the two outcomes ──────────────────────────────────────────────────


@dataclass(frozen=True)
class MaterialRef:
    """What the brief knows about a material: its UN (or NA) number, its name as the
    ERG prints it, and a CAS number where one is known."""

    un: str | None = None
    name: str | None = None
    cas: str | None = None

    def key(self) -> str:
        """The cache key: the UN number, else the CAS number, else the name."""
        if self.un:
            return f"un:{self.un}"
        if self.cas:
            return f"cas:{self.cas}"
        if self.name:
            return f"name:{self.name.strip().lower()}"
        raise ValueError("a material reference names a UN number, a CAS or a name")


Provenance = Literal["held", "fetched"]


@dataclass(frozen=True)
class Properties:
    """A material's properties as the source term and the dense-gas channel read them:
    `entry` has the seed pack's `materials[un]` shape (`thermodynamics`,
    `levels_of_concern`, `molecular_weight_g_mol`, `lfl_vol_pct`, `name`, `un`), and a
    fetched entry also carries `provenance` with its labels. `labels` maps each
    thermodynamic field to the text printed beside its value."""

    ref: MaterialRef
    provenance: Provenance
    entry: dict
    labels: dict[str, str]
    fetched_at: str | None = None
    sources: tuple[str, ...] = ()
    record_hash: str | None = None
    notes: tuple[str, ...] = ()

    def label(self, field_name: str) -> str:
        return self.labels.get(field_name) or f"{field_name}: absent"


@dataclass(frozen=True)
class Unresolved:
    """No source resolves the material; `reasons` says, per source, why."""

    ref: MaterialRef
    reasons: dict[str, str]

    def message(self) -> str:
        what = self.ref.name or self.ref.cas or f"UN{self.ref.un}"
        parts = "; ".join(f"{k}: {v}" for k, v in self.reasons.items())
        return f"not available: no source resolves {what} ({parts})"


# ── PubChem's limits (pubchem-pug-view-limits; config.py) ─────────────────────────────


class RateLimited(RuntimeError):
    """A request the gate refuses: admitting it would pass a held limit."""


class RateGate:
    """PubChem's three limits, client side: requests per second, requests per minute,
    and running time per minute ("No more than 5 requests per second. No more than 400
    requests per minute. No longer than 300 s running time per minute.",
    pubchem-pug-view-limits). `admit` refuses a request over a limit; `wait` sleeps
    until one is admitted. `clock` is injectable so a test can drive time."""

    def __init__(
        self,
        per_second: int | None = None,
        per_minute: int | None = None,
        running_s_per_minute: float | None = None,
        clock=time.monotonic,
        sleep=None,
    ):
        self.per_second = per_second or settings.pubchem_max_requests_per_second
        self.per_minute = per_minute or settings.pubchem_max_requests_per_minute
        self.running = (
            running_s_per_minute or settings.pubchem_max_running_seconds_per_minute
        )
        self.clock = clock
        self._sleep = sleep
        self.starts: deque[float] = deque()
        self.durations: deque[tuple[float, float]] = deque()

    def _trim(self, now: float) -> None:
        while self.starts and now - self.starts[0] >= 60.0:
            self.starts.popleft()
        while self.durations and now - self.durations[0][0] >= 60.0:
            self.durations.popleft()

    def refusal(self, now: float | None = None) -> str | None:
        """Why a request now would pass a limit, or None."""
        now = self.clock() if now is None else now
        self._trim(now)
        last_second = sum(1 for s in self.starts if now - s < 1.0)
        if last_second >= self.per_second:
            return (
                f"{last_second} requests in the last second (limit {self.per_second})"
            )
        if len(self.starts) >= self.per_minute:
            n = len(self.starts)
            return f"{n} requests in the last minute (limit {self.per_minute})"
        ran = sum(d for _, d in self.durations)
        if ran >= self.running:
            return (
                f"{ran:.0f} s running time in the last minute "
                f"(limit {self.running:g} s)"
            )
        return None

    def admit(self, now: float | None = None) -> float:
        """Record a request start, or raise `RateLimited` naming the limit."""
        now = self.clock() if now is None else now
        why = self.refusal(now)
        if why:
            raise RateLimited(f"PubChem rate gate: {why}")
        self.starts.append(now)
        return now

    def done(self, started: float, now: float | None = None) -> None:
        now = self.clock() if now is None else now
        self.durations.append((started, max(0.0, now - started)))

    async def wait(self) -> float:
        import asyncio

        while True:
            now = self.clock()
            if self.refusal(now) is None:
                return self.admit(now)
            await (self._sleep or asyncio.sleep)(0.25)


#: One gate per process: the limits are per user, not per resolution.
_GATE: RateGate | None = None


def gate() -> RateGate:
    global _GATE
    if _GATE is None:
        _GATE = RateGate()
    return _GATE


# ── fetching ──────────────────────────────────────────────────────────────────────────


@dataclass
class _Run:
    """One resolution's exchanges, in order, and the gate it spends."""

    gate: RateGate
    exchanges: list[Exchange] = field(default_factory=list)

    async def pubchem(self, path: str, params: dict | None = None) -> Exchange:
        cfg = config()
        api = cfg["sources"]["pubchem"]["api"]
        started = None
        if settings.hazbrief_http_mode != "replay":
            started = await self.gate.wait()
        try:
            ex = await fetch_json(
                api, path, params, answers=tuple(cfg["pubchem_not_found_status"])
            )
        finally:
            if started is not None:
                self.gate.done(started)
        self.exchanges.append(ex)
        return ex

    async def cameo(self, path: str) -> Exchange:
        api = config()["sources"]["cameo"]["api"]
        ex = await fetch_bytes(api, path, accept=("text/html",))
        self.exchanges.append(ex)
        return ex


def _seg(text: str) -> str:
    """A name or CAS as one percent-encoded path segment."""
    return quote(text.strip(), safe="")


def _found(ex: Exchange) -> bool:
    return ex.status == 200 and not (isinstance(ex.body, dict) and "Fault" in ex.body)


def lookup_names(ref: MaterialRef) -> list[str]:
    """The names PubChem is asked for, in `materials.yaml` `name_rules` order, each
    once."""
    out: list[str] = []
    for rule in config()["name_rules"]:
        if not ref.name:
            break
        if rule == "as_given":
            cand = ref.name.strip()
        elif rule == "before_first_comma":
            cand = ref.name.split(",", 1)[0].strip()
        else:
            raise RuntimeError(f"materials.yaml: unknown name rule {rule!r}")
        if cand and cand.lower() not in {n.lower() for n in out}:
            out.append(cand)
    return out


async def _identify(
    run: _Run, ref: MaterialRef, cas_from_un: list[str]
) -> tuple[int | None, list[str]]:
    """PubChem's one CID for the material, by name then by CAS, and the trail of what
    each lookup answered. More than one CID for a name is not a resolution: the name
    is ambiguous, and the next form is tried."""
    paths = config()["paths"]
    trail = []
    forms = [("name", n) for n in lookup_names(ref)]
    forms += [("CAS", c) for c in ([ref.cas] if ref.cas else []) + cas_from_un]
    seen = set()
    for kind, text in forms:
        if text.lower() in seen:
            continue
        seen.add(text.lower())
        ex = await run.pubchem(paths["pubchem_cids_by_name"].format(name=_seg(text)))
        if not _found(ex):
            trail.append(f"{kind} {text!r}: not found ({ex.status})")
            continue
        cids = ((ex.body or {}).get("IdentifierList") or {}).get("CID") or []
        if len(cids) == 1:
            trail.append(f"{kind} {text!r}: CID {cids[0]}")
            return int(cids[0]), trail
        trail.append(f"{kind} {text!r}: {len(cids)} CIDs {cids[:5]}, ambiguous")
    return None, trail


# ── reading CAMEO's datasheet ─────────────────────────────────────────────────────────


class _CameoPage(HTMLParser):
    """The datasheet's title, its identifier cells (CAS, UN/NA) and the text of each
    `div.physical_props` block, whitespace collapsed."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.cas, self.unna, self.props = "", [], [], []
        self._mode: str | None = None
        self._depth = 0
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self._mode is not None:
            if tag == self._tag:
                self._depth += 1
            return
        if tag == "h1" and "datasheet" in (a.get("class") or ""):
            self._open("title", tag)
        elif tag == "td" and a.get("headers") in ("th-cas", "th-unna"):
            self._open(a["headers"], tag)
        elif tag == "div" and (a.get("class") or "") == "physical_props":
            self._open("prop", tag)

    def _open(self, mode, tag):
        self._mode, self._tag, self._depth, self._buf = mode, tag, 1, []

    def handle_endtag(self, tag):
        if self._mode is None or tag != self._tag:
            return
        self._depth -= 1
        if self._depth:
            return
        text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
        if self._mode == "title":
            self.title = text
        elif self._mode == "th-cas":
            self.cas += re.findall(r"\b\d{2,7}-\d{2}-\d\b", text)
        elif self._mode == "th-unna":
            self.unna += re.findall(r"\b\d{4}\b", text)
        elif self._mode == "prop":
            self.props.append(text)
        self._mode = None

    def handle_data(self, data):
        if self._mode is not None:
            self._buf.append(data)


def read_cameo(html: bytes) -> dict:
    """The datasheet's name, CAS and UN/NA numbers and its Physical Properties
    fields, `{label: text as printed}` (the label without its colon)."""
    p = _CameoPage()
    p.feed(html.decode("utf-8", "replace"))
    props = {}
    for text in p.props:
        m = re.match(r"([^:]{2,60}?):\s*(.*)$", text)
        if m:
            props.setdefault(m.group(1).strip(), m.group(2).strip())
    return {"name": p.title, "cas": p.cas, "unna": p.unna, "props": props}


# ── reading PubChem's record ──────────────────────────────────────────────────────────


def _strings(info: dict) -> str:
    v = info.get("Value") or {}
    out = [s.get("String", "") for s in v.get("StringWithMarkup") or []]
    if "Number" in v:
        out.append(" ".join(f"{n:g}" for n in v["Number"]) + " " + v.get("Unit", ""))
    return " ".join(x for x in out if x).strip()


def pubchem_rows(view: dict) -> tuple[dict[str, list[tuple[str, str]]], dict]:
    """`({heading: [(source name, text)]}, {reference number: reference})` from a PUG
    View record, every subsection flattened, rows in PubChem's order."""
    rec = (view or {}).get("Record") or {}
    refs = {r.get("ReferenceNumber"): r for r in rec.get("Reference") or []}
    rows: dict[str, list[tuple[str, str]]] = {}

    def walk(sec):
        for info in sec.get("Information") or []:
            src = (refs.get(info.get("ReferenceNumber")) or {}).get("SourceName") or ""
            text = _strings(info)
            if text:
                rows.setdefault(sec.get("TOCHeading") or "", []).append((src, text))
        for s in sec.get("Section") or []:
            walk(s)

    for s in rec.get("Section") or []:
        walk(s)
    return rows, refs


# ── numbers, units and temperatures as printed ────────────────────────────────────────

_NUM = r"[-−]?\d[\d,]*(?:\.\d+)?(?:\s*[xX×]\s*10\s*[+\-−]?\s*\d+)?"
#: The degree sign and the two look-alikes PubChem's depositors print for it
#: ("157 ºC", U+00BA; U+02DA). Matched, never rewritten: a quote stays as printed.
DEG = "[°º˚]"
_TEMP = re.compile(rf"({_NUM})\s*{DEG}?\s*([CFK])\b(?!\w)")
#: The definitions applied where a page prints another unit (HB-109's precedent).
F_TO_K = (
    "K = (°F − 32) / 1.8 + 273.15 "
    "(the definitions of the degree Fahrenheit and the kelvin)"
)
C_TO_K = "K = °C + 273.15 (the definition of the degree Celsius)"
CAL = (
    "1 cal = 4.184 J (the thermochemical calorie; the page does not say which calorie, "
    "and the International Table calorie, 4.1868 J, differs by 0.07 %)"
)


def number(text: str) -> float:
    t = text.replace("−", "-").replace(",", "").replace(" ", "")
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)(?:[xX×]10([+\-]?\d+))?", t)
    if not m:
        raise ValueError(text)
    v = float(m.group(1))
    return v * 10 ** int(m.group(2)) if m.group(2) else v


def to_kelvin(value: float, unit: str) -> tuple[float, str | None]:
    if unit == "F":
        return (value - 32.0) / 1.8 + 273.15, F_TO_K
    if unit == "C":
        return value + 273.15, C_TO_K
    return value, None


def temperature(text: str) -> tuple[float, str, str | None] | None:
    """The first temperature printed in `text`: (K, as printed, conversion)."""
    m = _TEMP.search(text)
    if not m:
        return None
    k, conv = to_kelvin(number(m.group(1)), m.group(2))
    return k, m.group(0), conv


def _half_unit(printed: str) -> float:
    """Half a unit in the last printed digit: the precision of a value printed with
    no stated uncertainty (HB-109's agreement rule)."""
    digits = printed.replace(",", "").split(".")
    return 0.5 * 10 ** (-len(digits[1])) if len(digits) == 2 else 0.5


def _strip_citation(text: str) -> str:
    return re.sub(r"\s*\((?:[A-Z][A-Za-z/&. ]+,\s*\d{4})\)\s*", " ", text).strip()


# ── one value, as the pack holds it ───────────────────────────────────────────────────


@dataclass
class _Src:
    """Where a fetched value was read: the source key, the exchange and its entity
    hash."""

    key: str
    ex: Exchange
    sha256: str


def _receipt(src: _Src, quote_text: str) -> dict:
    s = config()["sources"][src.key]
    return {
        "doc_id": s["doc_id"],
        "page": 1,
        "locator": src.ex.url,
        "quote": re.sub(r"\s+", " ", quote_text).strip(),
        "read_by": "text_layer",
        "sha256": src.sha256,
    }


def _absent(unit: str, why: str) -> dict:
    return {
        "value": None,
        "unit": unit,
        "status": "not_held",
        "reason": why,
        "receipt": None,
        "derived_from": [],
        "temperature_k": None,
        "as_printed": None,
        "conversion": None,
        "value_range": None,
        "source_tier": None,
    }


def _held(
    value: float | None,
    unit: str,
    src: _Src,
    quote_text: str,
    *,
    as_printed: str | None = None,
    conversion: str | None = None,
    temperature_k: float | None = None,
    value_range: list[float] | None = None,
    derived_from: list[str] | None = None,
) -> dict:
    return {
        "value": None if value is None else round(value, 10),
        "unit": unit,
        "status": "held",
        "reason": None,
        "receipt": _receipt(src, quote_text),
        "derived_from": derived_from or [],
        "temperature_k": None if temperature_k is None else round(temperature_k, 6),
        "as_printed": as_printed,
        "conversion": conversion,
        "value_range": value_range,
        # CAMEO Chemicals and PubChem's experimental section are compiled property
        # tables (HB-124's `reference-table`); fetched, not benchmark-validated, is the
        # label's word, carried in the entry's provenance.
        "source_tier": "reference-table",
    }


def _plain(d: dict) -> dict:
    """A ThermoValue dict as a plain HeldValue (no temperature, tier or printed
    form)."""
    return {
        k: d[k]
        for k in ("value", "unit", "status", "reason", "receipt", "derived_from")
    }


# ── the fields, CAMEO first ───────────────────────────────────────────────────────────


def _cameo_fields(cameo: dict, src: _Src) -> dict[str, dict]:
    """The thermodynamic fields CAMEO's Physical Properties print, as held values. CAMEO
    prints no heat capacity, no liquid density, no critical point and no correlation
    (docs/evidence/hb119/sources.md)."""
    props, out = cameo["props"], {}

    def q(label):
        return f"{label}: {props[label]}"

    if "Molecular Weight" in props:
        t = _strip_citation(props["Molecular Weight"])
        m = re.match(rf"({_NUM})\s*$", t)
        if m:
            out["molecular_weight_g_mol"] = _held(
                number(m.group(1)), "g/mol", src, q("Molecular Weight"), as_printed=t
            )
    if "Boiling Point" in props:
        t = _strip_citation(props["Boiling Point"])
        rng = re.match(rf"({_NUM})\s*(?:to|-)\s*({_NUM})\s*{DEG}\s*([CF])", t)
        one = re.match(rf"({_NUM})\s*{DEG}\s*([CF])(?:\s+at\s+760\s*mm\s*Hg)?\s*$", t)
        if rng:
            lo, conv = to_kelvin(number(rng.group(1)), rng.group(3))
            hi, _ = to_kelvin(number(rng.group(2)), rng.group(3))
            out["normal_boiling_point_k"] = _held(
                None,
                "K",
                src,
                q("Boiling Point"),
                as_printed=t,
                conversion=conv,
                value_range=[round(lo, 6), round(hi, 6)],
            )
        elif one:
            k, conv = to_kelvin(number(one.group(1)), one.group(2))
            out["normal_boiling_point_k"] = _held(
                k, "K", src, q("Boiling Point"), as_printed=t, conversion=conv
            )
    if "Vapor Pressure" in props:
        t = _strip_citation(props["Vapor Pressure"])
        m = re.match(rf"({_NUM})\s*mm\s*Hg(.*)$", t)
        if m:
            tt = temperature(m.group(2))
            out["vapour_pressure_as_printed"] = _held(
                number(m.group(1)),
                "mmHg",
                src,
                q("Vapor Pressure"),
                as_printed=t,
                temperature_k=tt[0] if tt else None,
                conversion=tt[2] if tt else None,
            )
    if "Specific Gravity" in props:
        t = _strip_citation(props["Specific Gravity"]).split(" - ")[0].strip()
        m = re.match(rf"({_NUM})(.*)$", t)
        if m:
            tt = temperature(m.group(2))
            out["liquid_specific_gravity"] = _held(
                number(m.group(1)),
                "relative to water",
                src,
                q("Specific Gravity"),
                as_printed=t,
                temperature_k=tt[0] if tt else None,
                conversion=tt[2] if tt else None,
            )
    return out


def _cameo_lfl(cameo: dict, src: _Src) -> dict | None:
    label = "Lower Explosive Limit (LEL)"
    t = cameo["props"].get(label)
    if not t:
        return None
    m = re.match(rf"({_NUM})\s*%", _strip_citation(t))
    if not m:
        return None
    return _plain(_held(number(m.group(1)), "vol %", src, f"{label}: {t}"))


# ── PubChem's experimental section ────────────────────────────────────────────────────

_HC = re.compile(
    rf"(?:heat capacity|specific heat)[^:;=]*?(?:\(([^)]*)\))?[^:;=\d]*[:=]?\s*"
    rf"({_NUM})\s*((?:k?J|k?cal)\s*/\s*\(?\s*(?:mol|g|kg)[^;,)]*)",
    re.I,
)


def _cp_unit(unit: str) -> tuple[str | None, float, str | None]:
    """(basis "mol" | "g" | "kg", factor to J, conversion text) of a heat-capacity unit
    as printed, or (None, 0, None) for one this reads no basis from."""
    u = re.sub(r"[\s()·.*]", "", unit).lower()
    m = re.match(r"(k?)(j|cal)/(mol|g|kg)", u)
    if not m:
        return None, 0.0, None
    factor = (1000.0 if m.group(1) else 1.0) * (4.184 if m.group(2) == "cal" else 1.0)
    return m.group(3), factor, CAL if m.group(2) == "cal" else None


def _pubchem_heat_capacities(
    rows: dict, src: _Src, mw: float | None
) -> dict[str, dict]:
    """Each heat capacity PubChem's experimental section prints with its phase, as
    J/mol/K, with the temperature and phase printed beside it in the receipt (HB-119
    ADDENDUM-01 section 2). A value whose phase is not printed, or per mass where no
    molecular weight is held, is not taken. The first printed per phase is taken."""
    out: dict[str, dict] = {}
    for heading, items in rows.items():
        for source, text in items:
            for m in _HC.finditer(text):
                ctx = (m.group(1) or "") + " " + text[max(0, m.start() - 10) : m.end()]
                phase = (
                    "vapour"
                    if re.search(r"\b(gas|vapou?r|ideal gas)\b", ctx, re.I)
                    else "liquid"
                    if re.search(r"\bliquid\b", ctx, re.I)
                    else None
                )
                field_name = {
                    "vapour": "vapour_heat_capacity_j_mol_k",
                    "liquid": "liquid_heat_capacity_j_mol_k",
                }.get(phase or "")
                if field_name is None or field_name in out:
                    continue
                basis, factor, conv = _cp_unit(m.group(3))
                if basis is None:
                    continue
                v = number(m.group(2)) * factor
                derived = []
                if basis in ("g", "kg"):
                    if mw is None:
                        continue
                    v = v * mw / (1.0 if basis == "g" else 1000.0)
                    derived = ["molecular_weight_g_mol"]
                    conv = "; ".join(
                        x for x in (conv, "per mole = per mass x molecular weight") if x
                    )
                tt = temperature(m.group(1) or "") or temperature(
                    text[m.end() : m.end() + 40]
                )
                out[field_name] = _held(
                    v,
                    "J/mol/K",
                    src,
                    f"{heading} ({source}): {m.group(0)}",
                    as_printed=m.group(0).strip(),
                    conversion=conv,
                    temperature_k=tt[0] if tt else None,
                    derived_from=derived,
                )
    return out


def _pubchem_boiling_point(rows: dict, src: _Src) -> tuple[dict | None, list[str]]:
    """PubChem's boiling point rows at one atmosphere (a row naming another pressure is
    not one), chosen by HB-109's agreement rule: the first row that agrees with another
    within the larger of their printed precisions; a single row as printed; none where
    no two agree. Returns the value and every candidate as printed."""
    cands = []
    for source, text in rows.get("Boiling Point") or []:
        t = _strip_citation(text)
        if re.search(r"mm\s*Hg|kPa|atm|\bPa\b|torr", t, re.I) and not re.search(
            r"760\s*\]?\s*\[?\s*mm\s*Hg|101\.3\s*kPa|1\s*atm", t, re.I
        ):
            continue
        m = re.match(rf"\s*({_NUM})\s*{DEG}?\s*([CFK])\b", t)
        if not m or re.search(rf"{_NUM}\s*(?:to|-)\s*{_NUM}\s*{DEG}", t):
            continue
        k, conv = to_kelvin(number(m.group(1)), m.group(2))
        tol = _half_unit(m.group(1)) / (1.8 if m.group(2) == "F" else 1.0)
        cands.append((k, tol, conv, source, text))
    printed = [f"{c[3]}: {c[4]}" for c in cands]
    if not cands:
        return None, printed
    pick = cands[0] if len(cands) == 1 else None
    for i, a in enumerate(cands):
        if pick:
            break
        for b in cands[i + 1 :]:
            if abs(a[0] - b[0]) <= max(a[1], b[1]):
                pick = a
                break
    if pick is None:
        return None, printed
    k, tol, conv, source, text = pick
    value = _held(
        k,
        "K",
        src,
        f"Boiling Point ({source}): {text}",
        as_printed=text,
        conversion=conv,
    )
    value["_precision_k"] = tol
    return value, printed


def boiling_point_check(cameo_tb: dict, pubchem_tb: dict | None, printed: list[str]):
    """CAMEO's boiling point against PubChem's taken row (HB-109's cross-check): they
    agree within the larger of their printed precisions; PubChem's rows are listed."""
    m = re.match(rf"\s*({_NUM})\s*{DEG}\s*([CF])", cameo_tb["as_printed"] or "")
    tol_c = (_half_unit(m.group(1)) / (1.8 if m.group(2) == "F" else 1.0)) if m else 0.0
    names = {k: v["name"] for k, v in config()["sources"].items()}
    values = {
        names["cameo"]: f"{cameo_tb['value']:.2f} K ({cameo_tb['as_printed']})",
        names["pubchem"]: "; ".join(printed) if printed else None,
    }
    if pubchem_tb is None:
        status = "single_source"
    else:
        tol = max(tol_c, pubchem_tb.get("_precision_k") or 0.0)
        status = (
            "agree"
            if abs(pubchem_tb["value"] - cameo_tb["value"]) <= tol
            else ("disputed")
        )
    return CrossCheck(
        field="normal boiling point (K)", values=values, status=status
    ).model_dump(mode="json")


_HV_UNITS = {"kj/mol": 1000.0, "j/mol": 1.0, "kcal/mol": 4184.0, "cal/mol": 4.184}


def _pubchem_heat_of_vaporization(
    rows: dict, src: _Src, tb: float | None
) -> dict | None:
    """PubChem's heat of vaporisation, per mole, the printed row nearest the normal
    boiling point (HB-109's rule for a tabulated value; a tie goes to the first
    printed); with no boiling point held, the first printed."""
    cands = []
    for source, text in rows.get("Heat of Vaporization") or []:
        for part in text.split(";"):
            m = re.search(rf"({_NUM})\s*(k?cal|k?J)\s*/\s*mol\b(.*)", part, re.I)
            if not m:
                continue
            unit = f"{m.group(2)}/mol".lower()
            tt = temperature(m.group(3))
            conv = CAL if "cal" in unit else None
            cands.append((number(m.group(1)) * _HV_UNITS[unit], tt, conv, source, part))
    if not cands:
        return None
    if tb is not None:
        timed = [c for c in cands if c[1] is not None]
        if timed:
            cands = sorted(timed, key=lambda c: abs(c[1][0] - tb))
    v, tt, conv, source, part = cands[0]
    convs = "; ".join(x for x in (conv, tt[2] if tt else None) if x) or None
    return _held(
        v,
        "J/mol",
        src,
        f"Heat of Vaporization ({source}): {part}",
        as_printed=part.strip(),
        conversion=convs,
        temperature_k=tt[0] if tt else None,
    )


def _pubchem_vapour_pressure(rows: dict, src: _Src) -> dict | None:
    for source, text in rows.get("Vapor Pressure") or []:
        m = re.match(rf"\s*({_NUM})\s*mm\s*Hg(.*)$", _strip_citation(text), re.I)
        if m:
            tt = temperature(m.group(2))
            return _held(
                number(m.group(1)),
                "mmHg",
                src,
                f"Vapor Pressure ({source}): {text}",
                as_printed=text,
                temperature_k=tt[0] if tt else None,
                conversion=tt[2] if tt else None,
            )
    return None


def _pubchem_critical(rows: dict, src: _Src) -> dict[str, dict]:
    out = {}
    for heading, items in rows.items():
        for source, text in items:
            m = re.search(
                rf"critical temperature\s*[:=]?\s*({_NUM})\s*{DEG}?\s*([CFK])\b",
                text,
                re.I,
            )
            if m and "critical_temperature_k" not in out:
                k, conv = to_kelvin(number(m.group(1)), m.group(2))
                out["critical_temperature_k"] = _held(
                    k,
                    "K",
                    src,
                    f"{heading} ({source}): {m.group(0)}",
                    as_printed=m.group(0),
                    conversion=conv,
                )
            m = re.search(
                rf"critical pressure\s*[:=]?\s*({_NUM})\s*(MPa|kPa|bar|atm)\b",
                text,
                re.I,
            )
            if m and "critical_pressure_bar" not in out:
                factor, conv = {
                    "mpa": (10.0, "1 MPa = 10 bar (SI)"),
                    "kpa": (0.01, "1 kPa = 0.01 bar (SI)"),
                    "bar": (1.0, None),
                    "atm": (1.01325, "1 atm = 1.01325 bar (the standard atmosphere)"),
                }[m.group(2).lower()]
                out["critical_pressure_bar"] = _held(
                    number(m.group(1)) * factor,
                    "bar",
                    src,
                    f"{heading} ({source}): {m.group(0)}",
                    as_printed=m.group(0),
                    conversion=conv,
                )
    return out


def _pubchem_lfl(rows: dict, src: _Src) -> dict | None:
    """The lower flammable limit in vol %: the "Lower Explosive Limit (LEL)" heading's
    first percentage, else a "Flammable Limits" row that names the lower limit, or the
    ICSC form "Explosive limits, vol% in air: a-b" (a is the lower)."""
    for source, text in rows.get("Lower Explosive Limit (LEL)") or []:
        m = re.search(rf"({_NUM})\s*%", text)
        if m:
            return _plain(
                _held(
                    number(m.group(1)),
                    "vol %",
                    src,
                    f"Lower Explosive Limit (LEL) ({source}): {text}",
                )
            )
    for source, text in rows.get("Flammable Limits") or []:
        m = re.search(rf"lower[^:;\d]*[:=]?\s*({_NUM})\s*%", text, re.I) or re.search(
            rf"vol%\s*in\s*air\s*:\s*({_NUM})\s*-\s*{_NUM}", text, re.I
        )
        if m:
            return _plain(
                _held(
                    number(m.group(1)),
                    "vol %",
                    src,
                    f"Flammable Limits ({source}): {text}",
                )
            )
    return None


# ── the thermodynamics block ──────────────────────────────────────────────────────────

THERMO_UNITS = {
    "normal_boiling_point_k": "K",
    "heat_of_vaporization_j_mol": "J/mol",
    "liquid_heat_capacity_j_mol_k": "J/mol/K",
    "vapour_heat_capacity_j_mol_k": "J/mol/K",
    "liquid_specific_gravity": "relative to water",
    "liquid_density_kg_m3": "kg/m3",
    "vapour_pressure_as_printed": "mmHg",
    "critical_temperature_k": "K",
    "critical_pressure_bar": "bar",
}


@cache
def _seed_spec() -> dict:
    return yaml.safe_load(
        (REPO_ROOT / "packs" / "src" / "materials_properties.yaml").read_text("utf-8")
    )


def _missing(thermo: dict) -> list[str]:
    """`required_fields` (packs/src/materials_properties.yaml) not held, in its order;
    the vapour heat capacity is held as a value or a Shomate correlation."""
    out = []
    for name in _seed_spec()["required_fields"]:
        if name == "vapour_heat_capacity":
            held = (
                thermo["vapour_heat_capacity_j_mol_k"]["value"] is not None
            ) or bool(thermo["vapour_heat_capacity_shomate"]["rows"])
        elif name == "saturation_pressure_antoine":
            held = bool(thermo[name]["rows"])
        else:
            held = thermo[name]["status"] == "held"
        if not held:
            out.append(name)
    return out


def _correlation_absent(name: str, why: str) -> dict:
    form = _seed_spec()["correlations"][name]["form"]
    return {"form": form, "status": "not_held", "reason": why, "rows": []}


def thermodynamics(
    cameo_vals: dict[str, dict],
    pubchem_vals: dict[str, dict],
    mw: dict,
    cross_checks: list[dict],
    absent_why: dict[str, str],
) -> dict:
    """The `Thermodynamics` block, CAMEO's value first, PubChem's second, absent with
    the reason otherwise; validated against HB-109's schema."""
    t: dict[str, Any] = {"proxy": None, "molecular_weight_g_mol": mw}
    for name, unit in THERMO_UNITS.items():
        t[name] = (
            cameo_vals.get(name)
            or pubchem_vals.get(name)
            or _absent(unit, absent_why.get(name) or absent_why["default"])
        )
    t["vapour_heat_capacity_shomate"] = _correlation_absent(
        "shomate",
        "CAMEO Chemicals and PubChem print no Shomate constants",
    )
    t["saturation_pressure_antoine"] = _correlation_absent(
        "antoine",
        "CAMEO Chemicals and PubChem print no Antoine constants",
    )
    t["cross_checks"] = cross_checks
    t["missing"] = _missing(t)
    return Thermodynamics.model_validate(t).model_dump(mode="json")


# ── thresholds ────────────────────────────────────────────────────────────────────────


@cache
def _table(key: str) -> dict:
    return json.loads(
        (REPO_ROOT / config()["thresholds"][key]).read_text(encoding="utf-8")
    )


def _norm_name(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def npg_cas_for_un(un: str | None) -> list[str]:
    """The CAS numbers the held NIOSH Pocket Guide prints for a UN number (its DOT
    field), in page order."""
    if not un:
        return []
    out = []
    for e in _table("idlh_table")["entries"]:
        if e["cas"] and any(g["un"] == un for g in e["un_guide"]):
            if e["cas"] not in out:
                out.append(e["cas"])
    return out


def _table_receipt(table: dict, r: dict) -> dict:
    return {**r, "sha256": table["sha256"]} if "sha256" not in r else r


def aegl2_block(cas: list[str], names: list[str]) -> tuple[dict | None, str]:
    """The `aegl2` level of concern from the compiled table (a ppm entry found by CAS,
    else by name), its cells by averaging minutes, or (None, why)."""
    cfg = config()["thresholds"]
    table = _table("aegl_table")
    want_names = {_norm_name(n) for n in names if n}
    hits = [e for e in table["entries"] if e["cas"] and e["cas"] in cas] or [
        e for e in table["entries"] if _norm_name(e["name"]) in want_names
    ]
    if not hits:
        return None, "the compiled AEGL table lists no entry for its CAS or name"
    e = hits[0]
    level = e["levels"].get("AEGL-2") or {}
    if e["unit"] != "ppm":
        return None, (
            f"the compiled AEGL table states {e['name']}'s AEGLs in {e['unit']}, "
            f"not ppm (p. {e['page']})"
        )
    if "unparsed" in level:
        return None, f"the compiled AEGL table's AEGL-2 row for {e['name']} " + (
            f"is not read: {level['unparsed']} (p. {e['page']})"
        )
    values = {}
    for minutes, col in cfg["aegl_minutes"].items():
        cell = (level.get("values") or {}).get(col) or {}
        if cell.get("value") is None:
            values[minutes] = {
                "value": None,
                "unit": "ppm",
                "status": "not_held",
                "reason": cell.get("reason") or "not printed",
                "receipt": None,
                "derived_from": [],
            }
        else:
            values[minutes] = {
                "value": cell["value"],
                "unit": "ppm",
                "status": "held",
                "reason": None,
                "receipt": _table_receipt(
                    table, cell.get("see_below") or level["receipt"]
                ),
                "derived_from": [],
            }
    block = {
        "kind": "aegl2",
        "unit": "ppm",
        "basis": f"{cfg['aegl_basis']}; {e['status']} AEGLs, {e['name']} ({e['cas']})",
        "proxy_for": None,
        "values": values,
        "components": {},
    }
    return LevelOfConcern.model_validate(block).model_dump(mode="json"), (
        f"AEGL-2, {e['status']}, epa-aegl-compiled-2018 p. {e['page']}"
    )


def idlh_block(
    cas: list[str], un: str | None, names: list[str]
) -> tuple[dict | None, str]:
    """The NIOSH Pocket Guide's IDLH in ppm (ADDENDUM-00), by CAS, then UN, then name;
    `kind: idlh`, `values["any"]`. (None, why) where the guide prints none in ppm."""
    cfg = config()["thresholds"]
    table = _table("idlh_table")
    want_names = {_norm_name(n) for n in names if n}
    entries = table["entries"]
    hits = (
        [e for e in entries if e["cas"] and e["cas"] in cas]
        or [e for e in entries if un and any(g["un"] == un for g in e["un_guide"])]
        or [e for e in entries if _norm_name(e["name"]) in want_names]
    )
    if not hits:
        return None, "the NIOSH Pocket Guide lists no entry for its CAS, UN or name"
    e = hits[0]
    if e["value"] is None or e["unit"] != "ppm":
        return None, (
            f"the NIOSH Pocket Guide prints {e['name']}'s IDLH as "
            f"{e['as_printed']!r} (p. {e['page']}), no value in ppm"
        )
    return {
        "kind": "idlh",
        "unit": "ppm",
        "basis": cfg["idlh_basis"].format(page=e["page"]),
        "proxy_for": None,
        "values": {
            "any": {
                "value": e["value"],
                "unit": "ppm",
                "status": "held",
                "reason": None,
                "receipt": _table_receipt(table, e["receipt"]),
                "derived_from": [],
            }
        },
        "components": {},
    }, f"IDLH, NIOSH NPG 2005-149 p. {e['page']}"


def _seed_level(kind: str) -> dict:
    """A seed entry's level block of `kind`, the first in UN order (the ALOHA fraction
    and the 29 CFR 1910.134 threshold are the same for every material)."""
    from hazbrief import packs as P

    mats = P.load_app_pack("materials_properties").data.model_dump(mode="json")
    for un in sorted(mats["materials"]):
        for b in mats["materials"][un]["levels_of_concern"]:
            if b["kind"] == kind and not b.get("proxy_for"):
                return b
    raise RuntimeError(f"the seed pack holds no {kind} level to copy")


def lfl_block(lfl: dict) -> dict:
    """The `lfl_fraction` level from a resolved LFL and the seed's ALOHA fraction."""
    frac = _seed_level("lfl_fraction")["components"]["fraction"]
    seed = _seed_level("lfl_fraction")
    value = lfl["value"] * frac["value"] / 100.0
    block = {
        "kind": "lfl_fraction",
        "unit": "vol %",
        "basis": seed["basis"],
        "proxy_for": None,
        "values": {
            "any": {
                "value": round(value, 10),
                "unit": "vol %",
                "status": "held",
                "reason": None,
                "receipt": None,
                "derived_from": ["lfl", "fraction"],
            }
        },
        "components": {"lfl": lfl, "fraction": frac},
    }
    return LevelOfConcern.model_validate(block).model_dump(mode="json")


def levels(
    cas: list[str], un: str | None, names: list[str], lfl: dict | None
) -> tuple[list[dict], list[str]]:
    """Every level of concern the material has, and one line per level taken or not."""
    out, notes = [], []
    aegl, why_a = aegl2_block(cas, names)
    if aegl is not None:
        out.append(aegl)
        notes.append(f"toxic level: {why_a}")
    else:
        idlh, why_i = idlh_block(cas, un, names)
        if idlh is not None:
            out.append(idlh)
            notes.append(f"toxic level: {why_i}; no AEGL ({why_a})")
        else:
            what = names[0] if names else (cas[0] if cas else f"UN{un}")
            notes.append(
                config()["thresholds"]["none"].format(what=what)
                + f" ({why_a}; {why_i})"
            )
    if lfl is not None and lfl.get("value") is not None:
        out.append(lfl_block(lfl))
        notes.append("flammable level: 60 % of the resolved LFL (the seed's fraction)")
    else:
        notes.append("flammable level: no LFL resolved")
    out.append(_seed_level("oxygen_deficiency"))
    return out, notes


# ── the evidence store (DN-009 C2) ────────────────────────────────────────────────────


def _write_exchange_record(store: Path, ex: Exchange) -> str:
    """One exchange as an evidence entity with its record: source, url, retrieval
    time, content hash. Returns the entity sha256."""
    from hazbrief import __version__
    from hazbrief.evidence import catalog
    from hazbrief.evidence import store as S

    row = catalog.row_for_exchange(ex.api, ex.url)
    sha, _ = S.write_record(
        store,
        ex.body,
        activity={
            "type": "upstream_exchange",
            "name": config()["activity"],
            "params": {"url": ex.url, "status": ex.status},
            "startedAtTime": ex.recorded_at,
            "endedAtTime": ex.recorded_at,
            "http_mode": "live" if ex.origin == "live" else "replay",
        },
        server={
            "name": "hazbrief-mcp",
            "version": __version__,
            "tool_surface_sha256": None,
        },
        source=[{"id": row["id"], "endpoint": ex.url}],
        provenance_class=row["provenance_class"],
        as_of=ex.recorded_at,
        as_of_basis="the exchange's retrieval time",
        horizon_s=row["horizon_s"],
        horizon_source=row["id"],
        media_type=ex.content_type or "application/json",
    )
    return sha


def _write_resolution(store: Path, record: dict, used: list[str], at: str) -> str:
    from hazbrief import __version__
    from hazbrief.evidence import store as S

    sha, _ = S.write_record(
        store,
        record,
        activity={
            "type": "materials_resolution",
            "name": config()["activity"],
            "params": {"ref": record["ref"]},
            "startedAtTime": at,
            "endedAtTime": at,
            "http_mode": settings.hazbrief_http_mode,
        },
        server={
            "name": "hazbrief-mcp",
            "version": __version__,
            "tool_surface_sha256": None,
        },
        source=[{"id": s, "endpoint": None} for s in record["catalog_rows"]],
        provenance_class="live_call",
        as_of=at,
        as_of_basis="the latest retrieval time among the exchanges read",
        horizon_s=record["horizon_s"],
        horizon_source=record["horizon_source"],
        used=used,
    )
    return sha


# ── the cache ─────────────────────────────────────────────────────────────────────────


def default_cache_path() -> Path:
    """`materials.yaml` `cache_path` under the repository root, or the path the
    environment variable `cache_env` names."""
    cfg = config()
    override = os.environ.get(cfg["cache_env"])
    return Path(override) if override else REPO_ROOT / cfg["cache_path"]


def _cache_path(path: Path | None) -> Path:
    return Path(path) if path else default_cache_path()


def read_cache(path: Path | None = None) -> dict:
    p = _cache_path(path)
    if not p.is_file():
        return {"entries": {}}
    return json.loads(p.read_text(encoding="utf-8"))


def _write_cache(path: Path | None, key: str, item: dict) -> None:
    """Add one fetched entry; temporary file, fsync, rename (constitution 15.1)."""
    p = _cache_path(path)
    cache_doc = read_cache(p)
    cache_doc["entries"][key] = item
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(
                json.dumps(cache_doc, indent=1, sort_keys=True, ensure_ascii=False)
            )
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _stale(item: dict, now: datetime) -> bool:
    h = item.get("horizon_s")
    if h is None:
        return False
    at = datetime.fromisoformat(item["fetched_at"].replace("Z", "+00:00"))
    return (now - at).total_seconds() > h


# ── labels ────────────────────────────────────────────────────────────────────────────


def fetched_label(source_name: str, at: str) -> str:
    return config()["label"].format(time=at, source=source_name)


def held_label(value: dict) -> str:
    r = value.get("receipt") or {}
    return f"{r.get('doc_id')} p. {r.get('page')}" if r else "derived"


def _labels(entry: dict) -> dict[str, str]:
    """Per thermodynamic field: the fetched label, or the held page, or absent."""
    prov = entry.get("provenance") or {}
    by_doc = prov.get("labels") or {}
    out = {}
    thermo = entry["thermodynamics"]
    for name in ("molecular_weight_g_mol", *THERMO_UNITS):
        v = thermo[name]
        if v["status"] != "held":
            out[name] = f"absent: {v['reason']}"
            continue
        doc = (v.get("receipt") or {}).get("doc_id")
        out[name] = by_doc.get(doc) or held_label(v)
    return out


def _seed_properties(ref: MaterialRef, entry: dict) -> Properties:
    return Properties(ref=ref, provenance="held", entry=entry, labels=_labels(entry))


# ── resolve ───────────────────────────────────────────────────────────────────────────


def _latest(exs: list[Exchange]) -> str:
    times = sorted(e.recorded_at for e in exs if e.recorded_at)
    return (
        times[-1]
        if times
        else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )


async def resolve(
    ref: MaterialRef | dict,
    *,
    seed: dict | None = None,
    cache_path: Path | None = None,
    store: Path | None = None,
    rate_gate: RateGate | None = None,
    now: datetime | None = None,
) -> Properties | Unresolved:
    """Properties for `ref` (HB-119 step 3): the seed, the cache, then a fetch.

    `seed` is the properties pack's data (`materials`), read from packs/ when not
    given; `store` is the evidence store (`hazbrief.evidence.store.default_store_dir`
    when not given). Raises only for a broken install; a source that does not answer
    is a reason in `Unresolved`."""
    if isinstance(ref, dict):
        ref = MaterialRef(**ref)
    if seed is None:
        from hazbrief import packs as P

        seed = P.load_app_pack("materials_properties").data.model_dump(mode="json")
    if ref.un and ref.un in seed["materials"]:
        return _seed_properties(ref, seed["materials"][ref.un])

    now = now or datetime.now(timezone.utc)
    key = ref.key()
    cached = read_cache(cache_path)["entries"].get(key)
    if cached and not _stale(cached, now):
        return _from_item(ref, cached)

    run = _Run(rate_gate or gate())
    reasons: dict[str, str] = {}
    try:
        return await _fetch(ref, run, key, cache_path, store, reasons)
    except UpstreamServiceError as exc:
        reasons.setdefault("fetch", str(exc))
        return Unresolved(ref, reasons)


def _from_item(ref: MaterialRef, item: dict) -> Properties:
    entry = item["entry"]
    return Properties(
        ref=ref,
        provenance="fetched",
        entry=entry,
        labels=_labels(entry),
        fetched_at=item["fetched_at"],
        sources=tuple(item["sources"]),
        record_hash=item["record_hash"],
        notes=tuple(item.get("notes") or ()),
    )


async def _fetch(
    ref: MaterialRef,
    run: _Run,
    key: str,
    cache_path: Path | None,
    store: Path | None,
    reasons: dict[str, str],
) -> Properties | Unresolved:
    from hazbrief.evidence import catalog
    from hazbrief.evidence import store as S

    cfg = config()
    names = {k: v["name"] for k, v in cfg["sources"].items()}
    paths = cfg["paths"]
    cas_from_un = npg_cas_for_un(ref.un)
    cid, trail = await _identify(run, ref, cas_from_un)
    if cid is None:
        reasons[names["cameo"]] = (
            "no datasheet located: CAMEO's datasheet is reached through PubChem's "
            "reference to it, and PubChem does not identify the material"
        )
        reasons[names["pubchem"]] = "; ".join(trail) or "no name or CAS to look up"
        return Unresolved(ref, reasons)

    props_ex = await run.pubchem(paths["pubchem_properties"].format(cid=cid))
    view_ex = await run.pubchem(
        paths["pubchem_view"].format(cid=cid),
        {"heading": paths["pubchem_view_experimental"]},
    )
    cas_ex = await run.pubchem(
        paths["pubchem_view"].format(cid=cid), {"heading": paths["pubchem_view_cas"]}
    )
    rows, refs = pubchem_rows(view_ex.body if _found(view_ex) else {})
    cas_rows, _ = pubchem_rows(cas_ex.body if _found(cas_ex) else {})
    pub_cas = []
    for _, text in cas_rows.get("CAS") or []:
        for c in re.findall(r"\b\d{2,7}-\d{2}-\d\b", text):
            if c not in pub_cas:
                pub_cas.append(c)

    cameo_ids = sorted(
        {
            str(r.get("SourceID"))
            for r in refs.values()
            if r.get("SourceName") == cfg["cameo_reference_source_name"]
            and str(r.get("SourceID") or "").isdigit()
        },
        key=int,
    )
    cameo, cameo_ex, cameo_why = None, None, None
    if not cameo_ids:
        cameo_why = (
            f"PubChem's record for CID {cid} names no CAMEO Chemicals datasheet "
            "among its experimental properties' references"
        )
    for cid_c in cameo_ids:
        ex = await run.cameo(paths["cameo_datasheet"].format(id=cid_c))
        page = read_cameo(ex.body) if ex.status == 200 else None
        if page is None:
            cameo_why = f"datasheet {cid_c} answered {ex.status}"
            continue
        if ref.un and page["unna"] and ref.un not in page["unna"]:
            cameo_why = (
                f"datasheet {cid_c} ({page['name']}) lists UN/NA {page['unna']}, "
                f"not {ref.un}"
            )
            continue
        cameo, cameo_ex = page, ex
        break

    # Every exchange read goes to the store with its record (DN-009 C2).
    store = Path(store) if store else S.default_store_dir()
    shas = {id(ex): _write_exchange_record(store, ex) for ex in run.exchanges}
    pub_src = _Src("pubchem", view_ex, shas[id(view_ex)])
    props_src = _Src("pubchem", props_ex, shas[id(props_ex)])
    cam_src = _Src("cameo", cameo_ex, shas[id(cameo_ex)]) if cameo_ex else None

    cameo_vals = _cameo_fields(cameo, cam_src) if cameo else {}
    mw = cameo_vals.pop("molecular_weight_g_mol", None)
    if mw is None and _found(props_ex):
        table = (props_ex.body.get("PropertyTable") or {}).get("Properties") or [{}]
        mwt = table[0].get("MolecularWeight")
        if mwt is not None:
            mw = _held(
                float(mwt),
                "g/mol",
                props_src,
                f"MolecularWeight: {mwt} (computed by PubChem)",
                as_printed=str(mwt),
            )
    mw_plain = (
        _plain(mw)
        if mw
        else {
            "value": None,
            "unit": "g/mol",
            "status": "not_held",
            "reason": "neither CAMEO Chemicals nor PubChem gives one",
            "receipt": None,
            "derived_from": [],
        }
    )
    tb_cameo = (cameo_vals.get("normal_boiling_point_k") or {}).get("value")
    pub_vals: dict[str, dict] = {}
    bp, bp_printed = _pubchem_boiling_point(rows, pub_src)
    checks = []
    if tb_cameo is not None and bp_printed:
        checks.append(
            boiling_point_check(cameo_vals["normal_boiling_point_k"], bp, bp_printed)
        )
    if bp:
        bp.pop("_precision_k", None)
        pub_vals["normal_boiling_point_k"] = bp
    tb = tb_cameo or (bp or {}).get("value")
    hv = _pubchem_heat_of_vaporization(rows, pub_src, tb)
    if hv:
        pub_vals["heat_of_vaporization_j_mol"] = hv
    pub_vals |= _pubchem_heat_capacities(rows, pub_src, mw_plain["value"])
    vp = _pubchem_vapour_pressure(rows, pub_src)
    if vp:
        pub_vals["vapour_pressure_as_printed"] = vp
    pub_vals |= _pubchem_critical(rows, pub_src)

    absent_why = {
        "default": (
            "neither CAMEO Chemicals nor PubChem's experimental section prints it"
            + ("" if cameo else f" (CAMEO: {cameo_why})")
        ),
        "liquid_density_kg_m3": (
            "neither source prints a liquid density in kg/m3 at a stated temperature "
            "this reads (CAMEO prints the specific gravity; PubChem's density rows do "
            "not state their basis in one form)"
        ),
        "liquid_specific_gravity": (
            "CAMEO Chemicals prints none" if cameo else f"CAMEO: {cameo_why}"
        ),
    }
    thermo = thermodynamics(cameo_vals, pub_vals, mw_plain, checks, absent_why)
    lfl = (_cameo_lfl(cameo, cam_src) if cameo else None) or _pubchem_lfl(rows, pub_src)
    cas = list(
        dict.fromkeys(
            ([ref.cas] if ref.cas else []) + (cameo or {}).get("cas", []) + pub_cas
        )
    )
    title = ""
    if _found(props_ex):
        title = ((props_ex.body.get("PropertyTable") or {}).get("Properties") or [{}])[
            0
        ].get("Title") or ""
    lookup = [n for n in (ref.name, (cameo or {}).get("name"), title) if n]
    loc, loc_notes = levels(cas, ref.un, lookup, lfl)

    used = [e for e in run.exchanges]
    at = _latest(used)
    sources = [names["cameo"]] if cameo else []
    sources.append(names["pubchem"])
    labels_by_doc = {
        cfg["sources"]["pubchem"]["doc_id"]: fetched_label(
            names["pubchem"], _latest([view_ex, props_ex])
        )
    }
    if cameo_ex:
        labels_by_doc[cfg["sources"]["cameo"]["doc_id"]] = fetched_label(
            names["cameo"], cameo_ex.recorded_at or at
        )
    rows_used = sorted({catalog.row_for_exchange(e.api, e.url)["id"] for e in used})
    horizon = min(
        (catalog.row(r) for r in rows_used), key=lambda r: (r["horizon_s"], r["id"])
    )
    record = {
        "ref": {"un": ref.un, "name": ref.name, "cas": ref.cas},
        "cid": cid,
        "identified_by": trail,
        "cameo": {"datasheets": cameo_ids, "used": bool(cameo), "why_not": cameo_why},
        "exchanges": [
            {
                "source": catalog.row_for_exchange(e.api, e.url)["id"],
                "url": e.url,
                "status": e.status,
                "retrieved_at": e.recorded_at,
                "sha256": shas[id(e)],
            }
            for e in used
        ],
        "catalog_rows": rows_used,
        "horizon_s": horizon["horizon_s"],
        "horizon_source": horizon["id"],
    }
    record_hash = _write_resolution(store, record, [shas[id(e)] for e in used], at)
    name = (cameo or {}).get("name") or ref.name or title
    entry = {
        "un": ref.un,
        "name": name,
        "cas": cas,
        "molecular_weight_g_mol": mw_plain,
        "lfl_vol_pct": lfl
        or {
            "value": None,
            "unit": "vol %",
            "status": "not_held",
            "reason": "neither CAMEO Chemicals nor PubChem prints a lower flammable "
            "limit this reads",
            "receipt": None,
            "derived_from": [],
        },
        "thermodynamics": thermo,
        "levels_of_concern": loc,
        "provenance": {
            "kind": "fetched",
            "fetched_at": at,
            "sources": sources,
            "record_hash": record_hash,
            "labels": labels_by_doc,
        },
    }
    HeldValue.model_validate(entry["molecular_weight_g_mol"])
    HeldValue.model_validate(entry["lfl_vol_pct"])
    notes = tuple([*trail, *loc_notes] + ([f"CAMEO: {cameo_why}"] if cameo_why else []))
    item = {
        "provenance": "fetched",
        "fetched_at": at,
        "source": sources[0],
        "sources": sources,
        "record_hash": record_hash,
        "horizon_s": horizon["horizon_s"],
        "notes": list(notes),
        "entry": entry,
    }
    _write_cache(cache_path, key, item)
    return _from_item(ref, item)


def with_resolved(pack_data: dict, props: Properties) -> dict:
    """The properties pack's data with `props` as `materials[un]`, so the source term
    and the dense-gas channel read a fetched entry as they read a seed one. The seed's
    own entries are never replaced."""
    if props.provenance == "held":
        return pack_data
    un = props.ref.un or props.ref.key()
    mats = dict(pack_data["materials"])
    if un in mats:
        raise ValueError(f"UN{un} is seeded; a fetched entry never replaces it")
    mats[un] = props.entry
    return {**pack_data, "materials": mats}
