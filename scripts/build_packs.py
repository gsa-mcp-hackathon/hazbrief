#!/usr/bin/env python3
"""Build the knowledge packs the server reads at runtime (HB-03; packs/SCHEMA.md).

**No model.** No network, except the `hydrography` subcommand's two probes (one GET
each, through scripts/probe_apis.py). Every value in a pack is parsed by locator from a
held corpus file (`corpus/raw/`), resolved through `squiddy_intake.py`'s join,
so the raw sha256 and the licence (`corpus/sources.yaml` `reuse:`, with the intake's
default) are the corpus's own records and never the Squiddy manifest's (HB-01c section
1).

    uv run python scripts/build_packs.py all          # every pack, into packs/
    uv run python scripts/build_packs.py erg          # one pack: erg, cfr172, cameo,
                                                      # hazard_classes, flag_rules or
                                                      # vocabulary
    uv run python scripts/build_packs.py schema       # packs/schema/ from the models
    uv run python scripts/build_packs.py report       # the cross-check table (markdown)
    uv run python scripts/build_packs.py summary      # per-pack counts (JSON)
    uv run python scripts/build_packs.py hydrography  # the two probes (network)

A build is deterministic: keys are sorted, lists are in source or sorted order, and
`built_at` is the newest source's retrieval instant (or SOURCE_DATE_EPOCH when set;
reproducible-builds.org SOURCE_DATE_EPOCH specification), never the wall clock.
Rebuilding from the same held files gives byte-identical packs (test_packs.py).

Cross-checks (DN-003 section 5): each seed's guide number, names, TIH membership, Table
1 and Table 3 values, guide title, guide section text and guide evacuation distances,
and each 172.101 row, are compared across every source that carries them
(`cross_check`). A disagreement is written `disputed` with every value; a field only one
source carries is `single_source`. Neither is dropped; both are listed in the RESULT.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import importlib.util
import json
import os
import re
import sys
import urllib.parse
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO / "src"))

import corpus_text  # noqa: E402
import pack_parsers as PP  # noqa: E402
import squiddy_intake as I  # noqa: E402

from hazbrief.models import APP_PACK_MODELS, PACK_MODELS  # noqa: E402
from hazbrief.packs import data_sha256  # noqa: E402

F = I.F  # scripts/fetch_allowlisted.py, as the intake loads it

CONFIG_KEYS = (
    "schema_version",
    "paths",
    "pack_versions",
    "seed_un_numbers",
    "erg",
    "pubchem",
    "cameo",
    "cfr",
    "hazard_classes",
    "hydrography",
    "puff",
)
KINDS = (
    "erg",
    "cfr172",
    "cameo",
    "hazard_classes",
    "flag_rules",
    "vocabulary",
    # HB-207: read by the `decision_support` prompt
    "suggested_actions",
)
#: The application's packs (HB-66): built here like the server's, read only by the
#: workbench's puff (`hazbrief.packs.load_app_pack`).
#: HB-120: `release_routing`, every ERG guide routed (DN-020 ADDENDUM-02 item 3); it
#: reads the ERG pack, so `build_packs` builds it after the others.
APP_KINDS = (
    "materials_properties",
    "sigma_curves",
    "release_scenarios",
    "release_routing",
    "siting_rules",
)
#: Attribution notices carried verbatim, per source document that has one.
NOTICE_SOURCES = ("erg2024-en-pdf", "cfr49-govinfo-bulk")


class BuildError(RuntimeError):
    """A build that must stop: bad config, a value that cannot be parsed, a failed
    check."""


# ------------------------------------------------------------------ configuration
def load_config(path: Path) -> dict:
    if not Path(path).exists():
        raise BuildError(f"config not found: {path}")
    try:
        cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise BuildError(f"{path} is not valid YAML: {exc}") from None
    missing = [k for k in CONFIG_KEYS if k not in cfg]
    if missing:
        raise BuildError(f"{path}: missing required key(s): {', '.join(missing)}")
    missing = [k for k in KINDS + APP_KINDS if k not in cfg["pack_versions"]]
    if missing:
        raise BuildError(f"{path}: pack_versions lacks {', '.join(missing)}")
    return cfg


#: The keys `packs/src/materials_properties.yaml` must carry (HB-109).
PROPERTIES_KEYS = (
    "schema",
    "reference_only_quote",
    "units",
    "correlations",
    "tables",
    "required_fields",
    "absent",
    "levels_of_concern",
    "materials",
    # HB-124: the tier vocabulary, the Fluid Systems table's columns, SLAB's unit rule.
    "source_tiers",
    "saturation_table",
    "per_kilogram",
)


def load_properties_source(path: Path) -> dict:
    """The properties pack's citations (HB-109): every thermodynamic value and level of
    concern is found on its held page from what this file names."""
    if not Path(path).exists():
        raise BuildError(f"properties source not found: {path}")
    try:
        spec = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise BuildError(f"{path} is not valid YAML: {exc}") from None
    missing = [k for k in PROPERTIES_KEYS if k not in spec]
    if missing:
        raise BuildError(f"{path}: missing required key(s): {', '.join(missing)}")
    return spec


def _is_url(value) -> bool:
    """An absolute http(s) URL with a host (RFC 3986 scheme and authority)."""
    if not isinstance(value, str):
        return False
    parts = urllib.parse.urlsplit(value)
    return parts.scheme in ("http", "https") and bool(parts.netloc)


# ------------------------------------------------------------------ time
def _instant(value: str) -> datetime:
    v = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        v += "T00:00:00+00:00"
    dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _stamp(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def built_at_from(retrieved: list) -> str:
    """SOURCE_DATE_EPOCH if set, else the newest of the sources' retrieval instants."""
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch:
        try:
            return _stamp(datetime.fromtimestamp(int(epoch), timezone.utc))
        except ValueError:
            raise BuildError(f"SOURCE_DATE_EPOCH={epoch!r} is not an integer") from None
    if not retrieved:
        raise BuildError("a pack with no source has no built_at")
    return _stamp(max(_instant(x) for x in retrieved))


# ------------------------------------------------------------------ the held corpus
class SourceSet:
    """Held corpus documents by doc_id, through the intake's join (one entry at a
    time)."""

    def __init__(self, cfg: dict, repo: Path = REPO):
        self.repo = Path(repo)
        corpus = self.repo / "corpus"
        self._entries = {
            s["doc_id"]: s for s in F.load_sources(corpus / "sources.yaml")
        }
        self._fetched = F.FetchLog(corpus / "fetch_log.jsonl").latest_units()
        self._downloads = I.latest_downloads(
            F.FetchLog(corpus / "operator_downloads.jsonl").rows()
        )
        self._allow = F.load_allowlist(corpus / "allowlist.txt", env={})
        self._records: dict = {}
        self._pages: dict = {}
        #: The application packs' licence gate (HB-109; `_receipt`), from the
        #: properties source; None where the config names none.
        src = (cfg.get("puff") or {}).get("properties_source")
        self.quote_gate = (
            load_properties_source(self.repo / src)["reference_only_quote"]
            if src
            else None
        )

    def record(self, doc_id: str) -> dict:
        if doc_id not in self._records:
            if doc_id not in self._entries:
                raise BuildError(f"{doc_id}: not an entry in corpus/sources.yaml")
            try:
                [rec] = I.join(
                    [self._entries[doc_id]],
                    self._fetched,
                    self._downloads,
                    self._allow,
                    self.repo,
                )
            except SystemExit as exc:  # the join's own refusal (bytes changed)
                raise BuildError(str(exc)) from None
            self._records[doc_id] = rec
        return self._records[doc_id]

    def entry(self, doc_id: str) -> dict:
        self.record(doc_id)
        return self._entries[doc_id]

    def is_held(self, doc_id: str) -> bool:
        return self.record(doc_id)["acquisition"] in I.HELD

    def path(self, doc_id: str) -> Path:
        rec = self.record(doc_id)
        if rec["acquisition"] not in I.HELD:
            raise BuildError(f"{doc_id}: not held ({rec['acquisition']})")
        if rec.get("withheld_reason") == "copyrighted":
            raise BuildError(f"{doc_id}: copyrighted; never packed (DN-002 section 4)")
        return self.repo / rec["raw_path"]

    def raw_sha256(self, doc_id: str) -> str:
        self.path(doc_id)
        return self.record(doc_id)["raw_sha256"]

    def licence(self, doc_id: str) -> str:
        """`corpus/sources.yaml` `reuse:`, or the intake's DEFAULT_LICENCE (the
        join)."""
        return self.record(doc_id)["reuse"]

    def retrieved_at(self, doc_id: str) -> str:
        return _stamp(_instant(self.record(doc_id)["retrieved_at"]))

    def pages(self, doc_id: str) -> list:
        """PDF pages, or the form-feed blocks Squiddy indexes a converted file by."""
        if doc_id not in self._pages:
            p = self.path(doc_id)
            pages = (
                corpus_text.pdf_pages(p)
                if p.suffix.lower() == ".pdf"
                else corpus_text.text_blocks(p)
            )
            if pages is None and self.entry(doc_id).get("format") == "txt":
                # HB-124: the WebBook's tab-delimited tables are served with no
                # content type, so the fetcher stored them under the URL's suffix
                # (`.cgi`); the entry declares them text, read as text is read.
                pages = corpus_text.paragraph_blocks(p.read_bytes())
            if not pages:
                raise BuildError(f"{doc_id}: no text pages")
            self._pages[doc_id] = pages
        return self._pages[doc_id]

    def page(self, doc_id: str, page: int) -> str:
        pages = self.pages(doc_id)
        if not 1 <= page <= len(pages):
            raise BuildError(f"{doc_id}: page {page} out of range 1-{len(pages)}")
        return pages[page - 1]

    def quote_on_page(self, doc_id: str, page: int, quote: str) -> bool:
        return PP.norm(quote) in PP.norm(self.page(doc_id, page))

    def between(self, doc_id: str, page: int, start: str, end: str | None) -> str:
        """The page text from `start` (inclusive) to `end` (exclusive), each anchor
        unique."""
        text = PP.norm(self.page(doc_id, page))
        s = PP.norm(start)
        if text.count(s) != 1:
            raise BuildError(
                f"{doc_id} p. {page}: start anchor {start!r} occurs "
                f"{text.count(s)} times"
            )
        i = text.index(s)
        if end is None:
            return text[i:]
        e = PP.norm(end)
        j = text.find(e, i + len(s))
        if j < 0:
            raise BuildError(f"{doc_id} p. {page}: end anchor {end!r} not after start")
        return text[i:j].strip()

    def dom(self, doc_id: str):
        return PP.dom(self.path(doc_id).read_bytes())

    def source(self, doc_id: str, locator: str) -> dict:
        return {
            "doc_id": doc_id,
            "raw_sha256": self.raw_sha256(doc_id),
            "locator": locator,
            "licence": self.licence(doc_id),
        }

    def credit_url(self, doc_id: str) -> str:
        """The URL a credit names. An operator download registered before its URL was
        found records `source_url: unresolved` with the basis "corpus/sources.yaml url";
        by that basis the URL is the entry's, once the entry holds one (HB-62 found the
        five ERG2020 data files'; HB-95, review L5-8). Anything else that is not an
        http(s) URL is refused: a credit that names no URL is no credit."""
        rec = self.record(doc_id)
        url = rec.get("url")
        if not _is_url(url) and rec.get("url_basis") == "corpus/sources.yaml url":
            url = self.entry(doc_id).get("url")
        if not _is_url(url):
            raise BuildError(
                f"{doc_id}: the credit's url is {url!r}, not an http(s) URL; hold the "
                "document's URL in corpus/sources.yaml `url`"
            )
        return url

    def credit(self, doc_id: str) -> dict:
        e = self.entry(doc_id)
        return {
            "doc_id": doc_id,
            "title": e.get("title") or doc_id,
            "publisher": e.get("publisher") or "",
            "edition": str(e["edition"]) if e.get("edition") is not None else None,
            "url": self.credit_url(doc_id),
        }


# ------------------------------------------------------------------ cross-checks
def cross_check(field: str, values: dict) -> dict:
    """Compare one field across sources. `values`: source role -> printed value or
    None."""
    carried = {k: PP.compare_form(v) for k, v in values.items() if v is not None}
    if len(carried) < 2:
        status = "single_source"
    elif len(set(carried.values())) == 1:
        status = "agree"
    else:
        status = "disputed"
    return {"field": field, "values": dict(sorted(values.items())), "status": status}


def cross_checked_entries(data: dict):
    """(key, entry) for every pack entry that carries `cross_checks` (erg and
    cfr172)."""
    for un, m in sorted((data.get("materials") or {}).items()):
        if "cross_checks" in m:
            yield f"UN{un}", m
    for g, guide in sorted((data.get("guides") or {}).items()):
        yield f"guide {g}", guide
    if "table3_cross_checks" in data:
        yield "table3_wind_bands", {"cross_checks": data["table3_cross_checks"]}


def _mi(d: dict) -> str:
    """The miles value as ERG and CAMEO print it: one decimal, '+' kept."""
    return f"{d['mi']:.1f}{'+' if d['plus'] else ''} mi"


def _text_digest(items: list) -> str:
    text = PP.compare_form(" ".join(i["text"] for i in items))
    return (
        f"sha256:{hashlib.sha256(text.encode()).hexdigest()[:16]} ({len(text)} chars)"
    )


def _names(names: list) -> str:
    return " | ".join(sorted(PP.norm(n) for n in names))


# ------------------------------------------------------------------ attribution
def _notice(sources: SourceSet, cfg: dict, key: str) -> dict:
    if key == "erg2024-en-pdf":
        rn = cfg["erg"]["reuse_notice"]
        text = sources.between(key, rn["page"], rn["start"], None)
        return {"doc_id": key, "locator": f"{key}#p{rn['page']}", "text": text}
    if key == "cfr49-govinfo-bulk":
        text = PP.cfr_notice(sources.path(key), cfg["cfr"]["reuse_notice_contains"])
        return {"doc_id": key, "locator": f"{key}#OENOTICE", "text": text}
    raise BuildError(f"no notice reader for {key}")


def attribution(sources: SourceSet, cfg: dict, doc_ids: list, extra: list = ()) -> dict:
    notices = [
        _notice(sources, cfg, d) for d in sorted(set(doc_ids)) if d in NOTICE_SOURCES
    ]
    return {
        "credits": [sources.credit(d) for d in sorted(set(doc_ids))],
        "notices": sorted(
            notices + list(extra), key=lambda n: (n["doc_id"], n["locator"])
        ),
    }


def envelope(
    kind: str, cfg: dict, sources: SourceSet, src: list, attr: dict, data
) -> dict:
    src = sorted(src, key=lambda s: s["doc_id"])
    pack = {
        "schema_version": cfg["schema_version"],
        "pack_id": kind,
        "kind": kind,
        "version": cfg["pack_versions"][kind],
        "built_at": built_at_from([sources.retrieved_at(s["doc_id"]) for s in src]),
        "sources": src,
        "attribution": attr,
        "data": data,
    }
    model = {**PACK_MODELS, **APP_PACK_MODELS}[kind].model_validate(
        {**pack, "sha256": "0" * 64}
    )
    dumped = model.model_dump(mode="json")
    dumped["sha256"] = data_sha256(dumped["data"])
    return dumped


# ------------------------------------------------------------------ erg
def _keying(r: dict) -> dict:
    return {
        "keyed_by": r["keyed_by"],
        "adjudicated": r["adjudicated"],
        "unresolved": r["unresolved"],
        "unresolved_fields": r["unresolved_fields"],
    }


def load_keyed(cfg: dict, repo: Path = REPO) -> dict:
    """The adjudicated rows of HB-03b's triple keying (`scripts/erg_join.py
    adjudicate`), by table, and their meta (guide titles and pages, the Table 2 legend).
    The build refuses to run without them: the any-UN pack is built only from keyed
    rows."""
    kcfg = yaml.safe_load(
        (repo / cfg["erg"]["keys_config"]).read_text(encoding="utf-8")
    )
    d = repo / kcfg["paths"]["adjudicated_dir"]
    if not (d / "meta.json").exists():
        raise BuildError(
            f"{d}: no adjudicated rows; run scripts/erg_keya.py, erg_keyc.py, "
            "erg_join.py join, erg_keyb.py, erg_join.py adjudicate (HB-03b)"
        )
    out = {
        t: [
            json.loads(x)
            for x in (d / f"{t}.jsonl").read_text("utf-8").splitlines()
            if x
        ]
        for t in ("yellow", "blue", "table1", "table2", "table3", "guides")
    }
    out["meta"] = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    out["config"] = kcfg
    return out


_GUIDE_KINDS = ("heading", "bullet", "text")


def _erg_guide(
    sources, cfg, guide: str, keyed: dict, cameo_guide_ok: bool, others: list
) -> dict:
    """One orange guide from its adjudicated items (every guide), with DN-003 section
    5's cross-checks against CAMEO's copy where it is held (the seed guides)."""
    e = cfg["erg"]
    doc = e["doc_id"]
    heads = e["guide_sections"]
    gmeta = keyed["meta"]["guides"][guide]
    left_p, right_p = gmeta["pages"]
    page_of = {
        "potential_hazards": left_p,
        "public_safety": left_p,
        "emergency_response": right_p,
    }
    by_heading = {h: k for k, h in heads.items()}
    secs: dict = {k: [] for k in heads}
    for r in keyed["guides"]:
        if r["guide"] != guide or r["kind"] == "section":
            continue
        k = by_heading.get(r["section"])
        if k is None:
            raise BuildError(f"guide {guide}: item in unknown section {r['section']!r}")
        secs[k].append(
            {
                "kind": r["kind"] if r["kind"] in _GUIDE_KINDS else "text",
                "text": r["text"],
                **_keying(r),
            }
        )
    for k in heads:
        if not secs[k]:
            raise BuildError(f"guide {guide}: no items in {heads[k]}")
    title = gmeta["title"]
    try:
        evac = PP.evacuation_from_text(
            PP.evacuation_items_text(
                [
                    {"kind": i["kind"], "text": i["text"] or ""}
                    for i in secs["public_safety"]
                ]
            )
        )
    except PP.ParseError:
        evac = {
            "immediate_precautionary": None,
            "immediate_precautionary_solids": None,
            "large_spill_downwind": None,
            "large_spill_all_directions": None,
            "fire_isolate": None,
            "fire_evacuate": None,
            "spill_refers_to_table1": False,
        }
    checks = []
    if cameo_guide_ok:
        trail = e["guide_trailer_patterns"]
        cdoc = f"{cfg['cameo']['guide_doc_prefix']}{guide}"
        cp = sources.pages(cdoc)
        c_title = PP.cameo_guide_title(cp[0], guide, heads["potential_hazards"])
        cl = PP.guide_items(cp[0], heads["potential_hazards"], [], trail)
        cr = PP.guide_items(cp[1], heads["emergency_response"], [], trail)
        c_secs = PP.guide_sections(cl, cr, heads)
        c_evac = PP.evacuation_from_text(
            PP.evacuation_items_text(c_secs["public_safety"])
        )
        unna_titles = {k: v for k, v in others if k.startswith("cameo_unna")}
        checks.append(
            cross_check(
                "title", {"erg_pdf": title, "cameo_guide_pdf": c_title, **unna_titles}
            )
        )
        for key in heads:
            checks.append(
                cross_check(
                    f"sections.{key}",
                    {
                        "erg_pdf": _text_digest(
                            [{"text": i["text"] or ""} for i in secs[key]]
                        ),
                        "cameo_guide_pdf": _text_digest(c_secs[key]),
                    },
                )
            )
        sheet_evac = {k: v for k, v in others if k.startswith("cameo_datasheet")}
        for f in ("immediate_precautionary", "large_spill_downwind", "fire_isolate"):

            def show(d):
                return (
                    None
                    if d is None or d.get(f) is None
                    else f"{d[f]['m']} m ({d[f]['imperial']})"
                )

            vals = {"erg_pdf": show(evac), "cameo_guide_pdf": show(c_evac)}
            for role, ev in sheet_evac.items():
                vals[role] = show(ev)
            if evac.get(f) is None and all(v is None for v in vals.values()):
                continue
            checks.append(cross_check(f"evacuation.{f}", vals))
    return {
        "guide": guide,
        "title": title,
        "title_keyed_by": gmeta["title_keyed_by"],
        "sections": {
            k: {
                "heading": heads[k],
                "locator": f"{doc}#p{page_of[k]}",
                "items": secs[k],
            }
            for k in heads
        },
        "evacuation": evac,
        "cross_checks": checks,
        "disputed": any(c["status"] == "disputed" for c in checks),
    }


