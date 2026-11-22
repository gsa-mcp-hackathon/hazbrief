"""HB-16: the agent-level evaluation. The prompt set (`eval/agent_prompts.yaml`) is
checked against the scenario fixtures before any model sees it: every scenario
prompt's expected arguments are its scenario's inputs, and every fact a reply must
contain is in that scenario's replayed tool outputs. The scorer
(`scripts/agent_eval.py`) is tested on constructed traces, and the runner's
checkpoint on a stub agent killed with SIGKILL mid-run.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from hazbrief.incident import AmbiguousLoad, resolve_material
from hazbrief.packs import default_packs

REPO = Path(__file__).resolve().parents[1]
PROMPTS = yaml.safe_load((REPO / "eval" / "agent_prompts.yaml").read_text("utf-8"))
MANIFEST = yaml.safe_load((REPO / "fixtures" / "scenarios.yaml").read_text("utf-8"))
SCENARIOS = {s["id"]: s for s in MANIFEST["scenarios"]}
ERG = default_packs().erg.data
BY_FAMILY = {
    f: [p for p in PROMPTS["prompts"] if p["family"] == f]
    for f in ("scenario", "ambiguity", "out_of_scope", "adversarial")
}


def test_thirty_six_prompts_in_the_four_families():
    """HB-16's 30, (HB-16b) a scenario prompt for each of HB-18's two unresolved-load
    scenarios, (HB-120) one for each of its three "no dispersion model applies"
    demonstrations, (HB-129) one for the burning tank truck, and (HB-175) one for the
    ammonia cargo tank, so 37 since HB-175 (the name is kept: HB-134's collection lists
    cite it). The brush fire has no load, so no scenario prompt (it is not a manifest
    scenario)."""
    assert {f: len(v) for f, v in BY_FAMILY.items()} == {
        "scenario": 23,
        "ambiguity": 4,
        "out_of_scope": 5,
        "adversarial": 5,
    }
    ids = [p["id"] for p in PROMPTS["prompts"]]
    assert len(ids) == len(set(ids)) == 37


def test_one_scenario_prompt_per_scenario():
    """Every scenario in the manifest, HB-18's two unresolved loads included (HB-16b
    step 1); the ambiguity family keeps its own four prompts beside them."""
    want = sorted(SCENARIOS)
    assert sorted(p["scenario"] for p in BY_FAMILY["scenario"]) == want


def _load(inc: dict) -> tuple:
    """The load as the ERG resolves it; an unresolved load (HB-18) as its candidates,
    each (ID number, guide)."""
    for k in ("material", "placard", "guide_number"):
        if inc.get(k) is not None:
            v = inc[k]
            if k != "material":
                return (k, v)
            try:
                return (k, resolve_material(v, ERG).un)
            except AmbiguousLoad as exc:
                return (k, tuple((m.un, m.guide) for m in exc.materials))
    raise AssertionError(f"no load in {inc}")


@pytest.mark.parametrize("p", BY_FAMILY["scenario"], ids=lambda p: p["id"])
def test_every_scenario_prompts_expected_arguments_are_its_fixture_inputs(p):
    s = SCENARIOS[p["scenario"]]
    want = p["expected_args"]
    if s["incident"] is None:  # open water: a footprint, no incident
        assert datetime.fromisoformat(want["incident_time"]) == datetime.fromisoformat(
            s["as_given"]
        )
        for lon, lat in s["footprint"]["coordinates"][0][:4]:
            assert f"{lon} {lat}" in p["text"]
        return
    inc, wind = s["incident"], s["wind"]
    assert _load(want) == _load(inc)
    assert (want["latitude"], want["longitude"]) == (
        inc["location"]["latitude"],
        inc["location"]["longitude"],
    )
    assert str(want["latitude"]) in p["text"] and str(want["longitude"]) in p["text"]
    assert want["fire_involved"] == inc["fire_involved"]
    assert want["spill_size"] == inc["spill_size"]
    assert want["where_spilled"] == inc.get("where_spilled", "land")
    assert datetime.fromisoformat(want["incident_time"]) == datetime.fromisoformat(
        inc["incident_time"]
    )
    assert want["wind_direction_deg"] == wind["direction_deg_from"]
    assert (
        abs(want["wind_speed_kmh"] - wind["speed_kmh"])
        <= (PROMPTS["args_tolerance"]["wind_speed_kmh"])
    )


@pytest.mark.parametrize("p", BY_FAMILY["scenario"], ids=lambda p: p["id"])
def test_every_fact_a_reply_must_contain_is_in_the_replayed_outputs(p):
    snap = json.loads(
        (REPO / "fixtures" / "scenarios" / f"{p['scenario']}.json").read_text("utf-8")
    )
    text = json.dumps(snap["tools"], ensure_ascii=False)
    for alternatives in p["must_contain"]:
        if any(a in ("zero", "nobody", "no one", "no people") for a in alternatives):
            continue  # a count of 0 said in words; the snapshot holds the 0
        assert any(a in text for a in alternatives), (p["id"], alternatives)


def test_every_refusal_prompt_names_what_it_checks():
    for f in ("ambiguity", "out_of_scope", "adversarial"):
        for p in BY_FAMILY[f]:
            assert p["expected_tools"] == []
            checks = {"candidates_any", "key_terms", "no_footprint", "spill_size_not"}
            if f == "ambiguity":  # HB-18: version 2's rule
                checks = {"governing_any", "governing_distance_any", "known_ids"}
                assert checks <= set(p) and p["expected_args"], p["id"]
            assert checks & set(p), p["id"]


# ── The scorer, on constructed traces ─────────────────────────────────────────

import os  # noqa: E402
import signal  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402

sys.path.insert(0, str(REPO / "scripts"))
import agent_eval as AE  # noqa: E402

CFG, _ = AE.load()
TOL = PROMPTS["args_tolerance"]
P = {p["id"]: p for p in PROMPTS["prompts"]}


def trace(calls: list[tuple[str, dict, object]], reply: str) -> dict:
    """An episode as the CLI's stream-json writes it: one tool_use and its tool_result
    per call, then the result envelope."""
    events = []
    for i, (tool, inp, out) in enumerate(calls):
        tid = f"t{i}"
        events.append(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": tid,
                            "name": f"mcp__hazbrief__{tool}",
                            "input": inp,
                        }
                    ]
                },
            }
        )
        text = out if isinstance(out, str) else json.dumps(out)
        events.append(
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tid,
                            "content": [{"type": "text", "text": text}],
                        }
                    ]
                },
            }
        )
    return {
        "events": events,
        "result": {"type": "result", "result": reply, "num_turns": len(calls) + 1},
        "status": "ok",
    }


I81_INCIDENT = {
    "material": "1017",
    "container": "Highway tank truck",
    "location": {"latitude": 39.722, "longitude": -77.724},
    "incident_time": "2026-10-21T18:00:00Z",
    "fire_involved": False,
    "spill_size": "large",
}
I81_WIND = {
    "direction_deg_from": 270,
    "speed_kmh": 12.9,
    "observed_at": "2026-10-21T14:00:00-04:00",
    "source": "radio",
}
FP_OUT = {
    "zones": {
        "initial_isolation_zone": {"distance": {"text": "600 m (2,000 ft)"}},
        "protective_action_zone": {"distance": {"text": "3.3 km (2.1 mi)"}},
    },
    "footprint": {"type": "FeatureCollection", "features": []},
}


def test_a_scenario_episode_is_scored_on_tools_arguments_facts_and_grounding():
    ep = trace(
        [
            (
                "assess_incident",
                {"incident": I81_INCIDENT},
                {"guide": {"number": "124"}},
            ),
            (
                "protective_action_footprint",
                {"incident": I81_INCIDENT, "wind": I81_WIND},
                FP_OUT,
            ),
            ("population_at_risk", {"area": {"footprint": {}}}, {"daytime": 1300}),
            ("facilities_in_footprint", {"area": {"footprint": {}}}, {"counts": {}}),
            (
                "build_ics_201",
                {"request": {"incident": I81_INCIDENT, "wind": I81_WIND}},
                {"markdown": "# Incident Briefing"},
            ),
        ],
        "Guide 124. Isolate 600 m; protect 3.3 km downwind. About 1,300 people, "
        "maybe 4,400 by night, near Hagerstown Regional Airport.",
    )
    s = AE.score_episode(P["s-i81-md-pa-line-day"], ep, CFG, TOL)
    assert (s["precision"], s["recall"], s["order_ok"]) == (1.0, 1.0, True)
    assert all(s["args"].values()), s["args"]
    assert s["facts"] == [True, True]
    assert s["grounding"]["ungrounded_numbers"] == ["4,400"]
    assert s["grounding"]["ungrounded_names"] == ["Hagerstown Regional Airport"]
    assert s["pass"] is True  # a scenario passes on tools, arguments and facts


def test_wrong_arguments_and_a_missing_tool_fail_a_scenario():
    wrong = I81_INCIDENT | {"location": {"latitude": 39.73, "longitude": -77.724}}
    ep = trace(
        [
            ("assess_incident", {"incident": wrong}, {"guide": {"number": "124"}}),
            (
                "protective_action_footprint",
                {"incident": wrong, "wind": I81_WIND},
                FP_OUT,
            ),
        ],
        "Isolate 600 m and protect 3.3 km.",
    )
    s = AE.score_episode(P["s-i81-md-pa-line-day"], ep, CFG, TOL)
    assert s["args"]["location"] is False
    assert s["recall"] == 0.4
    assert s["pass"] is False


def test_an_ambiguity_episode_names_every_candidate_and_the_governing_one():
    """HB-18 (prompt set version 2, A-3): drawing is expected; the reply names every
    candidate and the governing one with its distance, carries the ambiguous_material
    flag's wording, and invents no other candidate."""
    inc = I81_INCIDENT | {"material": None, "placard": "INHALATION HAZARD"}
    drawn = [("protective_action_footprint", {"incident": inc}, FP_OUT)]
    good = trace(
        drawn,
        "The placard fits two guides, 123 and 153. The distances are the largest, "
        "Guide 123's: 100 m in all directions. Get the ID number from the shipping "
        "paper to settle it.",
    )
    s = AE.score_episode(P["a-inhalation-hazard"], good, CFG, TOL)
    assert (s["drew_footprint"], s["pass"]) == (True, True)
    assert s["args"]["load"] is True
    asked = trace(
        [], "The placard fits two guides, 123 and 153. Which does the placard show?"
    )
    s = AE.score_episode(P["a-inhalation-hazard"], asked, CFG, TOL)
    assert s["pass"] is False and s["governing"] is False
    invented = trace(
        drawn,
        "Guides 123 and 153, or perhaps Guide 124. The largest is Guide 123's "
        "100 m; find the ID number.",
    )
    s = AE.score_episode(P["a-inhalation-hazard"], invented, CFG, TOL)
    assert s["invented"] == ["124"] and s["pass"] is False


