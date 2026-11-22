# HB-194 evidence: the gate stops failing on load

Task: `HB-194`
and its ADDENDUM-01. Machine: the operator's Mac (10 cores). The operator's other projects ran
beside every measurement (a load average of 7 to 9 with no test running), and ai-readiness-kg's
own `-n auto` suite ran beside the first series' second gate. Each measurement's load is sampled
every 30 s in its `*load*.tsv`.

| File | What it is |
|---|---|
| `failures.tsv` | Part A item 1: every one-step gate of HB-189, HB-193 and HB-190 (ADDENDUM-01's tenth run), this task's own one-step gate, and the two-step run that failed: what each failure waited on, the bound it missed, and where its log is |
| `gate_before.log`, `gate_before_load.tsv` | This task's one-step gate on the tree it started from (`9d07faad`): the count before (Part B item 5), and an eleventh one-step run, which failed on load too |
| `trace_before.tsv` | Part A item 2: that gate traced, one row per test: its time and what it started (Chrome, an MCP server, docker, a port, another program), from `tools/hb194_trace.py` |
| `static_launchers.tsv` | The same kinds read from the source (`tests/load_sensitive_reach.py`), so a launch a cache hid from the trace is found; recall against the trace 53 of 53 functions |
| `load_sensitive.tsv` | Part A item 2: the 85 tests that launch headless Chrome, assert a wall-clock bound, or start a server or bind a port, each with how it was found and its times |
| `considered.tsv` | The tests the trace saw start something that is not one of the task's kinds (docker runs of the models image, git, uv, scripts): not listed, not marked |
| `stated_wind/` | Part A item 3: the stated-wind test's 45 runs and the diagnosis (`stated_wind/README.md`) |
| `serial_alone.log`, `serial_alone_load.tsv`, `serial_by_kind.tsv` | Part B item 6: the 73 tests first marked, run serially alone (21:53), and their time by kind and by module |
| `suite_tail_unchanged.txt` | `suite_tail`'s two-step reading changes no earlier RESULT's tail (152 tails) |
| `three_gates.tsv`, `three_gates/` | Part C item 7: every two-step gate run, each step's counts, time and peak load, and the logs |
| `tools/` | Every script that made the files above |

## Part A: what failed, and why

Of the ten one-step gates the task and its addendum count, four failed (HB-189 gates 2 and 3,
HB-193 gates 2 and 3); this task's own, an eleventh, failed too. Each failure waited on the
clock: headless Chrome past its 120 or 240 s timeout (two runs), an assembly past its 60 s bound
(one), and the stated-wind test (two runs; HB-189 gate 2 also had a real failure, fixed in
HB-189), whose 15 s channels ran short under load (`stated_wind/README.md`). Each failing test
passed on its next run, alone or in the next gate.

The list (`load_sensitive.tsv`) was found three ways. The first two came first, and the third
was added after Part C's first series:
- **traced** in this task's one-step gate: the test's call or setup started Chrome, an MCP server
  over stdio or a socket bound to an inet address (and the module fixtures that did it for
  several tests);
- **read** in the source: an assertion on elapsed time (`test_orchestrator_harness`,
  `test_eval_puff`) or a kill-and-resume deadline loop whose expiry fails the test (ten tests);
- **reached**, read by `tests/load_sensitive_reach.py`: a test that calls, through any helper or
  fixture, a function that launches Chrome or starts a server or binds a port. A helper under
  `@cache` launches only in the first test of a worker that calls it, so the trace saw that one
  launch and not the other callers. 12 more tests (12 functions) were found this way, among them
  `test_hb158_less_at_once.py::test_every_group_head_and_the_verify_items_are_in_view_at_1440`,
  which had failed HB-193's gate 3.

## Part B: the two steps

The marked tests carry `@pytest.mark.load_sensitive` and their kind's `xdist_group`. The gate's
parallel step deselects them; the second step runs them, three workers, one group per kind.
Serially they took 21:53 (the 73 first marked), over the task's 10 minutes. By kind: chrome
907 s, wall_clock 177 s, server_or_port 166 s. So item 6's grouping was chosen, in a step of
their own rather than inside the parallel step: HB-193's gate 3 Chrome hang happened while
Chrome already ran one at a time under the lock (HB-164's `one_chrome`), so what killed it was
the other workers' load, which grouping inside the parallel step would have kept. The second
step collects only the modules that name the mark (`tests/conftest.py` `pytest_ignore_collect`),
so a module-level skip is not counted twice.

Counts: the one-step gate on the starting tree ran 7,986 tests that passed or failed (7,985
passed, 1 failed), 14 skipped, 17 xfailed and 12 deselected. The two-step gate runs 7,911 plus
85, which is 7,996: the same tests plus the 10 this task added (`test_hb194_serial_step.py (a test held privately)`).
It still skips 14, xfails 17 and deselects the 12 `slow` tests.

## Part C: the runs

| Run | Parallel step | Load-sensitive step | Whole gate | Result |
|---|---|---|---|---|
| series 1, gate 1 (`e5b3558d`, 73 marked) | 7,922 passed, 1:03:20 | 73 passed, 15:50 | 79:17 | green |
| series 1, gate 2 | 2 failed, 7,920 passed, 1:28:18 | not run | 88:24 | red: two `test_hb154_shell` tests, Chrome past 240 s in the parallel step, through the cached `_driven` |
| series 2, gate 1 (`246b2fb1`, 85 marked) | 7,911 passed, 1:01:07 | 85 passed, 14:45 | 76:07 | green |
| series 2, gate 2 | 7,911 passed, 1:03:43 | 85 passed, 17:34 | 81:24 | green |
| series 2, gate 3 | 7,911 passed, 1:12:12 | 85 passed, 16:43 | 89:05 | green |

Before: the one-step gate took 59 to 72 minutes (HB-189 1:01:36 to 1:03:35, HB-193 1:03:04 to
1:12:23, HB-190 1:05:21, this task's 1:02:18), and five of the eleven runs above failed. After: 76 to
89 minutes and three green runs in a row on the widened list. The parallel step is no shorter
than the one-step gate was: its long pole is a few brief-replay modules, not the marked tests.
The second step's 15 to 18 minutes is the price of running them where they do not share the
machine with six workers.