def _table1_entry(r: dict, doc: str) -> dict:
    printed = r["printed_name"]
    name, qual = PP_split_qualifier(printed) if printed is not None else (None, None)
    return {
        "name": name if name is not None else "",
        "printed_name": printed if printed is not None else "",
        "guide": r["guide"],
        "spilled_in": {
            "when spilled in water": "water",
            "when spilled on land": "land",
        }.get(qual),
        "water_reactive_note": f"({qual})" if qual else None,
        "small": r["small"],
        "large": r["large"],
        "large_refer_to_table3": r["large_refer_to_table3"],
        "locator": f"{doc}#p{r['page']}",
        **_keying(r),
    }


def PP_split_qualifier(printed: str) -> tuple:
    """A printed Table 1 name and its spill-surface qualifier (ERG p. 30 Note 1), by the
    same rule Key A applies (`erg_keya.split_qualifier`)."""
    m = re.search(r"\s*\((when spilled (?:in water|on land))\)\s*$", printed, re.I)
    if not m:
        return PP.norm(printed), None
    return PP.norm(printed[: m.start()]), m.group(1).lower()


def build_erg(cfg: dict, sources: SourceSet) -> dict:
    """The any-UN ERG pack (HB-03b): every ID number in the yellow index, its Table 1,
    Table 2 and Table 3 rows, and every orange guide, from the adjudicated triple-keyed
    rows; the seed materials and guides keep HB-03's cross-checks against PubChem and
    CAMEO (DN-003 section 5)."""
    e = cfg["erg"]
    doc = e["doc_id"]
    seeds = list(cfg["seed_un_numbers"])
    keyed = load_keyed(cfg)
    kp = keyed["config"]["keya"]["pages"]
    # HB-03c: the cells whose printed US-unit value disagrees with the metric value
    sys.path.insert(0, str(REPO / "scripts"))
    import erg_units

    notes = erg_units.annotations(erg_units.audit())

    def noted(table: str, un: str, row: str, path: str, cell: dict) -> dict:
        note = notes.get((table, un, row, path))
        return {**cell, "unit_note": note} if note else cell

    pages = sources.pages(doc)

    index: dict = {}
    for r in keyed["yellow"]:
        if r["id"] == "—":
            continue  # no ID number: explosives by division (p. 30 Note 2)
        index.setdefault(r["id"], []).append(r)
    t1: dict = {}
    for r in keyed["table1"]:
        t1.setdefault(r["id"], []).append(r)
    t2: dict = {}
    for r in keyed["table2"]:
        t2.setdefault(r["id"], []).append(r)
    t3: dict = {}
    for r in keyed["table3"]:
        # a block heads one or two ID numbers (UN1050 and UN2186 share theirs)
        for u in r.get("uns") or [r["un"]]:
            t3.setdefault(u, []).append(r)
    table1_ids = {un: min(x["page"] for x in rows) for un, rows in t1.items()}

    pub_doc = cfg["pubchem"]["doc_id"]
    every_id = {f"{i:04d}" for i in range(10000)}
    pubchem_all = PP.pubchem_index(sources.dom(pub_doc), every_id)
    _check_full_index(index, table1_ids, pubchem_all)
    bands = PP.erg_wind_bands(pages[kp["table3"][0] - 1], kp["table3"][0])
    src = [
        sources.source(doc, _erg_locator(kp, e)),
        sources.source(pub_doc, "UN index rows"),
    ]
    for d in (
        keyed["config"]["keyc"][t]
        for t in ("yellow", "table1", "table2", "table3", "guides")
    ):
        src.append(sources.source(d, "HB-03b Key C (ERG2020; corroboration only)"))
    cameo_unna, sheets = {}, {}
    for un in seeds:
        d = f"{cfg['cameo']['unna_doc_prefix']}{un}"
        cameo_unna[un] = PP.cameo_unna(sources.dom(d))
        src.append(sources.source(d, "ERG section: names, guide, Table 1, Table 3"))
    for d in cfg["cameo"]["chemical_doc_ids"]:
        sheet = PP.cameo_datasheet(sources.dom(d), ["Isolation and Evacuation"])
        paras = sheet["sections"][0]["paragraphs"]
        m = re.search(r"Excerpt from ERG Guide (\d{3}P?)", " ".join(paras))
        if m:
            sheets.setdefault(m.group(1), []).append(
                (f"cameo_datasheet({d})", PP.evacuation_from_text(" ".join(paras)))
            )
            src.append(sources.source(d, "Isolation and Evacuation"))
    for un in seeds:
        if un not in index:
            raise BuildError(f"UN{un}: not in the ERG yellow index")

    materials, name_index = {}, {}
    for un, rows in sorted(index.items()):
        guides_ = {r["guide"] for r in rows if r["guide"]}
        guide = next(iter(guides_)) if len(guides_) == 1 else None
        entries = [_table1_entry(r, doc) for r in t1.get(un, [])]
        for e, r in zip(entries, t1.get(un, [])):
            for size in ("small", "large"):
                if e[size]:
                    e[size] = {
                        k: noted("table1", un, r["printed_name"], f"{size}.{k}", v)
                        for k, v in e[size].items()
                    }
        t3rows = t3.get(un)
        checks: list = []
        if un in seeds:
            if guide is None:
                raise BuildError(f"UN{un}: yellow index lists guides {sorted(guides_)}")
            c = cameo_unna[un]
            pc = pubchem_all.get(un, [])
            checks = [
                cross_check("guide", {
                    "erg_pdf": guide,
                    "pubchem_index": _one(
                        {r["guide"] for r in pc}, f"UN{un} PubChem guide"
                    ),
                    "cameo_unna": c["guide"],
                }),
                cross_check("names", {
                    "erg_pdf": _names([r["name"] for r in rows]),
                    "pubchem_index": _names([r["name"] for r in pc]) if pc else None,
                    "cameo_unna": _names(c["names"]),
                }),
                cross_check("tih", {
                    "erg_pdf": "yes" if entries else "no",
                    "pubchem_index": ("yes" if any(r["green"] for r in pc) else "no")
                    if pc else None,
                    "cameo_unna": "yes" if c["table1"] else "no",
                }),
            ]  # fmt: skip
            checks += _table1_checks(
                un,
                [{**x, "name": x["printed_name"]} for x in entries if x["small"]],
                c["table1"] or [],
            )
            if t3rows or c["table3"]:
                checks += _table3_checks(
                    un, {"rows": t3rows} if t3rows else None, c["table3"]
                )
        materials[un] = {
            "un": un,
            "names": [
                {"name": r["name"], "locator": f"{doc}#p{r['page']}"} for r in rows
            ],
            "guide": guide,
            "tih": bool(entries),
            "table1": entries,
            "table2": [
                {
                    "name": r["name"],
                    "guide": r["guide"],
                    "gases": r["gases"],
                    "locator": f"{doc}#p{r['page']}",
                    **_keying(r),
                }
                for r in t2[un]
            ]
            if un in t2
            else None,
            "where_spilled_matters": un in t2,
            "table3": {
                "heading": t3rows[0]["heading"],
                "locator": f"{doc}#p{t3rows[0]['page']}",
                "rows": [
                    {
                        "container": r["container"],
                        "isolate": noted(
                            "table3", un, r["container"], "isolate", r["isolate"]
                        ),
                        **{
                            p: {
                                b: noted("table3", un, r["container"], f"{p}.{b}", v)
                                for b, v in r[p].items()
                            }
                            for p in ("day", "night")
                        },
                        **_keying(r),
                    }  # fmt: skip
                    for r in t3rows
                ],
            }
            if t3rows
            else None,
            "cross_checks": checks,
            "disputed": any(x["status"] == "disputed" for x in checks),
        }

    guides = {}
    printed = {r["guide"] for r in keyed["guides"]}
    used = {n["guide"] for rows in index.values() for n in rows if n["guide"]}
    for g in sorted(keyed["meta"]["guides"]):
        if g not in printed:
            # Guides 121 and 167 print "Intentionally left blank" and "There are no
            # materials that refer to this guide": nothing to pack, and no name may use
            # them.
            if g in used or f"{g}P" in used:
                raise BuildError(f"guide {g}: prints no text, yet a material uses it")
            continue
        cdoc = f"{cfg['cameo']['guide_doc_prefix']}{g}"
        held = g in {materials[un]["guide"] for un in seeds} and sources.is_held(cdoc)
        if held:
            src.append(sources.source(cdoc, "guide pages 1-2"))
        titles = [
            (f"cameo_unna({un})", cameo_unna[un]["guide_title"])
            for un in seeds
            if materials[un]["guide"] == g
        ]
        guides[g] = _erg_guide(sources, cfg, g, keyed, held, titles + sheets.get(g, []))

    cameo_bands = None
    for un in seeds:
        if cameo_unna[un]["table3"]:
            cameo_bands = cameo_unna[un]["table3"]["wind"][:3]
            break
    band_checks = []
    for i, b in enumerate(bands):
        mph = re.sub(r"\s+", "", b["printed"].split("=")[0])
        cam = None
        if cameo_bands:
            mm = re.search(r"\(([^)]*)\)", cameo_bands[i])
            cam = re.sub(r"\s+", "", mm.group(1)) if mm else None
        band_checks.append(
            cross_check(f"{b['band']}.mph", {"erg_pdf": mph, "cameo_unna": cam})
        )
        band_checks.append(
            cross_check(
                f"{b['band']}.kmh",
                {
                    "erg_pdf": re.sub(r"\s+", "", b["printed"].split("=")[1]),
                    "cameo_unna": None,
                },
            )
        )
    full_index = {}
    for un, rows in sorted(index.items()):
        full_index[un] = {
            "un": un,
            "names": [
                {
                    "name": r["name"],
                    "guide": r["guide"],
                    "locator": f"{doc}#p{r['page']}",
                    **_keying(r),
                }
                for r in rows
            ],
            "in_table1": un in table1_ids,
            "table1_locator": f"{doc}#p{table1_ids[un]}" if un in table1_ids else None,
        }
        for r in rows:
            name_index.setdefault(r["name"].lower(), set()).add(un)
    legend_page = kp["table2"][0]
    data = {
        "seed_un_numbers": seeds,
        "materials": materials,
        "guides": guides,
        "index": full_index,
        "name_index": {k: sorted(v) for k, v in sorted(name_index.items())},
        "table3_wind_bands": [
            {k: v for k, v in b.items() if k not in ("printed", "page")}
            | {"locator": f"{doc}#p{b['page']}"}
            for b in bands
        ],
        "table3_cross_checks": band_checks,
        "table2_legend": [
            {"symbol": sym, "name": name, "locator": f"{doc}#p{legend_page}"}
            for sym, name in (keyed["meta"]["table2_legend"] or [])
        ],
    }
    # HB-15: the placard table, admitted only where Key A and Key B agree
    import erg_placards

    kb = yaml.safe_load(
        (REPO / cfg["erg"]["placards_key_b"]).read_text(encoding="utf-8")
    )
    try:
        rows, _ = erg_placards.key(sources.path(doc), kb)
    except erg_placards.KeyingError as exc:
        raise BuildError(f"placard table: {exc}") from None
    for r in rows:
        if r["guide"] not in guides:
            raise BuildError(f"placard {r['placard']}: guide {r['guide']} not packed")
    data["placards"] = rows
    data["unnumbered"] = _unnumbered(cfg, sources, keyed, guides, doc)
    prose = sorted({p["prose"]["page"] for p in kb["placards"] if p.get("prose")})
    src[0]["locator"] += (
        f"; placards pp. {', '.join(str(p) for p in kb['pages'])}"
        f" (prose pp. {', '.join(str(p) for p in prose)})"
    )
    docs = [s["doc_id"] for s in src]
    return envelope(
        "erg", cfg, sources, _dedupe(src), attribution(sources, cfg, docs), data
    )


def _unnumbered(cfg, sources, keyed, guides, doc) -> list:
    """HB-17: the yellow-index rows with no ID number (the explosives, p. 31), each with
    the p. 30 note that says why and the aliases a held source prints. Refuses a row
    whose guide is not packed or whose name is also a numbered name, a note not on its
    page, and an alias quote not in its CFR section."""
    e = cfg["erg"]
    note = e["unnumbered_note"]
    if not sources.quote_on_page(doc, note["page"], note["quote"]):
        raise BuildError(f"unnumbered note not on p. {note['page']}: {note['quote']!r}")
    numbered = {r["name"].lower() for r in keyed["yellow"] if r["id"] != "—"}
    out = []
    for r in keyed["yellow"]:
        if r["id"] != "—":
            continue
        if r["guide"] not in guides:
            raise BuildError(f"unnumbered {r['name']!r}: guide {r['guide']} not packed")
        if r["name"].lower() in numbered:
            raise BuildError(f"unnumbered {r['name']!r} is also a numbered name")
        out.append(
            {
                "name": r["name"],
                "guide": r["guide"],
                "locator": f"{doc}#p{r['page']}",
                "note": {
                    "quote": note["quote"],
                    "locator": f"{doc}#p{note['page']}",
                },
                "aliases": [],
                **_keying(r),
            }
        )
    by_name = {r["name"]: r for r in out}
    for a in e["unnumbered_aliases"]:
        row = by_name.get(a["name"])
        if row is None:
            raise BuildError(f"alias {a['alias']!r}: no unnumbered row {a['name']!r}")
        text = PP.cfr_section_text(sources.path(a["doc_id"]), a["section"])
        if a["quote"] not in text:
            raise BuildError(
                f"alias {a['alias']!r}: {a['quote']!r} is not in {a['doc_id']} "
                f"section {a['section']}"
            )
        row["aliases"].append(
            {
                "alias": a["alias"],
                "quote": a["quote"],
                "locator": f"{a['doc_id']}#{a['section']}",
            }
        )
    return out


def _check_full_index(index: dict, table1_ids: dict, pubchem: dict) -> None:
    """The whole-index cross-checks (schema version 2). The ERG PDF's yellow index and
    PubChem's ERG 2024 index list the same ID numbers, and every ID PubChem highlights
    as Table 1 is an ID the ERG PDF's Table 1 lists. The converse does not hold and is
    not required: Table 1 also lists water-reactive materials "(when spilled in water)"
    (ERG 2024 PDF p. 30, printed p. 28, Note 1), which PubChem's highlight does not
    mark."""
    if set(index) != set(pubchem):
        only_pdf = sorted(set(index) - set(pubchem))[:10]
        only_pc = sorted(set(pubchem) - set(index))[:10]
        raise BuildError(
            f"yellow index ID numbers differ from PubChem's: ERG PDF only {only_pdf}, "
            f"PubChem only {only_pc}"
        )
    missing = set(table1_ids) - set(index)
    if missing:
        raise BuildError(f"Table 1 IDs not in the yellow index: {sorted(missing)[:10]}")
    green = {un for un, rows in pubchem.items() if any(r["green"] for r in rows)}
    if not green <= set(table1_ids):
        raise BuildError(
            f"PubChem highlights IDs Table 1 does not list: "
            f"{sorted(green - set(table1_ids))[:10]}"
        )


def _erg_locator(kp: dict, e: dict) -> str:
    """The pages the any-UN pack reads (packs/src/erg_keys.yaml `keya.pages`)."""
    name = {"yellow": "yellow index", "blue": "blue index", "guides": "orange guides",
            "table1": "Table 1", "table2": "Table 2", "table3": "Table 3"}  # fmt: skip
    return (
        "; ".join(f"{name[t]} pp. {a}-{b}" for t, (a, b) in kp.items())
        + f"; reuse p. {e['reuse_notice']['page']}"
    )


def _one(values: set, what: str):
    if not values:
        return None
    if len(values) != 1:
        raise BuildError(f"{what}: more than one value {sorted(values)}")
    return next(iter(values))


def _dedupe(src: list) -> list:
    seen, out = set(), []
    for s in src:
        if s["doc_id"] not in seen:
            seen.add(s["doc_id"])
            out.append(s)
    return out


def _table1_checks(un: str, pdf: list, cameo: list) -> list:
    by_name = {PP.norm(r[0]): r for r in cameo}
    out = []
    for r in pdf:
        c = by_name.get(r["name"])
        f = f"table1[{r['name']}]"
        s = r["small"]
        out += [
            cross_check(
                f"{f}.small.isolate",
                {
                    "erg_pdf": f"{s['isolate']['ft']} ft",
                    "cameo_unna": c[1] if c else None,
                },
            ),
            cross_check(
                f"{f}.small.protect_day",
                {"erg_pdf": _mi(s["protect_day"]), "cameo_unna": c[2] if c else None},
            ),
            cross_check(
                f"{f}.small.protect_night",
                {"erg_pdf": _mi(s["protect_night"]), "cameo_unna": c[3] if c else None},
            ),
        ]
        if r["large"] is None:
            out.append(
                cross_check(
                    f"{f}.large",
                    {
                        "erg_pdf": "Refer to Table 3",
                        "cameo_unna": c[4] if c and len(c) == 5 else None,
                    },
                )
            )
        else:
            lg = r["large"]
            for i, (k, v) in enumerate(
                (
                    ("isolate", f"{lg['isolate']['ft']} ft"),
                    ("protect_day", _mi(lg["protect_day"])),
                    ("protect_night", _mi(lg["protect_night"])),
                )
            ):
                cv = c[4 + i] if c and len(c) == 7 else None
                out.append(
                    cross_check(f"{f}.large.{k}", {"erg_pdf": v, "cameo_unna": cv})
                )
    if pdf or cameo:
        out.append(
            cross_check(
                "table1.names",
                {
                    "erg_pdf": _names([r["name"] for r in pdf]) if pdf else None,
                    "cameo_unna": _names([r[0] for r in cameo]) if cameo else None,
                },
            )
        )
    return out


