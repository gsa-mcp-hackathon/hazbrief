# ruff: noqa: E501  (HB-212: docstrings and messages kept whole)
"""HB-212 Part A: one function gives a benchmark line's state (DN-030 section 2, items 1 to 5).

A ratio (MG, observed over predicted, against the measurements; or MG(hazbrief) over MG(tool), against a tool), its
95 percent limits and the number of arcs go in; one of four states comes out with its printed line:

- the limits exclude 1: "statistically significant at 95 percent", with the direction word (above or below), the
  ratio, the limits and the arcs;
- the limits include 1: "not statistically significant at 95 percent", with the same three numbers (the Census
  Bureau's words, ACS General Handbook 2020 block b952; HB-213 ADDENDUM-02);
- no run: "not yet evaluated".

The limits are not computed here: they are HB-209's (`docs/evidence/hb209/trial7_intervals.tsv`), from HB-176's
implementation of Hanna, Strimaitis and Chang (1993) equation 34 (`the HB-176 evidence` `limits`),
unchanged. The words are in `scripts/benchmark_state.yaml`. The same function serves both comparisons (item 2).

    uv run python scripts/benchmark_state.py            # write docs/evidence/hb212/states.tsv
    uv run python scripts/benchmark_state.py --check    # write nothing; exit 1 if it differs
"""

from __future__ import annotations

import csv
import io
import sys
from pathlib import Path
from typing import NamedTuple

import yaml

REPO = Path(__file__).resolve().parents[1]
WORDS = yaml.safe_load(
    (Path(__file__).with_name("benchmark_state.yaml")).read_text(encoding="utf-8")
)
INTERVALS = REPO / "docs" / "evidence" / "hb209" / "trial7_intervals.tsv"
STATES_OUT = REPO / "docs" / "evidence" / "hb212" / "states.tsv"
#: the four states a benchmark line can carry
STATES = tuple(WORDS["words"].values())


class State(NamedTuple):
    state: str
    line: str


def state(
    ratio: float | None,
    low: float | None,
    high: float | None,
    n: int | None,
    *,
    subject: str,
    reference: str,
    stat: str = "MG",
) -> State:
    """The state of `subject` against `reference` and its printed line. `ratio` is observed over predicted (or
    MG(subject) over MG(reference)), so above 1 means the subject's concentration is below the reference's. A run
    that is not held is `ratio=None`: "not yet evaluated"."""
    w = WORDS["words"]
    if ratio is None:
        return State(
            w["not_run"],
            WORDS["line"]["not_run"].format(subject=subject, reference=reference),
        )
    if low is None or high is None or not n:
        raise ValueError(
            f"{subject} against {reference}: a ratio needs its 95 percent limits and its number of arcs"
        )
    if not (0 < low <= ratio <= high):
        raise ValueError(
            f"{subject} against {reference}: ratio {ratio} is not inside its limits {low} to {high}"
        )
    nums = {
        "subject": subject,
        "reference": reference,
        "stat": stat,
        "ratio": f"{ratio:.2f}",
        "low": f"{low:.2f}",
        "high": f"{high:.2f}",
        "n": n,
    }
    if low > 1:
        return State(
            w["below"],
            WORDS["line"]["differs"].format(
                direction=WORDS["direction"]["below"], **nums
            ),
        )
    if high < 1:
        return State(
            w["above"],
            WORDS["line"]["differs"].format(
                direction=WORDS["direction"]["above"], **nums
            ),
        )
    return State(w["same"], WORDS["line"]["same"].format(**nums))


def _f(v: str) -> float | None:
    return None if v in ("", "none") else float(v)


def trial7(path: Path = INTERVALS) -> list[dict]:
    """Every line of HB-209's Trial 7 intervals with its state: each model against the measurements (its MG), then
    each hazbrief run against each tool (the ratio of MGs). Each carries the descriptive count, where the row has one
    (item 3), and the Trial 7 words (item 4)."""
    with path.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    label = WORDS["names"]
    out = []
    for r in rows:
        if r["section"] == "model":
            s = state(
                _f(r["MG"]),
                _f(r["MG_low_95"]),
                _f(r["MG_high_95"]),
                int(r["n_arcs"]),
                subject=label[r["model"]],
                reference="the measurements",
            )
            against, count = (
                "measurements",
                WORDS["count"].format(k=r["within_factor_2"]),
            )
        else:
            s = state(
                _f(r["ratio_of_MG"]),
                _f(r["ratio_low_95"]),
                _f(r["ratio_high_95"]),
                int(r["n_arcs"]),
                subject=label[r["model"]],
                reference=label[r["against"]],
                stat="MG ratio",
            )
            # the held tool's own column says whether its limits exclude 1; the state must agree with it
            excl = r["limits_exclude_1"] == "yes"
            if excl != (s.state in (WORDS["words"]["above"], WORDS["words"]["below"])):
                raise ValueError(
                    f"{r['model']} against {r['against']}: state {s.state} disagrees with limits_exclude_1"
                )
            against, count = r["against"], ""
        out.append(
            {
                "section": r["section"],
                "model": r["model"],
                "against": against,
                "state": s.state,
                "count": count,
                "line": s.line,
                "trial": WORDS["trial7"],
            }
        )
    return out


def by_key(path: Path = INTERVALS) -> dict[tuple[str, str], dict]:
    """trial7() keyed by (model, against)."""
    return {(r["model"], r["against"]): r for r in trial7(path)}


def minimum(lines: list[dict]) -> str:
    """BENCH-0's minimum (equivalence with each accepted tool): where no hazbrief run's difference from any tool's
    is statistically significant, it reads that state with its level and "one trial, five arcs"; no equivalence test
    is run, so it never reads met."""
    diffs = [r for r in lines if r["section"] == "difference"]
    if not diffs:
        return WORDS["words"]["not_run"]
    if all(r["state"] == WORDS["words"]["same"] for r in diffs):
        return WORDS["minimum_same"]
    raise ValueError(
        "a hazbrief run differs from a tool's at 95 percent: the minimum's wording is not decided for that case "
        "(HB-212 ADDENDUM-01 item 3 covers only 'not statistically significant'); stop and report"
    )


def table(path: Path = INTERVALS) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter="\t", lineterminator="\n")
    cols = ["section", "model", "against", "state", "count", "line", "trial"]
    w.writerow(cols)
    lines = trial7(path)
    for r in lines:
        w.writerow([r[c] for c in cols])
    w.writerow(
        [
            "minimum",
            "BENCH-0",
            "HPAC and ALOHA",
            minimum(lines),
            "",
            "",
            WORDS["trial7"],
        ]
    )
    return buf.getvalue()


def main(argv: list[str]) -> int:
    text = table()
    if "--check" in argv:
        if not STATES_OUT.exists() or STATES_OUT.read_text(encoding="utf-8") != text:
            print(
                f"{STATES_OUT.relative_to(REPO)} differs from a fresh run",
                file=sys.stderr,
            )
            return 1
        print(f"{STATES_OUT.relative_to(REPO)} equals a fresh run")
        return 0
    STATES_OUT.write_text(text, encoding="utf-8")
    print(f"wrote {STATES_OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
