"""The footprint as one shape, and the share of a Census unit's area inside it (HB-09).

`population_at_risk` counts people by **area weighting**: a block, block group or tract
wholly inside the footprint counts in full, and one partly inside counts by the share of
its area that lies inside. This is areal interpolation by areal weighting (Goodchild and
Lam, "Areal interpolation: a variant of the traditional spatial problem", Geo-Processing
1, 1980, pp. 297-312; UCGIS GIS&T Body of Knowledge AM-02-040). It assumes the counted
population is spread evenly over each source unit, the method's known weakness, and the
tool says so in its `limits`. MARPLOT's own allocation rule is disputed (LN-01 section
1), so this one is stated.

Intersections are taken by GEOS (shapely) on longitude and latitude, the ring edges read
as straight lines as RFC 7946 reads them. Areas are geodesic on the WGS84 ellipsoid
(Karney 2013, `geographiclib` PolygonArea), so a share is a ratio of true areas, not of
squared degrees.
"""

from __future__ import annotations

import shapely
from geographiclib.geodesic import Geodesic
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry import shape as _shape
from shapely.ops import unary_union
from shapely.validation import make_valid

from hazbrief.config import settings
from hazbrief.geometry import GeometryError

_WGS84 = Geodesic.WGS84
_POLYGONAL = ("Polygon", "MultiPolygon")
#: A share this close to 1 is a unit wholly inside: the intersection of a unit with a
#: footprint that contains it can differ from the unit in the last bits of a coordinate.
WHOLE_TOLERANCE = 1e-9


def shape(geometry: dict):
    """A GeoJSON geometry as a valid, two-dimensional shapely geometry. A position's
    third element (altitude, RFC 7946 section 3.1.1) is dropped: every measure here is
    on the ellipsoid's surface (review L2-6)."""
    try:
        g = shapely.force_2d(_shape(geometry))
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise GeometryError(f"not a GeoJSON geometry: {exc}") from None
    return g if g.is_valid else make_valid(g)


def footprint_shape(geojson: dict, zones: list[str] | None = None):
    """The union of the polygons in a GeoJSON object (a FeatureCollection such as
    `protective_action_footprint` returns, a Feature, or a bare Polygon or
    MultiPolygon). Points and lines are ignored. With `zones`, only the features whose
    `properties.zone` is listed.

    A footprint over `settings.max_footprint_vertices` polygon vertices or
    `settings.max_footprint_area_km2` of geodesic area is a `FootprintTooLarge`, raised
    before a caller pages any upstream service across it (HB-89; review L3-2)."""
    kind = geojson.get("type") if isinstance(geojson, dict) else None
    if kind == "FeatureCollection":
        features = geojson.get("features") or []
    elif kind == "Feature":
        features = [geojson]
    elif kind in _POLYGONAL or kind in ("Point", "MultiPoint", "LineString"):
        features = [{"type": "Feature", "geometry": geojson, "properties": {}}]
    else:
        raise GeometryError(f"not a GeoJSON object this tool reads (type {kind!r})")
    chosen = []
    for f in features:
        g = (f or {}).get("geometry") or {}
        if g.get("type") not in _POLYGONAL:
            continue
        if zones is not None and (f.get("properties") or {}).get("zone") not in zones:
            continue
        chosen.append(g)
    if not chosen:
        which = f" among zones {zones}" if zones is not None else ""
        raise GeometryError(f"the footprint has no polygon{which}")
    # Counted on the raw GeoJSON, before GEOS parses or repairs anything.
    vertices = sum(_vertex_count(g.get("coordinates")) for g in chosen)
    if vertices > settings.max_footprint_vertices:
        raise FootprintTooLarge(
            f"the footprint has {vertices} vertices, over the server's limit of "
            f"{settings.max_footprint_vertices}"
        )
    union = unary_union([shape(g) for g in chosen])
    area_km2 = geodesic_area_m2(union) / 1e6
    if area_km2 > settings.max_footprint_area_km2:
        raise FootprintTooLarge(
            f"the footprint covers {area_km2:,.0f} km2, over the server's limit of "
            f"{settings.max_footprint_area_km2:,.0f} km2 (the disk of the ERG's "
            "largest Table 3 protective action distance, 11 km)"
        )
    return union


#: The hint a tool returns with a `FootprintTooLarge` or a `PageCapExceeded`: the remedy
#: is a smaller area, never a retry.
TOO_LARGE_HINT = (
    "Pass the footprint protective_action_footprint returns, or draw a smaller "
    "polygon; the server bounds a caller's area, vertices and pages per layer "
    "(docs/SECURITY.md section 10)."
)


class FootprintTooLarge(GeometryError):
    """A caller's footprint exceeds the configured vertex or area bound (HB-89)."""


def _vertex_count(coords) -> int:
    """Positions in a GeoJSON coordinates array of any nesting; 0 for a malformed one,
    which `shape` then refuses."""
    if not isinstance(coords, (list, tuple)) or not coords:
        return 0
    if all(isinstance(c, (int, float)) for c in coords):
        return 1
    return sum(_vertex_count(c) for c in coords)


def _polygons(g) -> list:
    if isinstance(g, Polygon):
        return [g]
    if isinstance(g, MultiPolygon):
        return list(g.geoms)
    # A GeometryCollection from make_valid or an intersection: keep its areal parts.
    return [p for part in getattr(g, "geoms", []) for p in _polygons(part)]


def _ring_area(coords) -> float:
    poly = _WGS84.Polygon()
    for lon, lat, *_ in list(coords)[:-1]:
        poly.AddPoint(lat, lon)
    _, _, area = poly.Compute(False, True)
    return abs(area)


def geodesic_area_m2(g) -> float:
    """Square metres on the WGS84 ellipsoid: each exterior ring less its holes."""
    return sum(
        _ring_area(p.exterior.coords) - sum(_ring_area(h.coords) for h in p.interiors)
        for p in _polygons(g)
        if not p.is_empty
    )


def area_share(unit, footprint) -> tuple[float, str | None]:
    """`(share, kind)`: the share of `unit`'s geodesic area inside `footprint`, and
    "whole", "partial", or None when the two do not overlap in area."""
    if unit.is_empty or not unit.intersects(footprint):
        return 0.0, None
    if unit.within(footprint):
        return 1.0, "whole"
    total = geodesic_area_m2(unit)
    if total <= 0:
        return 0.0, None
    inside = geodesic_area_m2(unit.intersection(footprint))
    share = min(inside / total, 1.0)
    if share <= 0:
        return 0.0, None
    if share >= 1.0 - WHOLE_TOLERANCE:
        return 1.0, "whole"
    return share, "partial"
