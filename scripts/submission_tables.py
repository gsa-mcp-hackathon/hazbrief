# ruff: noqa: E501  (HB-196: rendered prose and paths are one line each)
"""HB-196 Part B items 6a, 6b, 6c (ADDENDA 01 and 02) and 8: the evaluation document's generated tables.

Each table is rendered from a committed file into `docs/submission/EVALUATION.md` between its markers
(`<!-- hb196:NAME -->` and `<!-- /hb196:NAME -->`), and the measured ones are first written as evidence files under
`docs/evidence/hb196/` that the table cites, so `test_evaluation_document.py` finds every number in a file its
row cites:

- `template-harness`: the template's evaluation harness beside hazbrief's, from `docs/submission/template_harness.yaml`.
- `question-bar`: the level D prompt set (`eval/agent_prompts.yaml`) against the template skill's five-point question
  bar, one rule per point (below), counted per prompt into `docs/evidence/hb196/question_bar.tsv`. No prompt changes.
- `out-of-scope`: the out-of-scope family's outcomes per model, counted from the committed per-episode scores
  (`eval/agent_runs/2026-10-25/scores.jsonl`) into `docs/evidence/hb196/out_of_scope.tsv`.
- `data-sources`: every MCP server and public source the brief reads, one row per channel the configuration names
  (`src/hazbrief/brief/orchestrator.yaml` `channels` and `data_sources.server_tools`) and per derivation, each with its
  state as the reference brief's Data sources view shows it (`docs/briefs/csx-point-of-rocks-day/brief.html`, the
  operator's reference scenario, DN-019 section 1), into `docs/evidence/hb196/data_sources.tsv`.
- `benchmarks` (ADDENDUM-03 item 4): each published benchmark row of the graph's projection
  (`docs/evidence/hb192/benchmark_rows.md`), its mean bias read from its MG, and hazbrief's status against it.
- `trial7` (HB-209 item 6): Jack Rabbit II Trial 7 as numbers, each run's share of the measured arc maximum, its arcs
  within a factor of two and MG with its 95 percent limits, then each hazbrief run against each tool run, from
  `docs/evidence/hb209/trial7_arcs.tsv` and `trial7_intervals.tsv`.
- `gate-ledger` (HB-198 ADDENDUM-01 3b; HB-203 item 5): the gate ledger's two sentences, quoted from
  `docs/evidence/hb198/gate_ledger_summary.txt`, which `gate_ledger.py` writes.

    uv run python scripts/submission_tables.py            # write the evidence files and the document's tables
    uv run python scripts/submission_tables.py --check    # write nothing; exit 1 when any differs

No network, no model. The script fails, writing nothing, when a configured channel has no row in the view, or when a
marker pair is missing from the document.
"""

from __future__ import annotations

import csv
import html
import io
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import benchmark_state  # noqa: E402  (HB-212: the one function that gives a benchmark line's state)

DOC = ROOT / "docs" / "submission" / "EVALUATION.md"
EVIDENCE = ROOT / "docs" / "evidence" / "hb196"
HARNESS = ROOT / "docs" / "submission" / "template_harness.yaml"
PROMPTS = ROOT / "eval" / "agent_prompts.yaml"
SCORES = ROOT / "eval" / "agent_runs" / "2026-10-25" / "scores.jsonl"
ORCHESTRATOR = ROOT / "src" / "hazbrief" / "brief" / "orchestrator.yaml"
#: the operator's reference scenario (DN-019 section 1; HB-133 ADDENDUM-01 section 4)
REFERENCE_BRIEF = ROOT / "docs" / "briefs" / "csx-point-of-rocks-day" / "brief.html"
#: the demo model, the one the evaluation's headline numbers are about (eval/harness.yaml `agent.demo_model`)
DEMO_MODEL = "claude-opus-5-5"


class TablesError(Exception):
    """A configured channel or a marker the tables cannot be rendered without."""


def rel(p: Path) -> str:
    return str(p.relative_to(ROOT))


