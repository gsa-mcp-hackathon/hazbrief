"""`receiving_hospitals`: hospitals with emergency services outside the footprint,
nearest first (HB-10; DN-001 sections 2, 6; DN-005 section 1 item 3).

The hospitals are CMS Hospital General Information rows that report emergency
services, joined to Provider of Services beds and placed once by address
(`scripts/fetch_cms.py`). Distance is straight-line and geodesic on WGS84, measured from
the footprint's **upwind edge**: the point where the ray upwind from the spill leaves
the footprint's union (review L2-3), where the ERG approach from upwind leaves the
footprint, past a guide's fire circle or a larger candidate's isolation circle. A
footprint without zone properties has no upwind edge, so distances are measured from
the spill and the output says so.

A hospital inside the footprint is a casualty site, not a receiver (FR-HOSP-01); it is
listed under `inside_footprint` and never ranked. A ranked hospital is flagged
`crosses_footprint` when the straight line from the upwind edge to it runs through the
protective action zone outside the isolation zone, by more than a tolerance
(`facilities_sources.yaml` `receiving`). The line is drawn from the upwind edge, not the
spill: every line from the spill starts inside the zone, so from there every hospital
not upwind would be flagged, while casualties leave the zone from upwind. A line from
the edge that heads at all downwind cuts the isolation circle it starts on, so that
part is reported (`line_in_isolation_zone_m`) and not counted. Without an upwind edge,
crossing is not assessed (null). No road network is read (the HB-10 task: no routing
engine); a flagged hospital may still have a road around the zone, and an unflagged one
may not.
"""

from __future__ import annotations

import math

from shapely.geometry import LineString, Point

from hazbrief import facilities, geometry
from hazbrief.facilities import CmsFileMissing
from hazbrief.geometry import GeometryError
from hazbrief.incident import basis
from hazbrief.models import ReceivingInput, with_notices

#: Eight compass points, from north clockwise.
COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
LIMITS = (
    "Distances are straight lines from the footprint's upwind edge, not drive times.",
    "Trauma level, burn care and toxicology capability are not in these datasets; "
    "confirm capability with each hospital.",
    "Hospitals listed are those registered with Medicare that report emergency "
    "services [CMS Hospital General Information].",
    "Emergency services means the hospital reports providing them, not that it has "
    "capacity now [CMS Hospital General Information].",
    "Bed counts are the Provider of Services bed counts, not beds available now [CMS "
    "Provider of Services].",
    "A hospital is flagged when the straight line to it from the upwind edge crosses "
    "the protective action zone.",
    "Roads are not read, so a flagged hospital may have a route around the zone.",
)
UNPLACED_LIMIT = "unplaced_in_states names the unplaced hospitals in each state listed."
FROM_SPILL_LIMIT = (
    "The footprint has no zone properties, so distances are measured from the spill "
    "and crossing the footprint is not assessed."
)
#: HB-17: a guide-only footprint has zones (the initial isolation zone, the guide's
#: circles) but no protective action zone, so no downwind edge to measure from.
NO_PROTECTIVE_ACTION_ZONE_LIMIT = (
    "The footprint has no protective action zone, so distances are measured from the "
    "spill, with no crossing test."
)


def compass(bearing: float) -> str:
    """The nearest of the eight points; a boundary bearing goes to the next point
    clockwise (half-up with wrap, review L2-8)."""
    return COMPASS[math.floor((bearing % 360) / 45 + 0.5) % 8]


def whole_degrees(bearing: float) -> int:
    """A bearing to the nearest degree, half-up, in 0-359: 359.6 prints 0, never 360
    (review L2-8)."""
    return math.floor(bearing % 360 + 0.5) % 360


def _downwind_bearing(footprint: dict) -> float | None:
    for f in footprint.get("features") or [] if isinstance(footprint, dict) else []:
        p = (f or {}).get("properties") or {}
        if p.get("zone") == "protective_action_zone":
            return p.get("downwind_bearing_deg")
    return None


def upwind_edge(
    footprint: dict, spill: Point, a: facilities.Area | None = None
) -> tuple[Point, str]:
    """The upwind edge: the point where the ray upwind from the spill leaves the
    footprint's union (review L2-3), so a guide's fire circle or a larger candidate's
    isolation circle is crossed, not stopped inside. The spill when the footprint
    carries no downwind bearing or the spill is not inside it."""
    bearing = _downwind_bearing(footprint)
    if bearing is None:
        return spill, "spill"
    a = a if a is not None else facilities.area(footprint)
    back = (bearing + 180) % 360
    # A ray longer than the footprint: past the farthest corner of its bounding box,
    # and a line step more.
    minx, miny, maxx, maxy = a.shape.bounds
    step = float(facilities.sources()["receiving"]["line_step_m"])
    reach = step + max(
        facilities.inverse(spill.y, spill.x, y, x)[0]
        for x in (minx, maxx)
        for y in (miny, maxy)
    )
    ray = facilities.geodesic_line(
        spill, facilities.destination(spill.y, spill.x, back, reach), step
    )
    pieces = ray.intersection(a.shape)
    lines = [
        g
        for g in getattr(pieces, "geoms", [pieces])
        if isinstance(g, LineString) and not g.is_empty
    ]
    # the piece that starts at the spill; its far end is where the ray leaves
    first = [g for g in lines if ray.project(Point(g.coords[0])) == 0.0]
    if not first:
        return spill, "spill"
    x, y, *_ = first[0].coords[-1]
    return Point(
        round(x, geometry.COORDINATE_DECIMALS), round(y, geometry.COORDINATE_DECIMALS)
    ), "upwind_edge"