def _table3_checks(un: str, pdf: dict | None, cameo: dict | None) -> list:
    out = [
        cross_check(
            "table3.containers",
            {
                "erg_pdf": _names([r["container"] for r in pdf["rows"]])
                if pdf
                else None,
                "cameo_unna": _names([r[0] for r in cameo["rows"]]) if cameo else None,
            },
        )
    ]
    if not pdf:
        return out
    by_c = {PP.norm(r[0]): r for r in (cameo["rows"] if cameo else [])}
    for r in pdf["rows"]:
        c = by_c.get(r["container"])
        f = f"table3[{r['container']}]"
        out.append(
            cross_check(
                f"{f}.isolate",
                {
                    "erg_pdf": f"{r['isolate']['ft']} ft",
                    "cameo_unna": c[1] if c else None,
                },
            )
        )
        for i, (period, band) in enumerate(
            [(p, b) for p in ("day", "night") for b in PP.BANDS]
        ):
            out.append(
                cross_check(
                    f"{f}.{period}.{band}",
                    {
                        "erg_pdf": _mi(r[period][band]),
                        "cameo_unna": c[2 + i] if c else None,
                    },
                )
            )
    return out


# ------------------------------------------------------------------ cfr172
def build_cfr172(cfg: dict, sources: SourceSet) -> dict:
    c = cfg["cfr"]
    doc = c["doc_id"]
    seeds = list(cfg["seed_un_numbers"])
    ids = {f"{c['identification_prefix']}{un}": un for un in seeds}
    section = c["section"].replace("§ ", "")
    parsed = PP.cfr_hazmat_rows(
        sources.path(doc), c["section"], c["table_columns"], set(ids)
    )
    src = [sources.source(doc, f"{c['section']} Hazardous Materials Table")]
    materials = {}
    for ident, un in ids.items():
        rows = parsed["rows"].get(ident)
        if not rows:
            raise BuildError(f"{ident}: no row in {c['section']}")
        d = f"{cfg['cameo']['unna_doc_prefix']}{un}"
        cameo = PP.cameo_unna(sources.dom(d))["hazmat"]
        src.append(sources.source(d, "Hazmat Table (49 CFR 172.101)"))
        out_rows, checks = [], []

        def key(desc, cls):
            return f"{PP.compare_form(desc)} [{cls}]"

        cam = {key(r[1], r[2]): r for r in cameo if len(r) >= 4}
        checks.append(
            cross_check(
                "rows",
                {
                    "cfr_xml": " | ".join(
                        sorted(key(r["description"], r["hazard_class"]) for r in rows)
                    ),
                    "cameo_unna": " | ".join(sorted(cam)) if cam else None,
                },
            )
        )
        for r in rows:
            k = key(r["description"], r["hazard_class"])
            cr = cam.get(k)
            label = f"rows[{r['description']} | {r['symbols'] or '-'}]"
            checks.append(
                cross_check(
                    f"{label}.label_codes",
                    {"cfr_xml": r["label_codes"], "cameo_unna": cr[3] if cr else None},
                )
            )
            out_rows.append(
                {
                    "symbols": r["symbols"],
                    "description": r["description"],
                    "roman_segments": r["roman_segments"],
                    "hazard_class": r["hazard_class"],
                    "identification_number": r["identification_number"],
                    "packing_group": r["packing_group"] or None,
                    "label_codes": _split(r["label_codes"]),
                    "special_provisions": _split(r["special_provisions"]),
                    "locator": f"{doc}#{section}:table{r['table']}:row{r['row']}",
                }
            )
        materials[un] = {
            "un": un,
            "rows": out_rows,
            "cross_checks": checks,
            "disputed": any(x["status"] == "disputed" for x in checks),
        }
    data = {
        "edition": parsed["edition"],
        "columns": c["table_columns"],
        "materials": materials,
    }
    docs = [s["doc_id"] for s in src]
    return envelope(
        "cfr172", cfg, sources, _dedupe(src), attribution(sources, cfg, docs), data
    )


def _split(cell: str) -> list:
    return [x.strip() for x in (cell or "").split(",") if x.strip()]


# ------------------------------------------------------------------ cameo
def build_cameo(cfg: dict, sources: SourceSet) -> dict:
    cc = cfg["cameo"]
    seeds = list(cfg["seed_un_numbers"])
    src, sheets = [], []
    for d in cc["chemical_doc_ids"]:
        s = PP.cameo_datasheet(sources.dom(d), cc["response_sections"])
        sheets.append((d, s))
        src.append(
            sources.source(
                d, "Response Recommendations: " + "; ".join(cc["response_sections"])
            )
        )
    materials, owner = {}, None
    for un in seeds:
        d = f"{cc['unna_doc_prefix']}{un}"
        page = PP.cameo_unna(sources.dom(d))
        owner = owner or (d, page["owner"])
        src.append(sources.source(d, "UN/NA datasheet"))
        mine = [
            {
                "doc_id": doc,
                "raw_sha256": sources.raw_sha256(doc),
                "title": s["title"],
                "un_numbers": s["un_numbers"],
                "locator": f"{doc}#Response Recommendations",
                "sections": s["sections"],
            }
            for doc, s in sheets
            if un in s["un_numbers"]
        ]
        if not mine:
            raise BuildError(f"UN{un}: no held CAMEO datasheet lists it")
        materials[un] = {
            "un": un,
            "unna_page": {
                "doc_id": d,
                "raw_sha256": sources.raw_sha256(d),
                "locator": f"{d}#ERG",
            },
            "datasheets": mine,
        }
    extra = []
    if owner and owner[1]:
        extra.append(
            {"doc_id": owner[0], "locator": f"{owner[0]}#footer", "text": owner[1]}
        )
    data = {"response_sections": list(cc["response_sections"]), "materials": materials}
    docs = [s["doc_id"] for s in src]
    return envelope(
        "cameo",
        cfg,
        sources,
        _dedupe(src),
        attribution(sources, cfg, docs, extra),
        data,
    )


# ------------------------------------------------------------------ hazard classes
def build_hazard_classes(cfg: dict, sources: SourceSet, erg: dict, cfr: dict) -> dict:
    seeds = list(cfg["seed_un_numbers"])
    members = {c["class_id"]: [] for c in cfg["hazard_classes"]}
    for un in seeds:
        m, rows = erg["data"]["materials"][un], cfr["data"]["materials"][un]["rows"]
        for c in cfg["hazard_classes"]:
            if _meets(c["criteria"], m, rows):
                members[c["class_id"]].append(un)
                break
    classes = [
        {
            "class_id": c["class_id"],
            "title": c["title"],
            "rule_set_id": c["rule_set_id"],
            "criteria": c["criteria"],
            "members": members[c["class_id"]],
            "basis": "DN-001 section 3",
        }
        for c in cfg["hazard_classes"]
    ]
    src = [
        sources.source(
            cfg["erg"]["doc_id"], "via the erg pack: Table 1 membership, names"
        ),
        sources.source(cfg["cfr"]["doc_id"], "via the cfr172 pack: hazard class"),
    ]
    docs = [s["doc_id"] for s in src]
    return envelope(
        "hazard_classes",
        cfg,
        sources,
        src,
        attribution(sources, cfg, docs),
        {"classes": classes},
    )


def _meets(criteria: dict, erg_m: dict, cfr_rows: list) -> bool:
    for k, v in criteria.items():
        if k == "erg_tih":
            ok = erg_m["tih"] is v
        elif k == "cfr_hazard_class":
            ok = any(r["hazard_class"] == v for r in cfr_rows)
        elif k == "erg_name_contains":
            ok = any(v.lower() in n["name"].lower() for n in erg_m["names"])
        else:
            raise BuildError(f"unknown hazard-class criterion {k!r}")
        if not ok:
            return False
    return True


# ------------------------------------------------------------------ flag rules
def _supplier(name: str, tool: str, fk: dict) -> str | None:
    """The tool that supplies an input today: the registry's `supplied_by` where the
    input is registered (`flag_kinds.yaml` `inputs`), else the input's own tool when
    that tool is registered."""
    reg = fk["inputs"].get(name)
    if reg is not None:
        return reg["supplied_by"]
    return tool if tool in fk["tools_registered"] else None


def _check_rule(rid: str, r: dict, known_classes: set) -> None:
    bad = set(r.get("classes") or []) - known_classes
    if bad:
        raise BuildError(f"{rid}: unknown class(es) {sorted(bad)}")
    names = {i["name"] for i in r["inputs"]} | set(r.get("params") or {})
    used = set(re.findall(r"(?<!\{)\{([a-z_]+)\}(?!\})", r["template"]))
    if used - names:
        raise BuildError(f"{rid}: template names {sorted(used - names)} not declared")
    for t in r["predicate"]["terms"]:
        refs = {t["input"], t.get("ref")} - {None}
        if refs - names or (
            t.get("param") and t["param"] not in (r.get("params") or {})
        ):
            raise BuildError(f"{rid}: predicate names an undeclared value: {t}")
    if not r.get("receipts"):
        raise BuildError(f"{rid}: no receipt")


def _flag_inputs(names: list, fk: dict, declared: dict) -> list:
    """FlagInput records for `names`: a rule's own declaration where it has one, else
    the registry's (`flag_kinds.yaml` `inputs`)."""
    out = []
    for nm in dict.fromkeys(names):
        if nm in declared:
            out.append(declared[nm])
            continue
        reg = fk["inputs"][nm]
        out.append(
            {
                "name": nm,
                "tool": reg["tool"],
                "field": reg["field"],
                "dataset": reg["dataset"],
                "description": reg["description"],
            }
        )
    return out


def _pred_inputs(pred: dict) -> list:
    names = []
    for t in pred["terms"]:
        names.append(t["input"])
        if t.get("ref"):
            names.append(t["ref"])
    return names


def _keya_statement(s: dict) -> dict:
    return {
        "doc_id": "erg2024-en-pdf",
        "page": s["page"],
        "quote": s["sentence"],
        "text_layer": "keyA",
    }


def _guide_flags(fk: dict, rat) -> dict:
    """One flag per (guide, kind) the lexical patterns find (HB-12b; DN-006 3.3-3.4):
    every hazard sentence a receipt, the first the consequence, the guide's first
    response sentence the response (else the kind's ERG table fallback; else an
    indication)."""
    out = {}
    for (g, kind), e in sorted(rat.guide_flags().items()):
        spec = fk["rationalization"][kind]
        pred = {
            "mode": "all",
            "terms": fk["predicates"][fk["kinds"][kind]["predicate"]]["terms"],
        }
        hazard = e["hazard"]
        # "Those substances designated with a (P) may polymerize explosively when heated
        # or involved in a fire" holds only for materials whose guide number carries the
        # P; a flag every receipt of which is that sentence fires only for them.
        if all(fk["p_designation_sentence"] in h["sentence"] for h in hazard):
            pred = {
                "mode": "all",
                "terms": pred["terms"]
                + [{"input": "guide_designated_p", "op": "is_true"}],
            }
        if e["response"]:
            response = _keya_statement(e["response"][0])
        elif spec.get("response_fallback"):
            fb = spec["response_fallback"]
            response = {
                "doc_id": "erg2024-en-pdf",
                "page": fb["page"],
                "quote": fb["sentence"],
                "text_layer": "pdf_text",
            }
        else:
            response = None
        rid = f"FR-G{g}-{kind.upper()}"
        out[rid] = {
            "rule_id": rid,
            "title": f"Guide {g}: {kind}",
            "kind": kind,
            "source_kind": "guide",
            "classes": [],
            "guides": [g],
            "modes": ["highway", "rail"],
            "input_names": _pred_inputs(pred),
            "declared_inputs": {},
            "params": {"guide": g},
            "predicate": pred,
            "receipts": [
                {**_keya_statement(h), "supports": f"{kind}: the guide's statement"}
                for h in hazard
            ],
            "consequence": _keya_statement(hazard[0]),
            "response": response,
            "merged": [],
            "basis": "HB-12b: lexical pattern over the guide's Key A text (DN-006)",
            "gaps": [],
        }
    return out


def absorb(predicate: dict, merged: list) -> tuple[dict, str | None]:
    """The rule's own cause, simplified by the absorption law, (A and B) or A = A: when
    a merged cause (mode all) has terms that are a subset of the own cause's (mode
    all), the own cause's other terms can never change whether the flag fires, and the
    own cause becomes that merged cause (the smallest, if several). Returns the cause
    and the merged rule id that absorbed it, or the cause unchanged and None. HB-15
    (HB-05 F-4; DN-006 section 3.4: a term that cannot change the alarm is not part of
    its cause)."""
    if predicate["mode"] != "all":
        return predicate, None

    def key(t: dict) -> str:
        return json.dumps(t, sort_keys=True)

    own = {key(t) for t in predicate["terms"]}
    subsets = [
        m
        for m in merged
        if m["predicate"]["mode"] == "all"
        and {key(t) for t in m["predicate"]["terms"]} < own
    ]
    if not subsets:
        return predicate, None
    m = min(subsets, key=lambda m: (len(m["predicate"]["terms"]), m["rule_id"]))
    return m["predicate"], m["rule_id"]


