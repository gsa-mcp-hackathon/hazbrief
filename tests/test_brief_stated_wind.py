"""HB-72 (was HB-70): the grid fits the puff, a stated wind drives it when the forecast
cannot, and calm draws nothing.

The `stated_wind` block's schema and refusals (the release block's shape); its
precedence over the forecast in `derive.puff`; the calm line; the grid sized by the
puff's reach with the ERG grid as its floor; the Scranton sibling fixture; and, over
every committed brief, no contour clipped by the grid and no release past its edge.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from hazbrief.brief import derive, render
from hazbrief.brief import stated_wind as W
from hazbrief.brief.orchestrator import load_config
from hazbrief.packs import load_app_pack

REPO = Path(__file__).resolve().parents[1]
SCHEMA = REPO / "docs" / "schema" / "scenario_stated_wind.schema.json"
BRIEFS = REPO / "docs" / "briefs"
RELEASE = {"quantity_kg": 20000.0, "quantity_source": "a test's stated quantity"}
WIND = {
    "speed_m_s": 3.0,
    "direction_deg_from": 90,
    "source": "scene observation, hand anemometer, 21:10 EDT",
}
CALM = {"speed_m_s": 0, "source": "a test's stated calm"}


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


def _footprint(pad_m=3300.0):
    return {
        "material": {"un_number": "1017"},
        "zones": {
            "protective_action_zone": {"distance": {"metres": pad_m, "text": "3.3 km"}}
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


def _brief(stated=None, release=RELEASE):
    record = {"activity": {"params": {"incident": {"container": "Rail tank car"}}}}
    return SimpleNamespace(
        location=None,
        channels={"protective_action_footprint": {"record": record}},
        time_zone="America/New_York",
        now=None,
        derived={},
        release=release,
        stated_wind=stated,
    )


def _derived(speed_kmh=18.0, hours=3):
    rows = [
        {"hour": h, "windSpeed": speed_kmh, "windDirection": 270.0}
        for h in range(hours)
    ]
    return {
        "stability": {"class": "D", "reason": None, "table": "Turner's key"},
        "forecast": {
            "rows": rows,
            "grid": "LWX/77,86",
            "update_time": "2026-10-21T02:52:44+00:00",
        },
    }


# ── the block's schema and refusals ───────────────────────────────────────────────────


def test_the_committed_schema_is_the_models():
    assert SCHEMA.read_text(encoding="utf-8") == W.schema_text()


@pytest.mark.parametrize(
    "block",
    [
        WIND,
        {**WIND, "observed_at": "2026-10-28T21:10:00-04:00"},
        CALM,
        {},
    ],
)
def test_the_schema_accepts_a_sourced_block(block):
    import jsonschema

    jsonschema.validate(block, json.loads(SCHEMA.read_text()))
    assert W.parse(block)[1] is None


@pytest.mark.parametrize(
    "block, why",
    [
        (
            {"speed_m_s": 3.0, "direction_deg_from": 90},
            "speed_m_s is given without source",
        ),
        ({**WIND, "source": ""}, "source"),
        ({"direction_deg_from": 90, "source": "x"}, "without speed_m_s"),
        ({"speed_m_s": 3.0, "source": "x"}, "without direction_deg_from"),
        ({**WIND, "speed_m_s": -1.0}, "greater than or equal to 0"),
        ({**WIND, "direction_deg_from": 361}, "less than or equal to 360"),
        ({**WIND, "gust_m_s": 9}, "gust_m_s"),
    ],
)
def test_the_schema_and_the_model_refuse_an_unsourced_or_wrong_block(block, why):
    import jsonschema

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(block, json.loads(SCHEMA.read_text()))
    got, refused = W.parse(block)
    assert got is None and why in refused


@pytest.mark.parametrize("when", ["21:10", "2026-10-28T21:10:00"])
def test_the_model_refuses_an_observed_time_without_its_zone(when):
    # the schema's `format: date-time` is an annotation unless a validator asserts it
    # (JSON Schema 2020-12 section 7.2.1), so the model is the refusal of record
    got, refused = W.parse({**WIND, "observed_at": when})
    assert got is None and refused.startswith("observed_at")


def test_no_block_is_not_a_refusal():
    assert W.parse(None) == (None, None)


# ── precedence: a stated wind replaces the forecast for the puff alone ────────────────


def test_a_stated_wind_replaces_the_forecast_and_the_first_assumption_names_it(cfg):
    out = derive.puff(_brief(WIND), _footprint(), _derived(), cfg)
    worst = next(e for e in out["envelopes"] if e["name"] == "worst_case")
    assert worst["contours"]
    assert out["assumptions"][0] == (
        "Wind: stated, 3.0 m/s from 90 degrees, by scene observation, hand anemometer, "
        "21:10 EDT; it replaces the NWS forecast for every hour of the window"
    )
    names = [i["name"] for i in out["inputs"]]
    assert "wind (stated)" in names
    assert not any(n.startswith("wind, hour") for n in names)
    assert "stated by scene observation, hand anemometer" in out["label"]
    assert "NWS forecast" not in out["label"]
    # the grid is sized by the stated speed, not the forecast's 5 m/s
    assert out["grid"]["speed_ms"] == 3.0


def test_the_stated_wind_moves_the_cloud_where_it_blows(cfg):
    # from 90 degrees the cloud goes west of the spill; the forecast's 270 sends it east
    def mean_lon(out):
        worst = next(e for e in out["envelopes"] if e["name"] == "worst_case")
        c = next(c for c in worst["contours"] if c["minute"] == 30)
        geom = c["geometry"]
        rings = (
            [geom["coordinates"][0]]
            if geom["type"] == "Polygon"
            else [p[0] for p in geom["coordinates"]]
        )
        xs = [x for ring in rings for x, _ in ring]
        return sum(xs) / len(xs)

    stated = derive.puff(_brief(WIND), _footprint(), _derived(), cfg)
    forecast = derive.puff(_brief(None), _footprint(), _derived(), cfg)
    assert mean_lon(stated) < -77.5394 < mean_lon(forecast)


def test_the_observed_time_prints_in_the_briefs_zone(cfg):
    block = {**WIND, "observed_at": "2026-10-29T01:10:00+00:00"}
    out = derive.puff(_brief(block), _footprint(), _derived(), cfg)
    assert ", observed 10/28/2026 21:10 EDT;" in out["assumptions"][0]


def test_a_stated_wind_drives_the_puff_where_the_forecast_has_none(cfg):
    d = _derived()
    d["forecast"] = {**d["forecast"], "rows": [], "reason": None}
    assert not derive.puff(_brief(None), _footprint(), d, cfg)["envelopes"]
    out = derive.puff(_brief(WIND), _footprint(), d, cfg)
    assert next(e for e in out["envelopes"] if e["name"] == "worst_case")["contours"]


def test_a_stated_wind_without_its_source_is_refused_and_the_panel_says_so(cfg):
    out = derive.puff(
        _brief({"speed_m_s": 3.0, "direction_deg_from": 90}),
        _footprint(),
        _derived(),
        cfg,
    )
    assert out["envelopes"] == []
    assert out["lines"] == [
        "Puff not drawn: the stated wind block is refused "
        "(speed_m_s is given without source)"
    ]


def test_without_the_block_the_forecast_drives_the_puff_as_before(cfg):
    out = derive.puff(_brief(None), _footprint(), _derived(), cfg)
    assert out["assumptions"][0].startswith("Wind: NWS gridpoint forecast LWX/77,86")
    assert "NWS forecast as of 2026-10-21T02:52:44+00:00" in out["label"]


# ── calm (step 4): a line, not a floor ────────────────────────────────────────────────


@pytest.mark.parametrize("stated, speed_kmh", [(CALM, 18.0), (None, 0.0)])
def test_a_wind_of_zero_draws_nothing_and_prints_the_calm_line(cfg, stated, speed_kmh):
    brief = _brief(stated)
    out = derive.puff(brief, _footprint(), _derived(speed_kmh=speed_kmh), cfg)
    assert out["envelopes"] == []
    assert out["lines"] == ["wind 0: no puff released; state a scene wind to draw it"]
    brief.derived = {"puff": out}
    assert (
        "wind 0: no puff released; state a scene wind to draw it"
        in render._puff_html(brief, cfg)
    )


# ── the grid fits the puff (step 1) ───────────────────────────────────────────────────


@pytest.fixture(scope="module")
def curves():
    return load_app_pack("sigma_curves").data.model_dump(mode="json")


def test_the_grid_is_the_reach_or_the_erg_floor_whichever_is_larger(cfg, curves):
    spec = cfg["weather"]["puff"]
    from hazbrief.brief import puff as engine

    g = derive.puff_grid(curves, "E", 3.1, 3600.0, 9400.0, spec)
    sy = float(engine.sigmas(curves, "E", [3.1 * 3600.0])[0][0])
    assert g["travel_m"] == pytest.approx(11160.0)
    assert g["spread_m"] == pytest.approx(4 * sy)
    assert g["half_width_m"] >= g["reach_m"] > 9400.0
    # the floor grid's cell size, kept; an odd count so the spill is a cell centre
    assert g["step_m"] == pytest.approx(2 * 9400.0 / int(spec["grid_cells"]))
    assert g["cells"] % 2 == 1 and not g["coarsened"]
    low = derive.puff_grid(curves, "E", 0.5, 3600.0, 9400.0, spec)
    assert low["half_width_m"] == pytest.approx(9400.0)
    assert low["cells"] == int(spec["grid_cells"])


def test_past_the_ceiling_the_cell_grows_not_the_count(cfg, curves):
    spec = cfg["weather"]["puff"]
    g = derive.puff_grid(curves, "B", 6.0, 3600.0, 100.0, spec)
    assert g["coarsened"] and g["cells_needed"] > int(spec["grid_cells_max"])
    assert g["cells"] <= int(spec["grid_cells_max"]) and g["cells"] % 2 == 1
    assert g["half_width_m"] >= g["reach_m"]


def test_the_grid_and_its_terms_print_on_the_panel(cfg):
    out = derive.puff(_brief(None), _footprint(), _derived(), cfg)
    grid = out["assumptions"][1]
    assert grid.startswith("Grid: ")
    for term in (
        "travelled at the largest driving wind",
        "4 sigma_y",
        "ERG distance x 2",
    ):
        assert term in grid


# ── the Scranton pair (steps 2 and 3) ─────────────────────────────────────────────────


def _layers(sid):
    page = (BRIEFS / sid / "brief.html").read_text(encoding="utf-8")
    m = re.search(r'id="map-data">(.*?)</script>', page, re.S)
    data = json.loads(m.group(1).replace("<\\/", "</"))
    return page, {lay["id"]: lay["features"] for lay in data["layers"]}


def test_the_fixture_states_one_sourced_test_wind_on_the_sibling_alone():
    doc = yaml.safe_load(
        (REPO / "fixtures" / "scenario_stated_winds.yaml").read_text(encoding="utf-8")
    )
    blocks = doc["stated_winds"]
    assert set(blocks) == {"scranton-i81-stated-wind"}
    got, refused = W.parse(blocks["scranton-i81-stated-wind"])
    assert refused is None and got.speed_m_s > 0
    assert "test value, not an observation" in got.source
    assert got.observed_at is None
    located = yaml.safe_load(
        (REPO / "fixtures" / "location_scenarios.yaml").read_text(encoding="utf-8")
    )["scenarios"]
    by_id = {s["id"]: s for s in located}
    base, sib = by_id["scranton-i81-nws-wind"], by_id["scranton-i81-stated-wind"]
    for key in ("given", "incident", "as_given", "not_run"):
        assert base[key] == sib[key], key
    scen = json.loads(
        (BRIEFS / "scranton-i81-stated-wind" / "scenario.json").read_text()
    )
    assert scen["stated_wind"] == blocks["scranton-i81-stated-wind"]
    assert "stated_wind" not in json.loads(
        (BRIEFS / "scranton-i81-nws-wind" / "scenario.json").read_text()
    )


def test_the_scranton_pair_reads_one_record_and_says_the_stated_wind_is_unused():
    # HB-133: a stated wind beside a held forecast is not the brief's wind (the
    # operator's ruling on Issue 90ac45af); its role is the harness's (above)
    calm_page, calm = _layers("scranton-i81-nws-wind")
    stated_page, stated = _layers("scranton-i81-stated-wind")
    assert "Wind: stated, 2.6 m/s from 110 degrees" not in stated_page
    assert "stated wind (the scenario author" in stated_page
    assert "is not used: a forecast is held for" in stated_page
    for zone in ("protective_action_zone", "initial_isolation_zone", "wind", "spill"):
        assert calm[zone] == stated[zone], zone
    assert not calm.get("puff_source_term") and not stated.get("puff_source_term")


# ── every committed brief: nothing clipped by the grid ────────────────────────────────


def _committed():
    return sorted(p.name for p in BRIEFS.iterdir() if (p / "brief.html").is_file())


def test_there_are_28_committed_briefs():
    # HB-120: three "no dispersion model applies" demonstrations; HB-129: two fires;
    # HB-175: the ammonia cargo tank (29; the name is kept)
    assert len(_committed()) == 29


@pytest.mark.parametrize("sid", _committed())
def test_no_brief_has_a_contour_at_the_grids_edge_or_a_release_past_it(sid):
    page, lays = _layers(sid)
    for lid, feats in lays.items():
        if lid.startswith("puff"):
            assert not any(f["properties"]["reaches_grid_edge"] for f in feats), lid
    assert "past the grid's edge" not in page
    assert "reaches the grid's edge" not in page
