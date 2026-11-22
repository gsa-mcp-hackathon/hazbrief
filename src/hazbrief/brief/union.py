"""The footprint over a shape: the union of the frozen tool's footprints along it
(DN-013 sections 2 and 5.3; HB-49 step 4).

Until the tool takes a location record (DN-013 section 6, after 2026-11-20), the
workbench calls the frozen `protective_action_footprint` at sample points along the
shape and unions the zones. Nothing here is a dispersion model: each zone is the ERG's,
drawn by the tool, and the union only says where that zone could lie (DN-001 invariant
1).

**Sampling.** The first sample is the shape's first vertex. Its footprint states the ERG
isolation distances in play, and the spacing is the smallest of them, never more than
the configured cap (`orchestrator.yaml` `location.sampling`), so no stretch of the shape
goes unsampled for longer than the smallest zone is wide. The line is simplified first,
within `simplify_m` in the local plane, so the samples follow the line's bends without
one call per surveyed vertex.

**The union.** For each zone, the union of the convex hulls of each consecutive pair of
its placements. A convex zone (the isolation disc, the downwind square) moved along a
straight piece sweeps exactly the convex hull of its two end placements (the Minkowski
sum of a convex set and a segment), so the union is the swept footprint along the
simplified line, and contains every sample's own footprint. A point with a stated
accuracy is the degenerate case: its zones are grown by that accuracy (DN-013 section
2: "a disc of that radius").
"""

from __future__ import annotations

import copy
import math

import shapely
from shapely.geometry import LineString, Point, mapping, shape
from shapely.ops import unary_union

from hazbrief import facilities
from hazbrief.geometry import COORDINATE_DECIMALS

#: the zones the frozen footprint draws as polygons (its `properties.zone`)
SPILL = "spill"


def isolation_m(payload: dict) -> float | None:
    """The smallest isolation distance the footprint states, in metres."""
    ds = [
        (z.get("distance") or {}).get("metres")
        for name, z in (payload.get("zones") or {}).items()
        if "isolation" in name
    ]
    ds = [d for d in ds if d]
    return min(ds) if ds else None


def spacing_m(payload: dict, cfg: dict) -> float:
    cap = float(cfg["location"]["sampling"]["max_spacing_m"])
    iso = isolation_m(payload)
    return min(iso, cap) if iso else cap


def _plane(g, c: Point):
    scale = (math.cos(math.radians(c.y)) * facilities._M_PER_DEG, facilities._M_PER_DEG)
    to = shapely.transform(g, lambda xy: (xy - (c.x, c.y)) * scale)
    return to, lambda p: shapely.transform(p, lambda xy: xy / scale + (c.x, c.y))


def simplified(line: LineString, cfg: dict) -> LineString:
    """The line simplified within `simplify_m` metres (Douglas-Peucker in the local
    plane), its ends kept."""
    tol = float(cfg["location"]["sampling"]["simplify_m"])
    plane, back = _plane(line, line.centroid)
    return back(plane.simplify(tol, preserve_topology=False))


def _rounded_point(x: float, y: float) -> tuple[float, float]:
    return round(x, COORDINATE_DECIMALS), round(y, COORDINATE_DECIMALS)


def parts(record: dict, spacing: float, cfg: dict) -> list[list[tuple[float, float]]]:
    """The samples in parts, each in order along its piece of the shape:
    * a Point, or each candidate point of an intersection (`points`, HB-50): a part of
      one sample, its zones grown by the record's accuracy;
    * a LineString, or each candidate segment of a MultiLineString (an address that
      ties, HB-50): its simplified vertices, with points between any two of them so
      that no two consecutive samples are farther apart than `spacing` (geodesic).
    Hulls join consecutive samples within a part, never across parts."""
    if record.get("points"):
        return [[_rounded_point(*p)] for p in record["points"]]
    g = shape(record["shape"])
    if g.geom_type == "Point":
        return [[_rounded_point(g.x, g.y)]]
    if g.geom_type == "LineString":
        return [_line_samples(g, spacing, cfg)]
    if g.geom_type == "MultiLineString":
        return [_line_samples(line, spacing, cfg) for line in g.geoms]
    raise ValueError(f"no sampling for a {g.geom_type} location")