def build_flag_rules(cfg: dict, sources: SourceSet, classes: dict, erg: dict) -> dict:
    """The rationalized flag rule pack (HB-12b, schema version 5; DN-006). Every flag is
    an alarm with a cause (its predicate, and the causes merged into it), a consequence
    and a response (ERG sentences by locator), a priority (`flag_kinds.yaml` `priority`)
    and its receipts; a flag with no ERG response is an indication. HB-03's authored
    rules keep their ids unless one duplicates a guide flag's response (then it is
    merged into it); the table rules are merged into the guide flags of their kind; the
    section kinds HB-12 mined are not flags (response guidance lives in the erg pack's
    guide sections). Every receipt is re-verified: `pdf_text` on the held page's text,
    `keyA` by HB-12's admission test on the page's Key A text."""
    import importlib

    sys.path.insert(0, str(REPO / "scripts"))
    mine = importlib.import_module("mine_flag_rules")
    rat = importlib.import_module("rationalize_flags")
    fk = yaml.safe_load((REPO / cfg["paths"]["flag_kinds"]).read_text(encoding="utf-8"))
    path = REPO / cfg["paths"]["flag_rules"]
    authored = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get(
        "rules"
    ) or []
    if not authored:
        raise BuildError(f"{path}: no rules")
    table = (
        yaml.safe_load(
            (REPO / cfg["paths"]["flag_rules_table"]).read_text(encoding="utf-8")
        )
        or {}
    ).get("rules") or []
    known = {c["class_id"]: c["rule_set_id"] for c in classes["data"]["classes"]}
    keya_pages = mine.guide_pages()
    flags = _guide_flags(fk, rat)

    # Table rules: merged into the guide flag of their kind for every guide whose
    # materials the table lists; a guide without that flag gets it from the rule alone.
    mats = erg["data"]["materials"]
    for t in table:
        if "merge_into_kind" not in t:
            continue  # HB-18: a table rule that stands alone, finished below
        kind = t["merge_into_kind"]
        # the guides of the materials the table lists: Table 2 prints each row's guide;
        # a Table 3 gas takes its yellow-index guide
        if kind == "water_reactive":
            printed = [e["guide"] for m in mats.values() for e in m["table2"] or []]
        else:
            printed = [m["guide"] for m in mats.values() if m["table3"]]
        guides = sorted({g.rstrip("P") for g in printed if g})
        receipts = [{**rc, "text_layer": "pdf_text"} for rc in t["receipts"]]
        for g in guides:
            rid = f"FR-G{g}-{kind.upper()}"
            if rid not in flags:
                spec = fk["rationalization"][kind]
                fb = spec["response_fallback"]
                pred = {
                    "mode": "all",
                    "terms": [{"input": "guide_page", "op": "eq", "param": "guide"}]
                    + t["predicate"]["terms"],
                }
                flags[rid] = {
                    "rule_id": rid,
                    "title": f"Guide {g}: {kind} (from {t['rule_id']})",
                    "kind": kind,
                    "source_kind": "guide",
                    "classes": [],
                    "guides": [g],
                    "modes": list(t["modes"]),
                    "input_names": _pred_inputs(pred),
                    "declared_inputs": {i["name"]: i for i in t["inputs"]},
                    "params": {"guide": g},
                    "predicate": pred,
                    "receipts": [],
                    "consequence": {**t["consequence"], "text_layer": "pdf_text"},
                    "response": {
                        "doc_id": "erg2024-en-pdf",
                        "page": fb["page"],
                        "quote": fb["sentence"],
                        "text_layer": "pdf_text",
                    },
                    "merged": [],
                    "basis": f"HB-12b: {t['rule_id']} (ERG Table 2), no guide sentence",
                    "gaps": [],
                }
            else:
                flags[rid]["merged"].append(
                    {"rule_id": t["rule_id"], "predicate": t["predicate"]}
                )
                flags[rid]["input_names"] += _pred_inputs(t["predicate"])
                flags[rid]["declared_inputs"].update(
                    {i["name"]: i for i in t["inputs"]}
                )
            flags[rid]["receipts"] += receipts

    out, seen, pages = [], set(), {}
    rule_sets = {rs: [] for rs in known.values()}

    def finish(r: dict, origin: str, kind: str) -> dict:
        rid = r["rule_id"]
        if rid in seen:
            raise BuildError(f"duplicate rule_id {rid!r}")
        seen.add(rid)
        if kind not in fk["kinds"] or kind not in fk["priority"]:
            raise BuildError(f"{rid}: kind {kind!r} has no entry or no priority")
        statements = [*r["receipts"], r["consequence"]] + (
            [r["response"]] if r["response"] else []
        )
        for st in statements:
            if not sources.is_held(st["doc_id"]):
                raise BuildError(f"{rid}: {st['doc_id']} is not held")
            if st["text_layer"] == "keyA":
                ok, why = mine.admit_one(
                    {"guide": r["guides"][0], "page": st["page"],
                     "trigger_text": st["quote"]},
                    keya_pages,
                )  # fmt: skip
            else:
                ok = sources.quote_on_page(st["doc_id"], st["page"], st["quote"])
                why = "not on the page"
            if not ok:
                raise BuildError(
                    f"{rid}: {st['quote']!r} on {st['doc_id']} p. {st['page']}: {why}"
                )
            pages.setdefault(st["doc_id"], set()).add(st["page"])
        inputs = (
            r["inputs"]
            if "inputs" in r
            else _flag_inputs(r["input_names"], fk, r["declared_inputs"])
        )
        _check_rule(rid, {**r, "inputs": inputs, "template": r["template"]}, set(known))

        def unsupplied(pred):
            names = _pred_inputs(pred)
            tools = {i["name"]: i["tool"] for i in inputs}
            return [n for n in names if _supplier(n, tools.get(n, ""), fk) is None]

        own = unsupplied(r["predicate"])
        merged_ok = any(not unsupplied(m["predicate"]) for m in r["merged"])
        dormant_inputs = sorted(
            {
                n
                for i in inputs
                for n in [i["name"]]
                if _supplier(n, i["tool"], fk) is None
            }
        )
        return {
            "rule_id": rid,
            "title": r["title"],
            "kind": kind,
            "source_kind": origin,
            "classes": list(r.get("classes") or []),
            "guides": list(r.get("guides") or []),
            "modes": list(r["modes"]),
            "inputs": inputs,
            "params": r.get("params") or {},
            "predicate": r["predicate"],
            "template": PP.norm(r["template"]),
            "receipts": [
                {**rc, "quote": PP.norm(rc["quote"]), "text_layer": rc["text_layer"]}
                for rc in r["receipts"]
            ],
            "basis": r["basis"],
            "gaps": [PP.norm(g) for g in r.get("gaps") or []],
            "dormant": bool(own) and not merged_ok,
            "dormant_inputs": dormant_inputs,
            "consequence": {
                **r["consequence"],
                "quote": PP.norm(r["consequence"]["quote"]),
            },
            "response": {**r["response"], "quote": PP.norm(r["response"]["quote"])}
            if r["response"]
            else None,
            "priority": fk["priority"][kind],
            "indication": r["response"] is None,
            "merged": r["merged"],
        }

    # Authored rules: merged ones fold into their guide flag first.
    for a in authored:
        if a.get("merge_into"):
            target = flags.get(a["merge_into"])
            if target is None:
                raise BuildError(
                    f"{a['rule_id']}: merge target {a['merge_into']} absent"
                )
            target["merged"].append(
                {"rule_id": a["rule_id"], "predicate": a["predicate"]}
            )
            target["input_names"] += [i["name"] for i in a["inputs"]]
            target["declared_inputs"].update({i["name"]: i for i in a["inputs"]})
            target["receipts"] += [
                {**rc, "text_layer": "pdf_text"} for rc in a["receipts"]
            ]
    for a in authored:
        if a.get("merge_into"):
            continue
        kind = fk["authored_kinds"][a["rule_id"]]
        r = {
            **a,
            "receipts": [{**rc, "text_layer": "pdf_text"} for rc in a["receipts"]],
            "consequence": {**a["consequence"], "text_layer": "pdf_text"},
            "response": {**a["response"], "text_layer": "pdf_text"}
            if a["response"]
            else None,
            "merged": [],
            "guides": [],
        }
        out.append(finish(r, "authored", kind))
        for c in a["classes"]:
            rule_sets[known[c]].append(a["rule_id"])
    # HB-18: a table rule with no guide kind to merge into (FR-AMB-01, the ambiguous
    # load) is its own flag and applies to every input (`table_rule_set`).
    table_set = []
    for t in table:
        if "merge_into_kind" in t:
            continue
        r = {
            **t,
            "receipts": [{**rc, "text_layer": "pdf_text"} for rc in t["receipts"]],
            "consequence": {**t["consequence"], "text_layer": "pdf_text"},
            "response": {**t["response"], "text_layer": "pdf_text"},
            "merged": [],
            "guides": [],
            "classes": [],
        }
        out.append(finish(r, "table", t["kind"]))
        table_set.append(t["rule_id"])
    guide_sets: dict = {}
    for rid, f in sorted(flags.items()):
        simple, by = absorb(f["predicate"], f["merged"])
        if by:
            dropped = set(_pred_inputs(f["predicate"])) - set(_pred_inputs(simple))
            still = {n for m in f["merged"] for n in _pred_inputs(m["predicate"])}
            still |= set(f["declared_inputs"])
            f["input_names"] = [
                n for n in f["input_names"] if n not in dropped or n in still
            ]
            f["predicate"] = simple
            f["basis"] += f"; HB-15: own cause absorbed by {by}'s (DN-006 3.4)"
        resp = f["response"]["quote"] if f["response"] else ""
        f["template"] = (
            (f"ERG Guide {f['guides'][0]}: {f['consequence']['quote']} {resp}")
            .replace("{", "{{")
            .replace("}", "}}")
        )
        out.append(finish(f, "guide", f["kind"]))
        guide_sets.setdefault(f["guides"][0], []).append(rid)
    src = [
        sources.source(d, "receipt pages " + ", ".join(f"p{p}" for p in sorted(ps)))
        for d, ps in sorted(pages.items())
    ]
    docs = [s["doc_id"] for s in src]
    data = {
        "rules": out,
        "rule_sets": {k: sorted(v) for k, v in sorted(rule_sets.items())},
        "guide_rule_sets": {k: v for k, v in sorted(guide_sets.items())},
        "table_rule_set": table_set,
        "kinds": [
            {"kind": k, "origin": v["origin"], "description": v["description"]}
            for k, v in sorted(fk["kinds"].items())
            if k in fk["priority"]
        ],
    }
    return envelope(
        "flag_rules", cfg, sources, src, attribution(sources, cfg, docs), data
    )


# ------------------------------------------------------------------ vocabulary
def build_vocabulary(cfg: dict, sources: SourceSet, flag_rules: dict) -> dict:
    path = REPO / cfg["paths"]["vocabulary"]
    terms = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("terms") or []
    if not terms:
        raise BuildError(f"{path}: no terms")
    rules = flag_rules["data"]["rules"]
    out, pages, seen = [], {}, set()
    for t in terms:
        if t["term"].lower() in seen:
            raise BuildError(f"{path}: duplicate term {t['term']!r}")
        seen.add(t["term"].lower())
        definition = sources.between(t["doc_id"], t["page"], t["start"], t["end"])
        pattern = rf"(?<![\w-]){re.escape(t['term'])}(?![\w-])"
        used = [r["rule_id"] for r in rules if re.search(pattern, r["template"], re.I)]
        out.append(
            {
                "term": t["term"],
                "definition": definition,
                "authority": t["authority"],
                "receipt": {
                    "doc_id": t["doc_id"],
                    "page": t["page"],
                    "locator": f"{t['doc_id']}#p{t['page']}",
                },
                "used_by": sorted(set(t.get("fields") or []) | set(used)),
            }
        )
        pages.setdefault(t["doc_id"], set()).add(t["page"])
    src = [
        sources.source(d, "definition pages " + ", ".join(f"p{p}" for p in sorted(ps)))
        for d, ps in sorted(pages.items())
    ]
    docs = [s["doc_id"] for s in src]
    return envelope(
        "vocabulary", cfg, sources, src, attribution(sources, cfg, docs), {"terms": out}
    )


# ------------------------------------------------------------------ write
# ------------------------------------------------------------------ the puff's packs
# HB-66 (DN-018 sections 3 to 5): materials_properties, sigma_curves and
# release_scenarios, read by the workbench's first-order puff and never by the server
# (`hazbrief.models.APP_PACK_MODELS`). Every number is found on a held page by its
# config locator and pattern and stored beside a receipt whose quote is verified on
# that page; a value no held page states is `not_held` with the reason (HB-66 step 1).
_NUMBER = re.compile(r"^-?(?:\d{1,3}(?:,\d{3})+|\d*\.?\d+)$")
_SCI = re.compile(r"(\d*\.?\d+) x 10\^(-?\d+)")


def _number(text: str) -> float:
    t = text.strip()
    if not _NUMBER.match(t):
        raise BuildError(f"not a number as printed: {text!r}")
    return float(t.replace(",", ""))


#: A number as the NIST WebBook and CAMEO print it: "239.", "-64.639", "1,013",
#: "2.825911×10-7" (the WebBook's exponent form).
_PRINTED_NUMBER = re.compile(
    r"^[-−]?(?:\d{1,3}(?:,\d{3})+|\d+\.?\d*|\.\d+)(?:×10[-−]?\d+)?$"
)


def _printed_number(text: str) -> float:
    t = text.strip().replace("−", "-")
    if not _PRINTED_NUMBER.match(t):
        raise BuildError(f"not a number as printed: {text!r}")
    if "×10" in t:
        mant, exp = t.split("×10")
        return float(mant) * 10 ** int(exp)
    return float(t.replace(",", ""))


def licence_gate_admits(quote: str, gate: dict) -> bool:
    """The licence gate for an application pack (review L5-10; DN-020 section 2 item
    4): a quote from a `reference-only` source may carry a number with its unit, never
    a sentence. Every whitespace-separated token is a printed number, a unit or a
    separator `gate` names, and at least one is a number."""
    allowed = set(gate["units"]) | set(gate["separators"])
    tokens = PP.norm(quote).split()
    numbers = [t for t in tokens if _PRINTED_NUMBER.match(t.replace("−", "-"))]
    return bool(numbers) and all(t in allowed or t in numbers for t in tokens)


def _receipt(sources: SourceSet, doc: str, page: int, quote: str, read_by="text_layer"):
    if read_by == "text_layer" and not sources.quote_on_page(doc, page, quote):
        raise BuildError(f"{doc} p. {page}: quote not on the page: {quote!r}")
    sources.page(doc, page)  # the page exists in the held file either way
    if sources.licence(doc) == "reference-only":
        if sources.quote_gate is None:
            raise BuildError(
                f"{doc} is reference-only and the licence gate is not configured "
                "(puff.properties_source reference_only_quote)"
            )
        if not licence_gate_admits(quote, sources.quote_gate):
            raise BuildError(
                f"{doc} p. {page}: a reference-only source supplies a number and its "
                f"unit, not text: {quote!r}"
            )
    return {
        "doc_id": doc,
        "page": page,
        "locator": f"{doc}#p{page}",
        "quote": PP.norm(quote),
        "read_by": read_by,
        "sha256": sources.raw_sha256(doc),
    }


def _find(sources: SourceSet, spec: dict, anchor: str | None = None):
    """(page, match) of `spec["pattern"]` over the normalized text of `spec["page"]`
    (from `anchor` on, when given), or of every page; exactly one match is accepted."""
    doc, pattern = spec["doc"], re.compile(spec["pattern"])
    pages = [spec["page"]] if "page" in spec else range(1, len(sources.pages(doc)) + 1)
    hits = []
    for p in pages:
        text = PP.norm(sources.page(doc, p))
        if anchor:
            text = sources.between(doc, p, anchor, None)
        hits += [(p, m) for m in pattern.finditer(text)]
    if len(hits) != 1:
        raise BuildError(f"{doc}: {spec['pattern']!r} matches {len(hits)} times")
    return hits[0]


def _quote_of(sources, doc: str, m: re.Match) -> str:
    """The text a receipt keeps: the whole match, or from a `reference-only` source the
    number and its unit only (group `q` where the pattern names one, else group 1)."""
    if sources.licence(doc) != "reference-only":
        return m.group(0)
    return m.group("q") if "q" in m.re.groupindex else m.group(1)


def _held(sources, spec, unit: str, anchor=None, scale: float = 1.0) -> dict:
    page, m = _find(sources, spec, anchor)
    return {
        "value": round(_number(m.group(1)) * scale, 10),
        "unit": unit,
        "status": "held",
        "reason": None,
        "receipt": _receipt(
            sources, spec["doc"], page, _quote_of(sources, spec["doc"], m)
        ),
        "derived_from": [],
    }


def _missing(unit: str, reason: str, status: str = "not_held") -> dict:
    return {
        "value": None,
        "unit": unit,
        "status": status,
        "reason": reason,
        "receipt": None,
        "derived_from": [],
    }


def _rendered(sources, spec: dict, unit: str) -> dict:
    """A value read from a rendered page (no usable text layer): the recorded reading
    is the quote, and the number is parsed from it, never typed beside it."""
    q = spec["rendered"]
    m = _SCI.search(q)
    value = float(m.group(1)) * 10 ** int(m.group(2)) if m else _number(q.split()[-1])
    return {
        "value": value,
        "unit": unit,
        "status": "held",
        "reason": None,
        "receipt": _receipt(sources, spec["doc"], spec["page"], q, "rendered_page"),
        "derived_from": [],
    }


def _derived(value: float, unit: str, names: list) -> dict:
    return {
        "value": round(value, 10),
        "unit": unit,
        "status": "held",
        "reason": None,
        "receipt": None,
        "derived_from": names,
    }


def _numeric_check(field: str, values: dict) -> dict:
    """Like `cross_check`, but numbers agree when equal at the coarser printed
    precision (NIST prints 70.906 where CAMEO prints 70.91)."""

    def places(s):
        return len(s.split(".")[1]) if "." in s else 0

    carried = {k: v for k, v in values.items() if v is not None}
    if len(carried) < 2:
        status = "single_source"
    else:
        dp = min(places(v.replace(",", "")) for v in carried.values())
        rounded = {round(_number(v), dp) for v in carried.values()}
        status = "agree" if len(rounded) == 1 else "disputed"
    return {"field": field, "values": dict(sorted(values.items())), "status": status}


def _air(sources: SourceSet, spec: dict) -> dict:
    """The conversion basis and the asphyxiant fraction at the oxygen threshold."""
    page, m = _find(sources, spec["conversion_basis"])
    rc = _receipt(sources, spec["conversion_basis"]["doc"], page, m.group(0))
    t_c = {**_derived(_number(m.group(1)), "degC", []), "receipt": rc}
    p_atm = {**_derived(_number(m.group(2)), "atm", []), "receipt": rc}
    t_k = _held(sources, spec["conversion_temperature_k"], "K")
    k = _rendered(sources, spec["boltzmann"], "N m/K")
    na = _rendered(sources, spec["avogadro"], "1/kmol")
    p0 = _rendered(sources, spec["sea_level_pressure"], "Pa")
    r = _derived(
        k["value"] * na["value"],
        "J/(kmol K)",
        ["boltzmann_constant_n_m_k", "avogadro_constant_per_kmol"],
    )
    # 1 atm is the standard sea-level pressure P0 (Standard Atmosphere Table 2).
    vm = _derived(
        r["value"] * t_k["value"] / (p0["value"] * p_atm["value"]),
        "m3/kmol",
        [
            "gas_constant_j_kmol_k",
            "conversion_temperature_k",
            "standard_pressure_pa",
            "conversion_pressure_atm",
        ],
    )
    return {
        "conversion_temperature_c": t_c,
        "conversion_pressure_atm": p_atm,
        "conversion_temperature_k": t_k,
        "boltzmann_constant_n_m_k": k,
        "avogadro_constant_per_kmol": na,
        "gas_constant_j_kmol_k": r,
        "standard_pressure_pa": p0,
        "molar_volume_m3_kmol": vm,
        "oxygen_volume_fraction": _rendered(sources, spec["oxygen_fraction"], "1"),
    }


def _aegl(sources, spec: dict, minutes: list) -> tuple[dict, list]:
    """AEGL-1 to -3 in ppm at `minutes` from the compiled table's rows under its
    anchor, cross-checked against the program's results page for the chemical."""
    doc, page = spec["doc"], spec["page"]
    text = sources.between(doc, page, spec["anchor"], None)
    head = PP.norm(spec["columns_quote"])
    if not text[len(PP.norm(spec["anchor"])) :].lstrip().startswith(head):
        raise BuildError(f"{doc} p. {page}: columns are not {head!r}")
    columns = [c.split()[0] for c in re.findall(r"\d+ (?:min|hr)", head)]
    out, rows = {}, {}
    for level in ("1", "2", "3"):
        m = re.search(rf"AEGL {level}((?: [0-9.,]+){{5}})", text)
        if not m:
            raise BuildError(f"{doc} p. {page}: no AEGL {level} row")
        cells = m.group(1).split()
        rows[level] = cells
        rc = _receipt(sources, doc, page, m.group(0))
        out[f"AEGL-{level}"] = {
            mins: {
                **_derived(_number(cells[columns.index(mins)]), "ppm", []),
                "receipt": rc,
            }
            for mins in minutes
        }
    xc = spec["cross_check"]
    other = " ".join(PP.norm(t) for t in sources.pages(xc["doc"]))
    checks = []
    for level, cells in rows.items():
        m = re.search(rf"AEGL {level}((?: \| [0-9.,]+){{5}})", other)
        theirs = m.group(1).replace("|", " ").split() if m else None
        checks.append(
            cross_check(
                f"AEGL-{level} ppm at {', '.join(minutes)} min",
                {
                    doc: " | ".join(cells[: len(minutes)]),
                    xc["doc"]: " | ".join(theirs[: len(minutes)]) if theirs else None,
                },
            )
        )
    return out, checks


# ---------------------------------------------------------- HB-109: thermodynamics
# DN-020 section 2 item 4 and section 3.1: the properties a source term needs, each read
# from its held page (packs/src/materials_properties.yaml says where); CAMEO first, the
# NIST WebBook second. The selection rules are stated in that file's header.


#: HB-124 step 5: every held value names the kind of page it came from (the keys of
#: `materials_properties.yaml` `source_tiers`). The CAMEO datasheets and the NIST
#: WebBook's pages are reference tables; a program's test-case input is not.
REFERENCE_TABLE = "reference-table"
MODEL_TEST_INPUT = "model-test-input"


def _thermo(value, unit, receipt=None, **extra) -> dict:
    return {
        "value": None if value is None else round(value, 10),
        "unit": unit,
        "status": "held",
        "reason": None,
        "receipt": receipt,
        "derived_from": extra.get("derived_from", []),
        "temperature_k": extra.get("temperature_k"),
        "as_printed": extra.get("as_printed"),
        "conversion": extra.get("conversion"),
        "value_range": extra.get("value_range"),
        "source_tier": extra.get("source_tier", REFERENCE_TABLE),
    }


def _thermo_missing(unit: str, reason: str) -> dict:
    return {
        **_missing(unit, reason),
        "temperature_k": None,
        "as_printed": None,
        "conversion": None,
        "value_range": None,
        "source_tier": None,
    }


