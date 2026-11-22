"""HB-75: the held station observation stands in for the puff's wind when the forecast
reads calm, and says so.

The fall-through in `derive.puff`: a `stated_wind` block for every hour (HB-72); else
the forecast hour; else, for a forecast hour that reads 0, the nearest station's held
observation (HB-60) when it is usable and reads a wind; else the calm line. The panel's
first assumption line names the source with the observation's age and distance; every
contour carries `wind_source`; over the committed briefs, the hours not driven by the
forecast are Scranton's alone.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from hazbrief.brief import derive, render
from hazbrief.brief.orchestrator import load_config

REPO = Path(__file__).resolve().parents[1]
BRIEFS = REPO / "docs" / "briefs"
RELEASE = {"quantity_kg": 20000.0, "quantity_source": "a test's stated quantity"}
WIND = {"speed_m_s": 3.0, "direction_deg_from": 90, "source": "a test's stated wind"}
AS_GIVEN = "2026-10-21T02:45:00+00:00"
OBS = {
    "station": "KTST",
    "usable": True,
    "wind_ms": 2.5,
    "wind_from_deg": 110.0,
    "observed_at": "2026-10-21T02:00:00+00:00",
    "distance_km": 9.4,
}
CALM_LINE = "wind 0: no puff released; state a scene wind to draw it"
#: HB-139 (Issue 473bdfeb's ruling): a resolved calm record names what the puff needs
CALM_RECORD_LINE = (
    "calm forecast: the puff needs a wind above 0 m/s, so no puff is released"
)


@pytest.fixture(scope="module")
def cfg():
    return load_config()


@pytest.fixture(autouse=True)
def _seeded_passive(monkeypatch):
    """HB-163 (ADDENDUM-02 items 2 and 6; DN-026): these test the puff engine. Their
    releases are chlorine, which the selection rule classes dense, or fixtures without
    the source term's weather, which it cannot class; either way no puff runs. The
    class is seeded passive here, so the puff runs as it did before HB-163; the rule
    and the dense path are test_hb163_one_cloud.py's."""
    from hazbrief.brief import derive as _derive

    monkeypatch.setattr(
        _derive,
        "engine_rule_for",
        lambda *a, **k: {"class": "passive", "line": "passive (seeded by the test)"},
    )


def _footprint():
    return {
        "material": {"un_number": "1017"},
        "zones": {
            "protective_action_zone": {"distance": {"metres": 3300.0, "text": "3.3 km"}}
        },
        "footprint": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"zone": "spill"},
                    "geometry": {"type": "Point", "coordinates": [-77.5394, 39.2756]},
                }
            ],
        },
    }


def _brief(stated=None):
    record = {"activity": {"params": {"incident": {"container": "Rail tank car"}}}}
    return SimpleNamespace(
        location=None,
        channels={"protective_action_footprint": {"record": record}},
        time_zone="America/New_York",
        now=None,
        as_given=AS_GIVEN,
        derived={},
        release=RELEASE,
        stated_wind=stated,
    )


def _derived(speeds_kmh=(0.0, 0.0), observation=OBS):
    rows = [
        {"hour": h, "windSpeed": s, "windDirection": 270.0}
        for h, s in enumerate(speeds_kmh)
    ]
    return {
        "stability": {"class": "D", "reason": None, "table": "Turner's key"},
        "forecast": {
            "rows": rows,
            "grid": "LWX/77,86",
            "update_time": "2026-10-21T01:52:44+00:00",
        },
        "observation": observation,
    }


def _worst(out):
    return next(e for e in out["envelopes"] if e["name"] == "worst_case")


# ── the fall-through (step 1) ─────────────────────────────────────────────────────────


def test_a_calm_forecast_takes_the_observation_for_every_calm_hour(cfg):
    out = derive.puff(_brief(), _footprint(), _derived(), cfg)
    assert _worst(out)["contours"]
    assert out["wind_hours"] == [
        {"hour": 0, "wind_source": "station_observation"},
        {"hour": 1, "wind_source": "station_observation"},
    ]
    assert out["wind_source"] == "station_observation"
    assert out["wind_station"] == {
        "station_id": "KTST",
        "observed_at": "2026-10-21T02:00:00+00:00",
    }
    hours = {i["name"]: i for i in out["inputs"] if i["name"].startswith("wind, hour")}
    assert hours["wind, hour 0"]["value"] == "9 km/h from 110 degrees"
    assert hours["wind, hour 0"]["source"] == (
        "NWS observation, station KTST, 9.4 km from the spill "
        "(forecast LWX/77,86 reads 0 km/h this hour)"
    )
    assert hours["wind, hour 0"]["as_of"] == OBS["observed_at"]
    # the grid is sized by the observed speed
    assert out["grid"]["speed_ms"] == 2.5
    assert "station KTST observation of 2026-10-21T02:00:00+00:00" in out["label"]


def test_the_fall_through_fires_only_on_an_hour_the_forecast_reads_zero(cfg):
    out = derive.puff(_brief(), _footprint(), _derived((0.0, 18.0)), cfg)
    assert out["wind_hours"] == [
        {"hour": 0, "wind_source": "station_observation"},
        {"hour": 1, "wind_source": "forecast"},
    ]
    assert out["wind_source"] == "station_observation, forecast"
    first = out["assumptions"][0]
    assert "reads calm for hour 0;" in first
    assert "is used for those hours, and the forecast for hour 1;" in first
    hours = {i["name"]: i for i in out["inputs"] if i["name"].startswith("wind, hour")}
    assert hours["wind, hour 1"]["source"] == "NWS gridpoint forecast LWX/77,86"
    assert hours["wind, hour 1"]["value"] == "18 km/h from 270 degrees"