def tsv(rows: list[dict], cols: list[str]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(
        buf, fieldnames=cols, delimiter="\t", lineterminator="\n", extrasaction="ignore"
    )
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


def md_table(header: list[str], rows: list[list[str]]) -> str:
    def cell(s: str) -> str:
        return str(s).replace("|", "/").replace("\n", " ")

    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(cell(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


# ── 6a: the template's harness beside hazbrief's ─────────────────────────────────────────────────────────────────


def template_harness() -> str:
    cfg = yaml.safe_load(HARNESS.read_text(encoding="utf-8"))
    rows = [[r["part"], r["hazbrief"], f"`{r['source']}`"] for r in cfg["rows"]]
    return md_table(
        [
            "The template's harness (participant aid, mcp-eval-wxai)",
            "hazbrief",
            "Source",
        ],
        rows,
    )


# ── 6b: the question bar ─────────────────────────────────────────────────────────────────────────────────────────

#: The skill's five points, each with the rule this script applies to a prompt of `eval/agent_prompts.yaml`:
BAR = [
    (
        "independent",
        "every prompt is one message in a fresh episode, and its text names no other prompt or earlier answer",
    ),
    (
        "read-only",
        "answering it needs no write: every tool the prompt may call is one of the server's seven read-only tools",
    ),
    (
        "one verifiable answer",
        "the prompt carries a fixed expected value the scorer checks (`expected_args`, `must_contain` or "
        "`governing_distance_any`), not only key terms of a refusal",
    ),
    (
        "stable over time",
        "the prompt states the incident's date, and the episode replays recorded exchanges, so its answer does not "
        "move with a live source",
    ),
    (
        "needs more than one tool call",
        "two or more tools are expected (`expected_tools`, or a tool the server says runs others, `covers`)",
    ),
]
_EARLIER = re.compile(r"\b(previous|earlier|above|as before|last answer)\b", re.I)
_DATE = re.compile(
    r"\b\d{1,2}\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b"
)


def question_bar() -> tuple[str, str, str]:
    cfg = yaml.safe_load(PROMPTS.read_text(encoding="utf-8"))
    tools = set(
        yaml.safe_load(ORCHESTRATOR.read_text(encoding="utf-8"))["data_sources"][
            "server_tools"
        ]
    )
    covers = cfg.get("covers") or {}
    # the level D set is the prompts the run scored: the file has since gained scenario prompts for
    # later fixtures (HB-120, HB-129, HB-175) that no agent run has asked
    scored = {
        json.loads(x)["prompt"]
        for x in SCORES.read_text(encoding="utf-8").splitlines()
        if x.strip()
    }
    rows = []
    for p in cfg["prompts"]:
        if p["id"] not in scored:
            continue
        expected = list(p.get("expected_tools") or [])
        allowed = set(expected) | set(p.get("allowed_tools") or [])
        reach = set(expected)
        for t in expected:
            reach |= set(covers.get(t, []))
        rows.append(
            {
                "prompt": p["id"],
                "family": p["family"],
                "independent": "yes" if not _EARLIER.search(p["text"]) else "no",
                "read-only": "yes" if allowed <= tools else "no",
                "one verifiable answer": "yes"
                if any(
                    p.get(k)
                    for k in ("expected_args", "must_contain", "governing_distance_any")
                )
                else "no",
                "stable over time": "yes" if _DATE.search(p["text"]) else "no",
                "needs more than one tool call": "yes" if len(reach) >= 2 else "no",
            }
        )
    cols = ["prompt", "family"] + [b for b, _ in BAR]
    families = sorted({r["family"] for r in rows})
    counts = []
    for point, _ in BAR:
        for f in [*families, "all"]:
            rs = [r for r in rows if f in ("all", r["family"])]
            counts.append(
                {
                    "point": point,
                    "family": f,
                    "meet": sum(r[point] == "yes" for r in rs),
                    "prompts": len(rs),
                }
            )
    table = []
    for point, rule in BAR:
        by_family = ", ".join(
            f"{f} {sum(r[point] == 'yes' for r in rows if r['family'] == f)} of "
            f"{sum(r['family'] == f for r in rows)}"
            for f in families
        )
        meet = sum(r[point] == "yes" for r in rows)
        table.append(
            [
                point,
                rule,
                f"{meet} of {len(rows)} ({by_family})",
                "`docs/evidence/hb196/question_bar_counts.tsv`; `docs/evidence/hb196/question_bar.tsv`",
            ]
        )
    md = md_table(
        ["Point of the bar", "Rule applied", "Prompts that meet it", "Source"], table
    )
    return tsv(counts, ["point", "family", "meet", "prompts"]), tsv(rows, cols), md


# ── 6c: the out-of-scope family's outcomes ───────────────────────────────────────────────────────────────────────


def out_of_scope() -> tuple[str, str, dict]:
    prompts = {
        p["id"]: p
        for p in yaml.safe_load(PROMPTS.read_text(encoding="utf-8"))["prompts"]
        if p["family"] == "out_of_scope"
    }
    scores = [
        json.loads(x)
        for x in SCORES.read_text(encoding="utf-8").splitlines()
        if x.strip()
    ]
    eps = [s for s in scores if s.get("family") == "out_of_scope"]
    cols = [
        "model",
        "episodes",
        "strict_refusal",
        "lenient_only",
        "neither",
        "called_a_tool",
        "drew_a_footprint",
        "a_number_no_tool_output_holds",
        "key_terms_missing",
        "forbidden_pattern_matched",
        "asked_for_clarification",
    ]
    rows = []
    for m in sorted({s["model"] for s in eps}):
        rs = [s for s in eps if s["model"] == m]
        rows.append(
            {
                "model": m,
                "episodes": len(rs),
                "strict_refusal": sum(bool(s["pass"]) for s in rs),
                "lenient_only": sum(
                    bool(s["pass_lenient"]) and not s["pass"] for s in rs
                ),
                "neither": sum(not s["pass_lenient"] for s in rs),
                "called_a_tool": sum(bool(s["tools_called"]) for s in rs),
                "drew_a_footprint": sum(bool(s["drew_footprint"]) for s in rs),
                "a_number_no_tool_output_holds": sum(
                    bool(s["grounding"]["ungrounded_numbers"]) for s in rs
                ),
                "key_terms_missing": sum(not all(s["key_terms"]) for s in rs),
                "forbidden_pattern_matched": sum(
                    bool(s["forbidden_matched"]) for s in rs
                ),
                "asked_for_clarification": "not recorded",
            }
        )
    src = "`docs/evidence/hb196/out_of_scope.tsv`"
    table = [
        [
            f"`{r['model']}`" + (" (demo)" if r["model"] == DEMO_MODEL else ""),
            str(r["episodes"]),
            str(r["strict_refusal"]),
            str(r["lenient_only"]),
            str(r["neither"]),
            str(r["called_a_tool"]),
            str(r["drew_a_footprint"]),
            str(r["a_number_no_tool_output_holds"]),
            r["asked_for_clarification"],
            src,
        ]
        for r in rows
    ]
    md = md_table(
        [
            "Model",
            "Episodes",
            "Strict refusal",
            "Declined with a number no tool holds",
            "Neither",
            "Called a tool",
            "Drew a footprint",
            "A number no tool output holds",
            "Asked for clarification",
            "Source",
        ],
        table,
    )
    kinds = {pid: " ".join(p["text"].split()) for pid, p in prompts.items()}
    return tsv(rows, cols), md, kinds


# ── 8: every public source and MCP server the brief reads ────────────────────────────────────────────────────────

_ROW = re.compile(r'<tr data-tool="([^"]+)" data-outcome="([^"]+)">(.*?)</tr>', re.S)
_SERVER = re.compile(r'<tr data-server="([^"]+)">(.*?)</tr>', re.S)
_STATE = re.compile(
    r'<span class="st [^"]*" data-state="[^"]*">(.*?)</span></td>', re.S
)
_LI = re.compile(r"<li>(.*?)</li>", re.S)
_PL = re.compile(r'<p class="pl">(.*?)</p>', re.S)
_TAGS = re.compile(r"<[^>]+>")


_MARK = re.compile(r'<span class="mk"[^>]*>.*?</span>', re.S)


def _text(s: str) -> str:
    """A cell's words: tags and the state's coloured mark glyph dropped."""
    return " ".join(html.unescape(_TAGS.sub(" ", _MARK.sub(" ", s))).split())


def data_sources() -> tuple[str, str]:
    page = REFERENCE_BRIEF.read_text(encoding="utf-8")
    orch = yaml.safe_load(ORCHESTRATOR.read_text(encoding="utf-8"))
    rows = []
    for server, body in _SERVER.findall(page):
        st = _STATE.search(body)
        tools = re.findall(r'data-tool="([^"]+)" data-calls="(\d+)"', body)
        rows.append(
            {
                "kind": "MCP server",
                "name": server,
                "source": "; ".join(
                    f"{t} ({n} call{'s' if n != '1' else ''})" for t, n in tools
                ),
                "state": _text(st.group(1)) if st else "",
                "outcome": "",
                "as_of": "",
            }
        )
        missing = set(orch["data_sources"]["server_tools"]) - {t for t, _ in tools}
        if missing:
            raise TablesError(
                f"the view's server row lacks configured tools {sorted(missing)}"
            )
    seen = set()
    for tool, outcome, body in _ROW.findall(page):
        st = _STATE.search(body)
        pls = _PL.findall(body)
        kind = (
            "derivation"
            if "derivation" in (_text(pls[0]) if pls else "")
            else "channel"
        )
        seen.add(tool)
        lis = _LI.findall(body.split("</ul>")[0]) if "<ul>" in body else []
        for li in lis or [""]:
            name, _, asof = _text(li).partition(": ")
            rows.append(
                {
                    "kind": kind,
                    "name": tool,
                    "source": name,
                    "state": _text(st.group(1)) if st else "",
                    "outcome": outcome,
                    "as_of": asof,
                }
            )
    missing = [c for c in orch["channels"] if c not in seen]
    if missing:
        raise TablesError(
            f"configured channels with no row in the Data sources view: {missing}"
        )
    cols = ["kind", "name", "source", "state", "outcome", "as_of"]
    src = f"`{rel(REFERENCE_BRIEF)}`"
    table = [
        [
            r["kind"],
            r["name"].replace("_", " "),
            r["source"],
            r["state"],
            r["outcome"],
            r["as_of"],
            src,
        ]
        for r in rows
    ]
    md = md_table(
        [
            "Kind",
            "Server, tool or derivation",
            "Public source",
            "State in the view",
            "Outcome",
            "As of",
            "Source",
        ],
        table,
    )
    return tsv(rows, cols), md


# ── ADDENDUM-03 item 4: the benchmark requirement, from the graph's projection ───────────────────────────────────

BENCHMARKS = ROOT / "docs" / "evidence" / "hb192" / "benchmark_rows.md"
_MG = re.compile(r"\bMG (\d+(?:\.\d+)?)(?: to (\d+(?:\.\d+)?))?")


def mean_bias(statement: str) -> str:
    """The direction of the row's mean bias, read from its MG (observed over predicted, both papers' definition:
    above 1 is under-prediction, below 1 over-prediction); a row with no MG says so."""
    m = _MG.search(statement)
    if not m:
        return "no MG in this row"
    lo = float(m.group(1))
    hi = float(m.group(2) or m.group(1))
    span = m.group(1) + (f" to {m.group(2)}" if m.group(2) else "")
    if lo > 1:
        return f"MG {span}: under-predicts"
    if hi < 1:
        return f"MG {span}: over-predicts"
    return f"MG {span}: both sides of 1"


def status_with_reason(status: str, note: str) -> str:
    """HB-203 item 3: a scored status carries, in the same cell, the reason the row's note gives right after
    "Status: <word>." (the note's next sentence). Since HB-212 the scored states are scripts/benchmark_state.py's
    (statistically significant with its direction, or not statistically significant, at 95 percent; HB-213
    ADDENDUM-02); the status word is the projection's, unchanged; "not yet
    evaluated" needs no reason."""
    if status == "not yet evaluated":
        return status
    m = re.search(rf"Status: {re.escape(status)}\.\s+(.+?\.)(?:\s|$)", note)
    if not m:
        return status
    return f"{status}: {m.group(1)}"


def benchmarks() -> str:
    rows = []
    for ln in BENCHMARKS.read_text(encoding="utf-8").splitlines():
        if not ln.startswith("| BENCH-"):
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split(" | ")]
        rid, _state, statement, status, note = cells[:5]
        if rid == "BENCH-0":
            continue
        rows.append(
            [
                rid,
                statement,
                mean_bias(statement),
                status_with_reason(status, note),
                f"`{rel(BENCHMARKS)}`",
            ]
        )
    if not rows:
        raise TablesError(f"{rel(BENCHMARKS)} holds no published benchmark row")
    return md_table(
        [
            "Row",
            "Published benchmark, its case, arcs, weather and source",
            "Mean bias",
            "hazbrief's status",
            "Source",
        ],
        rows,
    )


def benchmark_table() -> str:
    """HB-214: the one benchmark table, its definitions first and its numbered notes after, from its record
    (docs/evidence/hb214/benchmark_table.json, written by scripts/benchmark_table.py), rendered by the same module the
    TEVV page uses, so it is the same in both."""
    from hazbrief.brief import benchmark_table as BT

    return BT.markdown(BT.load())


#: HB-209 item 6: Jack Rabbit II Trial 7 as numbers, written by the HB-209 evidence
TRIAL7_ARCS = ROOT / "docs" / "evidence" / "hb209" / "trial7_arcs.tsv"
TRIAL7_INTERVALS = ROOT / "docs" / "evidence" / "hb209" / "trial7_intervals.tsv"
STATES = ROOT / "docs" / "evidence" / "hb212" / "states.tsv"


def _read_tsv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def trial7() -> str:
    """HB-209 item 6: no status word without its size. Each run's share of the measured arc maximum at each statistic
    arc (0.2 to 5 km), its arcs within a factor of two out of five, its MG with the 95 percent limits of Hanna,
    Strimaitis and Chang (1993) equation 34; then each hazbrief run's MG over each tool run's, with its limits. Read
    from the two files the evidence tool writes; nothing is recomputed here."""
    arcs = _read_tsv(TRIAL7_ARCS)
    stats = [r for r in _read_tsv(TRIAL7_INTERVALS) if r["section"] == "model"]
    diffs = [r for r in _read_tsv(TRIAL7_INTERVALS) if r["section"] == "difference"]
    if not arcs or not stats or not diffs:
        raise TablesError(
            f"{rel(TRIAL7_ARCS)} or {rel(TRIAL7_INTERVALS)} is empty; run the HB-209 evidence"
        )
    kms = [s["arc_km"] for s in arcs if s["model"] == stats[0]["model"]][
        : int(stats[0]["n_arcs"])
    ]
    sat = {r["arc_km"] for r in arcs if r["saturated"] == "yes"}
    # HB-212 Part A: each line's state (above or below only where the 95 percent limits exclude 1), by the one
    # function scripts/benchmark_state.py, reading the same intervals file; its record is docs/evidence/hb212/states.tsv
    states = benchmark_state.by_key(TRIAL7_INTERVALS)
    src = f"`{rel(TRIAL7_ARCS)}`; `{rel(TRIAL7_INTERVALS)}`; `{rel(STATES)}`"
    rows = []
    for s in stats:
        share = {
            r["arc_km"]: r["share_of_measured_percent"]
            for r in arcs
            if r["model"] == s["model"]
        }
        rows.append(
            [s["label"]]
            + [f"{share[k]} %" for k in kms]
            + [
                s["within_factor_2"],
                f"{s['MG']} ({s['MG_low_95']} to {s['MG_high_95']})",
                states[(s["model"], "measurements")]["state"],
                src,
            ]
        )
    head = (
        ["Run"]
        + [f"{k} km" + (" (saturated)" if k in sat else "") for k in kms]
        + [
            "Arcs within a factor of two",
            "MG (95 percent limits)",
            "State against the measurements",
            "Source",
        ]
    )
    first = md_table(head, rows)
    label = {s["model"]: s["label"] for s in stats}
    drows = [
        [
            label[d["model"]],
            label[d["against"]],
            f"{d['ratio_of_MG']} ({d['ratio_low_95']} to {d['ratio_high_95']})",
            states[(d["model"], d["against"])]["state"],
            f"`{rel(TRIAL7_INTERVALS)}`; `{rel(STATES)}`",
        ]
        for d in diffs
    ]
    second = md_table(
        [
            "hazbrief's run",
            "Against",
            "MG ratio, hazbrief over the tool (95 percent limits)",
            "State against the tool",
            "Source",
        ],
        drows,
    )
    return first + "\n\n" + second


#: HB-198 ADDENDUM-01 3b and HB-203 item 5: the gate ledger's summary, written by gate_ledger.py
GATE_LEDGER_SUMMARY = ROOT / "docs" / "evidence" / "hb198" / "gate_ledger_summary.txt"


def gate_ledger() -> str:
    """The ledger's two sentences (after HB-194 landed; before it), quoted from the summary
    gate_ledger.py writes, with the file they come from. Nothing is recomputed here."""
    text = GATE_LEDGER_SUMMARY.read_text(encoding="utf-8")
    after = next(
        (ln for ln in text.splitlines() if ln.startswith("After HB-194 landed:")), None
    )
    before = next((ln for ln in text.splitlines() if ln.startswith("Before it:")), None)
    if not after or not before:
        raise TablesError(
            f"{rel(GATE_LEDGER_SUMMARY)} lacks its two sentences; run gate_ledger.py"
        )
    return (
        "Every full gate run since HB-189 is a row of the gate ledger (`docs/evidence/hb198/gate_ledger.tsv`, "
        "written by `gate_ledger.py` from the committed tails), each failure classed by what it waited on. "
        "The bound is the exact (Clopper-Pearson) one-sided 95 percent upper limit on the failure rate. "
        f"{after} {before} (`{rel(GATE_LEDGER_SUMMARY)}`)"
    )


# ── the document ─────────────────────────────────────────────────────────────────────────────────────────────────


def splice(doc: str, name: str, body: str) -> str:
    start, end = f"<!-- hb196:{name} -->", f"<!-- /hb196:{name} -->"
    i, j = doc.find(start), doc.find(end)
    if i < 0 or j < i:
        raise TablesError(f"{rel(DOC)} lacks the marker pair for {name}")
    return doc[: i + len(start)] + "\n" + body + "\n" + doc[j:]


def build() -> dict[Path, str]:
    qbar_counts, qbar_tsv, qbar_md = question_bar()
    oos_tsv, oos_md, _ = out_of_scope()
    ds_tsv, ds_md = data_sources()
    doc = DOC.read_text(encoding="utf-8")
    for name, body in (
        ("template-harness", template_harness()),
        ("question-bar", qbar_md),
        ("out-of-scope", oos_md),
        ("data-sources", ds_md),
        ("benchmark-table", benchmark_table()),
        ("benchmarks", benchmarks()),
        ("trial7", trial7()),
        ("gate-ledger", gate_ledger()),
    ):
        doc = splice(doc, name, body)
    return {
        EVIDENCE / "question_bar.tsv": qbar_tsv,
        EVIDENCE / "question_bar_counts.tsv": qbar_counts,
        EVIDENCE / "out_of_scope.tsv": oos_tsv,
        EVIDENCE / "data_sources.tsv": ds_tsv,
        DOC: doc,
    }


def main(argv: list[str]) -> int:
    try:
        out = build()
    except TablesError as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 2
    if "--check" in argv:
        stale = [
            rel(p)
            for p, t in out.items()
            if not p.is_file() or p.read_text(encoding="utf-8") != t
        ]
        for s in stale:
            print(f"{s} differs from its sources; run scripts/submission_tables.py")
        if not stale:
            print("every generated table equals its sources")
        return 1 if stale else 0
    for p, t in out.items():
        p.write_text(t, encoding="utf-8")
        print(f"wrote {rel(p)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
