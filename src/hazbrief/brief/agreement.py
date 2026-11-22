"""Both engines for a dense release (HB-173; DN-028 ADDENDUM-04): whether SCICHEM's
drawn cloud and SLAB's footprint agree, which reaches farther at each level, and the
planning shape under a stable class (HBD-390). Every function here is a pure function
of held records; nothing calls a model or the network, except `lines_recorded` with
`record=True`, the recording route (as `scichem.recorded`).

**The lines run.** The brief's SCICHEM record (`cloud.py`, request B) holds sensors
and contours, no centreline. The measure needs a concentration at a downwind distance
from both engines, so a second request is run: the same release, wind and inputs, with
HB-167's crosswind lines of sensors on the release hour's wind instead of the points
(`agreement.yaml lines`). It is held in `fixtures/evidence/scichem_lines/<sha256>.json`,
one per request, written by the same route as the records (`HAZBRIEF_SCICHEM_RECORD`).

**The measure** (DN-028 ADDENDUM-04 decision 2): at each distance of the lines to 20 km
where both engines hold a concentration, SLAB's over SCICHEM's; the two disagree when
any pair lies outside the held factor of three (Hanna et al. 2016: "within a factor of
plus and minus three at any given downwind distance out to 20 km"). Each engine's reach
per level is stated beside it as a fact; no threshold is set on reach.

**Which reaches farther, per level** (HBD-390; HB-173 ADDENDUM-02 section 2): from each
engine's farthest point of its area at that level and whether that reach is cut (the
engine's domain for SCICHEM, the end of SLAB's table for SLAB). A pick is decidable when
the larger reach is a full one, or a lower bound that still exceeds the other's full
reach; otherwise it is "undecided". Since DN-028 ADDENDUM-10 the pick is a fact stated
in section T57; it no longer chooses what is drawn.

**The planning area** (DN-028 ADDENDUM-14 decisions 2 and 6, amending ADDENDUM-12
decisions 2 and 3): under the stable treatment (any hour of the horizon class E or F,
`derive.stability_hours`) each level's area is the moving cloud's area over the
horizon (SCICHEM's run at the stated vertical setting, reached at that level at any
time; the `cloud` part, filled) together with SLAB's time-bounded band outside it (the
`check` part, an extent check on one wind with no times, dashed). SLAB's band is drawn
to where the level closes or to the release hour's wind's travel in the horizon times
1.3, the nearer. Every time is the moving cloud's. By day with no stable hour nothing
changes: the levels are SCICHEM's and there is no planning area. Under ADDENDUM-12 the
parts' roles were the other way round (SLAB's filled, SCICHEM's forecast-turned part
dashed), under ADDENDUM-10 the area was SLAB's alone, and before it the
farther-reaching engine's (HBD-390, DN-028 ADDENDUM-04 decision 3).

**The warning** (DN-028 ADDENDUM-10 decision 4, extended by ADDENDUM-14): under the
stable treatment the two-methods warning is retired, both engines' areas being drawn
together on the first view; the measure is still computed and stated in section T57.
By day with no stable hour it stands as built.
"""

from __future__ import annotations

import base64
import gzip
import json
import math
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
CONFIG = Path(__file__).with_name("agreement.yaml")


def load_config(path: Path = CONFIG) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# ── the lines run ────────────────────────────────────────────────────────────────────


def lines_path(acfg: dict, request: dict, root: Path = ROOT) -> Path:
    from hazbrief.brief import live_records
    from hazbrief.brief import scichem as SC

    # HB-207: a served live brief writes a run no task recorded under its live root
    return live_records.resolve(
        root / acfg["recordings_dir"] / f"{SC.request_sha256(request)}.json"
    )


def _running_max(series: list[float], window: int) -> float:
    """The largest mean over `window` consecutive samples, the series padded with zeros
    to the window (HB-169 bench.py `running_max`, the comparison's reading)."""
    pad = series + [0.0] * max(0, window - len(series))
    run = best = sum(pad[:window])
    for k in range(window, len(pad)):
        run += pad[k] - pad[k - window]
        best = max(best, run)
    return best / window


def window_samples(request: dict) -> int:
    """The brief's averaging time in sensor samples: the tiers' minutes over the sensor
    interval (HB-169's `avg60` at 60 minutes and 120 s: 30)."""
    meta = request["meta"]
    minutes = float(meta["tiers"][0]["minutes"])
    return max(1, int(round(minutes * 60.0 / float(meta["dt_smp_s"]))))


