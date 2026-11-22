"""Derivations over held and catalogued data (DN-015 sections 2 and 3; HB-54).

**Roadblock candidates** (DN-015 section 2). Where a zone boundary of the footprint
crosses a road: shapely's intersection of each TIGER road line with each zone polygon's
boundary, one point per crossing. Crossings of one road within `merge_m` of each other
are one candidate (a divided highway is two lines). Each carries the road's name, its
MTFCC class, the zone and the road's bearing there. Rail lines (the NTAD features
`facilities_in_footprint` read) are crossed the same way. CATS did this (Kaul 2000,
`esri-uc2000-cats-pap722`: "all the street locations required to completely interdict
the hazard area"); the workbench does the geometric half and stops: no ordering, no
minimum set, no closure plan.

**The downstream path** (DN-015 section 3). From the 3DHP flowline nearest the spill
within D m, the USGS NLDI's downstream-main navigation for L km. NLDI navigates NHDPlus
V2 comids, not 3DHP ids (HB-54's probe), so the start is the comid whose catchment holds
the point on that flowline nearest the spill. Its path is used only if it follows 3DHP's
own downstream path along the first `along_km` (HB-58, `along_length`: within
`nldi_match_m` plus half the river's width at every sample), else the path is 3DHP's
connectivity inside the footprint. Both begin where the spill meets the nearest flowline
(`cut_point`). A live brief bounds NLDI's wait and says why it fell back (`_nldi_get`).
NLDI serves no names: each reach takes the name of the 3DHP flowline nearest its
midpoint. No travel time, no concentration (invariant 1).

**Workplaces, establishments and terrain** (DN-015 sections 4 and 5; HB-55). LODES
WAC jobs per block, joined on GEOID to the blocks the population layer draws; County
Business Patterns establishments by two-digit NAICS for the counties those blocks lie
in, complete; elevation from the USGS Elevation Point Query Service at the spill and
along each zone boundary; land cover from the Annual NLCD COG mirror at the spill, over
the footprint and along the downstream path (HB-59 ADDENDUM-03). Data only: what terrain
does to a release is the modelled tier (DN-009 E6), not drawn.

**Weather over the response window** (DN-016 sections 3 and 4; HB-56). The NWS
gridpoint forecast at the spill for `weather.window_h` hours after the as-given time,
with a flag when its wind turns past `weather.veer_flag_deg` from the wind the footprint
is oriented on (the footprint is never re-oriented on it); and the radar layer a live
brief draws from nowCOAST's WMS capabilities. A replayed brief holds no radar.

**Pure over records.** `roadblock_candidates`, `rail_candidates` and `downstream_path`
read only their arguments, so the tests run them on recorded exchanges. `run` gathers
the inputs for one brief through the one upstream client (`hazbrief.utils`): from the
recorded files when the brief replays, so the committed briefs make no call, and through
the recorder when `scripts/record_derivations.py` records them. A derivation whose input
is not held says so (`reason`), as the layer list's "Not drawn" does.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import csv
import dataclasses
import gzip
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import shapely
from shapely.geometry import LineString, MultiLineString, Point, mapping, shape
from shapely.ops import linemerge, nearest_points, substring, unary_union

from hazbrief import facilities
from hazbrief.brief import cog
from hazbrief.config import settings
from hazbrief.geometry import COORDINATE_DECIMALS
from hazbrief.utils import (
    Exchange,
    UnrecordedExchangeError,
    UpstreamServiceError,
    UpstreamStatusError,
    UpstreamTimeoutError,
    exchange_file,
    exchange_key,
    fetch_json,
    fetch_range,
)

#: The footprint's zone polygons a candidate can sit on, in draw order (inner first).
#: The zones a boundary is read from. `modelled_boundary` is never in a server
#: footprint: HB-157 item 8 builds it from the outer boundary of every drawn hazard
#: layer (`modelled_cordons`).
ZONES = (
    "initial_isolation_zone",
    "fire_isolation",
    "protective_action_zone",
    "modelled_boundary",
)


class DeriveError(RuntimeError):
    """An input the derivation cannot use: an error object, a truncated answer."""


# ── geometry helpers ──────────────────────────────────────────────────────────────────


def _plane(g, c: Point):
    """`g` in metres on the local plane around `c` (facilities.buffer's projection)."""
    scale = (math.cos(math.radians(c.y)) * facilities._M_PER_DEG, facilities._M_PER_DEG)
    return shapely.transform(g, lambda xy: (xy - (c.x, c.y)) * scale)


def _unplane(g, c: Point):
    """`_plane`'s inverse: `g` from metres around `c` back to longitude and latitude."""
    scale = (math.cos(math.radians(c.y)) * facilities._M_PER_DEG, facilities._M_PER_DEG)
    return shapely.transform(g, lambda xy: xy / scale + (c.x, c.y))


def _metres(a, b, c: Point) -> float:
    """The distance between two geometries, in metres on the local plane around `c`."""
    return _plane(a, c).distance(_plane(b, c))


def _rnd(x: float) -> float:
    return round(x, COORDINATE_DECIMALS)


def _points(g) -> list[Point]:
    """The crossing points of an intersection: a point, several, or the two ends of a
    piece of road that runs along the boundary."""
    if g.is_empty:
        return []
    if isinstance(g, Point):
        return [g]
    if isinstance(g, LineString):
        return [Point(g.coords[0]), Point(g.coords[-1])]
    out: list[Point] = []
    for part in getattr(g, "geoms", []):
        out += _points(part)
    return out


def zone_polygons(footprint: dict) -> list[tuple[str, Any]]:
    """(zone, polygon) of each zone polygon the footprint draws, inner zones first."""
    out = []
    for zone in ZONES:
        for f in (footprint.get("footprint") or {}).get("features") or []:
            if f["properties"].get("zone") != zone:
                continue
            if f["geometry"]["type"] in ("Polygon", "MultiPolygon"):
                out.append((zone, shape(f["geometry"])))
    return out


def esri_line(geom: dict):
    """A LineString (or MultiLineString) from an ArcGIS JSON polyline's `paths`."""
    paths = [p for p in geom.get("paths") or [] if len(p) >= 2]
    if not paths:
        return None
    return LineString(paths[0]) if len(paths) == 1 else MultiLineString(paths)


def _bearing_at(line, pt: Point, span_m: float) -> float | None:
    """The line's direction through `pt`, 0 to 180 degrees (a road runs both ways),
    between the points `span_m` along it on each side."""
    parts = list(line.geoms) if isinstance(line, MultiLineString) else [line]
    part = min(parts, key=lambda p: p.distance(pt))
    span = span_m / facilities._M_PER_DEG
    d = part.project(pt)
    a = part.interpolate(max(0.0, d - span))
    b = part.interpolate(min(part.length, d + span))
    if a.equals(b):
        return None
    _, az = facilities.inverse(a.y, a.x, b.y, b.x)
    return round(az % 180)


# ── roadblock candidates ──────────────────────────────────────────────────────────────


def boundary_crossings(
    footprint: dict, lines: list[tuple[str, dict, Any]], merge_m: float, span_m: float
) -> list[dict]:
    """Every point where a line crosses a zone boundary, merged per (zone, line key)
    within `merge_m`. `lines` is (key, attributes, geometry); one key is one road (or
    rail line), however many lines it is drawn as."""
    out = []
    for zone, poly in zone_polygons(footprint):
        edge = poly.boundary
        hits: dict[str, list[tuple[Point, dict, Any]]] = {}
        for key, attrs, geom in lines:
            for p in _points(geom.intersection(edge)):
                hits.setdefault(key, []).append((p, attrs, geom))
        for key in sorted(hits):
            for cluster in _clusters(hits[key], merge_m):
                pts = [p for p, _, _ in cluster]
                c = unary_union(pts).centroid
                # the candidate is an actual crossing: the one nearest the centre
                p, attrs, geom = min(cluster, key=lambda h: (h[0].distance(c), h[0].x))
                out.append(
                    {
                        "key": key,
                        "attributes": attrs,
                        "zone": zone,
                        "coordinates": [_rnd(p.x), _rnd(p.y)],
                        "bearing_deg": _bearing_at(geom, p, span_m),
                        "crossings": len(cluster),
                    }
                )
    return out


def _clusters(hits: list, merge_m: float) -> list[list]:
    """Single-linkage clusters of crossing points within `merge_m` (union-find), in a
    stable order."""
    hits = sorted(hits, key=lambda h: (h[0].x, h[0].y))
    parent = list(range(len(hits)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(hits)):
        for j in range(i + 1, len(hits)):
            if _metres(hits[i][0], hits[j][0], hits[i][0]) <= merge_m:
                parent[find(j)] = find(i)
    groups: dict[int, list] = {}
    for i, h in enumerate(hits):
        groups.setdefault(find(i), []).append(h)
    return [groups[k] for k in sorted(groups)]


def roadblock_candidates(footprint: dict, roads: list[dict], cfg: dict) -> dict:
    """The roadblock candidates of DN-015 section 2. `roads` are TIGERweb road
    features (ArcGIS JSON: `attributes`, `geometry.paths`). Only the configured MTFCC
    classes count. Returns {candidates, classes, merge_m, label, reason}."""
    spec = cfg["derive"]["roads"]
    classes = list(spec["classes"])
    lines = []
    for f in roads:
        a = f.get("attributes") or {}
        if a.get("MTFCC") not in classes:
            continue
        g = esri_line(f.get("geometry") or {})
        if g is None:
            continue
        lines.append((a.get("NAME") or f"unnamed line {a.get('OID')}", a, g))
    found = boundary_crossings(
        footprint, lines, spec["merge_m"], spec["bearing_span_m"]
    )
    cands = [
        {
            "road": c["attributes"].get("NAME") or "unnamed",
            "mtfcc": c["attributes"].get("MTFCC"),
            "zone": c["zone"],
            "coordinates": c["coordinates"],
            "bearing_deg": c["bearing_deg"],
            "crossings": c["crossings"],
        }
        for c in found
    ]
    reason = None
    if not zone_polygons(footprint):
        reason = "the footprint draws no zone polygon"
    elif not lines:
        reason = f"no road of class {', '.join(classes)} in the footprint's extent"
    elif not cands:
        reason = f"no road of class {', '.join(classes)} crosses a zone boundary"
    return {
        "candidates": cands,
        "classes": classes,
        "merge_m": spec["merge_m"],
        "label": spec["label"],
        "reason": reason,
    }


def rail_candidates(footprint: dict, rail: list[dict], cfg: dict) -> dict:
    """The same crossings for the NTAD rail lines (GeoJSON features, one per FRA arc);
    one rail line is one owner and subdivision."""
    spec = cfg["derive"]
    lines = []
    for f in rail:
        p = f.get("properties") or {}
        if not f.get("geometry"):
            continue
        key = f"{p.get('RROWNER1') or 'unknown owner'} {p.get('SUBDIV') or ''}".strip()
        lines.append((key, p, shape(f["geometry"])))
    found = boundary_crossings(
        footprint, lines, spec["roads"]["merge_m"], spec["roads"]["bearing_span_m"]
    )
    cands = [
        {
            "owner": c["attributes"].get("RROWNER1"),
            "subdivision": c["attributes"].get("SUBDIV"),
            "fra_arc": c["attributes"].get("FRAARCID"),
            "zone": c["zone"],
            "coordinates": c["coordinates"],
            "bearing_deg": c["bearing_deg"],
            "crossings": c["crossings"],
        }
        for c in found
    ]
    reason = None
    if not lines:
        reason = "no rail line in the footprint"
    elif not cands:
        reason = "no rail line crosses a zone boundary"
    return {
        "candidates": cands,
        "merge_m": spec["roads"]["merge_m"],
        "label": spec["rail"]["label"],
        "reason": reason,
    }


# ── the roadblock offset (HB-142R items 4 and 5; DN-019 ADDENDUM-02 F11) ─────────────


def _road_lines(roads: list[dict], classes: list[str]) -> list[tuple[str, dict, Any]]:
    """(key, attributes, geometry) of each TIGERweb road of `classes`; one key is one
    road by its name, or its line when unnamed (`roadblock_candidates`' rule)."""
    out = []
    for f in roads:
        a = f.get("attributes") or {}
        if a.get("MTFCC") not in classes:
            continue
        g = esri_line(f.get("geometry") or {})
        if g is None:
            continue
        out.append((a.get("NAME") or f"unnamed line {a.get('OID')}", a, g))
    return out


def _parts(g) -> list[LineString]:
    return list(g.geoms) if isinstance(g, MultiLineString) else [g]


def _junctions(walk: LineString, other, tol: float) -> list[Point]:
    """The points where `other` meets `walk` at a shared node and leaves it: a vertex
    of `other` within `tol` of `walk` whose neighbour on `other` is off `walk` (all in
    metres on one plane). Two lines that only cross, a bridge over a road, share no
    vertex there and give none; a second TIGER name drawn on the same carriageway (US
    Hwy 15 and James Monroe Hwy) never leaves it and gives none."""
    out = []
    for part in _parts(other):
        if part.distance(walk) > tol:
            continue
        pc = list(part.coords)
        for i, xy in enumerate(pc):
            p = Point(xy)
            if walk.distance(p) > tol:
                continue
            nbrs = [pc[j] for j in (i - 1, i + 1) if 0 <= j < len(pc)]
            if any(walk.distance(Point(q)) > tol for q in nbrs):
                out.append(walk.interpolate(walk.project(p)))
    return out


def _outward(part: LineString, d0: float, poly, step: float) -> int:
    """+1 when the line leaves `poly` going forward from `d0`, -1 going backward, 0
    when neither side or both sides are outside (the road runs along the boundary)."""
    ahead = part.interpolate(min(part.length, d0 + step))
    behind = part.interpolate(max(0.0, d0 - step))
    out_a = d0 + 1e-9 < part.length and not poly.covers(ahead)
    out_b = d0 > 1e-9 and not poly.covers(behind)
    if out_a and not out_b:
        return 1
    if out_b and not out_a:
        return -1
    return 0


def _heading(a, b) -> float:
    return math.degrees(math.atan2(b[0] - a[0], b[1] - a[1])) % 360


def _continuation(walk: LineString, others, walked: set, tol: float, spec: dict):
    """Where the road goes on at the end of `walk`: (key, line from the end) or None.
    A line that begins where `walk` ends and is the only one there continues it (a
    name change: State Hwy 28 becomes Clay St). At a node more lines meet, the line
    that turns least continues it when it turns at most `max_turn_deg` (the road goes
    straight through the junction); otherwise the road ends there (a T)."""
    coords = list(walk.coords)
    end = Point(coords[-1])
    ahead = _heading(coords[-2], coords[-1])
    options = []
    lines_here = 0
    for k, g in others:
        if k in walked or g.distance(end) > tol:
            continue
        lines_here += 1
        for part in _parts(g):
            if part.distance(end) > tol:
                continue
            pc = list(part.coords)
            d = part.project(end)
            if d <= tol:
                branches = [LineString(pc)]
            elif d >= part.length - tol:
                branches = [LineString(pc[::-1])]
            else:
                # the walk ends on a through line: both ways along it
                branches = [substring(part, d, part.length), substring(part, d, 0.0)]
            for br in branches:
                if not isinstance(br, LineString) or br.length <= tol:
                    continue
                bc = list(br.coords)
                turn = abs((_heading(bc[0], bc[1]) - ahead + 180) % 360 - 180)
                options.append((turn, k, br))
    if not options:
        return None
    turn, k, br = min(options, key=lambda o: (o[0], o[1]))
    if lines_here == 1 and len(options) == 1:
        return k, br
    if turn <= float(spec["max_turn_deg"]):
        return k, br
    return None


def offset_candidate(
    crossing: Point,
    key: str,
    zone_poly,
    lines: list[tuple[str, dict, Any]],
    spec: dict,
    forbid=None,
) -> dict:
    """Where a roadblock candidate stands (HB-142R item 4): from the crossing of road
    `key` with `zone_poly`'s boundary, outward along the road to the first junction
    outside the zone at least `min_m` and at most `max_m` along it; with none, the
    point `min_m` along it. A road that changes its name at a node no third line meets
    is followed through. Returns {coordinates, offset_m, rule, meets}; `rule` is one of
    `junction`, `minimum`, `past_zone`, `line_end`, `no_outward` or `dropped`
    (`spec["rules"]`).

    HB-178 (Issue 2c1d5f53; DN-023 ADDENDUM-01, held as a draft): the point never
    stands inside `forbid` (default `zone_poly`): the zone the candidate guards and
    every other zone its crossing is not already inside. Where the minimum point is
    inside it, the candidate stands at the first point past it, within `max_m`, that is
    outside (`past_zone`); where none is, or the held line ends inside it, the
    candidate is `dropped` from that road, with `coordinates` None, never placed
    inside."""
    c = crossing
    poly = _plane(zone_poly, c)
    bad = poly if forbid is None else _plane(forbid, c)
    origin = Point(0.0, 0.0)
    own = [_plane(g, c) for k, _, g in lines if k == key]
    tol = float(spec["junction_m"])
    lo, hi = float(spec["min_m"]), float(spec["max_m"])
    pieces = [p for g in own for p in _parts(g)]
    if not pieces:
        raise DeriveError(f"road {key!r} is not among the held lines")
    part = min(pieces, key=lambda p: p.distance(origin))
    d0 = part.project(origin)
    sign = _outward(part, d0, poly, float(spec["step_m"]))
    if sign == 0:
        return {
            "coordinates": [_rnd(c.x), _rnd(c.y)],
            "offset_m": 0.0,
            "rule": "no_outward",
            "meets": None,
        }
    walk = substring(part, d0, part.length if sign > 0 else 0.0)
    walked_keys = {key}
    others = [(k, _plane(g, c)) for k, _, g in lines]
    for _ in range(int(spec["max_follow"])):
        if walk.length >= hi:
            break
        nxt = _continuation(walk, others, walked_keys, tol, spec)
        if nxt is None:
            break
        k2, p2 = nxt
        walk = LineString(list(walk.coords) + list(p2.coords)[1:])
        walked_keys.add(k2)
    best: tuple[float, str] | None = None
    for k, g in others:
        if k in walked_keys:
            continue
        for p in _junctions(walk, g, tol):
            s = walk.project(p)
            if s < lo or s > hi or bad.covers(p):
                continue
            if best is None or (s, k) < best:
                best = (s, k)
    if best is not None:
        s, meets, rule = best[0], best[1], "junction"
    elif walk.length >= lo:
        s = _first_outside(walk, bad, lo, min(hi, walk.length), tol)
        meets = None
        rule = "minimum" if s == lo else "past_zone"
    else:
        s, meets, rule = walk.length, None, "line_end"
        if bad.covers(walk.interpolate(s)):
            s = None
    if s is None:
        return {
            "coordinates": None,
            "offset_m": None,
            "rule": "dropped",
            "meets": None,
        }
    pt = _unplane(walk.interpolate(s), c)
    return {
        "coordinates": [_rnd(pt.x), _rnd(pt.y)],
        "offset_m": round(s, 1),
        "rule": rule,
        "meets": meets,
    }


def _first_outside(
    walk: LineString, bad, lo: float, hi: float, margin: float
) -> float | None:
    """HB-178: the first distance along `walk`, from `lo` to `hi`, whose point `bad`
    does not cover (all in metres on one plane): `lo` itself where it is outside, else
    `margin` past where the walk leaves `bad` (so the rounded coordinates stay out);
    None where no stretch of that length is outside."""
    if hi < lo:
        return None
    if not bad.covers(walk.interpolate(lo)):
        return lo
    seg = substring(walk, lo, hi)
    if not isinstance(seg, LineString) or seg.length <= 0:
        return None
    free = seg.difference(bad)
    best = None
    for part in _parts_any(free):
        if part.is_empty:
            continue
        a, b = sorted(
            walk.project(Point(xy)) for xy in (part.coords[0], part.coords[-1])
        )
        s = math.ceil((a + margin) * 10) / 10
        if s <= min(b, hi) and not bad.covers(walk.interpolate(s)):
            best = s if best is None else min(best, s)
    return best


def _parts_any(g) -> list[LineString]:
    """The line parts of a difference: a line, a multi-line or a collection."""
    if isinstance(g, LineString):
        return [g]
    return [p for p in getattr(g, "geoms", []) if isinstance(p, LineString)]


def offset_candidates(footprint: dict, roads: list[dict], cfg: dict) -> dict:
    """HB-142R items 4 and 5: every crossing of a zone boundary by a road of the
    offset classes (`derive.roads.offset.classes`) is a candidate, merged as
    `roadblock_candidates` merges, and each stands at its offset point. `roads` are the
    offset query's TIGERweb features (`fetch_offset_roads`)."""
    base = cfg["derive"]["roads"]
    spec = base["offset"]
    classes = list(spec["classes"])
    lines = _road_lines(roads, classes)
    found = boundary_crossings(
        footprint, lines, base["merge_m"], base["bearing_span_m"]
    )
    polys = dict(zone_polygons(footprint))
    bounds = [g.bounds for _, _, g in lines]
    # a candidate's walk never runs past `max_m` from its crossing, so only the lines
    # within that distance (and the junction tolerance) can bear on it; the rest are
    # not projected (the pair's 500-odd lines times its 69 to 104 crossings)
    reach = float(spec["max_m"]) + float(spec["junction_m"]) + 1.0
    cands, dropped = [], []
    for c in found:
        pt = Point(c["coordinates"])
        dy = reach / facilities._M_PER_DEG
        dx = dy / math.cos(math.radians(pt.y))
        near = [
            ln
            for ln, (w, s, e, n) in zip(lines, bounds)
            if w <= pt.x + dx and e >= pt.x - dx and s <= pt.y + dy and n >= pt.y - dy
        ]
        # HB-178: the zone it guards and every zone its crossing is not inside (an
        # isolation-circle crossing inside the protective action zone stays an inner
        # cordon, HB-157 item 8)
        forbid = unary_union(
            [polys[c["zone"]]]
            + [g for z, g in polys.items() if z != c["zone"] and not g.contains(pt)]
        )
        off = offset_candidate(pt, c["key"], polys[c["zone"]], near, spec, forbid)
        if off["rule"] == "dropped":
            dropped.append(
                {
                    "road": c["attributes"].get("NAME") or "unnamed",
                    "mtfcc": c["attributes"].get("MTFCC"),
                    "tiger_oid": c["attributes"].get("OID"),
                    "zone": c["zone"],
                    "crossing": c["coordinates"],
                    "why": spec["dropped"].format(min=spec["min_m"], max=spec["max_m"]),
                }
            )
            continue
        cands.append(
            {
                "road": c["attributes"].get("NAME") or "unnamed",
                "mtfcc": c["attributes"].get("MTFCC"),
                "tiger_oid": c["attributes"].get("OID"),
                "zone": c["zone"],
                "coordinates": off["coordinates"],
                "crossing": c["coordinates"],
                "offset_m": off["offset_m"],
                "offset_rule": off["rule"],
                "meets": off["meets"],
                "bearing_deg": c["bearing_deg"],
                "crossings": c["crossings"],
            }
        )
    reason = None
    if not polys:
        reason = "the footprint draws no zone polygon"
    elif not lines:
        reason = f"no road of class {', '.join(classes)} in the footprint's extent"
    elif not cands and not dropped:
        reason = f"no road of class {', '.join(classes)} crosses a zone boundary"
    words = spec["rule_words"].format(min=spec["min_m"], max=spec["max_m"])
    return {
        "candidates": cands,
        "dropped": dropped,
        "classes": classes,
        "merge_m": base["merge_m"],
        "label": spec["label"].format(rule_words=words),
        "offset": {
            "min_m": spec["min_m"],
            "max_m": spec["max_m"],
            "rules": dict(spec["rules"]),
        },
        "reason": reason,
    }


# ── the services outside the footprint (HB-142R item 1; DN-019 ADDENDUM-02 F6) ───────


def area_radius_m(cfg: dict) -> float:
    """The area radius (HB-155 ADDENDUM-01 and ADDENDUM-02; DN-023 section 5.1):
    `derive.area.radius_m`, the operator's default, 10 miles."""
    return float(cfg["derive"]["area"]["radius_m"])


def traffic_radius_m(cfg: dict) -> float:
    """HB-155 ADDENDUM-02 item 2 (HBD-368): the traffic radius.
    `derive.traffic.radius_m` unset means the area radius (paired: traffic exists to
    get responders in and people out,
    so it is as local as they are); set, it is independent. HB-145 reads it."""
    own = (cfg["derive"].get("traffic") or {}).get("radius_m")
    return area_radius_m(cfg) if own is None else float(own)


def nearby_radius_m(footprint: dict, cfg: dict) -> float:
    """The services' search radius: the area radius (HB-155 ADDENDUM-01 item 2 replaced
    HB-142R's three times the protective action distance; the footprint no longer sets
    it, and is taken for the callers that pass it)."""
    return area_radius_m(cfg)


def area_steps_m(cfg: dict) -> list[float]:
    """The reader's steps (`derive.area.steps_mi`) in metres, then the ceiling."""
    a = cfg["derive"]["area"]
    mpm = float(a["metres_per_mile"])
    return sorted(
        {float(round(mi * mpm)) for mi in a["steps_mi"]} | {float(a["ceiling_m"])}
    )


def _distance_bearing(a: Point, b: Point) -> tuple[float, float]:
    """Geodesic metres and initial bearing (degrees from north) from a to b."""
    d, az = facilities.inverse(a.y, a.x, b.y, b.x)
    return d, az % 360


def nearby_services(
    incident: Point,
    footprint: dict,
    stations: dict[str, list[dict]],
    hospitals: list[dict] | None,
    cfg: dict,
) -> dict:
    """Every facility of each class outside the footprint's zones and within the area
    radius, sorted by distance from the incident (ties by name); a class with none
    inside widens to its nearest, never past the area's ceiling (HB-155 ADDENDUM-01 item
    3). `beyond` holds, per class, the rest of what is in hand past the class's radius,
    for the reader's wider steps. `stations` are the National Structures Dataset GeoJSON
    features by class; `hospitals` are receiving_hospitals' rows (CMS), or None when
    that
    tool did not answer. Pure."""
    spec = cfg["derive"]["nearby"]
    radius = area_radius_m(cfg)
    ceiling = max(radius, float(cfg["derive"]["area"]["ceiling_m"]))
    zones = [p for _, p in zone_polygons(footprint)]
    area = unary_union(zones) if zones else None
    out: dict[str, list[dict]] = {}
    beyond: dict[str, list[dict]] = {}
    candidates: dict[str, int] = {}
    inside: dict[str, int] = {}
    search: dict[str, dict] = {}

    def keep(cls: str, rows: list[dict]) -> None:
        outside = []
        candidates[cls] = len(rows)
        inside[cls] = 0
        for r in rows:
            pt = Point(r["coordinates"])
            if area is not None and area.covers(pt):
                inside[cls] += 1
                continue
            d, az = _distance_bearing(incident, pt)
            if d > ceiling:
                continue
            outside.append({**r, "distance_m": round(d), "bearing_deg": round(az)})
        outside.sort(key=lambda r: (r["distance_m"], r.get("name") or ""))
        within = [r for r in outside if r["distance_m"] <= radius]
        if within:
            kept, reach = within, radius
        elif outside:
            kept, reach = outside[:1], float(outside[0]["distance_m"])
        else:
            kept, reach = [], ceiling
        out[cls] = kept
        beyond[cls] = outside[len(kept) :]
        search[cls] = {
            "radius_m": reach,
            "widened": not within,
            "ceiling": not outside,
            "found": len(kept),
        }

    for cls, c in spec["classes"].items():
        if cls == "hospital":
            continue
        rows = []
        for f in stations.get(cls) or []:
            if not f.get("geometry") or f["geometry"].get("type") != "Point":
                continue
            p = {k.lower(): v for k, v in (f.get("properties") or {}).items()}
            xy = f["geometry"]["coordinates"][:2]
            rows.append(
                {
                    "name": p.get("name") or "Unnamed station",
                    "type": c["title"],
                    "address": ", ".join(
                        str(p[k]) for k in ("address", "city", "state") if p.get(k)
                    )
                    or None,
                    "coordinates": [_rnd(xy[0]), _rnd(xy[1])],
                    "source_id": p.get("permanent_identifier"),
                    "as_of": facilities._date(p.get("loaddate")),
                }
            )
        keep(cls, rows)
    if hospitals is not None:
        held = {h["ccn"]: h for h in facilities.cms_file("hospitals")["hospitals"]}
        rows = []
        for h in hospitals:
            if not h.get("coordinates"):
                continue
            rows.append(
                {
                    "name": h.get("name"),
                    "type": h.get("type"),
                    "coordinates": h["coordinates"],
                    "ccn": h.get("ccn"),
                    "beds": h.get("beds"),
                    "emergency_department": spec["hospital_ed"]
                    if h.get("ccn") in held
                    else None,
                    "address": ", ".join(
                        str(held.get(h.get("ccn"), {}).get(k))
                        for k in ("address", "city", "state")
                        if held.get(h.get("ccn"), {}).get(k)
                    )
                    or None,
                }
            )
        keep("hospital", rows)
    shown = max([radius] + [s["radius_m"] for s in search.values() if not s["ceiling"]])
    a = cfg["derive"]["area"]
    mpm = float(a["metres_per_mile"])
    return {
        "classes": out,
        "beyond": beyond,
        "radius_m": radius,
        "area_m": shown,
        "listed_per_class": int(spec["listed_per_class"]),
        "candidates": candidates,
        "inside": inside,
        "search": search,
        "ceiling_m": ceiling,
        "label": spec["label"].format(
            radius=f"{radius / 1000:,.1f} km ({round(radius / mpm, 1):g} mi)",
            area=a["label"].format(miles=round(radius / mpm, 1)),
        ),
    }


async def fetch_stations(incident: Point, box_m: float, cfg: dict):
    """The National Structures Dataset points of each station class in the box of
    `box_m` around the incident (HB-155 ADDENDUM-02 item 4: stage one reads the area
    radius's box and a wider step's for a class with none in it; stage two the next step
    out), read as `facilities_in_footprint` reads them (`facilities.arcgis_features`).
    Returns ({class: features}, urls)."""
    s = facilities.sources()["structures"]
    bbox = _bbox([incident], box_m)
    by_class: dict[str, list[dict]] = {}
    urls: list[str] = []
    for cls, c in cfg["derive"]["nearby"]["classes"].items():
        for layer in c["layers"]:
            feats, u = await facilities.arcgis_features(
                s["api"],
                f"{s['service']}/{layer}",
                bbox,
                s["out_fields"],
                int(s["page_size"]),
            )
            by_class.setdefault(cls, []).extend(feats)
            urls += u
    return by_class, urls


# ── responder travel time (HB-142R ADDENDUM-01 section 3; DN-013) ────────────────────


class _RoadGraph:
    """A road graph on the plane around `c`: nodes are the lines' vertices, merged
    within `tol` metres; each edge is one segment with its free-flow minutes. Built once
    per brief (HB-151: rebuilding it per service made the pair's replay twice as slow);
    a point joins it at the nearest point of the nearest segment (an STRtree query)."""

    def __init__(self, lines: list[tuple[str, dict, Any]], speeds: dict, tol: float, c):
        self.c = c
        self.nodes: list[tuple[float, float]] = []
        index: dict[tuple[int, int], int] = {}
        self.edges: dict[int, list[tuple[int, float]]] = {}
        seg_ij: list[tuple[int, int, float]] = []
        seg_xy: list[tuple[tuple[float, float], tuple[float, float]]] = []

        def node(xy) -> int:
            k = (round(xy[0] / tol), round(xy[1] / tol))
            if k not in index:
                index[k] = len(self.nodes)
                self.nodes.append((xy[0], xy[1]))
            return index[k]

        for _, a, g in lines:
            kmh = float(speeds[a.get("MTFCC")])
            for part in _parts(_plane(g, c)):
                pts = list(part.coords)
                for p, q in zip(pts, pts[1:]):
                    i, j = node(p), node(q)
                    if i == j:
                        continue
                    minutes = math.hypot(q[0] - p[0], q[1] - p[1]) / 1000 / kmh * 60
                    self.edges.setdefault(i, []).append((j, minutes))
                    self.edges.setdefault(j, []).append((i, minutes))
                    seg_ij.append((i, j, minutes))
                    seg_xy.append((p, q))
        self.seg_ij = seg_ij
        self.segs = (
            shapely.linestrings(np.asarray(seg_xy, dtype=float))
            if seg_xy
            else np.empty(0, dtype=object)
        )
        self.tree = shapely.STRtree(self.segs)

    def snap(self, p: Point) -> tuple[int, float] | None:
        """`p` (on the plane) joined at the nearest point of the nearest segment: a new
        node there, with the segment's minutes split at it. Returns (node, connector
        metres). Of equally near segments the first in reading order is taken, as the
        per-service scan before HB-151 took it."""
        if not len(self.segs):
            return None
        near = self.tree.query_nearest(p, all_matches=True)
        k = int(min(near))
        i, j, minutes = self.seg_ij[k]
        seg = self.segs[k]
        d = seg.distance(p)
        s = seg.project(p)
        q = seg.interpolate(s)
        n = len(self.nodes)
        self.nodes.append((q.x, q.y))
        share = s / seg.length if seg.length else 0.0
        for other, w in ((i, minutes * share), (j, minutes * (1 - share))):
            self.edges.setdefault(n, []).append((other, w))
            self.edges.setdefault(other, []).append((n, w))
        return n, d


def travel_times(
    incident: Point,
    stations: list[Point],
    roads: list[tuple[str, dict, Any]],
    footprint: dict,
    spec: dict,
) -> list[dict]:
    """The free-flow minutes between each of `stations` and `incident` over `roads`
    (one Dijkstra from the incident on the vertex graph; the graph is undirected), with
    a straight connector at `connector_kmh` at each end; and whether each route crosses
    the footprint's zones. Pure."""
    import heapq

    c = incident
    g = _RoadGraph(roads, spec["speed_kmh"], float(spec["junction_m"]), c)
    b = g.snap(Point(0.0, 0.0))
    snapped = [g.snap(_plane(s, c)) for s in stations]
    if b is None:
        return [{"minutes": None, "reason": "no held road"} for _ in stations]
    best = {b[0]: 0.0}
    prev: dict[int, int] = {}
    heap = [(0.0, b[0])]
    while heap:
        t, i = heapq.heappop(heap)
        if t > best.get(i, math.inf):
            continue
        for j, w in g.edges.get(i, []):
            if t + w < best.get(j, math.inf):
                best[j] = t + w
                prev[j] = i
                heapq.heappush(heap, (t + w, j))
    conn = float(spec["connector_kmh"])
    zones = [_plane(p, c) for _, p in zone_polygons(footprint)]
    out = []
    for a in snapped:
        if a is None:
            out.append({"minutes": None, "reason": "no held road"})
            continue
        if a[0] not in best:
            # HB-178 (Issue 76400690): the station's nearest held road is not joined
            # to the incident's within the travel classes (Marion Volunteer Fire
            # Department: US 11's two S1200 sections in Greencastle meet only through
            # a 15 m S1400 link, docs/evidence/hb178/marion.md). What is known is
            # said: the straight line and its bearing; no time is estimated.
            st = stations[len(out)]
            m, az = _distance_bearing(incident, st)
            why = spec["no_route"].format(
                classes=", ".join(spec["classes"]),
                km=m / 1000,
                deg=round(az) % 360,
            )
            out.append({"minutes": None, "reason": why, "no_route": True})
            continue
        path = [a[0]]
        while path[-1] != b[0]:
            path.append(prev[path[-1]])
        route = LineString([g.nodes[i] for i in path]) if len(path) > 1 else None
        minutes = best[a[0]] + (a[1] + b[1]) / 1000 / conn * 60
        crosses = bool(
            route is not None
            and any(route.crosses(z) or route.within(z) for z in zones)
        )
        out.append(
            {
                "minutes": round(minutes, 1),
                "road_km": round(route.length / 1000, 2) if route is not None else 0.0,
                "connector_m": round(a[1] + b[1]),
                "crosses_footprint": crosses,
                "reason": None,
            }
        )
    return out


def travel_time(
    incident: Point,
    station: Point,
    roads: list[tuple[str, dict, Any]],
    footprint: dict,
    spec: dict,
) -> dict:
    """`travel_times` for one station. Pure."""
    return travel_times(incident, [station], roads, footprint, spec)[0]


async def fetch_travel_roads(
    incident: Point, radius_m: float, cfg: dict
) -> list[Exchange]:
    """TIGERweb's roads of the travel classes in the radius's box (the roads a
    responder from a station inside the radius drives)."""
    spec = cfg["derive"]["nearby"]["travel"]
    classes = ",".join(f"'{c}'" for c in spec["classes"])
    out = []
    for layer in spec["layers"]:
        ex = await fetch_json(
            cfg["derive"]["roads"]["api"],
            layer,
            {
                "where": f"MTFCC IN ({classes})",
                "outFields": cfg["derive"]["roads"]["fields"],
                "returnGeometry": "true",
                "outSR": "4326",
                "f": "json",
                "geometry": _bbox([incident], radius_m),
                "geometryType": "esriGeometryEnvelope",
                "inSR": "4326",
                "spatialRel": "esriSpatialRelIntersects",
            },
        )
        _refuse_partial(ex, layer)
        out.append(ex)
    return out


def _refuse_partial(ex: Exchange, layer: str) -> None:
    body = ex.body if isinstance(ex.body, dict) else {}
    if ex.status != 200 or "error" in body or "features" not in body:
        raise DeriveError(f"TIGERweb {layer} answered {ex.status}: {body.get('error')}")
    if body.get("exceededTransferLimit"):
        raise DeriveError(f"TIGERweb {layer} returned a partial set")


# ── the downstream path ───────────────────────────────────────────────────────────────


def nearest_flowline(spill, flowlines: list[dict], d_m: float):
    """(feature, metres, point on it nearest the spill) of the 3DHP flowline nearest the
    spill within `d_m`, or None. Ties go to the lower id3dhp, for a stable answer."""
    c = spill.centroid
    best = None
    for f in flowlines:
        if not f.get("geometry"):
            continue
        g = shape(f["geometry"])
        m = _metres(g, spill, c)
        key = (m, (f.get("properties") or {}).get("id3dhp") or "")
        if m <= d_m and (best is None or key < best[0]):
            best = (key, f, g)
    if best is None:
        return None
    (m, _), f, g = best
    # nearest in metres, not in degrees: a degree of longitude is shorter than one of
    # latitude, and on a curving stream the two nearest points differ (HB-58: 182 m on
    # West Branch Marsh Run, 785 m from the I-81 spill)
    return f, m, _unplane(nearest_points(_plane(g, c), _plane(spill, c))[0], c)


def _by_role(exchanges: list[Exchange], cfg: dict) -> tuple:
    spec = cfg["derive"]["downstream"]
    pos = next((e for e in exchanges if spec["position"] in e.url), None)
    nav = next((e for e in exchanges if "/navigation/" in e.url), None)
    return pos, nav


def _chain(start: int, lines: dict[int, LineString], c: Point) -> list[int]:
    """The reaches in downstream order from `start`: each next one begins within a
    metre of where the last one ends."""
    order, seen = [start], {start}
    while True:
        end = Point(lines[order[-1]].coords[-1])
        nxt = sorted(
            k
            for k, g in lines.items()
            if k not in seen and _metres(Point(g.coords[0]), end, c) <= 1.0
        )
        if not nxt:
            return order
        order.append(nxt[0])
        seen.add(nxt[0])


def cut_point(spill, line, step_m: float) -> Point:
    """Where the spill meets `line` (the start flowline, digitized downstream): a
    point's projection onto it; for a shape, the upstream-most projection of the shape
    sampled every `step_m`, since material can enter the water anywhere along the shape
    (orchestrator.yaml `derive.downstream.fallback_label`'s note)."""
    c = spill.centroid
    pl = _plane(_single(line), c)
    if isinstance(spill, Point):
        samples = [_plane(spill, c)]
    else:
        ps = _plane(spill.boundary if spill.geom_type.endswith("Polygon") else spill, c)
        parts = list(getattr(ps, "geoms", [ps]))
        samples = []
        for part in parts:
            n = max(1, math.ceil(part.length / step_m))
            samples += [part.interpolate(i / n, normalized=True) for i in range(n + 1)]
    d = min(pl.project(s) for s in samples)
    return _unplane(pl.interpolate(d), c)


def _single(line) -> LineString:
    """One LineString of a flowline's geometry: its parts joined end to end when they
    join, else their coordinates in order (a flowline is one reach)."""
    if isinstance(line, LineString):
        return line
    merged = linemerge(line)
    if isinstance(merged, LineString):
        return merged
    return LineString([xy for p in line.geoms for xy in p.coords])


def _downstream_of(line, pt: Point) -> LineString:
    """The part of `line` downstream of `pt` (digitized direction is flow direction)."""
    g = _single(line)
    return substring(g, g.project(pt), g.length)


def _3dhp_chain(start: dict, flowlines: list[dict]) -> list[dict]:
    """From `start`, each next flowline is the held one whose hydrosequence is this
    one's dnhydrosequence, until none is held or one repeats."""
    by_seq: dict[float, dict] = {}
    for f in flowlines:
        p = f.get("properties") or {}
        if p.get("hydrosequence") is not None and f.get("geometry"):
            by_seq.setdefault(p["hydrosequence"], f)
    chain, seen, f = [], set(), start
    while f is not None:
        key = (f.get("properties") or {}).get("id3dhp") or id(f)
        if key in seen:
            break
        seen.add(key)
        chain.append(f)
        nxt = (f.get("properties") or {}).get("dnhydrosequence")
        f = by_seq.get(nxt) if nxt else None
    return chain


def _start_feature(out: dict, flowlines: list[dict]) -> dict | None:
    return next(
        (
            f
            for f in flowlines
            if (f.get("properties") or {}).get("id3dhp") == out["start"]["id3dhp"]
        ),
        None,
    )


def _chord_m(pt: Point, ahead: Point, behind: Point, rivers: list) -> float:
    """The width of the river polygon holding `pt`, across the line from `behind` to
    `ahead` (all in metres on one plane): the piece of the perpendicular through `pt`
    inside the polygon that holds it. 0 when no polygon holds it."""
    dx, dy = ahead.x - behind.x, ahead.y - behind.y
    norm = math.hypot(dx, dy)
    if not norm:
        return 0.0
    for poly in rivers:
        if not poly.covers(pt):
            continue
        w, s, e, n = poly.bounds
        reach = math.hypot(e - w, n - s)
        ux, uy = -dy / norm * reach, dx / norm * reach
        across = LineString([(pt.x - ux, pt.y - uy), (pt.x + ux, pt.y + uy)])
        pieces = across.intersection(poly)
        for piece in getattr(pieces, "geoms", [pieces]):
            if piece.distance(pt) < 1e-6 and piece.length:
                return piece.length
    return 0.0


def along_length(
    cut: Point, chain: list[dict], nldi_line, rivers: list[dict], cfg: dict
) -> dict:
    """NLDI's path against 3DHP's own downstream path (`chain`, from the start flowline)
    from `cut`, every `along_step_m` over the first `along_km` (orchestrator.yaml
    `derive.downstream`: Goodchild and Hunter's buffer measure at a share of 1.0). Each
    sample's separation is its distance to `nldi_line`; its tolerance is `nldi_match_m`
    plus half the width of the `width_types` polygon holding it (`_chord_m`). Returns
    {used, compared_m, samples, first_departure, widest: {at_m, separation_m,
    tolerance_m, width_m}, max_separation_m}; `first_departure` is None when every
    separation is within its tolerance."""
    spec = cfg["derive"]["downstream"]
    step, fixed = float(spec["along_step_m"]), float(spec["nldi_match_m"])
    span = float(spec["along_km"]) * 1000
    first = _downstream_of(shape(chain[0]["geometry"]), cut)
    coords = list(first.coords)
    for f in chain[1:]:
        coords += list(_single(shape(f["geometry"])).coords)
    ref = _plane(LineString(coords), cut)
    other = _plane(nldi_line, cut)
    polys = []
    near = ref.buffer(1.0)
    for f in rivers:
        if f.get("geometry"):
            poly = _plane(shape(f["geometry"]), cut)
            if poly.intersects(near):
                polys.append(poly)
    compared = min(span, ref.length)
    rows = []
    for i in range(int(compared // step) + 1):
        at = i * step
        pt = ref.interpolate(at)
        width = _chord_m(
            pt,
            ref.interpolate(min(ref.length, at + step)),
            ref.interpolate(max(0.0, at - step)),
            polys,
        )
        rows.append(
            {
                "at_m": round(at),
                "separation_m": round(pt.distance(other), 1),
                "tolerance_m": round(fixed + width / 2, 1),
                "width_m": round(width),
            }
        )
    departs = [r for r in rows if r["separation_m"] > r["tolerance_m"]]
    return {
        "used": not departs,
        "compared_m": round(compared),
        "samples": len(rows),
        "first_departure": departs[0] if departs else None,
        "widest": max(rows, key=lambda r: (r["separation_m"], -r["at_m"])),
        "max_separation_m": max(r["separation_m"] for r in rows),
        "profile": rows,
    }


def downstream_path(
    spill,
    flowlines: list[dict],
    nldi_exchanges: list[Exchange],
    cfg: dict,
    footprint: dict | None = None,
    rivers: list[dict] | None = None,
    nldi_why: str | None = None,
) -> dict:
    """The downstream path of DN-015 section 3. `spill` is the spill's shape (a point,
    or the derived location's line); `flowlines` the 3DHP flowline features (GeoJSON)
    near the spill, over the footprint and along the path; `nldi_exchanges` NLDI's
    position and navigation answers; `rivers` the 3DHP River polygons the width is
    measured on (`along_length`); `nldi_why` why a live brief holds no NLDI answer
    (`fetch_nldi`). When NLDI's path is not used and the `footprint` is given, the path
    is 3DHP's own connectivity inside it (`_fallback`). Returns {path, reaches, start,
    length_m, label, d_m, l_km, source, reason, match}."""
    out = _nldi_path(spill, flowlines, nldi_exchanges, cfg, rivers or [], nldi_why)
    if out["path"] is None and out["start"] is not None and footprint is not None:
        return _fallback(out, spill, flowlines, footprint, cfg)
    return out


def _fallback(
    out: dict, spill, flowlines: list[dict], footprint: dict, cfg: dict
) -> dict:
    """From the nearest flowline, cut where the spill meets it (`cut_point`), each next
    flowline is the held one whose hydrosequence is this one's dnhydrosequence; the
    chain is cut to the footprint."""
    spec = cfg["derive"]["downstream"]
    polys = [p for _, p in zone_polygons(footprint)]
    if not polys:
        return out
    area = unary_union(polys)
    start = _start_feature(out, flowlines)
    chain, entered = [], False
    for f in _3dhp_chain(start, flowlines) if start is not None else []:
        inside = shape(f["geometry"]).intersects(area)
        if entered and not inside:
            break
        entered = entered or inside
        chain.append(f)
    cut = cut_point(spill, shape(start["geometry"]), float(spec["along_step_m"]))
    why = out["reason"]
    reaches, pieces = [], []
    for i, f in enumerate(chain):
        p = f["properties"]
        g = shape(f["geometry"])
        inside = (_downstream_of(g, cut) if i == 0 else g).intersection(area)
        if inside.is_empty:
            continue
        pieces.append(inside)
        reaches.append(
            {
                "comid": None,
                "name": p.get("gnisidlabel"),
                "id3dhp": p.get("id3dhp"),
                "length_m": round(facilities.geodesic_length_m(inside)),
            }
        )
    if not pieces:
        out["reason"] = (
            f"{why}; and no 3DHP flowline from the start lies in the footprint"
        )
        return out
    path = _merge(pieces)
    out.update(
        path={
            "type": mapping(path)["type"],
            "coordinates": _round_coords(mapping(path)["coordinates"]),
        },
        reaches=reaches,
        length_m=sum(r["length_m"] for r in reaches),
        source="3dhp",
        reason=None,
        label=out["label"] + spec["fallback_label"].format(why=why),
    )
    return out


def _nldi_path(
    spill,
    flowlines: list[dict],
    nldi_exchanges: list[Exchange],
    cfg: dict,
    rivers: list[dict],
    nldi_why: str | None,
) -> dict:
    spec = cfg["derive"]["downstream"]
    d_m, l_km = float(spec["nearest_flowline_m"]), float(spec["length_km"])
    out: dict[str, Any] = {
        "path": None,
        "reaches": [],
        "start": None,
        "length_m": None,
        "d_m": d_m,
        "l_km": l_km,
        "label": spec["label"].format(d_m=d_m, l_km=l_km),
        "source": "nldi",
        "reason": None,
    }
    near = nearest_flowline(spill, flowlines, d_m)
    if near is None:
        out["reason"] = f"no mapped flowline within {d_m:g} m of the spill"
        return out
    f, m, snap = near
    props = f.get("properties") or {}
    out["start"] = {
        "id3dhp": props.get("id3dhp"),
        "name": props.get("gnisidlabel"),
        "distance_m": round(m),
        "point": [_rnd(snap.x), _rnd(snap.y)],
    }
    if nldi_why is not None:
        out["reason"] = nldi_why
        return out
    pos, nav = _by_role(nldi_exchanges, cfg)
    if pos is None or nav is None:
        out["reason"] = "NLDI's answers for this point are not held"
        return out
    feats = (pos.body or {}).get("features") if isinstance(pos.body, dict) else None
    if pos.status != 200 or not feats:
        out["reason"] = f"NLDI answered {pos.status} with no comid for the point"
        return out
    comid = int(feats[0]["properties"]["comid"])
    nfeats = (nav.body or {}).get("features") if isinstance(nav.body, dict) else None
    if nav.status != 200 or not nfeats:
        out["reason"] = f"NLDI's navigation answered {nav.status} with no flowline"
        return out
    lines = {
        int(n["properties"]["nhdplus_comid"]): LineString(n["geometry"]["coordinates"])
        for n in nfeats
        if n.get("geometry", {}).get("type") == "LineString"
    }
    if comid not in lines:
        out["reason"] = f"NLDI's navigation does not start at comid {comid}"
        return out
    order = _chain(comid, lines, snap)
    cut = cut_point(spill, shape(f["geometry"]), float(spec["along_step_m"]))
    first = lines[comid]
    rest = substring(first, first.project(cut), first.length)
    pieces = [(comid, rest)] + [(k, lines[k]) for k in order[1:]]
    match = along_length(
        cut, _3dhp_chain(f, flowlines), _merge([g for _, g in pieces]), rivers, cfg
    )
    del match["profile"]
    out["match"] = match
    if not match["used"]:
        d = match["first_departure"]
        out["reason"] = (
            f"NLDI's comid {comid} runs {d['separation_m']:.0f} m from 3DHP's flowline "
            f"{d['at_m']:,} m downstream of the start, more than the "
            f"{d['tolerance_m']:g} m allowed there"
        )
        return out
    w = match["widest"]
    out["label"] += spec["match_label"].format(
        fixed_m=float(spec["nldi_match_m"]),
        step_m=float(spec["along_step_m"]),
        km=float(spec["along_km"]),
    ) + (
        f" (compared over {match['compared_m']:,} m; largest separation "
        f"{w['separation_m']:g} m, {w['at_m']:,} m downstream, where "
        f"{w['tolerance_m']:g} m is allowed)"
    )
    named = [
        (shape(g["geometry"]), g.get("properties") or {})
        for g in flowlines
        if g.get("geometry")
    ]
    for k, g in pieces:
        mid = g.interpolate(0.5, normalized=True)
        name, fid = None, None
        best = min(named, key=lambda t: _metres(t[0], mid, mid), default=None)
        if best is not None and _metres(best[0], mid, mid) <= float(
            spec["name_match_m"]
        ):
            name, fid = best[1].get("gnisidlabel"), best[1].get("id3dhp")
        out["reaches"].append(
            {
                "comid": k,
                "name": name,
                "id3dhp": fid,
                "length_m": round(facilities.geodesic_length_m(g)),
            }
        )
    path = _merge([g for _, g in pieces])
    out["path"] = {
        "type": mapping(path)["type"],
        "coordinates": _round_coords(mapping(path)["coordinates"]),
    }
    out["length_m"] = sum(r["length_m"] for r in out["reaches"])
    if len(order) < len(lines):
        out["reason_partial"] = (
            f"{len(lines) - len(order)} of NLDI's {len(lines)} reaches do not join the "
            "path from the start and are not drawn"
        )
    return out


def _merge(pieces: list):
    """One line from the pieces: a LineString when they join end to end, else a
    MultiLineString of the runs that do."""
    lines = []
    for g in pieces:
        if isinstance(g, LineString):
            lines.append(g)
        else:
            lines += [p for p in getattr(g, "geoms", []) if isinstance(p, LineString)]
    lines = [g for g in lines if not g.is_empty]
    if len(lines) == 1:
        return lines[0]
    return linemerge(MultiLineString(lines))


def _round_coords(c: Any) -> Any:
    if isinstance(c, (int, float)):
        return _rnd(float(c))
    return [_round_coords(x) for x in c]


# ── workplaces, establishments, terrain (HB-55) ──────────────────────────────────────


def lodes_spec() -> dict:
    """The LODES files population_at_risk reads (population_sources.yaml `lodes`)."""
    from hazbrief.census import sources as population_sources

    return population_sources()["lodes"]


def read_wac(geoids: list[str], columns: list[str], lodes_dir=None) -> dict:
    """{geoid: {column: jobs}} for the blocks, from each state's held WAC file; and the
    files read and the states with no held file."""
    from hazbrief import lodes

    directory = Path(lodes_dir or settings.hazbrief_lodes_dir)
    by_state: dict[str, set[str]] = {}
    for g in geoids:
        by_state.setdefault(g[:2], set()).add(g)
    rows: dict[str, dict[str, float]] = {}
    files, missing = [], []
    for st in sorted(by_state):
        postal = lodes.STATE_POSTAL.get(st)
        path = directory / lodes.file_name(postal) if postal else None
        if path is None or not path.is_file():
            missing.append(postal or st)
            continue
        files.append(path.name)
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            absent = [c for c in columns if c not in (reader.fieldnames or [])]
            if "w_geocode" not in (reader.fieldnames or []) or absent:
                raise DeriveError(f"{path.name} is not a LODES WAC file with {absent}")
            for r in reader:
                if r["w_geocode"] in by_state[st]:
                    rows[r["w_geocode"]] = {c: float(r[c]) for c in columns}
    return {"rows": rows, "files": files, "missing_states": missing}


def workplaces_by_block(blocks: list[str], wac: dict, cfg: dict) -> dict:
    """LODES WAC jobs per block (DN-015 section 4): `blocks` are the GEOIDs the
    population layer draws, `wac` what `read_wac` returned. A block absent from the WAC
    file has no job located in it (LODES lists only blocks with jobs)."""
    spec, lo = cfg["derive"]["workplaces"], lodes_spec()
    cols = list(spec["columns"])
    jobs = {g: wac["rows"].get(g, dict.fromkeys(cols, 0.0)) for g in blocks}
    reason = None
    if not blocks:
        reason = "the population layer draws no block"
    elif wac["missing_states"] and not wac["files"]:
        reason = f"no LODES file held for {', '.join(wac['missing_states'])}"
    return {
        "jobs": jobs,
        "columns": spec["columns"],
        "files": wac["files"],
        "missing_states": wac["missing_states"],
        "label": spec["label"].format(vintage=lo["year"], version=lo["version"]),
        "note": spec["note"],
        "reason": reason,
    }


def county_establishments(cbp_exchanges: list[Exchange], cfg: dict) -> dict:
    """County Business Patterns establishments by two-digit NAICS, one row per county
    and sector, complete (DN-015 section 4: no selection of the sectors that matter)."""
    spec = cfg["derive"]["establishments"]
    rows = []
    for ex in cbp_exchanges:
        body = ex.body
        if ex.status != 200 or not isinstance(body, list) or not body:
            raise DeriveError(f"County Business Patterns answered {ex.status}")
        head = body[0]
        for r in body[1:]:
            d = dict(zip(head, r))
            rows.append(
                {
                    "county": d["state"] + d["county"],
                    "naics": d["NAICS2017"],
                    "sector": d["NAICS2017_LABEL"],
                    "establishments": int(d["ESTAB"]),
                }
            )
    rows.sort(key=lambda r: (r["county"], r["naics"] != "00", r["naics"]))
    return {
        "rows": rows,
        "counties": sorted({r["county"] for r in rows}),
        "label": spec["label"].format(vintage=spec["vintage"]),
        "reason": None if rows else "no county to read",
    }


def terrain_points(footprint: dict, cfg: dict) -> dict:
    """The points the terrain panel reads: the spill point, and points along each zone
    polygon's boundary at HB-49's spacing (`union.spacing_m`), as (lon, lat) rounded to
    the coordinate precision."""
    from hazbrief.brief import union

    spacing = union.spacing_m(footprint, cfg)
    spill = next(
        (
            shape(f["geometry"])
            for f in (footprint.get("footprint") or {}).get("features") or []
            if f["properties"].get("zone") == "spill"
        ),
        None,
    )
    zones: dict[str, list[tuple[float, float]]] = {}
    for zone, poly in zone_polygons(footprint):
        c = poly.centroid
        sx = math.cos(math.radians(c.y)) * facilities._M_PER_DEG
        sy = facilities._M_PER_DEG
        parts = list(poly.geoms) if poly.geom_type == "MultiPolygon" else [poly]
        for part in parts:
            ring = _plane(part.exterior, c)
            n = max(1, math.ceil(ring.length / spacing))
            for i in range(n):
                p = ring.interpolate(ring.length * i / n)
                zones.setdefault(zone, []).append(
                    (_rnd(p.x / sx + c.x), _rnd(p.y / sy + c.y))
                )
    return {
        "spill": (_rnd(spill.x), _rnd(spill.y)) if spill is not None else None,
        "zones": zones,
        "spacing_m": spacing,
    }


def _elevations(ex: Exchange, no_data: float) -> list[tuple[tuple, float | None]]:
    """(point, metres) for each point an elevation answer holds: one for an EPQS
    answer, one per sample for a 3DEP getSamples answer. A point answered with EPQS's
    no-data value, or with a sample value that is not a number (getSamples' "NoData"),
    is None: counted, not guessed."""
    body = ex.body if isinstance(ex.body, dict) else {}
    rows = body["samples"] if isinstance(body.get("samples"), list) else [body]
    out = []
    for row in rows:
        loc = row.get("location") or {}
        key = (_rnd(float(loc.get("x", "nan"))), _rnd(float(loc.get("y", "nan"))))
        try:
            v = float(row.get("value"))
        except (TypeError, ValueError):
            out.append((key, None))
            continue
        out.append((key, None if v == no_data or math.isnan(v) else v))
    return out


def _range(points: list, values: dict) -> dict:
    known = [v for v in (values.get(p) for p in points) if v is not None]
    return {
        "samples": len(points),
        "answered": len(known),
        "min_m": round(min(known), 1) if known else None,
        "max_m": round(max(known), 1) if known else None,
    }


def path_points(path: dict | None) -> list[tuple[float, float]]:
    """The downstream path's vertices, (lon, lat) rounded to the coordinate precision,
    in order and each once."""
    if not path:
        return []
    lines = (
        [path["coordinates"]]
        if path["type"] == "LineString"
        else list(path["coordinates"])
    )
    out, seen = [], set()
    for line in lines:
        for x, y in line:
            p = (_rnd(x), _rnd(y))
            if p not in seen:
                seen.add(p)
                out.append(p)
    return out


def terrain(
    spill_shape,
    footprint: dict,
    elevation_exchanges: list,
    cover: dict | None,
    cfg: dict,
    path: dict | None = None,
    fallback: str | None = None,
) -> dict:
    """Elevation at the spill, each zone boundary's minimum and maximum and the
    downstream path's, in metres with the vertical reference (DN-015 section 5), and the
    land cover `land_cover` read (None when it was not read). `elevation_exchanges` are
    3DEP getSamples answers, or EPQS answers where `fallback` says why getSamples was
    not read. A point with no answer, or answered with no data, is counted, not
    guessed."""
    spec = cfg["derive"]["terrain"]
    pts = terrain_points(footprint, cfg)
    values = {
        k: v
        for e in elevation_exchanges
        for k, v in _elevations(e, float(spec["no_data"]))
    }
    zones = {zone: _range(ps, values) for zone, ps in pts["zones"].items()}
    along = path_points(path)
    spill_v = values.get(pts["spill"]) if pts["spill"] else None
    # HB-155 (DN-023 section 4.1 item 4): the held points with their values, for the
    # siting layer's lower ground; a point with no answer is left out, never guessed
    held = sorted(
        {
            (p[0], p[1], round(values[p], 1))
            for ps in [*pts["zones"].values(), along]
            for p in ps
            if values.get(p) is not None
        }
    )
    return {
        "spill_m": round(spill_v, 1) if spill_v is not None else None,
        "zones": zones,
        "points": [list(t) for t in held],
        "path": _range(along, values) if along else None,
        "elevation_source": "epqs" if fallback else "3dep_getsamples",
        "elevation_fallback": fallback,
        "spacing_m": pts["spacing_m"],
        "vertical_reference": spec["vertical_reference"],
        "cover": cover,
        "label": spec["label"],
        "reason": None if (spill_v is not None or zones) else "no elevation answered",
    }


# ── weather over the response window (DN-016 sections 3 and 4; HB-56) ─────────────────


def _signed_turn(to_deg: float, from_deg: float) -> float:
    """The turn from `from_deg` to `to_deg`, -180 to 180: positive clockwise (the wind
    veers), negative anticlockwise (it backs)."""
    return (to_deg - from_deg + 180.0) % 360.0 - 180.0


def forecast_window(
    gridpoint: Exchange,
    now,
    cfg: dict,
    *,
    start,
    observed: dict | None,
) -> dict:
    """The gridpoint forecast for `weather.window_h` hours after `start` (the as-given
    time), one row an hour from hour 0, read from the layers `weather.layers` names at
    each hour's start (`nws.value_at`); an hour the grid does not cover is a row of
    blanks, never filled. As-of: the grid's `updateTime` (and `generatedAt` when the
    answer carries one). Stale when `now` is at or past the end of the grid's
    `validTimes`. The veer/back flag compares each forecast direction with `observed`
    (the wind the footprint is oriented on) and reports the largest turn when it passes
    `weather.veer_flag_deg`; the footprint is never re-oriented on it."""
    from datetime import timedelta

    from hazbrief import nws

    spec = cfg["weather"]
    body = gridpoint.body if isinstance(gridpoint.body, dict) else {}
    props = body.get("properties")
    if gridpoint.status != 200 or not isinstance(props, dict):
        raise DeriveError(f"NWS gridpoint answered {gridpoint.status}")
    for name, uom in spec["layers"].items():
        got = (props.get(name) or {}).get("uom")
        if got != uom:
            raise DeriveError(f"NWS gridpoint {name} is in {got!r}, not {uom!r}")
    valid_from, valid_to = nws.parse_interval(props["validTimes"])
    rows, uncovered = [], 0
    for h in range(int(spec["window_h"]) + 1):
        t = start + timedelta(hours=h)
        row: dict[str, Any] = {"hour": h, "time": t.isoformat()}
        for name in spec["layers"]:
            try:
                v, _, _ = nws.value_at(props[name], t, name)
            except nws.WindUnavailable:
                v = None
            row[name] = v
        if row["windSpeed"] is None or row["windDirection"] is None:
            uncovered += 1
        rows.append(_round_row(row))
    flag = None
    if observed is not None and observed.get("direction_deg_from") is not None:
        turns = [
            _signed_turn(r["windDirection"], float(observed["direction_deg_from"]))
            for r in rows
            if r["windDirection"] is not None
        ]
        worst = max(turns, key=abs, default=None)
        if worst is not None and abs(worst) > float(spec["veer_flag_deg"]):
            flag = spec["veer_label"].format(
                word="veers" if worst > 0 else "backs", deg=abs(worst)
            )
    updated = props.get("updateTime")
    # The ceiling at hour 0, for the stability class (HB-57): Table 6-6 needs it by day
    # above 5/10 cover and for an overcast. Held only when the grid gives it in metres.
    ceiling_m = None
    layer = props.get("ceilingHeight")
    if isinstance(layer, dict) and layer.get("uom") == "wmoUnit:m":
        try:
            ceiling_m, _, _ = nws.value_at(layer, start, "ceiling height")
        except (nws.WindUnavailable, UpstreamServiceError):
            ceiling_m = None
    # Relative humidity at hour 0 (HB-112 ADDENDUM-02 section 2), for SLAB's RH and the
    # pool's longwave flux; held only in the unit configured, never defaulted.
    rh_spec = spec["relative_humidity"]
    rh_pct = None
    layer = props.get(rh_spec["layer"])
    if isinstance(layer, dict) and layer.get("uom") == rh_spec["uom"]:
        try:
            rh_pct, _, _ = nws.value_at(layer, start, "relative humidity")
        except (nws.WindUnavailable, UpstreamServiceError):
            rh_pct = None
    # The mixing height at hour 0 (HB-129; DN-021 section 3), VSMOKE's input; read as
    # the relative humidity is, held only in the unit configured, never defaulted.
    mh_spec = spec["mixing_height"]
    mixing_m = None
    layer = props.get(mh_spec["layer"])
    if isinstance(layer, dict) and layer.get("uom") == mh_spec["uom"]:
        try:
            mixing_m, _, _ = nws.value_at(layer, start, "mixing height")
        except (nws.WindUnavailable, UpstreamServiceError):
            mixing_m = None
    return {
        "grid": f"{props.get('gridId')}/{props.get('gridX')},{props.get('gridY')}",
        "ceiling_m": ceiling_m,
        "relative_humidity_pct": rh_pct,
        "mixing_height_m": mixing_m,
        "rows": rows,
        "window_h": int(spec["window_h"]),
        "erg_frame_h": float(spec["erg_frame_h"]),
        "uncovered_hours": uncovered,
        "update_time": updated,
        "generated_at": props.get("generatedAt"),
        "valid_from": valid_from.isoformat(),
        "valid_to": valid_to.isoformat(),
        "stale": now >= valid_to,
        "observed": observed,
        "veer_flag_deg": float(spec["veer_flag_deg"]),
        "flag": flag,
        "label": spec["label"].format(
            grid=f"{props.get('gridId')}/{props.get('gridX')},{props.get('gridY')}"
        ),
        "reason": None,
    }


def _round_row(row: dict) -> dict:
    places = {
        "windSpeed": 1,
        "windDirection": 0,
        "temperature": 1,
        "skyCover": 0,
        "probabilityOfPrecipitation": 0,
    }
    return {
        k: (round(v, places[k]) if k in places and v is not None else v)
        for k, v in row.items()
    }


def wms_layer(capabilities: Exchange, layer: str) -> dict:
    """One layer of a nowCOAST WMS 1.3.0 capabilities answer: its time dimension's
    `default` (the newest scan) and every time it lists, and the service's Fees and
    AccessConstraints. A layer the capabilities do not list, or list without a time, is
    refused (HB-56's refusals, shared by radar and satellite since HB-103)."""
    import xml.etree.ElementTree as ET

    if capabilities.status != 200 or not isinstance(capabilities.body, bytes):
        raise DeriveError(f"nowCOAST capabilities answered {capabilities.status}")
    ns = {"w": "http://www.opengis.net/wms"}
    try:
        root = ET.fromstring(capabilities.body)
    except ET.ParseError as exc:
        raise DeriveError(f"nowCOAST capabilities are not XML: {exc}") from None
    for lay in root.iter("{http://www.opengis.net/wms}Layer"):
        if lay.findtext("w:Name", namespaces=ns) != layer:
            continue
        dim = next(
            (d for d in lay.findall("w:Dimension", ns) if d.get("name") == "time"),
            None,
        )
        if dim is None or not dim.get("default"):
            raise DeriveError(f"nowCOAST layer {layer} states no time")
        fees = root.findtext("w:Service/w:Fees", namespaces=ns)
        access = root.findtext("w:Service/w:AccessConstraints", namespaces=ns)
        return {
            "url": capabilities.url.split("?")[0],
            "layer": layer,
            "time": dim.get("default"),
            "times": [t.strip() for t in (dim.text or "").split(",") if t.strip()],
            "terms": f"Fees {fees}; AccessConstraints {access}",
        }
    raise DeriveError(f"nowCOAST capabilities do not list {layer}")


def radar_layer(capabilities: Exchange, cfg: dict) -> dict:
    """The radar layer a live brief draws (DN-016 section 4): the WMS endpoint, the
    configured layer, and its newest scan time, the time dimension's `default` in the
    service's WMS 1.3.0 capabilities (`wms_layer`, which refuses a layer not listed or
    listed without a time)."""
    spec = cfg["weather"]["radar"]
    got = wms_layer(capabilities, spec["layer"])
    return {
        "held": True,
        "url": got["url"],
        "layer": spec["layer"],
        "time": got["time"],
        "times": got["times"],
        "opacity": float(spec["opacity"]),
        "terms": got["terms"],
        "label": spec["label"].format(layer=spec["layer"], time=got["time"]),
        "reason": None,
    }


def satellite_layer(capabilities: Exchange, cfg: dict, period: str) -> dict:
    """The satellite layer a live brief draws (HB-103 Part A): the band
    `weather.satellite.bands` names for `period`, the footprint's own day or night (the
    visible band by day, the longwave infrared band by night), with its newest scan and
    the service's terms, by `wms_layer`'s refusals. A period with no band is refused."""
    spec = cfg["weather"]["satellite"]
    band = spec["bands"].get(period)
    if band is None:
        raise DeriveError(f"no satellite band is configured for the period {period!r}")
    got = wms_layer(capabilities, band["layer"])
    return {
        "held": True,
        "url": got["url"],
        "layer": band["layer"],
        "band": band["name"],
        "period": period,
        "time": got["time"],
        "times": got["times"],
        "opacity": float(spec["opacity"]),
        "terms": got["terms"],
        "label": spec["label"].format(
            band=band["name"], layer=band["layer"], time=got["time"], period=period
        ),
        "reason": None,
    }


# ── the wind field over the footprint (HB-103 Part B) ─────────────────────────────────


def _cell_axes(cell: Exchange) -> tuple[Point, np.ndarray, np.ndarray]:
    """The centre of a gridpoint answer's cell and its one-cell steps in +x and +y, as
    (lon, lat) vectors, from the answer's own `geometry` polygon: of the two edges at
    its first corner, the one with the larger eastward share is the x step, the other
    the y step, each signed so x runs east and y north (the NDFD grid's axes)."""
    geom = (cell.body or {}).get("geometry") if isinstance(cell.body, dict) else None
    if not geom or geom.get("type") != "Polygon":
        raise DeriveError("the NWS gridpoint answer carries no cell polygon")
    ring = np.asarray(geom["coordinates"][0][:4], dtype=float)
    if len(ring) != 4:
        raise DeriveError("the NWS gridpoint cell is not four-cornered")
    c = shape(geom).centroid
    k = math.cos(math.radians(c.y))
    a, b = ring[1] - ring[0], ring[3] - ring[0]
    x, y = (a, b) if abs(a[0] * k) > abs(b[0] * k) else (b, a)
    if x[0] < 0:
        x = -x
    if y[1] < 0:
        y = -y
    return c, x, y


def footprint_bounds(fp: dict) -> tuple[float, float, float, float] | None:
    """(west, south, east, north) of the footprint's zone polygons, else of its spill
    point; None for a footprint with neither."""
    feats = (fp.get("footprint") or {}).get("features") or []
    geoms = [
        shape(f["geometry"])
        for f in feats
        if f["geometry"]["type"] in ("Polygon", "MultiPolygon")
    ] or [shape(f["geometry"]) for f in feats if f["properties"].get("zone") == "spill"]
    if not geoms:
        return None
    return unary_union(geoms).bounds


def wind_field_offsets(
    spill_cell: Exchange, bounds: tuple[float, float, float, float], cfg: dict
) -> list[tuple[int, int]]:
    """The (dx, dy) offsets from the spill's gridpoint whose cells cover `bounds`, the
    footprint's box, widened by `weather.wind_field.margin_cells` cells on every side:
    each offset's cell, predicted from the spill cell's own polygon (`_cell_axes`),
    intersects that box. The spill's own cell (0, 0) is always first. A box that would
    need an offset past `max_offset` is refused."""
    from shapely.geometry import Polygon, box

    spec = cfg["weather"]["wind_field"]
    c0, vx, vy = _cell_axes(spill_cell)
    m = int(spec["margin_cells"])
    step_lon = max(abs(vx[0]), abs(vy[0]))
    step_lat = max(abs(vx[1]), abs(vy[1]))
    w, s, e, n = bounds
    target = box(w - m * step_lon, s - m * step_lat, e + m * step_lon, n + m * step_lat)
    cap = int(spec["max_offset"])
    got: list[tuple[int, int]] = []
    for dy in range(-cap, cap + 1):
        for dx in range(-cap, cap + 1):
            ctr = np.array([c0.x, c0.y]) + dx * vx + dy * vy
            cell = Polygon(
                [
                    ctr + sx * vx / 2 + sy * vy / 2
                    for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))
                ]
            )
            if cell.intersects(target):
                if abs(dx) == cap or abs(dy) == cap:
                    raise DeriveError(
                        f"the footprint's box needs cells past {cap} from the spill's"
                    )
                got.append((dx, dy))
    got.sort(key=lambda o: (o != (0, 0), o[1], o[0]))
    return got


def wind_field(
    cells: list[Exchange], spill_cell: Exchange, start, cfg: dict, missing=()
) -> dict:
    """One arrow per NWS gridpoint cell (HB-103 step 3): for each answer in `cells`, its
    wind direction and speed at each forecast hour's start (`nws.value_at`, as the
    window reads the spill's cell), hours 0 to `weather.window_h` after `start`. An hour
    a cell's grid does not cover is counted per hour and read at the grid's nearest
    covered hour, its row carrying that hour as a third value (HB-114 step 1); it is
    never filled from another cell. Each cell carries its grid, centre and as-of
    (`updateTime`). `missing` are the offsets whose answer the brief does not hold, or
    whose grid ends before them, with why."""
    from datetime import timedelta

    from hazbrief import nws

    spec = cfg["weather"]
    units = spec["layers"]
    hours = [start + timedelta(hours=h) for h in range(int(spec["window_h"]) + 1)]
    out_cells, uncovered = [], [0] * len(hours)
    for ex in cells:
        props = (ex.body or {}).get("properties") if isinstance(ex.body, dict) else None
        if ex.status != 200 or not isinstance(props, dict):
            raise DeriveError(f"NWS gridpoint {ex.url} answered {ex.status}")
        for name in ("windSpeed", "windDirection"):
            got = (props.get(name) or {}).get("uom")
            if got != units[name]:
                raise DeriveError(
                    f"NWS gridpoint {name} is in {got!r}, not {units[name]!r}"
                )
        c, _, _ = _cell_axes(ex)
        valid_from, valid_to = nws.parse_interval(props["validTimes"])

        def read(t):
            vals = []
            for name in ("windDirection", "windSpeed"):
                try:
                    v, _, _ = nws.value_at(props[name], t, name)
                except nws.WindUnavailable:
                    v = None
                vals.append(v)
            return None if None in vals else [round(vals[0]), round(vals[1], 1)]

        rows = []
        for i, t in enumerate(hours):
            row = read(t)
            if row is None:
                # HB-114 step 1: an hour the cell's grid does not cover is read at the
                # grid's nearest covered hour, and the row carries the hour read, so
                # the page labels the mismatch (as the window labels its uncovered
                # hours); a grid that holds no value there either stays blank
                uncovered[i] += 1
                near = min(max(t, valid_from), valid_to - timedelta(hours=1))
                row = read(near)
                if row is not None:
                    row.append(near.isoformat())
            rows.append(row)
        out_cells.append(
            {
                "grid": (
                    f"{props.get('gridId')}/{props.get('gridX')},{props.get('gridY')}"
                ),
                "lat": round(c.y, 5),
                "lon": round(c.x, 5),
                "update_time": props.get("updateTime"),
                "valid_from": valid_from.isoformat(),
                "valid_to": valid_to.isoformat(),
                "rows": rows,
                "spill": ex.url == spill_cell.url,
            }
        )
    return {
        "cells": out_cells,
        "hours": [t.isoformat() for t in hours],
        "uncovered": uncovered,
        "missing": [list(m) for m in missing],
        "label": spec["wind_field"]["label"],
        "reason": None,
    }


async def fetch_wind_cells(
    spill_cell: Exchange, offsets: list[tuple[int, int]], cfg: dict
) -> tuple[list[Exchange], list[tuple[int, int, str]]]:
    """Each offset's `/gridpoints/{wfo}/{x},{y}` answer through the one client, the
    spill's own cell (offset 0, 0) being the answer already read. An answer the brief
    does not hold, or a service error, is a missing cell with why, not a failure of the
    field. NWS's 404 "Gridpoint Does Not Exist" (problem type InvalidGridpoint) is read
    as an answer, recorded and replayed (`answers`, HB-119's route): the office's grid
    ends before that cell, and the cell is missing with `off_grid_line` (HB-114 step 1;
    Issue 33223d90). Any other 404 is still a failure."""
    from hazbrief import nws

    props = spill_cell.body["properties"]
    wfo, x0, y0 = props["gridId"], int(props["gridX"]), int(props["gridY"])
    got, missing = [], []
    for dx, dy in offsets:
        if (dx, dy) == (0, 0):
            got.append(spill_cell)
            continue
        x, y = x0 + dx, y0 + dy
        try:
            ex = await fetch_json(
                nws.API,
                f"gridpoints/{wfo}/{x},{y}",
                headers={"Accept": nws.ACCEPT},
                answers=(404,),
            )
        except UpstreamServiceError as exc:
            missing.append((dx, dy, _why(exc)))
            continue
        if ex.status == 404:
            body = ex.body if isinstance(ex.body, dict) else {}
            if not str(body.get("type", "")).endswith("/InvalidGridpoint"):
                missing.append((dx, dy, f"NWS answered {wfo}/{x},{y} with 404"))
                continue
            spec = cfg["weather"]["wind_field"]
            missing.append(
                (dx, dy, spec["off_grid_line"].format(wfo=wfo, title=body.get("title")))
            )
            continue
        got.append(ex)
    return got, missing


# ── the snapshot: one radar and one satellite image, stored (HB-103 Part C) ──────────

#: the sphere Web Mercator (EPSG:3857) is defined on, metres (EPSG Guidance Note 7-2,
#: 1.3.3.2), as `render._lat_lon` inverts it
_MERCATOR_R = 6378137.0


def mercator(lon: float, lat: float) -> tuple[float, float]:
    """Longitude and latitude to EPSG:3857 metres."""
    x = _MERCATOR_R * math.radians(lon)
    y = _MERCATOR_R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
    return x, y


def snapshot_request(bounds: tuple[float, float, float, float], cfg: dict) -> dict:
    """The GetMap frame of the map's extent `bounds` (west, south, east, north): its
    EPSG:3857 box, to the metre outward, and its pixel size, the longer side
    `weather.snapshot.max_px` and the other in proportion."""
    spec = cfg["weather"]["snapshot"]
    w, s, e, n = bounds
    x0, y0 = mercator(w, s)
    x1, y1 = mercator(e, n)
    x0, y0, x1, y1 = math.floor(x0), math.floor(y0), math.ceil(x1), math.ceil(y1)
    big = int(spec["max_px"])
    dx, dy = x1 - x0, y1 - y0
    width, height = (
        (big, max(1, round(big * dy / dx)))
        if dx >= dy
        else (max(1, round(big * dx / dy)), big)
    )
    return {"bbox": f"{x0},{y0},{x1},{y1}", "width": width, "height": height}


def snapshot_time(times: list[str], when) -> str | None:
    """The newest scan the capabilities list at or before `when`; None when `when` is
    before every scan they list (a scenario whose time has passed)."""
    from hazbrief.evidence import store as S

    held = [t for t in times if S.parse_time(t) <= when]
    return max(held, key=S.parse_time) if held else None


def _getmap_params(layer: str, time: str, req: dict, fmt: str) -> dict:
    return {
        "service": "WMS",
        "version": "1.3.0",
        "request": "GetMap",
        "layers": layer,
        "styles": "",
        "crs": "EPSG:3857",
        "bbox": req["bbox"],
        "width": str(req["width"]),
        "height": str(req["height"]),
        "format": fmt,
        "transparent": "true",
        "time": time,
    }


async def fetch_snapshot(spec: dict, layer: str, time: str, req: dict, fmt: str):
    """One GetMap image through the one client (`fetch_bytes`, PNG only)."""
    from hazbrief.utils import fetch_bytes

    return await fetch_bytes(
        spec["api"], spec["path"], _getmap_params(layer, time, req, fmt), accept=(fmt,)
    )


def store_snapshot(
    store: Path,
    ex: Exchange,
    *,
    service: str,
    layer: str,
    time: str,
    req: dict,
    cfg: dict,
) -> tuple[str, dict]:
    """Write one fetched snapshot to the evidence store (DN-009 C2): the image as an
    entity under its sha256, and a record naming its request url, the service's time
    value and when it was fetched. The source row is the catalog's for the url."""
    from hazbrief import __version__
    from hazbrief.evidence import catalog
    from hazbrief.evidence import store as S

    if ex.status != 200 or not isinstance(ex.body, bytes):
        raise DeriveError(f"nowCOAST GetMap answered {ex.status}")
    row = catalog.row_for_exchange(ex.api, ex.url)
    return S.write_record(
        store,
        ex.body,
        activity={
            "type": "upstream_exchange",
            "name": cfg["weather"]["snapshot"]["activity"],
            "params": {
                "service": service,
                "layer": layer,
                "time": time,
                "url": ex.url,
                **req,
            },
            "startedAtTime": ex.recorded_at,
            "endedAtTime": ex.recorded_at,
            "http_mode": "live",
        },
        server={
            "name": "hazbrief-mcp",
            "version": __version__,
            "tool_surface_sha256": None,
        },
        source=[{"id": row["id"], "endpoint": ex.url}],
        provenance_class=row["provenance_class"],
        as_of=time,
        as_of_basis="the service's WMS time value",
        horizon_s=row["horizon_s"],
        horizon_source=row["id"],
        media_type=ex.content_type or cfg["weather"]["snapshot"]["format"],
    )


def snapshot_records(stores: list[Path], cfg: dict) -> list[tuple[Path, dict]]:
    """Every stored snapshot record in the brief's stores, with its store (one pass
    over each store, read once per brief)."""
    from hazbrief.evidence import store as S

    name = cfg["weather"]["snapshot"]["activity"]
    return [
        (Path(st), r)
        for st in stores
        if Path(st).is_dir()
        for r in S.all_records(Path(st))
        if r["activity"]["name"] == name
    ]


def find_snapshot(
    records: list[tuple[Path, dict]], *, service: str, layer: str, req: dict
) -> tuple[Path, dict] | None:
    """The newest of `records` (`snapshot_records`) of `service`'s `layer` over this
    frame (`req`), with the store it is in; None when there is none."""
    hits = [
        (r["activity"]["endedAtTime"], r["activity"]["id"], st, r)
        for st, r in records
        if (p := r["activity"]["params"]).get("service") == service
        and p.get("layer") == layer
        and all(p.get(k) == v for k, v in req.items())
    ]
    if not hits:
        return None
    _, _, st, rec = max(hits, key=lambda h: (h[0], h[1]))
    return st, rec


def snapshot_entry(store: Path, rec: dict, service_title: str, cfg: dict) -> dict:
    """A stored snapshot as the page draws and cites it: the image's sha256, its scan
    time, when it was fetched, its request url and its frame."""
    from hazbrief.evidence import labels as L

    p = rec["activity"]["params"]
    sha = rec["entity"]["sha256"]
    n = L.config()["hash_prefix_chars"]
    return {
        "held": True,
        "store": str(store),
        "sha": sha,
        "media_type": rec["entity"]["media_type"],
        "layer": p["layer"],
        "time": p["time"],
        "fetched": rec["activity"]["endedAtTime"],
        "url": p["url"],
        "bbox": p["bbox"],
        "record": rec,
        "label": cfg["weather"]["snapshot"]["label"].format(
            service=service_title,
            layer=p["layer"],
            time=p["time"],
            fetched=rec["activity"]["endedAtTime"],
            sha=sha[:n],
        ),
        "reason": None,
    }


def brief_wind(brief, fp: dict | None) -> dict | None:
    """The wind a consumer reads (HB-133): the brief's one record, in the footprint's
    `wind` shape, once `assemble` has resolved it; else the footprint's own wind (a
    brief built by a test harness)."""
    from hazbrief.brief import wind_record

    if getattr(brief, "wind_resolved", False):
        return wind_record.as_footprint_wind(brief.wind_record)
    return (fp or {}).get("wind")


def forecast_point(spill) -> tuple[float, float] | None:
    """(lat, lon) the forecast is read at: the spill point; the middle of a spill line
    (a milepost range, an address range's segment); else a point inside the shape (an
    intersection's accuracy disc), shapely's `representative_point`."""
    if spill is None:
        return None
    if isinstance(spill, Point):
        p = spill
    elif isinstance(spill, LineString):
        p = spill.interpolate(0.5, normalized=True)
    else:
        p = spill.representative_point()
    return p.y, p.x


async def fetch_forecast(lat: float, lon: float) -> tuple[Exchange, Exchange]:
    """NWS `points` at the spill, then the `gridpoints` url it names: the two requests
    `nws.wind_at` makes, so a point whose wind was read from the grid replays the same
    recordings."""
    from hazbrief import nws
    from hazbrief.utils import relative_to_origin

    headers = {"Accept": nws.ACCEPT}
    points = await fetch_json(
        nws.API,
        f"points/{nws.coordinate(lat)},{nws.coordinate(lon)}",
        headers=headers,
    )
    props = (points.body or {}).get("properties") if points.status == 200 else None
    url = (props or {}).get("forecastGridData")
    if not isinstance(url, str):
        raise DeriveError("NWS points names no forecast grid")
    grid = await fetch_json(nws.API, relative_to_origin(nws.API, url), headers=headers)
    return points, grid


async def fetch_radar(cfg: dict) -> Exchange:
    """nowCOAST's WMS 1.3.0 capabilities for the radar service (XML: `fetch_bytes`)."""
    return await fetch_capabilities(cfg["weather"]["radar"])


async def fetch_satellite(cfg: dict) -> Exchange:
    """nowCOAST's WMS 1.3.0 capabilities for the satellite service (HB-103)."""
    return await fetch_capabilities(cfg["weather"]["satellite"])


async def fetch_capabilities(spec: dict) -> Exchange:
    """A nowCOAST service's WMS 1.3.0 GetCapabilities (`spec`: its `api` and `path`)."""
    from hazbrief.utils import fetch_bytes

    return await fetch_bytes(
        spec["api"],
        spec["path"],
        {"service": "WMS", "version": "1.3.0", "request": "GetCapabilities"},
        accept=("text/xml", "application/xml", "application/vnd.ogc.wms_xml"),
    )


async def _hb56(
    c, fp: dict, spill, cfg: dict, *, replay: bool
) -> tuple[dict, Exchange | None]:
    """The forecast over the window and the radar layer for one brief (HB-56), and the
    spill cell's gridpoint answer (None when it was not read) for the wind field."""
    from hazbrief.evidence import store as S

    out: dict[str, Any] = {}
    grid = None
    point = forecast_point(spill)
    try:
        if point is None:
            raise DeriveError("the brief holds no spill point")
        # HB-133: the forecast the brief's wind record was read from, not a second
        # read of it; the strip's first cell and the veer flag read the record
        held = getattr(c.brief, "wind_held", None)
        if held is not None:
            points, grid = held.points, held.grid
        else:
            points, grid = await fetch_forecast(*point)
        out["forecast"] = forecast_window(
            grid,
            c.brief.now,
            cfg,
            start=S.parse_time(c.brief.as_given) if c.brief.as_given else c.brief.now,
            observed=brief_wind(c.brief, fp),
        )
        out["forecast"]["sources"] = _sources([points, grid])
    except (DeriveError, UpstreamServiceError) as exc:
        out["forecast"] = {"rows": [], "reason": _why(exc), "sources": []}
    spec = cfg["weather"]["radar"]
    if replay:
        out["radar"] = {"held": False, "reason": spec["not_held"], "sources": []}
    else:
        try:
            cap = await fetch_radar(cfg)
            out["radar"] = radar_layer(cap, cfg)
            out["radar"]["sources"] = _sources([cap])
        except (DeriveError, UpstreamServiceError) as exc:
            out["radar"] = {"held": False, "reason": _why(exc), "sources": []}
    return out, grid


async def _hb103(
    c, fp: dict, grid: Exchange | None, out: dict, cfg: dict, *, replay: bool
) -> dict:
    """The satellite layer, the wind field and the two snapshots for one brief
    (HB-103). A replayed brief holds no live satellite (as it holds no live radar) and
    reads its snapshots from its stores; a live brief takes them and stores them in the
    run's own store."""
    from hazbrief.brief import layers
    from hazbrief.evidence import store as S

    wx = cfg["weather"]
    got: dict[str, Any] = {}
    start = S.parse_time(c.brief.as_given) if c.brief.as_given else c.brief.now
    period = (fp.get("day_night") or {}).get("period")

    # the satellite layer (Part A)
    sat_spec = wx["satellite"]
    if replay:
        got["satellite"] = {
            "held": False,
            "reason": sat_spec["not_held"],
            "sources": [],
        }
    else:
        try:
            cap = await fetch_satellite(cfg)
            got["satellite"] = satellite_layer(cap, cfg, period)
            got["satellite"]["sources"] = _sources([cap])
        except (DeriveError, UpstreamServiceError) as exc:
            got["satellite"] = {"held": False, "reason": _why(exc), "sources": []}

    # the wind field (Part B)
    try:
        if grid is None:
            raise DeriveError(out["forecast"].get("reason") or "no spill gridpoint")
        bounds = footprint_bounds(fp)
        if bounds is None:
            raise DeriveError("the footprint has no shape")
        offsets = wind_field_offsets(grid, bounds, cfg)
        cells, missing = await fetch_wind_cells(grid, offsets, cfg)
        got["wind_field"] = wind_field(cells, grid, start, cfg, missing)
        got["wind_field"]["sources"] = _sources(cells)
        got["wind_field"]["footprint"] = fp.get("wind")
        spill_pt = next(
            (
                shape(f["geometry"]).representative_point()
                for f in (fp.get("footprint") or {}).get("features") or []
                if f["properties"].get("zone") == "spill"
            ),
            None,
        )
        got["wind_field"]["spill"] = (
            [round(spill_pt.y, 6), round(spill_pt.x, 6)] if spill_pt else None
        )
    except (DeriveError, UpstreamServiceError) as exc:
        got["wind_field"] = {"cells": [], "reason": _why(exc), "sources": []}

    # the snapshots (Part C): the map's extent as the page first shows it, widened by
    # the clip margin, so the image covers the first view
    box = layers._Ctx(c.brief, cfg).clip_box()
    req = snapshot_request(box.bounds, cfg) if box is not None else None
    services = {
        "radar": (wx["radar"], out.get("radar") or {}, wx["radar"]["layer"]),
        "satellite": (
            sat_spec,
            got["satellite"],
            (sat_spec["bands"].get(period) or {}).get("layer"),
        ),
    }
    held = snapshot_records(c.brief.stores, cfg) if req is not None else []
    got["snapshots"] = {}
    for name, (spec, live, layer) in services.items():
        got["snapshots"][name] = await _snapshot(
            c, name, spec, live, layer, req, held, start, cfg, replay=replay
        )
    return got


async def _snapshot(
    c,
    name: str,
    spec: dict,
    live: dict,
    layer,
    req,
    held,
    when,
    cfg: dict,
    *,
    replay: bool,
) -> dict:
    """One service's snapshot: the stored one when the brief's stores hold it; else, in
    a live brief, the newest scan at or before `when`, fetched and stored in the run's
    own store; else why there is none."""
    from hazbrief.config import settings
    from hazbrief.evidence import labels as L

    snap = cfg["weather"]["snapshot"]
    title = {"radar": "Radar", "satellite": "Satellite"}[name]
    whenl = L.when(when.isoformat(), c.brief.time_zone)
    none = {"held": False, "reason": snap["none_recorded"].format(when=whenl)}
    if req is None or layer is None:
        return {**none, "reason": "no snapshot: the brief has no map extent or band"}
    found = find_snapshot(held, service=name, layer=layer, req=req)
    if found is not None:
        return snapshot_entry(*found, title, cfg)
    if replay or settings.hazbrief_http_mode != "live" or not live.get("held"):
        return none
    t = snapshot_time(live.get("times") or [], when)
    if t is None:
        first = min(live.get("times") or [live["time"]])
        return {
            "held": False,
            "reason": snap["too_old"].format(when=whenl, layer=layer, first=first),
        }
    try:
        ex = await fetch_snapshot(spec, layer, t, req, snap["format"])
        store = c.brief.stores[0]
        _, rec = store_snapshot(
            store, ex, service=name, layer=layer, time=t, req=req, cfg=cfg
        )
    except (DeriveError, UpstreamServiceError) as exc:
        return {"held": False, "reason": f"snapshot not taken: {_why(exc)}"}
    return snapshot_entry(store, rec, title, cfg)


# ── the nearest station's observation (DN-016 sections 2 and 3; HB-60) ───────────────


def nearest_station(stations: Exchange, lat: float, lon: float) -> tuple[dict, float]:
    """The station of an NWS `stations` answer nearest (lat, lon), geodesic, and its
    distance in metres; ties go to the lower station id. The answer's own order is by
    distance from the gridpoint, not from the spill."""
    feats = (
        (stations.body or {}).get("features")
        if isinstance(stations.body, dict)
        else None
    )
    if stations.status != 200 or not feats:
        raise DeriveError(f"NWS stations answered {stations.status} with no station")
    best = None
    for f in feats:
        x, y = f["geometry"]["coordinates"][:2]
        m, _ = facilities.inverse(lat, lon, y, x)
        key = (m, f["properties"]["stationIdentifier"])
        if best is None or key < best[0]:
            best = (key, f)
    return best[1], best[0][0]


def _quantity(q: dict | None, unit: str) -> float | None:
    """An NWS quantity's value in `unit` (wmoUnit codes the observations use)."""
    if not q or q.get("value") is None:
        return None
    code = q.get("unitCode", "")
    v = float(q["value"])
    if code == unit:
        return v
    if code == "wmoUnit:km_h-1" and unit == "wmoUnit:m_s-1":
        return v / 3.6
    raise DeriveError(f"an NWS quantity in {code}, not {unit}")


def station_observation(
    stations: Exchange, obs: Exchange, lat: float, lon: float, when, cfg: dict
) -> dict:
    """The nearest station's latest observation (DN-016; HB-60): wind, temperature,
    cloud layers and the ceiling (FMH-1 9.4.5: the lowest layer aloft reported broken
    or overcast, or the vertical visibility into an obscured sky), with the station,
    its distance from the spill and its elevation. `usable` is DN-010's stale rule
    against the time the brief is computed for (`when`, the as-given time): observed
    no later than it and within the source's horizon before it."""
    from hazbrief.evidence import catalog
    from hazbrief.evidence import store as S

    spec = cfg["weather"]["observation"]
    station, metres = nearest_station(stations, lat, lon)
    sp = station["properties"]
    body = obs.body if isinstance(obs.body, dict) else {}
    p = body.get("properties") or {}
    if obs.status != 200 or not p.get("timestamp"):
        raise DeriveError(f"NWS observation answered {obs.status} with no timestamp")
    layers = [
        {
            "amount": layer.get("amount"),
            "base_m": _quantity(layer.get("base"), "wmoUnit:m"),
        }
        for layer in p.get("cloudLayers") or []
    ]
    ceiling = [
        layer["base_m"]
        for layer in layers
        if layer["amount"] in spec["ceiling_amounts"] and layer["base_m"] is not None
    ]
    observed = S.parse_time(p["timestamp"])
    horizon = int(catalog.row(spec["catalog_row"])["horizon_s"])
    age = (when - observed).total_seconds()
    usable = 0 <= age <= horizon
    if usable:
        why = None
    elif age < 0:
        why = f"observed {_span(-age)} after the as-given time"
    else:
        why = (
            f"observed {_span(age)} before the as-given time, past its "
            f"{_span(horizon)} horizon"
        )
    return {
        "station": sp["stationIdentifier"],
        "name": sp.get("name"),
        "distance_km": round(metres / 1000, 1),
        "station_elevation_m": _quantity(sp.get("elevation"), "wmoUnit:m"),
        "observed_at": observed.isoformat(),
        "usable": usable,
        "stale_reason": why,
        "wind_from_deg": _quantity(p.get("windDirection"), "wmoUnit:degree_(angle)"),
        "wind_ms": _quantity(p.get("windSpeed"), "wmoUnit:m_s-1"),
        "wind_height": spec["wind_height_label"],
        "temperature_c": _quantity(p.get("temperature"), "wmoUnit:degC"),
        # SLAB's RH where the temperature row is this observation's (HB-112)
        "relative_humidity_pct": _quantity(
            p.get("relativeHumidity"), cfg["weather"]["relative_humidity"]["uom"]
        ),
        "cloud_layers": layers,
        "ceiling_ft": round(min(ceiling) / 0.3048) if ceiling else None,
        "ceiling_note": None if ceiling else spec["no_ceiling"],
        "label": spec["label"],
        "reason": None,
    }


def _span(seconds: float) -> str:
    """A duration as the label prints it: minutes under two hours, else hours under
    two days, else days."""
    if seconds < 7200:
        return f"{seconds / 60:.0f} min"
    if seconds < 172800:
        return f"{seconds / 3600:.1f} h"
    return f"{seconds / 86400:.1f} days"


async def fetch_observation(lat: float, lon: float) -> list[Exchange]:
    """NWS `points` at the spill (the request `fetch_forecast` makes, served from its
    file in replay and recording), the station list it names, and the nearest station's
    latest observation."""
    from hazbrief import nws
    from hazbrief.utils import relative_to_origin

    headers = {"Accept": nws.ACCEPT}
    points = await fetch_json(
        nws.API,
        f"points/{nws.coordinate(lat)},{nws.coordinate(lon)}",
        headers=headers,
    )
    props = (points.body or {}).get("properties") if points.status == 200 else None
    url = (props or {}).get("observationStations")
    if not isinstance(url, str):
        raise DeriveError("NWS points names no observation stations")
    stations = await fetch_json(
        nws.API, relative_to_origin(nws.API, url), headers=headers
    )
    station, _ = nearest_station(stations, lat, lon)
    sid = station["properties"]["stationIdentifier"]
    obs = await fetch_json(
        nws.API, f"stations/{sid}/observations/latest", headers=headers
    )
    return [points, stations, obs]


async def _hb60(c, spill, cfg: dict) -> dict:
    """The nearest station's observation for one brief (HB-60)."""
    from hazbrief.evidence import store as S

    point = forecast_point(spill)
    when = S.parse_time(c.brief.as_given) if c.brief.as_given else c.brief.now
    try:
        if point is None:
            raise DeriveError("the brief holds no spill point")
        exs = await fetch_observation(*point)
        out = station_observation(exs[1], exs[2], point[0], point[1], when, cfg)
        out["sources"] = _sources(exs)
    except (DeriveError, UpstreamServiceError) as exc:
        out = {"station": None, "usable": False, "reason": _why(exc), "sources": []}
    return out


# ── the Pasquill-Gifford stability class (DN-016 section 2; HB-57) ────────────────────

#: metres per second in one knot (the international knot, 1852 m per hour)
_MS_PER_KNOT = 1852 / 3600


def turner_period(when, sunrise, sunset, margin_h: float) -> str:
    """ "day" or "night" by Table 6-6 item 2 of EPA-454/R-99-005: night runs "from one
    hour before sunset to one hour after sunrise". `sunrise` and `sunset` bracket a
    day (the ones `incident.day_or_night` gives for a daytime instant)."""
    from datetime import timedelta

    m = timedelta(hours=margin_h)
    return "day" if sunrise + m <= when < sunset - m else "night"


def stability_class(obs: dict, solar: dict, cfg: dict) -> dict:
    """The Pasquill-Gifford class A to F by Turner's key as EPA states it (DN-016
    ADDENDUM-00 section 4): the net radiation index from the period, the solar
    altitude's insolation class, the sky cover and, where the rule needs it, the
    ceiling (Table 6-6); then the class by the wind's whole knots (Table 6-4). A missing
    input gives "not determined" naming it; nothing is defaulted. Printed with every
    input; nothing reads the class (DN-001 invariant 1)."""
    spec = cfg["weather"]["stability"]
    inputs = [
        {
            "name": "wind speed",
            "value": obs.get("wind_ms"),
            "unit": f"m/s, {spec['wind_height']}",
            "source": obs.get("wind_source"),
            "as_of": obs.get("wind_as_of"),
        },
        {
            "name": "sky cover",
            "value": obs.get("sky_cover_pct"),
            "unit": "%",
            "source": obs.get("sky_source"),
            "as_of": obs.get("sky_as_of"),
        },
        {
            "name": "solar altitude",
            "value": solar.get("elevation_deg"),
            "unit": f"degrees ({solar.get('period')})",
            "source": solar.get("source"),
            "as_of": solar.get("when"),
        },
    ]
    out = {
        "class": None,
        "number": None,
        "net_radiation_index": None,
        "insolation_class": None,
        "wind_knots": None,
        "period": solar.get("period"),
        "inputs": inputs,
        "ceiling_ft": obs.get("ceiling_ft"),
        "ceiling": {
            "name": "ceiling",
            "value": obs.get("ceiling_ft"),
            "unit": "ft",
            "source": obs.get("ceiling_source") or obs.get("ceiling_note"),
            "as_of": obs.get("ceiling_as_of") if obs.get("ceiling_ft") else None,
        },
        "table": spec["table"],
        "label": spec["label"],
        "reason": None,
    }
    for i in inputs:
        if i["value"] is None:
            out["reason"] = f"not determined: {i['name']} not held"
            return out
    tenths = obs["sky_cover_pct"] / 10.0
    ceiling = obs.get("ceiling_ft")
    overcast = tenths >= 10
    if overcast and ceiling is None:
        out["reason"] = "not determined: ceiling height not held"
        return out
    if overcast and ceiling < spec["ceiling_low_ft"]:
        nri = 0  # item 1, day or night
    elif solar["period"] == "night":
        nri = -2 if tenths <= spec["night_clear_max_tenths"] else -1  # item 2
    else:
        ins = next(
            (
                b["class"]
                for b in spec["insolation"]
                if solar["elevation_deg"] > b["above_deg"]
            ),
            1,
        )
        out["insolation_class"] = ins
        if tenths > spec["day_clear_max_tenths"]:  # item 3(c)
            if ceiling is None:
                out["reason"] = "not determined: ceiling height not held"
                return out
            if ceiling < spec["ceiling_low_ft"]:
                ins -= 2
            elif ceiling < spec["ceiling_high_ft"]:
                ins -= 1
            if overcast:
                ins -= 1
            ins = max(ins, 1)
        nri = ins
    knots = round(obs["wind_ms"] / _MS_PER_KNOT)
    row = next(
        r for r in spec["rows"] if r["knots_max"] is None or knots <= r["knots_max"]
    )
    number = min(
        row["classes"][spec["net_radiation_indices"].index(nri)],
        int(spec["highest_class"]),
    )
    out.update(
        {
            "class": "ABCDEFG"[number - 1],
            "number": number,
            "net_radiation_index": nri,
            "wind_knots": knots,
        }
    )
    return out


def solar_at(lat: float, lon: float, when, cfg: dict) -> dict:
    """The solar altitude at the point and time (astral's NOAA equations, `code:astral`,
    the source of the brief's day and night) and Turner's period from the sunrise and
    sunset of that day."""
    from datetime import timezone

    from astral import Observer
    from astral.sun import elevation

    from hazbrief import incident

    spec = cfg["weather"]["stability"]
    t = when.astimezone(timezone.utc)
    dn = incident.day_or_night(lat, lon, when)
    if dn["sunrise"] is None:  # polar day or night: no margin to apply
        period = dn["period"]
    elif dn["period"] == "night":
        period = "night"
    else:
        from hazbrief.evidence import store as S

        period = turner_period(
            t,
            S.parse_time(dn["sunrise"]),
            S.parse_time(dn["sunset"]),
            float(spec["night_margin_h"]),
        )
    return {
        "elevation_deg": round(elevation(Observer(lat, lon), t), 1),
        "period": period,
        "when": when.isoformat(),
        "sunrise": dn["sunrise"],
        "sunset": dn["sunset"],
        "source": "NOAA solar equations (astral)",
    }


def stated_stability(brief, computed: dict) -> dict:
    """The stability entry a stated weather source gives (DN-019 ADDENDUM-01 section 1;
    HB-139): the class the block states, with its basis as the source, in place of the
    class Turner's key computes (`_hb57`, kept as the entry's inputs, so the wind speed
    the one-wind check reads is still the record's). Unchanged when the record states
    no class (the forecast; HB-133's stated wind when no forecast cell is held)."""
    resolved = getattr(brief, "wind_resolved", False)
    rec = getattr(brief, "wind_record", None) if resolved else None
    cls = (rec or {}).get("stability_class")
    if not cls:
        return computed
    out = copy.deepcopy(computed)
    out["inputs"] = list(out.get("inputs") or []) + [
        {
            "name": "stability class (stated)",
            "value": cls,
            "unit": "Pasquill-Gifford class",
            "source": rec["source"],
            "as_of": rec.get("as_of"),
        }
    ]
    out.update(
        {
            "class": cls,
            "number": "ABCDEF".index(cls) + 1,
            "net_radiation_index": None,
            "insolation_class": None,
            "reason": None,
            "stated": True,
            "computed_class": computed.get("class"),
            "computed_reason": computed.get("reason"),
        }
    )
    return out


def _hb57(
    brief, fp: dict, spill, forecast: dict, cfg: dict, observation: dict | None = None
) -> dict:
    """The stability class for one brief (HB-57): the footprint's wind, the held sky
    cover at the as-given hour (the gridpoint's `skyCover`, hour 0 of HB-56's window),
    the ceiling, and the solar altitude at the spill and the as-given time. The ceiling
    is the nearest station's (HB-60) when its observation is usable and reports one;
    else the gridpoint's when it holds one; else none, and the class is computed as
    HB-57 computes it."""
    from hazbrief.evidence import store as S

    wind = brief_wind(brief, fp) or {}
    rows = forecast.get("rows") or []
    hour0 = rows[0] if rows else {}
    point = forecast_point(spill)
    when = S.parse_time(brief.as_given) if brief.as_given else brief.now
    obs = {
        "wind_ms": (
            wind["speed_kmh"] / 3.6 if wind.get("speed_kmh") is not None else None
        ),
        "wind_source": wind.get("source"),
        "wind_as_of": wind.get("as_of"),
        "sky_cover_pct": hour0.get("skyCover"),
        "sky_source": (
            f"NWS gridpoint forecast {forecast.get('grid')} skyCover" if hour0 else None
        ),
        "sky_as_of": forecast.get("update_time"),
        "ceiling_ft": (
            forecast["ceiling_m"] / 0.3048
            if forecast.get("ceiling_m") is not None
            else None
        ),
        "ceiling_source": (
            f"NWS gridpoint forecast {forecast.get('grid')} ceilingHeight"
            if forecast.get("ceiling_m") is not None
            else None
        ),
        "ceiling_as_of": forecast.get("update_time"),
    }
    o = observation or {}
    if o.get("usable") and o.get("ceiling_ft") is not None:
        obs.update(
            ceiling_ft=float(o["ceiling_ft"]),
            ceiling_source=f"NWS observation, station {o['station']}",
            ceiling_as_of=o["observed_at"],
        )
    elif obs["ceiling_ft"] is None:
        obs["ceiling_note"] = (
            o["ceiling_note"]
            if o.get("usable")
            else f"no usable observation ({o.get('stale_reason') or o.get('reason')})"
        )
    solar = (
        solar_at(point[0], point[1], when, cfg)
        if point
        else {"elevation_deg": None, "period": None, "when": when.isoformat()}
    )
    return stability_class(obs, solar, cfg)


def stability_hours(brief, spill, grid, out: dict, cfg: dict) -> dict:
    """HB-189 (DN-028 ADDENDUM-14 decision 2): the class at every hour from the release
    to the steps' horizon, and whether the stable treatment applies (any hour class E
    or F, SLAB's stable STAB, `agreement.yaml reach.stable_stab`). Hour 0 is the brief's
    own class (the derived `stability` entry); each later hour is Turner's key
    (`stability_class`) on the gridpoint forecast's wind speed, sky cover and ceiling at
    that hour and the sun's altitude at the spill then. A brief whose one wind record is
    stated or observed is not driven by the forecast (HB-133), so it reads its release
    hour's class alone; an hour the forecast does not hold is a row with its reason,
    never a class."""
    from datetime import timedelta

    from hazbrief import nws
    from hazbrief.evidence import store as S

    stab_of = cfg["weather"]["dense_gas"]["stab"]
    horizon = int(math.ceil(float(cfg["weather"]["puff"]["steps"]["horizon_h"])))
    rel = out.get("stability") or {}

    def stable(letter) -> bool:
        n = stab_of.get(str(letter or "").upper())
        return n is not None and slab_stable_stab(n)

    rows = [
        {
            "hour": 0,
            "class": rel.get("class"),
            "reason": rel.get("reason"),
            "basis": "the brief's class",
        }
    ]
    rec_w = getattr(brief, "wind_record", None)
    resolved = getattr(brief, "wind_resolved", False)
    by_forecast = not (
        resolved and rec_w is not None and rec_w.get("kind") != "forecast"
    )
    point = forecast_point(spill)
    if by_forecast and point and grid is not None and grid.status == 200:
        props = grid.body.get("properties") or {}
        when = S.parse_time(brief.as_given) if brief.as_given else brief.now
        for h in range(1, horizon + 1):
            t = when + timedelta(hours=h)
            got: dict = {}
            why = None
            for name, word in (
                ("windSpeed", "wind speed"),
                ("skyCover", "sky cover"),
                ("ceilingHeight", "ceiling height"),
            ):
                try:
                    got[name], _, _ = nws.value_at(props.get(name), t, word)
                except (nws.WindUnavailable, UpstreamServiceError) as exc:
                    got[name] = None
                    if name != "ceilingHeight":
                        why = str(exc)
            if why:
                rows.append({"hour": h, "class": None, "reason": why, "basis": None})
                continue
            obs = {
                "wind_ms": got["windSpeed"] / 3.6,  # wmoUnit:km_h-1
                "sky_cover_pct": got["skyCover"],
                "ceiling_ft": (
                    got["ceilingHeight"] / 0.3048
                    if got["ceilingHeight"] is not None
                    else None
                ),
            }
            c = stability_class(obs, solar_at(point[0], point[1], t, cfg), cfg)
            rows.append(
                {
                    "hour": h,
                    "class": c["class"],
                    "reason": c["reason"],
                    "basis": "the gridpoint forecast at the hour",
                }
            )
    first = next((r["hour"] for r in rows if stable(r["class"])), None)
    return {
        "hours": rows,
        "horizon_h": horizon,
        "by_forecast": bool(by_forecast and len(rows) > 1),
        "stable": first is not None,
        "first_stable_hour": first,
        "first_stable_class": rows[first]["class"] if first is not None else None,
    }


def stable_treatment(out: dict) -> bool:
    """Whether the brief takes the stable treatment (`stability_hours`)."""
    return bool((out.get("stability_hours") or {}).get("stable"))


# ── the first-order puff (DN-018 sections 4, 5, 8 and 9; HB-67) ───────────────────────


def _module_version() -> str:
    """The engine's version: the sha256 prefix of `hazbrief/brief/puff.py`'s bytes."""
    import hashlib

    from hazbrief.brief import puff as engine

    return hashlib.sha256(Path(engine.__file__).read_bytes()).hexdigest()[:12]


def _wind_at(rows: list[dict]):
    """The forecast window as an hourly wind (`puff.HourlyWind`) in seconds after the
    as-given time: hour h's row covers [h, h + 1) hours (HB-56's rows, read at each
    hour's start; the NWS gridpoint value is held over its interval, DN-025 section 3
    item 1). A time before the first held hour reads the first; after the last, the
    last (the channel requires every hour of its window, so a gap inside it never
    reaches here). Called with a time it gives (speed m/s, direction from); it carries
    each puff on every hour it travels (DN-025)."""
    from hazbrief.brief import puff as engine

    by_hour = {int(r["hour"]): r for r in rows}
    hours = sorted(by_hour)
    return engine.HourlyWind(
        [h * 3600.0 for h in hours],
        [by_hour[h]["windSpeed"] / 3.6 for h in hours],
        [by_hour[h]["windDirection"] for h in hours],
    )


def _when(iso: str, tz: str | None) -> str:
    """An instant as the page prints it (SB-NUM-06), in the brief's zone; as given
    when the brief has none yet."""
    from hazbrief.evidence import labels as L

    return L.when(iso, tz) if tz else iso


def _stated_wind_at(speed_ms: float, direction_deg_from: float):
    """A stated wind as the window's wind: the same speed and direction for every hour
    (HB-70 step 3; `puff.steady`)."""
    from hazbrief.brief import puff as engine

    return engine.steady(speed_ms, direction_deg_from)


def calm_stand_in(brief, observation: dict | None) -> dict | None:
    """The nearest station's observation as the wind for a forecast hour that reads
    calm (HB-75 step 1), or None when it cannot stand in: absent, not usable at the
    as-given time (DN-010's stale rule, HB-60's `usable`), calm itself, without a
    direction, or with no as-given time to state its age against (DN-009 C1: its age
    and distance print beside it, so a value whose age cannot be stated is not used).
    Nothing is defaulted: a stand-in is the observation's own speed and direction."""
    from hazbrief.evidence import store as S

    o = observation or {}
    if not (o.get("station") and o.get("usable")):
        return None
    if not o.get("wind_ms") or o["wind_ms"] <= 0 or o.get("wind_from_deg") is None:
        return None
    as_given = getattr(brief, "as_given", None)
    when = S.parse_time(as_given) if as_given else getattr(brief, "now", None)
    if when is None:
        return None
    age = (when - S.parse_time(o["observed_at"])).total_seconds()
    return {**o, "age_s": age, "age": _span(age)}


def _hours_text(hours: list[int], all_hours: list[int]) -> str:
    """Hours of the window as the panel names them: "both hours of the window" (or
    "all 3 hours"), "hour 0", "hours 0 and 1", "hours 0, 2 and 3"."""
    if hours == all_hours and len(hours) > 1:
        if len(hours) == 2:
            return "both hours of the window"
        return f"all {len(hours)} hours of the window"
    if len(hours) == 1:
        return f"hour {hours[0]}"
    return "hours " + ", ".join(str(h) for h in hours[:-1]) + f" and {hours[-1]}"


def puff_grid(
    curves: dict, cls: str, speed_ms: float, window_s: float, floor_m: float, spec
) -> dict:
    """The grid the puff fits (HB-70 step 1). The farthest puff centre at the window's
    end has travelled at most the largest driving wind times the window (each puff
    keeps the wind it was released in, and the first lives the whole window); the
    contour reaches `grid_sigma_multiple` sigma_y beyond it, the held equation's
    along-wind and crosswind spread both being sigma_y (Jia et al. 2025 Eq. (2)).
    sigma_y grows with the distance travelled, so the bound holds for every puff. The
    half-width is that reach or the floor (the ERG distance x `grid_factor`),
    whichever is larger; the cell size is the floor grid's (2 x floor / `grid_cells`),
    the count odd so the spill sits on a cell centre. Past `grid_cells_max` cells a side
    the count stops and the cell grows (`coarsened`), so the channel stays inside its
    timeout (DN-018 section 8, C3)."""
    from hazbrief.brief import puff as engine

    k = float(spec["grid_sigma_multiple"])
    travel = speed_ms * window_s
    spread = 0.0
    if travel > 0:
        sy, _ = engine.sigmas(curves, cls, [travel])
        spread = k * float(sy[0])
    reach = travel + spread
    half = max(reach, floor_m)
    step = 2.0 * floor_m / int(spec["grid_cells"])
    cells = math.ceil(2.0 * half / step - 1e-9)
    cells += 1 - cells % 2
    most = int(spec["grid_cells_max"])
    needed = cells
    coarsened = cells > most
    if coarsened:
        # past the ceiling the cell grows instead (a small ERG floor and a long reach:
        # UN1977's 100 m floor over a 21 km reach would ask 17,219 cells a side)
        cells = most - (1 - most % 2)
        step = 2.0 * half / cells
    return {
        "half_width_m": cells * step / 2.0,
        "cells": cells,
        "step_m": step,
        "reach_m": reach,
        "travel_m": travel,
        "spread_m": spread,
        "speed_ms": speed_ms,
        "floor_m": floor_m,
        "coarsened": coarsened,
        "cells_needed": needed,
    }


def proxied(mat: dict, mdata: dict) -> tuple[dict, dict | None]:
    """A material whose pack entry is a proxy (LPG, UN1075: `thermodynamics.proxy`,
    "propane properties used for LPG") with the proxy's molecular weight and LFL where
    its own are not held, and the input row that says so (issue 9e47d690; DN-020
    ADDENDUM-01 item 4: "LPG uses propane's properties and says so"). A material that
    is its own is returned as it is, with no row."""
    proxy = (mat.get("thermodynamics") or {}).get("proxy")
    if not proxy:
        return mat, None
    of = str(proxy["properties_of"]).removeprefix("UN")
    other = (mdata.get("materials") or {}).get(of)
    if other is None:
        return mat, None
    out = dict(mat)
    for key in ("molecular_weight_g_mol", "lfl_vol_pct"):
        if (mat.get(key) or {}).get("status") != "held":
            out[key] = other[key]
    rec = proxy.get("receipt") or {}
    row = {
        "name": "properties (proxy)",
        "value": f"{proxy['label']} (UN{of}): molecular weight and LFL are UN{of}'s",
        "source": f'{rec.get("doc_id")} p. {rec.get("page")}: "{rec.get("quote")}"',
        "as_of": None,
        "sha256": None,
    }
    return out, row


def _thresholds(
    mat: dict, air: dict, minutes: list[int]
) -> tuple[list[dict], str | None]:
    """The thresholds the material's class names (DN-018 section 3), each in kg/m3 at
    each contour minute, or the first one not held."""
    un = mat["un"]
    mw = mat["molecular_weight_g_mol"]
    if mw["status"] != "held":
        return [], f"molecular weight for UN{un} not held ({mw['reason']})"
    vm = air["molar_volume_m3_kmol"]["value"]
    out = []
    cls = mat["dispersion_class"]
    if cls == "pressure_liquefied_toxic":
        if not mat["aegl_ppm"]:
            return [], f"AEGL for UN{un} not held ({mat['aegl_reason']})"
        for level in ("AEGL-2", "AEGL-3"):
            cells = mat["aegl_ppm"].get(level) or {}
            for m in minutes:
                cell = cells.get(str(m))
                if not cell or cell["status"] != "held":
                    return [], f"{level} at {m} minutes for UN{un} not held"
                out.append(
                    {
                        "threshold": f"{level} ({m} min)",
                        "minute": m,
                        "as_printed": f"{cell['value']:g} ppm",
                        "kg_m3": cell["value"] * 1e-6 * mw["value"] / vm,
                        "source": cell["receipt"]["locator"],
                    }
                )
    elif cls == "cryogenic_asphyxiant":
        o2 = mat["oxygen_deficiency_threshold_vol_pct"]
        if o2["status"] != "held":
            return [], f"oxygen threshold for UN{un} not held"
        frac = air["asphyxiant_vol_pct_at_threshold"]["value"] / 100.0
        for m in minutes:
            out.append(
                {
                    "threshold": f"oxygen below {o2['value']:g} % by volume",
                    "minute": m,
                    "as_printed": (
                        f"{100 * frac:.2f} % by volume displaces oxygen below "
                        f"{o2['value']:g} %"
                    ),
                    "kg_m3": frac * mw["value"] / vm,
                    "source": o2["receipt"]["locator"],
                }
            )
    else:
        lfl = mat["lfl_vol_pct"]
        if lfl["status"] != "held":
            return [], f"LFL for UN{un} not held ({lfl['reason']})"
        for m in minutes:
            out.append(
                {
                    "threshold": f"LFL {lfl['value']:g} %",
                    "minute": m,
                    "as_printed": f"{lfl['value']:g} % by volume",
                    "kg_m3": lfl["value"] / 100.0 * mw["value"] / vm,
                    "source": lfl["receipt"]["locator"],
                }
            )
    return out, None


def _number_in(quote: str, pattern: str) -> float:
    """The number `pattern` reads out of a config quote (`m * 10**e` for two groups)."""
    import re

    m = re.search(pattern, quote)
    if not m:
        raise DeriveError(f"{pattern!r} reads nothing in {quote!r}")
    v = float(m.group(1))
    return v * 10 ** int(m.group(2)) if m.lastindex and m.lastindex >= 2 else v


def _row_numbers(quote: str) -> list[float]:
    """An Exhibit row's numbers after its CAS number, footnote letters and words
    skipped."""
    import re

    rest = quote.split(" ", 1)[1]
    return [float(x) for x in re.findall(r"(?<![\w.-])\d*\.?\d+(?![\w.-])", rest)]


def equation_7_1(
    un: str, hole_diameter_m: float, spec: dict
) -> tuple[float | None, str]:
    """EPA RMP OCA Guidance Equation 7-1 (epa-rmp-oca-guidance-2009 p. 78; flammable
    gases by the same method, p. 97), choked gas flow from a hole:

        QR = HA x Pt x (1 / sqrt(Tt)) x GF

    QR in pounds per minute, HA the hole area in square inches, Pt the tank pressure in
    psia (a liquefied gas's equilibrium vapour pressure at 25 C, Exhibit B-1), Tt in K
    (298 K), GF the gas factor (Exhibit B-1 for toxic gases, C-2 for flammable). Returns
    (rate in kg/s, how) or (None, the input not held). Every constant is parsed from its
    quote in `weather.puff.equation_7_1` (its pages verified by
    tests/test_brief_release.py).
    The guidance: it "will overestimate the overall release rate, because it does not
    take into account the decrease in the release rate as the pressure in the tank
    decreases" (p. 78)."""
    eq = spec["equation_7_1"]
    gas = (eq["gases"] or {}).get(un)
    if gas is None:
        return (
            None,
            f"the gas factor for UN{un} is not held (EPA RMP Exhibits B-1 and C-2)",
        )
    nums = _row_numbers(gas["quote"])
    gf = nums[gas["gas_factor"]]
    if gas["vapor_pressure_psia"] is None:
        return None, (
            f"the tank pressure for UN{un} is not held ({gas['exhibit']} states no "
            "vapour pressure)"
        )
    pt = nums[gas["vapor_pressure_psia"]]
    tt = _number_in(
        eq["tank_temperature_k"]["quote"], eq["tank_temperature_k"]["pattern"]
    )
    m2_in2 = _number_in(eq["m2_per_in2"]["quote"], eq["m2_per_in2"]["pattern"])
    lbmin = _number_in(eq["lb_min_per_kg_s"]["quote"], eq["lb_min_per_kg_s"]["pattern"])
    ha = math.pi * (hole_diameter_m / 2.0) ** 2 / m2_in2
    qr = ha * pt * (1.0 / math.sqrt(tt)) * gf
    how = (
        f"RMP Equation 7-1: HA {ha:.3f} sq in x Pt {pt:g} psia x 1/sqrt({tt:g} K) x GF "
        f"{gf:g} = {qr:.1f} lb/min ({gas['exhibit']}, {gas['doc']} p. {gas['page']})"
    )
    return qr / lbmin, how


def source_term_inputs(
    brief,
    fp: dict,
    derived: dict,
    cfg: dict,
    release,
    wind_ms: float,
    stability: dict,
):
    """The source term's scenario and weather for one brief (HB-110 step 5): the
    material, its DN-001 class and ERG names from the footprint; the container and the
    surface from the incident the footprint was called with; the quantity from the
    release block; the air temperature at hour 0 of the forecast window (else the
    nearest station's observation); the wind driving the puff at hour 0; and from
    `stability`, the puff's own stability entry (passed, not read again: derive.puff
    is the class's one reader in this module), the class and the sky cover and solar
    altitude it read; the relative humidity from the record the temperature came from
    (HB-112). Returns (Scenario, Met or None, the temperature's and the humidity's
    input rows, or None)."""
    from hazbrief.brief import source_term as ST

    spec = cfg["weather"]["source_term"]
    k = ST.constants(spec)
    mat = fp.get("material") or {}
    record = (brief.channels.get("protective_action_footprint") or {}).get("record")
    incident = (((record or {}).get("activity") or {}).get("params") or {}).get(
        "incident"
    ) or {}
    state, basis = ST.route_state(
        (fp.get("hazard_class") or {}).get("class_id"), mat.get("names")
    )
    scenario = ST.Scenario(
        un=str(mat.get("un_number")) if mat.get("un_number") else None,
        container=incident.get("container"),
        storage_state=state,
        quantity_kg=release.quantity_kg,
        where_spilled=incident.get("where_spilled") or "land",
        unresolved_reason=None if state else basis,
    )
    rows = (derived.get("forecast") or {}).get("rows") or []
    hour0 = next((r for r in rows if int(r.get("hour", -1)) == 0), {})
    # The air's temperature and its relative humidity come from one record (HB-112
    # ADDENDUM-02 section 2, "the same NWS record its temperature row uses"): relative
    # humidity is relative to that temperature, so the two are never taken from two
    # records. The forecast's hour 0 first, else the usable observation.
    t_c, t_row, rh, rh_row = hour0.get("temperature"), None, None, None
    if t_c is not None:
        fc = derived.get("forecast") or {}
        grid = fc.get("grid")
        where = f"NWS gridpoint forecast {grid}, hour 0"
        t_row = {
            "name": "air temperature (source term)",
            "value": f"{t_c:.1f} C",
            "source": where,
            "as_of": fc.get("update_time"),
            "sha256": None,
        }
        rh = fc.get("relative_humidity_pct")
        rh_as_of = fc.get("update_time")
    else:
        o = derived.get("observation") or {}
        if o.get("usable") and o.get("temperature_c") is not None:
            t_c = o["temperature_c"]
            where = f"NWS observation, station {o.get('station')}"
            t_row = {
                "name": "air temperature (source term)",
                "value": f"{t_c:.1f} C",
                "source": where,
                "as_of": o.get("observed_at"),
                "sha256": None,
            }
            rh = o.get("relative_humidity_pct")
            rh_as_of = o.get("observed_at")
    if rh is not None:
        rh_row = {
            "name": "relative humidity (source term)",
            "value": f"{rh:.0f} %",
            "source": where,
            "as_of": rh_as_of,
            "sha256": None,
        }
    if t_c is None or wind_ms is None or wind_ms <= 0:
        return scenario, None, None
    stab = {i["name"]: i.get("value") for i in stability.get("inputs") or []}
    cls = stability["class"]
    sky = stab.get("sky cover")
    t_k = float(t_c) + 273.15
    amb = ST.Ambient(
        pressure_pa=k["one_atmosphere_pa"],
        temperature_k=t_k,
        wind_ms=float(wind_ms),
        wind_height_m=k["deacon_height_m"],
        stability=cls,
        z0_m=k["open_country_z0_m"],
        cloud_tenths=None if sky is None else float(sky) / 10.0,
        solar_altitude_deg=stab.get("solar altitude"),
        rh_pct=rh,
    )
    kind = (
        "water"
        if scenario.where_spilled == "water"
        else spec["assumptions"]["ground_kind"]
    )
    ground = ST.Ground(kind, t_k, spec["assumptions"]["pool_spill"])
    rows = [r for r in (t_row, rh_row) if r]
    return scenario, ST.Met(amb, ground), rows


def _source_term_envelope(
    brief, fp: dict, derived: dict, cfg: dict, pack: dict, release, wind_ms, stability
) -> tuple[dict | None, str | None, list[dict], dict]:
    """The source term's envelope (HB-110 step 5), or (None, why, rows) where there is
    none: the worst case stays, and the line says why. The fourth value is what the
    dense-gas channel reads (HB-112; DN-020 section 3.4: the same source term): the
    scenario, the `Result` or the reason there is none, and the weather."""
    from hazbrief.brief import source_term as ST

    scenario, met, met_rows = source_term_inputs(
        brief, fp, derived, cfg, release, wind_ms, stability
    )
    res, why = ST.source_term(scenario, pack, met, cfg["weather"]["source_term"])
    rows = list(met_rows or [])
    run = {"scenario": scenario, "result": res, "why": why, "met": met}
    if res is None:
        return None, why, rows, run
    spec = cfg["weather"]["puff"]
    r = res.result
    window_s = float(spec["window_min"]) * 60.0
    duration = min(r["duration_s"], window_s)
    rows.append(
        {
            "name": "source term",
            "value": (
                f"{res.model}: {r['mean_rate_kg_s']:.2f} kg/s for "
                f"{r['duration_s'] / 60.0:.1f} minutes"
            ),
            "source": r["method"],
            "as_of": None,
            "sha256": None,
        }
    )
    env = {
        "name": "source_term",
        "title": spec["envelopes"]["source_term"]["title"],
        "mass_kg": r["released_kg"],
        "duration_s": duration,
        "rate_kg_s": r["mean_rate_kg_s"],
        "rate_how": r["method"],
        "hole_source": None,
        "quantity_kg": release.quantity_kg,
        "quantity_source": release.quantity_source,
        "source_term": {
            "model": res.model,
            **{k: v for k, v in r.items() if k != "series"},
            "assumptions": res.assumptions,
            "inputs": res.inputs,
            "notes": list(res.material.notes),
        },
        "assumption": ST.envelope_assumption(
            res, release.quantity_kg, release.quantity_source, spec
        ),
    }
    return env, None, rows, run


def _envelopes(
    rdata: dict, release, un: str, spec: dict, window_s: float, source_env=None
) -> list[dict]:
    """The two envelopes from the scenario's release block (DN-018 ADDENDUM-00 section
    3): the worst case, the stated quantity over RMP's ten minutes, replaced by the
    source term's envelope where one exists (HB-110 step 5); the alternative, only with
    a stated hole, at RMP Equation 7-1's rate until the stated quantity is gone or the
    window ends. An envelope that cannot be drawn carries the reason."""
    rel = spec["release"]
    minutes = rdata["worst_case"]["duration_min"]["value"]
    common = {
        "quantity_kg": release.quantity_kg,
        "quantity_source": release.quantity_source,
    }
    worst = source_env or {
        "name": "worst_case",
        "title": spec["envelopes"]["worst_case"]["title"],
        "mass_kg": release.quantity_kg,
        "duration_s": minutes * 60.0,
        "hole_source": None,
        **common,
        "assumption": spec["envelopes"]["worst_case"]["assumption"].format(
            quantity=release.quantity_kg,
            quantity_source=release.quantity_source,
            minutes=minutes,
        ),
    }
    alt_title = spec["envelopes"]["alternative"]["title"]
    if release.hole_diameter_m is None:
        return [
            worst,
            {
                "name": "alternative",
                "title": alt_title,
                "reason": rel["hole_not_given"],
            },
        ]
    rate, how = equation_7_1(un, release.hole_diameter_m, spec)
    if rate is None:
        return [worst, {"name": "alternative", "title": alt_title, "reason": how}]
    duration = min(release.quantity_kg / rate, window_s)
    alt = {
        "name": "alternative",
        "title": alt_title,
        "mass_kg": rate * duration,
        "duration_s": duration,
        "rate_kg_s": rate,
        "rate_how": how,
        "hole_diameter_m": release.hole_diameter_m,
        "hole_source": release.hole_source,
        **common,
        "assumption": spec["envelopes"]["alternative"]["assumption"].format(
            hole_cm=release.hole_diameter_m * 100.0,
            hole_source=release.hole_source,
            rate=rate,
            quantity=release.quantity_kg,
            quantity_source=release.quantity_source,
            minutes=duration / 60.0,
        ),
    }
    return [worst, alt]


def run_puff(
    spill_xy_deg: tuple[float, float],
    envelope: dict,
    thresholds: list[dict],
    wind,
    curves: dict,
    cls: str,
    half_width_m: float,
    spec: dict,
    start_s: float = 0.0,
    deadline: float | None = None,
    cells: int | None = None,
) -> dict:
    """One envelope: puffs from its release, the field at each contour minute, and one
    contour per threshold whose minute it is, in longitude and latitude around the
    spill. `start_s`: when the release begins, in seconds after the window's start (the
    channel's is 0: the release begins at the as-given time, hour 0 of the forecast
    window). `cells`: the grid's cells a side (`puff_grid`'s); None is the config's
    `grid_cells`. Pure over its arguments (the tests drive it directly)."""
    from hazbrief.brief import contours as isolines
    from hazbrief.brief import puff as engine

    c = Point(*spill_xy_deg)
    xg, yg, step = engine.grid(half_width_m, int(cells or spec["grid_cells"]))
    puffs = engine.release(
        envelope["mass_kg"],
        envelope["duration_s"],
        float(spec["puff_dt_s"]),
        wind,
        start_s=start_s,
    )
    contours, skipped, extents, edges = [], 0, {}, set()
    beyond = []
    for m in sorted({t["minute"] for t in thresholds}):
        # where the release is at this minute: the farthest live puff's centre. Past
        # the grid's edge, a missing contour may be the grid, not the dilution.
        now_s = start_s + m * 60.0
        far = max(
            (
                math.hypot(*engine.centre(p, now_s)[:2])
                for p in puffs
                if 0 < now_s - p.t_s <= float(spec["lifetime_s"])
            ),
            default=0.0,
        )
        if far > half_width_m:
            beyond.append(m)
        field, skipped = engine.field(
            puffs,
            start_s + m * 60.0,
            xg,
            yg,
            curves,
            cls,
            z_m=float(spec["receptor_height_m"]),
            z0_m=float(spec["release_height_m"]),
            lifetime_s=float(spec["lifetime_s"]),
            low_wind_ms=float(spec["low_wind_ms"]),
            deadline=deadline,
        )
        for t in (t for t in thresholds if t["minute"] == m):
            poly = engine.contour(field, xg, yg, step, t["kg_m3"])
            extents[t["threshold"]] = round(engine.extent_m(poly), 0)
            if poly is None:
                continue
            # a contour that reaches the grid's edge is clipped by the grid: its true
            # extent is at least the half-width, and the line says so (never hidden)
            at_edge = max(abs(v) for v in poly.bounds) >= half_width_m - step
            if at_edge:
                edges.add(t["threshold"])
            # HB-133 ADDENDUM-01: drawn as the isoline through the field (marching
            # squares, `contours.level_set`), not the cells above it; the extent above
            # stays the engine's cell reading, which the run record keeps
            drawn = isolines.level_set(field, xg, yg, t["kg_m3"]) or poly
            drawn = drawn.simplify(
                step * float(spec["contour_simplify_cells"]), preserve_topology=True
            )
            geom = _unplane(drawn, c)
            contours.append(
                {
                    "threshold": t["threshold"],
                    "minute": m,
                    "geometry": {
                        "type": geom.geom_type,
                        "coordinates": _round_coords(mapping(geom)["coordinates"]),
                    },
                    "extent_m": extents[t["threshold"]],
                    "cell_m": round(step, 1),
                    "reaches_grid_edge": at_edge,
                }
            )
    return {
        "puffs": len(puffs),
        "skipped_low_wind": skipped,
        "contours": contours,
        "extents_m": extents,
        "at_grid_edge": sorted(edges),
        "beyond_grid_minutes": beyond,
        "grid_half_width_m": half_width_m,
    }


def puff(brief, fp: dict, derived: dict, cfg: dict, packs: dict | None = None) -> dict:
    """The puff channel for one brief (HB-67): the material's class, thresholds and
    molecular weight from packs/materials_properties.json, the container's two
    envelopes from packs/release_scenarios.json, the hourly wind from HB-56's window,
    the class from HB-57's `stability` entry. A missing input writes no polygon and one
    line naming it (per envelope where only that envelope lacks it); the ERG footprint
    is never touched. Every run, drawn or not, carries its evidence record with the
    hashes of what it read (DN-018 section 8, C2). `packs` (kind -> pack) replaces the
    committed application packs, for the failure harness (HB-68); None reads them."""
    import hashlib

    from hazbrief import packs as P

    spec = cfg["weather"]["puff"]
    minutes = [int(m) for m in spec["contour_minutes"]]
    out: dict[str, Any] = {
        "engine": spec["engine"],
        "version": _module_version(),
        "envelopes": [],
        "lines": [],
        "inputs": [],
        "label": None,
        "dense_gas_caveat": None,
        "assumptions": [],
        # HB-120: the routing table's decision; the puff follows the same table as the
        # dense-gas channel, so a not-applicable guide draws no puff either and says so
        "state": None,
        "release_route": None,
    }

    def finish():
        if out["state"] is None:
            drawn = any(e.get("contours") for e in out["envelopes"])
            out["state"] = "drawn" if drawn else "not_available"
        record = {
            k: out[k]
            for k in ("engine", "version", "inputs", "lines", "state", "release_route")
        }
        record["envelopes"] = [
            {k: e.get(k) for k in ("name", "reason", "extents_m")}
            for e in out["envelopes"]
        ]
        # HB-163 (DN-026): the release's class and every number it rests on
        if out.get("engine_rule") is not None:
            record["engine_rule"] = out["engine_rule"]
        # HB-157: what the steps computed (C2): where they ended and why, the level,
        # the uncertainty lines' angle and the range's reason
        tl = out.get("timeline")
        if tl is not None:
            record["timeline"] = {
                "reason": tl.get("reason"),
                "end_minute": tl.get("end_minute"),
                "ended_by": tl.get("ended_by"),
                "level": (tl.get("level") or {}).get("threshold"),
                "alpha_deg": (tl.get("uncertainty") or {}).get("alpha_deg"),
                "range_reason": tl.get("range_reason"),
                "steps": [s["minute"] for s in tl.get("steps") or []],
            }
            # HB-162R (DN-025 section 3 item 5): the levels the cloud is drawn by,
            # their run's end and the hours' wind the puffs were carried on
            lr = tl.get("levels_run")
            if lr:
                record["timeline"]["levels"] = {
                    "tiers": [t["name"] for t in lr["tiers"]],
                    "end_minute": lr["end_minute"],
                    "wind": lr["run_inputs"]["wind"],
                }
        text = json.dumps(record, sort_keys=True, separators=(",", ":"))
        out["evidence"] = {
            "record": record,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }
        return out

    def stop(what: str):
        out["lines"].append(spec["not_drawn"].format(what=what))
        return finish()

    # The release route before any pack the puff reads (HB-120 ADDENDUM-01 section 2):
    # a not-applicable guide ends the channel with the ERG's reason, and nothing reads
    # the material's properties. A routed guide goes on as before; its not-available
    # lines are the ones below (HB-120 ADDENDUM-01 section 3: the brief is not yet
    # wired to the resolver, Issue d8668053).
    decision = _release_route(fp, out["inputs"])
    if decision is None:
        return stop("the release routing table is unavailable")
    out["release_route"] = decision.as_dict()
    if decision.status == "not_applicable":
        out["state"] = "not_applicable"
        out["lines"].append(spec["not_applicable"].format(reason=decision.reason))
        return finish()

    try:
        got = packs or {}
        mats = got.get("materials_properties") or P.load_app_pack(
            "materials_properties"
        )
        curves = got.get("sigma_curves") or P.load_app_pack("sigma_curves")
        release = got.get("release_scenarios") or P.load_app_pack("release_scenarios")
    except P.PackError as exc:
        return stop(f"a puff pack is unavailable ({exc})")
    for name, pack in (
        ("materials_properties", mats),
        ("sigma_curves", curves),
        ("release_scenarios", release),
    ):
        out["inputs"].append(
            {
                "name": f"pack {name}",
                "value": pack.version,
                "source": f"packs/{name}.json",
                "as_of": pack.built_at,
                "sha256": pack.sha256,
            }
        )
    mdata = mats.data.model_dump(mode="json")
    un = str((fp.get("material") or {}).get("un_number") or "")
    mat = mdata["materials"].get(un)
    if mat is None:
        if not un:
            return stop("the material is not resolved to an ID number")
        return stop(f"UN{un} is not in the puff's materials pack")
    mat, proxy_row = proxied(mat, mdata)
    if proxy_row:
        # LPG takes propane's molecular weight and LFL and says so (issue 9e47d690;
        # DN-020 ADDENDUM-01 item 4; HB-112 ADDENDUM-02 section 3); the source term's
        # envelope carries the same sentence in its assumption (the material's notes)
        out["inputs"].append(proxy_row)
    out["dense_gas_caveat"] = mat["dense_gas_caveat"]
    out["inputs"].append(
        {
            "name": "material class",
            "value": mat["dispersion_class"],
            "source": "DN-018 section 3",
            "as_of": None,
            "sha256": None,
        }
    )
    s = derived.get("stability") or {}
    cls = s.get("class")
    if not cls:
        return stop(f"stability class {s.get('reason') or 'not determined'}")
    out["inputs"].append(
        {
            "name": "stability class",
            "value": cls,
            "source": s.get("table"),
            "as_of": None,
            "sha256": None,
        }
    )
    # The wind driving the puff (HB-70 step 3): the scenario's stated wind when it
    # gives one, for every hour of the window; else the forecast, hour by hour, with
    # the nearest station's observation for an hour the forecast reads calm (HB-75);
    # else the calm line.
    from hazbrief.brief import stated_wind as W

    forecast = derived.get("forecast") or {}
    # HB-133: a brief that resolved its one wind record reads it and no other: the
    # record's stated wind when no forecast is held, else the forecast, hour by hour,
    # with no stand-in (the station observation is another record). Without a record
    # (the test harness), the engine's own choice below stands (HB-70, HB-75).
    resolved = bool(getattr(brief, "wind_resolved", False))
    record = getattr(brief, "wind_record", None) if resolved else None
    if resolved and record is None:
        return stop(spec["no_wind_record"])
    # HB-143: an observed record drives every hour as one wind, as a stated one does
    # (orchestrator.yaml puff.wind_observed_line says why); the panel names it observed
    held_kind = "stated"
    if resolved:
        stated, refused = None, None
        if record["kind"] in ("stated", "observed"):
            held_kind = record["kind"]
            stated = W.StatedWind(
                speed_m_s=float(record["speed_kmh"]) / 3.6,
                direction_deg_from=float(record["direction_deg_from"]),
                source=record["source"],
                observed_at=record.get("as_of"),
            )
    else:
        stated, refused = W.parse(getattr(brief, "stated_wind", None))
    if refused:
        return stop(spec["stated_wind_refused"].format(why=refused))
    if stated is not None and stated.speed_m_s is None:
        stated = None  # an empty block states nothing
    if stated is not None:
        wind_fn = _stated_wind_at(stated.speed_m_s, stated.direction_deg_from or 0.0)
        top_ms = stated.speed_m_s
        wind_as_of = stated.observed_at.isoformat() if stated.observed_at else None
        out["inputs"].append(
            {
                "name": f"wind ({held_kind})",
                "value": (
                    f"{stated.speed_m_s:.1f} m/s"
                    + (
                        f" from {stated.direction_deg_from:.0f} degrees"
                        if stated.direction_deg_from is not None
                        else ""
                    )
                ),
                "source": stated.source,
                "as_of": wind_as_of,
                "sha256": None,
            }
        )
        tz = getattr(brief, "time_zone", None)
        observed = f", observed {_when(wind_as_of, tz)}" if wind_as_of else ""
        out["assumptions"].append(
            spec[f"wind_{held_kind}_line"].format(
                speed=stated.speed_m_s,
                direction=stated.direction_deg_from or 0.0,
                source=stated.source,
                observed=observed,
            )
        )
        wind_label = spec[f"wind_{held_kind}"].format(source=stated.source)
        stand_in = None
        out["wind_hours"] = [
            {"hour": h, "wind_source": held_kind}
            for h in range(math.ceil(float(spec["window_min"]) / 60.0) + 1)
        ]
    else:
        rows = [
            r
            for r in forecast.get("rows") or []
            if r.get("windSpeed") is not None and r.get("windDirection") is not None
        ]
        window_h = math.ceil(float(spec["window_min"]) / 60.0)
        covered = {int(r["hour"]) for r in rows}
        if not set(range(window_h)) <= covered:
            return stop(
                f"no forecast wind for the {spec['window_min']}-minute window "
                f"({forecast.get('reason') or 'hours not covered'})"
            )
        rows = [r for r in rows if int(r["hour"]) <= window_h]
        # The fall-through (HB-75 step 1): a forecast hour that reads 0 takes the
        # nearest station's observation when it can stand in; every other hour keeps
        # the forecast. Never a floor: the stand-in is a measured wind or nothing.
        tz = getattr(brief, "time_zone", None)
        stand_in = (
            None if resolved else calm_stand_in(brief, derived.get("observation"))
        )
        calm_hours = [int(r["hour"]) for r in rows if r["windSpeed"] == 0]
        if stand_in is None:
            calm_hours = []
        driving = []
        for r in rows:
            h = int(r["hour"])
            if h in calm_hours:
                driving.append(
                    {
                        **r,
                        "windSpeed": stand_in["wind_ms"] * 3.6,
                        "windDirection": stand_in["wind_from_deg"],
                        "wind_source": "station_observation",
                    }
                )
                source = spec["wind_observation_source"].format(
                    station=stand_in["station"],
                    distance=stand_in["distance_km"],
                    grid=forecast.get("grid"),
                )
                as_of = stand_in["observed_at"]
            else:
                driving.append({**r, "wind_source": "forecast"})
                source = f"NWS gridpoint forecast {forecast.get('grid')}"
                as_of = forecast.get("update_time")
            out["inputs"].append(
                {
                    "name": f"wind, hour {h}",
                    "value": (
                        f"{driving[-1]['windSpeed']:.0f} km/h from "
                        f"{driving[-1]['windDirection']:.0f} degrees"
                    ),
                    "source": source,
                    "as_of": as_of,
                    "sha256": None,
                }
            )
        rows = driving
        out["wind_hours"] = [
            {"hour": int(r["hour"]), "wind_source": r["wind_source"]} for r in rows
        ]
        wind_fn = _wind_at(rows)
        top_ms = max(r["windSpeed"] for r in rows) / 3.6
        wind_as_of = forecast.get("update_time")
        forecast_as_of = _when(wind_as_of, tz) if wind_as_of else "unknown"
        if calm_hours:
            hours = [int(r["hour"]) for r in rows]
            rest = [h for h in hours if h not in calm_hours]
            out["assumptions"].append(
                spec["wind_observation_line"].format(
                    grid=forecast.get("grid"),
                    as_of=forecast_as_of,
                    calm_hours=_hours_text(calm_hours, hours),
                    station=stand_in["station"],
                    kmh=stand_in["wind_ms"] * 3.6,
                    ms=stand_in["wind_ms"],
                    direction=stand_in["wind_from_deg"],
                    observed=_when(stand_in["observed_at"], tz),
                    age=stand_in["age"],
                    distance=stand_in["distance_km"],
                    rest=(
                        spec["wind_observation_rest"].format(
                            hours=_hours_text(rest, hours)
                        )
                        if rest
                        else ""
                    ),
                )
            )
            wind_label = spec["wind_observation"].format(
                station=stand_in["station"],
                observed_at=stand_in["observed_at"],
                calm_hours=_hours_text(calm_hours, hours),
                as_of=wind_as_of,
            )
        else:
            out["assumptions"].append(
                spec["wind_forecast_line"].format(
                    grid=forecast.get("grid"), as_of=forecast_as_of
                )
            )
            wind_label = spec["wind_forecast"].format(as_of=wind_as_of)
    # The wind the puff read at hour 0, which the one-wind check compares with the
    # brief's record (HB-133 item 3; `wind_record.disagreements`)
    if stated is not None:
        out["wind_read"] = {
            "from_deg": float(stated.direction_deg_from or 0.0),
            "kmh": float(stated.speed_m_s) * 3.6,
            "source": stated.source,
        }
    else:
        out["wind_read"] = {
            "from_deg": float(rows[0]["windDirection"]),
            "kmh": float(rows[0]["windSpeed"]),
            "source": next(
                i["source"] for i in out["inputs"] if i["name"] == "wind, hour 0"
            ),
        }
    # Calm (HB-70 step 4): no held text gives a puff a calm treatment, so a wind of 0
    # releases nothing and the line says what would draw it; no floor is invented.
    if top_ms <= 0:
        if resolved:
            # Issue 473bdfeb's ruling (HB-139 item 3): a calm record is a true record;
            # the puff says what it needs, and no other wind replaces the record
            calm = cfg["wind_record"]["calm"]
            out["lines"].append(
                calm["puff"].format(
                    source=record["kind"], ms=float(calm["puff_needs_ms"])
                )
            )
        else:
            out["lines"].append(spec["calm_line"])
        out["calm"] = True
        return finish()
    thresholds, why = _thresholds(mat, mdata["air"], minutes)
    if why:
        return stop(why)
    for t in thresholds:
        out["inputs"].append(
            {
                "name": f"threshold {t['threshold']}",
                "value": t["as_printed"],
                "source": t["source"],
                "as_of": None,
                "sha256": None,
            }
        )
    # The ERG's downwind distance: Table 1 or 3's protective action distance, or, for a
    # material neither lists, its guide's large-spill downwind evacuation distance
    # (the footprint's `large_spill_downwind`; HB-67 RESULT section 3).
    zones = fp.get("zones") or {}
    erg_zone = next(
        (
            z
            for z in ("protective_action_zone", "large_spill_downwind")
            if ((zones.get(z) or {}).get("distance") or {}).get("metres")
        ),
        None,
    )
    if erg_zone is None:
        return stop("no ERG downwind distance to size the grid")
    pad = zones[erg_zone]["distance"]
    out["inputs"].append(
        {
            "name": "ERG downwind distance (sizes the grid)",
            "value": pad.get("text") or f"{pad['metres']} m",
            "source": erg_zone.replace("_", " "),
            "as_of": None,
            "sha256": None,
        }
    )
    # The release block (DN-018 ADDENDUM-00 section 3; HB-69): the quantity is given by
    # the scenario, never defaulted; a block without its sources is refused.
    from hazbrief.brief import release as R

    given, refused = R.parse(getattr(brief, "release", None))
    if refused:
        return stop(spec["release"]["refused"].format(why=refused))
    if given is None or given.quantity_kg is None:
        return stop(spec["release"]["not_given"])
    out["inputs"].append(
        {
            "name": "release quantity",
            "value": f"{given.quantity_kg:,.0f} kg",
            "source": given.quantity_source,
            "as_of": None,
            "sha256": None,
        }
    )
    if given.hole_diameter_m is not None:
        out["inputs"].append(
            {
                "name": "hole diameter",
                "value": f"{given.hole_diameter_m * 100:.1f} cm",
                "source": given.hole_source,
                "as_of": None,
                "sha256": None,
            }
        )
    spill = spill_shape(brief, fp)
    if spill is None:
        return stop("no spill point in the footprint")
    sx, sy = (
        (spill.x, spill.y)
        if spill.geom_type == "Point"
        else (spill.centroid.x, spill.centroid.y)
    )
    rdata = release.data.model_dump(mode="json")
    cdata = curves.data.model_dump(mode="json")
    window_s = float(spec["window_min"]) * 60.0
    g = puff_grid(
        cdata,
        cls,
        top_ms,
        window_s,
        float(pad["metres"]) * float(spec["grid_factor"]),
        spec,
    )
    half = g["half_width_m"]
    out["grid"] = {k: round(v, 1) if isinstance(v, float) else v for k, v in g.items()}
    out["assumptions"].append(
        spec["grid_line"].format(
            half=half,
            reach=g["reach_m"],
            travel=g["travel_m"],
            speed=g["speed_ms"],
            minutes=float(spec["window_min"]),
            k=float(spec["grid_sigma_multiple"]),
            spread=g["spread_m"],
            cls=cls,
            factor=float(spec["grid_factor"]),
            floor=g["floor_m"],
            cells=g["cells"],
            step=g["step_m"],
        )
    )
    if g["coarsened"]:
        out["assumptions"].append(
            spec["grid_coarsened_line"].format(
                needed=g["cells_needed"], cells=g["cells"], step=g["step_m"]
            )
        )
    import time

    from hazbrief.brief.puff import PuffError

    deadline = time.monotonic() + float(spec["timeout_s"])
    # The source term (HB-110 step 5; DN-020 section 3.1): where the container, the
    # quantity, the class and the properties give one, its rate and duration replace
    # the RMP worst case; where not, the worst case stays and a line says why.
    w0_ms, w0_from = wind_fn(0.0)
    source_env, st_why, st_rows, st_run = _source_term_envelope(
        brief, fp, derived, cfg, mdata, given, w0_ms, s
    )
    # what the dense-gas channel reads (HB-112): the same source term, the wind that
    # drove it at hour 0 and the words the puff's label names that wind with
    out["source_term_run"] = {
        **st_run,
        "release": given,
        "wind_ms": w0_ms,
        "wind_from_deg": w0_from,
        "wind_label": wind_label,
    }
    out["inputs"].extend(st_rows)
    if source_env is None:
        out["lines"].append(spec["source_term_envelope"]["not_used"].format(why=st_why))
    envs = list(_envelopes(rdata, given, un, spec, window_s, source_env))
    # HB-163 ADDENDUM-02 item 1 (DN-026 section 3; operator, 2026-11-11 10:58 EST: "We
    # should be letting the chemistry [and] the physics determine what engine should
    # be used"): the release's class by the held criterion. Only a passive release is
    # the puff's; a dense or unclassed one runs no puff (item 2), and the wind's angle
    # is kept for the modelled cloud's side lines (ADDENDUM-01 item 3)
    out["engine_rule"] = engine_rule_for(st_run, envs, mat, cls, cfg)
    if out["engine_rule"]["class"] != "passive":
        out["state"] = "not_run"
        out["lines"].append(
            spec["not_run_line"].format(line=out["engine_rule"]["line"])
        )
        out["uncertainty"] = uncertainty_angle(w0_ms, cls, cfg)
        out["class"] = cls
        out["wind_as_of"] = wind_as_of
        out["wind_label"] = wind_label
        # the ERG distance the dense-gas channel's comparison reads (HB-112 step 5)
        out["pad_m"] = float(pad["metres"])
        out["erg_distance"] = {
            "zone": erg_zone,
            "metres": float(pad["metres"]),
            "text": pad.get("text"),
        }
        return finish()
    for env in envs:
        if "reason" in env:
            out["envelopes"].append({**env, "contours": [], "extents_m": {}})
            out["lines"].append(
                spec["not_drawn"].format(what=f"{env['title']}: {env['reason']}")
            )
            continue
        try:
            run = run_puff(
                (sx, sy),
                env,
                thresholds,
                wind_fn,
                cdata,
                cls,
                half,
                spec,
                deadline=deadline,
                cells=g["cells"],
            )
        except PuffError as exc:
            # the channel degrades alone: its envelope is not drawn, nothing else moves
            why = (
                f"timed out after {spec['timeout_s']} s"
                if str(exc) == "timed out"
                else str(exc)
            )
            out["envelopes"].append(
                {**env, "reason": why, "contours": [], "extents_m": {}}
            )
            out["lines"].append(spec["not_drawn"].format(what=f"{env['title']}: {why}"))
            continue
        if run["at_grid_edge"]:
            out["lines"].append(
                spec["grid_edge_line"].format(
                    envelope=env["title"],
                    thresholds=", ".join(run["at_grid_edge"]),
                    half=half,
                )
            )
        if run["beyond_grid_minutes"]:
            out["lines"].append(
                spec["beyond_grid_line"].format(
                    envelope=env["title"],
                    minutes=", ".join(str(m) for m in run["beyond_grid_minutes"]),
                    half=half,
                )
            )
        if run["skipped_low_wind"]:
            out["lines"].append(
                spec["low_wind_line"].format(
                    n=run["skipped_low_wind"],
                    total=run["puffs"],
                    cut=spec["low_wind_ms"],
                )
            )
        out["envelopes"].append({**env, **run})
    out["label"] = spec["label"].format(
        engine=spec["engine"],
        version=out["version"],
        assumption="; ".join(
            e["assumption"] for e in out["envelopes"] if e.get("assumption")
        )
        or "no envelope drawn",
        wind=wind_label,
        **{"class": cls},
    )
    out["pad_m"] = float(pad["metres"])
    out["erg_distance"] = {
        "zone": erg_zone,
        "metres": float(pad["metres"]),
        "text": pad.get("text"),
    }
    out["grid_half_width_m"] = half
    out["wind_as_of"] = wind_as_of
    # what drove the puff, for every contour's properties (HB-75 step 4): one source,
    # or the window's sources in hour order where they differ
    seen = list(dict.fromkeys(w["wind_source"] for w in out["wind_hours"]))
    out["wind_source"] = ", ".join(seen)
    out["wind_station"] = (
        {"station_id": stand_in["station"], "observed_at": stand_in["observed_at"]}
        if stand_in is not None and "station_observation" in seen
        else None
    )
    out["class"] = cls
    out["sigma_source"] = spec["sigma_label"]
    # HB-157 (DN-024 sections 3.5 to 3.10): the steps from the as-given time, the
    # arrival bands, the uncertainty lines and the range, on the drawn primary envelope
    primary = next(
        (
            e
            for e in out["envelopes"]
            if e.get("name") in ("source_term", "worst_case")
            and "mass_kg" in e
            and "reason" not in e
        ),
        None,
    )
    if primary is not None:
        # DN-025 (HB-162R): the steps run to the horizon, so each puff is carried on the
        # forecast wind of every hour it travels, not only the window's hours; the grid
        # is sized by the largest of those hours' winds (DN-025 section 3 item 6)
        horizon_wind, horizon_top = wind_fn, top_ms
        if stated is None:
            last = int(math.ceil(float(spec["steps"]["horizon_h"])))
            later = [
                r
                for r in forecast.get("rows") or []
                if r.get("windSpeed") is not None
                and r.get("windDirection") is not None
                and int(r["hour"]) > max(int(x["hour"]) for x in rows)
                and int(r["hour"]) <= last
            ]
            horizon_wind = _wind_at(rows + later)
            horizon_top = max(r["windSpeed"] for r in rows + later) / 3.6
        # DN-025 section 3 item 5: the AEGL tiers the cloud is drawn by, read as
        # SCICHEM's request reads them (`scichem.tiers_from_pack`), at the steps'
        # level's averaging time; a class with no AEGL tier keeps HB-157's display
        tiers, tiers_reason = _puff_tiers(mdata, un, mat, thresholds)
        out["timeline"] = _timeline(
            brief,
            primary,
            thresholds,
            horizon_wind,
            cdata,
            cls,
            float(pad["metres"]) * float(spec["grid_factor"]),
            horizon_top,
            cfg,
            (sx, sy),
            held_kind if stated is not None else "forecast",
            forecast.get("rows") or [],
            record,
            tiers=tiers,
            tiers_reason=tiers_reason,
        )
        if stated is None:
            # each puff takes the wind of its release hour (the line above) and is then
            # carried on every later hour's (DN-025 section 3 item 1)
            out["assumptions"].append(spec["wind_follows_line"])
    return finish()


def _puff_tiers(mdata: dict, un: str, mat: dict, thresholds: list[dict]):
    """(the AEGL tiers, lowest concern first, at the steps' level's averaging time, as
    `scichem.Tier`s; None) or (None, why): DN-025 section 3 item 5. The tiers are read
    from the materials pack by the same function SCICHEM's request uses."""
    from hazbrief.brief import scichem as SC
    from hazbrief.brief import timeline as T

    try:
        minute = T.step_level(thresholds)["minute"]
    except T.TimelineError as exc:
        return None, str(exc)
    mw = (mat.get("molecular_weight_g_mol") or {}).get("value")
    if not mw or mat.get("dispersion_class") != "pressure_liquefied_toxic":
        return None, None
    sc = SC.load_config()
    try:
        return (
            SC.tiers_from_pack(
                mdata, un, float(minute), sc["record"]["tiers"], float(mw) / 1000.0, sc
            ),
            None,
        )
    except SC.Refusal as exc:
        return None, str(exc)


# ── the plume over time (HB-157; DN-024 sections 3.5 to 3.10) ─────────────────────────


def uncertainty_angle(u10: float, cls: str, cfg: dict) -> dict:
    """The wind-direction uncertainty lines' angle (HB-157 ADDENDA 03 to 05): U10, the
    wind at the release hour, reduced to 3 m by ALOHA's power law, then the held
    construction (`timeline.confidence_angle`). Shared by the puff's steps and, on a
    dense release, the modelled cloud's side lines (HB-163 ADDENDUM-01 item 3)."""
    from hazbrief.brief import timeline as T

    uspec = cfg["weather"]["puff"]["uncertainty"]
    try:
        n = cfg["weather"]["source_term"]["constants"]["power_law_n"]["rows"]
        u3 = T.u3_from_u10(u10, cls, n, uspec["ref_height_m"], uspec["to_height_m"])
        alpha = T.confidence_angle(u3, cls, uspec["table13"], uspec["seconds"])
        alpha["u10_ms"] = float(u10)
        alpha["n"] = float(n[cls])
        return {
            **{k: round(v, 3) if isinstance(v, float) else v for k, v in alpha.items()},
            "title": uspec["title"],
            "credit": uspec["credit"].format(
                alpha=alpha["alpha_deg"],
                x5=alpha["x5_m"],
                sy=alpha["sigma_y_m"],
                cls=cls,
                quote=uspec["quote"],
                u3=u3,
                u10=u10,
                n=f"{n[cls]:g}",
            ),
        }
    except T.TimelineError as exc:
        return {"reason": str(exc), "title": uspec["title"]}


def engine_rule_for(st_run: dict, envs: list[dict], mat: dict, cls: str, cfg: dict):
    """HB-163 ADDENDUM-02 item 1 (DN-026 section 3): the release's class by the held
    criterion (`engine_rule.classify`), from the release as computed: the source term
    where one ran (its mean rate, its release temperature and, for a two-phase release,
    its liquid fraction and the liquid's density; a pool by its largest diameter), else
    the EPA RMP worst case the puff would release (its rate, the material's vapour at
    the air temperature, a stated assumption). The wind, roughness and class are the
    source term's weather."""
    from hazbrief.brief import engine_rule as ER

    spec = cfg["weather"]["engine_rule"]
    res, met = st_run.get("result"), st_run.get("met")
    amb = getattr(met, "ambient", None)
    common = {
        "air_temperature_k": getattr(amb, "temperature_k", None),
        "wind_10m_ms": getattr(amb, "wind_ms", None),
        "z0_m": getattr(amb, "z0_m", None),
        "stability": getattr(amb, "stability", None) or cls,
    }
    if res is not None:
        r, m = res.result, res.material
        pool = r.get("model") == "evaporating pool"
        kind = (
            "puddle"
            if pool
            else ("instantaneous" if r.get("instantaneous") else "continuous")
        )
        rel = ER.Release(
            kind=kind,
            rate_kg_s=r.get("mean_rate_kg_s"),
            mw_kg_mol=m.mw_kg_mol,
            temperature_k=r.get(
                "pool_temperature_k" if pool else "source_temperature_k"
            ),
            liquid_fraction=0.0 if pool else float(r.get("aerosol_fraction") or 0.0),
            liquid_density_kg_m3=m.rhol_kg_m3,
            puddle_diameter_m=r.get("max_diameter_m") if pool else None,
            basis=spec["basis"]["source_term"].format(model=res.model),
            # HBD-464 (HB-206): a release floored to one minute is classed as one
            floored_from_s=r.get("computed_duration_s")
            if kind == "instantaneous"
            else None,
            **common,
        )
    else:
        wc = next(
            (
                e
                for e in envs
                if e.get("name") == "worst_case"
                and e.get("mass_kg")
                and e.get("duration_s")
                and "reason" not in e
            ),
            None,
        )
        mw = ((mat or {}).get("molecular_weight_g_mol") or {}).get("value")
        rel = ER.Release(
            kind="continuous" if wc else None,
            rate_kg_s=float(wc["mass_kg"]) / float(wc["duration_s"]) if wc else None,
            mw_kg_mol=float(mw) / 1000.0 if mw else None,
            temperature_k=common["air_temperature_k"],
            basis=spec["basis"]["worst_case"],
            **common,
        )
    out = ER.classify(rel, spec)
    out["line"] = spec["words"][out["class"]].format(
        ri=out["ri_c"] or 0.0,
        threshold=out["threshold"],
        missing="; ".join(out["missing"]),
    )
    if out.get("floored") and out["class"] != ER.NOT_DETERMINED:
        out["line"] += spec["words"]["floored"].format(
            seconds=out["floored_from_s"] or 0.0
        )
    return out


def hplus(minutes: int) -> str:
    """A step's time after release as the control prints it: "H+15 min", "H+1 h",
    "H+1 h 30 min"."""
    h, m = divmod(int(minutes), 60)
    if h == 0:
        return f"H+{m} min"
    return f"H+{h} h" + (f" {m} min" if m else "")


def _gj(g, c: Point) -> dict | None:
    if g is None or g.is_empty:
        return None
    geom = _unplane(g, c)
    return {
        "type": geom.geom_type,
        "coordinates": _round_coords(mapping(geom)["coordinates"]),
    }


def _clock(brief, minutes: int) -> str:
    """The step's clock time, in the brief's zone (SB-NUM-06)."""
    from datetime import timedelta

    from hazbrief.evidence import store as S

    as_given = getattr(brief, "as_given", None)
    if not as_given:
        return hplus(minutes)
    t = S.parse_time(as_given) + timedelta(minutes=int(minutes))
    return _when(t.isoformat(), getattr(brief, "time_zone", None))


def _timeline(
    brief,
    env: dict,
    thresholds: list[dict],
    wind_fn,
    cdata: dict,
    cls: str,
    floor_m: float,
    top_ms: float,
    cfg: dict,
    spill_xy: tuple[float, float],
    wind_kind: str,
    forecast_rows: list[dict],
    record: dict | None,
    tiers: list | None = None,
    tiers_reason: str | None = None,
) -> dict:
    """The steps, arrival bands, uncertainty lines, range and wind shift for the puff's
    primary envelope (DN-024 sections 3.5 to 3.10). A part that cannot be made carries
    its reason; the puff's own contours are never touched. `wind_fn` carries each puff
    on every hour it travels to the horizon (DN-025). With `tiers` (DN-025 section 3
    item 5) the run ends by the outermost tier and outlines every tier at every sample:
    `levels_run`, what `_puff_cloud` draws the cloud by level from."""
    import time

    from hazbrief.brief import timeline as T
    from hazbrief.brief.puff import PuffError

    spec = cfg["weather"]["puff"]
    tspec, rspec = spec["steps"], spec["range"]
    c = Point(*spill_xy)
    out: dict[str, Any] = {"reason": None}
    try:
        steps = T.step_minutes(tspec)
        level = T.step_level(thresholds)
    except T.TimelineError as exc:
        return {"reason": str(exc)}
    out["level"] = {k: level[k] for k in ("threshold", "as_printed", "source", "kg_m3")}
    out["level_line"] = tspec["level_line"].format(**level)
    out["horizon_h"] = float(tspec["horizon_h"])
    out["computed_on"] = _clock(brief, 0)
    # DN-025: a forecast-driven puff follows every hour's wind; a stated or observed
    # wind is one wind for every hour (HB-70 step 3; HB-143)
    out["one_wind"] = tspec[
        "follows_wind" if wind_kind == "forecast" else "one_wind"
    ].format(clock=out["computed_on"])
    levels = [(t.name, t.kg_m3) for t in tiers] if tiers else None

    def grid_for(top: float):
        def g(minutes: int) -> dict:
            return puff_grid(cdata, cls, top, minutes * 60.0, floor_m, spec)

        return g

    deadline = time.monotonic() + float(tspec["timeout_s"])
    try:
        run = T.run_steps(
            env,
            level["kg_m3"],
            wind_fn,
            cdata,
            cls,
            grid_for(top_ms),
            steps,
            spec,
            tspec,
            deadline,
            end_level=min(kg for _, kg in levels) if levels else None,
            levels=levels,
        )
    except (T.TimelineError, PuffError) as exc:
        return {**out, "reason": f"the steps were not run: {exc}"}
    out["end_minute"] = run.end_minute
    out["ended_by"] = run.ended_by
    out["end_line"] = tspec["end_lines"][run.ended_by].format(
        end=hplus(run.end_minute).removeprefix("H+"), horizon=f"{tspec['horizon_h']:g}"
    )
    out["grid"] = {
        "half_width_m": round(run.half_width_m, 1),
        "step_m": round(run.step_m, 1),
        "cells": int(run.xg.shape[0]),
    }
    # the wind of each step's hour, for the control's chip and the shift check
    by_hour = {
        int(r["hour"]): r for r in forecast_rows if r.get("windDirection") is not None
    }

    def step_wind(m: int) -> dict | None:
        if wind_kind != "forecast":
            s, frm = wind_fn(0.0)
            return {
                "from_deg": round(float(frm)),
                "kmh": round(s * 3.6, 1),
                "source": wind_kind,
            }
        h = min(m // 60, max(by_hour) if by_hour else 0)
        r = by_hour.get(h)
        if r is None:
            return None
        return {
            "from_deg": round(float(r["windDirection"])),
            "kmh": round(float(r["windSpeed"]), 1),
            "source": "forecast",
            "hour": h,
        }

    # the uncertainty lines' angle (ADDENDA 03 to 05): U10 is the wind the puff was
    # released on, reduced to 3 m by ALOHA's power law
    out["uncertainty"] = uncertainty_angle(wind_fn(0.0)[0], cls, cfg)
    # the range of plume paths (ADDENDUM-02 item 3): the low and high ends of the held
    # wind over the modelled time, with the central run
    variants, range_reason = [], None
    hours = list(range(0, run.end_minute // 60 + 1))
    if wind_kind == "stated":
        range_reason = rspec["stated"]
    elif wind_kind == "observed":
        sp = (record or {}).get("spread") or {}
        arc = sp.get("arc")
        if arc and sp.get("kmh_min") is not None:
            wr = {
                "from_lo": float(arc["from_deg"]),
                "from_hi": float(arc["to_deg"]),
                "kmh_lo": float(sp["kmh_min"]),
                "kmh_hi": float(sp["kmh_max"]),
                "hours": [0],
            }
        else:
            wr, range_reason = None, rspec["stated"]
    else:
        # DN-025: the central run follows the forecast hour by hour, so runs held on one
        # wind at the forecast's ends do not bound its path; the range is retired (T14)
        # and is not run for a forecast-driven puff
        wr, range_reason = None, rspec["follows"]
    if range_reason is None and wr is not None:
        out["range_what"] = rspec["what"].format(
            lo=wr["from_lo"],
            hi=wr["from_hi"],
            klo=wr["kmh_lo"],
            khi=wr["kmh_hi"],
            hours=", ".join(str(h) for h in wr["hours"]),
        )
        for frm in (wr["from_lo"], wr["from_hi"]):
            for kmh in (wr["kmh_lo"], wr["kmh_hi"]):
                if kmh > 0:
                    variants.append(_stated_wind_at(kmh / 3.6, frm))
        top = max(top_ms, wr["kmh_hi"] / 3.6)
        vruns = []
        try:
            for w in variants:
                vruns.append(
                    T.run_steps(
                        env,
                        level["kg_m3"],
                        w,
                        cdata,
                        cls,
                        grid_for(top),
                        steps,
                        spec,
                        {**tspec, "first_grid_min": run.end_minute},
                        deadline,
                        fixed_end=run.end_minute,
                    )
                )
        except (T.TimelineError, PuffError) as exc:
            range_reason, vruns = f"the range was not run: {exc}", []
    else:
        vruns = []
    out["range_reason"] = range_reason
    out["range_title"] = rspec["title"]
    shift = (
        T.wind_shift(forecast_rows, hours, spec["shift_limit_deg"])
        if wind_kind == "forecast"
        else None
    )
    if shift is not None:
        shift["clock"] = _clock(brief, shift["hour"] * 60)
        shift["item"] = spec["shift_item"].format(
            a=shift["from_deg"], b=shift["to_deg"], clock=shift["clock"]
        )
        shift["minute"] = next(
            (m for m in steps if m >= shift["hour"] * 60 and m <= run.end_minute), None
        )
    out["shift"] = shift
    rows = []
    for m in [s for s in steps if s <= run.end_minute]:
        f = run.snapshots[m]
        g = T.outline(f, run.xg, run.yg, level["kg_m3"], run.step_m, spec)
        ends = T.open_ends(g, run.half_width_m, run.step_m) if run.edge[m] else None
        lines = None
        alpha = out["uncertainty"] if "alpha_deg" in out["uncertainty"] else None
        if g is not None and alpha is not None:
            plus, minus = T.rotated(g, alpha["alpha_deg"])
            lines = [_gj(plus.boundary, c), _gj(minus.boundary, c)]
        rng = None
        if vruns and g is not None:
            parts = [g] + [
                T.outline(v.snapshots[m], v.xg, v.yg, level["kg_m3"], v.step_m, spec)
                for v in vruns
                if m in v.snapshots
            ]
            rng = unary_union([p for p in parts if p is not None])
        rows.append(
            {
                "minute": m,
                "hplus": hplus(m),
                "clock": _clock(brief, m),
                "wind": step_wind(m),
                "geometry": _gj(g, c),
                "open": ends is not None,
                "open_end": tspec["open_end"].format(
                    minutes=hplus(m).removeprefix("H+")
                )
                if ends is not None
                else None,
                "open_ends": _gj(ends, c),
                "reached": _gj(T.reached(run, m, spec), c),
                "lines": lines,
                "range": _gj(rng, c),
                "after_own_wind": m >= 60,
                "shift": bool(shift and shift.get("minute") == m),
            }
        )
    out["steps"] = rows
    # HB-163 ADDENDUM-01 item 3: the two lines bound the harm path (the area the steps
    # reached), not each step: no end-member outline moves with the time control
    last = next((r["reached"] for r in reversed(rows) if r.get("reached")), None)
    out["side_lines"] = _side_lines(
        shapely.make_valid(shape(last)) if last else None, out["uncertainty"], c
    )
    out["bands"] = [
        {
            "minute": m,
            "hplus": hplus(m),
            "clock": _clock(brief, m),
            "label": tspec["arrival_band"].format(
                label=hplus(m).removeprefix("H+"), clock=_clock(brief, m)
            ),
            "geometry": _gj(b, c),
        }
        for m, b in T.bands(run, steps, spec)
    ]
    out["arrival_title"] = tspec["arrival_title"].format(**level)
    out["step_title"] = tspec["step_title"].format(**level)
    if levels:
        out["levels_run"] = _levels_run(run, tiers, wind_fn, env, cls, cfg, c)
    elif tiers_reason:
        out["levels_reason"] = tiers_reason
    return out


def _levels_run(run, tiers: list, wind_fn, env: dict, cls: str, cfg: dict, c: Point):
    """DN-025 section 3 item 5: what the puff's run gives the cloud by level, in the
    shape `cloud.drawn` gives SCICHEM's record: per tier, its area at every sample and
    the area it reaches at any time (the outline of the run's running maximum at the
    end), whether it covers the spill at each sample, the side lines (section 3 item
    4), and the inputs that rebuild the run's puffs for the points (`_puff_places`)."""
    from hazbrief.brief import timeline as T

    spec = cfg["weather"]["puff"]
    names = [t.name for t in tiers]
    steps = []
    for m in sorted(run.samples):
        geoms = run.samples[m]
        steps.append(
            {
                "minute": int(m),
                "tiers": {n: _gj(geoms.get(n), c) for n in names},
                "area_km2": {
                    n: round(geoms[n].area / 1e6, 4) if geoms.get(n) else 0.0
                    for n in names
                },
                "contains_source": {n: bool(run.covers[m].get(n)) for n in names},
                "extent": None,
            }
        )
    path = {
        t.name: T.outline(run.peak, run.xg, run.yg, t.kg_m3, run.step_m, spec)
        for t in tiers
    }
    return {
        "tiers": [
            {"name": t.name, "ppm": t.ppm, "minutes": t.minutes, "receipt": t.receipt}
            for t in tiers
        ],
        "kg_m3": {t.name: t.kg_m3 for t in tiers},
        "steps": steps,
        "any_time": {n: _gj(path[n], c) for n in names},
        "side_lines": _puff_side_lines(
            run, path[names[0]], names[0], wind_fn, cls, cfg, c
        ),
        "end_minute": int(run.end_minute),
        "site": [float(c.x), float(c.y)],
        "run_inputs": {
            "mass_kg": float(env["mass_kg"]),
            "duration_s": float(env["duration_s"]),
            "wind": {
                "starts_s": list(wind_fn.starts_s),
                "speeds_ms": list(wind_fn.speeds_ms),
                "froms_deg": list(wind_fn.froms_deg),
            },
            "cls": cls,
        },
    }


def _puff_side_lines(run, path, outer: str, wind_fn, cls: str, cfg: dict, c: Point):
    """DN-025 section 3 item 4: the two wind-direction lines on each step's own wind.
    Each sample's outermost-tier area is rotated by plus and minus the angle the held
    construction gives on its hour's wind, and each line is the boundary of the union
    of its rotations; where every sample's hour gives one angle, the harm path itself is
    rotated, HB-163's form (`_side_lines`)."""
    from hazbrief.brief import timeline as T

    spec = cfg["weather"]["puff"]["uncertainty"]
    angles: dict[int, dict] = {}
    for m in sorted(run.samples):
        h = int(m) // 60
        if h not in angles:
            angles[h] = uncertainty_angle(wind_fn(h * 3600.0)[0], cls, cfg)
    first = angles[min(angles)] if angles else {"reason": "no step was run"}
    if path is None or any(not a.get("alpha_deg") for a in angles.values()):
        why = next((a.get("reason") for a in angles.values() if a.get("reason")), None)
        return {"tier": outer, "reason": why or "no area to draw them about"}
    distinct = {a["alpha_deg"] for a in angles.values()}
    if len(distinct) == 1:
        plus, minus = T.rotated(path, first["alpha_deg"])
    else:
        pp, mm = [], []
        for m in sorted(run.samples):
            g = run.samples[m].get(outer)
            if g is None:
                continue
            p, q = T.rotated(g, angles[int(m) // 60]["alpha_deg"])
            pp.append(p)
            mm.append(q)
        plus = shapely.make_valid(unary_union(pp))
        minus = shapely.make_valid(unary_union(mm))
    by_hour = ", ".join(
        spec["by_hour_item"].format(hour=h, alpha=a["alpha_deg"])
        for h, a in sorted(angles.items())
    )
    return {
        "tier": outer,
        "alpha_deg": first["alpha_deg"],
        "alpha_by_hour": {str(h): a["alpha_deg"] for h, a in sorted(angles.items())},
        "credit": first["credit"] + spec["by_step"].format(angles=by_hour),
        "lines": [_gj(plus.boundary, c), _gj(minus.boundary, c)],
    }


def _puff_cloud(brief, out: dict, cfg: dict) -> dict | None:
    """DN-025 section 3 item 5 (HB-162R ADDENDUM-02 item 3): a passive release's cloud
    by level, from the puff's run, in the shape `cloud.drawn` gives SCICHEM's record,
    so the level layers, Animate, the times row and the roadblock colours read it
    through HB-163's code. None where the puff drew no level run (the reason is the
    timeline's `levels_reason`, or HB-157's display stands)."""
    from datetime import UTC, timedelta

    from hazbrief.evidence import store as S

    p = out.get("puff") or {}
    tl = p.get("timeline") or {}
    lr = tl.get("levels_run")
    if not lr or not getattr(brief, "as_given", None):
        return None
    spec = cfg["weather"]["puff"]
    site = lr["site"]
    as_given = S.parse_time(brief.as_given)
    wind = lr["run_inputs"]["wind"]
    met = [
        {
            "time": (as_given + timedelta(seconds=s)).astimezone(UTC).isoformat(),
            "speed_m_s": v,
            "direction_deg": f,
        }
        for s, v, f in zip(wind["starts_s"], wind["speeds_ms"], wind["froms_deg"])
    ]
    reach = {}
    for t in lr["tiers"]:
        g = lr["any_time"].get(t["name"])
        if g:
            pts = shapely.get_coordinates(_plane(shape(g), Point(*site)))
            reach[t["name"]] = round(float(np.max(np.hypot(pts[:, 0], pts[:, 1]))))
    return {
        "reach_m": reach,
        "engine": spec["engine"],
        "engine_key": "puff",
        "state": "drawn",
        "reason": None,
        "record": p["evidence"]["sha256"],
        "record_a": p["evidence"]["sha256"],
        "engine_id": p.get("version"),
        "engine_kind": "puff",
        "site": {"lat": site[1], "lon": site[0]},
        "release_utc": as_given.astimezone(UTC).isoformat(),
        "release_minutes": round(lr["run_inputs"]["duration_s"] / 60.0, 3),
        "tiers": lr["tiers"],
        "steps": lr["steps"],
        "any_time": lr["any_time"],
        "any_time_extent": None,
        "places": [],
        "met": met,
        "inputs": p.get("inputs") or [],
        "assumptions": p.get("assumptions") or [],
        "cloud_left_domain": None,
        "engine_end_s": lr["end_minute"] * 60,
        "side_lines": lr["side_lines"],
    }


def _puff_places(brief, out: dict, cfg: dict) -> None:
    """DN-025 section 3 item 5: each drawn point's arrival, minutes above and clear
    from the puff's own field, at the receptor height its areas are drawn at, every
    `points.interval_s`; recorded as SCICHEM's points are (`scichem.place_record`, its
    variance zero: the puff gives none). The puff's field does not depend on the
    points, so the cordons and the suggested points placed on its area are measured
    with the rest (no second request, HB-163 ADDENDUM-06 item 4's reason)."""
    from hazbrief import packs as P
    from hazbrief.brief import cloud as CL
    from hazbrief.brief import puff as engine
    from hazbrief.brief import scichem as SC

    cl = out.get("cloud") or {}
    lr = ((out.get("puff") or {}).get("timeline") or {}).get("levels_run")
    if cl.get("engine_key") != "puff" or not lr:
        return
    spec = cfg["weather"]["puff"]
    sc = SC.load_config()
    pts = CL.places(brief, out, cfg, sc)
    if not pts:
        return
    ri = lr["run_inputs"]
    wind = engine.HourlyWind(**ri["wind"])
    puffs = engine.release(
        ri["mass_kg"], ri["duration_s"], float(spec["puff_dt_s"]), wind
    )
    curves = P.load_app_pack("sigma_curves").data.model_dump(mode="json")
    site = Point(cl["site"]["lon"], cl["site"]["lat"])
    xy = [_plane(Point(pl.lon, pl.lat), site) for pl in pts]
    xs = np.array([q.x for q in xy])
    ys = np.array([q.y for q in xy])
    dt = float(spec["points"]["interval_s"])
    end_s = lr["end_minute"] * 60.0
    times = [dt * k for k in range(1, int(end_s // dt) + 1)]
    series = np.zeros((len(times), len(pts)))
    for i, t in enumerate(times):
        series[i], _ = engine.field(
            puffs,
            t,
            xs,
            ys,
            curves,
            ri["cls"],
            z_m=float(spec["receptor_height_m"]),
            z0_m=float(spec["release_height_m"]),
            lifetime_s=end_s + float(spec["puff_dt_s"]),
            low_wind_ms=float(spec["low_wind_ms"]),
        )
    tiers = [{**t, "kg_m3": lr["kg_m3"][t["name"]]} for t in lr["tiers"]]
    meta = {"site": cl["site"]}
    keep = (
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
    recs = [
        SC.place_record(
            pl.as_dict(),
            times,
            [float(v) for v in series[:, j]],
            [0.0] * len(times),
            dt,
            tiers,
            meta,
        )
        for j, pl in enumerate(pts)
    ]
    cl["places"] = [{k: r.get(k) for k in keep} for r in recs]


# ── the release route (HB-120; DN-020 ADDENDUM-02 section 2 items 3 and 4) ────────────


def _release_route(fp: dict, inputs: list):
    """The routing table's decision for the footprint's guide and the material's storage
    state (`hazbrief.brief.routing.modelled_route`), with the pack named in `inputs`
    (C2); None where the pack cannot be read. A guide the table does not hold is not
    swallowed: it is a not-available decision whose reason is the error."""
    from hazbrief import packs as P
    from hazbrief.brief import routing as RT

    try:
        table, pack = RT.load_table()
    except P.PackError:
        return None
    inputs.append(
        {
            "name": "pack release_routing",
            "value": pack.version,
            "source": "packs/release_routing.json",
            "as_of": pack.built_at,
            "sha256": pack.sha256,
        }
    )
    try:
        return RT.modelled_route(table, fp)
    except RT.RoutingError as exc:
        return RT.Decision("not_available", None, None, None, reason=str(exc))


# ── the dense-gas footprint (DN-020 sections 3.3 and 3.4; HB-112) ─────────────────────


def _puff_extent(puff_out: dict, prefix: str) -> tuple[float | None, str | None]:
    """The puff's farthest extent at the class's threshold (any contour minute) on the
    envelope drawn in the worst case's place (the source term where it exists), and
    which contour it is; (None, None) where the puff drew no such envelope."""
    envs = {e.get("name"): e for e in puff_out.get("envelopes") or []}
    env = envs.get("source_term") or envs.get("worst_case")
    if env is None or "extents_m" not in env:
        return None, None
    hits = [
        (v, k) for k, v in (env.get("extents_m") or {}).items() if k.startswith(prefix)
    ]
    if not hits:
        return None, None
    v, k = max(hits)
    return float(v), f"{env.get('title')}, {k}"


def _comparison(
    puff_out: dict, spec: dict, class_id: str, dense_m: float | None, props: dict
) -> dict:
    """The comparison DN-020 section 3.4 asks for (HB-112 step 5): the ERG's protective
    action distance, the puff's extent at the class's threshold, and the dense-gas
    footprint's downwind extent (None where it is not drawn), each modelled extent over
    the ERG's; a dense-gas extent past SLAB's last row makes its ratio a lower bound."""
    from hazbrief.brief import dense_gas as DG

    erg = puff_out.get("erg_distance") or {}
    erg_m = erg.get("metres")
    puff_m, puff_at = _puff_extent(
        puff_out, spec["classes"][class_id]["puff_threshold"]
    )
    beyond = bool(props.get("beyond_table"))
    cmp_ = {
        "erg_m": erg_m,
        "erg_zone": erg.get("zone"),
        "puff_m": puff_m,
        "puff_at": puff_at,
        "dense_m": dense_m,
        "dense_beyond_table": beyond,
        "dense_beyond_width": bool(props.get("beyond_width")),
        "puff_ratio": DG.ratio_text(puff_m, erg_m, False),
        "dense_ratio": DG.ratio_text(dense_m, erg_m, beyond),
    }
    cmp_["line"] = spec["comparison_line"].format(
        erg=erg_m or 0.0,
        puff=DG.reach_text(puff_m, False, spec),
        puff_at=puff_at or "no contour at the class's threshold",
        dense=DG.reach_text(dense_m, beyond, spec),
        puff_ratio=cmp_["puff_ratio"],
        dense_ratio=cmp_["dense_ratio"],
    )
    return cmp_


def dense_gas(brief, fp: dict, derived: dict, cfg: dict, *, replay: bool) -> dict:
    """The dense-gas channel for one brief (HB-112; DN-020 sections 3.3 and 3.4): the
    source term the puff computed (the same one, DN-020 section 3.4), on the wind that
    drove the puff at hour 0, through SLAB (`hazbrief.brief.dense_gas`) to a footprint
    at the DN-001 class's level of concern, with DN-020 section 3.3's label, the
    comparison with the ERG and the puff, and its run record (C2).

    It degrades alone (C3): a missing input, an unbuilt image, an unrecorded run or a
    threshold not held is the layer's one line, and nothing else on the brief moves.
    Replaying, the run is read from `recordings_dir` and SLAB is never started unless
    HAZBRIEF_SLAB_RECORD is set; live, SLAB runs and the record is written into the
    brief's evidence store."""
    import hashlib

    from hazbrief import packs as P
    from hazbrief.brief import dense_gas as DG
    from hazbrief.brief import settings as AS
    from hazbrief.config import REPO_ROOT

    spec = cfg["weather"]["dense_gas"]
    out: dict[str, Any] = {
        "engine": "SLAB",
        "class": None,
        "legend": None,
        "level": None,
        "footprint": None,
        "reason": None,
        "hint": None,
        "label": None,
        "label_lines": [],
        "inputs": [],
        "tier_sentence": None,
        "comparison": None,
        "engine_kind": None,
        "engine_id": None,
        "route": None,
        # HB-120: the modelled tier's state (DN-020 ADDENDUM-02 item 4) and the routing
        # table's decision. `route` above stays the engine's route (slabx or the
        # container); the release route is its own key (HB-120 ADDENDUM-01 section 2).
        "state": None,
        "release_route": None,
    }
    record: dict[str, Any] = {"deck": None, "output": None}

    def finish():
        if out["state"] is None:
            out["state"] = "drawn" if out["footprint"] else "not_available"
        rec = {
            "engine": out["engine"],
            "engine_kind": out["engine_kind"],
            "engine_id": out["engine_id"],
            "route": out["route"],
            "state": out["state"],
            "release_route": out["release_route"],
            "class": out["class"],
            "level": out["level"],
            "reason": out["reason"],
            "inputs": out["inputs"],
            "source_term": record.get("source_term"),
            "deck": record["deck"],
            # HB-157 item 6: every XFFM SLAB was run to, the last the drawn one's
            "max_distance_m": record.get("max_distance_m"),
            "output_sha256": (
                hashlib.sha256(record["output"].encode("latin-1")).hexdigest()
                if record["output"]
                else None
            ),
            "footprint": (out["footprint"] or {}).get("properties"),
        }
        text = json.dumps(rec, sort_keys=True, separators=(",", ":"))
        out["evidence"] = {
            "record": rec,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }
        if not replay and record["output"] and getattr(brief, "stores", None):
            # live: the record, with SLAB's output file, into the brief's store (C2)
            from hazbrief.evidence import store as S

            S.write_entity(Path(brief.stores[0]), {**rec, "output": record["output"]})
        return out

    def stop(what: str, hint: str | None = None):
        out["reason"] = what
        out["hint"] = hint
        return finish()

    # The release route first, from the guide and the storage state (HB-120; DN-020
    # ADDENDUM-02 item 3), before any input, properties pack or source term is read
    # (ADDENDUM-01 section 2): "not applicable" is the chemistry, and ends here.
    un = str((fp.get("material") or {}).get("un_number") or "")
    out["un"] = un or None
    decision = _release_route(fp, out["inputs"])
    if decision is None:
        return stop("the release routing table is unavailable", None)
    out["release_route"] = decision.as_dict()
    if decision.status == "not_applicable":
        out["state"] = "not_applicable"
        out["reason"] = decision.reason
        return finish()
    for need in spec["needs"]:
        if not derived.get(need):
            return stop(f"its input {need} is not derived")
    if decision.status == "not_available":
        return stop(decision.reason)
    from hazbrief.brief import routing as RT

    # the class the routing table names; for the four DN-001 classes it is the
    # footprint's own class_id (tests/test_release_routing.py holds that)
    class_id = RT.class_key(decision, spec["loc_class_keys"])
    out["class"] = class_id
    try:
        mats = P.load_app_pack("materials_properties")
    except P.PackError as exc:
        return stop(f"the materials pack is unavailable ({exc})")
    mdata = mats.data.model_dump(mode="json")
    out["inputs"].append(
        {
            "name": "pack materials_properties",
            "value": mats.version,
            "source": "packs/materials_properties.json",
            "as_of": mats.built_at,
            "sha256": mats.sha256,
        }
    )
    loc = DG.class_level_of_concern(mdata, un, class_id, spec)
    if loc.level is None:
        return stop(loc.error, loc.hint)
    level = loc.level.as_dict()
    out["level"] = level
    legend = level["legend"]
    if (spec["classes"][class_id]["loc_kind"]) == "lfl_fraction":
        legend = f"{legend}; {spec['flammable_clause']}"
    out["legend"] = legend
    puff_out = derived["puff"]
    # the ERG and the puff beside it even where this layer is not drawn (HB-112 step 5)
    out["comparison"] = _comparison(puff_out, spec, class_id, None, {})
    st_run = puff_out.get("source_term_run")
    resolved = getattr(brief, "wind_resolved", False)
    calm_rec = getattr(brief, "wind_record", None) if resolved else None
    if st_run is None and puff_out.get("calm") and calm_rec is not None:
        # Issue 473bdfeb's ruling (HB-139 item 3): SLAB names the speed it needs
        calm = cfg["wind_record"]["calm"]
        return stop(
            calm["dense_gas"].format(
                source=calm_rec["kind"], ms=float(calm["puff_needs_ms"])
            )
        )
    if st_run is None:
        lines = "; ".join(
            line.removeprefix("Puff not drawn: ")
            for line in puff_out.get("lines") or []
        )
        return stop(
            f"no source term: the puff stopped before computing one ({lines})",
            spec["hints"]["source_term"],
        )
    result, release = st_run["result"], st_run["release"]
    if result is not None:
        record["source_term"] = {
            "model": result.model,
            **{k: v for k, v in result.result.items() if k != "series"},
            "assumptions": result.assumptions,
            "inputs": result.inputs,
            "notes": list(result.material.notes),
        }
        out["tier_rows"] = DG.tier_rows(result.material, spec)
        out["tier_sentence"] = DG.model_test_sentence(result.material, spec)
    spill = spill_shape(brief, fp)
    if spill is None:
        return stop("no spill point in the footprint")
    c = spill if spill.geom_type == "Point" else spill.centroid
    toward = (float(st_run["wind_from_deg"]) + 180.0) % 360.0
    if replay:
        runner = DG.recorded_runner(
            REPO_ROOT / spec["recordings_dir"], spec, record=AS.slab_record()
        )
    else:
        runner = None
    # HB-157 item 6 (DN-024 section 3.1): a drawn band still above its level at SLAB's
    # last row is not cut there. SLAB runs again with XFFM times `max_distance_factor`,
    # up to `max_distance_ceiling_m`; a band still open at the ceiling is drawn open.
    # The run's domain is sized to the modelled time (task item 6): never past the
    # distance SLAB's wind carries the cloud over the steps' horizon, nor the ceiling
    xffm = float(spec["max_distance_m"])
    horizon_s = float(cfg["weather"]["puff"]["steps"]["horizon_h"]) * 3600.0
    stable = stable_treatment(derived)
    time_bound = None
    if stable:
        # HB-189 (DN-028 ADDENDUM-14 decision 5, amending ADDENDUM-12 decision 1):
        # under the stable treatment SLAB checks how far within the time the brief
        # covers: its run is carried until its lowest level closes or its rows pass the
        # release hour's wind's travel in the horizon times `time_bound_factor`, and its
        # area is drawn and counted to the nearer of the two. The run bound (not a held
        # value) still stops the loop in code
        time_bound = (
            float(st_run["wind_ms"])
            * horizon_s
            * float(spec["stable_run"]["time_bound_factor"])
        )
        # XFFM keeps doubling (so the held runs at 10, 20, 40 and 80 km are reused); the
        # loop stops once a run's rows reach the time bound, and the bands are cut there
        ceiling = float(spec["stable_run"]["ceiling_m"])
        spec = {**spec, "draw_to_m": time_bound}
    else:
        ceiling = min(
            float(spec["max_distance_ceiling_m"]), float(st_run["wind_ms"]) * horizon_s
        )
        spec = {**spec, "draw_to_m": ceiling}
    tried = []
    while True:
        got = DG.model_footprint(
            (result, st_run["why"]),
            st_run["met"],
            pack=mdata,
            spec={**spec, "max_distance_m": xffm},
            lat=c.y,
            lon=c.x,
            toward_deg=toward,
            class_id=class_id,
            runner=runner,
        )
        tried.append(xffm)
        if got["footprint"] is None or xffm >= ceiling:
            break
        if time_bound is not None and xffm >= time_bound:
            break
        trial = dense_bands(
            got["output"],
            mdata,
            un,
            class_id,
            level,
            spec,
            lat=c.y,
            lon=c.x,
            toward_deg=toward,
            primary=got["footprint"],
        )
        if not any(b.get("beyond_table") for b in trial if b.get("geometry")):
            break
        xffm = min(xffm * float(spec["max_distance_factor"]), ceiling)
    record["max_distance_m"] = tried
    if stable:
        # HB-189: where time stops a level, the page says it is still open at the time
        # bound, the release hour's wind's travel in the horizon and 30 percent over
        out["time_bound_m"] = time_bound
        out["open_end_words"] = spec["stable_run"]["open_end"].format(
            km=time_bound / 1000.0,
            h=float(cfg["weather"]["puff"]["steps"]["horizon_h"])
            * float(spec["stable_run"]["time_bound_factor"]),
            horizon=f"{cfg['weather']['puff']['steps']['horizon_h']:g}",
            ms=float(st_run["wind_ms"]),
        )
    else:
        out["open_end_words"] = spec["open_end"].format(
            km=xffm / 1000.0, h=f"{cfg['weather']['puff']['steps']['horizon_h']:g}"
        )
    record["deck"], record["output"] = got["deck"], got["output"]
    if not replay and got["deck"] and got["output"]:
        # HB-207: kept for the two-engine record, which reads SLAB's output back
        DG.keep_live_output(got["deck"], got["output"])
    out.update(
        route=got["route"], engine_id=got["engine_id"], engine_kind=got["engine_kind"]
    )
    out["label_lines"] = got["label"]
    if got["footprint"] is None:
        p = got["problem"]
        return stop(p["error"], p["hint"])
    feat = got["footprint"]
    props = feat["properties"]
    container = st_run["scenario"].container
    out["label"] = DG.brief_label(
        result,
        storage_state=st_run["scenario"].storage_state,
        quantity_kg=release.quantity_kg,
        container=container,
        level=level,
        engine_kind=got["engine_kind"],
        engine_id=got["engine_id"],
        spec=spec,
    )
    out["footprint"] = feat
    out["wind"] = {
        "from_deg": float(st_run["wind_from_deg"]),
        "ms": float(st_run["wind_ms"]),
        "label": st_run["wind_label"],
    }
    # HB-133 ADDENDUM-01: the held levels of concern as nested bands through the same
    # SLAB output (no second run; the run record is unchanged)
    out["bands"] = dense_bands(
        record["output"],
        mdata,
        un,
        class_id,
        level,
        spec,
        lat=c.y,
        lon=c.x,
        toward_deg=toward,
        primary=feat,
    )
    out["comparison"] = _comparison(
        puff_out, spec, class_id, props["downwind_m"], props
    )
    # HB-157 ADDENDUM-05 item 4: the uncertainty lines around SLAB's outermost drawn
    # band, by the same Gaussian angle (the held construction's "width of the Guassian
    # plume", whatever engine drew the footprint) and SLAB's one wind
    unc = (puff_out.get("timeline") or {}).get("uncertainty") or {}
    outer = next((b for b in out["bands"] if b.get("geometry")), None)
    if unc.get("alpha_deg") and outer is not None:
        from hazbrief.brief import timeline as T

        plus, minus = T.rotated(_plane(shape(outer["geometry"]), c), unc["alpha_deg"])
        out["uncertainty_lines"] = {
            "tier": outer["tier"],
            "alpha_deg": unc["alpha_deg"],
            "lines": [_gj(plus.boundary, c), _gj(minus.boundary, c)],
        }
    return finish()


def slab_stable(met, spec: dict) -> bool:
    """Whether SLAB's deck for `met` takes a stable class (E or F): its STAB
    (`dense_gas.stab`, the guide's Table 1) is in `agreement.yaml reach.stable_stab`,
    the classes under which SLAB's area carries a brief's levels (DN-028 ADDENDUM-10
    decision 1) and its run is carried until its levels close (ADDENDUM-12 decision 1).
    False where no class is held: the deck itself then refuses."""
    amb = getattr(met, "ambient", None)
    letter = str(getattr(amb, "stability", "") or "").strip().upper()
    stab = spec["stab"].get(letter)
    if stab is None:
        return False
    return slab_stable_stab(stab)


def slab_stable_stab(stab: float) -> bool:
    """Whether SLAB's STAB is a stable class (`agreement.yaml reach.stable_stab`)."""
    from hazbrief.brief import agreement as AG

    return AG.is_stable({"stab": stab}, AG.load_config())


def dense_bands(
    output: str,
    mdata: dict,
    un: str,
    class_id: str,
    level: dict,
    spec: dict,
    *,
    lat: float,
    lon: float,
    toward_deg: float,
    primary: dict,
) -> list[dict]:
    """The dense-gas footprint's bands (HB-133 ADDENDUM-01 section 2): the contour of
    each held level of concern through SLAB's one output, read as the class level is
    (`dense_gas.footprint`: along the centreline and across the half-width, linear in
    log concentration), lowest concern (outermost) first. For a toxic class, every AEGL
    tier `dense_gas.bands.tiers` names that the pack holds at the class level's
    averaging time; otherwise the class level alone (one level held). A tier the cloud
    never reaches on the plane is a band with its reason and no geometry."""
    from hazbrief.brief import dense_gas as DG

    bands_spec = spec["bands"]
    cls = spec["classes"][class_id]
    one = {
        "tier": level["kind"],
        "ppm": level["ppm"],
        "minutes": level["minutes"],
        "receipt": level["source"],
        "geometry": primary["geometry"],
        "downwind_m": primary["properties"]["downwind_m"],
        "beyond_table": primary["properties"]["beyond_table"],
        "open_end": primary["properties"].get("open_end"),
        "primary": True,
        "reason": None,
    }
    if cls["loc_kind"] != "aegl2":
        return [one]
    cells = ((mdata.get("materials") or {}).get(un) or {}).get("aegl_ppm") or {}
    minutes = float(level["minutes"])
    out = []
    for tier in bands_spec["tiers"]:
        cell = (cells.get(tier) or {}).get(f"{minutes:g}") or {}
        if cell.get("status") != "held":
            continue
        rec = cell.get("receipt") or {}
        loc = DG.LevelOfConcern(
            kind=tier,
            ppm=float(cell["value"]),
            minutes=minutes,
            source=f'{rec.get("locator")}: "{rec.get("quote")}"',
            basis=bands_spec["basis"],
        )
        got = DG.footprint(
            output, loc, lat=lat, lon=lon, toward_deg=toward_deg, spec=spec
        )
        f = got.feature
        out.append(
            {
                "tier": tier,
                "ppm": loc.ppm,
                "minutes": minutes,
                "receipt": rec.get("locator"),
                "geometry": f["geometry"] if f else None,
                "downwind_m": f["properties"]["downwind_m"] if f else None,
                "beyond_table": f["properties"]["beyond_table"] if f else None,
                "open_end": f["properties"].get("open_end") if f else None,
                "primary": tier == bands_spec["primary_tier"],
                "reason": None if f else got.error,
            }
        )
    return out if any(b["geometry"] for b in out) else [one]


# ── gathering one brief's inputs (through the one upstream client) ────────────────────


@contextlib.contextmanager
def _replaying(replay: bool):
    """Serve only recorded exchanges while a replayed brief derives (the client's
    `replay` mode), whatever mode this process runs in; restored after."""
    if not replay:
        yield
        return
    held = settings.hazbrief_http_mode
    settings.hazbrief_http_mode = "replay"
    try:
        yield
    finally:
        settings.hazbrief_http_mode = held


def _bbox(geoms: list, margin_m: float = 0.0) -> str:
    g = unary_union(geoms)
    if margin_m:
        g = facilities.buffer(g, margin_m)
    w, s, e, n = g.bounds
    r = 10**COORDINATE_DECIMALS
    return (
        f"{math.floor(w * r) / r:.{COORDINATE_DECIMALS}f},"
        f"{math.floor(s * r) / r:.{COORDINATE_DECIMALS}f},"
        f"{math.ceil(e * r) / r:.{COORDINATE_DECIMALS}f},"
        f"{math.ceil(n * r) / r:.{COORDINATE_DECIMALS}f}"
    )


async def fetch_roads(footprint: dict, cfg: dict) -> list[Exchange]:
    """TIGERweb's roads of the configured classes in the footprint's extent, one query
    per configured layer. A truncated answer is refused (DeriveError)."""
    spec = cfg["derive"]["roads"]
    polys = [p for _, p in zone_polygons(footprint)]
    if not polys:
        return []
    classes = ",".join(f"'{c}'" for c in spec["classes"])
    out = []
    for layer in spec["layers"]:
        ex = await fetch_json(
            spec["api"],
            layer,
            {
                "where": f"MTFCC IN ({classes})",
                "outFields": spec["fields"],
                "returnGeometry": "true",
                "outSR": "4326",
                "f": "json",
                "geometry": _bbox(polys),
                "geometryType": "esriGeometryEnvelope",
                "inSR": "4326",
                "spatialRel": "esriSpatialRelIntersects",
            },
        )
        body = ex.body if isinstance(ex.body, dict) else {}
        if ex.status != 200 or "error" in body or "features" not in body:
            raise DeriveError(
                f"TIGERweb {layer} answered {ex.status}: {body.get('error')}"
            )
        if body.get("exceededTransferLimit"):
            raise DeriveError(f"TIGERweb {layer} returned a partial set")
        out.append(ex)
    return out


async def fetch_offset_roads(footprint: dict, cfg: dict) -> list[Exchange]:
    """HB-142R: TIGERweb's roads of the offset classes in the footprint's box grown by
    `offset.max_m`, one query per offset layer; a truncated answer is refused."""
    base = cfg["derive"]["roads"]
    spec = base["offset"]
    polys = [p for _, p in zone_polygons(footprint)]
    if not polys:
        return []
    classes = ",".join(f"'{c}'" for c in spec["classes"])
    out = []
    for layer in spec["layers"]:
        ex = await fetch_json(
            base["api"],
            layer,
            {
                "where": f"MTFCC IN ({classes})",
                "outFields": base["fields"],
                "returnGeometry": "true",
                "outSR": "4326",
                "f": "json",
                "geometry": _bbox(polys, float(spec["max_m"])),
                "geometryType": "esriGeometryEnvelope",
                "inSR": "4326",
                "spatialRel": "esriSpatialRelIntersects",
            },
        )
        _refuse_partial(ex, layer)
        out.append(ex)
    return out


async def fetch_offset_roads_tiled(
    outer, cfg: dict, deg: float
) -> tuple[list[dict], list[Exchange]]:
    """HB-186: `fetch_offset_roads` read by tiles: TIGERweb's roads of the offset
    classes in each tile of `deg` degrees (`block_tiles`) that touches the outer
    boundary grown by `offset.max_m`, one query per tile and offset layer, a truncated
    answer refused; each road line once (by layer and OID, the first tile's copy). A
    road the one box would hold within `max_m` of the boundary lies in some tile. Also
    the exchanges, the layer's sources."""
    from hazbrief import census

    base = cfg["derive"]["roads"]
    spec = base["offset"]
    near = facilities.buffer(outer.boundary, float(spec["max_m"]))
    classes = ",".join(f"'{c}'" for c in spec["classes"])
    out, seen, exchanges = [], set(), []
    for t in block_tiles(near, deg):
        for layer in spec["layers"]:
            ex = await fetch_json(
                base["api"],
                layer,
                {
                    "where": f"MTFCC IN ({classes})",
                    "outFields": base["fields"],
                    "returnGeometry": "true",
                    "outSR": "4326",
                    "f": "json",
                    "geometry": census.envelope(t),
                    "geometryType": "esriGeometryEnvelope",
                    "inSR": "4326",
                    "spatialRel": "esriSpatialRelIntersects",
                },
            )
            _refuse_partial(ex, layer)
            exchanges.append(ex)
            for f in ex.body["features"]:
                key = (layer, (f.get("attributes") or {}).get("OID"))
                if key in seen:
                    continue
                seen.add(key)
                out.append(f)
    return out, exchanges


async def _flowlines_in(bbox: str, cfg: dict) -> tuple[list[dict], list[str]]:
    """3DHP flowline features (GeoJSON) in `bbox`, paged, generalized as
    facilities_in_footprint reads them; and the exchanges' urls."""
    h = facilities.sources()["hydrography"]
    return await facilities.arcgis_features(
        h["api"],
        f"{h['service']}/{h['flowlines']['layer']}",
        bbox,
        cfg["derive"]["downstream"]["flowline_fields"],
        int(h["flowlines"].get("page_size", h["page_size"])),
        max_offset=float(h["max_allowable_offset_deg"]),
    )


class NldiUnanswered(Exception):
    """A live brief's NLDI call failed past its bounded wait; the message is the reason
    the label prints."""


async def _nldi_get(spec: dict, path: str, params: dict) -> Exchange:
    """One NLDI GET. Recording and replay call it as any upstream (a failure raises, so
    a recording's re-run retries it). A live brief bounds the wait (HB-58): the client's
    timeout once, a 5xx retried `live_retries_5xx` times, then `NldiUnanswered`."""
    if settings.hazbrief_http_mode != "live":
        return await fetch_json(spec["nldi_api"], path, params)
    tries = 1 + int(spec["live_retries_5xx"])
    for i in range(tries):
        try:
            return await fetch_json(spec["nldi_api"], path, params)
        except UpstreamTimeoutError:
            raise NldiUnanswered(
                f"NLDI did not answer in {settings.upstream_timeout_seconds:g} s"
            ) from None
        except UpstreamStatusError as exc:
            if exc.status < 500:
                raise NldiUnanswered(f"NLDI answered {exc.status}") from None
            if i + 1 == tries:
                raise NldiUnanswered(
                    f"NLDI answered {exc.status} on {tries} tries"
                ) from None
        except UpstreamServiceError:
            raise NldiUnanswered("NLDI's request failed") from None
    raise AssertionError("unreachable: the loop returns or raises")


async def fetch_nldi(snap: Point, cfg: dict) -> tuple[list[Exchange], str | None]:
    """NLDI's position answer at `snap` and, from its comid, the navigation answer: the
    exchanges, and why a live brief holds none (`_nldi_get`), else None."""
    spec, places = cfg["derive"]["downstream"], COORDINATE_DECIMALS
    try:
        pos = await _nldi_get(
            spec,
            spec["position"],
            {"coords": f"POINT({snap.x:.{places}f} {snap.y:.{places}f})"},
        )
        feats = (pos.body or {}).get("features") if isinstance(pos.body, dict) else None
        if pos.status != 200 or not feats:
            return [pos], None
        comid = int(feats[0]["properties"]["comid"])
        nav = await _nldi_get(
            spec,
            spec["navigation"].format(comid=comid),
            {"distance": f"{float(spec['length_km']):g}"},
        )
    except NldiUnanswered as exc:
        return [], str(exc)
    return [pos, nav], None


async def _rivers_along(
    start: dict, cut: Point, flowlines: list[dict], cfg: dict
) -> tuple[list[dict], list[str]]:
    """The 3DHP waterbody polygons of `width_types` over the first `along_km` of 3DHP's
    own path from `cut`, generalized as facilities_in_footprint reads them; and the
    exchanges' urls."""
    spec = cfg["derive"]["downstream"]
    h = facilities.sources()["hydrography"]
    chain = _3dhp_chain(start, flowlines)
    coords = list(_downstream_of(shape(chain[0]["geometry"]), cut).coords)
    for f in chain[1:]:
        coords += list(_single(shape(f["geometry"])).coords)
    ref = _plane(LineString(coords), cut)
    first = _unplane(
        substring(ref, 0, min(ref.length, float(spec["along_km"]) * 1000)), cut
    )
    types = ", ".join(f"'{t}'" for t in spec["width_types"])
    return await facilities.arcgis_features(
        h["api"],
        f"{h['service']}/{h['waterbodies']['layer']}",
        _bbox([first]),
        spec["width_fields"],
        int(h["waterbodies"].get("page_size", h["page_size"])),
        where=f"featuretypelabel IN ({types})",
        max_offset=float(h["max_allowable_offset_deg"]),
    )


@dataclass
class DownstreamInputs:
    """What `downstream_path` reads for one brief, and every answer read (`_source`)."""

    flowlines: list[dict]
    nldi: list[Exchange]
    rivers: list[dict]
    read: list[dict]
    nldi_why: str | None = None


async def fetch_downstream(spill, footprint: dict, cfg: dict) -> DownstreamInputs:
    """The 3DHP flowlines over the footprint and within D of the spill; then, from the
    nearest, NLDI's position and navigation answers (`fetch_nldi`); then the 3DHP
    flowlines along the path, to name its reaches, and the River polygons along 3DHP's
    own path, to measure the width `along_length` allows."""
    spec = cfg["derive"]["downstream"]
    near_d = facilities.buffer(spill, float(spec["nearest_flowline_m"]))
    h = facilities.sources()["hydrography"]["api"]
    flowlines, urls = await _flowlines_in(
        _bbox([near_d] + [p for _, p in zone_polygons(footprint)]), cfg
    )
    read = [_source(h, u) for u in urls]
    near = nearest_flowline(spill, flowlines, float(spec["nearest_flowline_m"]))
    if near is None:
        return DownstreamInputs(flowlines, [], [], read)
    nldi, why = await fetch_nldi(near[2], cfg)
    read += _sources(nldi)
    if len(nldi) < 2:
        return DownstreamInputs(flowlines, nldi, [], read, why)
    nav = nldi[1]
    nfeats = (nav.body or {}).get("features") if isinstance(nav.body, dict) else None
    if nav.status != 200 or not nfeats:
        return DownstreamInputs(flowlines, nldi, [], read)
    lines = [
        LineString(n["geometry"]["coordinates"])
        for n in nfeats
        if n.get("geometry", {}).get("type") == "LineString"
    ]
    if lines:
        more, urls = await _flowlines_in(_bbox(lines, float(spec["name_match_m"])), cfg)
        flowlines = flowlines + more
        read += [_source(h, u) for u in urls]
    cut = cut_point(spill, shape(near[0]["geometry"]), float(spec["along_step_m"]))
    rivers, urls = await _rivers_along(near[0], cut, flowlines, cfg)
    read += [_source(h, u) for u in urls]
    return DownstreamInputs(flowlines, nldi, rivers, read)


async def fetch_establishments(counties: list[str], cfg: dict) -> list[Exchange]:
    """CBP's two-digit sectors for each county (state FIPS + county FIPS), with the
    Census key (DN-003 section 1; the key never lands in a recorded file)."""
    from hazbrief.census import api_key

    spec = cfg["derive"]["establishments"]
    out = []
    for c in counties:
        out.append(
            await fetch_json(
                spec["api"],
                spec["dataset"],
                {
                    "get": spec["get"],
                    "for": f"county:{c[2:]}",
                    "in": f"state:{c[:2]}",
                    "INDLEVEL": spec["indlevel"],
                    "key": api_key(),
                },
            )
        )
    return out


def _samples_params(points: list) -> dict:
    """getSamples' query for `points`: a WGS84 multipoint, the first value only."""
    geom = {
        "points": [
            [
                float(f"{x:.{COORDINATE_DECIMALS}f}"),
                float(f"{y:.{COORDINATE_DECIMALS}f}"),
            ]
            for x, y in points
        ],
        "spatialReference": {"wkid": 4326},
    }
    return {
        "geometry": json.dumps(geom, separators=(",", ":")),
        "geometryType": "esriGeometryMultipoint",
        "returnFirstValueOnly": "true",
        "f": "json",
    }


def sample_chunks(points: list, cfg: dict) -> list[list]:
    """`points` in as few getSamples calls as fit `samples_max_url_chars`: one call
    unless the URL would pass the service's request-line limit."""
    import httpx

    spec = cfg["derive"]["terrain"]
    base = httpx.URL(settings.upstream_base_url(spec["samples_api"])).join(
        spec["samples_path"]
    )
    limit = int(spec["samples_max_url_chars"])

    def fits(ps):
        return len(str(base.copy_merge_params(_samples_params(ps)))) <= limit

    out, cur = [], []
    for p in points:
        if cur and not fits(cur + [p]):
            out.append(cur)
            cur = []
        if not fits([p]):
            raise DeriveError("one getSamples point does not fit the URL limit")
        cur.append(p)
    return out + ([cur] if cur else [])


async def _epqs(points: list, spec: dict) -> list[Exchange]:
    out = []
    for x, y in points:
        out.append(
            await fetch_json(
                spec["epqs_api"],
                spec["epqs_path"],
                {
                    "x": f"{x:.{COORDINATE_DECIMALS}f}",
                    "y": f"{y:.{COORDINATE_DECIMALS}f}",
                    "wkid": "4326",
                    "units": "Meters",
                    "includeDate": "false",
                },
            )
        )
    return out


async def _samples(points: list, cfg: dict) -> list[Exchange]:
    """3DEP getSamples for `points`, refusing an answer that is not one sample per
    point (an ArcGIS error object answers HTTP 200)."""
    spec = cfg["derive"]["terrain"]
    out = []
    for chunk in sample_chunks(points, cfg):
        ex = await fetch_json(
            spec["samples_api"], spec["samples_path"], _samples_params(chunk)
        )
        body = ex.body if isinstance(ex.body, dict) else {}
        if ex.status != 200 or len(body.get("samples") or []) != len(chunk):
            raise DeriveError(
                f"3DEP getSamples answered {ex.status} with "
                f"{len(body.get('samples') or [])} of {len(chunk)} samples"
                + (f" ({body['error'].get('message')})" if "error" in body else "")
            )
        out.append(ex)
    return out


async def fetch_terrain(
    footprint: dict, cfg: dict, path: dict | None = None
) -> tuple[list, str | None]:
    """Elevation at every terrain point (`terrain_points`) and the downstream path's
    vertices, one 3DEP getSamples call per set (the spill, the zone boundaries, the
    path); a set getSamples fails for is read from EPQS one point at a time. Returns
    the elevation exchanges and why EPQS was read, or None. A recording missing in
    replay is not a failure: it raises, as every replayed answer does."""
    spec = cfg["derive"]["terrain"]
    pts = terrain_points(footprint, cfg)
    sets = {
        "the spill": [pts["spill"]] if pts["spill"] else [],
        "the zone boundaries": list(
            dict.fromkeys(p for ps in pts["zones"].values() for p in ps)
        ),
        "the downstream path": path_points(path),
    }
    elevation, why = [], []
    for name, points in sets.items():
        if not points:
            continue
        try:
            elevation += await _samples(points, cfg)
        except UnrecordedExchangeError:
            raise
        except (DeriveError, UpstreamServiceError) as exc:
            why.append(f"{name}: {_why(exc)}")
            elevation += await _epqs(points, spec)
    return elevation, "; ".join(why) or None


@dataclass
class CoverRead:
    """What `fetch_cover` read: the exchanges, the image's grid and the decoded tiles,
    keyed (tile column, tile row)."""

    exchanges: list[Exchange]
    grid: cog.Grid
    tiles: dict


def _cover_tiles(grid: cog.Grid, footprint: dict, cfg: dict, path) -> set:
    """The tiles the land cover needs: every tile under the footprint's extent (the
    class mix), and the tile of the spill and of each downstream path vertex."""
    want: set = set()
    polys = [p for _, p in zone_polygons(footprint)]
    if polys:
        want |= grid.tiles_over(*unary_union(polys).bounds)
    spill = terrain_points(footprint, cfg)["spill"]
    for x, y in ([spill] if spill else []) + path_points(path):
        cell = grid.cell(x, y)
        if cell:
            want.add(grid.tile_of(*cell))
    return want


async def fetch_cover(
    footprint: dict, cfg: dict, path: dict | None = None
) -> CoverRead:
    """Land cover from the Annual NLCD COG mirror by HTTP range (HB-59 ADDENDUM-03):
    the file's head, then for each row of tiles the run of its TileOffsets and
    TileByteCounts entries, then the tiles, adjacent ones in one read up to
    `cover_max_read_bytes`. Read apart from the elevation, so that one service failing
    leaves the other's answer standing (HB-60)."""
    spec = cfg["derive"]["terrain"]
    api = spec["cover_api"]
    file = spec["cover_path"].format(vintage=spec["cover_vintage"])
    head = await fetch_range(api, file, 0, int(spec["cover_head_bytes"]) - 1)
    exchanges = [head]
    try:
        grid = cog.parse_header(head.body)
    except cog.CogError as exc:
        raise DeriveError(f"land cover: {exc}") from None
    rows: dict[int, list[int]] = {}
    for tcol, trow in _cover_tiles(grid, footprint, cfg, path):
        rows.setdefault(trow, []).append(tcol)
    blank = np.full((grid.tile_h, grid.tile_w), grid.nodata or 0, dtype=np.uint8)
    tiles: dict = {}
    cap = int(spec["cover_max_read_bytes"])
    for trow, cols in sorted(rows.items()):
        cols.sort()
        first, last = grid.tile_index(cols[0], trow), grid.tile_index(cols[-1], trow)
        span = []
        for at in (grid.offsets_at, grid.counts_at):
            ex = await fetch_range(
                api,
                file,
                at + first * grid.entry_size,
                at + (last + 1) * grid.entry_size - 1,
            )
            exchanges.append(ex)
            span.append(cog.entries_of(grid, ex.body))
        offsets, counts = span
        # Runs of adjacent tiles stored back to back, each read in one range.
        runs: list[list[int]] = []
        for tcol in cols:
            k = tcol - cols[0]
            if counts[k] == 0:  # a sparse tile holds no data (OGC 21-026)
                tiles[(tcol, trow)] = blank
                continue
            if runs:
                prev = runs[-1]
                k0, kp = prev[0] - cols[0], prev[-1] - cols[0]
                if (
                    tcol == prev[-1] + 1
                    and offsets[k] == offsets[kp] + counts[kp]
                    and offsets[k] + counts[k] - offsets[k0] <= cap
                ):
                    prev.append(tcol)
                    continue
            runs.append([tcol])
        for run in runs:
            k0, kp = run[0] - cols[0], run[-1] - cols[0]
            ex = await fetch_range(api, file, offsets[k0], offsets[kp] + counts[kp] - 1)
            exchanges.append(ex)
            for tcol in run:
                k = tcol - cols[0]
                start = offsets[k] - offsets[k0]
                try:
                    tiles[(tcol, trow)] = cog.decode_tile(
                        grid, ex.body[start : start + counts[k]]
                    )
                except cog.CogError as exc:
                    raise DeriveError(f"land cover: {exc}") from None
    return CoverRead(exchanges, grid, tiles)


def _class_rows(weights: dict, names: dict) -> list[dict]:
    total = sum(weights.values())
    return [
        {"code": code, "name": names.get(code), "share": w / total}
        for code, w in sorted(weights.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def land_cover(read: CoverRead, footprint: dict, cfg: dict, path=None) -> dict:
    """The class at the spill, the class mix over the footprint and the classes at the
    downstream path's vertices, from the tiles `fetch_cover` read. A cell holding the
    file's no-data value is counted as not answered, never as a class."""
    spec = cfg["derive"]["terrain"]
    names = spec["nlcd_classes"]
    g, tiles = read.grid, read.tiles

    def at(x: float, y: float) -> int | None:
        cell = g.cell(x, y)
        if cell is None:
            return None
        tile = tiles.get(g.tile_of(*cell))
        if tile is None:
            return None
        v = int(tile[cell[1] % g.tile_h, cell[0] % g.tile_w])
        return None if v == g.nodata else v

    spill = terrain_points(footprint, cfg)["spill"]
    code = at(*spill) if spill else None
    point = None if code is None else {"code": code, "name": names.get(code)}

    mix = None
    polys = [p for _, p in zone_polygons(footprint)]
    if polys:
        union = unary_union(polys)
        shapely.prepare(union)
        weights: dict = {}
        cells = no_data = 0
        for (tcol, trow), tile in tiles.items():
            xs, ys = g.centres(tcol, trow)
            lon, lat = np.meshgrid(xs, ys)
            inside = shapely.contains_xy(union, lon, lat)
            if not inside.any():
                continue
            vals, w = tile[inside], np.cos(np.radians(lat[inside]))
            cells += int(inside.sum())
            gone = vals == g.nodata
            no_data += int(gone.sum())
            for c in np.unique(vals[~gone]):
                weights[int(c)] = weights.get(int(c), 0.0) + float(w[vals == c].sum())
        mix = {
            "rows": _class_rows(weights, names) if weights else [],
            "cells": cells,
            "no_data": no_data,
        }

    along = None
    vertices = path_points(path)
    if vertices:
        counts: dict = {}
        for x, y in vertices:
            v = at(x, y)
            if v is not None:
                counts[v] = counts.get(v, 0) + 1
        along = {
            "vertices": len(vertices),
            "answered": sum(counts.values()),
            "rows": _class_rows(counts, names) if counts else [],
        }
    vintage = spec["cover_vintage"]
    return {
        "point": point,
        "mix": mix,
        "path": along,
        "vintage": vintage,
        "label": spec["cover_label"].format(vintage=vintage),
        "point_note": spec["cover_point_note"],
        "weighting": spec["cover_mix_weighting"],
    }


def spill_shape(brief, footprint: dict):
    """The spill's shape: the derived location's own shape (a line, a point) when the
    scenario gave one, else the footprint's spill point."""
    if brief.location and brief.location.get("shape"):
        return shape(brief.location["shape"])
    for f in (footprint.get("footprint") or {}).get("features") or []:
        if f["properties"].get("zone") == "spill":
            return shape(f["geometry"])
    return None


def _source(api: str, url: str, retrieved: str | None = None) -> dict:
    """One answer a derivation read: its api, url, recorded-exchange key and when it was
    retrieved (read from its recorded file when the caller has only the url)."""
    key = exchange_key("GET", url)
    if retrieved is None:
        f = exchange_file(api, key)
        if f.is_file():
            retrieved = json.loads(f.read_text(encoding="utf-8")).get("recorded_at")
    return {"api": api, "url": url, "key": key, "retrieved": retrieved}


def _sources(exchanges: list[Exchange]) -> list[dict]:
    """What a derivation read: each exchange's url, key and when it was retrieved."""
    return [_source(e.api, e.url, e.recorded_at) for e in exchanges]


async def run(brief, cfg: dict, *, replay: bool) -> dict:
    """The three derivations for one brief, with what each read. A derivation whose
    input the brief does not hold (the footprint unavailable, an exchange not recorded,
    a service error) carries the reason and nothing to draw."""
    from hazbrief.brief import layers

    c = layers._Ctx(brief, cfg)
    fp = c.payload("protective_action_footprint")
    out: dict[str, Any] = {}
    if fp is None:
        why = c.why_not("protective_action_footprint")
        none = {
            "roads": {"candidates": [], "reason": why, "sources": []},
            "rail": {"candidates": [], "reason": why, "sources": []},
            "downstream": {"path": None, "reaches": [], "reason": why, "sources": []},
            "workplaces": {"jobs": {}, "reason": why},
            "establishments": {"rows": [], "reason": why, "sources": []},
            "terrain": {"zones": {}, "reason": why, "sources": []},
            "forecast": {"rows": [], "reason": why, "sources": []},
            "radar": {"held": False, "reason": why, "sources": []},
            "satellite": {"held": False, "reason": why, "sources": []},
            "wind_field": {"cells": [], "reason": why, "sources": []},
            "snapshots": {},
            "observation": {"station": None, "usable": False, "reason": why},
            "stability": {"class": None, "inputs": [], "reason": why},
            "puff": {
                "envelopes": [],
                "lines": [f"Puff not drawn: {why}"],
                "inputs": [],
            },
            "dense_gas": {"footprint": None, "reason": why, "inputs": []},
            "nearby": {"classes": {}, "reason": why, "sources": []},
            "modelled_population": {"absent": True, "reason": why, "sources": []},
            "modelled_cordons": {"candidates": [], "reason": why, "sources": []},
            "siting": {"points": {}, "reason": why, "routes": [], "sources": []},
        }
        # HB-129: a fire brief keeps its smoke layer's refusal lines without a footprint
        # (the brush fire), so the inputs it lacks are named, not hidden
        smoke = _smoke(brief, None, none, cfg)
        return none if smoke is None else {**none, "smoke": smoke}
    with _replaying(replay):
        try:
            road_ex = await fetch_roads(fp, cfg)
            roads = [f for e in road_ex for f in e.body["features"]]
            out["roads"] = roadblock_candidates(fp, roads, cfg)
            out["roads"]["sources"] = _sources(road_ex)
        except (DeriveError, UpstreamServiceError) as exc:
            out["roads"] = {"candidates": [], "reason": _why(exc), "sources": []}
        # HB-142R items 4 and 5: every entering road, each candidate offset outward;
        # where that query is not held, the crossings above stay, with the reason
        try:
            off_ex = await fetch_offset_roads(fp, cfg)
            off = offset_candidates(
                fp, [f for e in off_ex for f in e.body["features"]], cfg
            )
            off["sources"] = _sources(off_ex)
            out["roads"] = off
        except (DeriveError, UpstreamServiceError) as exc:
            out["roads"]["offset_reason"] = _why(exc)
        out["nearby"] = await _nearby(c, brief, fp, cfg)
        if c.ok("facilities_in_footprint"):
            rail = [
                f
                for f, _ in layers._exchange_features(
                    c, "facilities_in_footprint", "bts_ntad", "Rail_Network_Lines"
                )
            ]
            out["rail"] = rail_candidates(fp, rail, cfg)
            out["rail"]["sources"] = []
        else:
            out["rail"] = {
                "candidates": [],
                "reason": c.why_not("facilities_in_footprint"),
                "sources": [],
            }
        spill = spill_shape(brief, fp)
        try:
            got = await fetch_downstream(spill, fp, cfg)
            out["downstream"] = downstream_path(
                spill, got.flowlines, got.nldi, cfg, fp, got.rivers, got.nldi_why
            )
            out["downstream"]["sources"] = got.read
        except (DeriveError, UpstreamServiceError) as exc:
            out["downstream"] = {
                "path": None,
                "reaches": [],
                "reason": _why(exc),
                "sources": [],
            }
        out.update(
            await _hb55(c, fp, spill, cfg, (out["downstream"] or {}).get("path"))
        )
        wx, grid = await _hb56(c, fp, spill, cfg, replay=replay)
        out.update(wx)
        out.update(await _hb103(c, fp, grid, out, cfg, replay=replay))
        out["observation"] = await _hb60(c, spill, cfg)
        # HB-139: a stated weather source's class in place of the computed one
        out["stability"] = stated_stability(
            brief, _hb57(brief, fp, spill, out["forecast"], cfg, out["observation"])
        )
        # HB-189 (DN-028 ADDENDUM-14 decision 2): the class at every hour of the
        # horizon; any stable hour gives the stable treatment
        out["stability_hours"] = stability_hours(brief, spill, grid, out, cfg)
    out["puff"] = puff(brief, fp, out, cfg)
    out["dense_gas"] = dense_gas(brief, fp, out, cfg, replay=replay)
    # HB-163 ADDENDA 02, 03 and 06 (DN-026, DN-028): the release's class decides the
    # engine; a dense release's cloud is SCICHEM's held record, read in two requests so
    # the cordons and the suggested points placed on its area are in the record drawn
    out["engine_rule"] = (out["puff"] or {}).get("engine_rule")
    # HB-189 (DN-028 ADDENDUM-14 decision 4): the engine runs on a worker thread, so a
    # live page can send each hour (`scichem.HOUR_SINK`) while it runs
    rec_a = await asyncio.to_thread(_cloud_a, brief, fp, out, grid, cfg, replay=replay)
    # HB-157 items 7 and 8 (DN-024 sections 3.2 and 3.3): the population under the
    # union of the drawn modelled layers, and the cordons on the outer boundary of
    # every drawn hazard layer, read once the modelled layers exist
    with _replaying(replay):
        out["modelled_population"] = await modelled_population(c, fp, out, cfg)
        out["modelled_cordons"] = await modelled_cordons(fp, out, cfg)
        # HB-155: the suggested points, from stage one and every drawn hazard layer
        # (ADDENDUM-04 item 1), before the brief is presented (ADDENDUM-05 item 6)
        try:
            out["siting"] = await _siting(c, brief, fp, out, cfg)
        except (DeriveError, UpstreamServiceError) as exc:
            out["siting"] = {
                "points": {},
                "reason": _why(exc),
                "routes": [],
                "sources": [],
            }
    if rec_a is not None:
        with _no_hour_sink():
            _cloud_b(brief, fp, out, grid, cfg, rec_a, replay=replay)
    else:
        _puff_places(brief, out, cfg)
    smoke = _smoke(brief, fp, out, cfg)
    if smoke is not None:
        out["smoke"] = smoke
    return out


@contextlib.contextmanager
def _no_hour_sink():
    """HB-189: the hours a live page is sent are request A's, the first run of the
    moving cloud; the lines run and request B (the same cloud, more sensors) send
    none."""
    from hazbrief.brief import scichem as SC

    token = SC.HOUR_SINK.set(None)
    try:
        yield
    finally:
        SC.HOUR_SINK.reset(token)


def _cloud_a(brief, fp: dict, out: dict, grid, cfg: dict, *, replay: bool):
    """HB-163: the modelled cloud's first request (A, every point but those placed on
    the cloud) for a dense release, its drawn form into `out["cloud"]` so the cordons
    and the siting read its area; the record, or None where nothing more is read (a
    passive release, an unclassed one, a refusal)."""
    from hazbrief.brief import cloud as CL
    from hazbrief.brief import scichem as SC

    rule = out.get("engine_rule")
    if rule is None:
        return None
    sc = SC.load_config()
    if rule["class"] == "not_determined":
        out["cloud"] = CL.refused(rule["line"], sc, unclassed=True)
        return None
    if rule["class"] != "dense":
        # DN-025 section 3 item 5: a passive release's cloud by level is the puff's
        # run, drawn through the same code; its points are measured once the cordons
        # and the suggested points are placed (`_puff_places`)
        cl = _puff_cloud(brief, out, cfg)
        if cl is not None:
            out["cloud"] = cl
        return None
    try:
        if grid is None or grid.status != 200:
            raise SC.Refusal(
                sc["refusals"]["missing"].format(detail="the NWS gridpoint forecast")
            )
        # HB-133's one wind: SCICHEM's record reads the NWS forecast hour by hour
        # (DN-028 decision 3); a brief whose one wind record is stated or observed is
        # not driven by it, so the engine refuses rather than draw on another wind
        rec_w = getattr(brief, "wind_record", None)
        if getattr(brief, "wind_resolved", False) and rec_w is not None:
            if rec_w.get("kind") != "forecast":
                raise SC.Refusal(
                    sc["refusals"]["one_wind"].format(kind=rec_w.get("kind"))
                )
        pts = CL.places(brief, out, cfg, sc, leave_out=CL.PLACED_ON_THE_CLOUD)
        req_a = CL.request(brief, fp, out, grid.body, cfg, sc, pts)
        rec = CL.read(req_a, sc, replay=replay, frames=CL.frames_spec(req_a, sc, cfg))
        if CL.hour1_late(rec, sc):
            # HB-189 (DN-028 ADDENDUM-14 decision 4): a run at the stable setting whose
            # first hour came past its ceiling is a finding; the brief is built at the
            # fallback setting and says so
            out["vertical_fallback"] = {
                "from_m": float(sc["project"]["stable_vertical"]["vres_m"]),
                "hour1_s": (rec.get("hours") or [{}])[0].get("engine_wall_s"),
            }
            req_a = CL.request(brief, fp, out, grid.body, cfg, sc, pts)
            rec = CL.read(
                req_a, sc, replay=replay, frames=CL.frames_spec(req_a, sc, cfg)
            )
    except SC.Refusal as exc:
        out["cloud"] = CL.refused(str(exc), sc)
        return None
    if rec.get("state") != "modelled":
        out["cloud"] = CL.refused(rec.get("reason") or "not modelled", sc)
        return None
    out["cloud"] = CL.drawn(rec, rec["request_sha256"], sc, cfg)
    _cloud_side_lines(out)
    _agreement(brief, fp, out, grid, cfg, rec, sc, replay=replay)
    return rec


def _agreement(brief, fp, out: dict, grid, cfg: dict, rec: dict, sc: dict, *, replay):
    """HB-173 (DN-028 ADDENDUM-04): the second engine beside the drawn cloud. The lines
    run of the same release is read (or, in record mode, run) and the agreement record
    built: the measure, the reaches per level, the inputs the two requests do not
    share and, under a stable class, the planning shape. Request A's record is used:
    its areas and inputs are request B's (`cloud.same_steps`)."""
    from hazbrief.brief import agreement as AG
    from hazbrief.brief import cloud as CL
    from hazbrief.brief import scichem as SC

    acfg = AG.load_config()
    lines_rec, why = None, None
    try:
        lreq = CL.request(brief, fp, out, grid.body, cfg, sc, [], lines=acfg["lines"])
        with _no_hour_sink():
            lines_rec = AG.lines_recorded(lreq, sc, acfg, record=CL.record_mode(replay))
    except SC.Refusal as exc:
        why = str(exc)
    out["agreement"] = AG.build(
        rec,
        lines_rec,
        why,
        out["cloud"],
        out.get("dense_gas") or {},
        acfg,
        int(cfg["map"]["coord_places"]),
        treatment=out.get("stability_hours"),
    )


def _side_lines(area, unc: dict, c0: Point) -> dict:
    """HB-163 ADDENDUM-01 item 3: the two wind-direction lines about a harm path (an
    area in longitude and latitude), the held construction's rotation by the angle
    either side of the wind about the source `c0`; the reason where no angle was
    computed."""
    from hazbrief.brief import timeline as T

    if not unc.get("alpha_deg") or area is None or area.is_empty:
        return {"reason": unc.get("reason") or "no area to draw them about"}
    plus, minus = T.rotated(_plane(area, c0), unc["alpha_deg"])
    return {
        "alpha_deg": unc["alpha_deg"],
        "credit": unc["credit"],
        "lines": [_gj(plus.boundary, c0), _gj(minus.boundary, c0)],
    }


def _cloud_side_lines(out: dict) -> None:
    """The side lines about the cloud's outermost level reached at any time, on the
    angle the puff channel computed from the release hour's wind (HB-163 ADDENDUM-06
    item 1: they stay on a dense release, the forecast wind's treatment, HBD-379)."""
    cl = out["cloud"]
    outer = cl["tiers"][0]["name"]
    g = cl["any_time"].get(outer)
    unc = (out.get("puff") or {}).get("uncertainty") or {}
    area = shapely.make_valid(shape(g)) if g else None
    c0 = Point(cl["site"]["lon"], cl["site"]["lat"])
    cl["side_lines"] = {"tier": outer, **_side_lines(area, unc, c0)}


def _cloud_b(brief, fp: dict, out: dict, grid, cfg: dict, rec_a: dict, *, replay):
    """HB-163 ADDENDUM-06 item 4 (c): the record the brief draws, with every point; its
    step areas must equal request A's (`cloud.CloudError` otherwise)."""
    from hazbrief.brief import cloud as CL
    from hazbrief.brief import scichem as SC

    sc = SC.load_config()
    try:
        pts = CL.places(brief, out, cfg, sc)
        rec = CL.read(
            CL.request(brief, fp, out, grid.body, cfg, sc, pts), sc, replay=replay
        )
    except SC.Refusal as exc:
        out["cloud"] = CL.refused(str(exc), sc)
        return
    if rec.get("state") != "modelled":
        out["cloud"] = CL.refused(rec.get("reason") or "not modelled", sc)
        return
    if not CL.same_steps(rec_a, rec):
        raise CL.CloudError(
            f"request B ({rec['request_sha256'][:12]}) draws other areas than "
            f"request A ({rec_a['request_sha256'][:12]})"
        )
    out["cloud"] = CL.drawn(rec, rec_a["request_sha256"], sc, cfg)
    _cloud_side_lines(out)


def planning_carries(derived: dict) -> bool:
    """Whether the planning areas are the brief's level areas: the stable treatment
    (DN-028 ADDENDUM-14 decisions 2 and 6; `agreement.build` sets `levels`)."""
    ag = derived.get("agreement") or {}
    return ag.get("levels") == "planning" and bool(ag.get("planning"))


def action_levels(cfg: dict) -> list[str]:
    """The levels counts, named places and candidate blocks are stated for under the
    stable treatment (`derive.modelled.action_levels`; DN-028 ADDENDUM-14
    decision 7)."""
    return list(cfg["derive"]["modelled"]["action_levels"])


def cloud_part_area(derived: dict, tiers: list[str] | None = None):
    """The moving cloud's part of the planning area (the levels `tiers`, or every
    level, together; longitude and latitude) under the stable treatment (DN-028
    ADDENDUM-14 decision 6), or None."""
    if not planning_carries(derived):
        return None
    plan = (derived.get("agreement") or {}).get("planning") or {}
    gs = [
        shapely.make_valid(shape(p["cloud"]))
        for t, p in plan.items()
        if p.get("cloud") and (tiers is None or t in tiers)
    ]
    return shapely.make_valid(unary_union(gs)) if gs else None


def drawn_hazards(
    fp: dict, derived: dict, cfg: dict, *, what: str = "carried"
) -> list[tuple[str, str, Any]]:
    """(id, words, shape in longitude and latitude) of every drawn hazard layer: the ERG
    zones, then each modelled outline (the puff's drawn contours, the area its steps
    reached, the dense-gas bands), in the words the inner-cordon mark names them by
    (`derive.modelled.names`). `what` says which modelled outlines of a dense release:

    - "carried" (the inner-cordon marks, the blocks a level count reads): the areas
      that carry the brief's levels: SCICHEM's cloud, or under the stable treatment
      each level's planning area, the moving cloud's together with SLAB's extent check
      (DN-028 ADDENDUM-14 decision 6);
    - "action" (the headline count and the candidate blocks): as "carried", but under
      the stable treatment the planning areas at the action levels alone
      (`derive.modelled.action_levels`, AEGL-3 and AEGL-2; ADDENDUM-14 decisions 7 to
      9); the same as "carried" elsewhere;
    - "cloud" (the siting): SCICHEM's cloud alone, whatever carries the levels (DN-028
      ADDENDUM-04 decision 5, unchanged by ADDENDUM-10);
    - "read" (the blocks the population reads): every modelled outline drawn, the cloud
      and the planning areas, so a block under any drawn layer is held."""
    if what not in ("carried", "action", "cloud", "read"):
        raise ValueError(f"drawn_hazards: what={what!r}")
    action = set(action_levels(cfg))
    names = cfg["derive"]["modelled"]["names"]
    out = [(z, names[z], g) for z, g in zone_polygons(fp) if z != "modelled_boundary"]
    # HB-163 ADDENDUM-02 item 2: a release the rule does not class passive is drawn by
    # one engine, the modelled cloud; nothing derived from the puff or SLAB is a hazard
    # layer then, and the cordons, the siting and the population read the cloud alone
    rule = derived.get("engine_rule") or {}
    cl = derived.get("cloud") or {}
    if cl.get("state") == "drawn":
        slab = planning_carries(derived)
        if what in ("cloud", "read") or not slab:
            for t in cl["tiers"]:
                g = cl["any_time"].get(t["name"])
                if g:
                    out.append(
                        (
                            f"cloud_{t['name']}",
                            names["cloud"].format(tier=t["name"]),
                            shapely.make_valid(shape(g)),
                        )
                    )
        # HB-173 (HBD-390; DN-028 ADDENDUM-04 decision 5), as DN-028 ADDENDUM-14
        # decisions 6 to 9 amend it: under the stable treatment each level's planning
        # area (the moving cloud's together with SLAB's extent check) is a drawn hazard
        # and carries the level; the headline count and the candidate blocks read the
        # action levels' areas; the siting reads the cloud alone; every time comes from
        # the cloud
        plan = (
            (derived.get("agreement") or {}).get("planning")
            if what in ("carried", "action", "read")
            else None
        )
        for t, p in (plan or {}).items():
            if what == "action" and t not in action:
                continue
            out.append(
                (
                    f"planning_{t}",
                    names["planning"].format(tier=t),
                    shapely.make_valid(shape(p["geometry"])),
                )
            )
    if rule.get("class") in ("dense", "not_determined"):
        return out
    p = derived.get("puff") or {}
    for e in p.get("envelopes") or []:
        if e.get("name") not in ("source_term", "worst_case"):
            continue
        gs = [shape(ct["geometry"]) for ct in e.get("contours") or []]
        if gs:
            out.append(("puff", names["puff"], shapely.make_valid(unary_union(gs))))
    tl = p.get("timeline") or {}
    reached = [shape(s["reached"]) for s in tl.get("steps") or [] if s.get("reached")]
    # DN-025 section 3 item 5: where the puff's cloud is drawn by level, its levels are
    # the time layers drawn (above); HB-157's arrival bands are not
    if reached and cl.get("state") != "drawn":
        out.append(("arrival_bands", names["arrival_bands"], reached[-1]))
    # a passive release draws no dense-gas layer (HB-163 ADDENDUM-02 item 2)
    dense = [] if rule.get("class") == "passive" else derived.get("dense_gas") or {}
    for b in (dense or {}).get("bands") or []:
        if b.get("geometry"):
            out.append(
                (
                    f"dense_gas_{b['tier']}",
                    names["dense_gas"].format(tier=b["tier"]),
                    shape(b["geometry"]),
                )
            )
    return out


def modelled_area(fp: dict, derived: dict, cfg: dict, *, what: str = "carried"):
    """The union of the drawn modelled outlines (longitude, latitude) `drawn_hazards`
    names for `what`, or None."""
    gs = [g for k, _, g in drawn_hazards(fp, derived, cfg, what=what) if k not in ZONES]
    return shapely.make_valid(unary_union(gs)) if gs else None


def _outer(g):
    """`g` without its holes: the outer boundary a cordon guards."""
    parts = list(g.geoms) if hasattr(g, "geoms") else [g]
    polys = [shapely.Polygon(p.exterior) for p in parts if p.geom_type == "Polygon"]
    return unary_union(polys) if polys else None


def inner_marks(cands: list[dict], hazards: list, cfg: dict) -> None:
    """HB-157 item 8: a candidate inside a drawn hazard layer other than the one it
    guards is kept and marked "inside the <layer>; inner cordon, protective equipment
    required" (`inside`, `inner`); drawn muted by the map."""
    words = cfg["derive"]["modelled"]["inner"]
    for c in cands:
        pt = Point(c["coordinates"])
        inside = [w for k, w, g in hazards if k != c.get("zone") and g.contains(pt)]
        if inside:
            c["inside"] = inside
            c["inner"] = words.format(layer="; ".join(inside))


async def modelled_cordons(fp: dict, derived: dict, cfg: dict) -> dict:
    """HB-157 item 8 (DN-024 section 3.3): roadblock candidates on the outer boundary of
    the union of every drawn hazard layer, by HB-142R's offset rule, each labelled with
    the boundary it guards; a crossing within `merge_m` of an ERG zone's own boundary is
    left to that zone's candidate. Every candidate on the brief (these and the ERG
    zones') is then marked where it lies inside another drawn hazard layer.

    HB-189 (DN-028 ADDENDUM-14 decision 9): under the stable treatment they are
    candidate blocks on the action levels' planning area's boundary only (AEGL-3 and
    AEGL-2, `action_levels`), never along the AEGL-1 band, and the marks read the same
    areas; elsewhere "action" is every drawn hazard layer, as before."""
    spec = cfg["derive"]["modelled"]
    hazards = drawn_hazards(fp, derived, cfg, what="action")
    stable = planning_carries(derived)
    inner_marks((derived.get("roads") or {}).get("candidates") or [], hazards, cfg)
    empty = {"candidates": [], "sources": []}
    if not any(k not in ZONES for k, _, _ in hazards):
        return {**empty, "reason": spec["absent"]}
    outer = _outer(shapely.make_valid(unary_union([g for _, _, g in hazards])))
    erg = [g for k, _, g in hazards if k in ZONES]
    pseudo = {
        "footprint": {
            "features": [
                {
                    "type": "Feature",
                    "geometry": mapping(outer),
                    "properties": {"zone": "modelled_boundary"},
                }
            ]
        }
    }
    try:
        if planning_carries(derived):
            # HB-186 (DN-028 ADDENDUM-12 decision 4): the planning area's boundary can
            # run 350 km, whose one box answers past the client's response cap; it is
            # read by the tiles along it
            feats, ex = await fetch_offset_roads_tiled(
                outer, cfg, float(spec["block_tile_deg"])
            )
        else:
            ex = await fetch_offset_roads(pseudo, cfg)
            feats = [f for e in ex for f in e.body["features"]]
    except (DeriveError, UpstreamServiceError) as exc:
        return {**empty, "reason": _why(exc)}
    got = offset_candidates(pseudo, feats, cfg)
    c0 = outer.centroid
    merge = float(cfg["derive"]["roads"]["merge_m"])
    keep = []
    for cand in got["candidates"]:
        x = Point(cand["crossing"])
        if any(_metres(x, g.boundary, c0) <= merge for g in erg):
            continue
        cand["guards"] = spec["guards_stable" if stable else "guards"]
        keep.append(cand)
    inner_marks(keep, hazards, cfg)
    # HB-178: a dropped cordon an ERG zone's candidate stands for is that zone's
    got["dropped"] = [
        g
        for g in got.get("dropped") or []
        if not any(_metres(Point(g["crossing"]), e.boundary, c0) <= merge for e in erg)
    ]
    reason = got["reason"]
    if not keep and reason is None:
        reason = spec["none_beyond"]
    return {
        **got,
        "candidates": keep,
        "label": spec["cordon_label_stable" if stable else "cordon_label"],
        "reason": reason,
        "sources": _sources(ex),
    }


def block_tiles(area, deg: float) -> list:
    """The squares of `deg` degrees, on a grid anchored at 0, 0, that intersect `area`
    (longitude and latitude), west to east and south to north: the same area always
    gives the same tiles, so each query's URL (and its recorded exchange) is stable."""
    from shapely.geometry import box

    w, s, e, n = area.bounds
    out = []
    for i in range(math.floor(w / deg), math.ceil(e / deg)):
        for j in range(math.floor(s / deg), math.ceil(n / deg)):
            t = box(i * deg, j * deg, (i + 1) * deg, (j + 1) * deg)
            if t.intersects(area):
                out.append(t)
    return out


async def tiled_blocks(area, deg: float) -> tuple[list, list]:
    """Every TIGERweb 2020 block intersecting the tiles of `deg` degrees that touch
    `area` (`block_tiles`), one paged query per tile (`census._tigerweb_features`, its
    page cap per tile), each block once (the first tile's copy); and the exchanges'
    urls. A block intersecting the area intersects some tile, so none is missed."""
    from hazbrief import census

    feats, urls, seen = [], [], set()
    for t in block_tiles(area, deg):
        got, u = await census._tigerweb_features("block", census.envelope(t))
        urls += u
        for f in got:
            gid = str((f.get("properties") or {}).get("GEOID"))
            if gid in seen:
                continue
            seen.add(gid)
            feats.append(f)
    return feats, urls


async def modelled_population(c, fp: dict, derived: dict, cfg: dict) -> dict:
    """HB-157 item 7 (DN-024 section 3.2): residents and workers under the union of the
    drawn modelled layers, read as the population tool reads them (TIGERweb 2020 blocks,
    DHC 2020 P1, each block by its area share; LODES workplace jobs where held), never
    merged with the ERG figure; and the residents under the area each step has reached.
    Absent, not zero, where no modelled layer is drawn."""
    from hazbrief import census, geo, lodes
    from hazbrief.census import CensusKeyMissing, Unit
    from hazbrief.tools import population_at_risk as PT
    from hazbrief.utils import PageCapExceeded

    spec = cfg["derive"]["modelled"]
    area = modelled_area(fp, derived, cfg)
    if area is None:
        return {"absent": True, "reason": spec["absent"], "sources": []}
    # the ERG figures beside it, like for like: the tool's residents (DHC) and workers
    erg_pop = c.payload("population_at_risk") or {}
    out: dict[str, Any] = {
        "absent": False,
        "area_km2": round(geo.geodesic_area_m2(area) / 1e6, 3),
        "erg_residents": (erg_pop.get("nighttime") or {}).get("total"),
        "erg_workers": (erg_pop.get("daytime") or {}).get("workers"),
        "engines": [
            w
            for k, w, _ in drawn_hazards(fp, derived, cfg, what="action")
            if k not in ZONES
        ],
    }
    # DN-028 ADDENDUM-10 decision 1: the blocks are read under every modelled layer
    # drawn (under a stable class SCICHEM's cloud is still drawn) and counted under the
    # layers that carry the levels; elsewhere the two areas are one
    read = modelled_area(fp, derived, cfg, what="read") or area
    try:
        if planning_carries(derived):
            # HB-186 (DN-028 ADDENDUM-12 decision 4): under a stable class the planning
            # area can run past 100 km on a diagonal, whose bounding box holds more
            # blocks than one query's cap; it is read by the tiles that touch it
            feats, urls = await tiled_blocks(read, float(spec["block_tile_deg"]))
        else:
            feats, urls = await census._tigerweb_features(
                "block", census.envelope(read)
            )
        blocks, geoms = [], {}
        for f in feats:
            g = f.get("geometry")
            if not g:
                continue
            gs = geo.shape(g)
            share, kind = geo.area_share(gs, area)
            if kind is None:
                continue
            p = f.get("properties") or {}
            u = Unit(
                level="block",
                geoid=str(p["GEOID"]),
                share=share,
                kind=kind,
                state=str(p["STATE"]),
                county=str(p["COUNTY"]),
                tract=str(p["TRACT"]),
            )
            blocks.append(u)
            geoms[u.geoid] = (g, gs)
        dhc = await census.dhc_blocks(blocks) if blocks else {}
    except (
        DeriveError,
        UpstreamServiceError,
        CensusKeyMissing,
        PageCapExceeded,
    ) as exc:
        return {**out, "reason": _why(exc), "sources": []}
    night = PT._nighttime(blocks, dhc, census.sources()["dhc"])
    parts = None
    band = None

    def count_in(g) -> int:
        inside = []
        if g is not None:
            for b in blocks:
                share, kind = geo.area_share(geoms[b.geoid][1], g)
                if kind is not None:
                    inside.append(dataclasses.replace(b, share=share, kind=kind))
        return PT._nighttime(inside, dhc, census.sources()["dhc"])["total"]

    if planning_carries(derived):
        # DN-028 ADDENDUM-14 decisions 6 to 8: the headline count is the action
        # levels' planning area (AEGL-3 and AEGL-2), stated with its parts: inside the
        # moving cloud's area and further inside SLAB's extent check only; the AEGL-1
        # band (every level's area less the action levels') is counted separately,
        # below the headline (Desktop's assumption, decision 8)
        every = night["total"]
        head_area = modelled_area(fp, derived, cfg, what="action")
        head = count_in(head_area)
        cloud_n = count_in(cloud_part_area(derived, action_levels(cfg)))
        parts = {"cloud": cloud_n, "check": head - cloud_n}
        night = {**night, "total": head}
        band = {
            "levels": [
                t
                for t in ((derived.get("agreement") or {}).get("planning") or {})
                if t not in action_levels(cfg)
            ],
            "residents": every - head,
            "every_level": every,
        }
        out["area_km2"] = (
            round(geo.geodesic_area_m2(head_area) / 1e6, 3) if head_area else 0.0
        )
    try:
        work = lodes.jobs(blocks)
        workers = round(work["jobs"])
        work_why = (
            f"LODES not held for {', '.join(sorted(work['missing_states']))}"
            if work["missing_states"]
            else None
        )
    except (OSError, ValueError) as exc:
        workers, work_why = None, str(exc)
    out.update(
        residents=night["total"],
        workers=workers,
        workers_reason=work_why,
        blocks={
            "total": len(blocks),
            "whole": sum(1 for b in blocks if b.kind == "whole"),
            "outside_erg": sum(
                1
                for b in blocks
                if not any(
                    geoms[b.geoid][1].intersects(g)
                    for k, _, g in drawn_hazards(fp, derived, cfg)
                    if k in ZONES
                )
            ),
        },
        vintage=night["vintage"],
        # blocks the DHC rows did not answer: never counted as nobody (review L2-5)
        dhc_missing=len(night["missing_blocks"]),
        reason=None,
    )
    if parts is not None:
        out["parts"] = parts
    if band is not None:
        out["band"] = band
    out["rows"] = [
        {
            "geoid": b.geoid,
            "geometry": geoms[b.geoid][0],
            "share": round(b.share, 4),
            "kind": b.kind,
            "residents": (dhc.get(b.geoid) or {}).get("total"),
            # HB-171 ADDENDUM-01 item 6: the block's group-quarters count by type (the
            # same DHC P18 row; only the types it holds), for the timeline's rows
            "group_quarters": {
                t: int(n)
                for t, n in sorted(
                    ((dhc.get(b.geoid) or {}).get("group_quarters") or {}).items()
                )
                if n
            },
        }
        for b in blocks
    ]
    # the residents under the area each step has reached (the time control's figure)
    steps = ((derived.get("puff") or {}).get("timeline") or {}).get("steps") or []
    by_step = {}
    for s in steps:
        if not s.get("reached"):
            by_step[str(s["minute"])] = 0
            continue
        r = shape(s["reached"])
        n = 0.0
        for b in blocks:
            tot = (dhc.get(b.geoid) or {}).get("total")
            if tot is None:
                continue
            sh, kind = geo.area_share(geoms[b.geoid][1], r)
            if kind is not None:
                n += tot * sh
        by_step[str(s["minute"])] = round(n)
    out["by_step"] = by_step
    # the TIGERweb answers by url (`census._tigerweb_features`' api is "tigerweb"); the
    # DHC rows are read through the same client, tract by tract, and named by vintage
    out["sources"] = [_source("tigerweb", u) for u in urls]
    return out


def incident_point(brief, fp: dict) -> Point:
    """The point distances and bearings are measured from: the spill, or the middle
    of a located shape (a segment's centroid)."""
    spill = spill_shape(brief, fp)
    return spill if isinstance(spill, Point) else spill.centroid


def _short_classes(d: dict, box_m: float) -> list[str]:
    """The station classes whose nearest outside the zones is not known from a box of
    `box_m`: none found, or the nearest found lies past `box_m` (a box's corner holds
    places farther than its half-width, so a nearer one may lie outside it)."""
    out = []
    for cls in ("fire", "ems", "police"):
        rows = (d.get("classes") or {}).get(cls) or []
        if not rows or rows[0]["distance_m"] > box_m:
            out.append(cls)
    return out


def _with_travel(
    out: dict, incident: Point, fp: dict, lines: list, tspec: dict
) -> None:
    """Every row of `out` (the kept and those beyond) given its free-flow time over
    `lines`; one Dijkstra from the incident (HB-151), so every row is computed
    (ADDENDUM-01 item 5)."""
    rows = [r for v in out["classes"].values() for r in v]
    rows += [r for v in (out.get("beyond") or {}).values() for r in v]
    if not rows:
        return
    times = travel_times(
        incident, [Point(r["coordinates"]) for r in rows], lines, fp, tspec
    )
    for r, t in zip(rows, times):
        r["travel"] = t


async def _nearby(c, brief, fp: dict, cfg: dict) -> dict:
    """Stage one of the services in the area (HB-155 ADDENDUM-02 item 4; DN-023 section
    5.3): the stations from the National Structures Dataset in the area radius's box,
    then each wider step's box while a station class's nearest is not known, up to the
    ceiling; the hospitals from receiving_hospitals' answer; and every row's free-flow
    travel time over the roads read in the box of the farthest kept row plus the margin.
    A source the brief does not hold leaves its classes empty with the reason. The
    roads'
    lines are kept (`_lines`) for the siting derivation."""
    spec = cfg["derive"]["nearby"]
    incident = incident_point(brief, fp)
    radius = area_radius_m(cfg)
    rh = c.payload("receiving_hospitals")
    hospitals = None if rh is None else (rh.get("hospitals") or [])
    stations: dict[str, list[dict]] = {}
    read: list[dict] = []
    stations_why = None
    box = radius
    try:
        steps = [m for m in area_steps_m(cfg) if m > radius]
        while True:
            stations, urls = await fetch_stations(incident, box, cfg)
            got = nearby_services(incident, fp, stations, hospitals, cfg)
            if not _short_classes(got, box) or not steps:
                break
            box = steps.pop(0)
        read += [_source(facilities.sources()["structures"]["api"], u) for u in urls]
    except (DeriveError, UpstreamServiceError) as exc:
        stations, stations_why = {}, _why(exc)
    out = nearby_services(incident, fp, stations, hospitals, cfg)
    out["box_m"] = box if stations_why is None else None
    out["stations_reason"] = stations_why
    out["hospitals_reason"] = (
        None if rh is not None else c.why_not("receiving_hospitals")
    )
    a = cfg["derive"]["area"]
    out["stages"] = [
        {
            "n": 1,
            "box_m": box,
            "outcome": "retrieved" if stations_why is None else "failed",
            "reason": stations_why,
        }
    ]
    two = float(a["stage_two_mi"]) * float(a["metres_per_mile"])
    if two > box:
        out["stages"].append(
            {"n": 2, "box_m": two, "outcome": "pending", "reason": None}
        )
    tspec = spec["travel"]
    out["travel_label"] = tspec["label"].format(
        speeds=", ".join(f"{k} {v} km/h" for k, v in tspec["speed_kmh"].items()),
        connector=tspec["connector_kmh"],
    )
    out["_lines"] = []
    rows = [r for v in out["classes"].values() for r in v]
    out["travel_reason"] = stations_why
    if rows:
        far = max(float(r["distance_m"]) for r in rows)
        reach = max(radius, far) + float(tspec["box_margin_m"])
        out["roads_box_m"] = reach
        try:
            ex = await fetch_travel_roads(incident, reach, cfg)
            read += _sources(ex)
            lines = _road_lines(
                [f for e in ex for f in e.body["features"]], list(tspec["classes"])
            )
            # rows beyond the roads' box are not given a time from roads that stop
            # short of them; stage two reads the wider roads
            held_beyond = out.get("beyond") or {}
            out["beyond"] = {
                k: [
                    r
                    for r in v
                    if r["distance_m"] <= reach - float(tspec["box_margin_m"])
                ]
                for k, v in held_beyond.items()
            }
            _with_travel(out, incident, fp, lines, tspec)
            out["beyond"] = {
                k: [
                    r if "travel" in r else {**r, "travel": None}
                    for r in held_beyond.get(k) or []
                ]
                for k in held_beyond
            }
            out["_lines"] = lines
            out["travel_reason"] = None
        except (DeriveError, UpstreamServiceError) as exc:
            out["travel_reason"] = _why(exc)
    out["sources"] = read
    return out


async def _read_box(c, brief, fp: dict, d: dict, cfg: dict, box_m: float) -> None:
    """The stations in the box of `box_m` and the travel roads in its box plus the
    margin, merged into the services in the area `d`: the kept rows (and the sited
    points derived from them) stay stage one's; only the rows beyond the radius grow,
    each with its free-flow time. Raises what the reads raise."""
    spec = cfg["derive"]["nearby"]
    tspec = spec["travel"]
    incident = incident_point(brief, fp)
    rh = c.payload("receiving_hospitals")
    hospitals = None if rh is None else (rh.get("hospitals") or [])
    stations, urls = await fetch_stations(incident, box_m, cfg)
    ex = await fetch_travel_roads(incident, box_m + float(tspec["box_margin_m"]), cfg)
    wide = nearby_services(incident, fp, stations, hospitals, cfg)
    lines = _road_lines(
        [f for e in ex for f in e.body["features"]], list(tspec["classes"])
    )
    _with_travel(wide, incident, fp, lines, tspec)
    kept = {
        cls: {(r.get("name"), tuple(r["coordinates"])) for r in rows}
        for cls, rows in d["classes"].items()
    }
    d["beyond"] = {
        cls: [
            r
            for r in rows + (wide["beyond"].get(cls) or [])
            if (r.get("name"), tuple(r["coordinates"])) not in kept.get(cls, set())
        ]
        for cls, rows in wide["classes"].items()
    }
    d["sources"] = (
        (d.get("sources") or [])
        + [_source(facilities.sources()["structures"]["api"], u) for u in urls]
        + _sources(ex)
    )


async def stage_two(c, brief, fp: dict, derived: dict, cfg: dict) -> bool:
    """Stage two of the services in the area (HB-155 ADDENDUM-02 item 4), after the
    brief is presented: the next step's box (`derive.area.stage_two_mi`), so one step of
    widening is in hand (`_read_box`). The sited points are stage one's and do not
    change (ADDENDUM-05 item 6). Returns whether anything changed. On a replay with no
    recorded answer the stage is "not contacted" (ADDENDUM-03 item 7)."""
    d = derived.get("nearby") or {}
    st = [x for x in d.get("stages") or [] if x["n"] == 2 and x["outcome"] == "pending"]
    if not st or d.get("stations_reason"):
        for x in st:
            x["outcome"], x["reason"] = "not_contacted", d.get("stations_reason")
        return bool(st)
    stage = st[0]
    try:
        await _read_box(c, brief, fp, d, cfg, stage["box_m"])
    except UnrecordedExchangeError as exc:
        stage["outcome"], stage["reason"] = "not_contacted", _why(exc)
        return True
    except (DeriveError, UpstreamServiceError) as exc:
        stage["outcome"], stage["reason"] = "failed", _why(exc)
        return True
    stage["outcome"] = "retrieved"
    return True


async def widen_area(
    c, brief, fp: dict, derived: dict, cfg: dict, box_m: float
) -> None:
    """A live serve's Area radius step past the data in hand (HB-155 ADDENDUM-02 item
    5): that box read (`_read_box`) and recorded as a further stage, read on the
    reader's request. Raises what the reads raise; the page keeps what it drew."""
    d = derived["nearby"]
    n = 1 + max([x["n"] for x in d.get("stages") or []] or [0])
    stage = {"n": n, "box_m": box_m, "outcome": "retrieving", "reason": None}
    d.setdefault("stages", []).append(stage)
    try:
        await _read_box(c, brief, fp, d, cfg, box_m)
    except (DeriveError, UpstreamServiceError) as exc:
        stage["outcome"], stage["reason"] = "failed", _why(exc)
        raise
    stage["outcome"] = "retrieved"


async def stage_two_run(brief, cfg: dict) -> bool:
    """`stage_two` for one assembled brief (the orchestrator calls it after
    `stage_reached`); False where there is no footprint or no services derivation."""
    from hazbrief.brief import layers

    c = layers._Ctx(brief, cfg)
    fp = c.payload("protective_action_footprint")
    if fp is None or not (brief.derived or {}).get("nearby"):
        return False
    return await stage_two(c, brief, fp, brief.derived, cfg)


async def fetch_siting_places(incident: Point, radius_m: float, cfg: dict) -> dict:
    """The places read for siting in the area radius's box (HB-155 item 6): the National
    Structures Dataset's public buildings by layer, TIGER parking lot roads and NTAD's
    truck parking. Each source that fails is its reason; the others stand."""
    spec = cfg["derive"]["siting"]["candidates"]
    bbox = _bbox([incident], radius_m)
    out: dict[str, Any] = {
        "structures": {},
        "parking": [],
        "rest_areas": [],
        "read": [],
    }
    reasons: dict[str, str] = {}
    s = facilities.sources()["structures"]
    try:
        for layer in spec["nsd_layers"]:
            feats, u = await facilities.arcgis_features(
                s["api"],
                f"{s['service']}/{layer}",
                bbox,
                s["out_fields"],
                int(s["page_size"]),
            )
            out["structures"][str(layer)] = feats
            out["read"] += [_source(s["api"], x) for x in u]
    except (DeriveError, UpstreamServiceError) as exc:
        out["structures"], reasons["structures"] = {}, _why(exc)
    try:
        pk = spec["parking"]
        ex = await fetch_json(
            cfg["derive"]["roads"]["api"],
            pk["layer"],
            {
                "where": f"MTFCC='{pk['mtfcc']}'",
                "outFields": cfg["derive"]["roads"]["fields"],
                "returnGeometry": "true",
                "outSR": "4326",
                "f": "json",
                "geometry": bbox,
                "geometryType": "esriGeometryEnvelope",
                "inSR": "4326",
                "spatialRel": "esriSpatialRelIntersects",
            },
        )
        _refuse_partial(ex, pk["layer"])
        if (ex.body or {}).get("exceededTransferLimit"):
            raise DeriveError(f"TIGERweb {pk['layer']} returned a partial set")
        out["parking"] = ex.body["features"]
        out["read"] += _sources([ex])
    except (DeriveError, UpstreamServiceError) as exc:
        reasons["parking"] = _why(exc)
    try:
        ra = spec["rest_areas"]
        feats, u = await facilities.arcgis_features(
            ra["api"], ra["path"], bbox, ra["out_fields"], 2000
        )
        out["rest_areas"] = feats
        out["read"] += [_source(ra["api"], x) for x in u]
    except (DeriveError, UpstreamServiceError) as exc:
        reasons["rest_areas"] = _why(exc)
    out["reasons"] = reasons
    return out


async def _siting(c, brief, fp: dict, derived: dict, cfg: dict) -> dict:
    """HB-155 (DN-023): the places read for siting, then `siting.derive` over them, the
    services in the area and the travel roads. Absent with the reason where the
    services in the area could not be read (a replay with no recorded answer)."""
    from hazbrief.brief import siting

    near = derived.get("nearby") or {}
    why = near.get("reason") or near.get("stations_reason") or near.get("travel_reason")
    if why:
        return {"points": {}, "reason": why, "routes": [], "sources": []}
    incident = incident_point(brief, fp)
    radius = area_radius_m(cfg)
    places = await fetch_siting_places(incident, radius, cfg)
    cands = siting.service_candidates(near)
    cands += siting.structure_candidates(places["structures"], cfg)
    cands += siting.parking_candidates(places["parking"], incident, cfg)
    cands += siting.rest_area_candidates(places["rest_areas"])
    out = siting.derive(
        brief, fp, derived, cands, near.get("_lines") or [], cfg, radius
    )
    out["place_reasons"] = places["reasons"]
    out["candidate_count"] = len(cands)
    out["sources"] = places["read"]
    return out


def _smoke(brief, fp: dict | None, derived: dict, cfg: dict) -> dict | None:
    """The smoke layer (DN-021; HB-129), only for a brief with a fire block."""
    from hazbrief.brief import smoke

    return smoke.derive(brief, fp, derived, cfg)


async def _hb55(c, fp: dict, spill, cfg: dict, path: dict | None) -> dict:
    """Workplaces, establishments and terrain for one brief (HB-55); the terrain
    also along the downstream `path` (HB-59)."""
    from hazbrief.brief import layers

    out: dict[str, Any] = {}
    if c.ok("population_at_risk"):
        blocks = [b["geoid"] for b in layers.population_blocks(c)]
        try:
            wac = read_wac(blocks, list(cfg["derive"]["workplaces"]["columns"]))
            out["workplaces"] = workplaces_by_block(blocks, wac, cfg)
        except DeriveError as exc:
            out["workplaces"] = {"jobs": {}, "reason": str(exc)}
        counties = layers.population_counties(c)
        try:
            cbp = await fetch_establishments(counties, cfg)
            out["establishments"] = county_establishments(cbp, cfg)
            out["establishments"]["sources"] = _sources(cbp)
        except (DeriveError, UpstreamServiceError) as exc:
            out["establishments"] = {"rows": [], "reason": _why(exc), "sources": []}
    else:
        why = c.why_not("population_at_risk")
        out["workplaces"] = {"jobs": {}, "reason": why}
        out["establishments"] = {"rows": [], "reason": why, "sources": []}
    try:
        elevation, fallback = await fetch_terrain(fp, cfg, path)
        try:
            read = await fetch_cover(fp, cfg, path)
            cover = land_cover(read, fp, cfg, path)
            cover_ex, cover_why = read.exchanges, None
        except (DeriveError, UpstreamServiceError) as exc:
            cover, cover_ex, cover_why = None, [], _why(exc)
        out["terrain"] = terrain(spill, fp, elevation, cover, cfg, path, fallback)
        out["terrain"]["cover_reason"] = cover_why
        out["terrain"]["sources"] = _sources(elevation + cover_ex)
    except (DeriveError, UpstreamServiceError) as exc:
        out["terrain"] = {"zones": {}, "reason": _why(exc), "sources": []}
    return out


def _why(exc: Exception) -> str:
    if isinstance(exc, UnrecordedExchangeError):
        return "its upstream answer is not recorded"
    return str(exc)
