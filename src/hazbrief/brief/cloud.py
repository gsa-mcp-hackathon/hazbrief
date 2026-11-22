"""The modelled cloud of a dense release: SCICHEM's held record read into the brief
(HB-163 ADDENDA 02, 03 and 06; DN-026; DN-028).

The selection rule (`engine_rule`, run inside the puff channel) classes the release.
For a dense release this module:

1. builds SCICHEM's request from what the brief holds (`scichem.build_request`): the
   SLAB problem the dense-gas channel ran (its deck), the NWS gridpoint forecast the
   brief read, the spill point and the release time, the AEGL tiers at the brief's
   averaging time, and every point the brief draws as a sensor;
2. reads the held record of that request (`scichem.recorded`); a request not held, a
   wet or short forecast, a pool source or a missing tier is SCICHEM's own refusal, and
   the brief says "not modelled" with its reason. SLAB never draws in its place
   (HBD-376);
3. turns the record into what the map and the Hazard tab draw: per tier, the area
   reached at any time (the harm path) and the area at each output step; the
   uncertainty area (per step and tier, the tier's area with the area where the
   probability of exceeding the tier is at least 5 percent, HBD-378); and each point's
   arrival, minutes above and time clear.

**Two requests, so the cordons and the record do not chase each other (ADDENDUM-06
item 4).** A record's name is the sha256 of its request, and the request holds every
drawn point. The modelled cordons (and the suggested points, whose siting reads every
drawn hazard layer) are placed on the cloud's own area, so they cannot be in the
request that draws that area:

- request A holds every point except the modelled cordons and the suggested points;
- the cordons and the siting are placed on A's area reached at any time;
- request B holds every point, these included; B is the record the brief draws.

The engine's sensors do not change the dispersion, so B's step areas equal A's; the
brief refuses a B that differs (`CloudError`), and the test holds it.
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from shapely import make_valid
from shapely.geometry import shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[3]

#: the point layers request A leaves out: placed on the cloud's own area
PLACED_ON_THE_CLOUD = ("modelled_cordons", "sited_points")


class CloudError(RuntimeError):
    """Request B's step areas differ from request A's: the record and the points chase
    each other, and the brief does not draw either."""


class _WithDerived:
    """The brief, read through the derivations made so far (the layer functions read
    `brief.derived`; at derivation time the brief does not hold them yet)."""

    #: HB-192 (DN-024 ADDENDUM-01 decision 9): the engine's sensors are every
    #: candidate block the data holds, not only those the first map draws, so the
    #: request (and its record's name) does not move with what the map shows
    every_candidate = True

    def __init__(self, brief, derived: dict):
        self._brief = brief
        self.derived = derived

    def __getattr__(self, name: str):
        return getattr(self._brief, name)


def record_mode(replay: bool) -> bool:
    """Whether a request not held runs the engine: a live brief does; a replay does
    only under HAZBRIEF_SCICHEM_RECORD (the recording route, as SLAB's
    HAZBRIEF_SLAB_RECORD)."""
    return (not replay) or os.environ.get("HAZBRIEF_SCICHEM_RECORD") == "1"


def places(brief, derived: dict, cfg: dict, sc: dict, *, leave_out=()) -> list:
    """The sensors: every point feature the brief draws in `record.point_layers`, from
    the same layer functions the map is drawn with, less the layers `leave_out`."""
    from hazbrief.brief import layers
    from hazbrief.brief import scichem as SC

    data = layers.build(_WithDerived(brief, derived), cfg)
    data = {"layers": [x for x in data["layers"] if x["id"] not in leave_out]}
    return SC.places_from_map_data(data, sc)


def vertical_for(derived: dict, sc: dict) -> dict | None:
    """HB-189 (DN-028 ADDENDUM-14 decisions 3 and 4): the vertical setting a brief's
    requests take: none by day with no stable hour inside the horizon (the request is
    then byte-identical to one built before); under the stable treatment
    `project.stable_vertical`, or its fallback where `derived["vertical_fallback"]` is
    set (a run at the setting that did not reach hour 1 within its ceiling)."""
    if not (derived.get("stability_hours") or {}).get("stable"):
        return None
    v = sc["project"]["stable_vertical"]
    if derived.get("vertical_fallback"):
        v = v["fallback"]
    return {"vres_m": float(v["vres_m"]), "zmax_m": float(v["zmax_m"])}


def hour1_late(rec: dict, sc: dict) -> bool:
    """Whether an hourly record's first hour came later than the setting's ceiling
    (`project.stable_vertical.hour1_ceiling_s`), or never: decision 4's finding."""
    if not rec.get("request", {}).get("hourly"):
        return False
    hours = rec.get("hours") or []
    ceiling = float(sc["project"]["stable_vertical"]["hour1_ceiling_s"])
    return not hours or float(hours[0]["engine_wall_s"]) > ceiling


