"""src/hazbrief/geo.py: the footprint as one shape, geodesic areas, and the share of a
Census unit's area inside the footprint (HB-09 method step 2)."""

from __future__ import annotations

import pytest
from geographiclib.geodesic import Geodesic

from hazbrief import geo, geometry


def square(lon0: float, lat0: float, lon1: float, lat1: float) -> list:
    return [[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]]


BLOCK = {"type": "Polygon", "coordinates": [square(-77.01, 38.90, -77.00, 38.91)]}


def test_a_polygon_covering_exactly_half_a_square_block_allocates_half():
    """The west half of the block, by longitude: equal widths at the same latitudes
    are equal geodesic areas, so the share is a half to float precision."""
    half = {"type": "Polygon", "coordinates": [square(-77.02, 38.89, -77.005, 38.92)]}
    share, kind = geo.area_share(geo.shape(BLOCK), geo.shape(half))
    assert share == pytest.approx(0.5, abs=1e-9) and kind == "partial"


def test_a_block_inside_the_footprint_is_whole_and_one_outside_is_none():
    big = {"type": "Polygon", "coordinates": [square(-77.1, 38.8, -76.9, 39.0)]}
    far = {"type": "Polygon", "coordinates": [square(-76.0, 38.0, -75.9, 38.1)]}
    assert geo.area_share(geo.shape(BLOCK), geo.shape(big)) == (1.0, "whole")
    assert geo.area_share(geo.shape(BLOCK), geo.shape(far)) == (0.0, None)


def test_geodesic_area_matches_geographiclib_polygon_area():
    poly = Geodesic.WGS84.Polygon()
    for lon, lat in square(-77.01, 38.90, -77.00, 38.91)[:-1]:
        poly.AddPoint(lat, lon)
    _, _, area = poly.Compute(False, True)
    assert geo.geodesic_area_m2(geo.shape(BLOCK)) == pytest.approx(abs(area), rel=1e-9)


def test_a_hole_is_subtracted():
    ring = square(-77.02, 38.89, -76.99, 38.92)
    hole = list(reversed(square(-77.01, 38.90, -77.00, 38.91)))
    donut = geo.shape({"type": "Polygon", "coordinates": [ring, hole]})
    outer = geo.shape({"type": "Polygon", "coordinates": [ring]})
    expect = geo.geodesic_area_m2(outer) - geo.geodesic_area_m2(geo.shape(BLOCK))
    assert geo.geodesic_area_m2(donut) == pytest.approx(expect, rel=1e-9)


def test_the_footprint_is_the_union_of_its_polygon_features():
    """protective_action_footprint's FeatureCollection: a spill point (ignored), an
    isolation circle and a downwind square that overlap; their union is counted once."""
    lat, lon = 39.722, -77.724
    fc = {
        "type": "FeatureCollection",
        "features": [
            geometry.point_feature(lat, lon, {"zone": "spill"}),
            geometry.polygon_feature(
                geometry.circle(lat, lon, 600, 72), {"zone": "initial_isolation_zone"}
            ),
            geometry.polygon_feature(
                geometry.downwind_square(lat, lon, 3300, 90.0),
                {"zone": "protective_action_zone"},
            ),
        ],
    }
    union = geo.footprint_shape(fc)
    square_only = geo.footprint_shape(fc, zones=["protective_action_zone"])
    a_union, a_square = geo.geodesic_area_m2(union), geo.geodesic_area_m2(square_only)
    assert a_square == pytest.approx(3300**2, rel=0.002)
    # The circle's upwind half lies outside the square: the union adds about half of it.
    assert a_union - a_square == pytest.approx(3.14159 * 600**2 / 2, rel=0.01)


def test_a_footprint_with_no_polygon_is_refused():
    with pytest.raises(geometry.GeometryError, match="no polygon"):
        geo.footprint_shape({"type": "Point", "coordinates": [-77.0, 38.9]})
    with pytest.raises(geometry.GeometryError, match="no polygon"):
        geo.footprint_shape(
            {"type": "FeatureCollection", "features": []}, zones=["absent"]
        )


def test_an_unknown_geojson_type_is_refused():
    with pytest.raises(geometry.GeometryError, match="GeoJSON"):
        geo.footprint_shape({"type": "Topology", "objects": {}})
