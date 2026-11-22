"""The dense-gas client: SLAB from the source term to a footprint (DN-020 section 3.2;
HB-111 Part B and ADDENDUM-01).

Three steps, each its own function, each returning a value or a one-line `error` and
`hint`, never raising into the brief:

1. `slab_input(result, met, loc, spec=)`: SLAB's input deck from HB-110's
   `source_term.Result`, the weather (`source_term.Met`) and the level of concern. The
   fields, their order and units are the SLAB user's guide's Table 1
   (`epa-slab-users-guide-1990`, PDF p. 50; HB-102 `inventory.md` section 3), one value
   per record in `format (f10.3)` (SLAB.FOR line 204). Where each value comes from
   (every field is defined in Table 1; a page is named where the guide says more):

   - IDSPL: `result.model` (`dense_gas.idspl`): two-phase 2, pool 1.
   - WMS, TBP: `material.mw_kg_mol`, `material.tb_k`.
   - CPS: `material.vapour_cp_j_mol_k / mw`, the pack's
     `thermodynamics.vapour_heat_capacity_j_mol_k` (HB-126); `None` is an error.
   - CMEDO: `result["aerosol_fraction"]` (two-phase), 0 (pool); section 3.1.2.4,
     PDF p. 53.
   - DHE, CPSL, RHOSL: `material.hv_j_kg`, `cpl_j_kg_k`, `rhol_kg_m3`.
   - SPB, SPC: SLAB's default, -1 and 0 (`dense_gas.spb`, `spc` say why); PDF p. 53.
   - TS: `result["source_temperature_k"]` (two-phase) or `["pool_temperature_k"]`.
   - QS, TSD: `result["mean_rate_kg_s"]`, `["duration_s"]` (the puff's values).
   - AS: pool `["max_area_m2"]`; jet RHOSL A_r / rho_m from `["hole_area_m2"]`;
     section 3.1.3.3, PDF p. 56.
   - QTIS: 0, since neither model is SLAB's instantaneous source.
   - HS: pool 0; jet `dense_gas.jet_height_m`, a labelled assumption; section
     3.1.3.6, PDF p. 57.
   - TAV, XFFM, ZP: `dense_gas.averaging_time_s` (the level of concern's duration),
     `max_distance_m`, `receptor_height_m`.
   - Z0, ZA, UA, TA, RH: the ambient's `z0_m`, `wind_height_m`, `wind_ms`,
     `temperature_k`, `rh_pct`.
   - STAB: the Pasquill class, A to F as 1 to 6 (`dense_gas.stab`).

   The hole's area is never AS: for a two-phase jet the guide defines AS as "the area
   of the source after it has flashed and formed a liquid droplet-vapor mixture", AS =
   RHOSL A_r / rho_m (PDF p. 56). Nothing is defaulted: a property the pack does not
   hold (CPS for gasoline and diesel; HB-126 filled it for the five pure seed
   materials), the LPG proxy (issue `9e47d690` is HB-112's), or a relative humidity the
   weather does not carry is an `error`.
2. `run_slab(deck, spec)`: SLAB's output, from the `hazbrief-models` image (`docker run
   --rm -i --network none --pull never`), or from the binary `HAZBRIEF_SLAB_BIN` names,
   both through `slab_driver.run_deck`'s logic. A missing image, docker or binary is an
   `error` with the hint that fixes it.
3. `footprint(output, loc, lat=, lon=, toward_deg=, spec=)`: SLAB's time-averaged
   concentration table on the receptor plane ("concentration in the z = ... plane": x,
   then c at y/bbc = 0, 0.5, ..., 2.5) read into the downwind distance and the
   crosswind half-width at which it falls to the level of concern, each interpolated
   between printed rows linearly in distance and in log concentration, and drawn as a
   polygon in the footprint's azimuthal equidistant frame (`hazbrief.geometry.offset`,
   the frame the ERG zones use), oriented toward `toward_deg`, the puff's wind (HB-72,
   HB-75). A level still exceeded at SLAB's last row or its widest printed ratio is
   reported as reaching beyond it (`beyond_table`, `beyond_width`), never as ending
   there.

`model_footprint` chains the three for one source term, and returns the source term's
own reason as its error when there is none (ADDENDUM-01 section 1).

The level of concern (`level_of_concern`): AEGL-2 at SLAB's averaging time, the pack's
cell (`materials_properties` `levels_of_concern`, HB-66) at `averaging_time_s / 60`
minutes; the ERG's own basis is the 60-minute AEGL-2 (DN-020 section 3.2).

No brief layer reads this yet (HB-112).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from hazbrief import geometry as G
from hazbrief.brief import settings as S
from hazbrief.brief import slab_driver
from hazbrief.brief import source_term as ST

#: Table 1's problem fields in input order, after IDSPL and NCALC (PDF p. 50).
PROBLEM_FIELDS = (
    "wms cps tbp cmedo dhe cpsl rhosl spb spc ts qs as tsd qtis hs "
    "tav xffm zp1 zp2 zp3 zp4"
).split()
#: The met block, which a further problem repeats (SLAB.FOR lines 205-238): ALA is read
#: only when STAB is 0.
MET_FIELDS = ("z0", "za", "ua", "ta", "rh", "stab")


@dataclass
class Outcome:
    """`error` and `hint` are one line each when the step could not be done."""

    error: str | None = None
    hint: str | None = None


@dataclass
class LevelOfConcern:
    """A level of concern as SLAB's volume fraction (`ppm` x 1e-6) at SLAB's averaging
    time (`minutes`). `words` is the label's, `legend` the legend entry's (HB-112
    ADDENDUM-00), each empty where a caller states only the number."""

    kind: str
    ppm: float
    minutes: float
    source: str
    basis: str
    words: str = ""
    legend: str = ""

    @property
    def volume_fraction(self) -> float:
        return self.ppm * 1e-6

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "ppm": self.ppm,
            "minutes": self.minutes,
            "source": self.source,
            "basis": self.basis,
            "words": self.words,
            "legend": self.legend,
        }


@dataclass
class LevelOutcome(Outcome):
    level: LevelOfConcern | None = None


@dataclass
class DeckOutcome(Outcome):
    deck: str | None = None
    label: list[str] = field(default_factory=list)


@dataclass
class RunOutcome(Outcome):
    output: str | None = None
    route: str | None = None
    #: what ran it: the image's id (`docker image inspect`) or the binary's sha256
    engine_id: str | None = None
    #: "image" or "binary"
    engine_kind: str | None = None


@dataclass
class FootprintOutcome(Outcome):
    feature: dict | None = None


# ── the deck ─────────────────────────────────────────────────────────────────────────


def f10(v: float) -> str:
    """A real in SLAB's `format (f10.3)`: ten columns, with its decimal point always
    written, because a field without one is read with three implied decimals."""
    v = float(v)
    if v == 0.0:
        return f"{'0.':>10}"
    for digits in range(8, 0, -1):
        s = f"{v:.{digits}g}".upper()
        mant, _, exp = s.partition("E")
        if "." not in mant:
            mant += "."
        if exp:
            s = f"{mant}E{int(exp)}"
        else:
            s = mant
        if len(s) <= 10:
            return f"{s:>10}"
    raise ValueError(f"{v!r} does not fit SLAB's ten-column field")


def deck_text(problems: list[dict]) -> str:
    """The input deck for one or more problems (a further problem repeats the met
    block only, as INPR1 does), ending in SLAB's stop record, a negative Z0."""
    p0 = problems[0]
    lines = [f"{int(p0['idspl']):5d}", f"{int(p0['ncalc']):5d}"]
    lines += [f10(p0[f]) for f in PROBLEM_FIELDS]
    for p in problems:
        lines += [f10(p[f]) for f in MET_FIELDS]
        if p["stab"] == 0.0:
            lines.append(f10(p["ala"]))
    lines.append(f10(-1.0))
    return "\n".join(lines) + "\n"