def _site(brief, fp: dict) -> tuple[float, float]:
    from hazbrief.brief import derive as D

    p = D.incident_point(brief, fp)
    return float(p.y), float(p.x)


def request(
    brief,
    fp: dict,
    derived: dict,
    grid_body: dict,
    cfg: dict,
    sc: dict,
    pts: list,
    *,
    lines: dict | None = None,
) -> dict:
    """SCICHEM's request for this brief's release (module docstring, step 1); a
    `scichem.Refusal` where an input is not held. With `lines` (HB-173,
    `agreement.yaml lines`), the lines run of the same release: no point sensors, the
    crosswind lines instead, no contours, and the lines' specification in its `meta`
    (part of its name)."""
    from hazbrief import packs as P
    from hazbrief.brief import dense_gas as DG
    from hazbrief.brief import scichem as SC

    dg = derived.get("dense_gas") or {}
    deck = ((dg.get("evidence") or {}).get("record") or {}).get("deck")
    if not deck:
        raise SC.Refusal(
            sc["refusals"]["missing"].format(
                detail="the dense-gas channel's SLAB problem (its deck)"
            )
        )
    (problem,) = DG.read_deck(deck)[:1]
    if not brief.as_given:
        raise SC.Refusal(sc["refusals"]["missing"].format(detail="the release time"))
    local = datetime.fromisoformat(brief.as_given)
    un = str(dg.get("un") or "")
    minutes = float((dg.get("level") or {}).get("minutes") or 0.0)
    if not un or not minutes:
        raise SC.Refusal(
            sc["refusals"]["missing"].format(
                detail="the material or its averaging time"
            )
        )
    mdata = P.load_app_pack("materials_properties").data.model_dump(mode="json")
    tiers = SC.tiers_from_pack(
        mdata, un, minutes, sc["record"]["tiers"], problem["wms"], sc
    )
    lat, lon = _site(brief, fp)
    name = sc["brief"]["material_name"].format(un=un)
    label = sc["brief"]["label"].format(un=un, lat=lat, lon=lon)
    req = SC.build_request(
        problem,
        grid_body,
        lat=lat,
        lon=lon,
        release=local,
        tiers=tiers,
        places=[] if lines else pts,
        cfg=sc,
        material=name,
        label=label,
        tzone=SC.tzone_of(local),
        lines=lines,
        extract=not lines,
        vertical=vertical_for(derived, sc),
    )
    if lines:
        req["meta"]["lines"] = dict(lines)
    return req


def read(req: dict, sc: dict, *, replay: bool, frames: dict | None = None) -> dict:
    """The held record of `req` (with `record_mode`, the run written as one). HB-192:
    `frames` (`frames.spec`) is passed for request A of a run read while it runs: its
    frames are written beside the record and handed to a live page as they land."""
    from hazbrief.brief import scichem as SC

    return SC.recorded(req, sc, record=record_mode(replay), frames=frames)


def frames_spec(req: dict, sc: dict, cfg: dict) -> dict | None:
    """HB-192 (DN-024 ADDENDUM-01 decision 1): the frames asked of request A's run, a
    frame every `frames.every_s` over the brief's horizon (`weather.puff.steps.
    horizon_h`); None for a run that is not read while it runs (no stable hour)."""
    from hazbrief.brief import frames as F

    if not req.get("hourly"):
        return None
    return F.spec(sc["frames"], float(cfg["weather"]["puff"]["steps"]["horizon_h"]))


def same_steps(a: dict, b: dict) -> bool:
    """Whether two records draw the same areas at every step and tier (the sensors do
    not move the cloud)."""
    ra, rb = a.get("result") or {}, b.get("result") or {}
    sa, sb = ra.get("steps") or [], rb.get("steps") or []
    if len(sa) != len(sb):
        return False
    for x, y in zip(sa, sb):
        if x["time_s"] != y["time_s"] or x["tiers"].keys() != y["tiers"].keys():
            return False
        for t in x["tiers"]:
            if x["tiers"][t]["rings_km"] != y["tiers"][t]["rings_km"]:
                return False
        if x["probability"] != y["probability"]:
            return False
    return True


