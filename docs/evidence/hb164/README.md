# HB-164 evidence: the gate runs in parallel

Task: `HB-164`.
Machine: the operator's Mac (10 cores: 8 performance, 2 efficiency; 32 GB, swap nearly
full and the disk 98 % full during these runs; other sessions running).

| File | What it is |
|---|---|
| `durations_serial.txt` | Part A item 1: the serial run's 100 slowest phases, as `--durations=100 --durations-min=1.0` prints them |
| `durations_serial_table.md` | Part A item 1: the 100 slowest tests (phases summed), their file and share of the serial wall clock; the slowest 1 percent's share; files by summed time |
| `slowest_classified.md` | Part A item 2: the 100 slowest tests by what makes them slow |
| `runs.md` | Every full run of this task: configuration, wall clock, counts, failures |
| `gate_tail.txt` | The third proof run's tail |
| `tools/durations.py` | Writes the two durations files from a `--durations=0 --durations-min=0` log |
| `tools/classify.py` | Writes `slowest_classified.md` |
| `tools/gate.sh` | Runs `the Seldon configuration (held privately)` `dispatch.gate_command` verbatim, with wall clock and exit |

## What was measured

- **Serial**, on a clone of main at `8962050e` in `/tmp` (the worktree's interpreter):
  `2670.39 s` (44 min 30 s) of pytest. The slowest 1 percent of tests (68 of 6,753) take
  47.3 percent of the summed test time (46.1 percent of the wall clock); the slowest 100
  take 56.3 percent.
- **What makes them slow** (the 100 slowest, `slowest_classified.md`): the first use of a
  module's cached replay of a committed brief (48 tests, 612 s), computation (21, 347 s),
  brief rebuilds (10, 224 s; one test, 137 s, builds every committed brief twice),
  corpus or fixture reads (6, 122 s), headless Chrome captures (10, 119 s), and
  kill-and-resume harnesses (5, 80 s).
- **The same expensive setup more than once:** `test_hb130_event_stream.py`,
  `test_hb131_panels.py`, `test_hb141_checklist.py` and `test_hb154_shell.py` each replay
  the committed briefs with the identical call (`cli.replay_brief(_scenario(sid), _now(),
  events.append)`) into a module `@cache`; `test_hb132_load_read.py`,
  `test_hb115_cue_block.py`, `test_hb157_plume_over_time.py` and others replay or
  assemble the same briefs again. A replay of `csx-point-of-rocks-night` costs 16 to 20 s
  the first time in each module. `test_corpus_claims.py`'s module fixture `answers`
  starts a Squiddy search over the corpus graph (21 s).

## Why `--dist loadfile`, and why six workers

1. `-n auto` (10 workers) with tests spread one at a time (`--dist loadgroup` with no
   groups is xdist's `load`) was slower than serial: every worker repeated each module's
   brief replays and the corpus-claims search (ten Squiddy processes at once), the load
   average reached 38, and the run was stopped at 39 percent after 18 minutes.
2. `--dist loadfile` keeps a module on one worker, so each module cache fills once: 10
   workers ran the suite in 634.58 s with the serial counts.
3. At 10 workers headless Chrome failed in three of four completed runs (exit status 2, Chromium's
   `RESULT_CODE_HUNG`, twice; a 240 s hang once): the load average was 40 to 53. A lock
   that runs one Chrome at a time (`tests/one_chrome.py`) did not stop it on its own.
   `--maxprocesses 6` caps `-n auto` at six workers; at six, three consecutive gates
   passed with load averages of 9 to 15.

The long pole is `test_hb131_panels.py (a test held privately)`: 296 s serially, 517 s on one worker at
ten workers. A module cannot finish faster than its own serial time under `loadfile`.

## Not done, and why

- **One shared replay cache across modules.** Mechanical in form, but it would hand the
  same mutable brief and event list to tests of five modules, which now each own theirs;
  and under `loadfile` the modules sit on different workers, so the parallel gate would
  gain little.
- **Splitting the long-pole module** (`xdist_group` on its three kill-and-resume and
  recording tests, ~90 s serially) or ordering the heaviest modules first. Both would
  shorten the wall clock by roughly the long pole's excess; neither was measured.
- No test was deleted, deselected, skipped, marked flaky or moved to `slow`.
