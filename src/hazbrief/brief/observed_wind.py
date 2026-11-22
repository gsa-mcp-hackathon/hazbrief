"""The observed wind: one representative NWS station, the others a spread (HB-143).

`weather.source: observed` (DN-019 ADDENDUM-01; HB-139's selection, `weather_source`)
reads the live NWS station observations, the source catalog's `nws:observations` row,
recorded per brief like every live call (DN-011 D7: a replayed brief reads the records).

**The method** was chosen from the prior art before any code
(`docs/evidence/hb143/prior_art.md`; it replaces `hazbrief-mcp:HBD-275`):
* every held engine takes one wind, uniform over the area (ALOHA user's manual PDF
  p. 29; technical documentation PDF p. 12; SLAB's UA);
* EPA's guidance for a steady-state run takes one site, "as close as possible to the
  source in question" (EPA-454/R-99-005, `epa-mmgrma-1999`, section 3.5, PDF p. 40);
* blending several sites is the work of gridded field analyses (Cressman 1959, Barnes
  1964, Shepard 1968; cited by title, not held), which with two or three stations
  reduce to a weighted mean no anemometer measured.

So the record is the wind of the nearest of the `stations` nearest NWS stations whose
latest observation reports a wind within `tolerance_minutes` of the brief's hour. The
other stations are carried as a **spread**: the smallest arc that holds their bearings
(`arc`, which never averages a bearing) and the range of their speeds. A calm
observation is a true one (FMH-1 section 5.5.2; Issue 473bdfeb): it enters the spread
at speed 0 with no bearing, and a calm representative station gives a calm record.
Fewer than `min_stations` fresh stations: no record here, and `wind_record` falls back
to the forecast cell with the reason on the first screen (HB-143 item 3; Issue
94309222 carries the departure from DN-019 ADDENDUM-01's no-fallback rule).

**The stations** are read as HB-60 reads the nearest one (`derive.fetch_observation`):
NWS `points` at the point, the `observationStations` url it names (the gridpoint's
station list; the held OpenAPI 3.12.2 has no `/points/{point}/stations`), and each
chosen station's `observations/latest`. Distance is geodesic from the point
(`facilities.inverse`), ties to the lower station id.
"""

from __future__ import annotations

from typing import Any

from hazbrief.evidence import store as S
from hazbrief.utils import Exchange, UpstreamServiceError


def _spec(cfg: dict) -> dict:
    return cfg["weather"]["observed_client"]


def arc(bearings: list[float]) -> dict | None:
    """The smallest arc, clockwise from `from_deg` to `to_deg`, that holds every
    bearing (degrees the wind blows from), and its width. Bearings are never averaged:
    350 and 010 give the 20 degrees through north, not 340 through south. None: no
    bearing (every station calm or none read). Ties between equal largest gaps go to
    the gap after the lowest bearing, so the answer is deterministic."""
    b = sorted({round(float(x) % 360.0, 6) for x in bearings})
    if not b:
        return None
    if len(b) == 1:
        return {"from_deg": b[0], "to_deg": b[0], "width_deg": 0.0}
    n = len(b)
    gaps = [((b[(i + 1) % n] - b[i]) % 360.0, i) for i in range(n)]
    gap, i = max(gaps, key=lambda t: (t[0], -t[1]))
    return {
        "from_deg": b[(i + 1) % n],
        "to_deg": b[i],
        "width_deg": round(360.0 - gap, 6),
    }


def nearest(
    stations: Exchange, lat: float, lon: float, n: int
) -> list[tuple[dict, float]]:
    """The `n` stations of an NWS station list nearest (lat, lon), geodesic, with their
    distance in metres; ties to the lower station id (`derive.nearest_station`'s
    order, extended to n)."""
    from hazbrief import facilities
    from hazbrief.brief.derive import DeriveError

    feats = (
        (stations.body or {}).get("features")
        if isinstance(stations.body, dict)
        else None
    )
    if stations.status != 200 or not feats:
        raise DeriveError(f"NWS stations answered {stations.status} with no station")
    ranked = []
    for f in feats:
        x, y = f["geometry"]["coordinates"][:2]
        m, _ = facilities.inverse(lat, lon, y, x)
        ranked.append((m, f["properties"]["stationIdentifier"], f))
    ranked.sort(key=lambda t: (t[0], t[1]))
    return [(f, m) for m, _, f in ranked[:n]]


