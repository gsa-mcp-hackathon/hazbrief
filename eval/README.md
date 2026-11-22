# Evaluation

The evaluation harness is `eval_harness.py (a build tool held privately)`, and every value a run depends on is in
`eval/harness.yaml`, so a change to a run is a reviewed diff of that file. No model writes any
sentence the server returns, so there is no model trace to score: the harness is deterministic
and runs over the code's own outputs. Its method and first results are
[`LN-05`](../docs/lab/2026-10-21_LN-05_eval_harness.md).
The agent-level evaluation (part D of `harness.yaml`, `scripts/agent_eval.py`, the prompt set
`eval/agent_prompts.yaml` and the runs under `eval/agent_runs/`) is
[`LN-07`](../docs/lab/2026-10-22_LN-07_agent_eval.md).

There are three families. **A, invariants**, is bounded-exhaustive over the whole finite input
domain: every ID number and name, every Table 1 and Table 3 cell, every guidance combination and
every flag cause by MC/DC, with every distance traced to its pack cell. **B, regression**, is
characterization testing: every tool on every frozen scenario against its golden-master snapshot
in `fixtures/scenarios/`, the recorders' `expected.json` entries and the frozen forms. **C, live
drift**, re-records the scenarios against the live federal sources under a call ceiling and
diffs each exchange, and each tool output, against replay.

```bash
uv run pytest -m slow test_eval_invariants.py (a test held privately)   # A (nightly in CI)
uv run python eval_harness.py (a build tool held privately) invariants      # A, with its report
uv run python eval_harness.py (a build tool held privately) regression      # B (also in the default test gate)
uv run python eval_harness.py (a build tool held privately) live            # C: network; needs CENSUS_API_KEY
```

A and B run network-free, in replay. B's snapshots are written only by `regression --approve`,
and a change is reviewed by `git diff` (`docs/FIXTURES.md`). The reports of A and B land in
`logs/` as `<date>_HB-05_<part>.json`, which is gitignored. C records into a dated directory,
`fixtures/exchanges_live/<date>/`, with its `calls.jsonl` and `drift.json`, never into the replay
fixtures. Filed and unfixed part A findings are listed in `eval/known_findings.yaml`, which the
slow test reads. `databricks/ (held privately)` is the template's MLflow kit for a Databricks deployment; this
project does not use it.