def line_summary(request: dict, response: dict) -> dict:
    """Per line sensor, the largest instantaneous mean and the largest running mean over
    the brief's averaging time (kg/m3), by distance and position on the line."""
    from hazbrief.brief import scichem as SC

    smp = SC.read_smp(response["smp"])
    sensors = request["meta"]["sensors"]
    by_id = {sid: i for i, sid in enumerate(sensors, start=1)}
    w = window_samples(request)
    lines = request["meta"]["lines"]
    inst, run = [], []
    for d in lines["distances_m"]:
        a, b = [], []
        for j in range(int(lines["points"])):
            s = smp.column(SC._col(smp, "C", by_id[f"line:{d}:{j}"]))
            a.append(max(s) if s else 0.0)
            b.append(_running_max(s, w))
        inst.append(a)
        run.append(b)
    return {
        "distances_m": [float(d) for d in lines["distances_m"]],
        "points": int(lines["points"]),
        "window_samples": w,
        "inst_kg_m3": inst,
        "run_kg_m3": run,
    }


def lines_recorded(
    request: dict,
    sc: dict,
    acfg: dict,
    *,
    record: bool,
    argv: list[str] | None = None,
    root: Path = ROOT,
) -> dict:
    """The held lines record of `request`: read it, or with `record` run the engine and
    write it (one unit, written before the next is built: constitution section 15).
    Without `record`, a request not held is a `scichem.Refusal` naming the record it
    lacks."""
    from hazbrief.brief import scichem as SC

    path = lines_path(acfg, request, root)
    sha = SC.request_sha256(request)
    if path.exists():
        rec = json.loads(path.read_text(encoding="utf-8"))
        if rec.get("request_sha256") != sha or rec.get("request") != request:
            raise RuntimeError(
                f"{path}: the recorded request is not the one its name hashes"
            )
        return rec
    if not record:
        raise SC.Refusal(
            acfg["words"]["not_recorded"].format(
                sha=sha[:12], dir=acfg["recordings_dir"]
            )
        )
    response, kind, engine_id = SC.run_request(request, sc, argv=argv)
    run = response.get("runsci") or {}
    rec: dict[str, Any] = {
        "request_sha256": sha,
        "request": request,
        "engine_kind": kind,
        "engine_id": engine_id,
        "wall_s": response.get("wall_s"),
        "runsci": {
            "normal": bool(run.get("normal")),
            "exit": run.get("exit"),
            "log_tail": list(run.get("log_tail") or [])[-3:],
        },
    }
    if run.get("normal") and response.get("smp") is not None:
        rec["state"] = "modelled"
        rec["reason"] = None
        rec["lines"] = line_summary(request, response)
    else:
        tail = " ".join(rec["runsci"]["log_tail"][-2:]) or f"exit {run.get('exit')}"
        rec["state"] = "not_modelled"
        rec["reason"] = sc["refusals"]["engine"].format(detail=tail)
        rec["lines"] = None
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return rec


# ── the two centrelines and the measure ──────────────────────────────────────────────


def ppm_per_kg_m3(request: dict) -> float:
    t = request["meta"]["tiers"][0]
    return float(t["ppm"]) / float(t["kg_m3"])


def scichem_centre(lrec: dict) -> dict[float, float]:
    """SCICHEM's concentration at each line's distance (ppm): the largest running mean
    over the averaging time of any sensor on the line (HB-169's `centre_ppm.avg60`)."""
    k = ppm_per_kg_m3(lrec["request"])
    ln = lrec["lines"]
    return {d: max(row) * k for d, row in zip(ln["distances_m"], ln["run_kg_m3"])}


def slab_centre(output: str, distances: list[float]) -> dict[float, float | None]:
    """SLAB's time-averaged concentration on its centreline plane at each distance
    (ppm), log-linear between its table's rows; None past the table (HB-169 bench.py
    `slab_summary`)."""
    from hazbrief.brief import dense_gas as DG

    planes = DG.parse_output(output)["planes"]
    rows = next(v for k, v in planes.items() if abs(k) < 0.005)
    cen = [(r.x, r.c[0] * 1e6) for r in rows]
    out: dict[float, float | None] = {}
    for d in distances:
        v = None
        for (x0, c0), (x1, c1) in zip(cen, cen[1:]):
            if x0 <= d <= x1 and x1 > x0 > 0:
                f = (math.log(d) - math.log(x0)) / (math.log(x1) - math.log(x0))
                v = (
                    math.exp(math.log(c0) + f * (math.log(c1) - math.log(c0)))
                    if c0 > 0 and c1 > 0
                    else c0 + f * (c1 - c0)
                )
                break
        out[float(d)] = v
    return out


