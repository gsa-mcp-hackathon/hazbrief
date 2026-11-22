# ruff: noqa: E501  (HB-214: docstrings and messages kept whole)
"""HB-214 Part A: the benchmark results as one table with short notes (the operator, 2026-11-20 19:19 EST;
ADDENDUM-01, 21:49 EST).

One row per test: the 15 Trial 7 lines HB-212 scored (each model against the measurements, then each hazbrief run
against each tool) and one row for each published benchmark row not yet evaluated. Measurement rows first, tool rows
second. Columns, in order: Test, Run, Compared with, Arcs (n), Ratio, 95 percent limits, Within a factor of two
(k of n), Statistically different?, Note. No cell holds a sentence. Definitions come before the table, numbered notes
after it.

The numbers are read from HB-209's `docs/evidence/hb209/trial7_intervals.tsv`; the result cell is derived from
`scripts/benchmark_state.py`'s state of the same line (ADDENDUM-02 item 1), never retyped; the rows not yet evaluated
are the graph's projection's (`docs/evidence/hb192/benchmark_rows.md`). The words are in `scripts/benchmark_table.yaml`.
The table renders through `hazbrief.brief.benchmark_table`, which the TEVV page uses too.

    uv run python scripts/benchmark_table.py            # write the HB-214 evidence.{json,tsv,md,html}
    uv run python scripts/benchmark_table.py --check    # write nothing; exit 1 if any differs
"""

from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import benchmark_state  # noqa: E402  (HB-212: the one function that gives a benchmark line's state)

from hazbrief.brief import benchmark_table as BT  # noqa: E402

WORDS = yaml.safe_load(
    (Path(__file__).with_name("benchmark_table.yaml")).read_text(encoding="utf-8")
)
INTERVALS = benchmark_state.INTERVALS
PROJECTION = REPO / "docs" / "evidence" / "hb192" / "benchmark_rows.md"
OUT = REPO / "docs" / "evidence" / "hb214"
#: the order hazbrief's runs come first in, then the tools' published runs
RUN_ORDER = (
    "P_scichem",
    "P_slab_rh20",
    "P_slab_rh80",
    "HPAC_complex",
    "HPAC_simple",
    "ALOHA",
)
HAZBRIEF = ("P_scichem", "P_slab_rh20", "P_slab_rh80")


class TableError(Exception):
    pass


def _result(state: str) -> str:
    """The "Statistically different?" cell for one of benchmark_state's states (ADDENDUM-01 item 1)."""
    by_state = {v: k for k, v in benchmark_state.WORDS["words"].items()}
    if state not in by_state:
        raise TableError(f"not one of benchmark_state's states: {state!r}")
    return WORDS["result"][by_state[state]]


def _not_evaluated() -> list[str]:
    """The published rows (not BENCH-0) whose projected result is "not yet evaluated", in the projection's order."""
    out = []
    for ln in PROJECTION.read_text(encoding="utf-8").splitlines():
        if not ln.startswith("| BENCH-"):
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split(" | ")]
        if (
            cells[0] != "BENCH-0"
            and cells[3] == benchmark_state.WORDS["words"]["not_run"]
        ):
            out.append(cells[0])
    return out


def _test(rid: str) -> str:
    return f"{rid} {WORDS['tests'][rid]}"


def rows() -> list[dict]:
    with INTERVALS.open(encoding="utf-8") as fh:
        lines = list(csv.DictReader(fh, delimiter="\t"))
    states = benchmark_state.by_key(INTERVALS)
    run = WORDS["runs"]
    model = {r["model"]: r for r in lines if r["section"] == "model"}
    diffs = [r for r in lines if r["section"] == "difference"]
    if set(model) != set(RUN_ORDER):
        raise TableError(
            f"{INTERVALS.name} holds runs {sorted(model)}, not {sorted(RUN_ORDER)}"
        )
    out = []
    for m in RUN_ORDER:
        r = model[m]
        test = WORDS["trial7_both"] if m in HAZBRIEF else _test(WORDS["trial7_row"][m])
        out.append(
            {
                "group": "measurements",
                "test": test,
                "run": run[m],
                "against": WORDS["measurements"],
                "arcs": r["n_arcs"],
                "ratio": r["MG"],
                "limits": f"{r['MG_low_95']} to {r['MG_high_95']}",
                "fac2": r["within_factor_2"],
                "result": _result(states[(m, "measurements")]["state"]),
                "note": WORDS["row_notes"]["measurements"],
            }
        )
    for rid in _not_evaluated():
        out.append(
            {
                "group": "measurements",
                "test": _test(rid),
                "run": "",
                "against": WORDS["measurements"],
                "arcs": "",
                "ratio": "",
                "limits": "",
                "fac2": "",
                "result": WORDS["result"]["not_run"],
                "note": "",
            }
        )
    for d in sorted(
        diffs,
        key=lambda d: (RUN_ORDER.index(d["model"]), RUN_ORDER.index(d["against"])),
    ):
        out.append(
            {
                "group": "tools",
                "test": _test(WORDS["trial7_row"][d["against"]]),
                "run": run[d["model"]],
                "against": run[d["against"]],
                "arcs": d["n_arcs"],
                "ratio": d["ratio_of_MG"],
                "limits": f"{d['ratio_low_95']} to {d['ratio_high_95']}",
                "fac2": "",
                "result": _result(states[(d["model"], d["against"])]["state"]),
                "note": WORDS["row_notes"]["tool"],
            }
        )
    return out