def _unplaced_in(states: set, doc: dict) -> dict:
    out: dict[str, list] = {}
    for h in doc["hospitals"]:
        if h["latitude"] is None and h["state"] in states:
            out.setdefault(h["state"], []).append(f"{h['name']}, {h['city']}")
    return {s: sorted(v) for s, v in sorted(out.items())}


async def rank(req: ReceivingInput) -> dict:
    try:
        a = facilities.area(req.footprint)
    except GeometryError as exc:
        return {
            "error": f"The footprint cannot be read: {exc}.",
            "hint": "Pass the `footprint` GeoJSON protective_action_footprint returns.",
        }
    cfg = facilities.sources()["receiving"]
    try:
        doc = facilities.cms_file("hospitals")
    except CmsFileMissing as exc:
        return {"error": str(exc), "hint": "Run scripts/fetch_cms.py."}
    meta = doc["meta"]
    max_km = req.max_km or float(cfg["max_km"])
    tolerance = float(cfg["crossing_tolerance_m"])
    spill = Point(req.location.longitude, req.location.latitude)
    origin, origin_kind = upwind_edge(req.footprint, spill, a)
    iso = a.zones.get("isolation")
    if iso is None or "protective_action" not in a.zones:
        origin, origin_kind = spill, "spill"
    else:
        downwind = a.zones["protective_action"].difference(iso)

    ranked, inside, states = [], [], set()
    for h in doc["hospitals"]:
        if h["latitude"] is None:
            continue
        metres, bearing = facilities.inverse(
            origin.y, origin.x, h["latitude"], h["longitude"]
        )
        if metres > max_km * 1000:
            continue
        p = Point(h["longitude"], h["latitude"])
        states.add(h["state"])
        row = {
            "name": h["name"],
            "address": f"{h['address']}, {h['city']}, {h['state']} {h['zip']}",
            "type": h["type"],
            "beds": h["beds"],
            "coordinates": [h["longitude"], h["latitude"]],
            "ccn": h["ccn"],
            "placed_by": h.get("geocode_input"),
        }
        zone = facilities.zone_of(p, a)
        if zone is not None:
            inside.append(row | {"zone": zone})
            continue
        through = in_iso = None
        if origin_kind == "upwind_edge":
            line = facilities.geodesic_line(origin, p, float(cfg["line_step_m"]))
            through = round(facilities.geodesic_length_m(line.intersection(downwind)))
            in_iso = round(facilities.geodesic_length_m(line.intersection(iso)))
        ranked.append(
            row
            | {
                "distance_km": round(metres / 1000, 1),
                "bearing_deg": whole_degrees(bearing),
                "direction": compass(bearing),
                "crosses_footprint": None if through is None else through > tolerance,
                "line_in_protective_action_zone_m": through,
                "line_in_isolation_zone_m": in_iso,
            }
        )
    ranked.sort(key=lambda r: (r["distance_km"], r["name"]))
    limit = int(cfg["limit"])
    g = meta["geocode"]
    limits = list(LIMITS)
    if origin_kind == "spill":
        limits[0] = "Distances are straight lines from the spill, not drive times."
        limits.append(NO_PROTECTIVE_ACTION_ZONE_LIMIT if a.zones else FROM_SPILL_LIMIT)
    limits += [
        f"{g['unmatched']:,} hospitals could not be placed by address and are not "
        f"ranked, of {g['submitted']:,} hospitals with emergency services [CMS "
        f"Hospital General Information, as of {meta['as_of']}].",
        UNPLACED_LIMIT,
    ]
    return {
        "hospitals": ranked[:limit],
        "more": max(0, len(ranked) - limit),
        "inside_footprint": inside,
        "measured_from": {
            "kind": origin_kind,
            "coordinates": [origin.x, origin.y],
        },
        "max_km": max_km,
        "unplaced_in_states": _unplaced_in(states, doc),
        "basis": [
            basis(
                "hospitals and emergency services",
                f"{meta['source']}, as of {meta['as_of']}",
                None,
            ),
            basis("beds", f"{meta['beds_source']}, as of {meta['beds_as_of']}", None),
            basis(
                "hospital locations",
                # HB-94 (review L5-2): the locations were placed when the file was
                # built, so the tag carries that date, not the call's
                f"{meta['geocoder']}; USGS National Structures Dataset by address, "
                f"as of {meta['built_at'][:10]}",
                None,
            ),
        ],
        "limits": limits,
    }


def register(mcp) -> None:
    facilities.sources()

    @mcp.tool(
        name="receiving_hospitals",
        annotations={
            "title": "Receiving Hospitals",
            "readOnlyHint": True,
            "openWorldHint": False,
        },
    )
    async def receiving_hospitals(incident: ReceivingInput) -> dict:
        """Hospitals with emergency services outside the footprint, nearest first by
        straight-line distance from the footprint's upwind edge, with beds, type,
        distance, bearing, and `crosses_footprint` when the straight line from that
        edge runs through the footprint (a hospital reached only through the zone).
        Hospitals inside the footprint are listed apart, as casualty sites.

        Pass `incident.location` (the spill point), `incident.footprint` (the GeoJSON
        protective_action_footprint returns) and optionally `max_km` (50 km by
        default). Distances are straight-line, not drive time; trauma level and burn
        or toxicology capability are not in these datasets.

        Data sources: CMS Hospital General Information (emergency services, type)
        joined to CMS Provider of Services (beds) on the CCN, placed by the Census
        Geocoder and, where it fails, by the USGS National Structures Dataset hospital
        at the same address (a file cached by scripts/fetch_cms.py; no call per
        incident). Update cadence: CMS quarterly. As-of: the `basis` source tags.
        """
        return with_notices(await rank(incident), incident=incident)