def measure(slab: dict, sci: dict, acfg: dict) -> dict:
    """The paired measure (module docstring): every distance to `measure.max_distance_m`
    where both engines hold a concentration above zero, SLAB's over SCICHEM's, and the
    pairs outside the held factor."""
    m = acfg["measure"]
    f = float(m["factor"])
    pairs, only_one = [], []
    for d in sorted(sci):
        if d > float(m["max_distance_m"]):
            continue
        sl, sc = slab.get(d), sci.get(d)
        has_sl, has_sc = bool(sl and sl > 0), bool(sc and sc > 0)
        if has_sl and has_sc:
            r = sl / sc
            pairs.append(
                {
                    "d": d,
                    "slab_ppm": sl,
                    "scichem_ppm": sc,
                    "ratio": r,
                    "outside": r > f or r < 1.0 / f,
                }
            )
        elif has_sl or has_sc:
            only_one.append(d)
    outside = [p for p in pairs if p["outside"]]
    return {
        "factor": f,
        "max_distance_m": float(m["max_distance_m"]),
        "pairs": pairs,
        "only_one_m": only_one,
        "outside_m": [p["d"] for p in outside],
        "within_factor_two": sum(
            1 for p in pairs if 0.5 <= p["ratio"] <= float(m["second_source"]["factor"])
        ),
        "alert": bool(outside),
        "computed": bool(pairs),
    }


# ── reaches and the planning shape ───────────────────────────────────────────────────


def grid_half_width(rec: dict) -> float | None:
    """The largest coordinate (km) any step's mean overlay of a held record reaches
    (`scichem._grid_half_width`). HB-178 took it as the grid's edge; it is that edge
    only where a contour reaches the domain, and otherwise the outermost contour's own
    extent (HB-180 convergence.tsv, last table). No brief reads it since HB-182
    (`domain_edges`); HB-180's evidence tool re-derives its table with it."""
    from hazbrief.brief import scichem as SC

    resp = json.loads(gzip.decompress(base64.b64decode(rec["response_gz_b64"])))
    hw = None
    for k, text in sorted((resp.get("overlays") or {}).items()):
        if not k.startswith("m_") or not isinstance(text, str):
            continue
        h = SC._grid_half_width(SC.read_overlay(text))
        if h is not None and (hw is None or h > hw):
            hw = h
    return hw


def domain_half_width(rec: dict) -> float:
    """The domain's half-width (km) the record's request set (`scichem` request,
    `meta.inputs.domain_half_width_km`; XMIN to XMAX and YMIN to YMAX about the site).
    A record without it is refused: its edge is never inferred from a contour
    (HB-182)."""
    inputs = ((rec.get("request") or {}).get("meta") or {}).get("inputs") or {}
    if inputs.get("domain_half_width_km") is None:
        raise ValueError(
            f"record {str(rec.get('request_sha256'))[:8]}: its request carries no "
            "meta.inputs.domain_half_width_km, so the engine's domain is not known"
        )
    return float(inputs["domain_half_width_km"])


def edge_centres_km(hw: float, acfg: dict) -> list[float]:
    """Where the post-processor's field can end inside a domain of half-width `hw`
    (km): the outermost cell centre at each refinement level, hw - dx0 / 2**(L+1), dx0
    the base cell (agreement.yaml `reach.post_processor_base_cells`, SCICHEM
    `slice.f90` and `sliceh.f90`), until the half-cell is within the edge tolerance."""
    r = acfg["reach"]
    dx0 = 2.0 * hw / float(r["post_processor_base_cells"])
    tol = float(r["edge_tolerance_km"])
    out, lev = [], 0
    while dx0 / 2 ** (lev + 1) > tol:
        out.append(round(hw - dx0 / 2 ** (lev + 1), 6))
        lev += 1
    return out


def domain_edges(rec: dict, acfg: dict) -> dict[str, list[float]]:
    """Per level of a held record, the outermost cell centres (km from the site, each
    way) its area reached at any time lies on: where it touches the engine's domain.
    Empty for a level whose area ends inside the domain (HB-182)."""
    r = acfg["reach"]
    tol = float(r["edge_tolerance_km"])
    need = int(r["min_points_on_edge"])
    edges = edge_centres_km(domain_half_width(rec), acfg)
    inner = edges[0] - tol if edges else math.inf
    out = {}
    for t, a in (rec["result"].get("any_time") or {}).items():
        hits: dict[float, int] = {}
        for poly in a["rings_km"]:
            for ring in poly:
                for x, y in ring:
                    c = max(abs(x), abs(y))
                    if c < inner:
                        continue
                    for e in edges:
                        if abs(c - e) <= tol:
                            hits[e] = hits.get(e, 0) + 1
                            break
        out[t] = sorted(e for e, n in hits.items() if n >= need)
    return out


def domain_cut(rec: dict, acfg: dict) -> dict[str, bool]:
    """Per level of a held record, whether its area reached at any time touches the
    engine's domain (`domain_edges`): the level's reach is then a lower bound, cut by
    the engine's domain."""
    return {t: bool(e) for t, e in domain_edges(rec, acfg).items()}


