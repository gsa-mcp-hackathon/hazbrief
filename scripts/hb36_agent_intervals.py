#!/usr/bin/env python3
"""HB-36 step 4: each agent measure beside HB-16b's, with its interval. No model call.

    uv run python scripts/hb36_agent_intervals.py \\
        --base eval/agent_runs/2026-10-23/scores.jsonl \\
        --new eval/agent_runs/2026-10-25/scores.jsonl \\
        --out eval/agent_runs/2026-10-25/intervals_vs_hb16b.json

Each measure is `agent_eval.summarize`'s, recomputed from the scored episodes so its
count is known. A proportion over episodes (scenario pass, arguments match, the refusal
readings, the ambiguity rule) carries its Wilson 95 % interval; pooled grounding is a
proportion over every number and name the replies hold, with its Wilson interval. Tool
precision and recall are means of per-episode fractions, not proportions, so theirs is a
percentile bootstrap over episodes (`BOOTSTRAP_DRAWS`, seed `BOOTSTRAP_SEED`, fixed so
the file reproduces). `outside` marks a new rate outside the base run's interval, the
task's test for a move that is a finding.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

#: z for a two-sided 95 % interval.
Z95 = 1.959963984540054
#: Bootstrap resamples for the mean measures; enough for a stable 2.5/97.5 percentile.
BOOTSTRAP_DRAWS = 4000
BOOTSTRAP_SEED = 20261025
ADJUDICATED_FAMILIES = ("ambiguity", "out_of_scope", "adversarial")


def wilson(k: int, n: int) -> list[float] | None:
    if not n:
        return None
    p = k / n
    d = 1 + Z95 * Z95 / n
    c = (p + Z95 * Z95 / (2 * n)) / d
    h = Z95 * math.sqrt(p * (1 - p) / n + Z95 * Z95 / (4 * n * n)) / d
    return [round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]


def prop(flags: list[bool]) -> dict:
    k, n = sum(flags), len(flags)
    return {
        "k": k,
        "n": n,
        "rate": round(k / n, 4) if n else None,
        "interval": wilson(k, n),
        "method": "wilson",
    }


def mean_boot(values: list[float]) -> dict:
    n = len(values)
    if not n:
        return {"n": 0, "rate": None, "interval": None, "method": "bootstrap"}
    rng = random.Random(BOOTSTRAP_SEED)
    means = sorted(
        sum(rng.choice(values) for _ in range(n)) / n for _ in range(BOOTSTRAP_DRAWS)
    )
    lo = means[int(0.025 * BOOTSTRAP_DRAWS)]
    hi = means[int(0.975 * BOOTSTRAP_DRAWS) - 1]
    return {
        "n": n,
        "rate": round(sum(values) / n, 4),
        "interval": [round(lo, 4), round(hi, 4)],
        "method": "bootstrap",
    }


def measures(rows: list[dict]) -> dict:
    out = {}
    for m in sorted({r["model"] for r in rows}):
        rs = [r for r in rows if r["model"] == m]
        fam = lambda f: [r for r in rs if r["family"] == f]  # noqa: E731
        adj = [r for r in rs if r["family"] in ADJUDICATED_FAMILIES]
        nums = sum(r["grounding"]["numbers"] + r["grounding"]["names"] for r in rs)
        bad = sum(
            len(r["grounding"]["ungrounded_numbers"])
            + len(r["grounding"]["ungrounded_names"])
            for r in rs
        )
        g = prop([True] * (nums - bad) + [False] * bad)
        out[m] = {
            "tool_precision": mean_boot(
                [r["precision"] for r in rs if r["precision"] is not None]
            ),
            "tool_recall": mean_boot(
                [r["recall"] for r in fam("scenario") if r["recall"] is not None]
            ),
            "args_match": prop([all(r["args"].values()) for r in rs if r["args"]]),
            "grounding_rate_pooled": g,
            "scenario_pass": prop([bool(r["pass"]) for r in fam("scenario")]),
            "refusal_correct": prop([bool(r["pass"]) for r in adj]),
            "refusal_correct_lenient": prop([bool(r.get("pass_lenient")) for r in adj]),
            "out_of_scope_refusal": prop(
                [bool(r["pass"]) for r in fam("out_of_scope")]
            ),
            "out_of_scope_refusal_lenient": prop(
                [bool(r.get("pass_lenient")) for r in fam("out_of_scope")]
            ),
            "ambiguity": prop([bool(r["pass"]) for r in fam("ambiguity")]),
        }
    return out


def rows_of(p: Path) -> list[dict]:
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", type=Path, required=True)
    ap.add_argument("--new", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    base, new = measures(rows_of(a.base)), measures(rows_of(a.new))
    table, moved = {}, []
    for m in new:
        table[m] = {}
        for k, nv in new[m].items():
            bv = base[m][k]
            lo, hi = bv["interval"] or (None, None)
            outside = (
                nv["rate"] is not None and lo is not None and not lo <= nv["rate"] <= hi
            )
            table[m][k] = {"base": bv, "new": nv, "outside": outside}
            if outside:
                moved.append(f"{m} {k}: {bv['rate']} -> {nv['rate']} (base {lo}-{hi})")
    body = {
        "base": str(a.base),
        "new": str(a.new),
        "measures": table,
        "outside_the_base_interval": moved,
        "bootstrap": {"draws": BOOTSTRAP_DRAWS, "seed": BOOTSTRAP_SEED},
    }
    a.out.write_text(json.dumps(body, indent=1) + "\n", encoding="utf-8")
    print("\n".join(moved) or "no measure moved outside the base run's interval")
    return 0


if __name__ == "__main__":
    sys.exit(main())