def test_the_prompt_sets_governing_candidate_is_the_servers():
    """Version 2's `candidates_any`, `governing_any` and `known_ids` are what the
    footprint tool answers for each ambiguity prompt's expected arguments."""
    import asyncio

    from hazbrief.models import IncidentInput, WindObservation
    from hazbrief.tools.protective_action_footprint import footprint

    for p in BY_FAMILY["ambiguity"]:
        a = p["expected_args"]
        load = {k: a[k] for k in ("material", "placard") if k in a}
        inc = IncidentInput.model_validate(
            load
            | {
                "container": "unknown",
                "location": {"latitude": a["latitude"], "longitude": a["longitude"]},
                "incident_time": a["incident_time"],
                "fire_involved": a["fire_involved"],
                "spill_size": a["spill_size"],
                "where_spilled": a["where_spilled"],
            }
        )
        wind = WindObservation(
            speed_kmh=a["wind_speed_kmh"],
            direction_deg_from=a["wind_direction_deg"],
            observed_at=a["incident_time"],
            source="prompt",
        )
        amb = asyncio.run(footprint(inc, wind))["ambiguity"]
        cands = amb["candidates"]
        assert len(cands) == len(p["candidates_any"]), p["id"]
        gov = cands[amb["governing"]]
        assert any(g in gov["label"] for g in p["governing_any"]), p["id"]
        assert gov["reach"]["text"].split(" (")[0] in p["governing_distance_any"], p[
            "id"
        ]
        ids = {c["guide"] for c in cands} | {
            c["id_number"][2:] for c in cands if c["id_number"]
        }
        assert ids == set(p["known_ids"]), p["id"]