def farther(sc_m, sc_cut: bool, sl_m, sl_cut: bool) -> str:
    """Which engine's reach is the farther at one level: "scichem", "slab" or
    "undecided" (module docstring)."""
    if sl_m is None:
        return "scichem"
    if sc_m is None:
        return "slab"
    if sc_cut and sl_cut:
        return "undecided"
    if sc_cut:
        return "scichem" if sc_m >= sl_m else "undecided"
    if sl_cut:
        return "slab" if sl_m > sc_m else "undecided"
    return "slab" if sl_m > sc_m else "scichem"


def reaches(cl: dict, dense: dict) -> list[dict]:
    """Per level of the drawn cloud, outermost first: each engine's reach (m), whether
    is cut and by what, each engine's area (km2), and which reaches farther."""
    from shapely.geometry import shape

    from hazbrief import geo

    bands = {
        b["tier"]: b for b in (dense or {}).get("bands") or [] if b.get("geometry")
    }
    out = []
    for t in cl.get("tiers") or []:
        name = t["name"]
        b = bands.get(name)
        sc_m = (cl.get("reach_m") or {}).get(name)
        sc_cut = bool((cl.get("reach_cut") or {}).get(name))
        sl_m = float(b["downwind_m"]) if b else None
        sl_cut = bool(b.get("beyond_table")) if b else False
        g = (cl.get("any_time") or {}).get(name)
        out.append(
            {
                "tier": name,
                "scichem_m": sc_m,
                "scichem_cut": sc_cut,
                "scichem_km2": (cl.get("any_time_km2") or {}).get(name),
                "slab_m": sl_m,
                "slab_cut": sl_cut,
                "slab_km2": round(geo.geodesic_area_m2(shape(b["geometry"])) / 1e6, 3)
                if b
                else None,
                "farther": farther(sc_m, sc_cut, sl_m, sl_cut),
                "has_cloud": bool(g),
            }
        )
    return out


def is_stable(problem: dict, acfg: dict) -> bool:
    return int(round(float(problem["stab"]))) in {
        int(s) for s in acfg["reach"]["stable_stab"]
    }


def _polygonal(g):
    """The polygonal part of `g` (a difference of two areas can leave lines and points
    on their shared edges), or None where it has no area."""
    from shapely.geometry import GeometryCollection, MultiPolygon, Polygon

    if isinstance(g, (Polygon, MultiPolygon)):
        return None if g.is_empty else g
    if isinstance(g, GeometryCollection):
        polys = []
        for p in g.geoms:
            if isinstance(p, Polygon):
                polys.append(p)
            elif isinstance(p, MultiPolygon):
                polys.extend(p.geoms)
        polys = [p for p in polys if not p.is_empty]
        if not polys:
            return None
        return polys[0] if len(polys) == 1 else MultiPolygon(polys)
    return None


def planning(
    dense: dict, rows: list[dict], places: int, cl: dict | None = None
) -> dict:
    """The planning area per level under the stable treatment (module docstring), as
    GeoJSON geometries rounded to `places`. DN-028 ADDENDUM-14 decision 6: at each
    level, the area the moving cloud reaches at that level at any time
    (`cl["any_time"]`) together with SLAB's time-bounded band. Its two parts are kept:
    `cloud`, the moving cloud's area (timed, filled), and `check`, SLAB's band outside
    it (one wind, time-averaged, no times; dashed), None where SLAB adds nothing.
    `slab_cut` is whether SLAB's band was cut where it adds area (its table's end or
    the time bound),
    `scichem_cut` whether the cloud meets its domain, `cut` either; and `open_end` the
    band's open end, so the cut is drawn where SLAB's record puts it."""
    import shapely
    from shapely.geometry import mapping, shape
    from shapely.ops import unary_union

    from hazbrief import geo

    def rounded(g) -> dict:
        return json.loads(
            json.dumps(mapping(g)), parse_float=lambda s: round(float(s), places)
        )

    bands = {
        b["tier"]: b for b in (dense or {}).get("bands") or [] if b.get("geometry")
    }
    any_time = (cl or {}).get("any_time") or {}
    out = {}
    for r in rows:
        b = bands.get(r["tier"])
        at = any_time.get(r["tier"])
        if b is None and not at:
            continue
        slab = shapely.make_valid(shape(b["geometry"])) if b else None
        sci = shapely.make_valid(shape(at)) if at else None
        whole = unary_union([g for g in (slab, sci) if g is not None])
        check = None
        if slab is not None:
            check = _polygonal(
                shapely.make_valid(slab.difference(sci) if sci is not None else slab)
            )
        if sci is not None and check is not None:
            engine = "both"
        else:
            engine = "scichem" if sci is not None else "slab"
        # SLAB's cut (its table's end or the time bound) counts only where its part
        # adds area; the cloud's domain counts wherever the cloud reaches it
        slab_cut = bool(b.get("beyond_table")) and check is not None if b else False
        scichem_cut = bool(r.get("scichem_cut")) and sci is not None

        def km2(g) -> float | None:
            return round(geo.geodesic_area_m2(g) / 1e6, 3) if g is not None else None

        out[r["tier"]] = {
            "engine": engine,
            "km2": km2(whole),
            "cloud_km2": km2(sci),
            "check_km2": km2(check),
            "slab_km2": km2(slab),
            "geometry": rounded(shapely.make_valid(whole)),
            "cloud": rounded(sci) if sci is not None else None,
            "check": rounded(check) if check is not None else None,
            "slab_cut": slab_cut,
            "scichem_cut": scichem_cut,
            "cut": slab_cut or scichem_cut,
            "open_end": b.get("open_end") if b else None,
        }
    return out