def _gj(rings: list, lat: float, lon: float, places: int) -> dict | None:
    from hazbrief.brief import scichem as SC

    g = SC.to_geojson(rings, lat, lon)
    if g is None:
        return None
    return json.loads(json.dumps(g), parse_float=lambda s: round(float(s), places))


def _shape(rings: list):
    """A record's km rings as one valid shape: each polygon made valid before the
    union (rings rounded to a metre can touch themselves; `scichem.shape_of` unions
    them as written)."""
    from shapely.geometry import Polygon

    from hazbrief.brief import scichem as SC

    polys = [make_valid(Polygon(r[0], r[1:])) for r in rings if r]
    polys = [SC._polygonal(p) for p in polys]
    polys = [p for p in polys if not p.is_empty]
    return unary_union(polys) if polys else Polygon()


def _union(rings_a: list, rings_b: list):
    from hazbrief.brief import scichem as SC

    # an exceedance contour can close on itself (a ring touching its own edge): made
    # valid before the union, as the record's own `contour_shape` does
    parts = [_shape(r) for r in (rings_a, rings_b) if r]
    parts = [p for p in parts if not p.is_empty]
    if not parts:
        return []
    return SC._rings(SC._polygonal(unary_union(parts)))


def drawn(rec: dict, sha_a: str, sc: dict, cfg: dict) -> dict:
    """What the brief draws from record B (module docstring, step 3)."""
    from hazbrief.brief import scichem as SC

    req, res = rec["request"], rec["result"]
    meta = req["meta"]
    lat, lon = meta["site"]["lat"], meta["site"]["lon"]
    places_n = int(cfg["map"]["coord_places"])
    tiers = [
        {k: t[k] for k in ("name", "ppm", "minutes", "receipt")} for t in meta["tiers"]
    ]
    names = [t["name"] for t in tiers]
    outer = names[0]
    pct = sc["brief"]["uncertainty_percent"]
    steps = []
    for s in res["steps"]:
        prob = (s.get("probability") or {}).get(pct) or {}
        steps.append(
            {
                "minute": round(s["time_s"] / 60.0),
                "tiers": {
                    t: _gj(s["tiers"][t]["rings_km"], lat, lon, places_n) for t in names
                },
                "area_km2": {t: s["tiers"][t]["area_km2"] for t in names},
                "contains_source": {t: s["tiers"][t]["contains_source"] for t in names},
                # HBD-378: the tier's area with the area where P(C > tier) >= 5 percent
                "extent": _gj(
                    _union(
                        s["tiers"][outer]["rings_km"],
                        (prob.get(outer) or {}).get("rings_km") or [],
                    ),
                    lat,
                    lon,
                    places_n,
                ),
            }
        )
    any_time = {
        t: _gj(res["any_time"][t]["rings_km"], lat, lon, places_n) for t in names
    }
    # the uncertainty area reached at any time: the union of every step's
    ext = [
        _shape(
            _union(
                s["tiers"][outer]["rings_km"],
                (((s.get("probability") or {}).get(pct) or {}).get(outer) or {}).get(
                    "rings_km"
                )
                or [],
            )
        )
        for s in res["steps"]
    ]
    ext = [make_valid(g) for g in ext if not g.is_empty]
    ext_rings = SC._rings(SC._polygonal(unary_union(ext))) if ext else []
    src = meta["source"]
    # the farthest point of each level's harm path from the source (m): the reach the
    # agreement field sets beside SLAB's
    reach = {}
    for t in names:
        pts = [
            xy
            for poly in res["any_time"][t]["rings_km"]
            for ring in poly[:1]
            for xy in ring
        ]
        if pts:
            reach[t] = round(max(math.hypot(x, y) for x, y in pts) * 1000.0)
    # HB-173: a level whose area touches the engine's domain is cut by it, so its reach
    # is a lower bound (DN-028 ADDENDUM-03 section 2); HB-182: the domain is the
    # request's, never the outermost contour's own extent
    from hazbrief.brief import agreement as AG

    edges = AG.domain_edges(rec, AG.load_config())
    frames, frames_run = _frames(sha_a, names, lat, lon, places_n, meta)
    return {
        # HB-192 (DN-024 ADDENDUM-01): the 15-minute frames' outlines drawn from the
        # stored mesh, read from request A's frames record (empty where none is held),
        # and how the run computed them; the mesh itself stays in the record
        "frames": frames,
        "frames_run": frames_run,
        "reach_m": reach,
        "reach_cut": {t: bool(edges.get(t)) for t in names},
        # HB-182: per cut level, where the post-processor's field ends along the edge
        # its area meets (km from the site, each way)
        "cut_edge_km": {t: edges[t] for t in names if edges.get(t)},
        # HB-178 (Issue 78ccbb4b): where a cut level's area meets the grid's edge,
        # drawn on the map at the cut
        "cut_edges": cut_edges(rec, edges, lat, lon, places_n),
        "any_time_km2": {t: res["any_time"][t]["area_km2"] for t in names},
        "engine": sc["brief"]["engine"],
        "state": "drawn",
        "reason": None,
        "record": rec["request_sha256"],
        "record_a": sha_a,
        "engine_id": rec.get("engine_id"),
        "engine_kind": rec.get("engine_kind"),
        "site": {"lat": lat, "lon": lon},
        "release_utc": meta["release_utc"],
        "release_minutes": round(float(src["duration_s"]) / 60.0, 3),
        "tiers": tiers,
        "steps": steps,
        "any_time": any_time,
        "any_time_extent": _gj(ext_rings, lat, lon, places_n),
        "places": [
            {
                k: p.get(k)
                for k in (
                    "id",
                    "kind",
                    "names",
                    "lat",
                    "lon",
                    "layers",
                    "distance_m",
                    "highest_tier",
                    "peak_ppm",
                    "tiers",
                    "reached",
                )
            }
            for p in res["places"]
        ],
        "met": [
            {k: m[k] for k in ("time", "speed_m_s", "direction_deg") if k in m}
            for m in meta["met"]
        ],
        "inputs": meta["inputs"],
        "assumptions": meta["assumptions"],
        "cloud_left_domain": res.get("cloud_left_domain"),
        "engine_end_s": res.get("engine_end_s"),
    }