def samples(record: dict, spacing: float, cfg: dict) -> list[tuple[float, float]]:
    """Every sample, the parts in order (`parts`)."""
    return [p for part in parts(record, spacing, cfg) for p in part]


def _line_samples(
    g: LineString, spacing: float, cfg: dict
) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    coords = list(simplified(g, cfg).coords)
    for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
        piece = facilities.geodesic_line(Point(x1, y1), Point(x2, y2), step_m=spacing)
        for x, y in piece.coords:
            p = (round(x, COORDINATE_DECIMALS), round(y, COORDINATE_DECIMALS))
            if not pts or pts[-1] != p:
                pts.append(p)
    return pts


def representative(record: dict) -> tuple[float, float]:
    """The point other tools are asked about when the location is a shape: the
    source's own point when the record holds one (`hint`: the geocoder's interpolated
    address, the first crossing, HB-50), else its middle (half its length along a
    line), rounded as the tools round."""
    if record.get("hint"):
        return _rounded_point(*record["hint"])
    g = shape(record["shape"])
    if g.geom_type != "Point":
        g = g.interpolate(0.5, normalized=True)
    return _rounded_point(g.x, g.y)


def _zones(payload: dict) -> dict[str, tuple[dict, object]]:
    out = {}
    for f in payload["footprint"]["features"]:
        z = (f.get("properties") or {}).get("zone")
        if z and z != SPILL and f["geometry"]["type"] in ("Polygon", "MultiPolygon"):
            out[z] = (f["properties"], shape(f["geometry"]))
    return out


def _lists(c):
    return [_lists(x) for x in c] if isinstance(c, (list, tuple)) else c


def _rounded(g) -> dict:
    """GeoJSON rounded as the tools round, with lists, so the payload equals its own
    JSON round trip (the parameters a downstream call is recorded with)."""
    m = mapping(shapely.set_precision(g, 10**-COORDINATE_DECIMALS))
    return {"type": m["type"], "coordinates": _lists(m["coordinates"])}


def union(payloads: list[dict], record: dict, spacing: float, cfg: dict) -> dict:
    """The footprint payload over the shape: the first sample's payload, its zones
    replaced by their unions along the samples (module docstring), its spill feature by
    the representative point, and `location_union` saying how it was made."""
    out = copy.deepcopy(payloads[0])
    per = [_zones(p) for p in payloads]
    names = [z for z in per[0] if all(z in q for q in per)]
    sizes = [len(part) for part in parts(record, spacing, cfg)]
    if sum(sizes) != len(payloads):
        raise ValueError(f"{len(payloads)} footprints for {sum(sizes)} samples")
    # a point's stated accuracy grows its zones; a segment's length is not a radius
    acc = (
        0 if record.get("basis") == "segment_length" else record.get("accuracy_m") or 0
    )
    feats = []
    for name in names:
        polys, pieces, i = [q[name][1] for q in per], [], 0
        for n in sizes:
            part = polys[i : i + n]
            i += n
            if n == 1:
                pieces.append(facilities.buffer(part[0], acc) if acc else part[0])
            else:
                pieces += [
                    unary_union([a, b]).convex_hull for a, b in zip(part, part[1:])
                ]
        g = unary_union(pieces)
        feats.append(
            {
                "type": "Feature",
                "geometry": _rounded(g),
                "properties": dict(per[0][name][0]),
            }
        )
    lon, lat = representative(record)
    spill = {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {"zone": SPILL},
    }
    out["footprint"] = {"type": "FeatureCollection", "features": [spill, *feats]}
    loc = cfg["location"]
    if max(sizes) > 1:
        note = loc["union_label"].format(n=len(payloads), spacing_m=spacing)
    elif acc and len(sizes) > 1:
        note = loc["grown_points_label"].format(accuracy_m=acc, n=len(sizes))
    elif acc:
        note = loc["grown_label"].format(accuracy_m=acc)
    else:
        note = ""
    out["location_union"] = {
        "samples": len(payloads),
        "spacing_m": spacing,
        "simplify_m": cfg["location"]["sampling"]["simplify_m"],
        "label": record["label"] + note,
    }
    return out
