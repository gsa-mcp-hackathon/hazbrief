"""The place at the spill, from TIGERweb (HB-11b step 4): the incorporated place or
census designated place the point lies in, if any, and its county and state.

Data source: TIGERweb `tigerWMS_Current/MapServer` (ics201.yaml `place`: the layers, and
the vintage its service description states, "January 1, 2026 vintage"). Two calls: an
`identify` on the places layers at the point, then a `query` on the counties layer at
the point, which also returns the county's outline for the Block 4 sketch. Both go
through `fetch_json`, so they record and replay like every other exchange (DN-005
section 2). Update cadence: the service's annual vintage; as-of: that vintage.

A failure is never fatal to the briefing: `locate` returns what it found and lists
what failed in `errors`, and `build_ics_201` then names the incident by its coordinates
and says so in Annex A.
"""

from __future__ import annotations

from hazbrief import ics201
from hazbrief.geometry import COORDINATE_DECIMALS
from hazbrief.lodes import STATE_POSTAL
from hazbrief.utils import UpstreamServiceError, fetch_json


def _blank(cfg: dict) -> dict:
    return {
        "service": f"TIGERweb/{cfg['service']}",
        "vintage": cfg["vintage"],
        "tag": f"[TIGERweb {cfg['vintage']}]",
        "place": None,
        "county": None,
        "outline": None,
        "urls": [],
        "errors": [],
    }


def failed(message: str) -> dict:
    """The answer when TIGERweb could not be read: nothing found, the reason listed."""
    out = _blank(ics201.config()["place"])
    out["errors"].append(message)
    return out


def _body(ex) -> dict:
    body = ex.body if isinstance(ex.body, dict) else {}
    if "error" in body:
        # TIGERweb answers an error object with HTTP 200 (corpus/api_catalog.yaml).
        raise UpstreamServiceError("TIGERweb returned an error object.")
    return body


async def _place(lat: float, lon: float, cfg: dict, out: dict) -> None:
    half = cfg["identify_half_extent_deg"]
    layers = {int(k): v for k, v in cfg["places_layers"].items()}
    ex = await fetch_json(
        "tigerweb",
        f"{cfg['service']}/identify",
        params={
            "geometry": f"{lon},{lat}",
            "geometryType": "esriGeometryPoint",
            "sr": "4326",
            "layers": "all:" + ",".join(str(k) for k in layers),
            "tolerance": "0",
            # at the footprint's six decimals, so the url (and its recorded exchange)
            # carries no floating-point noise
            "mapExtent": ",".join(
                f"{v:.{COORDINATE_DECIMALS}f}"
                for v in (lon - half, lat - half, lon + half, lat + half)
            ),
            "imageDisplay": cfg["identify_image"],
            "returnGeometry": "false",
            "f": "json",
        },
    )
    out["urls"].append(ex.url)
    body = _body(ex)
    if "results" not in body:
        raise UpstreamServiceError("TIGERweb identify returned no results list.")
    # the configured layer order decides between an incorporated place and a CDP
    hits = sorted(
        (r for r in body["results"] if r.get("layerId") in layers),
        key=lambda r: list(layers).index(r["layerId"]),
    )
    if hits:
        a = hits[0]["attributes"]
        out["place"] = {
            "name": a["NAME"],
            "basename": a["BASENAME"],
            "geoid": a["GEOID"],
            "layer": layers[hits[0]["layerId"]],
        }


async def _county(lat: float, lon: float, cfg: dict, out: dict) -> None:
    ex = await fetch_json(
        "tigerweb",
        f"{cfg['service']}/{cfg['counties_layer']}/query",
        params={
            "geometry": f"{lon},{lat}",
            "geometryType": "esriGeometryPoint",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "GEOID,STATE,COUNTY,NAME,BASENAME",
            "returnGeometry": "true",
            "outSR": "4326",
            "maxAllowableOffset": str(cfg["outline_offset_deg"]),
            "geometryPrecision": str(COORDINATE_DECIMALS),
            "f": "geojson",
        },
    )
    out["urls"].append(ex.url)
    body = _body(ex)
    if "features" not in body:
        raise UpstreamServiceError("TIGERweb query returned no features list.")
    if not body["features"]:
        return
    f = body["features"][0]
    p = f["properties"]
    state = STATE_POSTAL.get(str(p["STATE"]))
    out["county"] = {
        "name": p["NAME"],
        "basename": p["BASENAME"],
        "geoid": str(p["GEOID"]),
        "state_fips": str(p["STATE"]),
        "state": state.upper() if state else None,
        "layer": cfg["counties_layer_name"],
    }
    out["outline"] = f.get("geometry")


async def locate(lat: float, lon: float) -> dict:
    """`{service, vintage, tag, place, county, outline, urls, errors}` at the point.
    `place` and `county` are None where TIGERweb finds none (a point in open water has
    no county) or where its call failed; each failure is a line in `errors`."""
    cfg = ics201.config()["place"]
    out = _blank(cfg)
    for step in (_place, _county):
        try:
            await step(lat, lon, cfg, out)
        except UpstreamServiceError as exc:
            out["errors"].append(f"{step.__name__.strip('_')}: {exc}")
    return out
