"""Wind at a point and time from the National Weather Service API (DN-005 section 3).

Data source: api.weather.gov. `/points/{lat},{lon}` names the forecast office grid cell
that holds the point; the forecast grid (`/gridpoints/{office}/{x},{y}`) carries the
wind speed and the direction the wind blows from as time series, each value valid over
an ISO 8601 interval. Update cadence: the office revises the grid through the day; the
grid's `updateTime` says when. As-of: the grid's `updateTime` and the response's Date,
Last-Modified, Expires and Cache-Control headers, all returned with the wind.

The wind is the grid value whose interval holds the incident time. For an incident
happening now that is the current period. An incident time the grid does not cover (in
the past, or beyond the forecast) is refused, never filled from the nearest period.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from hazbrief.utils import (
    Exchange,
    UpstreamServiceError,
    fetch_json,
    relative_to_origin,
)

API = "nws"
#: GeoJSON is the API's default; asked for explicitly so a format change is visible.
ACCEPT = "application/geo+json"
#: The units the grid states (`uom`), and the factor to km/h. Any other unit is refused.
SPEED_TO_KMH = {"wmoUnit:km_h-1": 1.0, "wmoUnit:m_s-1": 3.6}
DIRECTION_UOM = "wmoUnit:degree_(angle)"

_DURATION = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?$")


class WindUnavailable(RuntimeError):
    """The grid has no usable wind for the time asked; the caller should supply one."""


@dataclass(frozen=True)
class NwsWind:
    speed_kmh: float
    direction_deg_from: float
    valid_from: datetime
    valid_to: datetime
    #: the forecast office and grid cell, "LWX/96,70"
    grid: str
    time_zone: str | None
    update_time: str | None
    points: Exchange
    gridpoint: Exchange


def coordinate(value: float) -> str:
    """A coordinate as the points endpoint takes it: at most four decimals, no trailing
    zeros (the API answers a longer form with a redirect, which the client does not
    follow)."""
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def parse_interval(valid_time: str) -> tuple[datetime, datetime]:
    """`2026-10-21T03:00:00+00:00/PT2H` -> (start, end)."""
    try:
        start_text, duration = valid_time.split("/")
        start = datetime.fromisoformat(start_text)
    except ValueError:
        # SECURITY.md section 2: the message names the field, never its upstream value
        # (review L3-4)
        raise UpstreamServiceError("NWS grid validTime is not an interval.") from None
    m = _DURATION.match(duration)
    if not m or not any(m.groups()) or start.tzinfo is None:
        raise UpstreamServiceError("NWS grid validTime is not readable.")
    days, hours, minutes = (int(g or 0) for g in m.groups())
    return start, start + timedelta(days=days, hours=hours, minutes=minutes)


def _valid_time(v) -> str:
    """A grid value's `validTime`; a value without one is the API's failure, not a
    KeyError (review L2-13)."""
    t = v.get("validTime") if isinstance(v, dict) else None
    if not isinstance(t, str):
        raise UpstreamServiceError("NWS grid value has no validTime.")
    return t


def value_at(
    layer: dict, when: datetime, name: str
) -> tuple[float, datetime, datetime]:
    """The value of a grid layer whose interval holds `when` (start inclusive)."""
    try:
        values = layer["values"]
    except (KeyError, TypeError):
        raise UpstreamServiceError(f"NWS grid has no {name} values.") from None
    for v in values:
        start, end = parse_interval(_valid_time(v))
        if start <= when < end:
            if v.get("value") is None:
                raise WindUnavailable(
                    f"The NWS grid gives no {name} for {when.isoformat()}."
                )
            return float(v["value"]), start, end
    first = parse_interval(_valid_time(values[0]))[0] if values else None
    last = parse_interval(_valid_time(values[-1]))[1] if values else None
    raise WindUnavailable(
        f"The NWS forecast grid covers {name} from "
        f"{first.isoformat() if first else 'nothing'} to "
        f"{last.isoformat() if last else 'nothing'}; it does not cover "
        f"{when.isoformat()}."
    )


def _properties(ex: Exchange, what: str) -> dict:
    props = ex.body.get("properties") if isinstance(ex.body, dict) else None
    if not isinstance(props, dict):
        raise UpstreamServiceError(f"NWS {what} response has no properties.")
    return props


#: HB-18 (A-2): the source tag of a time zone read from the points endpoint.
POINTS_SOURCE = "NWS api.weather.gov points"


async def time_zone_at(latitude: float, longitude: float) -> tuple[str, str]:
    """The IANA time zone NWS gives for the point (the points endpoint's `timeZone`),
    and the url read. The same request `wind_at` makes first, so a point whose wind
    was read from the grid replays it from the same recording.

    Raises:
        UpstreamServiceError: the API failed or named no time zone.
    """
    points = await fetch_json(
        API,
        f"points/{coordinate(latitude)},{coordinate(longitude)}",
        headers={"Accept": ACCEPT},
    )
    zone = _properties(points, "points").get("timeZone")
    if not isinstance(zone, str):
        raise UpstreamServiceError("NWS points response names no time zone.")
    return zone, points.url


async def wind_at(latitude: float, longitude: float, when: datetime) -> NwsWind:
    """The forecast wind at the point for the grid period holding `when`.

    Raises:
        WindUnavailable: the grid has no wind for that time.
        UpstreamServiceError: the API failed or answered in an unexpected form.
    """
    headers = {"Accept": ACCEPT}
    points = await fetch_json(
        API, f"points/{coordinate(latitude)},{coordinate(longitude)}", headers=headers
    )
    pp = _properties(points, "points")
    grid_url = pp.get("forecastGridData")
    if not isinstance(grid_url, str):
        raise UpstreamServiceError("NWS points response names no forecast grid.")
    gridpoint = await fetch_json(
        API, relative_to_origin(API, grid_url), headers=headers
    )
    gp = _properties(gridpoint, "gridpoint")

    speed_layer, dir_layer = gp.get("windSpeed"), gp.get("windDirection")
    if not isinstance(speed_layer, dict) or not isinstance(dir_layer, dict):
        raise UpstreamServiceError("NWS grid has no windSpeed or windDirection.")
    factor = SPEED_TO_KMH.get(speed_layer.get("uom"))
    if factor is None:
        raise UpstreamServiceError("NWS grid windSpeed is not in a known unit.")
    if dir_layer.get("uom") != DIRECTION_UOM:
        raise UpstreamServiceError("NWS grid windDirection is not in degrees.")
    speed, s0, s1 = value_at(speed_layer, when, "wind speed")
    direction, d0, d1 = value_at(dir_layer, when, "wind direction")
    return NwsWind(
        speed_kmh=speed * factor,
        direction_deg_from=direction % 360.0,
        # The two layers are reported over their own intervals; the wind holds over
        # both.
        valid_from=max(s0, d0),
        valid_to=min(s1, d1),
        grid=f"{pp.get('gridId')}/{pp.get('gridX')},{pp.get('gridY')}",
        time_zone=pp.get("timeZone"),
        update_time=gp.get("updateTime"),
        points=points,
        gridpoint=gridpoint,
    )