def test_a_moving_forecast_keeps_the_forecast_and_its_line(cfg):
    out = derive.puff(_brief(), _footprint(), _derived((18.0, 18.0)), cfg)
    assert {w["wind_source"] for w in out["wind_hours"]} == {"forecast"}
    assert out["wind_station"] is None
    assert out["assumptions"][0].startswith("Wind: NWS gridpoint forecast LWX/77,86")
    assert "observation" not in out["assumptions"][0]
    assert "NWS forecast as of 2026-10-21T01:52:44+00:00" in out["label"]


def test_a_stated_wind_still_wins(cfg):
    out = derive.puff(_brief(WIND), _footprint(), _derived(), cfg)
    assert {w["wind_source"] for w in out["wind_hours"]} == {"stated"}
    assert out["wind_source"] == "stated"
    assert out["wind_station"] is None
    assert out["assumptions"][0].startswith("Wind: stated, 3.0 m/s from 90 degrees")
    assert out["grid"]["speed_ms"] == 3.0


@pytest.mark.parametrize(
    "observation",
    [
        {**OBS, "wind_ms": 0.0},
        None,
        {"station": None, "usable": False, "reason": "no station"},
        {**OBS, "usable": False, "stale_reason": "observed 3.0 h before"},
        {**OBS, "wind_from_deg": None},
    ],
    ids=["observation_calm", "absent", "no_station", "stale", "no_direction"],
)
def test_without_an_observed_wind_the_calm_line_stands(cfg, observation):
    out = derive.puff(_brief(), _footprint(), _derived(observation=observation), cfg)
    assert out["envelopes"] == []
    assert out["lines"] == [CALM_LINE]


def test_without_an_as_given_time_the_age_cannot_be_stated_and_it_is_not_used(cfg):
    brief = _brief()
    brief.as_given = None
    out = derive.puff(brief, _footprint(), _derived(), cfg)
    assert out["lines"] == [CALM_LINE]


# ── the panel (steps 2 and 3) ─────────────────────────────────────────────────────────


def test_the_panel_names_the_station_its_age_and_its_distance(cfg):
    brief = _brief()
    out = derive.puff(brief, _footprint(), _derived(), cfg)
    want = (
        "Wind: NWS gridpoint forecast LWX/77,86, updated 10/20/2026 21:52 EDT, reads "
        "calm for both hours of the window; station KTST's observation, 9.0 km/h "
        "(2.5 m/s) from 110 degrees, observed 10/20/2026 22:00 EDT (45 min before the "
        "as-given time), 9.4 km from the spill, is used for those hours; each puff "
        "takes the wind of the hour it is released in"
    )
    assert out["assumptions"][0] == want
    brief.derived = {"puff": out}
    assert render.esc(want) in render._puff_html(brief, cfg)


# ── the committed briefs (steps 4 to 6) ───────────────────────────────────────────────


def _committed():
    return sorted(p.name for p in BRIEFS.iterdir() if (p / "brief.html").is_file())


def _page(sid):
    page = (BRIEFS / sid / "brief.html").read_text(encoding="utf-8")
    m = re.search(r'id="map-data">(.*?)</script>', page, re.S)
    data = json.loads(m.group(1).replace("<\\/", "</"))
    return page, {lay["id"]: lay["features"] for lay in data["layers"]}


def _wind_rows(page):
    """The puff panel's wind inputs, (name, source), from its inputs table."""
    return re.findall(
        r"<tr><td>(wind, hour \d+|wind \(stated\))</td><td>[^<]*</td><td>([^<]*)</td>",
        page,
    )


def test_no_committed_brief_drives_its_puff_off_its_one_wind_record():
    """HB-133 (the operator's ruling on Issue 90ac45af): every layer of a brief reads
    its one wind record, so no committed brief's puff takes a station observation or a
    stated wind beside a held forecast. The stand-in keeps its role through the
    harness above (a brief that has resolved no record)."""
    observed, stated = [], []
    for sid in _committed():
        for name, source in _wind_rows(_page(sid)[0]):
            if name == "wind (stated)":
                stated.append(sid)
            elif not source.startswith("NWS gridpoint forecast"):
                assert source.startswith("NWS observation, station "), (sid, source)
                observed.append((sid, name))
    assert observed == []
    assert stated == []


@pytest.mark.parametrize("sid", _committed())
def test_every_contour_carries_its_wind_source(sid):
    _, lays = _page(sid)
    for lid, feats in lays.items():
        if not lid.startswith("puff"):
            continue
        for f in feats:
            props = f["properties"]
            if sid == "scranton-i81-nws-wind":
                assert props["wind_source"] == "station_observation"
                assert props["station_id"] == "KAVP"
                assert props["observed_at"] == "2026-10-28T04:00:00+00:00"
            else:
                want = "stated" if sid == "scranton-i81-stated-wind" else "forecast"
                assert props["wind_source"] == want
                assert "station_id" not in props and "observed_at" not in props


def test_scranton_reads_its_calm_forecast_cell_and_releases_no_puff():
    """HB-133: Scranton's record is the forecast cell at its as-given hour, which reads
    calm; the ERG footprint is oriented on it, so the puff reads it too and says what
    would draw it (HB-139: the speed it needs, Issue 473bdfeb). KAVP's observation
    would be a second record."""
    page, lays = _page("scranton-i81-nws-wind")
    assert not lays.get("puff_source_term")
    assert CALM_RECORD_LINE in page and CALM_LINE not in page
    assert "station KAVP's observation" not in page