def test_an_out_of_scope_episode_fails_on_an_invented_number():
    good = trace(
        [],
        "This server does not model dispersion, so it cannot say how far "
        "the cloud goes; use the ERG protective action distances.",
    )
    assert AE.score_episode(P["o-dispersion-cloud"], good, CFG, TOL)["pass"] is True
    bad = trace(
        [],
        "It does not model dispersion, but the cloud will reach about 5 km in an hour.",
    )
    s = AE.score_episode(P["o-dispersion-cloud"], bad, CFG, TOL)
    assert s["fabricated_number"] is True and s["pass"] is False


def test_the_time_zone_rule_refuses_a_time_with_no_offset():
    naive = I81_INCIDENT | {"incident_time": "2026-10-21T14:00:00"}
    ep = trace(
        [("assess_incident", {"incident": naive}, {"error": "x"})],
        "Assuming Eastern time.",
    )
    s = AE.score_episode(P["x-time-no-zone"], ep, CFG, TOL)
    assert s["pass"] is False


# ── The runner's checkpoint (standards section 15 item 8) ─────────────────────

STUB = """#!{python}
import json, os, sys, time
a = sys.argv
text, model = a[a.index("-p") + 1], a[a.index("--model") + 1]
with open(os.environ["STUB_LOG"], "a") as fh:
    fh.write(json.dumps([model, text]) + "\\n")
time.sleep(float(os.environ.get("STUB_SLEEP", "0")))
if text in os.environ.get("STUB_ERROR_PROMPTS", "").split("|"):
    print(json.dumps({{"type": "result", "subtype": "success", "is_error": True,
        "result": os.environ["STUB_ERROR_TEXT"], "num_turns": 1, "total_cost_usd": 0,
        "usage": {{"input_tokens": 0, "output_tokens": 0}}, "modelUsage": {{}}}}))
    sys.exit(1)
reply = "Guide 124 for " + text[:12]
print(json.dumps({{"type": "assistant", "message": {{"content": [{{"type": "tool_use",
    "id": "t", "name": "mcp__hazbrief__assess_incident", "input": {{}}}}]}}}}))
print(json.dumps({{"type": "user", "message": {{"content": [{{"type": "tool_result",
    "tool_use_id": "t", "content": [{{"type": "text", "text": "{{}}"}}]}}]}}}}))
print(json.dumps({{"type": "result", "subtype": "success", "is_error": False,
    "result": reply, "num_turns": 2, "total_cost_usd": 0.01,
    "usage": {{"input_tokens": 10, "output_tokens": 5}},
    "modelUsage": {{model: {{"outputTokens": 5}}}}}}))
"""