# ── like for like ────────────────────────────────────────────────────────────────────


def class_letter(stab: int, acfg: dict) -> str:
    """SLAB's STAB number as the Pasquill letter (SLAB user's guide: 1 to 6 for A to F;
    `dense_gas` module docstring)."""
    return acfg["like_for_like"]["class_letters"][stab - 1]


def like_for_like(request: dict, problem: dict, acfg: dict) -> list[dict]:
    """The inputs the two requests do not share (HB-173 ADDENDUM-01 section 3): the
    stability (SCICHEM's boundary layer against SLAB's class), the release hour's wind
    speed and the release. Empty where they are like for like."""
    lf = acfg["like_for_like"]
    meta = request["meta"]
    inputs = meta["inputs"]
    stab = int(round(float(problem["stab"])))
    cls = class_letter(stab, acfg)
    out = []
    obs = inputs.get("bl_type") == "OBS" and inputs.get("pgt") is not None
    if not (obs and int(round(float(inputs["pgt"]))) == stab):
        out.append(
            {
                "input": "boundary_layer",
                "scichem": inputs.get("bl_type"),
                "slab_class": cls,
            }
        )
    rel = meta["release_utc"]
    row = next((m for m in meta["met"] if m["time"] == rel), None)
    sc_u = float(row["speed_m_s"]) if row else None
    sl_u = float(problem["ua"])
    # half the wind record's rounding step (km/h), in m/s
    tol = float(lf["wind_record_step_kmh"]) / 2.0 / 3.6
    if sc_u is None or abs(sc_u - sl_u) > tol:
        out.append({"input": "wind", "scichem": sc_u, "slab": sl_u})
    src = meta["source"]
    sc_q, sc_t = float(src["rate_kg_s"]), float(src["duration_s"])
    sl_q, sl_t = float(problem["qs"]), float(problem["tsd"])
    if abs(sc_q - sl_q) > float(lf["rate_tolerance_frac"]) * max(sl_q, 1e-12) or abs(
        sc_t - sl_t
    ) > float(lf["duration_tolerance_s"]):
        out.append(
            {
                "input": "release",
                "scichem": [sc_q, sc_t],
                "slab": [sl_q, sl_t],
            }
        )
    return out


# ── Volume II's continuous or instantaneous release ──────────────────────────────────


def release_kind(problem: dict, acfg: dict) -> dict:
    """By Volume II's criterion (u T / x): the distance to which the release is
    continuous, the distance beyond which it is instantaneous, and which it is over
    the evaluated range (or neither throughout)."""
    k = acfg["release_kind"]
    ut = float(problem["ua"]) * float(problem["tsd"])
    cont = ut / float(k["continuous_at_least"])
    inst = ut / float(k["instantaneous_at_most"])
    lo, hi = float(k["evaluated_from_m"]), float(k["evaluated_to_m"])
    if hi <= cont:
        which = "continuous"
    elif lo >= inst:
        which = "instantaneous"
    else:
        which = "neither"
    return {"continuous_to_m": cont, "instantaneous_from_m": inst, "which": which}


# ── the record the brief carries ─────────────────────────────────────────────────────


def slab_output(deck: str) -> str:
    """SLAB's held output for `deck` (`dense_gas.read_recording` in the SLAB client's
    recordings directory): the brief's own SLAB run; for a live brief, which runs SLAB
    unrecorded, the output its run kept in this process (`dense_gas.LIVE_OUTPUTS`,
    HB-207)."""
    from hazbrief.brief import dense_gas as DG
    from hazbrief.brief.orchestrator import load_config

    spec = load_config()["weather"]["dense_gas"]
    rec = DG.read_recording(ROOT / spec["recordings_dir"], deck)
    if rec is None and DG.deck_sha256(deck) in DG.LIVE_OUTPUTS:
        return DG.LIVE_OUTPUTS[DG.deck_sha256(deck)]
    if rec is None:
        raise RuntimeError(
            f"SLAB's run of deck {DG.deck_sha256(deck)[:12]} is not held"
        )
    return rec["output"]


