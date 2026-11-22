# ruff: noqa: E501  (HB-214: docstrings, prose and paths kept whole)
"""HB-214 Part A item 7 (ADDENDUM-01 item 5): the benchmark results as one table with short notes.

The table (`scripts/benchmark_table.py`, its record `docs/evidence/hb214/benchmark_table.json`) has one row per test
and the columns in the task's order, the result column headed "Statistically different?" with Yes, below / Yes, above
/ No / Not yet tested; no cell exceeds eight words; every number equals its source file (HB-209's intervals); every
note is at most 25 words; the definitions come before the table wherever it prints; the old paragraph notes are gone
from the graph's projection; the deck's benchmark slide is condensed (at most five rows, four columns).
"""

from __future__ import annotations

import csv
import html
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
RECORD = REPO / "docs" / "evidence" / "hb214" / "benchmark_table.json"
INTERVALS = REPO / "docs" / "evidence" / "hb209" / "trial7_intervals.tsv"
PROJECTION = REPO / "docs" / "evidence" / "hb192" / "benchmark_rows.md"
EVALUATION = REPO / "docs" / "submission" / "EVALUATION.md"
COLUMNS = [
    "Test",
    "Run",
    "Compared with",
    "Arcs (n)",
    "Ratio",
    "95 percent limits",
    "Within a factor of two (k of n)",
    "Statistically different?",
    "Note",
]
RESULTS = {"Yes, below", "Yes, above", "No", "Not yet tested"}