# ------------------------------------------------- HB-124: the liquid properties
def _saturation_row(sources, doc: str, spec: dict, t_k: float) -> dict:
    """The NIST Fluid Systems saturation row nearest `t_k` (a tie goes to the first
    printed, `_nearest_row`'s rule), as printed: `cells` by column header, and the
    receipt quoting the whole row, numbers only (the licence gate), on the held text's
    page 1. Every column `spec["columns"]` names must be in the header exactly once."""
    lines = [x for x in sources.path(doc).read_text("utf-8").splitlines() if x.strip()]
    if len(lines) < 2:
        raise BuildError(f"{doc}: a saturation table with no row")
    header = lines[0].split("\t")
    cols = {}
    for key, name in spec["columns"].items():
        if header.count(name) != 1:
            raise BuildError(
                f"{doc}: column {name!r} occurs {header.count(name)} times"
            )
        cols[key] = header.index(name)
    rows = []
    for line in lines[1:]:
        cells = line.split("\t")
        if len(cells) != len(header):
            raise BuildError(f"{doc}: a row of {len(cells)} cells under {len(header)}")
        rows.append({"t": _printed_number(cells[cols["temperature"]]), "cells": cells})
    row = _nearest_row(rows, t_k)
    quote = " ".join(row["cells"])
    if PP.norm(sources.page(doc, 1)).count(PP.norm(quote)) != 1:
        raise BuildError(f"{doc}: the row {quote!r} is not once on the held text")
    return {
        "t": row["t"],
        "printed": {k: row["cells"][i] for k, i in cols.items()},
        "receipt": _receipt(sources, doc, 1, quote),
    }


def _fluid_liquid(sources, props: dict, doc: str, t_ref: float) -> dict:
    """Liquid density and Cp, and the enthalpy of vaporisation h(v) − h(l), from one
    Fluid Systems row nearest the boiling point (HB-124 step 4); and the saturated
    vapour's Cp from the same row, SLAB's CPS (HB-126 Part A item 1)."""
    spec = props["saturation_table"]
    r = _saturation_row(sources, doc, spec, t_ref)
    p, rc, t = r["printed"], r["receipt"], r["t"]
    at = f" at {p['temperature']} K"
    kj = props["units"]["kilojoule"]["scale"]
    h_v, h_l = Decimal(p["vapour_enthalpy"]), Decimal(p["liquid_enthalpy"])
    return {
        "liquid_density_kg_m3": _thermo(
            _printed_number(p["liquid_density"]),
            "kg/m3",
            rc,
            temperature_k=t,
            as_printed=f"{p['liquid_density']} kg/m3{at}",
        ),
        "liquid_heat_capacity_j_mol_k": _thermo(
            _printed_number(p["liquid_heat_capacity"]),
            "J/mol/K",
            rc,
            temperature_k=t,
            as_printed=f"{p['liquid_heat_capacity']} J/mol*K{at}",
        ),
        "vapour_heat_capacity_j_mol_k": _thermo(
            _printed_number(p["vapour_heat_capacity"]),
            "J/mol/K",
            rc,
            temperature_k=t,
            as_printed=f"{p['vapour_heat_capacity']} J/mol*K{at}",
        ),
        "heat_of_vaporization_j_mol": _thermo(
            float((h_v - h_l) * Decimal(str(kj))),
            "J/mol",
            rc,
            temperature_k=t,
            as_printed=f"h(v) {p['vapour_enthalpy']} kJ/mol, "
            f"h(l) {p['liquid_enthalpy']} kJ/mol{at}",
            conversion=spec["enthalpy_of_vaporization"],
            derived_from=[
                spec["columns"]["vapour_enthalpy"],
                spec["columns"]["liquid_enthalpy"],
            ],
        ),
    }


def _reading(spec: dict, name: str) -> tuple[str, float]:
    """`NAME = number` as read from a rendered page: (the printed number, its value).
    The number is parsed from the reading, never typed beside it."""
    m = re.fullmatch(rf"{re.escape(name)} = (?P<v>\S+)", spec["rendered"])
    if not m:
        raise BuildError(f"not a {name} reading: {spec['rendered']!r}")
    return m.group("v"), _printed_number(m.group("v"))


def _slab_test_input(sources, props: dict, spec: dict) -> tuple[dict, list]:
    """HB-124 Part A step 2: DHE, CPSL and RHOSL as the SLAB user's guide prints a
    test case's input, read from the rendered page, the per-kilogram ones per mole by
    the same input's WMS; each `model-test-input`. HB-126: CPS the same way. The
    guide's Table 2 row is the cross-check of each."""
    doc, page = spec["doc"], spec["page"]
    rc = {
        k: _receipt(sources, doc, page, spec[k]["rendered"], "rendered_page")
        for k in (
            "molecular_weight",
            "boiling_point",
            "heat_of_vaporization",
            "liquid_heat_capacity",
            "liquid_density",
            "vapour_heat_capacity",
        )
    }
    wms_p, _ = _reading(spec["molecular_weight"], "WMS")
    tbp_p, tbp = _reading(spec["boiling_point"], "TBP")
    dhe_p, _ = _reading(spec["heat_of_vaporization"], "DHE")
    cpsl_p, _ = _reading(spec["liquid_heat_capacity"], "CPSL")
    rhosl_p, rhosl = _reading(spec["liquid_density"], "RHOSL")
    cps_p, _ = _reading(spec["vapour_heat_capacity"], "CPS")
    wms = Decimal(wms_p)
    conv = f"{props['per_kilogram']['conversion']} (WMS {wms_p} kg/mol)"
    tier = {"source_tier": MODEL_TEST_INPUT}
    values = {
        "heat_of_vaporization_j_mol": _thermo(
            float(Decimal(dhe_p) * wms),
            "J/mol",
            rc["heat_of_vaporization"],
            temperature_k=tbp,
            as_printed=f'{dhe_p} J/kg at TBP {tbp_p} K ("Heat of vaporization at '
            'the boiling point temperature")',
            conversion=conv,
            derived_from=[spec["molecular_weight"]["rendered"]],
            **tier,
        ),
        "liquid_heat_capacity_j_mol_k": _thermo(
            float(Decimal(cpsl_p) * wms),
            "J/mol/K",
            rc["liquid_heat_capacity"],
            as_printed=f"{cpsl_p} J/kg*K (no temperature printed)",
            conversion=conv,
            derived_from=[spec["molecular_weight"]["rendered"]],
            **tier,
        ),
        "liquid_density_kg_m3": _thermo(
            rhosl,
            "kg/m3",
            rc["liquid_density"],
            as_printed=f"{rhosl_p} kg/m3 (no temperature printed)",
            **tier,
        ),
        "vapour_heat_capacity_j_mol_k": _thermo(
            float(Decimal(cps_p) * wms),
            "J/mol/K",
            rc["vapour_heat_capacity"],
            as_printed=f"{cps_p} J/kg*K (no temperature printed)",
            conversion=conv,
            derived_from=[spec["molecular_weight"]["rendered"]],
            **tier,
        ),
    }
    t2 = spec["table2"]
    _receipt(sources, doc, t2["page"], t2["rendered"], "rendered_page")
    cells = t2["rendered"].split()
    if len(cells) != len(t2["columns"]):
        raise BuildError(
            f"{doc} p. {t2['page']}: Table 2 reading has {len(cells)} cells"
        )
    row = dict(zip(t2["columns"], cells))
    checks = []
    for name, printed, unit in (
        ("DHE", dhe_p, "J/kg"),
        ("CPSL", cpsl_p, "J/kg*K"),
        ("RHOSL", rhosl_p, "kg/m3"),
        ("CPS", cps_p, "J/kg*K"),
    ):
        other = row[name]
        checks.append(
            {
                "field": f"SLAB chlorine {name} ({unit})",
                "values": {
                    f"{doc} (test case input, p{page})": printed,
                    f"{doc} (Table 2, p{t2['page']})": other,
                },
                "status": "agree"
                if _printed_number(printed) == _printed_number(other)
                else "disputed",
            }
        )
    return values, checks


def _f_to_k(printed: str, units: dict) -> float:
    u = units["fahrenheit"]
    return round(
        (_printed_number(printed) - u["offset_f"]) / u["f_per_k"] + u["offset_k"], 10
    )


def _half_unit(printed: str) -> float:
    """Half a unit in the last printed digit: the precision a value without a stated
    uncertainty carries ("239." is +/- 0.5; "70.906" is +/- 0.0005)."""
    t = printed.replace("−", "-").split("×")[0]
    places = len(t.split(".")[1]) if "." in t else 0
    return 0.5 * 10 ** (-places)


def _agree(a: dict, b: dict) -> bool:
    """Two printed values agree within the larger of their stated uncertainties (half
    a unit in the last printed digit where none is stated)."""
    return abs(a["value"] - b["value"]) <= max(a["tol"], b["tol"])


def _tolerance_check(field: str, rows: list, taken: dict | None) -> dict:
    """Every printed row of a field, compared with the row taken: `agree` when each
    agrees with it, `disputed` when one does not (or none is taken), `single_source`
    when one row is printed."""
    values = {r["key"]: r["shown"] for r in rows}
    if len(rows) < 2:
        status = "single_source"
    elif taken is not None and all(_agree(r, taken) for r in rows):
        status = "agree"
    else:
        status = "disputed"
    return {"field": field, "values": dict(sorted(values.items())), "status": status}


def _nist_quantity_rows(sources, doc: str, quantity: str, unit: str) -> list:
    """Every row of a NIST WebBook quantity table ("Tc | 416.956 | K | N/A | Angus,
    Armstrong, et al., 1984 | TRC"), with its stated uncertainty (the "±" value, or the
    comment's "Uncertainty assigned by TRC")."""
    pat = re.compile(
        rf"(?:^|; ){re.escape(quantity)} \| "
        rf"(?P<q>(?P<v>[-0-9.]+)(?: ± (?P<u>[0-9.]+))? "
        rf"\| {re.escape(unit)}) \| [^|]* \| (?P<ref>[^|]*?) \|(?P<comment>[^;]*)"
    )
    rows = []
    for p in range(1, len(sources.pages(doc)) + 1):
        for m in pat.finditer(PP.norm(sources.page(doc, p))):
            trc = re.search(
                rf"Uncertainty assigned by TRC = ([0-9.]+) {re.escape(unit)}",
                m.group("comment"),
            )
            stated = m.group("u") or (trc.group(1) if trc else None)
            rows.append(
                {
                    "page": p,
                    "quote": m.group("q"),
                    "value": _printed_number(m.group("v")),
                    "printed": m.group("v"),
                    "tol": float(stated) if stated else _half_unit(m.group("v")),
                    "key": f"{doc} ({m.group('ref').strip()}, p{p})",
                    "shown": f"{m.group('v')} {unit}"
                    + (f" ± {stated}" if stated else ""),
                }
            )
    return rows


def _pick_row(rows: list) -> dict | None:
    """The first printed row that agrees with another printed row; a single row as
    printed; None when no two agree."""
    if len(rows) == 1:
        return rows[0]
    for r in rows:
        if any(_agree(r, o) for o in rows if o is not r):
            return r
    return None


def _nist_quantity(sources, doc, quantity, unit, field, absent) -> tuple[dict, dict]:
    rows = _nist_quantity_rows(sources, doc, quantity, unit)
    if not rows:
        return _thermo_missing(unit, absent["critical_not_printed"]), None
    taken = _pick_row(rows)
    check = _tolerance_check(field, rows, taken)
    if taken is None:
        shown = ", ".join(r["shown"] for r in rows)
        return (
            _thermo_missing(
                unit,
                f"the held page prints {len(rows)} rows ({shown}) and no two agree "
                "within their stated uncertainties",
            ),
            check,
        )
    rc = _receipt(sources, doc, taken["page"], taken["quote"])
    return _thermo(taken["value"], unit, rc), check


def _table_rows(sources, doc: str, header: str) -> list:
    """(value, temperature) rows of every NIST table under `header`, in print order."""
    pat = re.compile(
        r"(?:^|; )(?P<q>(?P<v>[0-9.]+)(?: ± (?P<u>[0-9.]+))? \| (?P<t>[0-9.]+))"
        r"(?= ;| \||$)"
    )
    head = PP.norm(header)
    rows = []
    for p in range(1, len(sources.pages(doc)) + 1):
        text = PP.norm(sources.page(doc, p))
        i = text.find(head)
        if i < 0:
            continue
        for m in pat.finditer(text, i + len(head)):
            rows.append(
                {
                    "page": p,
                    "quote": m.group("q"),
                    "value": _printed_number(m.group("v")),
                    "printed": m.group("v"),
                    "t": _printed_number(m.group("t")),
                    "t_printed": m.group("t"),
                }
            )
    return rows


def _nearest_row(rows: list, t_k: float) -> dict:
    """The row nearest `t_k`; `min` keeps the first printed on a tie."""
    return min(rows, key=lambda r: abs(r["t"] - t_k))


def _constant(value: float, unit: str, receipt: dict) -> dict:
    """A correlation constant as printed, unrounded: `_derived`'s ten decimal places
    would cut a printed 2.825911×10-7 to 2.826e-07."""
    return {
        "value": value,
        "unit": unit,
        "status": "held",
        "reason": None,
        "receipt": receipt,
        "derived_from": [],
    }


def _forms_on_page(sources, doc: str, quotes: list) -> None:
    text = " ".join(PP.norm(p) for p in sources.pages(doc))
    for q in quotes:
        if PP.norm(q) not in text:
            raise BuildError(f"{doc}: the correlation's form {q!r} is not on the page")


def _antoine(sources, doc: str, spec: dict) -> dict:
    """Every Antoine row the page prints, each with its range and the row's numbers as
    its receipt (DN-020 section 2 item 4: the numbers, not the text)."""
    _forms_on_page(sources, doc, spec["form_quotes"])
    pat = re.compile(
        r"(?:^|; )(?P<q>(?P<tmin>[0-9.]+) to (?P<tmax>[0-9.]+) \| (?P<A>-?[0-9.]+) \| "
        r"(?P<B>-?[0-9.]+) \| (?P<C>-?[0-9.]+)) \|"
    )
    head = PP.norm(spec["header"])
    units = {"A": "log10(bar)", "B": "K", "C": "K"}
    rows = []
    for p in range(1, len(sources.pages(doc)) + 1):
        text = PP.norm(sources.page(doc, p))
        i = text.find(head)
        if i < 0:
            continue
        for m in pat.finditer(text, i + len(head)):
            rc = _receipt(sources, doc, p, m.group("q"))
            rows.append(
                {
                    "t_min_k": _printed_number(m.group("tmin")),
                    "t_max_k": _printed_number(m.group("tmax")),
                    "constants": {
                        k: _constant(_printed_number(m.group(k)), u, rc)
                        for k, u in units.items()
                    },
                    "receipt": rc,
                }
            )
    if not rows:
        raise BuildError(f"{doc}: the Antoine header is printed with no row")
    return {"form": spec["form"], "status": "held", "reason": None, "rows": rows}


def _shomate(sources, doc: str, spec: dict, absent: dict) -> dict:
    """The gas-phase Shomate constants of the lowest-temperature column, with its
    range; each constant's receipt is its printed number on the table's page."""
    for p in range(1, len(sources.pages(doc)) + 1):
        text = PP.norm(sources.page(doc, p))
        if not re.match(r"Temperature \(K\) \| [0-9.]+ to [0-9.]+", text):
            continue
        cells = text.split(" ; ")
        if not set(spec["constants"]) <= {c.split(" | ")[0] for c in cells[1:]}:
            continue  # another correlation's table (propane's ΔvapH fit)
        _forms_on_page(sources, doc, spec["form_quotes"])
        first = cells[0].split(" | ")[1]
        tmin, tmax = (_printed_number(x) for x in first.split(" to "))
        rc = _receipt(sources, doc, p, first)
        constants = {}
        for cell in cells[1:]:
            parts = cell.split(" | ")
            if parts[0] in spec["constants"]:
                constants[parts[0]] = _constant(
                    _printed_number(parts[1]),
                    "J/mol*K",
                    _receipt(sources, doc, p, parts[1]),
                )
        if set(constants) != set(spec["constants"]):
            raise BuildError(f"{doc} p. {p}: the Shomate table lacks a constant")
        row = {"t_min_k": tmin, "t_max_k": tmax, "constants": constants, "receipt": rc}
        return {"form": spec["form"], "status": "held", "reason": None, "rows": [row]}
    return {
        "form": spec["form"],
        "status": "not_held",
        "reason": absent["shomate_not_printed"],
        "rows": [],
    }


def _cameo_value(sources, spec: dict, unit: str, units: dict, absent: dict) -> dict:
    """A CAMEO physical property as printed (a value, with its temperature in °F where
    printed), or `not_held` where the datasheet prints "data unavailable"."""
    if "not_printed" in spec:
        _find(sources, spec["not_printed"])  # the datasheet's own "data unavailable"
        return _thermo_missing(unit, absent["cameo_unavailable"])
    page, m = _find(sources, spec)
    t = m.groupdict().get("t")
    return _thermo(
        _printed_number(m.group("v")),
        unit,
        _receipt(sources, spec["doc"], page, m.group(0)),
        temperature_k=_f_to_k(t, units) if t else None,
        as_printed=f"{m.group('v')} {unit}" + (f" at {t} °F" if t else ""),
        conversion=units["fahrenheit"]["conversion"] if t else None,
    )


def _boiling_point(sources, spec, nist: str | None, units, absent):
    """CAMEO's normal boiling point first (°F at 760 mmHg, in K), NIST's Tboil rows
    second and as its cross-check; a mixture's printed range as a range."""
    rows, taken, value = [], None, None
    if "cameo" in spec:
        s = spec["cameo"]
        page, m = _find(sources, s)
        v = m.group("v")
        k = _f_to_k(v, units)
        value = _thermo(
            k,
            "K",
            _receipt(sources, s["doc"], page, m.group(0)),
            as_printed=f"{v} °F at 760 mmHg",
            conversion=units["fahrenheit"]["conversion"],
        )
        taken = {
            "value": k,
            "tol": _half_unit(v) / units["fahrenheit"]["f_per_k"],
            "key": s["doc"],
            "shown": f"{k:.2f} K ({v} °F)",
        }
        rows.append(taken)
    elif "cameo_range" in spec:
        s = spec["cameo_range"]
        page, m = _find(sources, s)
        lo, hi = m.group("lo"), m.group("hi")
        value = _thermo(
            None,
            "K",
            _receipt(sources, s["doc"], page, m.group(0)),
            as_printed=f"{lo} to {hi} °F at 760 mmHg",
            conversion=units["fahrenheit"]["conversion"],
            value_range=[_f_to_k(lo, units), _f_to_k(hi, units)],
        )
        return value, None
    elif "cameo_unavailable" in spec:
        _find(sources, spec["cameo_unavailable"])
    if nist:
        nrows = _nist_quantity_rows(sources, nist, "Tboil", "K")
        if value is None and nrows:
            pick = _pick_row(nrows)
            if pick is not None:
                taken = pick
                value = _thermo(
                    pick["value"],
                    "K",
                    _receipt(sources, nist, pick["page"], pick["quote"]),
                )
        rows += nrows
    if value is None:
        value = _thermo_missing("K", absent["cameo_unavailable"])
    check = _tolerance_check("normal boiling point (K)", rows, taken) if rows else None
    return value, check