def read_deck(text: str) -> list[dict]:
    """The problems of an input deck, as SLAB reads it (SLAB.FOR lines 196-238)."""
    vals = [float(v) for v in text.split() if v != "\x1a"]
    head = ["idspl", "ncalc", *PROBLEM_FIELDS]
    first = dict(zip(head, vals[: len(head)]))
    rest = vals[len(head) :]
    problems = []
    while rest and rest[0] >= 0.0:
        p = dict(problems[-1] if problems else first)
        p.pop("ala", None)
        p.update(zip(MET_FIELDS, rest[: len(MET_FIELDS)]))
        rest = rest[len(MET_FIELDS) :]
        if p["stab"] == 0.0:
            p["ala"], rest = rest[0], rest[1:]
        problems.append(p)
    return problems


def material_fields(m: ST.Material) -> dict:
    """The material's SLAB lines that need no choice: per kg, as Table 1 takes them."""
    return {
        "wms": m.mw_kg_mol,
        "tbp": m.tb_k,
        "dhe": m.hv_j_kg,
        "cpsl": m.cpl_j_kg_k,
        "rhosl": m.rhol_kg_m3,
    }


def _flashed_area(spec: dict, m: ST.Material, cmedo: float, hole_m2: float) -> float:
    """The guide's AS for a two-phase jet (section 3.1.3.3, PDF p. 56):
    AS = RHOSL A_r / rho_m, rho_m = 1 / [(1 - CMEDO)/RHOS + CMEDO/RHOSL],
    RHOS = WMS P_a / (R_c TBP)."""
    pa = spec["ambient_pressure_pa"]["value"]
    rc = spec["gas_constant_j_mol_k"]["value"]
    rhos = m.mw_kg_mol * pa / (rc * m.tb_k)
    rho_m = 1.0 / ((1.0 - cmedo) / rhos + cmedo / m.rhol_kg_m3)
    return m.rhol_kg_m3 * hole_m2 / rho_m


def _un(m: ST.Material) -> str:
    return f"UN{m.un}" if m.un else m.name


def proxy_of(un: str | None, pack: dict | None) -> dict | None:
    """The pack's proxy block for a material whose entry is a proxy (LPG, UN1075,
    takes propane's properties; `thermodynamics.proxy`), with the proxied material's
    name; None when the material is its own. HB-112 runs SLAB on the proxy's values
    and labels it (issue `9e47d690`; DN-020 ADDENDUM-01 item 4), where HB-111 refused.
    `Material` carries the proxy's values without a flag, so the pack is the signal."""
    if pack is None or not un:
        return None
    mats = pack.get("materials") or {}
    proxy = ((mats.get(un) or {}).get("thermodynamics") or {}).get("proxy")
    if not proxy:
        return None
    of = str(proxy["properties_of"]).removeprefix("UN")
    return {**proxy, "of_un": of, "of_name": (mats.get(of) or {}).get("name") or of}


def proxy_line(proxy: dict, spec: dict) -> str:
    """The label's line for a proxied material: the pack's sentence and its page."""
    rec = proxy.get("receipt") or {}
    return spec["proxy_line"].format(
        label=proxy["label"],
        of_un=proxy["of_un"],
        doc=rec.get("doc_id"),
        page=rec.get("page"),
        quote=rec.get("quote"),
    )


