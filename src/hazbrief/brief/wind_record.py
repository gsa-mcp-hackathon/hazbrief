"""One brief, one wind (HB-133; Issue 90ac45af; DN-019 section 1, DN-011 D2).

The brief resolves one wind record, once, before any channel is called and before any
layer draws, and every consumer reads that record and no other:

* the ERG footprint's orientation, through the request the brief sends the server
  (`request_scenario`), and so the footprint wind arrow, the first-actions wind line,
  the footprint section's wind row, the wind field's footprint arrow;
* the wind strip's first ("Footprint") cell and the veer/back flag (`derive._hb56`);
* the stability class's wind speed (`derive._hb57`);
* the puff's wind (`derive.puff`), and through it the dense-gas deck and the smoke
  layer's wind.

**Which record.** The held NWS gridpoint forecast's cell at the as-given hour when one
is held (the forecast window's hour 0, `derive.forecast_window`); otherwise the
scenario's stated wind (its request `wind`, else its `stated_wind` block), labelled
"stated wind, no forecast held for <hour>"; otherwise none, and nothing modelled draws.
A stated wind given beside a held forecast is not used, and the record says so.

**The weather source** (DN-019 ADDENDUM-01; HB-139; `weather_source`). The above is the
`forecast` source, the default. Under `stated` the record is the selection's stated
block (`from_stated`: direction, speed, stability class, mixing height and basis), and
the request always carries it. Under `observed` (HB-143) the record is one
representative NWS station's latest observation, with the others as a spread
(`from_observed`; `observed_wind`), and the request carries it too; below the minimum
it is the forecast cell with the reason printed. `label` prints the record's source in
the addendum's three forms on the first screen; a calm record is a true record
(`is_calm`; Issue 473bdfeb), named by each model that cannot run on it, and nothing
replaces it.

**The request.** The record orients the served footprint. When the scenario gives the
server a wind (a fixture's worked example wind) and the record is the forecast cell, the
brief sends the record in its place. When the scenario gives none, the server reads the
NWS gridpoint at the incident time itself: the same request the forecast was read with,
so the same answer (`derive.fetch_forecast`'s docstring). When the record is a stated
wind, the scenario's own wind is sent unchanged.

**The check** (`disagreements`). After the footprint lands and after the derivations
run, every consumer's wind is compared with the record. Any consumer that read another
record (another source, another hour, another issue of the forecast) makes the brief's
map degraded, with DN-011 D2's label naming both records: two winds are never drawn on
one map.

The record's stated-wind role in the puff's own tests (HB-72, HB-75) is through the test
harness, which calls `derive.puff` on a brief that has not resolved a record.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hazbrief.evidence import store as S

#: floating-point slack on the rounding tolerances (`_same`), far below any unit printed
_EPS = 1e-9
#: the weather sources `resolve` reads a record for (all three since HB-143)
SOURCES_WITH_A_CLIENT = ("forecast", "observed", "stated")


class WindRecordsDisagree(RuntimeError):
    """Two consumers on one brief read different wind records; it names both."""


@dataclass(frozen=True)
class Held:
    """The forecast the record was read from: the two exchanges (NWS `points`, then the
    `gridpoints` url it names) and the forecast window built on them, so the
    derivations read the same forecast and do not fetch it again."""

    points: Any
    grid: Any
    window: dict


def _spec(cfg: dict) -> dict:
    spec = cfg.get("wind_record")
    if not spec:
        raise RuntimeError("orchestrator.yaml has no wind_record block (HB-133)")
    return spec


def _stated_from(scenario: dict) -> dict | None:
    """The scenario's stated wind as a record's fields, or None: its request `wind`
    (km/h, the server's shape) first, else its `stated_wind` block (m/s, HB-70)."""
    w = scenario.get("wind")
    if w and w.get("speed_kmh") is not None:
        return {
            "direction_deg_from": float(w.get("direction_deg_from") or 0.0) % 360.0,
            "speed_kmh": float(w["speed_kmh"]),
            "given_source": w.get("source"),
            "as_of": w.get("observed_at"),
            "block": "wind",
        }
    from hazbrief.brief import stated_wind as W

    sw, refused = W.parse(scenario.get("stated_wind"))
    if refused or sw is None or sw.speed_m_s is None:
        return None
    return {
        "direction_deg_from": float(sw.direction_deg_from or 0.0) % 360.0,
        "speed_kmh": float(sw.speed_m_s) * 3.6,
        "given_source": sw.source,
        "as_of": sw.observed_at.isoformat() if sw.observed_at else None,
        "block": "stated_wind",
    }


def from_forecast(window: dict | None, scenario: dict, cfg: dict) -> dict | None:
    """The brief's record from a forecast window (or None) and the scenario: the
    forecast cell at hour 0 when it holds a wind, else the stated wind, else None."""
    spec = _spec(cfg)
    rows = (window or {}).get("rows") or []
    h0 = rows[0] if rows else {}
    stated = _stated_from(scenario)
    hour = h0.get("time") or scenario.get("as_given")
    if h0.get("windSpeed") is not None and h0.get("windDirection") is not None:
        grid = window.get("grid")
        rec = {
            "kind": "forecast",
            "direction_deg_from": float(h0["windDirection"]) % 360.0,
            "speed_kmh": float(h0["windSpeed"]),
            "source": spec["forecast_source"].format(grid=grid, hour=hour),
            "as_of": window.get("update_time"),
            "hour": hour,
            "grid": grid,
            "unused": None,
        }
        if stated is not None:
            rec["unused"] = spec["stated_unused"].format(
                source=stated["given_source"],
                deg=stated["direction_deg_from"],
                kmh=stated["speed_kmh"],
                hour=hour,
            )
        return rec
    if stated is not None:
        return {
            "kind": "stated",
            "direction_deg_from": stated["direction_deg_from"],
            "speed_kmh": stated["speed_kmh"],
            "source": spec["stated_source"].format(
                source=stated["given_source"], hour=hour
            ),
            "as_of": stated["as_of"],
            "hour": hour,
            "grid": None,
            "unused": None,
            "block": stated["block"],
            "given_source": stated["given_source"],
        }
    return None


def from_stated(weather: dict, scenario: dict, cfg: dict) -> dict:
    """The brief's record when `weather.source` is stated (DN-019 ADDENDUM-01 section
    1; HB-139): the block's wind, stability class and mixing height, with its basis,
    standing for the as-given hour. `weather` is `weather_source.select`'s answer, so
    every field is present."""
    spec = _spec(cfg)
    st = weather["stated"]
    hour = scenario.get("as_given")
    return {
        "kind": "stated",
        "direction_deg_from": float(st["direction_from_deg"]) % 360.0,
        "speed_kmh": float(st["speed_kmh"]),
        "source": spec["stated_config_source"].format(basis=st["basis"]),
        "as_of": hour,
        "hour": hour,
        "grid": None,
        "unused": None,
        "block": "weather",
        "basis": st["basis"],
        "stability_class": st["stability_class"],
        "mixing_height_m": float(st["mixing_height_m"]),
    }


def from_observed(
    result: dict, window: dict | None, scenario: dict, observed: dict, cfg: dict
) -> dict | None:
    """The brief's record when `weather.source` is observed (HB-143): the
    representative station's wind (`observed_wind.choose`), standing for the hour of its
    observation, with every station read, the spread and the method on the record.
    Below the minimum the record is the forecast cell (`from_forecast`), carrying
    `observed_fallback`, the line the first screen prints (HB-143 item 3; Issue
    94309222)."""
    oc = cfg["weather"]["observed_client"]
    rep = result.get("representative")
    if rep is None:
        rec = from_forecast(window, scenario, cfg)
        if rec is not None:
            rec = {
                **rec,
                "observed_fallback": oc["fallback"].format(
                    why=result["reason"], issue=oc["fallback_issue"]
                ),
                "observed_stations": result.get("stations") or [],
                "observed_sources": result.get("sources") or [],
                "method": result.get("method"),
            }
        return rec
    dataset = oc["clients"][observed["dataset"]]["name"]
    source = oc["source"].format(
        dataset=dataset,
        station=rep["station"],
        observed_at=rep["observed_at"],
        km=float(rep["distance_km"]),
    )
    return {
        "kind": "observed",
        # a calm observation reports no bearing; a calm record has none to agree on
        # (`_same`), so 0 stands in as `_stated_from` does
        "direction_deg_from": float(rep["wind_from_deg"] or 0.0) % 360.0,
        "speed_kmh": float(rep["wind_kmh"]),
        "source": source,
        "as_of": rep["observed_at"],
        "hour": rep["observed_at"],
        "grid": None,
        "unused": None,
        # sent to the server in the scenario's place, as a stated record is
        # (`request_scenario`): otherwise the server would read the forecast
        "block": "weather",
        "dataset": dataset,
        "dataset_id": observed["dataset"],
        "station": rep["station"],
        "station_name": rep.get("name"),
        "distance_km": float(rep["distance_km"]),
        "method": result["method"],
        "stations": result["stations"],
        "spread": result["spread"],
        "observed_config": {
            k: observed[k]
            for k in ("dataset", "tolerance_minutes", "stations", "min_stations")
        },
        "sources": result.get("sources") or [],
    }


def _arc_text(spread: dict | None, forms: dict) -> str:
    a = (spread or {}).get("arc")
    if a is None:
        return forms["arc_none"]
    if a["width_deg"] == 0.0:
        return forms["arc_one"].format(lo=a["from_deg"])
    return forms["arc"].format(lo=a["from_deg"], hi=a["to_deg"])


def observed_lines(rec: dict | None, cfg: dict, when) -> list[tuple[str, str]]:
    """The first screen's lines under the wind line for the observed source (HB-143),
    as (css class, text): every station read, with its distance, wind and time, or
    why it was not used; and, when the record fell back to the forecast, why. Empty
    for any other record."""
    if not rec:
        return []
    oc = cfg["weather"]["observed_client"]
    out: list[tuple[str, str]] = []
    stations = rec.get("stations") if rec["kind"] == "observed" else None
    if rec.get("observed_fallback"):
        out.append(("pl fa-wind-fallback", rec["observed_fallback"]))
        stations = rec.get("observed_stations")
    if stations:
        parts = []
        for s in stations:
            at = when(s["observed_at"]) if s.get("observed_at") else "unknown"
            if s.get("used"):
                wind = (
                    oc["wind_calm"]
                    if s["calm"]
                    else oc["wind_from"].format(
                        deg=float(s["wind_from_deg"]), kmh=float(s["wind_kmh"])
                    )
                )
                form = (
                    oc["station_used"]
                    if rec["kind"] == "observed" and s["station"] == rec.get("station")
                    else oc["station_spread"]
                )
                parts.append(
                    form.format(
                        station=s["station"], km=s["distance_km"], wind=wind, at=at
                    )
                )
            else:
                parts.append(
                    oc["station_dropped"].format(
                        station=s["station"], km=s["distance_km"], why=s["dropped"]
                    )
                )
        method = rec.get("method") or ""
        out.append(
            (
                "pl fa-wind-stations",
                oc["stations_line"].format(method=method, stations="; ".join(parts)),
            )
        )
    return out


def label(rec: dict | None, cfg: dict, when) -> str | None:
    """The record's source in DN-019 ADDENDUM-01 section 1's form (`labels`):
    "forecast, NWS cell X for <hour>, as of ...", "observed, <dataset> station Y,
    <hour>"
    or "stated: notional, from D at S km/h, basis: B". `when(iso)` prints a time in the
    incident's zone. HB-133's stated wind when no forecast cell is held prints in the
    stated form, its basis naming the scenario's source and the hour. None: no
    record."""
    if rec is None:
        return None
    spec = _spec(cfg)
    forms = spec["labels"]

    def t(x):
        return when(x) if x else "unknown"

    if rec["kind"] == "forecast":
        return forms["forecast"].format(
            grid=rec.get("grid"), hour=t(rec.get("hour")), as_of=t(rec.get("as_of"))
        )
    if rec["kind"] == "observed":
        text = forms["observed"].format(
            dataset=rec.get("dataset"), station=rec.get("station"), hour=t(rec["hour"])
        )
        # HB-143: how the station was chosen and how the others read
        spread = rec.get("spread")
        if spread is not None:
            read = len(rec.get("stations") or [])
            if spread["n"] > 1:
                text += forms["observed_spread"].format(
                    n=spread["n"],
                    km=float(rec["distance_km"]),
                    arc=_arc_text(spread, forms),
                    kmin=float(spread["kmh_min"]),
                    kmax=float(spread["kmh_max"]),
                )
            else:
                text += forms["observed_one"].format(
                    read=read, km=float(rec["distance_km"])
                )
        return text
    basis = rec.get("basis")
    if basis is None:  # HB-133: the scenario's wind when no forecast cell is held
        basis = spec["stated_fallback_basis"].format(
            source=rec.get("given_source") or rec.get("source"),
            hour=t(rec.get("hour")),
        )
    return forms["stated"].format(
        deg=float(rec["direction_deg_from"]), kmh=float(rec["speed_kmh"]), basis=basis
    )


def is_calm(rec: dict | None) -> bool:
    """A calm record: a true record with no motion of air (FMH-1 section 5.5.2), which
    the models that cannot run on it name (Issue 473bdfeb)."""
    return rec is not None and float(rec["speed_kmh"]) <= 0.0


def describe(rec: dict | None, cfg: dict) -> str:
    """One line naming a record: source, direction, speed and as-of."""
    if rec is None:
        return _spec(cfg)["no_record"]
    return _spec(cfg)["describe"].format(
        deg=float(rec["direction_deg_from"]),
        kmh=float(rec["speed_kmh"]),
        source=rec.get("source"),
        as_of=rec.get("as_of") or "unknown",
    )


def as_footprint_wind(rec: dict | None) -> dict | None:
    """The record in the footprint's `wind` shape (the keys the page reads)."""
    if rec is None:
        return None
    return {
        "direction_deg_from": rec["direction_deg_from"],
        "speed_kmh": rec["speed_kmh"],
        "source": rec["source"],
        "as_of": rec.get("as_of"),
    }


def request_scenario(scenario: dict, rec: dict | None) -> dict:
    """The scenario as the brief asks the server about it: its `wind` replaced by the
    record when the record is the forecast and the scenario gave a wind (module
    docstring, "The request"); otherwise unchanged. A record stated by the weather
    source (HB-139) is always sent: the server would otherwise read the forecast."""
    if rec is not None and rec.get("block") == "weather":
        return {
            **scenario,
            "wind": {
                "speed_kmh": rec["speed_kmh"],
                "direction_deg_from": rec["direction_deg_from"],
                "observed_at": rec["as_of"],
                "source": rec["source"],
            },
        }
    if rec is None or rec["kind"] != "forecast" or not scenario.get("wind"):
        return scenario
    return {
        **scenario,
        "wind": {
            "speed_kmh": rec["speed_kmh"],
            "direction_deg_from": rec["direction_deg_from"],
            "observed_at": rec["as_of"],
            "source": rec["source"],
        },
    }


def _turn(a: float, b: float) -> float:
    return abs((float(a) - float(b) + 180.0) % 360.0 - 180.0)


def _same(rec: dict, deg, kmh, cfg: dict) -> bool:
    spec = _spec(cfg)
    if deg is None or kmh is None:
        return False
    if float(rec["speed_kmh"]) == 0.0 and float(kmh) == 0.0:
        return True  # calm: no direction to agree on (FMH-1 section 5.5.2)
    # _EPS: a half-unit difference computed in binary floating point lands a hair over
    # the half unit (9.25 - 9.3); the tolerance is the rounding, not the float error
    return _turn(deg, rec["direction_deg_from"]) <= float(
        spec["tolerance_deg"]
    ) + _EPS and (
        abs(float(kmh) - float(rec["speed_kmh"])) <= float(spec["tolerance_kmh"]) + _EPS
    )


def _same_time(a, b) -> bool:
    if not a or not b:
        return a == b
    return S.parse_time(str(a)) == S.parse_time(str(b))


def disagreements(
    rec: dict | None, fp: dict | None, derived: dict | None, cfg: dict
) -> list[str]:
    """Each consumer that read a wind other than the record, as one line naming what it
    read (empty: every consumer read the record). A consumer that drew nothing (no
    footprint, a puff not drawn) read nothing and is not compared."""
    spec = _spec(cfg)
    out: list[str] = []
    w = (fp or {}).get("wind") or {}
    if w.get("direction_deg_from") is not None:
        if rec is None or not (
            _same(rec, w["direction_deg_from"], w.get("speed_kmh"), cfg)
            and _same_time(w.get("as_of"), rec.get("as_of"))
        ):
            out.append(
                spec["consumer"].format(
                    consumer="the ERG footprint",
                    what=describe(
                        {
                            "direction_deg_from": w["direction_deg_from"],
                            "speed_kmh": w.get("speed_kmh") or 0.0,
                            "source": w.get("source"),
                            "as_of": w.get("as_of"),
                        },
                        cfg,
                    ),
                )
            )
    d = derived or {}
    puff_w = (d.get("puff") or {}).get("wind_read")
    if puff_w and (
        rec is None or not _same(rec, puff_w["from_deg"], puff_w["kmh"], cfg)
    ):
        out.append(
            spec["consumer"].format(
                consumer="the puff",
                what=spec["engine_read"].format(
                    deg=puff_w["from_deg"], kmh=puff_w["kmh"], source=puff_w["source"]
                ),
            )
        )
    dg = (d.get("dense_gas") or {}).get("wind")
    if dg and (rec is None or not _same(rec, dg["from_deg"], dg["ms"] * 3.6, cfg)):
        out.append(
            spec["consumer"].format(
                consumer="the dense-gas footprint",
                what=spec["engine_read"].format(
                    deg=dg["from_deg"], kmh=dg["ms"] * 3.6, source=dg.get("label")
                ),
            )
        )
    st = d.get("stability") or {}
    sw = next((i for i in st.get("inputs") or [] if i["name"] == "wind speed"), None)
    if sw and sw.get("value") is not None and rec is not None:
        if (
            abs(float(sw["value"]) * 3.6 - float(rec["speed_kmh"]))
            > float(spec["tolerance_kmh"]) + _EPS
        ):
            out.append(
                spec["consumer"].format(
                    consumer="the stability class",
                    what=f"{float(sw['value']):.2f} m/s ({sw.get('source')})",
                )
            )
    return out


def degraded_reason(rec: dict | None, lines: list[str], cfg: dict) -> str:
    """DN-011 D2's label for a map whose consumers read two winds: both records."""
    return _spec(cfg)["degraded_label"].format(
        record=describe(rec, cfg), others="; ".join(lines)
    )


def check(rec: dict | None, fp: dict | None, derived: dict | None, cfg: dict) -> None:
    """Raise `WindRecordsDisagree`, naming both records, when any consumer read another
    wind than the record."""
    lines = disagreements(rec, fp, derived, cfg)
    if lines:
        raise WindRecordsDisagree(degraded_reason(rec, lines, cfg))


async def resolve(
    scenario: dict,
    point: tuple[float, float] | None,
    cfg: dict,
    *,
    now,
    replay: bool,
    weather: dict | None = None,
) -> tuple[dict | None, Held | None]:
    """The brief's one wind record and the forecast it was read from (None when no
    forecast is held): the NWS gridpoint at `point` (latitude, longitude), read through
    the derivations' own fetch (recorded exchanges only when `replay`), its window from
    the as-given hour.

    `weather` is the brief's weather selection (`weather_source.select`; None is the
    forecast, as before HB-139). Under `stated` the forecast is still read, because the
    wind strip and the wind field are weather layers shown as data, but the record is
    the stated wind. Under `observed` (HB-143) the forecast is read too, and the record
    is the representative station's observation (`observed_wind`) at the incident
    point, the forecast cell when fewer than the minimum stations have a fresh wind."""
    if weather is not None and weather["source"] not in SOURCES_WITH_A_CLIENT:
        raise ValueError(f"weather source {weather['source']!r} has no record client")
    from hazbrief.brief import derive
    from hazbrief.utils import UpstreamServiceError

    held = None
    if point is not None:
        start = S.parse_time(scenario["as_given"]) if scenario.get("as_given") else now
        with derive._replaying(replay):
            try:
                points, grid = await derive.fetch_forecast(*point)
                window = derive.forecast_window(
                    grid, now, cfg, start=start, observed=None
                )
                held = Held(points=points, grid=grid, window=window)
            except (derive.DeriveError, UpstreamServiceError):
                held = None
    if weather is not None and weather["source"] == "stated":
        hour = scenario.get("as_given") or now.isoformat()
        return from_stated(weather, {**scenario, "as_given": hour}, cfg), held
    if weather is not None and weather["source"] == "observed":
        from hazbrief.brief import observed_wind

        when = S.parse_time(scenario["as_given"]) if scenario.get("as_given") else now
        with derive._replaying(replay):
            result = await observed_wind.read(point, when, weather["observed"], cfg)
        rec = from_observed(
            result, held.window if held else None, scenario, weather["observed"], cfg
        )
        return rec, held
    return from_forecast(held.window if held else None, scenario, cfg), held
