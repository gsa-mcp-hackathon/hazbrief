# HB-196: gate 2's one load-sensitive failure, read

Gate 2's load-sensitive step failed one test:
`test_hb103_weather_map.py (a test held privately)::test_the_drawn_arrow_layer_counts_one_symbol_per_cell` (headless Chrome past its
120 s timeout). The test renders the csx night brief its fixture assembles, in headless Chrome with every host
unresolvable. This task's rebuild moved only the 13 dense briefs' `tevv.html`, so the page Chrome renders is the same
as main's.

| Where | Runs | Outcome |
|---|---|---|
| this worktree, gate 2's load-sensitive step | 1 | failed: Chrome past 120 s |
| this worktree, the test alone (load average about 6.5 to 7.7) | 4 | failed, passed (155 s), failed (226 s), failed: Chrome exited 2, its own `RESULT_CODE_HUNG` ("Teardown watchdog expired"), 20 s into the call after a 149 s fixture setup |
| a `git archive` of main in /tmp, the test alone (`tools/main_baseline.sh`) | 3 | passed (52, 36, 39 s) |
| a `git archive` of this branch's HEAD in /tmp, the test alone | 2 | passed (58, 25 s) |

The code is not the difference: this branch's own archive passes. The one difference found between the worktree and
the archives is the worktree's `.env` link (the dispatcher's, to the primary checkout's file), which sets
`CENSUS_API_KEY`; the archives hold no `.env`. With the key the population tools answer from their recordings rather
than with DN-003's structured no-key error, so the brief the fixture assembles carries more. That this is why Chrome
hangs here is not established: no run varied the key alone. The lasting form for a test bound to a fixed clock is
Issue `d0475c31` (future work F11).