def _thermodynamics(sources, props: dict, un: str, mw: dict) -> tuple[dict, set]:
    spec = props["materials"][un]
    units, absent = props["units"], props["absent"]
    nist = spec.get("nist")
    used = {
        s["doc"]
        for s in (
            spec.get("specific_gravity"),
            spec.get("vapour_pressure"),
            *(spec.get("boiling_point") or {}).values(),
        )
        if s and "doc" in s
    }
    for key in ("specific_gravity", "vapour_pressure"):
        if "not_printed" in spec[key]:
            used.add(spec[key]["not_printed"]["doc"])
    checks = []
    tb, check = _boiling_point(sources, spec["boiling_point"], nist, units, absent)
    if check:
        checks.append(check)
    sg = _cameo_value(
        sources, spec["specific_gravity"], "1 (relative to water)", units, absent
    )
    vp = _cameo_value(sources, spec["vapour_pressure"], "mmHg", units, absent)
    if nist:
        used.add(nist)
        hv_rows = _table_rows(
            sources, nist, props["tables"]["heat_of_vaporization"]["header"]
        )
        cp_rows = _table_rows(
            sources, nist, props["tables"]["vapour_heat_capacity"]["header"]
        )
        t_ref = tb["value"]
        if hv_rows and t_ref is not None:
            r = _nearest_row(hv_rows, t_ref)
            kj = props["units"]["kilojoule"]
            hv = _thermo(
                r["value"] * kj["scale"],
                "J/mol",
                _receipt(sources, nist, r["page"], r["quote"]),
                temperature_k=r["t"],
                as_printed=f"{r['printed']} kJ/mol at {r['t_printed']} K",
                conversion=kj["conversion"],
            )
        else:
            hv = _thermo_missing("J/mol", absent["heat_of_vaporization_not_printed"])
        if cp_rows and t_ref is not None:
            r = _nearest_row(cp_rows, t_ref)
            cpv = _thermo(
                r["value"],
                "J/mol/K",
                _receipt(sources, nist, r["page"], r["quote"]),
                temperature_k=r["t"],
                as_printed=f"{r['printed']} J/mol*K at {r['t_printed']} K",
            )
        else:
            cpv = _thermo_missing("J/mol/K", absent["vapour_cp_not_tabulated"])
        shomate = _shomate(sources, nist, props["correlations"]["shomate"], absent)
        antoine = _antoine(sources, nist, props["correlations"]["antoine"])
        tc, tc_check = _nist_quantity(
            sources, nist, "Tc", "K", "critical temperature (K)", absent
        )
        pc, pc_check = _nist_quantity(
            sources, nist, "Pc", "bar", "critical pressure (bar)", absent
        )
        checks += [c for c in (tc_check, pc_check) if c]
    else:
        hv = _thermo_missing("J/mol", absent["no_nist"])
        cpv = _thermo_missing("J/mol/K", absent["no_nist"])
        shomate = {
            "form": props["correlations"]["shomate"]["form"],
            "status": "not_held",
            "reason": absent["no_nist"],
            "rows": [],
        }
        antoine = {
            "form": props["correlations"]["antoine"]["form"],
            "status": "not_held",
            "reason": absent["no_nist"],
            "rows": [],
        }
        tc = _thermo_missing("K", absent["no_nist"])
        pc = _thermo_missing("bar", absent["no_nist"])
    # HB-124: the liquid fields, and an enthalpy of vaporisation the species page does
    # not print, from the NIST Fluid Systems row nearest the boiling point; where
    # Fluid Systems has no table (chlorine), from the SLAB guide's test-case input.
    liq_cp = _thermo_missing("J/mol/K", absent["liquid_heat_capacity"])
    liq_rho = _thermo_missing("kg/m3", absent["liquid_density"])
    if spec.get("nist_fluid") and spec.get("slab_test_input"):
        raise BuildError(f"UN{un}: one liquid-property source, not two")
    if spec.get("nist_fluid"):
        if tb["value"] is None:
            raise BuildError(f"UN{un}: a saturation row needs a boiling point")
        used.add(spec["nist_fluid"])
        fl = _fluid_liquid(sources, props, spec["nist_fluid"], tb["value"])
        liq_cp, liq_rho = fl["liquid_heat_capacity_j_mol_k"], fl["liquid_density_kg_m3"]
        if hv["status"] != "held":
            hv = fl["heat_of_vaporization_j_mol"]
        # HB-126: the species page's tabulated gas Cp stays first (propane's)
        if cpv["status"] != "held":
            cpv = fl["vapour_heat_capacity_j_mol_k"]
    elif spec.get("slab_test_input"):
        used.add(spec["slab_test_input"]["doc"])
        sl, sl_checks = _slab_test_input(sources, props, spec["slab_test_input"])
        liq_cp, liq_rho = sl["liquid_heat_capacity_j_mol_k"], sl["liquid_density_kg_m3"]
        if hv["status"] != "held":
            hv = sl["heat_of_vaporization_j_mol"]
        if cpv["status"] != "held":
            cpv = sl["vapour_heat_capacity_j_mol_k"]
        checks += sl_checks
    thermo = {
        "proxy": None,
        "molecular_weight_g_mol": mw,
        "normal_boiling_point_k": tb,
        "heat_of_vaporization_j_mol": hv,
        "liquid_heat_capacity_j_mol_k": liq_cp,
        "vapour_heat_capacity_j_mol_k": cpv,
        "vapour_heat_capacity_shomate": shomate,
        "liquid_specific_gravity": sg,
        "liquid_density_kg_m3": liq_rho,
        "vapour_pressure_as_printed": vp,
        "saturation_pressure_antoine": antoine,
        "critical_temperature_k": tc,
        "critical_pressure_bar": pc,
        "cross_checks": checks,
    }
    thermo["missing"] = _thermo_missing_fields(thermo, props["required_fields"])
    return thermo, used


def _thermo_missing_fields(thermo: dict, required: list) -> list:
    """The required source-term fields not held (packs/src/materials_properties.yaml
    `required_fields`). The vapour heat capacity is held when the value SLAB reads as
    CPS is (HB-126): a Shomate row is not evaluated outside its range, and every held
    row starts above the boiling point, so the correlation alone does not count."""
    out = []
    for name in required:
        if name == "vapour_heat_capacity":
            held = thermo["vapour_heat_capacity_j_mol_k"]["status"] == "held"
        else:
            held = thermo[name]["status"] == "held"
        if not held:
            out.append(name)
    return out


def _proxy_thermodynamics(sources, props, un: str, of: dict) -> tuple[dict, set]:
    """DN-020 ADDENDUM-01 section 2 item 4: a mixture drawn with a pure substance's
    properties, marked so; the receipt is the mixture's page stating what it is."""
    spec = props["materials"][un]["proxy"]
    page, m = _find(sources, spec)
    thermo = json.loads(json.dumps(of))
    thermo["proxy"] = {
        "proxy_for": f"UN{un}",
        "properties_of": f"UN{spec['properties_of']}",
        "label": spec["label"],
        "receipt": _receipt(sources, spec["doc"], page, m.group(0)),
    }
    return thermo, {spec["doc"]}


def _levels_of_concern(
    sources, props, mat: dict, lfl: dict, proxy_for: str | None
) -> tuple[list, set]:
    """The level of concern per DN-001 class (DN-020 ADDENDUM-01 section 2 item 2):
    AEGL-2 for a toxic gas, a fraction of the LFL for a flammable, the oxygen-deficiency
    threshold for a cryogenic asphyxiant."""
    loc = props["levels_of_concern"]
    cls = mat["dispersion_class"]
    if cls == "pressure_liquefied_toxic":
        if not mat["aegl_ppm"]:
            return [], set()
        return [
            {
                "kind": "aegl2",
                "unit": "ppm",
                "basis": loc["aegl2"]["basis"],
                "proxy_for": None,
                "values": mat["aegl_ppm"]["AEGL-2"],
                "components": {},
            }
        ], set()
    if cls == "cryogenic_asphyxiant":
        o2 = mat["oxygen_deficiency_threshold_vol_pct"]
        if o2["status"] != "held":
            return [], set()
        return [
            {
                "kind": "oxygen_deficiency",
                "unit": "vol % oxygen",
                "basis": loc["oxygen_deficiency"]["basis"],
                "proxy_for": None,
                "values": {"any": o2},
                "components": {},
            }
        ], set()
    if lfl["status"] != "held":
        return [], set()
    fs = loc["lfl_fraction"]["fraction"]
    fraction = _held(sources, fs, fs["unit"])
    value = _derived(
        lfl["value"] * fraction["value"] / 100.0, "vol %", ["lfl", "fraction"]
    )
    return [
        {
            "kind": "lfl_fraction",
            "unit": "vol %",
            "basis": loc["lfl_fraction"]["basis"],
            "proxy_for": proxy_for,
            "values": {"any": value},
            "components": {"lfl": lfl, "fraction": fraction},
        }
    ], {fs["doc"]}


def build_materials_properties(cfg: dict, sources: SourceSet) -> dict:
    from hazbrief.packs import load_pack

    spec = cfg["puff"]
    packs_dir = REPO / cfg["paths"]["packs_dir"]
    erg = load_pack(packs_dir / "erg.json").data.materials
    cameo = load_pack(packs_dir / "cameo.json").data.materials
    air = _air(sources, spec["air"])
    o2 = _held(sources, spec["oxygen_deficiency"], "vol %")
    air["asphyxiant_vol_pct_at_threshold"] = _derived(
        100.0 * (1.0 - o2["value"] / (100.0 * air["oxygen_volume_fraction"]["value"])),
        "vol %",
        ["oxygen_deficiency_threshold_vol_pct", "oxygen_volume_fraction"],
    )
    vm = air["molar_volume_m3_kmol"]["value"]
    used = {r["receipt"]["doc_id"] for r in air.values() if r.get("receipt")}
    used.add(spec["oxygen_deficiency"]["doc"])
    minutes = list(spec["aegl_minutes"])
    materials = {}
    for un in cfg["seed_un_numbers"]:
        m = spec["materials"][un]
        cls = m["class"]
        rule = spec["classes"][cls]
        sheet = cameo[un].datasheets[0]
        checks = []
        mw_spec = m["molecular_weight"]
        if "not_held" in mw_spec:
            mw = _missing("g/mol", mw_spec["not_held"])
        else:
            mw = _held(sources, mw_spec, "g/mol")
            used.add(mw_spec["doc"])
            # CAMEO prints "Molecular Weight: data unavailable" where it has none: the
            # datasheet then carries no value for the check.
            page, cm = _find(
                sources,
                {
                    "doc": sheet.doc_id,
                    "pattern": r"Molecular Weight: ([0-9.]+ \(|data unavailable)",
                },
            )
            used.add(sheet.doc_id)
            theirs = cm.group(1).rstrip(" (")
            checks.append(
                _numeric_check(
                    "molecular weight (g/mol)",
                    {
                        mw_spec["doc"]: f"{mw['value']:g}",
                        sheet.doc_id: None if theirs == "data unavailable" else theirs,
                    },
                )
            )
        if "ppm_factor_check" in m and mw["status"] == "held":
            pc = m["ppm_factor_check"]
            page, pm = _find(sources, pc)
            used.add(pc["doc"])
            checks.append(
                _numeric_check(
                    "mg/m3 per ppm at 25 C and 1 atm",
                    {
                        pc["doc"]: pm.group(1),
                        "molecular weight / molar volume": f"{mw['value'] / vm:.4f}",
                    },
                )
            )
        lfl_spec = m.get("lfl")
        if cls != "flammable":
            lfl = _missing(
                "vol %",
                f"not drawn to an LFL: the {cls} class (DN-018 section 3)",
                "not_applicable",
            )
        elif "not_held" in lfl_spec:
            lfl = _missing("vol %", lfl_spec["not_held"])
            page, qm = _find(
                sources,
                {"doc": lfl_spec["quote_doc"], "pattern": lfl_spec["quote_pattern"]},
            )
            used.add(lfl_spec["quote_doc"])
            checks.append(
                cross_check("LFL as printed", {lfl_spec["quote_doc"]: qm.group(1)})
            )
        else:
            scale = 1e-4 if lfl_spec["unit"] == "ppm" else 1.0  # ppm by volume to vol %
            lfl = _held(sources, lfl_spec, "vol %", lfl_spec.get("anchor"), scale)
            used.add(lfl_spec["doc"])
            values = {lfl_spec["doc"]: f"{lfl['value']:g} %"}
            if "lfl_cross_check" in m:
                xc = m["lfl_cross_check"]
                page, xm = _find(sources, xc)
                used.add(xc["doc"])
                values[xc["doc"]] = f"{xm.group(1)} %"
            checks.append(
                _numeric_check(
                    "LFL (vol %)", {k: v.rstrip(" %") for k, v in values.items()}
                )
            )
        if "aegl" in m:
            aegl, aegl_checks = _aegl(sources, m["aegl"], minutes)
            used |= {m["aegl"]["doc"], m["aegl"]["cross_check"]["doc"]}
            page, sm = _find(sources, m["aegl"]["status"])
            used.add(m["aegl"]["status"]["doc"])
            status, reason = sm.group(1), None
            checks += aegl_checks
            pf = _held(sources, m["ppm_factor"], "mg/m3 per ppm")
            used.add(m["ppm_factor"]["doc"])
            checks.append(
                _numeric_check(
                    "mg/m3 per ppm at 25 C and 1 atm",
                    {
                        m["ppm_factor"]["doc"]: pf["receipt"]["quote"]
                        .split("=")[1]
                        .split()[0],
                        "molecular weight / molar volume": f"{mw['value'] / vm:.4f}",
                    },
                )
            )
        else:
            aegl, status = None, None
            reason = f"not drawn to an AEGL: the {cls} class (DN-018 section 3)"
        o2_value = (
            o2
            if cls == "cryogenic_asphyxiant"
            else _missing(
                "vol %",
                f"not drawn to an oxygen threshold: the {cls} class (DN-018 section 3)",
                "not_applicable",
            )
        )
        materials[un] = {
            "un": un,
            "name": sheet.title,
            "guide": str(erg[un].guide),
            "dispersion_class": cls,
            "dense_gas_caveat": bool(rule["dense_gas_caveat"]),
            "molecular_weight_g_mol": mw,
            "lfl_vol_pct": lfl,
            "aegl_status": status,
            "aegl_ppm": aegl,
            "aegl_reason": reason,
            "oxygen_deficiency_threshold_vol_pct": o2_value,
            "cross_checks": checks,
        }
    # HB-109: the thermodynamics (a proxy after the material it borrows from) and the
    # level of concern per class.
    props = load_properties_source(REPO / spec["properties_source"])
    if set(props["materials"]) != set(materials):
        raise BuildError(
            "properties source and seeds differ: "
            f"{sorted(set(props['materials']) ^ set(materials))}"
        )
    for un in sorted(materials, key=lambda u: "proxy" in props["materials"][u]):
        m = materials[un]
        p = props["materials"][un]
        if "proxy" in p:
            of = materials[p["proxy"]["properties_of"]]
            thermo, docs = _proxy_thermodynamics(
                sources, props, un, of["thermodynamics"]
            )
            lfl, proxy_for = of["lfl_vol_pct"], f"UN{un}"
        else:
            thermo, docs = _thermodynamics(
                sources, props, un, m["molecular_weight_g_mol"]
            )
            lfl, proxy_for = m["lfl_vol_pct"], None
        loc, loc_docs = _levels_of_concern(sources, props, m, lfl, proxy_for)
        m["thermodynamics"], m["levels_of_concern"] = thermo, loc
        used |= docs | loc_docs
    data = {"classes": spec["classes"], "air": air, "materials": materials}
    src = [sources.source(d, f"{d} (HB-66 receipts)") for d in sorted(used)]
    return envelope(
        "materials_properties",
        cfg,
        sources,
        src,
        attribution(sources, cfg, sorted(used)),
        data,
    )


_BAND = re.compile(
    r"<\s?\.?\d+(?:\.\d+)?|>\s?\d+(?:\.\d+)?|\d+\.\d+\s?-\s?\d+\.\d+|All"
)


def _sigma_z_blocks(sources: SourceSet, doc: str, pages: list) -> dict:
    """Table 1-2's class blocks: the printed text from one class letter to the next."""
    blocks = {}
    for p in pages:
        text = PP.norm(sources.page(doc, p))
        text = text.split("Category x (km) a b", 1)[1].split("* If the calculated", 1)[
            0
        ]
        marks = list(re.finditer(r"(?:^| )([A-F])\*? (?=<|All|\d)", text))
        for i, mk in enumerate(marks):
            end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
            blocks[mk.group(1)] = (p, text[mk.start() : end].strip())
    return blocks


def build_sigma_curves(cfg: dict, sources: SourceSet) -> dict:
    spec = cfg["puff"]["sigma"]
    doc = spec["doc"]

    def const(quote, page, pattern, unit):
        if not sources.quote_on_page(doc, page, quote):
            raise BuildError(f"{doc} p. {page}: {quote!r} not on the page")
        return {
            "value": _number(re.search(pattern, quote).group(1)),
            "unit": unit,
            "receipt": _receipt(sources, doc, page, quote),
        }

    yp = spec["sigma_y_page"]
    ytext = PP.norm(sources.page(doc, yp))
    classes = {}
    for cls in "ABCDEF":
        m = re.search(
            rf"(?:^| ){cls} ([0-9.]+) ([0-9.]+)(?= |$)",
            ytext.split("Category c d", 1)[1],
        )
        if not m:
            raise BuildError(f"{doc} p. {yp}: no Table 1-1 row for {cls}")
        classes[cls] = {
            "sigma_y": {
                "c": _number(m.group(1)),
                "d": _number(m.group(2)),
                "receipt": _receipt(sources, doc, yp, m.group(0).strip()),
            }
        }
    fixed = const(spec["fixed_quote"], spec["sigma_z_pages"][0], r"(\d+) m", "m")
    for cls, (page, block) in _sigma_z_blocks(
        sources, doc, spec["sigma_z_pages"]
    ).items():
        body = re.sub(rf"^{cls}\*? ", "", block)
        bands = _BAND.findall(body)
        rest = _BAND.sub(" ", body).split()
        n = len(bands)
        if len(rest) != 2 * n:
            raise BuildError(
                f"{doc} p. {page}: class {cls}: {n} bands, {len(rest)} values"
            )
        rc = _receipt(sources, doc, page, block)
        rows = []
        for band, a, b in zip(bands, rest[:n], rest[n:]):
            upper = (
                None
                if band.startswith(">") or band == "All"
                else _number(re.split(r"[-<]", band)[-1])
            )
            star = a == "**"
            rows.append(
                {
                    "x_range_as_printed": band,
                    "x_max_km": upper,
                    "a": None if star else _number(a),
                    "b": None if star else _number(b),
                    "fixed_m": fixed["value"] if star else None,
                    "receipt": rc,
                }
            )
        classes[cls]["sigma_z"] = rows
    if set(classes) != set("ABCDEF") or any(
        "sigma_z" not in c for c in classes.values()
    ):
        raise BuildError(f"{doc}: Table 1-2 does not give every class A to F")
    data = {
        "terrain": "rural",
        "sigma_y_form": (
            "sigma_y = 465.11628 x tan(TH), TH = 0.017453293 (c - d ln x); "
            "x in km, sigma_y in m"
        ),
        "sigma_z_form": "sigma_z = a x^b; x in km, sigma_z in m, capped",
        "sigma_y_scale": const(spec["sigma_y_scale_quote"], yp, r"= ([0-9.]+)", "m/km"),
        "theta_scale": const(spec["theta_quote"], yp, r"= ([0-9.]+)", "rad/deg"),
        "sigma_z_cap_m": const(
            spec["cap_quote"], spec["sigma_z_pages"][0], r"set to (\d+) m", "m"
        ),
        "band_rule": spec["band_rule"],
        "classes": classes,
        "urban": {"status": "not_built", "reason": spec["urban_not_built"]},
    }
    zp = "-".join(map(str, spec["sigma_z_pages"]))
    loc = f"{doc}#p{yp} (Table 1-1); #p{zp} (Table 1-2)"
    return envelope(
        "sigma_curves",
        cfg,
        sources,
        [sources.source(doc, loc)],
        attribution(sources, cfg, [doc]),
        data,
    )


