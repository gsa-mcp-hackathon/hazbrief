"""HB-03b: the any-UN ERG pack by triple keying, Table 2, and the spill surface.

The known answers (step 6) were written before the build ran: HB-01d's two worked
examples, the Esri widget's ERG 2016 chlorine rail values that ERG 2024 did not change,
and six rows read by eye from the rendered pages (PDF pp. 31, 293, 337 and 343) during
this task. The keying mechanics (range checks, the join, adjudication, the Key B
checkpoint) are tested on small inputs, network-free and model-free.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import erg_adjudicate as ADJ  # noqa: E402
import erg_join as J  # noqa: E402
import erg_keya as KA  # noqa: E402
import erg_keyb as KB  # noqa: E402

from hazbrief import models as M  # noqa: E402
from hazbrief.packs import default_packs  # noqa: E402

RAW = REPO / "corpus" / "raw"
needs_raw = pytest.mark.skipif(not RAW.is_dir(), reason="corpus/raw/ absent")


@pytest.fixture(scope="module")
def erg():
    return default_packs().erg.data


def _t1(erg, un: str, printed: str):
    m = erg.materials[un]
    hits = [e for e in m.table1 if e.printed_name == printed]
    assert len(hits) == 1, [e.printed_name for e in m.table1]
    return hits[0]


# ------------------------------------------------------------------ schema (step 1)
def test_the_schema_carries_table2_the_spill_surface_and_the_keying():
    fields = M.ErgMaterial.model_fields
    assert "table2" in fields and "where_spilled_matters" in fields
    t1 = M.Table1Entry.model_fields
    for f in (
        "water_reactive_note",
        "spilled_in",
        "keyed_by",
        "adjudicated",
        "unresolved",
    ):
        assert f in t1, f
    for model in (M.Table3Row, M.Table2Entry, M.ErgIndexName, M.GuideItem):
        for f in ("keyed_by", "adjudicated", "unresolved"):
            assert f in model.model_fields, (model.__name__, f)


def test_where_spilled_matters_exactly_when_table2_lists_the_material(erg):
    for un, m in erg.materials.items():
        assert m.where_spilled_matters == bool(m.table2), un


def test_the_pack_covers_every_yellow_index_id(erg):
    assert set(erg.materials) == set(erg.index)
    assert len(erg.index) == 1983


def test_every_table1_value_traces_to_a_page(erg):
    for un, m in erg.materials.items():
        for e in m.table1:
            assert e.locator.startswith("erg2024-en-pdf#p"), un
            assert 292 <= int(e.locator.split("#p")[1]) <= 335, (un, e.locator)
            assert e.keyed_by or e.unresolved, (un, e.printed_name)


# ------------------------------------------------------------------ known answers (step
# 6)
def test_hb01d_worked_example_chlorine_rail_day_low(erg):
    t3 = erg.materials["1017"].table3
    rail = next(r for r in t3.rows if r.container == "Rail tank car")
    assert rail.day.low.km == 9.6 and rail.day.low.mi == 6.0
    assert t3.locator == "erg2024-en-pdf#p343"


def test_hb01d_worked_example_chlorine_table1_small_night(erg):
    e = _t1(erg, "1017", "Chlorine")
    assert e.small.protect_night.km == 1.5
    assert e.locator == "erg2024-en-pdf#p292"


@needs_raw
def test_esri_2016_chlorine_rail_values_that_2024_did_not_change(erg):
    rows = json.loads((RAW / "esri-solutions-erg-widget-materials.txt").read_text())
    esri = next(r for r in rows if str(r["IDNum"]) == "1017")
    rail = next(
        r for r in erg.materials["1017"].table3.rows if r.container == "Rail tank car"
    )
    assert rail.isolate.m == esri["RAIL_ISO"] == 1000
    assert round(rail.day.high.km * 1000) == esri["RAILDYHI"] == 5100
    assert round(rail.night.low.km * 1000) == esri["RAILNTELOW"] == 11000
    assert rail.night.low.plus  # "11.0+" in 2024; Esri carries no "+" flag
    # and the one the edition changed: 9.9 km in 2016, 9.6 km in 2024
    assert esri["RAILDYLOW"] == 9900 and rail.day.low.km == 9.6


def test_by_eye_p293_acrolein(erg):
    e = _t1(erg, "1092", "Acrolein, stabilized")
    assert (e.small.isolate.m, e.small.isolate.ft) == (100, 300)
    assert (e.small.protect_day.km, e.small.protect_day.mi) == (1.3, 0.8)
    assert (e.small.protect_night.km, e.small.protect_night.mi) == (3.5, 2.2)
    assert (e.large.isolate.m, e.large.isolate.ft) == (600, 2000)
    assert (e.large.protect_day.km, e.large.protect_night.km) == (6.8, 11.1)
    assert e.guide == "131P" and e.locator == "erg2024-en-pdf#p293"


def test_by_eye_p293_phosgene(erg):
    e = _t1(erg, "1076", "Phosgene")
    assert e.small.isolate.m == 100
    assert (e.small.protect_day.km, e.small.protect_night.km) == (0.6, 2.5)
    assert (e.large.isolate.m, e.large.isolate.ft) == (500, 1500)
    assert (e.large.protect_day.km, e.large.protect_night.mi) == (3.0, 5.9)


def test_by_eye_p293_a_water_only_entry(erg):
    m = erg.materials["1162"]
    [e] = m.table1
    assert e.printed_name == "Dimethyldichlorosilane (when spilled in water)"
    assert e.spilled_in == "water"
    assert (e.small.isolate.m, e.small.protect_day.km, e.small.protect_night.km) == (
        30,
        0.1,
        0.1,
    )
    assert (e.large.isolate.m, e.large.protect_day.km, e.large.protect_night.km) == (
        30,
        0.4,
        1.2,
    )
    assert m.where_spilled_matters


def test_by_eye_p343_ammonia_nurse_tank(erg):
    rows = erg.materials["1005"].table3.rows
    r = next(r for r in rows if r.container == "Agricultural nurse tank")
    assert (r.isolate.m, r.isolate.ft) == (60, 200)
    assert (r.day.low.km, r.day.moderate.km, r.day.high.km) == (0.5, 0.3, 0.3)
    assert (r.night.low.km, r.night.moderate.km, r.night.high.km) == (1.4, 0.3, 0.3)


def test_by_eye_p337_sodium_dithionite_table2(erg):
    t2 = erg.materials["1384"].table2
    e = next(x for x in t2 if x.name == "Sodium dithionite")
    assert e.guide == "135" and e.gases == ["H2S", "SO2"]
    assert e.locator == "erg2024-en-pdf#p337"


def test_by_eye_p31_cyanogen_is_highlighted(erg):
    entry = erg.index["1026"]
    assert entry.in_table1
    assert [(n.name, n.guide) for n in entry.names] == [("Cyanogen", "119")]


def test_a_land_and_water_pair_is_two_entries(erg):
    """ERG p. 30 Note 1: UN1746 has one Table 1 entry for land and one for water."""
    m = erg.materials["1746"]
    assert sorted(e.spilled_in for e in m.table1) == ["land", "water"]


def test_the_table2_legend_names_every_gas_the_table_uses(erg):
    symbols = {g.symbol for g in erg.table2_legend}
    used = {
        g for m in erg.materials.values() for e in (m.table2 or []) for g in e.gases
    }
    assert used <= symbols


# ------------------------------------------------------------------ Key A mechanics
def test_range_checks_flag_a_misprinted_imperial_value():
    rc = {"ft_per_m": [3.0, 3.5], "mi_per_km": 0.621371, "mi_tolerance": 0.15}
    assert KA.check_m_ft(30, 100, rc) is None
    assert KA.check_m_ft(1000, 3000, rc) is None
    assert KA.check_m_ft(30, 300, rc)
    assert KA.check_km_mi(9.6, 6.0, rc) is None
    assert KA.check_km_mi(5.0, 3.3, rc)


def test_a_qualifier_is_split_from_the_printed_name():
    assert KA.split_qualifier("Thionyl chloride (when spilled on land)") == (
        "Thionyl chloride",
        "when spilled on land",
    )
    assert KA.split_qualifier("Chlorine") == ("Chlorine", None)


def test_a_line_broken_at_a_hyphen_joins_without_a_space():
    assert KA.join_parts(["Liquefied gases, non-", "flammable"]) == (
        "Liquefied gases, non-flammable"
    )
    assert KA.join_parts(["Argon, refrigerated liquid", "(cryogenic liquid)"]) == (
        "Argon, refrigerated liquid (cryogenic liquid)"
    )


def test_collinear_segments_make_one_rule():
    segs = [(10.0, 0.0, 40.0), (10.3, 40.0, 90.0), (30.0, 0.0, 20.0)]
    assert KA._collinear(segs, 80) == [10.0]


# ------------------------------------------------------------------ join and
# adjudication
def test_a_case_change_pairs_rows_and_reports_the_name():
    a = [
        {
            "id": "1040",
            "name": "Ethylene oxide with nitrogen",
            "guide": "119P",
            "highlighted": True,
            "page": 31,
        }
    ]
    c = [
        {
            "id": "1040",
            "name": "Ethylene oxide with Nitrogen",
            "guide": "119P",
            "highlighted": True,
        }
    ]
    [j] = J.join_keyed("yellow", a, c)
    assert j["class"] == "C_differs" and j["diffs"] == ["name"]


def test_alignment_survives_an_inserted_line():
    a = ["x", "new", "y", "z"]
    b = ["x", "y", "z"]
    assert J.align(a, b) == [(0, 0), (1, None), (2, 1), (3, 2)]


def test_decide_follows_the_rule():
    assert ADJ.decide("1.5", "1.5", "1.4") == ("1.5", "A", False, False)
    assert ADJ.decide("1.5", "1.6", "1.5") == ("1.5", "A", True, False)
    assert ADJ.decide("1.5", "1.6", "1.6") == ("1.6", "B", True, False)
    assert ADJ.decide("1.5", "1.6", "1.4") == (None, None, False, True)
    assert ADJ.decide("1.5", "1.6", None) == (None, None, False, True)


def test_comparison_form_folds_typesetting_only():
    assert J.cmp_form("Refer to the “General First Aid” section.") == J.cmp_form(
        'Refer to the "General First Aid" section.'
    )
    assert J.cmp_form("non‑flammable") == J.cmp_form("non-flammable")
    assert J.cmp_form("Chlorine") != J.cmp_form("chlorine")


def test_adjudication_never_fills_an_unresolved_field():
    a = {
        "id": "1017",
        "printed_name": "Chlorine",
        "name": "Chlorine",
        "guide": "124",
        "small": {"x": 1},
        "large": None,
        "large_refer_to_table3": True,
        "page": 292,
    }
    b = dict(a, guide="125")
    c = dict(a, guide="126")
    joined = [
        {
            "key": ["1017", "chlorine"],
            "class": "C_differs",
            "diffs": ["guide"],
            "a": a,
            "c": c,
            "page": 292,
        }
    ]
    final, unres, _ = ADJ.adjudicate_table("table1", joined, {292: [b]})
    [row] = final
    assert row["guide"] is None and row["unresolved"]
    assert row["unresolved_fields"] == ["guide"]
    assert unres and unres[0]["fields"] == ["guide"]


def test_a_row_only_key_b_and_key_c_print_is_added_from_b():
    c = {
        "id": "1001",
        "name": "Acetylene, dissolved",
        "guide": "116",
        "highlighted": False,
    }
    b = dict(c, table="yellow", page=31)
    joined = [
        {
            "key": ["1001", "acetylene, dissolved"],
            "class": "A_missing",
            "a": None,
            "c": c,
            "page": 31,
        }
    ]
    final, unres, dropped = ADJ.adjudicate_table("yellow", joined, {31: [b]})
    assert [r["keyed_by"] for r in final] == [["B", "C"]] and not unres and not dropped


# ------------------------------------------------------------------ Key B checkpoint
def test_unit_keys_change_with_the_prompt_and_the_model():
    k1 = KB.unit_key("table1", 292, 300, "m1")
    assert k1 != KB.unit_key("table1", 292, 300, "m2")
    assert k1 != KB.unit_key("table1", 292, 150, "m1")
    assert k1 != KB.unit_key("table1", 293, 300, "m1")


def test_a_reading_without_its_list_is_refused():
    with pytest.raises(ValueError):
        KB.parse_reading("table1", '{"rows": []}')
    with pytest.raises(ValueError):
        KB.parse_reading("guides", '{"rows": [1]}')
    assert KB.parse_reading("table2", '```json\n{"rows": [1]}\n```') == {"rows": [1]}


_FAKE_SQUIDDY = textwrap.dedent(
    """
    import json, os, time
    from contextlib import contextmanager
    from pathlib import Path

    CALLS = Path(os.environ["FAKE_CALLS"])

    class Inv:
        def __init__(self, content):
            self.content, self.usage, self.cost_usd = content, {}, 0.0
            self.seconds, self.receipt = 0.0, {"ok": True}
            self.resolved_model = "fake-model"

    class ClaudeCLIClient:
        def __init__(self, **kw):
            self.model, self.role, self.effort = "fake-model", "fake", "low"
            self.usage_totals, self.total_cost_usd = {}, 0.0
            self._cwd = Path(os.environ["FAKE_CWD"])
        def _cwd_for_child(self):
            self._cwd.mkdir(parents=True, exist_ok=True)
            return self._cwd
        def command(self, prompt):
            return ["claude", "-p", prompt, "--tools", ""]
        def spend_profile(self):
            return "fake"
        def invoke(self, prompt):
            page = prompt.split("It is page ")[1].split(" ")[0]
            with CALLS.open("a") as f:
                f.write(page + "\\n"); f.flush(); os.fsync(f.fileno())
            time.sleep(float(os.environ.get("FAKE_SLEEP", "0")))
            return Inv(json.dumps({"rows": [{"id": "1017", "page": page}]}))

    def run_pool(tasks, call, *, workers, retries=2, on_result=None, **kw):
        for t in tasks:
            r = {"task": t, "result": call(t), "error": None, "attempts": 1}
            on_result(t, r)
        return {}
    """
)
_FAKE_SPEND = textwrap.dedent(
    """
    from contextlib import contextmanager
    def declare_or_pilot(spec, guess):
        return {**spec, "record": "declare"}
    @contextmanager
    def job(rec):
        yield rec
    """
)
_RUNNER = textwrap.dedent(
    """
    import sys, json
    sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[2])
    import erg_keyb as KB
    from pathlib import Path
    KB.REPO = Path(sys.argv[3])
    KB.render = lambda src, page, dpi, out: out.write_bytes(b"png")
    KB.pdf_path = lambda: Path(sys.argv[3]) / "erg.pdf"
    cfg = KB.load_config(Path(sys.argv[3]) / "keys.yaml")
    pages = [{"table": "table1", "page": p} for p in range(292, 302)]
    KB.run_pages(cfg, pages, "job", Path(sys.argv[3]) / "run.log")
    """
)


def _fake_env(tmp_path: Path) -> tuple[list, dict]:
    fake = tmp_path / "fake"
    (fake / "squiddy").mkdir(parents=True)
    (fake / "squiddy" / "__init__.py").write_text("")
    (fake / "squiddy" / "model_client.py").write_text(_FAKE_SQUIDDY)
    (fake / "squiddy" / "spend.py").write_text(_FAKE_SPEND)
    root = tmp_path / "repo"
    root.mkdir()
    (root / "erg.pdf").write_bytes(b"%PDF")
    cfg = KB.load_config()
    cfg["paths"] = {**cfg["paths"], "keyb_dir": "keyB"}
    cfg["keyb"] = {**cfg["keyb"], "progress_seconds": 3600}
    (root / "keys.yaml").write_text(json.dumps(cfg))
    (tmp_path / "runner.py").write_text(_RUNNER)
    runner = str(tmp_path / "runner.py")
    argv = [sys.executable, runner, str(fake), str(REPO / "scripts"), str(root)]
    env = {
        **os.environ,
        "FAKE_CALLS": str(tmp_path / "calls.txt"),
        "FAKE_CWD": str(tmp_path / "cwd"),
    }
    return argv, env


def _rows(tmp_path: Path) -> list:
    p = tmp_path / "repo" / "keyB" / "pages.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]


@pytest.mark.load_sensitive
@pytest.mark.xdist_group("wall_clock")
def test_sigkill_mid_run_then_resume_reads_every_page_once(tmp_path):
    """Standards section 15.8: kill the loop with SIGKILL, restart it, and the result
    equals an uninterrupted run's, with no settled page read twice."""
    argv, env = _fake_env(tmp_path)
    proc = subprocess.Popen(argv, env={**env, "FAKE_SLEEP": "0.3"})
    ck = tmp_path / "repo" / "keyB" / "pages.jsonl"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if ck.exists() and len(ck.read_text().splitlines()) >= 3:
            break
        time.sleep(0.05)
    os.kill(proc.pid, signal.SIGKILL)
    proc.wait()
    settled_before = {r["page"] for r in _rows(tmp_path)}
    assert 3 <= len(settled_before) < 10
    subprocess.run(argv, env={**env, "FAKE_SLEEP": "0"}, check=True)
    rows = _rows(tmp_path)
    assert sorted(r["page"] for r in rows) == list(range(292, 302))
    calls = (tmp_path / "calls.txt").read_text().split()
    # every settled page was called once; at most the one in flight at the kill twice
    twice = [p for p in set(calls) if calls.count(p) > 1]
    assert not set(int(p) for p in twice) & settled_before
    assert len(twice) <= 1

    # an uninterrupted run gives the same readings
    clean = tmp_path / "clean"
    clean.mkdir()
    argv2, env2 = _fake_env(clean)
    subprocess.run(argv2, env={**env2, "FAKE_SLEEP": "0"}, check=True)
    strip = lambda rs: sorted((r["page"], json.dumps(r["reading"])) for r in rs)  # noqa: E731
    assert strip(rows) == strip(_rows(clean))


# ------------------------------------------------------- guide evacuation variants
def test_a_guide_with_liquids_and_solids_distances(erg):
    ev = erg.guides["135"].evacuation
    assert ev.immediate_precautionary.m == 50
    assert ev.immediate_precautionary_solids.m == 25


def test_a_guide_with_a_large_spill_in_all_directions(erg):
    ev = erg.guides["112"].evacuation
    assert ev.immediate_precautionary.m == 500
    assert ev.large_spill_all_directions.m == 800 and ev.large_spill_downwind is None
    assert (ev.fire_isolate.m, ev.fire_evacuate.m) == (1600, 1600)


def test_a_guide_with_a_fire_evacuation_only(erg):
    ev = erg.guides["161"].evacuation
    assert ev.fire_isolate is None and ev.fire_evacuate.m == 300


def test_every_printed_guide_yields_its_immediate_precautionary_distance(erg):
    assert len(erg.guides) == 62  # 64 guides; 121 and 167 print no text
    assert all(g.evacuation.immediate_precautionary for g in erg.guides.values())