def notes() -> list[str]:
    minimum = benchmark_state.minimum(benchmark_state.trial7(INTERVALS))
    return [n.format(minimum=minimum) for n in WORDS["notes"]]


def table() -> dict:
    t = {
        "caption": WORDS["caption"],
        "definitions_heading": WORDS["definitions_heading"],
        "notes_heading": WORDS["notes_heading"],
        "definitions": WORDS["definitions"],
        "columns": WORDS["columns"],
        "names": WORDS["names"],
        "rows": rows(),
        "notes": notes(),
        "detail": WORDS["detail"],
        "source": [
            str(INTERVALS.relative_to(REPO)),
            str(benchmark_state.STATES_OUT.relative_to(REPO)),
            str(PROJECTION.relative_to(REPO)),
        ],
    }
    check(t)
    return t


def words(s: str) -> int:
    return len(s.split())


def check(t: dict) -> None:
    """Task items 1 to 4: the columns in order; no cell over the cap; a test name at most six words; every note at
    most 25 words."""
    want = [
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
    got = [c["name"] for c in t["columns"]]
    if got != want:
        raise TableError(f"columns {got}, not {want}")
    for r in t["rows"]:
        for c in t["columns"]:
            if words(r[c["key"]]) > WORDS["max_cell_words"]:
                raise TableError(
                    f"{r['test']}: cell {c['name']!r} is over {WORDS['max_cell_words']} words: {r[c['key']]!r}"
                )
    for rid, name in WORDS["tests"].items():
        if words(name) > WORDS["max_name_words"]:
            raise TableError(
                f"{rid}: name over {WORDS['max_name_words']} words: {name!r}"
            )
    for i, n in enumerate(t["notes"], 1):
        if words(n) > WORDS["max_note_words"]:
            raise TableError(
                f"note {i} is over {WORDS['max_note_words']} words ({words(n)}): {n!r}"
            )


def tsv(t: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter="\t", lineterminator="\n")
    w.writerow([c["name"] for c in t["columns"]])
    for r in t["rows"]:
        w.writerow([r[c["key"]] for c in t["columns"]])
    return buf.getvalue()


def page(t: dict) -> str:
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        f"<title>{BT.esc(t['caption'])}</title>"
        "<style>body { font-family: Calibri, Carlito, 'Segoe UI', Arial, sans-serif; color: #111;"
        f" background: #fff; margin: 24px; max-width: 1100px; }}{BT.CSS}</style></head><body>"
        f"<h1>{BT.esc(t['caption'])}</h1>"
        "<p>Generated by <code>scripts/benchmark_table.py</code> (HB-214); do not edit.</p>"
        f"{BT.html(t)}</body></html>\n"
    )


def outputs() -> dict[Path, str]:
    t = table()
    head = "<!-- generated by scripts/benchmark_table.py (HB-214); do not edit -->\n\n"
    return {
        OUT / "benchmark_table.json": json.dumps(t, indent=1, ensure_ascii=False)
        + "\n",
        OUT / "benchmark_table.tsv": tsv(t),
        OUT / "benchmark_table.md": head + BT.markdown(t) + "\n",
        OUT / "benchmark_table.html": page(t),
    }


def main(argv: list[str]) -> int:
    try:
        out = outputs()
    except TableError as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 2
    if "--check" in argv:
        stale = [
            p
            for p, text in out.items()
            if not p.exists() or p.read_text(encoding="utf-8") != text
        ]
        for p in stale:
            print(f"{p.relative_to(REPO)} differs from a fresh run", file=sys.stderr)
        return 1 if stale else 0
    OUT.mkdir(parents=True, exist_ok=True)
    for p, text in out.items():
        p.write_text(text, encoding="utf-8")
        print(f"wrote {p.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