def build_release_scenarios(cfg: dict, sources: SourceSet) -> dict:
    spec = cfg["puff"]["release"]
    wc = spec["worst_case_definition"]
    alt = spec["alternative_method"]

    def definition(s):
        return {
            "text": PP.norm(s["quote"]),
            "receipt": _receipt(sources, s["doc"], s["page"], s["quote"]),
        }

    duration = _held(
        sources, {"doc": wc["doc"], "page": wc["page"], "pattern": wc["pattern"]}, "min"
    )
    _receipt(
        sources,
        spec["transport_scope"]["doc"],
        spec["transport_scope"]["page"],
        spec["transport_scope"]["quote"],
    )
    dur_alt = spec["alternative_duration"]
    _receipt(sources, dur_alt["doc"], dur_alt["page"], dur_alt["quote"])
    containers = {}
    for c in spec["containers"]:
        reason = (
            spec["unknown_container"]
            if c == "unknown"
            else spec["worst_case_quantity_not_held"].format(container=c.lower())
        )
        containers[c] = {
            "container": c,
            "covered": False,
            "reason": reason,
            "worst_case_quantity_kg": _missing("kg", reason),
            "alternative_hole_size_cm": _missing(
                "cm", spec["alternative_hole_not_held"]
            ),
            "alternative_duration_min": _missing(
                "min", spec["alternative_duration_not_held"]
            ),
        }
    data = {
        "authority": spec["authority"],
        "worst_case": {"definition": definition(wc), "duration_min": duration},
        "alternative": {
            "method": definition(alt),
            "hole_size_cm": _missing("cm", spec["alternative_hole_not_held"]),
            "duration_min": _missing("min", spec["alternative_duration_not_held"]),
        },
        "containers": containers,
        "not_adopted": [dict(x) for x in spec["not_adopted"]],
    }
    docs = sorted(
        {wc["doc"], alt["doc"], dur_alt["doc"], spec["transport_scope"]["doc"]}
    )
    src = [sources.source(d, f"{d} (HB-66 receipts)") for d in docs]
    return envelope(
        "release_scenarios", cfg, sources, src, attribution(sources, cfg, docs), data
    )


# ------------------------------------------------------------------ release routing
#: The keys `packs/src/release_routing.yaml` carries (HB-120).
ROUTING_KEYS = ("doc", "rules", "guides")


def _routing_rule_text(sources: SourceSet, doc: str, spec: dict) -> dict:
    return {
        "text": PP.norm(spec["quote"]),
        "receipt": _receipt(sources, doc, int(spec["page"]), spec["quote"]),
    }


def build_release_routing(cfg: dict, sources: SourceSet, erg: dict) -> dict:
    """The release routing table (HB-120; DN-020 ADDENDUM-02 section 2 item 3) from
    `packs/src/release_routing.yaml` and the ERG pack `erg` (read, never written).

    Refused, naming what is wrong, when:
    * a guide of the ERG pack has no block, or a block names a guide the pack lacks;
    * a row has no basis, or its basis is not one of the guide's own POTENTIAL HAZARDS
      items, printed on that section's page of the held ERG (`_receipt` re-reads it);
    * a storage state the ERG names of a guide's index entries state
      (`hazbrief.brief.routing.name_state`) has no row on a guide without an `any` row.
    Each guide carries the 49 CFR 172.101 hazard classes and divisions of its index
    entries (UN and NA numbers), and the ERG placard table's classes that name it."""
    from hazbrief.brief import routing as RT

    path = Path(sources.repo) / cfg["paths"]["release_routing"]
    try:
        spec = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise BuildError(f"{path}: {exc}") from None
    missing = [k for k in ROUTING_KEYS if k not in spec]
    if missing:
        raise BuildError(f"{path}: missing key(s) {', '.join(missing)}")
    doc = spec["doc"]
    ed = erg["data"]
    held = set(ed["guides"])
    authored = {str(g) for g in spec["guides"]}
    if held != authored:
        raise BuildError(
            f"{path}: the routing table and the ERG pack's guides differ: "
            f"no block for {sorted(held - authored)}, "
            f"no such guide for {sorted(authored - held)}"
        )
    # the index entries each guide serves, and the states their names state
    names: dict[str, list[str]] = {g: [] for g in held}
    uns: dict[str, set[str]] = {g: set() for g in held}
    for un, entry in ed["index"].items():
        for n in entry["names"]:
            g = RT.base_guide(n["guide"])
            names[g].append(n["name"])
            uns[g].add(un)
    c = cfg["cfr"]
    wanted = {f"{p}{un}" for un in ed["index"] for p in ("UN", "NA")}
    hazmat = PP.cfr_hazmat_rows(
        sources.path(c["doc_id"]), c["section"], c["table_columns"], wanted
    )["rows"]
    placards: dict[str, set[str]] = {g: set() for g in held}
    for p in ed["placards"]:
        if p.get("hazard_class") and re.fullmatch(r"\d(\.\d)?", p["placard"]):
            placards[p["guide"]].add(p["placard"])
    guides = {}
    for g in sorted(held):
        block = spec["guides"].get(g) or spec["guides"].get(int(g))
        ph = ed["guides"][g]["sections"]["potential_hazards"]
        page = int(ph["locator"].rsplit("#p", 1)[1])
        items = {PP.norm(it["text"]) for it in ph["items"]}
        rows = []
        for r in block.get("rows") or []:
            b = r.get("basis") or {}
            if not b.get("quote") or not b.get("page"):
                raise BuildError(f"guide {g} {r.get('state')}: a row with no basis")
            if int(b["page"]) != page or PP.norm(b["quote"]) not in items:
                raise BuildError(
                    f"guide {g} {r.get('state')}: the basis is not one of the guide's "
                    f"POTENTIAL HAZARDS items on p. {page}: {b['quote']!r}"
                )
            rows.append(
                {
                    "state": r["state"],
                    "route": r["route"],
                    "loc_class": r.get("loc_class"),
                    "reason": r.get("reason"),
                    "basis": _receipt(sources, doc, page, b["quote"]),
                }
            )
        states = {r["state"] for r in rows}
        if "any" not in states:
            named = {RT.name_state([n])[0] for n in names[g]} - {None}
            if named - states:
                raise BuildError(
                    f"guide {g}: its index names state {sorted(named - states)}, "
                    "which have no row"
                )
        classes = sorted(
            {
                r["hazard_class"]
                for un in uns[g]
                for p in ("UN", "NA")
                for r in hazmat.get(f"{p}{un}", [])
                if r["hazard_class"]
            }
        )
        guides[g] = {
            "guide": g,
            "title": ed["guides"][g]["title"],
            "hazard_classes": classes,
            "placard_classes": sorted(placards[g]),
            "rows": rows,
        }
    data = {
        "rules": {
            k: _routing_rule_text(sources, doc, v) for k, v in spec["rules"].items()
        },
        "guides": guides,
    }
    docs = [doc, c["doc_id"]]
    src = [
        sources.source(doc, "orange guides, POTENTIAL HAZARDS (HB-120 receipts)"),
        sources.source(c["doc_id"], f"{c['section']} Hazardous Materials Table"),
    ]
    return envelope(
        "release_routing", cfg, sources, src, attribution(sources, cfg, docs), data
    )


#: HB-155: a siting rule's keys (`packs/src/siting_rules.yaml`).
SITING_KEYS = {
    "applies",
    "point",
    "words",
    "sources",
    "operator_stated",
    "material_sources",
    "material_none",
    "source_notes",
}


def build_siting_rules(cfg: dict, sources: SourceSet) -> dict:
    """The siting rules (HB-155; DN-023 section 4) from `packs/src/siting_rules.yaml`.
    Every quote is re-read on its page of the held original (`_receipt`); a rule with
    neither a held quote nor an operator record, an unknown key or an operator record
    that names no line of the statements file is refused, naming the rule."""
    path = Path(sources.repo) / cfg["paths"]["siting_rules"]
    try:
        spec = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise BuildError(f"{path}: {exc}") from None
    if not isinstance(spec.get("rules"), dict) or not spec["rules"]:
        raise BuildError(f"{path}: no `rules` mapping")
    statements = Path(sources.repo) / "docs/evidence/hb155/operator_statements.md"
    held = {
        line.split(".", 1)[0]
        for line in statements.read_text(encoding="utf-8").splitlines()
        if re.match(r"^S\d+\. ", line)
    }
    rules, docs = {}, set()
    for rid, r in spec["rules"].items():
        extra = set(r) - SITING_KEYS
        if extra:
            raise BuildError(f"{path}: rule {rid}: unknown key(s) {sorted(extra)}")
        receipts = []
        for s in r.get("sources") or []:
            receipts.append(_receipt(sources, s["doc"], int(s["page"]), s["quote"]))
            docs.add(s["doc"])
        op = r.get("operator_stated")
        if op is not None and op.get("statement") not in held:
            raise BuildError(
                f"{path}: rule {rid}: operator statement {op.get('statement')!r} is "
                f"not a line of {statements.name}"
            )
        if not receipts and op is None:
            raise BuildError(
                f"{path}: rule {rid}: no held quote and no operator record"
            )
        # HB-178: a source about one material is keyed by it; every UN number is read
        # on its page of the document, as every quote is
        by_un: dict[str, dict] = {}
        for m in r.get("material_sources") or []:
            docs.add(m["doc"])
            k = m["key"]
            quotes = [
                _receipt(sources, m["doc"], int(q["page"]), q["quote"])
                for q in m["quotes"]
            ]
            for un in k["numbers"]:
                if un in by_un:
                    raise BuildError(f"{path}: rule {rid}: UN{un} keyed twice")
                by_un[un] = {
                    "key": _receipt(sources, m["doc"], int(k["page"]), f"UN {un}"),
                    "sources": quotes,
                }
        if by_un and not r.get("material_none"):
            raise BuildError(f"{path}: rule {rid}: material sources need material_none")
        notes = {}
        for doc, n in (r.get("source_notes") or {}).items():
            if doc not in {s["doc"] for s in r.get("sources") or []}:
                raise BuildError(f"{path}: rule {rid}: a note on {doc}, not a source")
            notes[doc] = {
                "note": n["note"],
                "receipt": _receipt(sources, doc, int(n["page"]), n["quote"]),
            }
        rules[rid] = {
            "applies": r["applies"],
            "point": r.get("point"),
            "words": r["words"],
            "sources": receipts,
            "operator_stated": op,
            "material_sources": dict(sorted(by_un.items())),
            "material_none": r.get("material_none"),
            "source_notes": notes,
        }
    src = [sources.source(d, "the siting rules' quotes (HB-155)") for d in sorted(docs)]
    return envelope(
        "siting_rules",
        cfg,
        sources,
        src,
        attribution(sources, cfg, sorted(docs)),
        {"rules": rules},
    )


#: HB-207: a suggested action's keys (`packs/src/suggested_actions.yaml`).
ACTION_KEYS = {
    "when",
    "reads",
    "order",
    "quote",
    "doc",
    "page",
    "block",
    "guide_cell",
    "who",
    "by_when",
    "by_when_source",
    "heading",
}


def build_suggested_actions(cfg: dict, sources: SourceSet) -> dict:
    """The suggested actions to consider (HB-207 Part E; DN-029 ADDENDUM-00 section 3)
    from `packs/src/suggested_actions.yaml`. Every quotation, every `who` and every
    `by_when` is re-read on its page of the held original (`_receipt`); an entry with an
    unknown key, both or neither of a quotation and a guide cell, or a `who` its own
    quotation does not carry is refused, naming the entry."""
    path = Path(sources.repo) / cfg["paths"]["suggested_actions"]
    try:
        spec = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise BuildError(f"{path}: {exc}") from None
    if not isinstance(spec.get("actions"), dict) or not spec["actions"]:
        raise BuildError(f"{path}: no `actions` mapping")
    actions, docs = {}, set()
    for aid, a in spec["actions"].items():
        extra = set(a) - ACTION_KEYS
        if extra:
            raise BuildError(f"{path}: action {aid}: unknown key(s) {sorted(extra)}")
        if ("quote" in a) == ("guide_cell" in a):
            raise BuildError(f"{path}: action {aid}: a quote or a guide cell, not both")
        out = {
            "when": a["when"],
            "reads": list(a["reads"]),
            "order": int(a["order"]),
            "guide_cell": a.get("guide_cell"),
            "who": a.get("who"),
        }
        if "quote" in a:
            out["action"] = _receipt(sources, a["doc"], int(a["page"]), a["quote"])
            out["block"] = int(a["block"])
            if a.get("heading"):
                # a table's column heading, printed apart from its cell
                out["heading"] = _receipt(
                    sources, a["doc"], int(a["page"]), a["heading"]
                )
            docs.add(a["doc"])
            if a.get("who") and PP.norm(a["who"]) not in PP.norm(a["quote"]):
                raise BuildError(f"{path}: action {aid}: `who` is not in its quote")
        if a.get("by_when"):
            s = a["by_when_source"]
            out["by_when"] = _receipt(sources, s["doc"], int(s["page"]), a["by_when"])
            docs.add(s["doc"])
        actions[aid] = out
    data = {k: spec[k] for k in ("label", "demonstration", "decides", "no_entry")}
    data["uncovered"] = list(spec.get("uncovered") or [])
    data["actions"] = actions
    src = [
        sources.source(d, "the suggested actions' quotations (HB-207)")
        for d in sorted(docs)
    ]
    return envelope(
        "suggested_actions",
        cfg,
        sources,
        src,
        attribution(sources, cfg, sorted(docs)),
        data,
    )


def _committed_pack(cfg: dict, repo: Path, kind: str) -> dict:
    """A server pack as committed (`packs/<kind>.json`), for an application pack built
    on its own: the routing table reads the ERG pack, never rebuilds it."""
    p = Path(repo) / cfg["paths"]["packs_dir"] / f"{kind}.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BuildError(f"{p}: {exc}") from None


APP_BUILDERS = {
    "materials_properties": build_materials_properties,
    "sigma_curves": build_sigma_curves,
    "release_scenarios": build_release_scenarios,
    "siting_rules": build_siting_rules,
}


def pack_text(pack: dict) -> str:
    return json.dumps(pack, sort_keys=True, indent=1, ensure_ascii=False) + "\n"