def reading(
    station: dict, metres: float, obs: Exchange | None, why: str | None
) -> dict:
    """One station's latest observation as the method reads it: id, name, distance,
    observation time and wind (km/h, degrees from; None where not reported). `why` is
    the reason the observation is not held (no exchange)."""
    from hazbrief.brief.derive import _quantity

    sp = station["properties"]
    out: dict[str, Any] = {
        "station": sp["stationIdentifier"],
        "name": sp.get("name"),
        "distance_km": round(metres / 1000, 1),
        "observed_at": None,
        "wind_from_deg": None,
        "wind_kmh": None,
        "not_held": why,
    }
    if obs is None:
        return out
    body = obs.body if isinstance(obs.body, dict) else {}
    p = body.get("properties") or {}
    if obs.status != 200 or not p.get("timestamp"):
        out["not_held"] = f"NWS answered {obs.status} with no timestamp"
        return out
    ms = _quantity(p.get("windSpeed"), "wmoUnit:m_s-1")
    out["observed_at"] = S.parse_time(p["timestamp"]).isoformat()
    out["wind_kmh"] = None if ms is None else round(ms * 3.6, 1)
    out["wind_from_deg"] = _quantity(p.get("windDirection"), "wmoUnit:degree_(angle)")
    return out


def _span(seconds: float) -> str:
    from hazbrief.brief.derive import _span as span

    return span(seconds)


def choose(readings: list[dict], when, observed: dict, cfg: dict) -> dict:
    """The method on read stations (pure): each station marked used or dropped with
    its reason, the representative station (the nearest used one), the spread over the
    used ones, and `reason` when fewer than `min_stations` are used. `when` is the
    brief's hour (aware datetime); `observed` is the selection's `observed` block."""
    spec = _spec(cfg)
    tol = int(observed["tolerance_minutes"])
    out_rows: list[dict] = []
    used: list[dict] = []
    for r in sorted(readings, key=lambda r: (r["distance_km"], r["station"])):
        row = dict(r)
        why = None
        if r.get("not_held"):
            why = spec["reasons"]["no_answer"].format(why=r["not_held"])
        else:
            age = (when - S.parse_time(r["observed_at"])).total_seconds()
            if abs(age) > tol * 60:
                why = spec["reasons"]["stale"].format(
                    span=_span(abs(age)),
                    side="before" if age > 0 else "after",
                    tol=tol,
                )
            elif r["wind_kmh"] is None:
                why = spec["reasons"]["no_wind"]
            elif r["wind_kmh"] > 0 and r["wind_from_deg"] is None:
                why = spec["reasons"]["variable"].format(kmh=r["wind_kmh"])
        row["calm"] = why is None and float(r["wind_kmh"]) == 0.0
        row["used"] = why is None
        row["dropped"] = why
        out_rows.append(row)
        if why is None:
            used.append(row)
    need = int(observed["min_stations"])
    result: dict[str, Any] = {
        "stations": out_rows,
        "representative": None,
        "spread": None,
        "reason": None,
        "method": spec["method"].format(tol=tol),
    }
    if len(used) < need:
        result["reason"] = spec["too_few"].format(
            fresh=len(used), n=len(out_rows), tol=tol, hour=when.isoformat(), need=need
        )
        return result
    result["representative"] = used[0]
    kmh = [float(r["wind_kmh"]) for r in used]
    result["spread"] = {
        "n": len(used),
        "calm": sum(1 for r in used if r["calm"]),
        "arc": arc([r["wind_from_deg"] for r in used if not r["calm"]]),
        "kmh_min": min(kmh),
        "kmh_max": max(kmh),
    }
    return result


async def fetch(lat: float, lon: float, n: int) -> tuple[list[Exchange], list[dict]]:
    """The exchanges read (points, the station list, each station's latest
    observation) and the `n` nearest stations' readings. A station whose observation
    cannot be read is a reading with its reason, not a failure of the rest
    (standards section 4: failures are rows)."""
    from hazbrief import nws
    from hazbrief.brief.derive import DeriveError, _why, fetch_json
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
    exchanges = [points, stations]
    readings = []
    for station, metres in nearest(stations, lat, lon, n):
        sid = station["properties"]["stationIdentifier"]
        try:
            obs = await fetch_json(
                nws.API, f"stations/{sid}/observations/latest", headers=headers
            )
        except (DeriveError, UpstreamServiceError) as exc:
            readings.append(reading(station, metres, None, _why(exc)))
            continue
        exchanges.append(obs)
        readings.append(reading(station, metres, obs, None))
    return exchanges, readings


async def read(
    point: tuple[float, float] | None, when, observed: dict, cfg: dict
) -> dict:
    """`choose` on the stations read now (or replayed) at `point`, with what was read
    (`sources`). A station list that cannot be read is the result's `reason`, with no
    station: the record then falls back as below the minimum."""
    from hazbrief.brief.derive import DeriveError, _sources, _why

    spec = _spec(cfg)

    def none_read(why: str) -> dict:
        return {
            "stations": [],
            "representative": None,
            "spread": None,
            "reason": spec["no_stations"].format(why=why),
            "sources": [],
            "method": spec["method"].format(tol=observed["tolerance_minutes"]),
        }

    if point is None:
        return none_read("the brief holds no incident point")
    try:
        exchanges, readings = await fetch(point[0], point[1], int(observed["stations"]))
    except (DeriveError, UpstreamServiceError) as exc:
        return none_read(_why(exc))
    out = choose(readings, when, observed, cfg)
    out["sources"] = _sources(exchanges)
    return out
