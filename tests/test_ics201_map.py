"""The Block 4 sketch renderer (HB-11b step 5): Web Mercator, the frame, the scale bar,
and an SVG that is the same bytes for the same inputs. Network-free: the basemap here
is a stand-in PNG; the replayed TIGERweb export is exercised by test_build_ics_201.py.
"""

from __future__ import annotations

import math

import pytest

from hazbrief import ics201_map

PNG = b"\x89PNG\r\n\x1a\n" + bytes(32)


def test_mercator_is_epsg_3857():
    # EPSG:3857 on the WGS84 semi-major axis: lon 180 is pi * a, the equator is y 0
    x, y = ics201_map.mercator(180.0, 0.0)
    assert x == pytest.approx(math.pi * 6378137.0) and y == pytest.approx(0.0, abs=1e-6)
    # Washington, DC, checked against the EPSG:3857 forward formula by hand
    x, y = ics201_map.mercator(-77.0, 38.9)
    assert x == pytest.approx(-8571600.0, abs=1.0)
    assert y == pytest.approx(4707357.5, abs=1.0)  # spherical, not ellipsoidal


def test_the_frame_holds_its_points_at_the_image_aspect_ratio():
    cfg = ics201_map.config()
    pts = [(-77.73, 39.70), (-77.68, 39.62), (-77.70, 39.73)]
    f = ics201_map.frame(pts, cfg)
    assert f["width"] == cfg["width_px"]
    assert cfg["min_height_px"] <= f["height"] <= cfg["max_height_px"]
    for lon, lat in pts:
        x, y = ics201_map.mercator(lon, lat)
        assert f["xmin"] < x < f["xmax"] and f["ymin"] < y < f["ymax"]
    ratio = (f["xmax"] - f["xmin"]) / (f["ymax"] - f["ymin"])
    assert ratio == pytest.approx(f["width"] / f["height"], rel=1e-3)


@pytest.mark.parametrize(
    "ground_m, expected", [(10_000, 2_000), (3_000, 500), (40_000, 5_000)]
)
def test_the_scale_bar_is_a_round_length_near_a_fifth_of_the_width(ground_m, expected):
    assert ics201_map.scale_length(ground_m / 5) == expected


def _minimal_geojson():
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-77.724, 39.722]},
                "properties": {"zone": "spill"},
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-77.73, 39.72],
                            [-77.72, 39.72],
                            [-77.72, 39.73],
                            [-77.73, 39.73],
                            [-77.73, 39.72],
                        ]
                    ],
                },
                "properties": {"zone": "initial_isolation_zone"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-77.70, 39.70]},
                "properties": {
                    "layer": "receiving_hospital",
                    "name": "AT&T <Test> HOSPITAL",
                    "distance_km": 3.0,
                },
            },
        ],
    }


def test_the_svg_is_deterministic_and_escapes_labels():
    cfg = ics201_map.config()
    gj = _minimal_geojson()
    f = ics201_map.frame([(-77.73, 39.72), (-77.70, 39.70)], cfg)
    a = ics201_map.render_svg(gj, f, PNG, None, cfg, label=str)
    b = ics201_map.render_svg(gj, f, PNG, None, cfg, label=str)
    assert a == b
    assert "AT&amp;T &lt;Test&gt; HOSPITAL" in a and "<Test>" not in a
    assert 'id="initial_isolation_zone"' in a and 'id="spill"' in a


def test_without_a_basemap_the_sketch_still_draws_and_says_so():
    cfg = ics201_map.config()
    f = ics201_map.frame([(-77.73, 39.72), (-77.70, 39.70)], cfg)
    svg = ics201_map.render_svg(_minimal_geojson(), f, None, None, cfg, label=str)
    assert "data:image/png" not in svg
    assert "Basemap not available" in svg