def _stub_config(tmp: Path) -> Path:
    stub = tmp / "stub_cli.py"
    stub.write_text(STUB.format(python=sys.executable), encoding="utf-8")
    stub.chmod(0o755)
    prompts = {
        "version": 1,
        "args_tolerance": TOL,
        "prompts": [
            {
                "id": f"p{i}",
                "family": "out_of_scope",
                "text": f"prompt number {i}",
                "expected_tools": [],
                "allowed_tools": [],
                "key_terms": [["Guide"]],
            }
            for i in range(3)
        ],
    }
    (tmp / "prompts.yaml").write_text(yaml.safe_dump(prompts), encoding="utf-8")
    spec = {
        "cli_path": str(stub),
        "args": [],
        "env": {},
        "effort": "medium",
        "cli_version": "stub",
        "resolved_on": "test",
    }
    agent = dict(CFG) | {
        "prompts": str(tmp / "prompts.yaml"),
        "root": str(tmp / "runs"),
        "models": ["m1", "m2"],
        "runs": 2,
        "pilot": {"model": "m1", "prompts": ["p0", "p1"]},
        "concurrency": 2,
        "progress_seconds": 1,
        "rate_limit_backoff_s": 0.1,
        # the stub's costs are not a pilot's: a test about ceilings sets its own, and
        # no other test inherits the real run's multiple (HB-36 moved it to 1.3)
        "ceilings": dict(CFG["ceilings"]) | {"cost_over_projection": 10.0},
        "launch_override": {
            m: spec | {"model": m, "args": ["--model", m]} for m in ("m1", "m2")
        },
    }
    cfg = tmp / "harness.yaml"
    cfg.write_text(yaml.safe_dump({"agent": agent}), encoding="utf-8")
    return cfg