def build(
    rec: dict,
    lines_rec: dict | None,
    why: str | None,
    cl: dict,
    dense: dict,
    acfg: dict,
    places: int,
    treatment: dict | None = None,
) -> dict:
    """The agreement record of one dense brief: the measure (or why it is not computed),
    the reaches per level, the inputs the two requests do not share, the release's kind,
    whether the stable treatment applies, the planning area (stable treatment only) and
    the reason shown. `rec` is SCICHEM's drawn record (B); `lines_rec` its lines record,
    or None with `why`; `treatment` the brief's `stability_hours` (HB-189: any hour of
    the horizon class E or F gives the stable treatment, DN-028 ADDENDUM-14 decision
    2; without it, SLAB's own class decides, as before)."""
    from hazbrief.brief import dense_gas as DG

    ev = ((dense or {}).get("evidence") or {}).get("record") or {}
    (problem,) = DG.read_deck(ev["deck"])[:1]
    if treatment is not None:
        stable = bool(treatment.get("stable"))
    else:
        stable = is_stable(problem, acfg)
    rows = reaches(cl, dense)
    out: dict[str, Any] = {
        "state": "computed",
        "reason": None,
        "stable": stable,
        "stab": int(round(float(problem["stab"]))),
        "first_stable_hour": (treatment or {}).get("first_stable_hour"),
        "first_stable_class": (treatment or {}).get("first_stable_class"),
        # HB-189: the moving cloud's vertical setting (its request's), for the words
        "vertical_setting_m": rec["request"]["meta"]["inputs"].get(
            "vertical_setting_m"
        ),
        "reaches": rows,
        "like_for_like": like_for_like(rec["request"], problem, acfg),
        "release_kind": release_kind(problem, acfg),
        "planning": planning(dense, rows, places, cl) if stable else {},
        # DN-028 ADDENDUM-14 decision 6: under the stable treatment a level's area is
        # the planning area (the moving cloud's together with SLAB's check); SCICHEM's
        # cloud otherwise
        "levels": "planning" if stable else "scichem",
        "lines_record": (lines_rec or {}).get("request_sha256"),
        "slab_record": (dense.get("evidence") or {}).get("sha256"),
    }
    if not (dense or {}).get("bands"):
        why = acfg["words"]["no_slab"]
    if lines_rec is None or lines_rec.get("state") != "modelled" or why:
        out.update(
            state="not_computed",
            reason=why or (lines_rec or {}).get("reason") or "not computed",
            measure=None,
            alert=False,
            warning=False,
        )
        return out
    sci = scichem_centre(lines_rec)
    sl = slab_centre(slab_output(ev["deck"]), list(sci))
    m = measure(sl, sci, acfg)
    if not m["computed"]:
        out.update(
            state="not_computed",
            reason=acfg["words"]["no_pairs"],
            measure=m,
            alert=False,
            warning=False,
        )
        return out
    # DN-028 ADDENDUM-10 decision 4: under a stable class the two-methods warning is
    # retired (the difference is known, explained and stated as a condition of use,
    # sections T58 and T59); `alert` is the measure's own result, `warning` whether the
    # checklist raises it
    out.update(measure=m, alert=m["alert"], warning=m["alert"] and not stable)
    out["reason_shown"] = reason(out["stab"], acfg)
    return out


def untimed_places(cl: dict, ag: dict) -> list[dict]:
    """HB-173 (DN-028 ADDENDUM-04 decision 5): each measured place inside a level's
    planning shape whose SCICHEM sensor did not reach that level, once, at the worst
    such level: it is listed with the engine that puts it inside and no time (times come
    only from SCICHEM). Ordered nearest the source first."""
    import shapely
    from shapely.geometry import Point, shape

    plan = ag.get("planning") or {}
    if not plan:
        return []
    shapes = {t: shapely.make_valid(shape(p["geometry"])) for t, p in plan.items()}
    worst_first = [t["name"] for t in reversed(cl.get("tiers") or [])]
    out = []
    for p in cl.get("places") or []:
        pt = Point(p["lon"], p["lat"])
        for t in worst_first:
            if t not in shapes:
                continue
            if ((p.get("tiers") or {}).get(t) or {}).get("arrival_s") is not None:
                continue
            if shapes[t].covers(pt):
                out.append(
                    {
                        "id": p["id"],
                        "kind": p["kind"],
                        "name": "; ".join(p.get("names") or []),
                        "lat": p["lat"],
                        "lon": p["lon"],
                        "distance_m": p.get("distance_m"),
                        "tier": t,
                        "engine": plan[t]["engine"],
                        "place": p,
                    }
                )
                break
    out.sort(key=lambda u: (u["distance_m"] is None, u["distance_m"] or 0, u["id"]))
    return out


