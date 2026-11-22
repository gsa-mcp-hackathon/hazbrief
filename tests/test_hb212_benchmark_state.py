# ruff: noqa: E501  (HB-212: quoted lines are one line each)
"""HB-212 Part A: one function gives a benchmark line's state (`scripts/benchmark_state.py`; DN-030 section 2).

- the direction of "below" is held against one hand-worked row: hazbrief's SCICHEM run on Jack Rabbit II Trial 7,
  whose arc maxima are each read from `docs/evidence/hb209/trial7_arcs.tsv` and worked here by hand;
- limits that include 1 give "not statistically significant at 95 percent" (HB-213 ADDENDUM-02: the Census
  Bureau's words, ACS General Handbook 2020 block b952), with the confidence level on the line;
- no run gives "not yet evaluated";
- the held file gives what the task file expects: SCICHEM below the measurements, 2.88 (1.58 to 5.27) on 5 arcs, and
  every other line not statistically significant; the minimum carries the same words, the level and "one trial,
  five arcs";
- `docs/evidence/hb212/states.tsv` equals a fresh run.
"""

from __future__ import annotations

import csv
import importlib.util
import math
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "benchmark_state", REPO / "scripts" / "benchmark_state.py"
)
BS = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(BS)


def test_the_direction_of_below_against_a_hand_worked_row():
    """SCICHEM's arc maxima on the five statistic arcs, each over the measured one (trial7_arcs.tsv): 23,260 of
    72,580; 6,466 of 22,686; 1,924 of 2,621; 531.7 of 1,417; 74.3 of 373. Every share but one is under a half, so
    the run predicts less than was measured. MG, observed over predicted, is then above 1, and the state is below."""
    with (REPO / "docs/evidence/hb209/trial7_arcs.tsv").open(encoding="utf-8") as fh:
        rows = [
            r
            for r in csv.DictReader(fh, delimiter="\t")
            if r["model"] == "P_scichem" and float(r["arc_km"]) <= 5
        ]
    pairs = [(float(r["observed_ppm"]), float(r["predicted_ppm"])) for r in rows]
    assert pairs == [
        (72580, 23260),
        (22686, 6466),
        (2621, 1924),
        (1417, 531.7),
        (373, 74.3),
    ]
    mg = math.exp(sum(math.log(o / p) for o, p in pairs) / len(pairs))
    assert round(mg, 2) == 2.88
    got = BS.state(mg, 1.58, 5.27, 5, subject="SCICHEM", reference="the measurements")
    assert got.state == "statistically significant at 95 percent, below"
    assert got.line == (
        "SCICHEM is below the measurements, a difference that is statistically significant at the 95 percent "
        "confidence level (MG 2.88, 95 percent limits 1.58 to 5.27, which exclude 1, on 5 arcs)"
    )
    # the mirror: a run predicting three times what was measured is above it
    assert (
        BS.state(1 / mg, 1 / 5.27, 1 / 1.58, 5, subject="x", reference="y").state
        == "statistically significant at 95 percent, above"
    )


def test_limits_that_include_1_are_not_statistically_significant_at_the_level():
    got = BS.state(
        1.66, 0.87, 3.16, 5, subject="SCICHEM", reference="HPAC", stat="MG ratio"
    )
    assert got.state == "not statistically significant at 95 percent"
    assert (
        "1.66, 95 percent limits 0.87 to 3.16, which include 1, on 5 arcs" in got.line
    )
    assert (
        "is not statistically significant at the 95 percent confidence level"
        in got.line
    )
    assert "equivalence" not in got.line and "shown to differ" not in got.line
    assert "equivalent" not in got.line


def test_no_run_is_not_yet_evaluated():
    got = BS.state(None, None, None, None, subject="SCICHEM", reference="BENCH-1")
    assert got.state == "not yet evaluated"


def test_a_ratio_outside_its_limits_or_without_them_fails_loud():
    with pytest.raises(ValueError, match="not inside its limits"):
        BS.state(0.5, 0.87, 3.16, 5, subject="a", reference="b")
    with pytest.raises(ValueError, match="needs its 95 percent limits"):
        BS.state(1.2, None, 3.0, 5, subject="a", reference="b")


def test_the_held_file_gives_the_expected_states():
    lines = BS.trial7()
    below = [
        r for r in lines if r["state"] != "not statistically significant at 95 percent"
    ]
    assert [(r["model"], r["against"], r["state"]) for r in below] == [
        ("P_scichem", "measurements", "statistically significant at 95 percent, below")
    ]
    assert (
        "MG 2.88, 95 percent limits 1.58 to 5.27, which exclude 1, on 5 arcs"
        in below[0]["line"]
    )
    assert len(lines) == 15
    assert all(
        r["trial"]
        == "one trial, five arcs, and the five arcs are of one release, not five independent releases"
        for r in lines
    )
    # item 3: the descriptive count stands beside each model's line, with no status word in it
    for r in lines:
        if r["section"] == "model":
            assert r["count"].endswith(
                " arcs within a factor of two of the measured maximum"
            )
            assert not any(w in r["count"] for w in ("above", "below", "significant"))
    assert BS.minimum(lines) == (
        "not statistically significant at 95 percent against HPAC or ALOHA (one trial, five arcs)"
    )


def test_the_states_record_equals_a_fresh_run():
    assert (REPO / "docs/evidence/hb212/states.tsv").read_text(
        encoding="utf-8"
    ) == BS.table()


def test_every_line_prints_the_confidence_level():
    """HB-212 ADDENDUM-01 item 2: the level is on every line, the minimum's included."""
    lines = BS.trial7()
    for r in lines:
        assert (
            "95 percent" in r["state"] and "95 percent confidence level" in r["line"]
        ), r
    assert "95 percent" in BS.minimum(lines)