def proxy_legend(proxy: dict | None, spec: dict) -> str:
    """ " (propane, proxy for LPG)" from the pack's "propane properties used for LPG";
    empty for a material that is its own, or a sentence of another shape."""
    if not proxy:
        return ""
    hit = re.match(spec["proxy_pattern"], proxy.get("label") or "")
    if hit is None:
        return f" ({proxy.get('label')})"
    return spec["proxy_legend"].format(**hit.groupdict())


def slab_input(
    result: ST.Result,
    met: ST.Met,
    loc: LevelOfConcern,
    *,
    spec: dict,
    pack: dict | None = None,
) -> DeckOutcome:
    """SLAB's input deck for one source term, or a one-line error naming what is not
    held. `pack` (the materials pack's data) is read only to label a proxied material:
    `Material` carries the proxy's values without a flag, so the pack entry's
    `thermodynamics.proxy` is the signal (HB-112 ADDENDUM-02 section 3, LPG)."""
    hints = spec["hints"]
    m, r = result.material, result.result
    label: list[str] = []
    proxy = proxy_of(m.un, pack)
    if proxy is not None and "proxy_line" in spec:
        label.append(proxy_line(proxy, spec))
    idspl = spec["idspl"].get(result.model)
    if idspl is None:
        return DeckOutcome(
            error=f"not applicable: SLAB takes no source of the model {result.model!r}",
            hint=hints["source_term"],
        )
    if m.vapour_cp_j_mol_k is None:
        return DeckOutcome(
            error=(
                f"not available: the properties pack does not hold the vapour heat "
                f"capacity (SLAB's CPS) for {_un(m)} {m.name}"
            ),
            hint=hints["property"],
        )
    amb = met.ambient
    if amb.rh_pct is None:
        return DeckOutcome(
            error=(
                "not available: no relative humidity is held for the spill (SLAB's RH)"
            ),
            hint=hints["weather"],
        )
    stab = spec["stab"].get(str(amb.stability).strip().upper())
    if stab is None:
        return DeckOutcome(
            error=f"not available: the stability class {amb.stability!r} is not A to F",
            hint=hints["weather"],
        )
    p = {"idspl": idspl, "ncalc": spec["ncalc"], **material_fields(m)}
    p["cps"] = m.vapour_cp_j_mol_k / m.mw_kg_mol
    p["spb"], p["spc"] = spec["spb"], spec["spc"]
    p["qs"], p["tsd"], p["qtis"] = r["mean_rate_kg_s"], r["duration_s"], 0.0
    if idspl == 2:
        p["cmedo"] = r["aerosol_fraction"]
        p["ts"] = r["source_temperature_k"]
        p["as"] = _flashed_area(spec, m, p["cmedo"], r["hole_area_m2"])
        p["hs"] = spec["jet_height_m"]
        label.append(
            f"source area {p['as']:.4g} m2: the flashed two-phase jet's, RHOSL x hole "
            f"{r['hole_area_m2']:.4g} m2 / mixture density (SLAB user's guide section "
            "3.1.3.3, PDF p. 56)"
        )
        label.append(spec["jet_height_label"])
    else:
        p["cmedo"] = 0.0
        p["ts"] = r["pool_temperature_k"]
        p["as"] = r["max_area_m2"]
        p["hs"] = 0.0
        label.append(
            f"source area {p['as']:.4g} m2: the pool's largest (SLAB user's guide "
            'section 3.1.3.3, PDF p. 56: "AS is the area of the evaporating pool")'
        )
    if r.get("instantaneous"):
        label.append(
            f"duration {r['duration_s']:g} s, the one-minute floor; computed "
            f"{r['computed_duration_s']:.3g} s"
        )
    p["tav"] = loc.minutes * 60.0
    p["xffm"] = spec["max_distance_m"]
    p["zp1"], p["zp2"], p["zp3"], p["zp4"] = spec["receptor_height_m"], 0.0, 0.0, 0.0
    p.update(
        z0=amb.z0_m,
        za=amb.wind_height_m,
        ua=amb.wind_ms,
        ta=amb.temperature_k,
        rh=amb.rh_pct,
        stab=stab,
    )
    label.append(
        "saturation pressure: SLAB's default, the Clapeyron equation through TBP and "
        "DHE (SPB -1, SPC 0; SLAB user's guide PDF p. 53)"
    )
    try:
        deck = deck_text([p])
    except ValueError as exc:
        return DeckOutcome(error=f"not available: {exc}", hint=hints["source_term"])
    return DeckOutcome(deck=deck, label=label)


# ── the run ──────────────────────────────────────────────────────────────────────────


def _unavailable(spec: dict, why: str) -> str:
    """No image, no docker, no binary: the layer's entry (HB-112 step 1), "dense-gas
    model not available on this machine", with what is missing."""
    words = spec.get("unavailable")
    return words.format(why=why) if words else why


