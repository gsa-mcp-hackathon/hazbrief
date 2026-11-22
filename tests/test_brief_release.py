"""HB-69: the scenario's release block (DN-018 ADDENDUM-00 section 3) and the
alternative release by EPA RMP Equation 7-1.

The quantity is given, never defaulted: the block's schema, its refusals, what draws
with and without it, and the equation's every constant against its held page.
"""

from __future__ import annotations

import importlib.util
import json
import math
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from hazbrief.brief import derive, layers
from hazbrief.brief import release as R
from hazbrief.brief.orchestrator import load_config
from hazbrief.packs import load_app_pack

REPO = Path(__file__).resolve().parents[1]
RAW = REPO / "corpus" / "raw"
SCHEMA = REPO / "docs" / "schema" / "scenario_release.schema.json"
STATED = {"quantity_kg": 20000.0, "quantity_source": "a test's stated quantity"}
HOLE = {**STATED, "hole_diameter_m": 0.05, "hole_source": "a test's stated hole"}

needs_raw = pytest.mark.skipif(
    not RAW.is_dir(),
    reason="corpus/raw/ absent: binaries are gitignored; provenance is url + sha256",
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


def _footprint(un="1017", pad_m=3300.0):
    return {
        "material": {"un_number": un},
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


def _brief(release):
    record = {"activity": {"params": {"incident": {"container": "Rail tank car"}}}}
    return SimpleNamespace(
        location=None,
        channels={"protective_action_footprint": {"record": record}},
        time_zone="America/New_York",
        now=None,
        derived={},
        release=release,
    )


def _derived():
    rows = [{"hour": h, "windSpeed": 18.0, "windDirection": 270.0} for h in range(3)]
    return {
        "stability": {"class": "D", "reason": None, "table": "Turner's key"},
        "forecast": {
            "rows": rows,
            "grid": "LWX/77,86",
            "update_time": "2026-10-21T02:52:44+00:00",
        },
    }


# ── the schema ────────────────────────────────────────────────────────────────────────


def test_the_committed_schema_is_the_models():
    assert SCHEMA.read_text(encoding="utf-8") == R.schema_text()


@pytest.mark.parametrize("block", [STATED, HOLE, {}])
def test_the_schema_accepts_a_sourced_block(block):
    import jsonschema

    jsonschema.validate(block, json.loads(SCHEMA.read_text()))
    assert R.parse(block)[1] is None


@pytest.mark.parametrize(
    "block, why",
    [
        ({"quantity_kg": 5.0}, "quantity_kg is given without quantity_source"),
        ({"quantity_kg": 5.0, "quantity_source": ""}, "quantity_source"),
        (
            {**STATED, "hole_diameter_m": 0.05},
            "hole_diameter_m is given without hole_source",
        ),
        (
            {"hole_diameter_m": 0.05, "hole_source": "x"},
            "hole_diameter_m is given without quantity_kg",
        ),
        ({**STATED, "quantity_kg": -1.0}, "greater than 0"),
        ({**STATED, "tonnes": 3}, "tonnes"),
    ],
)
def test_the_schema_and_the_model_refuse_an_unsourced_or_wrong_block(block, why):
    import jsonschema

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(block, json.loads(SCHEMA.read_text()))
    got, refused = R.parse(block)
    assert got is None and why in refused


def test_no_block_is_not_a_refusal():
    assert R.parse(None) == (None, None)


# ── what draws ────────────────────────────────────────────────────────────────────────


def test_without_a_quantity_the_line_says_where_to_get_it(cfg):
    out = derive.puff(_brief(None), _footprint(), _derived(), cfg)
    assert out["lines"] == [
        "Puff not drawn: release quantity not given. The quantity is on the shipping "
        "papers or the train consist"
    ]
    assert not out["envelopes"]


def test_a_quantity_without_its_source_is_refused_and_the_panel_says_so(cfg):
    from hazbrief.brief import render

    brief = _brief({"quantity_kg": 80000})
    out = derive.puff(brief, _footprint(), _derived(), cfg)
    assert out["lines"] == [
        "Puff not drawn: the release block is refused (quantity_kg is given without "
        "quantity_source)"
    ]
    brief.derived = {"puff": out}
    assert "the release block is refused" in render._puff_html(brief, cfg)


def test_with_a_quantity_the_worst_case_draws_and_the_alternative_names_the_hole(cfg):
    out = derive.puff(_brief(STATED), _footprint(), _derived(), cfg)
    env = {e["name"]: e for e in out["envelopes"]}
    assert env["worst_case"]["contours"]
    assert env["worst_case"]["mass_kg"] == 20000.0
    assert env["worst_case"]["duration_s"] == 600.0  # RMP's ten minutes, the pack's
    assert not env["alternative"].get("contours")
    assert "Puff not drawn: alternative release: hole size not given" in out["lines"]


def test_with_a_hole_the_alternative_draws_at_equation_7_1s_rate(cfg):
    out = derive.puff(_brief(HOLE), _footprint(), _derived(), cfg)
    alt = next(e for e in out["envelopes"] if e["name"] == "alternative")
    assert alt["contours"]
    # by hand: HA = pi (2.5 cm)^2 in square inches; chlorine Pt 113 psia, GF 29
    ha = math.pi * 0.025**2 / 6.4516e-4
    qr = ha * 113 * (1 / math.sqrt(298)) * 29  # lb/min
    assert alt["rate_kg_s"] == pytest.approx(qr / 132.2, rel=1e-9)
    assert alt["duration_s"] == pytest.approx(min(20000.0 / alt["rate_kg_s"], 3600.0))
    assert "Equation 7-1" in alt["rate_how"]


@pytest.mark.parametrize(
    "un, why",
    [
        (
            "1978",
            "the tank pressure for UN1978 is not held "
            "(Exhibit C-2 states no vapour pressure)",
        ),
        (
            "1951",
            "the gas factor for UN1951 is not held (EPA RMP Exhibits B-1 and C-2)",
        ),
    ],
)
def test_the_alternative_names_the_equations_input_not_held(cfg, un, why):
    rate, how = derive.equation_7_1(un, 0.05, cfg["weather"]["puff"])
    assert rate is None and how == why


def test_every_drawn_contour_carries_its_quantity_and_hole_sources(cfg):
    brief = _brief(HOLE)
    out = derive.puff(brief, _footprint(), _derived(), cfg)
    brief.derived = {"puff": out}
    lays = {lay["id"]: lay for lay in layers._puff_layers(layers._Ctx(brief, cfg))}
    for lid in ("puff_worst_case", "puff_alternative"):
        assert lays[lid]["features"], lid
        for f in lays[lid]["features"]:
            assert f["properties"]["quantity_source"] == "a test's stated quantity"
    for f in lays["puff_alternative"]["features"]:
        assert f["properties"]["hole_source"] == "a test's stated hole"
    assert "a test's stated quantity" in out["label"]


def test_a_contour_at_the_grids_edge_is_flagged_not_hidden(cfg):
    # HB-70 sizes the grid to the puff, so the channel no longer clips; the flag stays
    # for a grid smaller than the contour, driven here through `run_puff` directly
    spec = cfg["weather"]["puff"]
    out = derive.puff(_brief(STATED), _footprint(), _derived(), cfg)
    worst = next(e for e in out["envelopes"] if e["name"] == "worst_case")
    thresholds, why = derive._thresholds(
        load_app_pack("materials_properties").data.model_dump(mode="json")["materials"][
            "1017"
        ],
        load_app_pack("materials_properties").data.model_dump(mode="json")["air"],
        [int(m) for m in spec["contour_minutes"]],
    )
    assert why is None
    run = derive.run_puff(
        (-77.5394, 39.2756),
        worst,
        thresholds,
        derive._wind_at(_derived()["forecast"]["rows"]),
        load_app_pack("sigma_curves").data.model_dump(mode="json"),
        "D",
        300.0,
        spec,
    )
    assert run["at_grid_edge"]
    assert all(
        c["reaches_grid_edge"]
        for c in run["contours"]
        if c["threshold"] in run["at_grid_edge"]
    )


def test_with_a_small_erg_distance_the_grid_still_fits_the_puff(cfg):
    # HB-69 clipped this one at 300 m (150 m x 2); HB-70's grid takes the puff's reach
    out = derive.puff(_brief(STATED), _footprint(pad_m=150.0), _derived(), cfg)
    worst = next(e for e in out["envelopes"] if e["name"] == "worst_case")
    assert worst["contours"] and not worst["at_grid_edge"]
    assert not worst["beyond_grid_minutes"]
    assert not any("grid's edge" in line for line in out["lines"])
    assert out["grid"]["half_width_m"] >= out["grid"]["reach_m"] > 300.0


# ── the fixtures ──────────────────────────────────────────────────────────────────────


def test_every_fixture_block_is_valid_and_the_unknown_containers_state_none():
    rel = yaml.safe_load((REPO / "fixtures" / "scenario_releases.yaml").read_text())
    blocks = rel["releases"]
    for sid, block in blocks.items():
        got, refused = R.parse(block)
        assert refused is None and got.quantity_kg > 0, sid
        # Table 2.3 (gases) or, for a liquid, Table 2.2 (HB-110 Part 0)
        assert re.search(
            r"ERG 2024 methodology Table 2\.[23]\b", got.quantity_source
        ), sid
        assert got.hole_diameter_m is None, sid
    scenarios = yaml.safe_load((REPO / "fixtures" / "scenarios.yaml").read_text())
    for s in scenarios["scenarios"]:
        container = (s.get("incident") or {}).get("container")
        assert (s["id"] in blocks) is (container not in (None, "unknown")), s["id"]
        assert s.get("release") == blocks.get(s["id"]), s["id"]


# ── Equation 7-1's constants against their held pages ─────────────────────────────────


def _sources():
    spec = importlib.util.spec_from_file_location(
        "build_packs", REPO / "scripts" / "build_packs.py"
    )
    B = importlib.util.module_from_spec(spec)
    sys.modules["build_packs"] = B
    spec.loader.exec_module(B)
    return B.SourceSet(
        B.load_config(REPO / "packs" / "src" / "build_config.yaml"), REPO
    )


@needs_raw
def test_every_equation_7_1_quote_is_on_its_held_page(cfg):
    S = _sources()
    eq = cfg["weather"]["puff"]["equation_7_1"]
    quotes = [
        *eq["terms"],
        eq["tank_temperature_k"],
        eq["lb_min_per_kg_s"],
        eq["m2_per_in2"],
    ]
    quotes += list(eq["gases"].values())
    for q in quotes:
        assert S.quote_on_page(q["doc"], q["page"], q["quote"]), q


def test_the_constants_parse_from_their_quotes(cfg):
    eq = cfg["weather"]["puff"]["equation_7_1"]
    assert (
        derive._number_in(
            eq["tank_temperature_k"]["quote"], eq["tank_temperature_k"]["pattern"]
        )
        == 298
    )
    assert (
        derive._number_in(
            eq["lb_min_per_kg_s"]["quote"], eq["lb_min_per_kg_s"]["pattern"]
        )
        == 132.2
    )
    assert derive._number_in(
        eq["m2_per_in2"]["quote"], eq["m2_per_in2"]["pattern"]
    ) == pytest.approx(6.4516e-4)
    chlorine = derive._row_numbers(eq["gases"]["1017"]["quote"])
    assert chlorine[eq["gases"]["1017"]["gas_factor"]] == 29
    assert chlorine[eq["gases"]["1017"]["vapor_pressure_psia"]] == 113
    ammonia = derive._row_numbers(eq["gases"]["1005"]["quote"])
    assert ammonia[eq["gases"]["1005"]["gas_factor"]] == 14
    assert ammonia[eq["gases"]["1005"]["vapor_pressure_psia"]] == 145