def reason(stab: int, acfg: dict) -> dict:
    """The reason the alert shows (DN-028 ADDENDUM-04 decision 4): the held trace's
    quotation with its key and reference where one exists for the class, else "not
    traced"."""
    r = acfg["reasons"]["stable"]
    if stab in {int(s) for s in r["stab"]}:
        return {"key": r["key"], "ref": r["ref"], "quotes": list(r["quotes"])}
    return {"key": None, "ref": None, "quotes": []}


# ── the words (checklist line, timeline head, pop-out) ───────────────────────────────


def _metres(d: float) -> str:
    d = int(round(d))
    return f"{d // 1000} km" if d >= 1000 and d % 1000 == 0 else f"{d:,} m"


def _series(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + f" and {items[-1]}"


def _slab_by(ag: dict) -> str:
    """What cuts SLAB's reach: under the stable treatment the time bound (DN-028
    ADDENDUM-14 decision 5); by day its table's end (the horizon's travel)."""
    return "cut_time" if ag.get("stable") else "cut_table"


def reach_text(m, cut: bool, by: str, w: dict) -> str:
    """A reach as the page writes it: never a lower bound as a plain reach (HB-173
    ADDENDUM-02 section 2 item 3)."""
    if m is None:
        return w["reach_none"]
    if cut:
        return w["reach_cut"].format(m=int(round(m)), by=w[by])
    return w["reach_m"].format(m=int(round(m)))


def reaches_text(ag: dict, acfg: dict) -> str:
    """Each level's two reaches, the worst level first."""
    w = acfg["words"]
    tiers = [
        w["reach_tier"].format(
            tier=r["tier"],
            scichem=reach_text(r["scichem_m"], r["scichem_cut"], "cut_domain", w),
            slab=reach_text(r["slab_m"], r["slab_cut"], _slab_by(ag), w),
        )
        for r in reversed(ag.get("reaches") or [])
    ]
    return w["reaches"].format(tiers="; ".join(tiers))


def measure_text(ag: dict, acfg: dict) -> str:
    w = acfg["words"]
    m = ag["measure"]
    want = [float(x) for x in acfg["measure"]["report_m"]]
    got = [p for p in m["pairs"] if p["d"] in want]
    return w["measure"].format(
        ratios=_series([f"{p['ratio']:.3g}" for p in got]) or w["ratio_none"],
        distances=_series([_metres(p["d"]) for p in got]) or w["ratio_none"],
        outside=len(m["outside_m"]),
        pairs=len(m["pairs"]),
        max_km=m["max_distance_m"] / 1000.0,
        factor=m["factor"],
    )


def like_text(ag: dict, acfg: dict) -> str:
    """The inputs the two requests do not share, named; "" when like for like."""
    w = acfg["words"]
    parts = []
    for d in ag.get("like_for_like") or []:
        if d["input"] == "boundary_layer":
            sc = (
                w["like_bl_obs"].format(cls=d["slab_class"])
                if d["scichem"] == "OBS"
                else w["like_bl_calc"]
            )
            parts.append(w["like_bl"].format(sc=sc, cls=d["slab_class"]))
        elif d["input"] == "wind":
            parts.append(w["like_wind"].format(sc=d["scichem"] or 0.0, sl=d["slab"]))
        else:
            parts.append(
                w["like_release"].format(
                    sc_q=d["scichem"][0],
                    sc_t=d["scichem"][1],
                    sl_q=d["slab"][0],
                    sl_t=d["slab"][1],
                )
            )
    return w["not_like"].format(inputs="; ".join(parts)) if parts else ""


def line(ag: dict, acfg: dict) -> str:
    """The one line: the alert's where the measure is outside the held factor, the
    agreement's where it is inside, or why the two were not compared."""
    w = acfg["words"]
    if ag.get("state") != "computed":
        return w["not_computed"].format(why=ag.get("reason"))
    form = w["alert"] if ag.get("alert") else w["agree"]
    # DN-028 ADDENDUM-10 decision 4: under a stable class a difference beyond the factor
    # is a stated condition of use, not a warning, and the line says so
    if ag.get("alert") and ag.get("stable"):
        form = w["differ_stable"]
    return form.format(
        measure=measure_text(ag, acfg),
        reaches=reaches_text(ag, acfg),
        like=like_text(ag, acfg),
    )


def stable_line(ag: dict, acfg: dict, ref: str | None) -> str:
    """DN-028 ADDENDUM-10 decisions 2 to 4, as ADDENDUM-14 decisions 1 to 3, 6 and 13
    amend them: under the stable treatment, the one line the checklist and the
    Timeline page's top carry in the place of the two-methods item: when the horizon
    turns stable, that the moving cloud is drawn hour by hour by level at its stated
    vertical setting (an approximation, not converged), that each level's planning area
    is its area, filled, together with SLAB's extent check, dashed, every time from
    that run, and where the Conditions of use are (`ref`, SCICHEM's section)."""
    w = acfg["words"]
    hour = ag.get("first_stable_hour")
    cls = ag.get("first_stable_class") or class_letter(int(ag["stab"]), acfg)
    when = (
        w["stable_when_later"].format(cls=cls, hour=hour)
        if hour
        else w["stable_when_release"].format(cls=cls)
    )
    return w["stable_line"].format(
        when=when, vres=float(ag.get("vertical_setting_m") or 0.0), ref=ref
    )


def popout_lines(
    ag: dict, acfg: dict, stab_item: str, wind_item: str, cond_ref: str | None = None
) -> list[str]:
    """The pop-out (the measure's TEVV section, which the checklist item opens): the
    line, the measure with its source, every pair, each level's two reaches and areas
    and which reaches farther, the inputs not shared, the release's kind by Volume II
    and what is known of each engine, the reason or "not traced", and the line naming
    the existing Verify items the shared inputs rest on. Under a stable class the
    second line is `stable_line`, naming SCICHEM's Conditions of use (`cond_ref`)."""
    w = acfg["words"]
    m = acfg["measure"]
    out = [line(ag, acfg)]
    if ag.get("state") != "computed":
        return out
    if ag.get("stable"):
        out.append(stable_line(ag, acfg, cond_ref))
    out.append(
        w["factor_line"].format(
            factor_quote=f'"{m["factor_source"]["quote"]}"',
            factor_cite=m["factor_source"]["cite"],
            factor=float(m["factor"]),
            second_quote=m["second_source"]["quote"],
            second_cite=m["second_source"]["cite"],
        )
    )
    me = ag["measure"]
    for p in me["pairs"]:
        out.append(
            w["pairs_line"].format(
                d=p["d"],
                sl=p["slab_ppm"],
                sc=p["scichem_ppm"],
                r=p["ratio"],
                flag=w["flag_outside"].format(factor=me["factor"])
                if p["outside"]
                else "",
            )
        )
    if me["only_one_m"]:
        out.append(
            w["only_one"].format(
                n=len(me["only_one_m"]), max_km=me["max_distance_m"] / 1000.0
            )
        )
    plan = ag.get("planning") or {}
    far_words = {
        "scichem": w["farther_scichem"],
        "slab": w["farther_slab"],
        "undecided": w["farther_undecided"],
    }

    def area(a) -> str:
        return w["area_km2"].format(a=a) if a is not None else w["reach_none"]

    for r in reversed(ag.get("reaches") or []):
        far = far_words[r["farther"]]
        p = plan.get(r["tier"])
        if p:
            # DN-028 ADDENDUM-12 decisions 2 and 4: the planning area, with its parts
            far += w["planning_on"].format(
                what=w["planning_parts"].format(
                    km2=area(p.get("km2")),
                    cloud=area(p.get("cloud_km2")),
                    check=area(p.get("check_km2")),
                )
            )
        out.append(
            w["tier_line"].format(
                tier=r["tier"],
                sc_reach=reach_text(r["scichem_m"], r["scichem_cut"], "cut_domain", w),
                sl_reach=reach_text(r["slab_m"], r["slab_cut"], _slab_by(ag), w),
                sc_area=area(r["scichem_km2"]),
                sl_area=area(r["slab_km2"]),
                farther=far,
            )
        )
    lt = like_text(ag, acfg)
    if lt:
        out.append(w["like_line"].format(like=lt[len("; ") :]))
    k = ag["release_kind"]
    rk = acfg["release_kind"]
    out.append(
        w["kind_line"].format(
            blocks=rk["blocks"],
            cont=k["continuous_to_m"],
            inst=k["instantaneous_from_m"],
            which=w[f"kind_{k['which']}"],
        )
    )
    ev = acfg["evaluations"]
    if k["which"] in ("continuous", "neither"):
        out.append(ev["continuous"])
    if k["which"] in ("instantaneous", "neither"):
        out.append(ev["instantaneous"])
    out.append(ev["jack_rabbit"])
    out.append(ev["beyond"])
    rs = ag.get("reason_shown") or {}
    if rs.get("quotes"):
        out.append(
            w["reason_line"].format(
                quotes="; ".join(f'"{q}"' for q in rs["quotes"]),
                ref=rs["ref"],
                key=rs["key"],
            )
        )
    else:
        out.append(w["reason_none"])
    out.append(
        (w["verify_line"] if ag.get("stable") else w["verify_line_day"]).format(
            wind_item=wind_item, stab_item=stab_item
        )
    )
    return out