def _frames(
    sha_a: str, names: list[str], lat: float, lon: float, places_n: int, meta: dict
) -> tuple[list[dict], dict | None]:
    """HB-192: request A's frames as the map draws them (each level's stored outline as
    GeoJSON about the site; nothing is decoded or drawn here: the outlines were drawn
    from the mesh when the frames record was made), and the run's line: how many
    frames, every how many minutes, to which minute, at which vertical setting, how it
    was made, and the engine's wall time to the first and the last frame. ([], None)
    where no frames record is held."""
    from hazbrief.brief import frames as F

    held = F.read_record(sha_a)
    if held is None:
        return [], None
    out = []
    for fr in held.get("frames") or []:
        if fr.get("error"):
            continue
        out.append(
            {
                "minute": int(fr["minute"]),
                "tiers": {
                    t: _gj((fr.get("outlines") or {}).get(t) or [], lat, lon, places_n)
                    for t in names
                },
            }
        )
    walls = [fr.get("engine_wall_s") for fr in held.get("frames") or []]
    walls = [w for w in walls if w is not None]
    spec = held.get("spec") or {}
    run = {
        "count": len(out),
        "every_min": round(float(spec.get("every_s", 0)) / 60.0),
        "until_min": round(float(spec.get("until_s", 0)) / 60.0),
        "last_min": out[-1]["minute"] if out else None,
        "spacing_m": round(float(spec.get("spacing_km", 0)) * 1000.0, 3),
        "tolerance_m": (held.get("config") or {}).get("tolerance_m"),
        "drawn_within_m": (held.get("config") or {}).get("drawn_within_m"),
        "vertical_setting_m": (meta.get("inputs") or {}).get("vertical_setting_m"),
        "levels_kg": {t["name"]: float(t["kg_m3"]) for t in meta["tiers"]},
        "made": held.get("made"),
        "first_s": walls[0] if walls else None,
        "last_s": walls[-1] if walls else None,
        "record": sha_a,
    }
    return out, run