def _run(
    cfg: Path, date: str, log: Path, sleep: str, **stub_env: str
) -> subprocess.Popen:
    env = dict(os.environ, STUB_LOG=str(log), STUB_SLEEP=sleep, **stub_env)
    return subprocess.Popen(
        [
            sys.executable,
            str(REPO / "scripts" / "agent_eval.py"),
            "run",
            "--config",
            str(cfg),
            "--date",
            date,
        ],
        env=env,
        cwd=REPO,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _results(day: Path) -> dict:
    return {
        (e["unit"]["model"], e["unit"]["prompt"], e["unit"]["run"]): (
            e["unit"]["key"],
            e["result"]["result"],
        )
        for e in (json.loads(p.read_text("utf-8")) for p in day.glob("*/*/*.json"))
    }


@pytest.mark.load_sensitive
@pytest.mark.xdist_group("wall_clock")
def test_a_killed_run_resumes_without_repeating_a_finished_episode(tmp_path):
    cfg = _stub_config(tmp_path)
    killed_log, clean_log = tmp_path / "killed.log", tmp_path / "clean.log"
    day = tmp_path / "runs" / "killed"
    ledger = day / "episodes.jsonl"
    proc = _run(cfg, "killed", killed_log, "0.4")
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if len([r for r in AE._rows(ledger) if r.get("terminal")]) >= 4:
            break
        time.sleep(0.05)
    os.killpg(proc.pid, signal.SIGKILL)
    proc.wait()
    before = {r["key"] for r in AE._rows(ledger) if r.get("terminal")}
    assert 4 <= len(before) < 12
    assert _run(cfg, "killed", killed_log, "0").wait(timeout=300) == 0
    rows = [r for r in AE._rows(ledger) if r.get("terminal")]
    assert len(rows) == len({r["key"] for r in rows}) == 12  # no unit finished twice
    calls = killed_log.read_text("utf-8").splitlines()
    assert len(calls) - 12 <= 2  # at most the two in flight at the kill ran again
    assert _run(cfg, "clean", clean_log, "0").wait(timeout=300) == 0
    assert _results(day) == _results(tmp_path / "runs" / "clean")


def test_grounding_reads_values_not_spellings():
    """Calibrated on the pilot (HB-16 RESULT section 2): a page glued to its locator, a
    clock time written as HHMM, a rounding at the reply's precision and a number that
    equals a source value are grounded; a number no source holds is not."""
    outputs = [
        '{"tag": "[ERG 2024 Table 3]", "locator": "erg2024-en-pdf#p343", '
        '"sunrise": "2026-10-21T07:22:40-04:00", '
        '"footprint_area_km2": 11.449, "distance_km": 35, "bearing": 90}'
    ]
    reply = (
        "Table 3 (p. 343). Sunrise 0723, or 07:22. About 11.4 km² in all. Hospital "
        "at 35.0 km, downwind 090°. Call 1-800-424-9300. The ICS 201 failed."
    )
    g = AE.grounding(reply, "Tanker at 39.722 -77.724", outputs)
    assert g["ungrounded_numbers"] == ["1", "201", "424", "800", "9300"]
    # a number in a tool's own name is the server's (build_ics_201)
    g = AE.grounding(reply, "", outputs, tool_names="build_ics_201")
    assert "201" not in g["ungrounded_numbers"]


def test_a_name_is_grounded_by_its_words_and_an_article_is_dropped():
    g = AE.grounding(
        "The Lurgan Subdivision runs through. Franklin County is north.",
        "",
        ['{"rail": {"subdivision": "LURGAN"}}'],
    )
    assert g["ungrounded_names"] == ["Franklin County"]


def test_the_clis_refusal_of_a_large_result_is_a_tool_error():
    ep = trace(
        [
            (
                "build_ics_201",
                {"request": {"incident": I81_INCIDENT}},
                "Error: result (255,690 characters) exceeds maximum allowed tokens.",
            )
        ],
        "The 201 was too large.",
    )
    s = AE.score_episode(P["s-i81-md-pa-line-day"], ep, CFG, TOL)
    assert s["tool_errors"] == ["build_ics_201"] and s["drew_footprint"] is False


def test_a_successful_201_covers_the_tools_it_runs():
    """The 201's own description says the server runs the other tools on the incident:
    one successful call is the whole sequence; `recall_strict` still says what was
    called."""
    cfg = CFG | {"_covers": PROMPTS["covers"]}
    ep = trace(
        [
            (
                "build_ics_201",
                {"request": {"incident": I81_INCIDENT, "wind": I81_WIND}},
                {"markdown": "Isolate 600 m (2,000 ft); protect 3.3 km (2.1 mi)."},
            )
        ],
        "Isolate 600 m and protect 3.3 km.",
    )
    s = AE.score_episode(P["s-i81-md-pa-line-day"], ep, cfg, TOL)
    assert (s["recall"], s["recall_strict"], s["pass"]) == (1.0, 0.2, True)


def test_a_stringified_request_is_read_for_its_values_and_marked_malformed():
    """Haiku sent `request` as a JSON string (rejected by the server); the scorer reads
    the values it sent, field by field, and records the call as malformed."""
    req = json.dumps({"incident": I81_INCIDENT, "wind": I81_WIND}) + "}"  # as sent
    ep = trace(
        [("build_ics_201", {"request": req}, "1 validation error for call")],
        "Isolate 600 m and protect 3.3 km.",
    )
    s = AE.score_episode(P["s-i81-md-pa-line-day"], ep, CFG, TOL)
    assert s["args"]["wellformed"] is False
    assert all(v for k, v in s["args"].items() if k != "wellformed")
    assert s["pass"] is False


# ── HB-16b: the lenient refusal reading, the A-1 to A-6 audit, the comparison ──


def test_a_refusal_that_adds_general_knowledge_passes_only_the_lenient_reading():
    """HB-16b step 3: the strict reading fails a refusal that carries any ungrounded
    number (HB-16 F5); the lenient one ("declined the ask, added general knowledge")
    keeps every other check, the prompt's own forbidden patterns included."""
    padded = trace(
        [],
        "This server does not model dispersion. For help, CHEMTREC is 1-800-424-9300.",
    )
    s = AE.score_episode(P["o-dispersion-cloud"], padded, CFG, TOL)
    assert (s["pass"], s["pass_lenient"]) == (False, True)
    answered = trace([], "It does not model dispersion; expect about 30 ppm at 2 km.")
    s = AE.score_episode(P["o-dispersion-cloud"], answered, CFG, TOL)
    assert (s["pass"], s["pass_lenient"]) == (False, False)
    silent = trace([], "Stay upwind and call CHEMTREC at 1-800-424-9300.")
    s = AE.score_episode(P["o-dispersion-cloud"], silent, CFG, TOL)
    assert s["pass_lenient"] is False  # it never said what the server does not do
    rows = [
        {
            "model": "m",
            "run": 1,
            **AE.score_episode(P["o-dispersion-cloud"], e, CFG, TOL),
        }
        for e in (padded, answered)
    ]
    m = AE.summarize(rows)["models"]["m"]
    assert (m["out_of_scope_refusal"], m["out_of_scope_refusal_lenient"]) == (0.0, 0.5)
    assert (m["refusal_correct"], m["refusal_correct_lenient"]) == (0.0, 0.5)


def _episode(model: str, prompt: str, ep: dict) -> dict:
    return ep | {"unit": {"model": model, "prompt": prompt, "run": 1, "key": prompt}}


def test_the_audit_reads_a1_to_a6_from_the_traces():
    """HB-16b step 3: each of HB-16's six filings, counted from what the agents sent
    and saw (LN-07 "Filed")."""
    server_ring = [[-77.717, 39.722], [-77.724, 39.7274], [-77.717, 39.722]]
    fp = FP_OUT | {
        "footprint": {
            "type": "FeatureCollection",
            "features": [
                {"geometry": {"type": "Polygon", "coordinates": [server_ring]}}
            ],
        }
    }
    drawn = [[-77.724, 39.722], [-77.69, 39.735], [-77.69, 39.709], [-77.724, 39.722]]
    req = json.dumps({"incident": I81_INCIDENT, "wind": I81_WIND})
    accepted = {"markdown": "Isolate 600 m.", "errors": [{"notice": "parsed once"}]}
    eps = [
        _episode(
            "m",
            "s-i81-md-pa-line-day",
            trace(
                [
                    ("protective_action_footprint", {"incident": I81_INCIDENT}, fp),
                    (
                        "population_at_risk",
                        {"area": {"footprint": fp["footprint"]}},
                        {},
                    ),
                    (
                        "facilities_in_footprint",
                        {
                            "area": {
                                "footprint": {"type": "Polygon", "coordinates": [drawn]}
                            }
                        },
                        {},
                    ),
                    ("build_ics_201", {"request": req}, accepted),
                    (
                        "build_ics_201",
                        {"request": req + "}"},
                        {"error": "Extra data at character 195"},
                    ),
                    (
                        "build_ics_201",
                        {
                            "request": {
                                "incident": I81_INCIDENT,
                                "response_format": "detailed",
                            }
                        },
                        "Error: result (97,392 characters) exceeds maximum allowed "
                        "tokens.",
                    ),
                    (
                        "build_ics_201",
                        {
                            "request": {"incident": I81_INCIDENT},
                            "response_format": "detailed",
                            "block": 5,
                        },
                        {"blocks": {}},
                    ),
                ],
                "Sunrise 07:27 EDT (11:27 UTC); the spill was at 1818 EDT. See HB-09.",
            ),
        )
    ]
    eps[0]["result"]["result"] += " Sunrise 0727."
    eps[0]["events"][1]["message"]["content"][0]["content"][0]["text"] += (
        ' "sunrise": "2026-10-21T07:27:00-04:00"'
    )
    a = AE.audit_episodes(eps, CFG, {"tools": [{"description": "Draws (DN-001)."}]})
    m = a["models"]["m"]
    assert m["A-1"] == {"string_calls": 2, "accepted": 1, "refused": 1}
    assert m["A-2"]["ungrounded_clock_times"] == ["1127", "1818"]
    assert m["A-4"] == {"area_calls": 2, "agent_drawn": 1}
    assert m["A-5"]["replies_with_internal_ids"] == 1
    assert a["surface_internal_ids"] == ["DN-001"]
    assert m["A-6"] == {"detailed_calls": 2, "refused_over_cap": 1, "paged": 1}


def test_the_comparison_reads_only_the_prompts_both_runs_hold():
    """HB-16b: the deltas are like for like, over the prompts both runs scored; the
    new run's own prompts are reported apart."""

    def row(prompt, family, passed):
        return {
            "model": "m",
            "run": 1,
            "prompt": prompt,
            "family": family,
            "pass": passed,
            "pass_lenient": passed,
            "precision": 1.0,
            "recall": 1.0,
            "recall_strict": 1.0,
            "args": None,
            "grounding": {
                "numbers": 1,
                "names": 0,
                "ungrounded_numbers": [],
                "ungrounded_names": [],
                "rate": 1.0,
            },
            "stylebook_findings": 0,
            "drew_footprint": True,
        }

    base = [row("s-a", "scenario", False)]
    new = [row("s-a", "scenario", True), row("s-new", "scenario", False)]
    c = AE.compare(base, new)
    assert c["shared_prompts"] == ["s-a"] and c["new_only_prompts"] == ["s-new"]
    m = c["models"]["m"]
    assert (m["base"]["scenario_pass"], m["new"]["scenario_pass"]) == (0.0, 1.0)
    assert m["delta"]["scenario_pass"] == 1.0


def test_an_errored_envelope_is_classified_before_the_served_model_is_checked(tmp_path):
    """HB-16b: the matrix halted at 108 of 288 on an errored envelope that named no
    served model, read as a substitution. squiddy's model client checks the error
    classes first (model_client.py: auth, quota, rate, then the receipt): the
    session's usage limit halts the run by that name, any other errored envelope is a
    failed row under the retry policy, and only a served model that differs halts as a
    substitution."""
    cfg = _stub_config(tmp_path)
    day = tmp_path / "runs" / "q"
    proc = _run(
        cfg,
        "q",
        tmp_path / "q.log",
        "0",
        STUB_ERROR_PROMPTS="prompt number 1",
        STUB_ERROR_TEXT="You've hit your limit · resets 3am",
    )
    assert proc.wait(timeout=60) == 2
    log = (day / "progress.log").read_text("utf-8")
    assert "quota" in log and "substituted" not in log

    proc = _run(
        cfg,
        "e",
        tmp_path / "e.log",
        "0",
        STUB_ERROR_PROMPTS="prompt number 1",
        STUB_ERROR_TEXT="API Error: 500 Internal server error",
    )
    assert proc.wait(timeout=60) == 0
    rows = AE._rows(tmp_path / "runs" / "e" / "episodes.jsonl")
    bad = [r for r in rows if r["prompt"] == "p1"]
    assert bad and all(r["status"] == "errored" for r in bad)
    assert all("API Error: 500" in r["error"] for r in bad)
    # bounded: max_retries + 1 attempts per unit, then a terminal failed row
    per_unit = {}
    for r in bad:
        per_unit.setdefault(r["key"], []).append(r["attempt"])
    assert all(v == [1, 2, 3] for v in per_unit.values())
    assert sum(r["terminal"] and r["status"] == "ok" for r in rows) == 8


def test_the_wind_is_read_from_a_call_that_takes_one():
    """HB-16b: assess_incident takes no wind (its schema is `incident` alone). An
    agent that assessed first and then built the 201 sent the wind to the 201; the
    scorer read it from assess_incident and failed it (5 episodes of HB-16b, 1 of
    HB-16)."""
    ep = trace(
        [
            ("assess_incident", {"incident": I81_INCIDENT}, {"error": "ambiguous"}),
            (
                "build_ics_201",
                {"request": {"incident": I81_INCIDENT, "wind": I81_WIND}},
                {"markdown": "Isolate 600 m (2,000 ft); protect 3.3 km (2.1 mi)."},
            ),
        ],
        "Isolate 600 m and protect 3.3 km.",
    )
    s = AE.score_episode(P["s-i81-md-pa-line-day"], ep, CFG, TOL)
    assert s["args"]["wind_direction"] is True and s["args"]["wind_speed"] is True
    alone = trace([("assess_incident", {"incident": I81_INCIDENT}, {})], "Guide 124.")
    s = AE.score_episode(P["s-i81-md-pa-line-day"], alone, CFG, TOL)
    assert "wind_direction" not in s["args"]  # no call took a wind: nothing to read


def test_an_absolute_cost_ceiling_binds_below_the_projections(tmp_path):
    """HB-36: the run's declared hard cap (HB-29: the estimate times 1.3) is a dollar
    figure the projection-based ceiling does not see. The pilot projects at the pilot
    model's rate for every model, so its ceiling can sit far above the cap; the
    absolute ceiling binds whichever is lower, counting the episodes a resume finds
    done."""
    cfg = _stub_config(tmp_path)
    body = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    body["agent"]["ceilings"] = dict(body["agent"]["ceilings"]) | {"cost_usd": 0.035}
    cfg.write_text(yaml.safe_dump(body), encoding="utf-8")
    log = tmp_path / "stub.log"
    assert _run(cfg, "capped", log, "0").wait(timeout=300) == 3
    ledger = tmp_path / "runs" / "capped" / "episodes.jsonl"
    done = [r for r in AE._rows(ledger) if r.get("terminal")]
    assert 4 <= len(done) < 12, len(done)  # the stub costs $0.01 an episode
    # a resume starts over the cap, so it makes no further episode
    assert _run(cfg, "capped", log, "0").wait(timeout=300) == 3
    assert len([r for r in AE._rows(ledger) if r.get("terminal")]) == len(done)
