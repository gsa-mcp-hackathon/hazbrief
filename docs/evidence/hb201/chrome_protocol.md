# HB-201 Part B: the protocol for the Chrome test that failed alone in a worktree

Committed before any run of the test it governs, and never changed after (task item 6;
`test_hb201_evidence.py (a test held privately)` holds that this file's first commit precedes `chrome_runs.tsv`'s and that this file has
one commit). An amendment, if one is needed, is a new file committed before the runs it governs.

The test: `test_hb103_weather_map.py (a test held privately)::test_the_drawn_arrow_layer_counts_one_symbol_per_cell`. Its module
fixture `night` assembles the brief of `docs/briefs/i81-md-pa-line-night/scenario.json` in replay
(`_brief(NIGHT)`); the test writes the page and dumps its DOM with headless Chrome through
`test_brief_map.py (a test held privately)::_dump_offline` (`--virtual-time-budget=15000`, every host unresolvable, a 120 s bound,
under `tests/one_chrome.py`'s machine-wide lock), then reads `#map[data-wind-field]`.

## What was known before the first run

These come from reading the code and from pilots of the instrument on *other* tests; none is a run of the test
above.

1. **The key is not what differs between HB-196's places.** `CENSUS_API_KEY` is exported in this session's
   environment, and the master secrets file (`~/.secrets/master.env`, DN-004) holds it. An exported variable outranks
   both files (`src/hazbrief/config.py`), so a `git archive` copy in /tmp with no `.env` resolves the same real key as
   the worktree. HB-196's record does not state its session's environment; if it was as this one is (the same
   dispatcher), its archive runs had the key too, and the one difference it named was not a difference.
2. **Without a key the tests hold a placeholder.** `tests/conftest.py::_replay_census_key` sets
   `replay-placeholder` whenever no key resolves in replay. The key's value is read only for presence
   (`src/hazbrief/census.py`) and to keep it out of records (`utils._secret_values`, `evidence.store`).
3. **Pilot, the same fixture without Chrome**
   (`test_hb103_weather_map.py (a test held privately)::test_the_brief_keys_the_band_on_the_footprints_own_period`, worktree, the probe
   loaded): with the real key and with the key unset (variable removed, master file emptied, `.env` link aside), the
   assembled page was 1,683,449 bytes both times, sha256 `d0fde1a4f3e3...` both times, and the Data sources view read
   `population_at_risk: not_contacted` (its replayed record is DN-003's no-key error) and
   `modelled_population: answered` both times. 1,683,449 bytes is also the committed i81 night brief's size in
   `docs/evidence/hb192/live_load.tsv`.
   **Prediction:** all four cells assemble the same page, so H1's mechanism, as stated, does not operate in replay.
   The cells still vary the key alone, as the task asks; the reading rule below says what a key split would then
   mean.
4. **A leftover Chrome.** At 07:08 EST, before any run, one headless Chrome of exactly this test was running: profile
   `pytest-3628/popen-gw0/test_the_drawn_arrow_layer_cou0` (an xdist worker's, so a gate's), 2 h 51 min old, parent
   gone (an orphan), 0.0 percent of a processor. The first run's check ends it and records it.
5. **Load.** Load average 5.96, 5.82, 5.97 at 07:08 with no work of this session running; `fseventsd` was using about
   80 percent of one processor. The machine has 10 cores.
6. **Instrument pilot, Chrome** (`test_brief_map.py (a test held privately)::test_offline_every_layer_draws_and_the_zones_fit_the_payload[-un1057-fire-unresolved-i81]`):
   the probe recorded Chrome's 6.7 s, exit 0, a 0.0 s wait for the lock, 1,432,870 DOM characters, both signals.

## Hypotheses

- **H1, the key:** with `CENSUS_API_KEY` set, the fixture assembles a fuller brief (population answered from its
  recordings, not DN-003's no-key error), which takes longer to assemble and to render.
- **H2, load:** other work on the machine at the time.
- **H3, the place:** something else that differs between a dispatcher worktree and a copy: its links (`.env`,
  `corpus/raw`, the graph directories), its `.venv`, its gitignored files.
- **H4, leftover processes:** Chrome or engine processes left running by an earlier failed run.

## Design

Four cells, place by key, six runs a cell, 24 runs:

| Cell | Place | Key |
|---|---|---|
| `worktree:set` | this worktree | set |
| `copy:set` | a `git archive` of the commit the runs start from, extracted once into `/tmp/hb201_copy_<commit>` | set |
| `worktree:unset` | this worktree | not set |
| `copy:unset` | the same copy | not set |

- **Place.** Both places run this worktree's interpreter (`.venv/bin/python -m pytest`), with the place's own `src/`,
  root and `the HB-201 evidence (held privately)` on `PYTHONPATH` and the place as the working directory (HB-196's method,
  `the HB-196 evidence (held privately)`). So the interpreter and packages are held; the files, links and
  gitignored data differ.
- **Key, set:** the environment as the session has it: `CENSUS_API_KEY` exported (in the worktree the `.env` link
  and the master file hold the same key; in the copy, the master file).
- **Key, not set:** `CENSUS_API_KEY` removed from the run's environment and `HAZBRIEF_MASTER_ENV` pointed at an empty
  file, in both places; in the worktree the `.env` link (which sets only `CENSUS_API_KEY`) is moved aside for the run
  and put back after it; the copy has no `.env`. Nothing else changes.
- **Shown per run:** the key the run's settings resolved (`real`, `placeholder`), and from the assembled brief's
  Data sources view (`data_sources.rows`, the rows the view prints) the outcome of each population channel.
- **Order:** a fixed rotation, `worktree:set`, `copy:set`, `worktree:unset`, `copy:unset`, repeated six times, so
  load falls on all four alike. One run at a time, the test alone. This session starts nothing else while they run.
- **The tool:** `the HB-201 evidence (held privately) run --phase cells --runs 24`, with the pytest plugin
  `the HB-201 evidence (held privately)` loaded (`-p chrome_probe`). The plugin changes nothing the test does:
  it times the `night` fixture, hashes the page, reads the Data sources rows, and times Chrome's own run inside the
  lock. One row a run is appended to `chrome_runs.tsv` as the run ends; re-running the command resumes.

## Per run

`chrome_runs.tsv` columns: the cell; the commit; the load average (one minute) before and after; the count of Chrome
and engine processes already running, and for each its age and processor share; any orphan among them ended, and
said so (a process with a live parent is someone's running work and is only recorded); the fixture's seconds;
Chrome's wait for the lock; Chrome's own seconds; Chrome's exit code (`timeout` when the bound ended it); the bound;
the page's bytes and sha256; the DOM's characters; whether the DOM carries `#map[data-drawn]` (the page's finished
signal) and `#map[data-wind-field]`; the resolved key; the population outcomes; pytest's seconds; the outcome, and on
a failure its own line. The full pytest output of each run is kept in the gitignored `logs/`.

## The reading rule (written before the runs)

Outcome per run: passed, or not passed (failed, error, or the runner's 1800 s ceiling).

- **The test:** Fisher's exact test, two-sided, on passed and not passed: by key (12 runs against 12) and by place
  (12 against 12), computed from the hypergeometric distribution (`chrome_runs.py fisher_two_sided`). A split is read
  as supported at p < 0.05. At this size, with none failing on one side: 3 of 12 against 0 gives p = 0.217, 4 gives
  0.093, 5 gives 0.037. So a difference of about one failure in four against none (3 of 12) is not told from chance,
  and if that is the result the RESULT says "not established" again.
- **H1** is supported only if failures split by key (p < 0.05) *and* the key cells assemble different pages (sha256)
  or population outcomes. If the pages are the same across the key cells (the prediction), a key split cannot be the
  key's doing through the brief, and H1 as stated is refuted whatever the counts.
- **H3** is supported if failures split by place (p < 0.05), the two key cells alike within each place.
- **H2** is supported if failures fall in more than one cell and each failing run's load before it lies above the
  range of the passing runs' loads; it is not supported if failing runs' loads lie inside the passing runs' range.
- **H4** is supported if the failing runs are the ones that found leftover processes at their start; not supported if
  failures occur with none found.
- **No failure in 24:** HB-196's failure is not reproduced under these conditions, and its cause is not established.
  Six passes in a cell rule out a failure rate there as high as HB-196's three in four alone ((1/4)^6 = 0.0002), and
  do not rule out one in four ((3/4)^6 = 0.18).

## Item 8, if any cell fails

The cell that failed most (a tie goes to `worktree:set`, HB-196's own, then to the rotation's order). For its failing
runs: the fixture's seconds (assembly), the wait for the lock, Chrome's seconds and exit, and whether the DOM Chrome
printed carries the finished signal. A bound that ends Chrome leaves no DOM (`--dump-dom` prints at exit), so where
Chrome's time goes inside its run is read on the kept page (`HB201_KEEP_PAGE`) with Chrome's own log
(`--enable-logging=stderr`) and the page's signals timed against it, outside the test. Then six runs of that cell
with the bound lifted to 600 s by environment (`HB201_CHROME_TIMEOUT=600`, read by the probe; nothing committed
changes the test): Chrome's seconds to exit, whether the signal is in the DOM, and whether the assertion holds.

## Item 9, which one follows

- **(a)** if, in item 8's runs, the runs that took past 120 s finish (exit 0, the signal given) and the assertion
  holds: the bound is measuring the machine. The ceiling becomes at least three times the slowest finishing run of
  item 8, stated with that number, and the tests wait for the signal under it; six runs alone in the worktree with
  the key before and after, in `chrome_runs.tsv`. If that needs anything under `src/`, it stops and says so.
- **(b)** if Chrome hangs (exit 2, `RESULT_CODE_HUNG`) or runs to the 600 s bound, or exits without the signal, in
  any of item 8's runs: an Issue, importance high, with the runs; then the committed
  `docs/briefs/csx-point-of-rocks-night/brief.html` opened from its file six times in the same headless Chrome.
- **(c)** otherwise (no cell failed; or item 8's runs all finish within 120 s, so the bound never bit): not
  established. The table is reported and nothing changes.

In every case no test is deleted, skipped or marked expected to fail, and where the page with the key takes longer
than `docs/evidence/hb192/live_load.tsv` says the live i81 night brief takes (49.7 s), both numbers are printed side
by side.
