"""Facility, waterway and rail reads for `facilities_in_footprint` and
`receiving_hospitals` (HB-10), through the one upstream client (`utils.fetch_json`,
DN-005 section 2), plus the CMS files `scripts/fetch_cms.py` caches. Every service,
layer, field and as-of is in `facilities_sources.yaml`.

The method is HB-09's: an envelope query on the footprint's bounding box (ArcGIS
`esriSpatialRelIntersects`, paged), then the exact test by GEOS on longitude and
latitude. A point is inside when the footprint contains it; a line's length inside and
a polygon's area inside are geodesic on the WGS84 ellipsoid (Karney 2013,
`geographiclib`), as `geo.geodesic_area_m2` measures areas.

**Buffer.** `buffer_m` grows the footprint by a distance in metres. It is drawn in a
local equirectangular plane centred on the footprint (x scaled by the cosine of the
centre latitude), which for a footprint tens of kilometres across is within 0.1 percent
of the geodesic distance; the footprint's own zones are drawn geodesically and are not
redrawn.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import shapely
import yaml
from geographiclib.geodesic import Geodesic
from shapely.geometry import LineString, MultiLineString, Point

from hazbrief import geo
from hazbrief.census import envelope
from hazbrief.config import settings
from hazbrief.geometry import COORDINATE_DECIMALS, GeometryError
from hazbrief.utils import PageCapExceeded, UpstreamServiceError, fetch_json

SOURCES_FILE = Path(__file__).with_name("facilities_sources.yaml")
REQUIRED = {
    "structures": (
        "api",
        "service",
        "label",
        "as_of",
        "page_size",
        "out_fields",
        "categories",
        "fcode_types",
    ),
    "hydrography": (
        "api",
        "service",
        "label",
        "as_of",
        "page_size",
        "max_allowable_offset_deg",
        "flowlines",
        "waterbodies",
    ),
    "rail": ("api", "page_size", "lines", "crossings"),
    "arcgis": ("max_features_per_layer",),
    "cms": ("hospitals", "pos", "nursing_homes", "geocoder"),
    "receiving": ("max_km", "limit", "crossing_tolerance_m", "line_step_m"),
}
_WGS84 = Geodesic.WGS84
#: The footprint's zone names (protective_action_footprint), and the short names a
#: facility's `zone` is written with: the two ERG table zones, then (HB-15, F-5b) the
#: orange guide's circles, which keep their own names.
ZONES = {
    "initial_isolation_zone": "isolation",
    "protective_action_zone": "protective_action",
    "large_spill_evacuation": "large_spill_evacuation",
    "fire_isolation": "fire_isolation",
    "fire_evacuation": "fire_evacuation",
}
#: The table zones, which a facility is placed in first (the inner one first).
TABLE_ZONES = ("isolation", "protective_action")
#: A metre of mean Earth radius per degree of latitude (IUGG mean radius 6,371,008.8 m),
#: for the local plane `buffer` draws in.
_M_PER_DEG = 6_371_008.8 * math.pi / 180


class SourcesError(RuntimeError):
    """`facilities_sources.yaml` is missing or lacks a required key."""


class CmsFileMissing(RuntimeError):
    """A CMS file `scripts/fetch_cms.py` caches is not in
    `settings.hazbrief_cms_dir`."""


def load_sources(path: Path = SOURCES_FILE) -> dict:
    if not path.is_file():
        raise SourcesError(f"facilities sources not found: {path}")
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for section, keys in REQUIRED.items():
        missing = [k for k in keys if k not in (doc.get(section) or {})]
        if missing:
            raise SourcesError(f"{path}: {section} lacks {', '.join(missing)}")
    return doc


@lru_cache(maxsize=1)
def sources() -> dict:
    return load_sources()


# ── The footprint's zones ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class Area:
    """The footprint as one shape (buffered when asked), and its zones by short name.
    `zones` is empty for a footprint whose polygons carry no zone property."""

    shape: object
    zones: dict
    buffer_m: float


def area(footprint: dict, buffer_m: float = 0.0) -> Area:
    whole = geo.footprint_shape(footprint)
    zones = {}
    for name, short in ZONES.items():
        try:
            zones[short] = geo.footprint_shape(footprint, [name])
        except GeometryError:
            continue
    shape = buffer(whole, buffer_m) if buffer_m > 0 else whole
    return Area(shape=shape, zones=zones, buffer_m=buffer_m)


def buffer(g, metres: float):
    """`g` grown by `metres`, drawn in the local plane (module docstring)."""
    c = g.centroid
    scale = (math.cos(math.radians(c.y)) * _M_PER_DEG, _M_PER_DEG)
    plane = shapely.transform(g, lambda xy: (xy - (c.x, c.y)) * scale)
    return shapely.transform(plane.buffer(metres), lambda xy: xy / scale + (c.x, c.y))


def zone_of(g, a: Area) -> str | None:
    """The zone a feature is in: "isolation" or "protective_action" (a feature in both
    is in the isolation zone, the inner one); else the smallest guide circle it is in
    ("large_spill_evacuation", "fire_isolation", "fire_evacuation"; HB-15, F-5b);
    "buffer" (inside only the buffer); "footprint" (inside a polygon that carries no
    zone name); or None when the feature does not reach the area."""
    if not g.intersects(a.shape):
        return None
    for short in TABLE_ZONES:
        z = a.zones.get(short)
        if z is not None and g.intersects(z):
            return short
    circles = sorted(
        (z.area, short) for short, z in a.zones.items() if short not in TABLE_ZONES
    )
    for _, short in circles:
        if g.intersects(a.zones[short]):
            return short
    return "buffer" if a.buffer_m > 0 else "footprint"


def geodesic_length_m(g) -> float:
    """Metres along the WGS84 ellipsoid, summed over every line of `g`."""
    lines = []
    if isinstance(g, LineString):
        lines = [g]
    elif isinstance(g, MultiLineString):
        lines = list(g.geoms)
    else:
        lines = [p for p in getattr(g, "geoms", []) if isinstance(p, LineString)]
    total = 0.0
    for line in lines:
        pts = list(line.coords)
        for (x1, y1, *_), (x2, y2, *_) in zip(pts, pts[1:]):
            total += _WGS84.Inverse(y1, x1, y2, x2)["s12"]
    return total


def inverse(lat1: float, lon1: float, lat2: float, lon2: float) -> tuple[float, float]:
    """(metres, initial bearing in degrees 0-360) from the first point to the second."""
    r = _WGS84.Inverse(lat1, lon1, lat2, lon2)
    return r["s12"], r["azi1"] % 360


def destination(lat: float, lon: float, bearing: float, metres: float) -> Point:
    r = _WGS84.Direct(lat, lon, bearing, metres)
    return Point(round(r["lon2"], 6), round(r["lat2"], 6))


def geodesic_line(a: Point, b: Point, step_m: float = 250.0) -> LineString:
    """The geodesic from `a` to `b` as a line with a vertex every `step_m` metres, so a
    straight line in longitude and latitude between vertices departs from it by less
    than a metre at the distances this module measures (50 km)."""
    line = _WGS84.InverseLine(a.y, a.x, b.y, b.x)
    n = max(1, math.ceil(line.s13 / step_m))
    pts = []
    for i in range(n + 1):
        p = line.Position(line.s13 * i / n)
        pts.append((p["lon2"], p["lat2"]))
    return LineString(pts)


# ── ArcGIS envelope queries ───────────────────────────────────────────────────


async def arcgis_features(
    api: str,
    path: str,
    bbox: str,
    out_fields: str,
    page: int,
    where: str = "1=1",
    max_offset: float | None = None,
    geometry: bool = True,
) -> tuple[list, list]:
    """Every feature of the layer at `path` intersecting `bbox`, paged in OBJECTID
    order, generalized by `max_offset` degrees when given; and the exchanges' urls. An
    ArcGIS error object (answered with HTTP 200) is an `UpstreamServiceError`. With
    `geometry` false the features carry attributes only. A query that would read past
    ceil(`arcgis.max_features_per_layer` / `page`) pages is a `PageCapExceeded`
    (HB-89; review L3-2)."""
    offset, features, urls = 0, [], []
    max_pages = math.ceil(int(sources()["arcgis"]["max_features_per_layer"]) / page)
    extra = {} if max_offset is None else {"maxAllowableOffset": str(max_offset)}
    # The parameter order is the recorded URL's (a replay file is keyed by its URL).
    shape = (
        {
            "returnGeometry": "true",
            "outSR": "4326",
            "geometryPrecision": str(COORDINATE_DECIMALS),
        }
        if geometry
        else {"returnGeometry": "false"}
    )
    while True:
        if len(urls) >= max_pages:
            raise PageCapExceeded(
                f"{api} query reached its cap of {max_pages} pages of {page}; the "
                "footprint's bounding box holds too many features."
            )
        ex = await fetch_json(
            api,
            f"{path}/query",
            params=extra
            | {
                "where": where,
                "geometry": bbox,
                "geometryType": "esriGeometryEnvelope",
                "inSR": "4326",
                "spatialRel": "esriSpatialRelIntersects",
                "outFields": out_fields,
            }
            | shape
            | {
                "orderByFields": "OBJECTID",
                "resultOffset": str(offset),
                "resultRecordCount": str(page),
                "f": "geojson",
            },
        )
        urls.append(ex.url)
        body = ex.body if isinstance(ex.body, dict) else {}
        if "error" in body or "features" not in body:
            raise UpstreamServiceError(f"{api} returned an error object.")
        features += body["features"]
        more = body.get("exceededTransferLimit") or (body.get("properties") or {}).get(
            "exceededTransferLimit"
        )
        if not more and len(body["features"]) < page:
            return features, urls
        if not body["features"]:
            return features, urls
        offset += len(body["features"])


def _date(ms) -> str | None:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date().isoformat()


def _xy(g) -> list:
    return [round(g.x, COORDINATE_DECIMALS), round(g.y, COORDINATE_DECIMALS)]


#: The name printed for a structure whose NSD NAME is null (the schema allows it):
#: its type and permanent identifier, so the 201 names it and its receipt finds it
#: (review L2-7: alone it printed "None", grouped it raised TypeError).
UNNAMED = "Unnamed {type} ({source_id})"


def _unnamed(kind: str, p: dict) -> str:
    return UNNAMED.format(
        type=kind, source_id=p.get("permanent_identifier") or "no identifier"
    )


async def structures(category: str, a: Area) -> tuple[list, dict]:
    """The National Structures Dataset points of `category` inside the area."""
    s = sources()["structures"]
    bbox = envelope(a.shape)
    out, urls, candidates = [], [], 0
    for layer, layer_name in s["categories"][category].items():
        feats, u = await arcgis_features(
            s["api"],
            f"{s['service']}/{layer}",
            bbox,
            s["out_fields"],
            int(s["page_size"]),
        )
        urls += u
        candidates += len(feats)
        for f in feats:
            if not f.get("geometry"):
                continue
            g = geo.shape(f["geometry"])
            zone = zone_of(g, a)
            if zone is None:
                continue
            p = {k.lower(): v for k, v in (f.get("properties") or {}).items()}
            kind = s["fcode_types"].get(p.get("fcode"), layer_name)
            out.append(
                {
                    "name": p.get("name") or _unnamed(kind, p),
                    "type": kind,
                    "address": ", ".join(
                        str(p[k]) for k in ("address", "city", "state") if p.get(k)
                    )
                    or None,
                    "coordinates": _xy(g),
                    "zone": zone,
                    "source": s["label"],
                    "source_id": p.get("permanent_identifier"),
                    "layer": layer,
                    "as_of": _date(p.get("loaddate")),
                }
            )
    out.sort(key=lambda r: (r["zone"] != "isolation", r["name"]))
    query = {
        "service": s["service"],
        "layers": sorted(s["categories"][category]),
        "envelope": bbox,
        "candidates": candidates,
        "urls": urls,
    }
    return out, query


def _waterway_key(p: dict) -> str:
    """One waterway per named river or stream, else per 3DHP mainstem, else per
    feature: a flowline is a reach, and a river is many reaches."""
    return p.get("gnisidlabel") or p.get("mainstemid") or p.get("id3dhp")


async def flowlines_near(h: dict, a: Area) -> tuple[list, list]:
    """The attributes of every flowline within `search_m` of the area (HB-17), with the
    waterbody each runs through (`waterbodyid3dhp`) and its NHDPlus main-path
    attributes; and the exchanges' urls. The filter on the waterbody is applied here,
    not by the service: the field is not indexed, and a query on it timed out."""
    near = h["waterbodies"]["flowlines_through"]
    feats, urls = await arcgis_features(
        h["api"],
        f"{h['service']}/{h['flowlines']['layer']}",
        envelope(buffer(a.shape, float(near["search_m"]))),
        near["out_fields"],
        int(near["page_size"]),
        geometry=False,
    )
    return [f.get("properties") or {} for f in feats], urls


def main_path(through: list[dict]) -> dict | None:
    """The river a waterbody belongs to, among the flowlines that run through it: the
    main path by NHDPlus's rule, the lowest stream level (a tributary's level is its
    river's plus one), then the largest arbolate sum, then the lowest id for a stable
    answer [USGS NHDPlus HR User's Guide, StreamLevel and ArbolateSu]."""
    ranked = [t for t in through if t.get("streamlevel") is not None]
    if not ranked:
        return None
    return min(
        ranked,
        key=lambda t: (
            t["streamlevel"],
            -(t.get("arbolatesum") or 0.0),
            t.get("id3dhp") or "",
        ),
    )


async def waterways(a: Area) -> tuple[dict, dict]:
    h = sources()["hydrography"]
    bbox = envelope(a.shape)
    generalize = float(h["max_allowable_offset_deg"])
    fl, wb = h["flowlines"], h["waterbodies"]
    lines, u1 = await arcgis_features(
        h["api"],
        f"{h['service']}/{fl['layer']}",
        bbox,
        fl["out_fields"],
        int(fl.get("page_size", h["page_size"])),
        max_offset=generalize,
    )
    bodies, u2 = await arcgis_features(
        h["api"],
        f"{h['service']}/{wb['layer']}",
        bbox,
        wb["out_fields"],
        int(wb.get("page_size", h["page_size"])),
        max_offset=generalize,
    )
    iso = a.zones.get("isolation")
    by_flowline = set(h["waterbodies"]["counted_by_flowline"])
    flow: dict[str, dict] = {}
    inside_lines = []
    for f in lines:
        if not f.get("geometry"):
            continue
        g = geo.shape(f["geometry"])
        if not g.intersects(a.shape):
            continue
        inside = geodesic_length_m(g.intersection(a.shape))
        if inside <= 0:
            continue
        p = f.get("properties") or {}
        inside_lines.append(g)
        w = flow.setdefault(
            _waterway_key(p),
            {
                "name": p.get("gnisidlabel"),
                "kind": "flowline",
                "mainstem": p.get("mainstemid"),
                "length_inside_m": 0.0,
                "reaches": 0,
                "in_isolation_zone": False,
                "source_ids": [],
            },
        )
        w["length_inside_m"] += inside
        w["reaches"] += 1
        w["in_isolation_zone"] |= bool(iso is not None and g.intersects(iso))
        w["source_ids"].append(p.get("id3dhp"))
    # What a flowline inside already counts: its waterway key and its mainstem.
    counted_keys = set(flow) | {w["mainstem"] for w in flow.values() if w["mainstem"]}
    water, u3, near = [], [], None
    for f in bodies:
        if not f.get("geometry"):
            continue
        g = geo.shape(f["geometry"])
        if not g.intersects(a.shape):
            continue
        inside = geo.geodesic_area_m2(g.intersection(a.shape))
        if inside <= 0:
            continue
        p = f.get("properties") or {}
        name, name_source, counted = p.get("gnisidlabel"), "waterbody", True
        if p.get("featuretypelabel") in by_flowline:
            # A flowline inside the footprint that runs within the polygon counts it
            # (HB-10's rule, now tested per polygon); else the river is found and named
            # by the flowlines that run through the polygon near the footprint.
            footprint_water = g.intersection(a.shape)
            if any(
                line.intersection(footprint_water).length > 0 for line in inside_lines
            ):
                counted = False
            elif p.get("id3dhp"):
                if near is None:
                    near, u3 = await flowlines_near(h, a)
                field = h["waterbodies"]["flowlines_through"]["field"]
                trunk = main_path([t for t in near if t.get(field) == p["id3dhp"]])
                if trunk is not None:
                    keys = {_waterway_key(trunk), trunk.get("mainstemid")} - {None}
                    counted = not keys & counted_keys
                    if name is None and trunk.get("gnisidlabel"):
                        name, name_source = trunk["gnisidlabel"], "main_path"
        water.append(
            {
                "name": name,
                "name_source": name_source if name else None,
                "kind": "waterbody",
                "type": p.get("featuretypelabel"),
                "counted": counted,
                "area_inside_m2": round(inside),
                "in_isolation_zone": bool(iso is not None and g.intersects(iso)),
                "source_ids": [p.get("id3dhp")],
            }
        )
    flows = sorted(flow.values(), key=lambda w: -w["length_inside_m"])
    for w in flows:
        w["length_inside_m"] = round(w["length_inside_m"])
    water.sort(key=lambda w: -w["area_inside_m2"])
    result = {
        "flowlines": flows,
        "waterbodies": water,
        "named": sorted({w["name"] for w in flows + water if w["name"]}),
        "count": len(flows) + sum(1 for w in water if w["counted"]),
        "in_isolation_zone": any(w["in_isolation_zone"] for w in flows + water),
        "source": h["label"],
        "as_of": h["as_of"],
    }
    query = {
        "service": h["service"],
        "layers": [h["flowlines"]["layer"], h["waterbodies"]["layer"]],
        "envelope": bbox,
        "candidates": len(lines) + len(bodies),
        "urls": u1 + u2 + u3,
    }
    return result, query


async def rail(a: Area) -> tuple[dict, dict]:
    r = sources()["rail"]
    bbox = envelope(a.shape)
    page = int(r["page_size"])
    ln, cx = r["lines"], r["crossings"]
    arcs, u1 = await arcgis_features(
        r["api"], ln["service"], bbox, ln["out_fields"], page
    )
    xings, u2 = await arcgis_features(
        r["api"], cx["service"], bbox, cx["out_fields"], page
    )
    segments = []
    for f in arcs:
        if not f.get("geometry"):
            continue
        g = geo.shape(f["geometry"])
        zone = zone_of(g, a)
        if zone is None:
            continue
        inside = geodesic_length_m(g.intersection(a.shape))
        p = f.get("properties") or {}
        segments.append(
            {
                "owner": p.get("RROWNER1"),
                "subdivision": p.get("SUBDIV"),
                "yard": p.get("YARDNAME"),
                "tracks": p.get("TRACKS"),
                "length_inside_m": round(inside),
                "zone": zone,
                "source_id": p.get("FRAARCID"),
            }
        )
    crossings = []
    for f in xings:
        p = f.get("properties") or {}
        if p.get("CrossingPosition") != cx["at_grade"] or not f.get("geometry"):
            continue
        g = geo.shape(f["geometry"])
        if (g.x, g.y) == (
            0.0,
            0.0,
        ):  # relocated off-state crossings (layer description)
            continue
        zone = zone_of(g, a)
        if zone is None:
            continue
        crossings.append(
            {
                "crossing_id": p.get("CrossingID"),
                "type": p.get("CrossingType"),
                "road": p.get("HighwayName") or p.get("STREET"),
                "railroad": p.get("RailroadCode"),
                "coordinates": _xy(g),
                "zone": zone,
            }
        )
    segments.sort(key=lambda s: -s["length_inside_m"])
    crossings.sort(key=lambda c: c["crossing_id"] or "")
    result = {
        "segments": segments,
        "owners": sorted({s["owner"] for s in segments if s["owner"]}),
        "length_inside_m": sum(s["length_inside_m"] for s in segments),
        "crossings": crossings,
        "source": {"lines": ln["label"], "crossings": cx["label"]},
        "as_of": {"lines": ln["as_of"], "crossings": cx["as_of"]},
    }
    query = {
        "layers": [ln["service"], cx["service"]],
        "envelope": bbox,
        "candidates": len(arcs) + len(xings),
        "urls": u1 + u2,
    }
    return result, query


# ── CMS files ─────────────────────────────────────────────────────────────────


@lru_cache(maxsize=4)
def cms_file(which: str) -> dict:
    """The cached file of `which` ("hospitals" or "nursing_homes"), with its meta."""
    path = Path(settings.hazbrief_cms_dir) / sources()["cms"][which]["file"]
    if not path.is_file():
        # The directory is named by its setting, not its path: facilities_in_footprint
        # and receiving_hospitals return this message to the client (HB-89; L3-5).
        raise CmsFileMissing(
            f"{path.name} is not in the CMS directory (HAZBRIEF_CMS_DIR); build it "
            "with `uv run python scripts/fetch_cms.py`."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def nursing_homes(a: Area) -> tuple[list, dict]:
    doc = cms_file("nursing_homes")
    meta = doc["meta"]
    minx, miny, maxx, maxy = a.shape.bounds
    out = []
    for r in doc["nursing_homes"]:
        lat, lon = r.get("latitude"), r.get("longitude")
        if (
            lat is None
            or lon is None
            or not (minx <= lon <= maxx and miny <= lat <= maxy)
        ):
            continue
        g = Point(lon, lat)
        zone = zone_of(g, a)
        if zone is None:
            continue
        out.append(
            {
                "name": r["name"],
                "type": r["type"],
                "address": f"{r['address']}, {r['city']}, {r['state']}",
                "beds": r["beds"],
                "coordinates": _xy(g),
                "zone": zone,
                "source": meta["source"],
                "source_id": r["ccn"],
                "as_of": meta["as_of"],
            }
        )
    out.sort(key=lambda r: (r["zone"] != "isolation", r["name"]))
    return out, meta