def run_slab(deck: str, spec: dict, *, binary: str | None | object = ...) -> RunOutcome:
    """SLAB's output for `deck`. `binary`: a path runs that binary (the development
    route); None runs the image; left out, HAZBRIEF_SLAB_BIN decides (empty: the
    image)."""
    hints = spec["hints"]
    timeout = float(spec["timeout_s"])
    if binary is ...:
        binary = S.slab_bin() or None
    if binary:
        try:
            out = slab_driver.run_deck(binary, deck.encode("latin-1"), timeout)
        except slab_driver.SlabRunError as exc:
            if "not an executable" in str(exc):
                return RunOutcome(
                    error=_unavailable(spec, f"SLAB did not run: {exc}"),
                    hint=hints["no_binary"],
                )
            return RunOutcome(
                error=f"SLAB did not run: {exc}", hint=hints["run_failed"]
            )
        return RunOutcome(
            output=out.decode("latin-1"),
            route=f"binary {binary}",
            engine_id=hashlib.sha256(Path(binary).read_bytes()).hexdigest(),
            engine_kind="binary",
        )
    docker = shutil.which(spec["docker"])
    if docker is None:
        return RunOutcome(
            error=_unavailable(
                spec, f"SLAB did not run: {spec['docker']} is not installed"
            ),
            hint=hints["no_docker"],
        )
    cmd = [
        docker,
        "run",
        "--rm",
        "-i",
        "--network",
        "none",
        "--pull",
        "never",
        spec["image"],
    ]
    try:
        proc = subprocess.run(
            cmd,
            input=deck.encode("latin-1"),
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return RunOutcome(
            error=f"SLAB did not finish within {timeout:g} s", hint=hints["run_failed"]
        )
    if proc.returncode == 0:
        # the image that ran, by its id, for the label (HB-112 ADDENDUM-02 section 6)
        inspect = subprocess.run(
            [docker, "image", "inspect", "--format", "{{.Id}}", spec["image"]],
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        if inspect.returncode != 0:
            return RunOutcome(
                error=(
                    f"SLAB ran, but the models image {spec['image']} could not be "
                    f"inspected for its id ({inspect.stderr.decode().strip()})"
                ),
                hint=hints["no_image"],
            )
        return RunOutcome(
            output=proc.stdout.decode("latin-1"),
            route=f"image {spec['image']}",
            engine_id=inspect.stdout.decode().strip(),
            engine_kind="image",
        )
    msg = proc.stderr.decode("latin-1").strip().splitlines()
    last = msg[-1] if msg else f"exit {proc.returncode}"
    if proc.returncode == 125:  # docker's own failure: no daemon, no such image
        return RunOutcome(
            error=_unavailable(
                spec,
                f"SLAB did not run: the models image {spec['image']} is not "
                f"available ({last})",
            ),
            hint=hints["no_image"],
        )
    return RunOutcome(error=f"SLAB did not run: {last}", hint=hints["run_failed"])


# ── the output ───────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PlaneRow:
    """One row of a "concentration in the z = ... plane" table."""

    x: float
    t_max: float
    duration: float
    bbc: float
    c: tuple[float, ...]  # at y/bbc = 0, 0.5, ..., 2.5


def _floats(tokens: list[str]) -> list[float] | None:
    try:
        return [float(t) for t in tokens]
    except ValueError:
        return None


def parse_output(text: str) -> dict:
    """The first problem's time-averaged plane tables, keyed by the plane's height."""
    planes: dict[float, list[PlaneRow]] = {}
    current: list[PlaneRow] | None = None
    for line in text.replace("\r", "").splitlines():
        if "concentration in the z =" in line:
            z = float(line.split("z =")[1].split("plane")[0])
            if z in planes:  # a second problem's tables: the client writes one
                break
            current = planes.setdefault(z, [])
            continue
        if current is None:
            continue
        toks = line.split()
        vals = _floats(toks) if len(toks) == 10 else None
        if vals is not None:
            current.append(
                PlaneRow(vals[0], vals[1], vals[2], vals[3], tuple(vals[4:]))
            )
        elif current and toks:
            current = None  # the table ended
    return {"planes": planes}


@dataclass(frozen=True)
class Reach:
    distance_m: float | None
    beyond_table: bool


def _cross(a: float, ca: float, b: float, cb: float, level: float) -> float:
    """Where c falls to `level` between (a, ca) and (b, cb), linear in log c."""
    if ca <= 0 or cb <= 0 or ca == cb:
        return a
    return a + (math.log(ca) - math.log(level)) / (math.log(ca) - math.log(cb)) * (
        b - a
    )


def downwind_reach(rows: list[PlaneRow], level: float) -> Reach:
    """The farthest distance at which the centreline concentration is at `level`."""
    above = [i for i, r in enumerate(rows) if r.c[0] >= level]
    if not above:
        return Reach(None, False)
    i = above[-1]
    if i == len(rows) - 1:
        return Reach(rows[i].x, True)
    a, b = rows[i], rows[i + 1]
    return Reach(_cross(a.x, a.c[0], b.x, b.c[0], level), False)


def half_width(row: PlaneRow, level: float, ratios: list[float]) -> tuple[float, bool]:
    """(half-width in m, beyond the widest printed ratio) at which `row` falls to
    `level`; 0 when the centreline is below it."""
    if row.c[0] < level:
        return 0.0, False
    for k in range(1, len(ratios)):
        if row.c[k] < level:
            r = _cross(ratios[k - 1], row.c[k - 1], ratios[k], row.c[k], level)
            return r * row.bbc, False
    return ratios[-1] * row.bbc, True


def footprint(
    output: str,
    loc: LevelOfConcern,
    *,
    lat: float,
    lon: float,
    toward_deg: float,
    spec: dict,
) -> FootprintOutcome:
    """SLAB's output read into a GeoJSON Feature at the level of concern."""
    hints = spec["hints"]
    z = float(spec["receptor_height_m"])
    planes = parse_output(output)["planes"]
    rows = next((v for k, v in planes.items() if abs(k - z) < 0.005), None)
    if not rows:
        return FootprintOutcome(
            error=f"SLAB's output holds no concentration table on the {z:g} m plane",
            hint=hints["run_failed"],
        )
    # HB-157 item 6: rows past `draw_to_m` (the modelled time's distance, set by the
    # brief) are not drawn; SLAB prints rows past its XFFM, so XFFM alone is no bound
    draw_to = spec.get("draw_to_m")
    if draw_to is not None:
        rows = [r for r in rows if r.x <= float(draw_to)] or rows[:1]
    level = loc.volume_fraction
    reach = downwind_reach(rows, level)
    if reach.distance_m is None:
        return FootprintOutcome(
            error=(
                f"SLAB's concentration never reaches "
                f"{loc.legend or f'{loc.kind} {loc.ppm:g} ppm'} on the "
                f"{z:g} m plane: no footprint"
            ),
            hint="the release is below the level of concern at every printed distance",
        )
    ratios = [float(v) for v in spec["crosswind_ratios"]]
    pts = []
    beyond_width = False
    for r in rows:
        if r.x > reach.distance_m:
            break
        w, wide = half_width(r, level, ratios)
        beyond_width |= wide
        pts.append((r.x, w))
    pts.append((reach.distance_m, 0.0))
    # Between rows the edge is straight: one quadrilateral per pair, their union the
    # shape (a zero width pinches it to a point; separate lobes stay separate).
    pieces = [
        Polygon([(x1, -w1), (x2, -w2), (x2, w2), (x1, w1)]).buffer(0)
        for (x1, w1), (x2, w2) in zip(pts, pts[1:])
        if x2 > x1 and (w1 > 0 or w2 > 0)
    ]
    shape = unary_union([p for p in pieces if not p.is_empty])
    if shape.is_empty:
        return FootprintOutcome(
            error=f"the {loc.kind} footprint has no area on the {z:g} m plane",
            hint="the level is reached only on the centreline line",
        )
    b = math.radians(toward_deg)
    ux, uy = math.sin(b), math.cos(b)  # downwind (east, north)
    rx, ry = math.cos(b), -math.sin(b)  # to the right of downwind

    def ring(coords) -> list:
        out = [G.offset(lat, lon, a * ux + c * rx, a * uy + c * ry) for a, c in coords]
        out[-1] = out[0]  # shapely's ring is closed; keep it closed after rounding
        return out

    polys = list(shape.geoms) if isinstance(shape, MultiPolygon) else [shape]
    # Counterclockwise in (along, cross) is clockwise on the map, since cross points
    # right of downwind: orient clockwise here so the map ring is counterclockwise
    # (RFC 7946 section 3.1.6).
    rings = [[ring(orient(p, sign=-1.0).exterior.coords)] for p in polys]
    geom = (
        {"type": "Polygon", "coordinates": rings[0]}
        if len(rings) == 1
        else {"type": "MultiPolygon", "coordinates": rings}
    )
    props = {
        "level_of_concern": {
            "kind": loc.kind,
            "ppm": loc.ppm,
            "minutes": loc.minutes,
            "source": loc.source,
            "basis": loc.basis,
        },
        "plane_height_m": z,
        "downwind_m": reach.distance_m,
        "beyond_table": reach.beyond_table,
        "max_half_width_m": max(w for _, w in pts),
        "beyond_width": beyond_width,
        "toward_deg": toward_deg,
        # More than one where the cloud leaves the plane and returns: PR4's chlorine jet
        # rises above 1 m between 1.5 and 1.8 m downwind and comes down again.
        "parts": len(polys),
        # the shape in metres, (along the wind, to its right), for a reader to check
        "local_wkt": shape.wkt,
    }
    if reach.beyond_table:
        # HB-157 item 6 (DN-024 section 3.1): the last row's crosswind edge is where
        # SLAB's table ended, not where the cloud did; the map leaves it undrawn and
        # labels the open end (`derive.dense_gas` first runs SLAB farther)
        x, w = pts[-2]
        props["open_end"] = [
            G.offset(lat, lon, x * ux + c * rx, x * uy + c * ry) for c in (-w, w)
        ]
    return FootprintOutcome(
        feature={"type": "Feature", "geometry": geom, "properties": props}
    )


# ── the level of concern ─────────────────────────────────────────────────────────────


def _receipt_text(rec: dict | None) -> str:
    rec = rec or {}
    return f'{rec.get("doc_id")} p. {rec.get("page")}: "{rec.get("quote")}"'


def _receipt_ref(rec: dict | None) -> str:
    """A receipt as the label cites it: its document and page (the quote is in the
    level's `source`, which the panel and the record print)."""
    rec = rec or {}
    return f"{rec.get('doc_id')} p. {rec.get('page')}"


def class_level_of_concern(
    pack: dict, un: str, class_id: str | None, spec: dict
) -> LevelOutcome:
    """The level of concern the DN-001 class names (DN-020 ADDENDUM-01 section 2 item
    2; HB-112 ADDENDUM-00 and ADDENDUM-02 section 5), from the pack entry's
    `levels_of_concern` block by its `kind`, at the class's averaging time:

    - toxic (`aegl2`): the AEGL-2 cell at TAV / 60 minutes;
    - flammable (`lfl_fraction`): the block's "any" value, the fraction of the LFL
      already applied (ALOHA's 60 percent; a proxy's LFL where the material is one);
    - cryogenic asphyxiant (`oxygen_deficiency`): the oxygen threshold, converted to
      the released gas's volume fraction by the pack's `air` rows (1 - threshold / air's
      oxygen fraction), the conversion printed.

    A class with no entry here, or a material whose entry holds no such block, is an
    error naming the missing threshold; nothing is assumed."""
    hints = spec["hints"]
    cls = (spec.get("classes") or {}).get(class_id or "")
    if cls is None:
        return LevelOutcome(
            error=(
                f"not applicable: the DN-001 class {class_id!r} names no dense-gas "
                "level of concern"
                if class_id
                else "not applicable: the material has no DN-001 class"
            ),
            hint=hints["threshold"],
        )
    tav = float(cls["averaging_time_s"])
    minutes = tav / 60.0
    entry = (pack.get("materials") or {}).get(un) or {}
    block = next(
        (
            b
            for b in entry.get("levels_of_concern") or []
            if b["kind"] == cls["loc_kind"]
        ),
        None,
    )
    fallback = cls.get("fallback_kind")
    if block is None and fallback:
        # HB-119 ADDENDUM-00: no AEGL is published for the material, so the class's
        # fallback level (the NIOSH Pocket Guide's IDLH, from the materials resolver)
        # stands in, and the words and legend say which level was used.
        alt = next(
            (b for b in entry.get("levels_of_concern") or [] if b["kind"] == fallback),
            None,
        )
        cell = ((alt or {}).get("values") or {}).get("any") or {}
        if cell.get("value") is not None:
            ppm = float(cell["value"])
            fmt = {
                "minutes": minutes,
                "ppm": ppm,
                "ref": _receipt_ref(cell.get("receipt")),
                "tav": tav,
            }
            return LevelOutcome(
                level=LevelOfConcern(
                    kind=fallback.upper(),
                    ppm=ppm,
                    minutes=minutes,
                    source=_receipt_text(cell.get("receipt")),
                    basis=alt.get("basis") or spec["loc_basis"],
                    words=cls["fallback_words"].format(**fmt),
                    legend=cls["fallback_legend"].format(**fmt),
                )
            )
    if block is None:
        return LevelOutcome(
            error=(
                f"not available: the pack holds no {cls['loc_kind']} level of concern "
                f"for UN{un}" + (f" and no {fallback} level" if fallback else "")
            ),
            hint=hints["threshold"],
        )
    values = block.get("values") or {}
    kind = cls["loc_kind"]
    if kind == "aegl2":
        cell = values.get(f"{minutes:g}")
        if not cell or cell.get("value") is None:
            return LevelOutcome(
                error=(
                    f"not available: the pack holds no AEGL-2 at {minutes:g} minutes "
                    f"for UN{un}"
                ),
                hint=hints["loc"],
            )
        ppm = float(cell["value"])
        source = _receipt_text(cell.get("receipt"))
        fmt = {
            "minutes": minutes,
            "ppm": ppm,
            "source": source,
            "ref": _receipt_ref(cell.get("receipt")),
            "tav": tav,
        }
        return LevelOutcome(
            level=LevelOfConcern(
                kind="AEGL-2",
                ppm=ppm,
                minutes=minutes,
                source=source,
                basis=block.get("basis") or spec["loc_basis"],
                words=cls["loc_words"].format(**fmt),
                legend=cls["legend"].format(**fmt),
            )
        )
    cell = values.get("any")
    if not cell or cell.get("value") is None:
        return LevelOutcome(
            error=f"not available: the pack holds no {kind} value for UN{un}",
            hint=hints["threshold"],
        )
    if kind == "lfl_fraction":
        comp = block.get("components") or {}
        frac, lfl = comp.get("fraction") or {}, comp.get("lfl") or {}
        pct = float(cell["value"])
        proxy = None
        if block.get("proxy_for"):
            proxy = proxy_of(un, pack)
        fmt = {
            "fraction": float(frac.get("value") or 0.0),
            "pct": pct,
            "lfl": float(lfl.get("value") or 0.0),
            "lfl_source": _receipt_text(lfl.get("receipt")),
            "lfl_ref": _receipt_ref(lfl.get("receipt")),
            "fraction_ref": _receipt_ref(frac.get("receipt")),
            "proxy": proxy_legend(proxy, spec),
            "tav": tav,
        }
        return LevelOutcome(
            level=LevelOfConcern(
                kind="LFL fraction",
                ppm=pct * 1e4,
                minutes=minutes,
                source=fmt["lfl_source"],
                basis=block.get("basis") or "",
                words=cls["loc_words"].format(**fmt),
                legend=cls["legend"].format(**fmt),
            )
        )
    if kind == "oxygen_deficiency":
        air = pack.get("air") or {}
        o2_air = (air.get("oxygen_volume_fraction") or {}).get("value")
        added = (air.get("asphyxiant_vol_pct_at_threshold") or {}).get("value")
        if o2_air is None or added is None:
            return LevelOutcome(
                error=(
                    "not available: the pack holds no oxygen fraction of air, so the "
                    "oxygen threshold cannot be read as a volume fraction of the gas"
                ),
                hint=hints["threshold"],
            )
        o2 = float(cell["value"])
        source = _receipt_text(cell.get("receipt"))
        fmt = {
            "o2": o2,
            "pct": float(added),
            "air_o2": 100.0 * float(o2_air),
            "air_o2_fraction": float(o2_air),
            "air_ref": _receipt_ref(air["oxygen_volume_fraction"].get("receipt")),
            "ref": _receipt_ref(cell.get("receipt")),
            "source": source,
            "tav": tav,
        }
        return LevelOutcome(
            level=LevelOfConcern(
                kind="oxygen deficiency",
                ppm=float(added) * 1e4,
                minutes=minutes,
                source=source,
                basis=block.get("basis") or "",
                words=cls["loc_words"].format(**fmt),
                legend=cls["legend"].format(**fmt),
            )
        )
    return LevelOutcome(
        error=f"not available: the level-of-concern kind {kind!r} is not read",
        hint=hints["threshold"],
    )


def level_of_concern(pack: dict, un: str, spec: dict) -> LevelOutcome:
    """AEGL-2 at SLAB's averaging time, from the materials pack's levels of concern
    (HB-111; the toxic class's rule, which `class_level_of_concern` generalises)."""
    hints = spec["hints"]
    minutes = float(spec["averaging_time_s"]) / 60.0
    key = f"{minutes:g}"
    entry = (pack.get("materials") or {}).get(un) or {}
    for lv in entry.get("levels_of_concern") or []:
        if lv.get("kind") != spec["loc_kind"].lower().replace("-", ""):
            continue
        cell = (lv.get("values") or {}).get(key)
        if not cell or cell.get("value") is None:
            break
        rec = cell.get("receipt") or {}
        return LevelOutcome(
            level=LevelOfConcern(
                kind=spec["loc_kind"],
                ppm=float(cell["value"]),
                minutes=minutes,
                source=(
                    f'{rec.get("doc_id")} p. {rec.get("page")}: "{rec.get("quote")}"'
                ),
                basis=spec["loc_basis"],
            )
        )
    return LevelOutcome(
        error=(
            f"not available: the pack holds no {spec['loc_kind']} at {key} minutes for "
            f"UN{un}"
        ),
        hint=hints["loc"],
    )


# ── the chain ────────────────────────────────────────────────────────────────────────


def model_footprint(
    st: tuple[ST.Result | None, str | None],
    met: ST.Met | None,
    *,
    pack: dict,
    spec: dict,
    lat: float,
    lon: float,
    toward_deg: float,
    binary: str | None | object = ...,
    class_id: str | None = None,
    runner=None,
) -> dict:
    """One source term through the client: {"footprint": Feature | None, "problem":
    {"error", "hint"} | None, "label": [...], "route", "engine_id", "engine_kind",
    "level": {...} | None, "deck", "output"}.

    `class_id`, the DN-001 class, chooses the level of concern (HB-112 ADDENDUM-00);
    without it the toxic class's AEGL-2 rule is read (HB-111). `runner(deck)` returns a
    `RunOutcome` in place of `run_slab` (the brief's recorded run, HB-112 ADDENDUM-02
    section 6)."""
    hints = spec["hints"]
    got: dict = {"level": None, "deck": None, "output": None}

    def fail(o: Outcome, label=None, run: RunOutcome | None = None) -> dict:
        return {
            "footprint": None,
            "problem": {"error": o.error, "hint": o.hint},
            "label": label or [],
            "route": run.route if run else None,
            "engine_id": run.engine_id if run else None,
            "engine_kind": run.engine_kind if run else None,
            **got,
        }

    result, reason = st
    if result is None:
        return fail(Outcome(reason or "no source term", hints["source_term"]))
    if met is None:
        return fail(
            Outcome("not available: no weather is held for the spill", hints["weather"])
        )
    un = result.material.un
    if un is None:
        return fail(
            Outcome(
                "not available: the material has no UN number for its level of concern",
                hints["loc"],
            )
        )
    loc = (
        class_level_of_concern(pack, un, class_id, spec)
        if class_id is not None
        else level_of_concern(pack, un, spec)
    )
    if loc.level is None:
        return fail(loc)
    got["level"] = loc.level.as_dict()
    deck = slab_input(result, met, loc.level, spec=spec, pack=pack)
    if deck.deck is None:
        return fail(deck)
    got["deck"] = deck.deck
    if runner is not None:
        run = runner(deck.deck)
    else:
        run = run_slab(deck.deck, spec, binary=binary)
    if run.output is None:
        return fail(run, deck.label)
    got["output"] = run.output
    fp = footprint(
        run.output, loc.level, lat=lat, lon=lon, toward_deg=toward_deg, spec=spec
    )
    if fp.feature is None:
        return fail(fp, deck.label, run)
    return {
        "footprint": fp.feature,
        "problem": None,
        "label": deck.label,
        "route": run.route,
        "engine_id": run.engine_id,
        "engine_kind": run.engine_kind,
        **got,
    }


# ── the brief's label, tiers and comparison (HB-112 Parts A and B) ───────────────────


def model_test_names(material: ST.Material, spec: dict) -> list[str]:
    """The SLAB names of the source-term inputs whose tier is `model-test-input`, in
    the order the source term read them (HB-112 ADDENDUM-01 section 2)."""
    names = spec["slab_names"]
    return [
        names.get(v.name, v.name)
        for v in material.values
        if v.tier == "model-test-input"
    ]


def tier_rows(material: ST.Material, spec: dict) -> list[dict]:
    """Every source-term input as the panel and the appendix print it: its name, SLAB's
    name, its value, and in one cell its tier beside its doc_id and page (HB-112
    ADDENDUM-01 section 2); then, once per material, the sentence for its
    model-test-input values."""
    names = spec["slab_names"]
    rows = [
        {
            "name": v.name,
            "slab": names.get(v.name, ""),
            "value": f"{v.value:.6g} {v.unit}",
            "tier_source": f"{v.tier or 'tier not stated'}; {v.source}",
        }
        for v in material.values
    ]
    return rows


def model_test_sentence(material: ST.Material, spec: dict) -> str | None:
    """ "DHE, CPSL and RHOSL are the SLAB user's guide's recommended test inputs (Table
    2, 1990); no reference table for chlorine's liquid properties is held", or None
    when no value is a model-test-input."""
    names = model_test_names(material, spec)
    if not names:
        return None
    joined = (
        names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    )
    return spec["model_test_input_sentence"].format(
        names=joined, material=material.name.lower()
    )


def evaluation_key(model: str, storage_state: str | None) -> str:
    """Which 1991 sentence stands behind the release (DN-020 ADDENDUM-01 item 5):
    the pressurised jets, the cryogenic pool, or a pool with no trial."""
    if model == "two-phase flashing release":
        return "jet"
    if storage_state == "refrigerated_liquid":
        return "cryogenic_pool"
    return "pool"


def engine_words(kind: str | None, engine_id: str | None, spec: dict) -> str:
    if kind == "binary":
        return spec["engine_binary"].format(sha=engine_id)
    return spec["engine_image"].format(image_id=engine_id)


def brief_label(
    result: ST.Result,
    *,
    storage_state: str | None,
    quantity_kg: float,
    container: str,
    level: dict,
    engine_kind: str | None,
    engine_id: str | None,
    spec: dict,
) -> str:
    """DN-020 section 3.3's label with every bracketed value filled from the run
    (HB-112 step 3), per class and per release (ADDENDUM-00), the tier clause beside
    the engine (ADDENDUM-01)."""
    r = result.result
    if r.get("instantaneous"):
        duration = spec["duration_instantaneous"].format(
            seconds=r["duration_s"], computed=r["computed_duration_s"]
        )
    else:
        duration = spec["duration"].format(seconds=r["duration_s"])
    common = {
        "model": result.model,
        "rate": r["mean_rate_kg_s"],
        "duration": duration,
        "quantity": quantity_kg,
        "container": container,
    }
    if result.model == "two-phase flashing release":
        source = spec["source_two_phase"].format(
            flashed=r["flashed_fraction"], hole_m2=r["hole_area_m2"], **common
        )
    else:
        source = spec["source_pool"].format(area=r["max_area_m2"], **common)
    names = model_test_names(result.material, spec)
    tier = spec["tier_clause"].format(names=", ".join(names)) if names else ""
    return spec["label"].format(
        engine=engine_words(engine_kind, engine_id, spec),
        tier_clause=tier,
        source=source,
        loc=level["words"],
        check=spec["check"],
        evaluation=spec["evaluation"][evaluation_key(result.model, storage_state)],
    )


def reach_text(x: float | None, beyond: bool, spec: dict) -> str:
    """A reach as the label and the table print it: "beyond <x> m" where the level is
    still exceeded at SLAB's last printed row, never as an end (ADDENDUM-02 sec. 6)."""
    if x is None:
        return "none"
    return spec["beyond_line" if beyond else "reach_line"].format(x=x)


def ratio_text(x: float | None, erg_m: float | None, lower_bound: bool) -> str:
    """The modelled extent over the ERG's, two decimals; ">= r" where the extent is a
    floor (ADDENDUM-02 section 6)."""
    if x is None or not erg_m:
        return "none"
    r = f"{x / erg_m:.2f}"
    return f">= {r}" if lower_bound else r


# ── the recorded run (HB-112 ADDENDUM-02 section 6) ──────────────────────────────────


def deck_sha256(deck: str) -> str:
    return hashlib.sha256(deck.encode("latin-1")).hexdigest()


def recording_path(recordings_dir, deck: str) -> Path:
    from hazbrief.brief import live_records

    # HB-207: a served live brief writes a run no task recorded under its live root
    return live_records.resolve(Path(recordings_dir) / f"{deck_sha256(deck)}.json")


def read_recording(recordings_dir, deck: str) -> dict | None:
    """The recorded run of `deck` (its deck, SLAB's output, the route and the engine
    id), or None. A recording whose deck differs from `deck` is refused loudly: the
    name is the deck's hash, so it is a corrupted file, not a different run."""
    path = recording_path(recordings_dir, deck)
    if not path.exists():
        return None
    rec = json.loads(path.read_text(encoding="utf-8"))
    if rec.get("deck") != deck:
        raise RuntimeError(f"{path}: the recorded deck is not the deck its name hashes")
    return rec


def write_recording(recordings_dir, deck: str, run: RunOutcome) -> dict:
    """Record one run: the deck, SLAB's output, how it ran and with what. No time is
    written, so a re-recording of the same run on the same engine is the same bytes."""
    rec = {
        "deck": deck,
        "deck_sha256": deck_sha256(deck),
        "output": run.output,
        "engine_kind": run.engine_kind,
        "engine_id": run.engine_id,
        "route": run.route,
    }
    path = recording_path(recordings_dir, deck)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return rec


#: HB-207: SLAB's output of each run a live brief made in this process, by its deck's
#: sha256. A live brief runs SLAB unrecorded (a replay reads recordings); the two-engine
#: record reads SLAB's output back (`agreement.slab_output`), and before HB-207 found
#: none, so a live dense day brief failed whole there ("SLAB's run of deck ... is not
#: held"). The same deck on the same engine gives the same output, so the table is a
#: cache; nothing is written to disk.
LIVE_OUTPUTS: dict[str, str] = {}


def keep_live_output(deck: str, output: str) -> None:
    LIVE_OUTPUTS[deck_sha256(deck)] = output


def recorded_runner(recordings_dir, spec: dict, *, record: bool, binary=...):
    """A runner for `model_footprint` that reads the recorded run of a deck and, with
    `record`, runs SLAB and records it when none is held. Without `record`, a deck not
    recorded is an error naming the recording it lacks: a replayed brief never runs
    SLAB, so it regenerates byte for byte where no image is built, and across the
    macOS binary and the Linux image's last-digit difference (HB-111 Deviation 2)."""

    def run(deck: str) -> RunOutcome:
        rec = read_recording(recordings_dir, deck)
        if rec is None and record:
            out = run_slab(deck, spec, binary=binary)
            if out.output is None:
                return out
            rec = write_recording(recordings_dir, deck, out)
        if rec is None:
            return RunOutcome(
                error=spec["not_recorded"].format(
                    sha=deck_sha256(deck)[:12], dir=spec["recordings_dir"]
                ),
                hint=spec["hints"]["not_recorded"],
            )
        return RunOutcome(
            output=rec["output"],
            route=f"recorded {rec['route']}",
            engine_id=rec["engine_id"],
            engine_kind=rec["engine_kind"],
        )

    return run
