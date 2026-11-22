# HB-201 Part B: the reading of chrome_runs.tsv

Written by `the HB-201 evidence (held privately) summarize` from `chrome_runs.tsv`, under the reading rule of `chrome_protocol.md` (committed before the first run).

## Phase `cells` (24 runs)

| Cell | Runs | Passed | Not passed | Fixture s (min to max) | Chrome s (min to max) | Pages (sha256, first 12) | Population (Data sources) | Census key resolved |
|---|---|---|---|---|---|---|---|---|
| worktree:set | 6 | 6 | 0 | 22 to 26 | 2 to 7 | d0fde1a4f3e3 | {"modelled_population": "answered", "population_at_risk": "not_contacted"} | real |
| copy:set | 6 | 6 | 0 | 22 to 24 | 2 to 6 | d0fde1a4f3e3 | {"modelled_population": "answered", "population_at_risk": "not_contacted"} | real |
| worktree:unset | 6 | 6 | 0 | 22 to 25 | 2 to 4 | d0fde1a4f3e3 | {"modelled_population": "answered", "population_at_risk": "not_contacted"} | placeholder |
| copy:unset | 6 | 6 | 0 | 22 to 36 | 3 to 10 | d0fde1a4f3e3 | {"modelled_population": "answered", "population_at_risk": "not_contacted"} | placeholder |

- By key: set 0 not passed of 12, unset 0 of 12; Fisher's exact test, two-sided, p = 1.000
- By place: worktree 0 not passed of 12, copy 0 of 12; Fisher's exact test, two-sided, p = 1.000

- Load average before a run: 4.81 to 10.04.
- Pages assembled: 1 distinct (d0fde1a4f3e3).
- Assembly plus Chrome, per run: 23.9 to 39.0 s, beside 49.7 s, the live i81 night brief's load in `docs/evidence/hb192/live_load.tsv` (a different measure: the live page in the shell).

Under the protocol's reading rule: no failure in 24, so HB-196's failure is not reproduced under these conditions and its cause is not established. Six passes in each cell rule out a failure rate as high as HB-196's three in four alone ((1/4)^6 = 0.0002) and do not rule out one in four ((3/4)^6 = 0.18). H1 is refuted as a mechanism: one page across both keys. No split by key or by place to read for H1 or H3; no failure to set against load (H2) or leftovers (H4).

Processes found running before a run:

- run 1 worktree:set: chrome pid 17232 age 10678 s cpu 0.0% orphan, ended profile test_the_drawn_arrow_layer_cou0; engine pid 47937 age 1283 s cpu 0.8% parent 47315, left
- run 2 copy:set: engine pid 47937 age 1320 s cpu 0.3% parent 47315, left
- run 3 worktree:unset: engine pid 47937 age 1350 s cpu 0.0% parent 47315, left
- run 4 copy:unset: engine pid 47937 age 1381 s cpu 0.2% parent 47315, left
- run 5 worktree:set: engine pid 47937 age 1411 s cpu 1.9% parent 47315, left
- run 6 copy:set: engine pid 47937 age 1442 s cpu 1.9% parent 47315, left
- run 7 worktree:unset: engine pid 47937 age 1472 s cpu 1.5% parent 47315, left
- run 8 copy:unset: engine pid 47937 age 1506 s cpu 0.1% parent 47315, left
- run 9 worktree:set: engine pid 47937 age 1536 s cpu 0.9% parent 47315, left
- run 10 copy:set: engine pid 47937 age 1563 s cpu 1.9% parent 47315, left
- run 11 worktree:unset: engine pid 47937 age 1594 s cpu 4.4% parent 47315, left
- run 12 copy:unset: engine pid 47937 age 1626 s cpu 0.1% parent 47315, left
- run 13 worktree:set: engine pid 47937 age 1658 s cpu 0.5% parent 47315, left
- run 14 copy:set: engine pid 47937 age 1692 s cpu 0.1% parent 47315, left
- run 15 worktree:unset: engine pid 47937 age 1726 s cpu 2.1% parent 47315, left
- run 16 copy:unset: engine pid 47937 age 1762 s cpu 0.5% parent 47315, left
- run 17 worktree:set: engine pid 47937 age 1807 s cpu 0.3% parent 47315, left
- run 18 copy:set: engine pid 47937 age 1840 s cpu 1.0% parent 47315, left
- run 19 worktree:unset: engine pid 47937 age 1869 s cpu 0.6% parent 47315, left
- run 20 copy:unset: engine pid 47937 age 1900 s cpu 1.3% parent 47315, left
- run 21 worktree:set: engine pid 47937 age 1942 s cpu 0.4% parent 47315, left
- run 22 copy:set: engine pid 47937 age 1982 s cpu 1.1% parent 47315, left
- run 23 worktree:unset: engine pid 47937 age 2013 s cpu 0.2% parent 47315, left
- run 24 copy:unset: engine pid 47937 age 2042 s cpu 1.3% parent 47315, left

Note on the `engine` column: in this phase the pattern matched whole command lines, and the process it counted in every row (pid 47937, parent 47315) is this session's own `claude -p`, launched by `seldon dispatch once`, whose prompt holds the word SLAB. It is not an engine, and it was only recorded, never ended. No SCICHEM, SLAB or models-image process ran during the phase. The pattern now reads the executable's name only. The one real leftover was the orphaned headless Chrome of the protocol's observation 4, ended before run 1.