def _script(name: str):
    sys.path.insert(0, str(REPO / "scripts"))
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def table() -> dict:
    return json.loads(RECORD.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def intervals() -> list[dict]:
    with INTERVALS.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def _projection() -> dict[str, list[str]]:
    out = {}
    for ln in PROJECTION.read_text(encoding="utf-8").splitlines():
        if ln.startswith("| BENCH-"):
            c = [x.strip() for x in ln.strip().strip("|").split(" | ")]
            out[c[0]] = c
    return out


def test_the_record_equals_a_fresh_run():
    assert _script("benchmark_table").main(["--check"]) == 0


def test_the_columns_are_the_task_s_in_its_order_and_none_is_headed_status(table):
    assert [c["name"] for c in table["columns"]] == COLUMNS
    head = PROJECTION.read_text(encoding="utf-8")
    assert "| Status |" not in head and "| Status |" not in EVALUATION.read_text(
        encoding="utf-8"
    )


def test_one_row_per_test_measurements_first_then_tools(table, intervals):
    scored = [r for r in intervals if r["section"] in ("model", "difference")]
    not_run = [
        rid
        for rid, c in _projection().items()
        if rid != "BENCH-0" and c[3] == "not yet evaluated"
    ]
    rows = table["rows"]
    assert len(rows) == len(scored) + len(not_run) == 15 + 7
    groups = [r["group"] for r in rows]
    assert groups == sorted(groups, key=lambda g: g != "measurements"), (
        "measurement rows come first"
    )
    for rid in not_run:
        mine = [r for r in rows if r["test"].startswith(f"{rid} ")]
        assert len(mine) == 1 and mine[0]["result"] == "Not yet tested", rid
        assert not any(mine[0][k] for k in ("arcs", "ratio", "limits", "fac2")), (
            f"{rid}: numbers must be empty"
        )


def test_no_cell_holds_a_sentence_or_exceeds_eight_words(table):
    for r in table["rows"]:
        assert r["result"] in RESULTS, r
        for c in table["columns"]:
            cell = r[c["key"]]
            assert len(cell.split()) <= 8, (r["test"], c["name"], cell)
            assert ". " not in cell and not cell.endswith("."), (
                r["test"],
                c["name"],
                cell,
            )


def test_every_number_equals_its_source(table, intervals):
    words = yaml.safe_load(
        (REPO / "scripts" / "benchmark_table.yaml").read_text(encoding="utf-8")
    )
    name = words["runs"]
    want = {}
    for r in intervals:
        if r["section"] == "model":
            want[(name[r["model"]], words["measurements"])] = (
                r["n_arcs"],
                r["MG"],
                f"{r['MG_low_95']} to {r['MG_high_95']}",
                r["within_factor_2"],
            )
        else:
            want[(name[r["model"]], name[r["against"]])] = (
                r["n_arcs"],
                r["ratio_of_MG"],
                f"{r['ratio_low_95']} to {r['ratio_high_95']}",
                "",
            )
    got = {
        (r["run"], r["against"]): (r["arcs"], r["ratio"], r["limits"], r["fac2"])
        for r in table["rows"]
        if r["run"]
    }
    assert got == want


def test_the_result_is_benchmark_state_s_state(table, intervals):
    bs = _script("benchmark_state")
    words = yaml.safe_load(
        (REPO / "scripts" / "benchmark_table.yaml").read_text(encoding="utf-8")
    )
    by_state = {v: words["result"][k] for k, v in bs.WORDS["words"].items()}
    name = {v: k for k, v in words["runs"].items()}
    states = bs.by_key(INTERVALS)
    for r in table["rows"]:
        if not r["run"]:
            continue
        against = (
            "measurements"
            if r["against"] == words["measurements"]
            else name[r["against"]]
        )
        assert r["result"] == by_state[states[(name[r["run"]], against)]["state"]], r


def test_the_notes_are_numbered_and_short_and_the_definitions_hold_the_level(table):
    assert len(table["notes"]) == 5
    for n in table["notes"]:
        assert len(n.split()) <= 25, n
    defs = " ".join(c["text"] for c in table["columns"])
    assert "95 percent confidence level" in defs
    assert table["definitions"][0]["term"].startswith("Benchmark row (BENCH-n)")
    assert "BENCH-0" in table["definitions"][0]["text"]


def _tevv_pages() -> list[Path]:
    return [
        p
        for p in sorted((REPO / "docs" / "briefs").glob("*/tevv.html"))
        if "Benchmarks and requirement" in p.read_text(encoding="utf-8")
    ]


def test_the_same_table_prints_on_every_dense_tevv_page_and_in_evaluation(table):
    from hazbrief.brief import benchmark_table as BT

    pages = _tevv_pages()
    assert len(pages) == 13
    frag = BT.html(table)
    for p in pages:
        assert p.read_text(encoding="utf-8").count(frag) == 1, p.parent.name
    assert BT.markdown(table) in EVALUATION.read_text(encoding="utf-8")
    page = (REPO / "docs" / "evidence" / "hb214" / "benchmark_table.html").read_text(
        encoding="utf-8"
    )
    assert frag in page


def test_the_old_paragraph_notes_are_gone():
    """Task item 5: BENCH-0, -5, -8 and -9's notes are one line each, ending at the benchmark table."""
    proj = _projection()
    for rid in ("BENCH-0", "BENCH-5", "BENCH-8", "BENCH-9"):
        note = proj[rid][4]
        assert note.endswith("see the benchmark table."), rid
        # one line: HB-213's notes ran to 170 to 720 words; these keep the result words and the numbers only
        # (BENCH-5's are its 15 arrival ratios, BENCH-0's its minimum and the range of the nine ratios)
        assert len(note.split()) <= 80, (rid, len(note.split()))
    cut = " ".join(proj[rid][4] for rid in ("BENCH-0", "BENCH-5", "BENCH-8", "BENCH-9"))
    for old in (
        "Two models can agree with one another",
        "Why these tools, in the operator's words",
        "Until HB-212 the",
        "Shown by:",
    ):
        assert old not in cut, old


def test_the_deck_s_benchmark_slide_is_condensed():
    """ADDENDUM-01 item 4: at most five rows, four columns, and a line saying the full table is in the evidence."""
    deck = yaml.safe_load(
        (REPO / "docs" / "submission" / "deck.yaml").read_text(encoding="utf-8")
    )
    slide = next(s for s in deck["slides"] if s["id"] == "benchmarks")
    tables = [i["table"] for i in slide["items"] if "table" in i]
    assert len(tables) == 1
    t = tables[0]
    assert t["header"] == [
        "Compared",
        "Ratio",
        "95 percent limits",
        "Statistically different?",
    ]
    assert len(t["rows"]) <= 5
    # HB-219 restates where the line is: a body prints no file path, so the line naming
    # the full table's file is in the slide's notes
    assert any(
        "full table" in i.get("label", "") and "benchmark_table" in str(i.get("value"))
        for i in slide["notes"]
    )


def test_the_tevv_lines_outside_the_table_keep_their_status_words():
    """The lines outside the table keep HB-213's words; inside, only the table's (ADDENDUM-02 item 1)."""
    for p in _tevv_pages():
        text = p.read_text(encoding="utf-8")
        inner = text[text.find('<div class="benchmark-table">') :]
        inner = inner[: inner.find("</div>")]
        cells = [html.unescape(c) for c in re.findall(r"<td>(.*?)</td>", inner)]
        assert not any("statistically significant" in c for c in cells), p.parent.name
