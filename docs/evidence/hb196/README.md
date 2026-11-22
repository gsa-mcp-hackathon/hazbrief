# HB-196 evidence

What this task wrote, and how each file was made. No network, no model call.

- `resume.md`: the task's items, ticked as each was committed.
- `bench_evidence.txt`: ADDENDUM-05, BENCH-0 to BENCH-7 given HB-192's RESULT as evidence (Result `c939abef`), and
  `seldon verify`'s unverified count before and after.
- `issues.log`: the Issues filed by `tools/file_issues.py` before `docs/FUTURE_WORK.md` names them.
- `blocks_before.tsv`, `weight_before.tsv` (ADDENDUM-04 item 2): written by HB-192's own committed tools,
  `the HB-192 evidence (held privately)` and `weight.py`, copied unchanged into a `git archive` of HB-192's base
  `f63b4249` in `/tmp` (so their `ROOT` is that copy), on the brief ids of `docs/evidence/hb192/blocks_after.tsv` and
  `weight_after.tsv`. Both read only the committed `docs/briefs/<id>/brief.html`; no engine run. They agree with
  HB-192's RESULT: csx night drew 13 + 152 = 165 modelled cordons and 18 + 82 + 2 = 102 road candidates before, and its
  population under the cloud took 3,334,501 bytes of the page.
- `csx_day_before.tsv` (ADDENDUM-04 item 3): csx day's `brief.html` bytes in the same archive copy. Its before live
  load (48.0 s) was never saved as data; the evaluation cites it from HB-192's RESULT and says so.
- `question_bar.tsv`, `out_of_scope.tsv`, `data_sources.tsv`: written by `scripts/submission_tables.py` (ADDENDUM-01
  items 6a and 6b, ADDENDUM-02, Part B item 8), which renders the evaluation's generated tables from them.
- `tools/rebuild.sh`: the replay rebuild after the conditions-of-use edit (HB-189's, without its read list).