def write_pack(pack: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"{pack['kind']}.json"
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(pack_text(pack), encoding="utf-8")
    os.replace(tmp, p)
    return p


def build_packs(cfg: dict, repo: Path = REPO, kinds=KINDS) -> dict:
    """Build the named kinds (and the kinds they depend on) in memory."""
    sources = SourceSet(cfg, repo)
    built: dict = {}
    need = set(kinds)
    if need & {"hazard_classes", "flag_rules", "vocabulary"}:
        need |= {"erg", "cfr172", "hazard_classes"}
    if "vocabulary" in need:
        need.add("flag_rules")
    if "erg" in need:
        built["erg"] = build_erg(cfg, sources)
    if "cfr172" in need:
        built["cfr172"] = build_cfr172(cfg, sources)
    if "cameo" in need:
        built["cameo"] = build_cameo(cfg, sources)
    if "hazard_classes" in need:
        built["hazard_classes"] = build_hazard_classes(
            cfg, sources, built["erg"], built["cfr172"]
        )
    if "flag_rules" in need:
        built["flag_rules"] = build_flag_rules(
            cfg, sources, built["hazard_classes"], built["erg"]
        )
    if "vocabulary" in need:
        built["vocabulary"] = build_vocabulary(cfg, sources, built["flag_rules"])
    if "suggested_actions" in need:
        built["suggested_actions"] = build_suggested_actions(cfg, sources)
    for kind in APP_KINDS:
        if kind in need and kind in APP_BUILDERS:
            built[kind] = APP_BUILDERS[kind](cfg, sources)
    if "release_routing" in need:
        erg = built.get("erg") or _committed_pack(cfg, repo, "erg")
        built["release_routing"] = build_release_routing(cfg, sources, erg)
    return {k: v for k, v in built.items() if k in kinds}


def build_all(cfg: dict, repo: Path = REPO, out_dir: Path | None = None) -> list:
    out_dir = Path(out_dir) if out_dir else Path(repo) / cfg["paths"]["packs_dir"]
    built = build_packs(cfg, repo, KINDS + APP_KINDS)
    return [write_pack(p, out_dir) for p in built.values()]


# ------------------------------------------------------------------ schema
def schema_text(kind: str) -> str:
    schema = {**PACK_MODELS, **APP_PACK_MODELS}[kind].model_json_schema()
    schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", **schema}
    return json.dumps(schema, sort_keys=True, indent=1, ensure_ascii=False) + "\n"


def write_schemas(cfg: dict, repo: Path = REPO) -> list:
    d = Path(repo) / cfg["paths"]["schema_dir"]
    d.mkdir(parents=True, exist_ok=True)
    out = []
    for k in KINDS + APP_KINDS:
        p = d / f"{k}.schema.json"
        p.write_text(schema_text(k), encoding="utf-8")
        out.append(p)
    return out


# ------------------------------------------------------------------ report
def _cell(values: dict, roles) -> str:
    """One report cell for the roles of one source family: "-" if none carries the
    field, the value if every carrying role agrees ("x2" when two or more do), else
    role=value."""
    carried = {r: v for r, v in values.items() if r in roles and v is not None}
    if not carried:
        return "-"
    distinct = sorted(set(carried.values()))
    if len(distinct) == 1:
        n = len(carried)
        return distinct[0].replace("|", "/") + (f" (x{n})" if n > 1 else "")
    return "; ".join(f"{r}={v}" for r, v in sorted(carried.items())).replace("|", "/")


def report(packs_dir: Path) -> str:
    """The cross-check table of the built erg and cfr172 packs, as markdown: one row per
    (entry, field), the value as the PDF (or the CFR XML), PubChem and CAMEO print
    it."""
    lines = []
    for kind in ("erg", "cfr172"):
        pack = json.loads((packs_dir / f"{kind}.json").read_text(encoding="utf-8"))
        lines += [
            f"### {kind}",
            "",
            "| entry | field | PDF / XML | PubChem | CAMEO | status |",
            "|---|---|---|---|---|---|",
        ]
        for key, e in cross_checked_entries(pack["data"]):
            for c in e["cross_checks"]:
                v = c["values"]
                prim = _cell(v, {"erg_pdf", "cfr_xml"})
                pub = _cell(v, {"pubchem_index"})
                cam = _cell(v, {r for r in v if r.startswith("cameo")})
                lines.append(
                    f"| `{key}` | `{c['field']}` | {prim} | {pub} | {cam} "
                    f"| {c['status']} |"
                )
        lines.append("")
    return "\n".join(lines)


def summary(packs_dir: Path) -> dict:
    out = {}
    for kind in KINDS:
        pack = json.loads((packs_dir / f"{kind}.json").read_text(encoding="utf-8"))
        d = pack["data"]
        counts = {"sources": len(pack["sources"])}
        for k, v in d.items():
            if isinstance(v, (list, dict)):
                counts[k] = len(v)
        status: dict = {}
        for _, e in cross_checked_entries(d):
            for c in e["cross_checks"]:
                status[c["status"]] = status.get(c["status"], 0) + 1
        if status:
            counts["cross_checks"] = status
        out[kind] = {"sha256": pack["sha256"], "built_at": pack["built_at"], **counts}
    return out


# ------------------------------------------------------------------ seed diff (HB-03b)
def seed_diff(old: dict, new: dict) -> list:
    """Every difference between the seed rows of an earlier ERG pack (HB-03's) and the
    any-UN pack (HB-03b step 5): names, guide, Table 1 and Table 3 values, guide titles,
    section items and evacuation distances. Each is (where, field, old, new, locator).
    """
    out = []
    od, nd = old["data"], new["data"]
    for un in od["seed_un_numbers"]:
        o, n = od["materials"][un], nd["materials"][un]
        for f in ("guide", "tih"):
            if o[f] != n[f]:
                out.append((f"UN{un}", f, o[f], n[f], None))
        on = [x["name"] for x in o["names"]]
        nn = [x["name"] for x in n["names"]]
        if on != nn:
            out.append((f"UN{un}", "names", on, nn, n["names"][0]["locator"]))
        by = {e["printed_name"]: e for e in n["table1"]}
        for e in o["table1"]:
            ne = by.get(e["name"])
            if ne is None:
                out.append(
                    (
                        f"UN{un}",
                        f"table1[{e['name']}]",
                        "present",
                        "absent",
                        e["locator"],
                    )
                )
                continue
            for f in ("small", "large", "large_refer_to_table3", "locator"):
                if e[f] != ne[f]:
                    out.append(
                        (
                            f"UN{un}",
                            f"table1[{e['name']}].{f}",
                            e[f],
                            ne[f],
                            ne["locator"],
                        )
                    )
        if (o["table3"] is None) != (n["table3"] is None):
            out.append(
                (f"UN{un}", "table3", bool(o["table3"]), bool(n["table3"]), None)
            )
        elif o["table3"]:
            nr = {r["container"]: r for r in n["table3"]["rows"]}
            for r in o["table3"]["rows"]:
                x = nr.get(r["container"])
                for f in ("isolate", "day", "night"):
                    if x is None or r[f] != x[f]:
                        out.append(
                            (
                                f"UN{un}",
                                f"table3[{r['container']}].{f}",
                                r[f],
                                x and x[f],
                                n["table3"]["locator"],
                            )
                        )
    for g, o in od["guides"].items():
        n = nd["guides"][g]
        if o["title"] != n["title"]:
            out.append((f"guide {g}", "title", o["title"], n["title"], None))
        if o["evacuation"] != n["evacuation"]:
            out.append(
                (
                    f"guide {g}",
                    "evacuation",
                    o["evacuation"],
                    n["evacuation"],
                    n["sections"]["public_safety"]["locator"],
                )
            )
        for k, sec in o["sections"].items():
            ot = [(i["kind"], i["text"]) for i in sec["items"]]
            nt = [(i["kind"], i["text"]) for i in n["sections"][k]["items"]]
            sm = difflib.SequenceMatcher(None, ot, nt, autojunk=False)
            for op, i1, i2, j1, j2 in sm.get_opcodes():
                if op != "equal":
                    out.append(
                        (
                            f"guide {g}",
                            f"sections.{k}",
                            ot[i1:i2],
                            nt[j1:j2],
                            n["sections"][k]["locator"],
                        )
                    )
    return out


# ------------------------------------------------------------------ hydrography
def probe_hydrography(
    cfg: dict, repo: Path, log_path: Path, user_agent: str | None = None
) -> int:
    """One GET per candidate service description, through scripts/probe_apis.py `run`
    (resume by key: a service already probed is not requested again)."""
    spec = importlib.util.spec_from_file_location(
        "probe_apis", Path(repo) / "scripts" / "probe_apis.py"
    )
    pa = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pa)
    if user_agent is None:
        from hazbrief.config import settings

        user_agent = settings.user_agent
    apis = [
        {"id": s["id"], "probe": s["probe"]} for s in cfg["hydrography"]["services"]
    ]
    allow = tuple(h.lower() for h in cfg["hydrography"]["probe_hosts"])
    pcfg = pa.load_config(Path(repo) / cfg["paths"]["probe_config"])
    return pa.run(apis, pcfg, Path(log_path), allow, user_agent)


# ---------------------------------------------------------- HB-119: threshold tables
# HB-119 step 4 and ADDENDUM-00: the brief's materials resolver takes a toxic material's
# level of concern for a material the properties pack does not seed from two held
# tables, parsed here once with the page of every row: the EPA's compiled AEGL values
# (AEGL-2 first) and the NIOSH Pocket Guide's IDLH (the fallback, where no AEGL is
# published). A row this parser cannot read to its printed columns is kept as printed,
# `unparsed` with the reason, never guessed (standards s4). The outputs sit beside the
# other parsed sources in packs/src/ (flag_rules_mined.jsonl's precedent): they are not
# packs, and the server never reads them.

#: A CAS Registry Number as the two tables print it.
_CAS = r"\d{2,7}-\d{2}-\d"
#: An entry's name line in the AEGL table: "74-90-8 Hydrogen cyanide (ppm)"; the unit
#: is the last parenthesis that opens with ppm or mg/m.
_AEGL_HEAD = re.compile(rf"^\*?(?:({_CAS})\s+)?\*?(.*)\((ppm|mg/m)")
_AEGL_ROW = re.compile(r"^AEGL\s*([123])\s+(?!-)(.*)$")
_AEGL_BELOW = re.compile(r"^AEGL\s*([123])\s+-\s+(.*)$")
#: One printed cell: a number, NR (not recommended), ND (not determined) or a
#: "see below" pointer, with the asterisks that mark a fraction of the LEL.
_AEGL_CELL = re.compile(
    r"(\*{0,3})\s*(see below|NR|ND|\d[\d,]*(?:\.\d+)?|\.\d+)(\*{0,3})", re.I
)
_AEGL_BELOW_SEG = re.compile(r"(.+?)=\s*(\*{0,3})\s*([\d,]+(?:\.\d+)?)\s*ppm")


def _aegl_columns(spec: str) -> list[str]:
    """`10 min/30 min/60 min/4 hr/8 hr` or `4hr` as the columns line names them."""
    out = []
    for part in spec.split("/"):
        m = re.fullmatch(r"\s*(\d+)\s*(min|hr)\s*", part)
        if not m:
            raise ValueError(part)
        out.append(f"{m.group(1)} {m.group(2)}")
    return out


def _aegl_cells(text: str) -> list[dict]:
    """The printed cells of one AEGL row: bracketed and parenthesised alternates (the
    mg/m3 and the other unit some rows print beside each value) are dropped first."""
    text = re.sub(r"[\[(][^\])]*[\])]", " ", text)
    cells = []
    for m in _AEGL_CELL.finditer(text):
        lead, val, trail = m.groups()
        mark = (lead or "") + (trail or "")
        v = val.lower()
        if v == "see below":
            cells.append({"kind": "see_below", "mark": mark, "as_printed": m.group(0)})
        elif v in ("nr", "nd"):
            cells.append({"kind": v, "mark": mark, "as_printed": m.group(0)})
        else:
            cells.append(
                {
                    "kind": "number",
                    "value": float(val.replace(",", "")),
                    "mark": mark,
                    "as_printed": m.group(0).strip(),
                }
            )
    return cells


def _aegl_table(sources: SourceSet, spec: dict) -> dict:
    doc = spec["doc"]
    columns = spec["columns_quote"].split(" ")
    columns = [f"{columns[i]} {columns[i + 1]}" for i in range(0, len(columns), 2)]
    status_re = re.compile(spec["status_pattern"])
    lines = []  # (page, status, line)
    for n, page in enumerate(sources.pages(doc), 1):
        raw = [ln.strip() for ln in page.splitlines() if ln.strip()]
        m = status_re.search(raw[0]) if raw else None
        if m is None:
            continue  # the contents and the revision history name no status
        lines += [(n, m.group(1), ln) for ln in raw[1:]]
    entries, cur = [], None
    for i, (page, status, ln) in enumerate(lines):
        if PP.norm(ln) == spec["columns_quote"]:
            head_i = next(
                (
                    j
                    for j in range(i - 1, max(i - 4, -1), -1)
                    if _AEGL_HEAD.match(lines[j][2])
                ),
                None,
            )
            if head_i is None:
                raise BuildError(f"{doc} p. {page}: a columns line with no entry name")
            head = PP.norm(" ".join(x[2] for x in lines[head_i:i]))
            hm = _AEGL_HEAD.match(head)
            cur = {
                "cas": hm.group(1),
                "name": PP.norm(hm.group(2)),
                "unit": "ppm" if hm.group(3) == "ppm" else "mg/m3",
                "status": lines[head_i][1],
                "page": lines[head_i][0],
                "heading": head,
                "rows": {},
                "below": [],
            }
            entries.append(cur)
            continue
        if cur is None:
            continue
        rm = _AEGL_ROW.match(ln)
        if rm and f"AEGL-{rm.group(1)}" not in cur["rows"]:
            cur["rows"][f"AEGL-{rm.group(1)}"] = (page, ln, rm.group(2))
            continue
        bm = _AEGL_BELOW.match(ln)
        if bm:
            cur["below"].append((page, ln, bm.group(1), bm.group(2)))
    out = []
    for e in entries:
        below: dict = {}
        for page, ln, level, rest in e["below"]:
            for seg in rest.split(";"):
                sm = _AEGL_BELOW_SEG.search(seg)
                if not sm:
                    continue
                try:
                    cols = _aegl_columns(sm.group(1))
                except ValueError:
                    continue
                for c in cols:
                    below[(f"AEGL-{level}", c)] = {
                        "value": float(sm.group(3).replace(",", "")),
                        "mark": sm.group(2),
                        "receipt": _receipt(sources, doc, page, ln),
                    }
        levels = {}
        for level in ("AEGL-1", "AEGL-2", "AEGL-3"):
            row = e["rows"].get(level)
            if row is None:
                levels[level] = {"unparsed": "no row printed under the entry"}
                continue
            page, ln, rest = row
            receipt = _receipt(sources, doc, page, ln)
            cells = _aegl_cells(rest)
            if len(cells) != len(columns):
                levels[level] = {
                    "unparsed": f"the row prints {len(cells)} cells, not the "
                    f"{len(columns)} columns {spec['columns_quote']!r}",
                    "receipt": receipt,
                }
                continue
            values = {}
            for col, cell in zip(columns, cells):
                if cell["kind"] == "number":
                    values[col] = {
                        "value": cell["value"],
                        "mark": cell["mark"],
                        "as_printed": cell["as_printed"],
                    }
                elif cell["kind"] == "see_below" and (level, col) in below:
                    b = below[(level, col)]
                    values[col] = {
                        "value": b["value"],
                        "mark": b["mark"],
                        "as_printed": f"{cell['as_printed']}; {b['value']:g} ppm",
                        "see_below": b["receipt"],
                    }
                else:
                    why = {
                        "nr": "NR: not recommended due to insufficient data",
                        "nd": "ND: not determined",
                        "see_below": "see below, and no line below gives it",
                    }[cell["kind"]]
                    values[col] = {"value": None, "reason": why}
            levels[level] = {"values": values, "receipt": receipt}
        out.append(
            {k: e[k] for k in ("cas", "name", "unit", "status", "page", "heading")}
            | {"levels": levels}
        )
    return {
        "doc_id": doc,
        "sha256": sources.raw_sha256(doc),
        "columns": columns,
        "entries": out,
    }


_NPG_FIELD = re.compile(r"CAS#:\s*(.*?)\s*RTECS#:.*?IDLH:\s*(.*?)\s*Conversion:", re.S)


def _npg_name(before: str) -> str:
    """An entry's name: the lines after the previous entry's last First Aid field
    (`Eye:`, `Skin:`, `Breath:` or `Swallow:`, whichever it ends on) and the alphabet
    tab (a lone letter), up to `Formula:`."""
    tail = re.split(r"(?m)^\s*(?:Eye|Skin|Breath|Swallow):[^\n]*\n", before)[-1]
    keep = [
        ln.strip()
        for ln in tail.splitlines()
        if ln.strip() and not re.fullmatch(r"[A-Z]|\d+", ln.strip())
    ]
    return PP.norm(" ".join(keep))


def _idlh_table(sources: SourceSet, spec: dict) -> dict:
    doc = spec["doc"]
    out = []
    for n, page in enumerate(sources.pages(doc), 1):
        if "IDLH:" not in page or "CAS#:" not in page:
            continue
        starts = [m.start() for m in re.finditer(r"Formula:", page)]
        for k, at in enumerate(starts):
            end = starts[k + 1] if k + 1 < len(starts) else len(page)
            body = page[at:end]
            fm = _NPG_FIELD.search(body)
            if fm is None:
                continue
            prev = starts[k - 1] if k else 0
            name = _npg_name(page[prev:at])
            # The text layer sometimes interleaves the name and the page number into
            # the CAS field ("CAS#: Heptachlor 157 76-44-8", p. 187): the number is
            # the field's CAS-shaped token, and a name not found before `Formula:`
            # is the field's words.
            field = PP.norm(fm.group(1))
            cm = re.search(_CAS, field)
            cas = cm.group(0) if cm else None
            if not name:
                name = PP.norm(re.sub(rf"{_CAS}|\b\d+\b", " ", field)) or None
            idlh = PP.norm(fm.group(2))
            dot = re.search(r"DOT:\s*(.*?)\s*Synonyms", body, re.S)
            dot_text = PP.norm(dot.group(1)) if dot else ""
            vm = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*(ppm|mg/m3)", idlh)
            quote = PP.norm(body[fm.start() : fm.end() - len("Conversion:")])
            entry = {
                "name": name,
                "cas": cas,
                "un_guide": [
                    {"un": u, "guide": g}
                    for u, g in re.findall(r"\b(\d{4})\s+(\d{3}P?)\b", dot_text)
                ],
                "page": n,
                "as_printed": idlh,
                "carcinogen": idlh.startswith("Ca"),
                "receipt": _receipt(sources, doc, n, quote),
            }
            if vm:
                entry |= {
                    "value": float(vm.group(1).replace(",", "")),
                    "unit": vm.group(2),
                    "reason": None,
                }
            else:
                entry |= {
                    "value": None,
                    "unit": None,
                    "reason": f"the guide prints no IDLH value: {idlh!r}",
                }
            out.append(entry)
    return {"doc_id": doc, "sha256": sources.raw_sha256(doc), "entries": out}


def build_threshold_tables(cfg: dict, repo: Path = REPO) -> dict:
    """`{path: table}` for the two threshold tables (`build_config.yaml` `thresholds`).
    Every row's receipt is verified on its held page by `_receipt`."""
    spec = cfg.get("thresholds")
    if not spec or set(spec) != {"aegl", "idlh"}:
        raise BuildError("build_config.yaml `thresholds` needs `aegl` and `idlh`")
    sources = SourceSet(cfg, repo)
    out = {}
    for key, fn in (("aegl", _aegl_table), ("idlh", _idlh_table)):
        table = fn(sources, spec[key])
        table["built_by"] = f"scripts/build_packs.py thresholds ({key})"
        out[spec[key]["out"]] = table
    return out


# ------------------------------------------------------------------ CLI
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "command",
        choices=(
            *KINDS,
            *APP_KINDS,
            "all",
            "schema",
            "report",
            "summary",
            "hydrography",
            "seed-diff",
            "thresholds",
        ),
    )
    ap.add_argument("--old", type=Path, help="seed-diff: the earlier erg pack")
    ap.add_argument(
        "--config", type=Path, default=REPO / "packs" / "src" / "build_config.yaml"
    )
    ap.add_argument(
        "--out", type=Path, default=None, help="packs directory (default: config)"
    )
    a = ap.parse_args(argv)
    try:
        cfg = load_config(a.config)
        out = a.out or REPO / cfg["paths"]["packs_dir"]
        if a.command == "schema":
            for p in write_schemas(cfg):
                print(f"[schema] {p.relative_to(REPO)}")
        elif a.command == "report":
            print(report(out))
        elif a.command == "seed-diff":
            old = json.loads(Path(a.old).read_text(encoding="utf-8"))
            new = json.loads((out / "erg.json").read_text(encoding="utf-8"))
            print(json.dumps(seed_diff(old, new), indent=1, ensure_ascii=False))
        elif a.command == "summary":
            print(json.dumps(summary(out), indent=1, sort_keys=True))
        elif a.command == "thresholds":
            for rel, table in build_threshold_tables(cfg, REPO).items():
                p = REPO / rel
                p.write_text(
                    json.dumps(table, indent=1, ensure_ascii=False, sort_keys=True)
                    + "\n",
                    encoding="utf-8",
                )
                print(f"[thresholds] {rel}: {len(table['entries'])} entries")
        elif a.command == "hydrography":
            return probe_hydrography(
                cfg, REPO, REPO / cfg["paths"]["hydrography_probe_log"]
            )
        else:
            kinds = KINDS + APP_KINDS if a.command == "all" else (a.command,)
            for kind, pack in build_packs(cfg, REPO, kinds).items():
                p = write_pack(pack, out)
                print(
                    f"[pack] {kind}: {p} sha256={pack['sha256'][:12]} "
                    f"built_at={pack['built_at']}"
                )
        return 0
    except (BuildError, PP.ParseError, F.ConfigError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
