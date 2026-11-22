"""The ERG zones as GeoJSON polygons (DN-005 section 4).

The ERG draws the protective action zone as a square ("Its length and width are the
same as the downwind distance shown in Table 1"), the spill at the middle of its upwind
side, and the initial isolation zone as a circle of the isolation distance around the
spill (ERG 2024 PDF pp. 290-291). Each shape is laid out in a local azimuthal
equidistant projection about the spill, where a distance and a bearing from the spill
are true, and each vertex is carried back to longitude and latitude by the WGS84
geodesic (Karney 2013, as `geographiclib` implements it; the azimuthal equidistant
point at (x east, y north) is the geodesic from the spill of length hypot(x, y) at
azimuth atan2(x, y)). Edges are the
straight lines between vertices, as RFC 7946 interprets a GeoJSON ring. No smoothing, no
sectors, no dispersion.
"""

from __future__ import annotations

import math

from geographiclib.geodesic import Geodesic

_WGS84 = Geodesic.WGS84
#: RFC 7946 section 11.2: six decimal places of a degree are about 10 centimetres, finer
#: than any ERG distance is printed.
COORDINATE_DECIMALS = 6


class GeometryError(ValueError):
    """A shape this module cannot draw as valid GeoJSON."""


def offset(lat0: float, lon0: float, east_m: float, north_m: float) -> list[float]:
    """The point at (east, north) metres in the azimuthal equidistant projection about
    (lat0, lon0), as a GeoJSON [longitude, latitude]."""
    d = math.hypot(east_m, north_m)
    if d == 0:
        return [round(lon0, COORDINATE_DECIMALS), round(lat0, COORDINATE_DECIMALS)]
    g = _WGS84.Direct(lat0, lon0, math.degrees(math.atan2(east_m, north_m)), d)
    return [
        round(g["lon2"], COORDINATE_DECIMALS),
        round(g["lat2"], COORDINATE_DECIMALS),
    ]


def _ring(lat0: float, lon0: float, local: list[tuple[float, float]]) -> list:
    """A closed GeoJSON linear ring from local (east, north) vertices given
    counterclockwise (RFC 7946 section 3.1.6: exterior rings are counterclockwise)."""
    ring = [offset(lat0, lon0, x, y) for x, y in local]
    lons = [p[0] for p in ring]
    if max(lons) - min(lons) > 180:
        raise GeometryError("The zone crosses the antimeridian; not supported.")
    return ring + [ring[0]]


def circle(lat0: float, lon0: float, radius_m: float, vertices: int) -> list:
    """The ring of a circle of `radius_m` about the spill, `vertices` points on it."""
    if radius_m <= 0 or vertices < 8:
        raise GeometryError(f"circle radius {radius_m} m, {vertices} vertices")
    # Counterclockwise from east: angle a from the east axis, x = r cos a, y = r sin a.
    local = [
        (
            radius_m * math.cos(2 * math.pi * k / vertices),
            radius_m * math.sin(2 * math.pi * k / vertices),
        )
        for k in range(vertices)
    ]
    return _ring(lat0, lon0, local)


def downwind_square(
    lat0: float, lon0: float, side_m: float, downwind_bearing_deg: float
) -> list:
    """The ring of the ERG protective action square: side `side_m`, extending downwind
    along `downwind_bearing_deg` (clockwise from north), the spill at the midpoint of
    its upwind side."""
    if side_m <= 0:
        raise GeometryError(f"square side {side_m} m")
    b = math.radians(downwind_bearing_deg)
    ux, uy = math.sin(b), math.cos(b)  # downwind unit vector (east, north)
    rx, ry = math.cos(b), -math.sin(b)  # unit vector to the right of downwind
    h = side_m / 2
    # Upwind-right, downwind-right, downwind-left, upwind-left: counterclockwise.
    local = [
        (h * rx, h * ry),
        (h * rx + side_m * ux, h * ry + side_m * uy),
        (-h * rx + side_m * ux, -h * ry + side_m * uy),
        (-h * rx, -h * ry),
    ]
    return _ring(lat0, lon0, local)


def polygon_feature(ring: list, properties: dict) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [ring]},
        "properties": properties,
    }


def point_feature(lat: float, lon: float, properties: dict) -> dict:
    return {
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": [
                round(lon, COORDINATE_DECIMALS),
                round(lat, COORDINATE_DECIMALS),
            ],
        },
        "properties": properties,
    }