def cut_edges(
    rec: dict, edges: dict[str, list[float]], lat: float, lon: float, places: int
) -> dict[str, dict]:
    """HB-178 (Issue 78ccbb4b; HBD-419): per level whose area reached at any time is cut
    by the engine's domain, the stretch of the grid's edge that area meets, as a GeoJSON
    line about the site: where the map marks the cut. A level not cut has none. HB-182:
    the edge is each outermost cell centre the level's own area reaches
    (`agreement.domain_edges`); the field's edge lies at 28.5 km where the grid is
    refined once and 29.25 km where twice, so one level can meet both."""
    from shapely.geometry import LineString, MultiLineString, box
    from shapely.ops import unary_union

    from hazbrief.brief import agreement as AG
    from hazbrief.brief import scichem as SC

    tol = float(AG.load_config()["reach"]["edge_tolerance_km"])
    out = {}
    for t, a in (rec["result"].get("any_time") or {}).items():
        if not edges.get(t):
            continue
        area = _shape(a["rings_km"])
        if area.is_empty:
            continue
        rims = [box(-e, -e, e, e).boundary for e in edges[t]]
        # one rim as it is (the line HB-178 drew); two or more noded together
        edge = rims[0] if len(rims) == 1 else unary_union(rims)
        g = edge.intersection(area.buffer(2 * tol))
        parts = [
            p
            for p in (g.geoms if hasattr(g, "geoms") else [g])
            if isinstance(p, LineString) and not p.is_empty
        ]
        if not parts:
            continue
        lines = [
            [SC.G.offset(lat, lon, x * 1000.0, y * 1000.0) for x, y in p.coords]
            for p in MultiLineString(parts).geoms
        ]
        gj = {"type": "MultiLineString", "coordinates": lines}
        out[t] = json.loads(
            json.dumps(gj), parse_float=lambda v: round(float(v), places)
        )
    return out


def times(cl: dict) -> dict:
    """HB-163 item 6 and ADDENDUM-04: what the cloud's record measures, as numbers
    (minutes after the release), for the page's lines and the tests:

    - `scene_clear_min`: the first output step after the last at which any level
      covers the source (the time the last level leaves the scene), None where it still
      covers it at the run's last step;
    - `places`: each named place and suggested point the cloud reaches: first arrival
      of the outermost level, minutes above the highest level reached there, and clear
      (the outermost level's);
    - `roadblocks`: each roadblock and cordon position: as above, or not reached;
    - `roadblocks_reached` and `first_roadblock_min`: how many reach the lowest level
      or above, and the earliest arrival among them."""
    tiers = [t["name"] for t in cl.get("tiers") or []]
    outer = tiers[0] if tiers else None
    steps = cl.get("steps") or []
    covering = [s["minute"] for s in steps if any(s["contains_source"].values())]
    after = [s["minute"] for s in steps if covering and s["minute"] > covering[-1]]
    scene = after[0] if after else None

    def row(p: dict) -> dict:
        hi = p.get("highest_tier")
        o = (p.get("tiers") or {}).get(outer) or {}
        h = (p.get("tiers") or {}).get(hi) or {}
        return {
            "id": p["id"],
            "kind": p["kind"],
            "names": list(p.get("names") or []),
            "lat": p["lat"],
            "lon": p["lon"],
            "highest": hi,
            "arrival_min": o["arrival_s"] / 60.0
            if o.get("arrival_s") is not None
            else None,
            "minutes_above": h.get("minutes_above") if hi else 0.0,
            "clear_min": o["clear_s"] / 60.0 if o.get("clear_s") is not None else None,
            "distance_m": p.get("distance_m"),
        }

    rows = [row(p) for p in cl.get("places") or []]
    places = [r for r in rows if r["kind"] in ("named_place", "sited") and r["highest"]]
    blocks = [r for r in rows if r["kind"] == "roadblock"]
    reached = [r for r in blocks if r["highest"]]
    return {
        "scene_clear_min": scene,
        "places": sorted(places, key=lambda r: (r["arrival_min"], r["distance_m"])),
        "roadblocks": sorted(
            blocks,
            key=lambda r: (
                r["arrival_min"] is None,
                r["arrival_min"] or 0,
                r["distance_m"],
            ),
        ),
        "roadblocks_reached": len(reached),
        "first_roadblock_min": min((r["arrival_min"] for r in reached), default=None),
    }


def refused(reason: str, sc: dict, **extra: Any) -> dict:
    return {
        "engine": sc["brief"]["engine"],
        "state": "not_modelled",
        "reason": reason,
        "record": None,
        "steps": [],
        "any_time": {},
        "places": [],
        **extra,
    }


def any_time_shape(rec: dict, tier: str | None = None):
    """Record `rec`'s area reached at any time for `tier` (the outermost when None), in
    longitude and latitude, or None."""
    from hazbrief.brief import scichem as SC

    meta = rec["request"]["meta"]
    names = [t["name"] for t in meta["tiers"]]
    rings = rec["result"]["any_time"][tier or names[0]]["rings_km"]
    g = SC.to_geojson(rings, meta["site"]["lat"], meta["site"]["lon"])
    return shape(g) if g else None
