# The engine's vertical extent (HB-192 ADDENDUM-01 section 4, ADDENDUM-02 item 6): measurement only

Nothing that ships changed. Runs by `tools/tops.py`, each alone in the models image `sha256:bfff10a9...` (HB-192's
driver layer over HB-189's engine), one after another; the machine's one-minute load average is in each row (7.7 to
13.4: other work was running, so a time difference under about 10 percent is not read as a difference).

## From the code (SCICHEM 3.4, commit 156625ef, `src/lib/SCIPUFFlib/SCIPUFF/`)

- **Where the number of levels comes from:** `set_grid.f90` lines 174 to 180: the top is rounded up to a whole number
  of settings, `nz = MIN(MAX(NINT(zmax/vres),1),max_vres())`, `dzg = zmax/FLOAT(nz)`; `max_vres` is `MAXGZ`, 200
  (`util_ip.f90` 601 to 607, `inc/ipgrd_fi.f90` line 6). So HB-187's "800 levels at 0.3125 m under a 250 m top"
  cannot be: the engine takes 200 levels and a 1.25 m cell there. At 1.25 m the top cannot pass 250 m without the
  cell coarsening (`dzg` = top / 200).
- **What reads the levels:** each puff's own cell range, `k0 - nk` to `k0 + nk` with `nk` its own depth over `dzg`,
  capped at `nz` (`inter_dyn.f90` 987 to 991 and 1184 to 1186; `merge.f90` 74 to 76 and 687 to 694); each sensor's
  level range (`sampler.f90` 712 to 738); and once per large time step a loop over every level for the grid's largest
  refinement (`find_mxgrd`, `util_ip.f90` 553 to 574, called from `step.f90` 439).
- **Does any work scale with levels that hold no gas:** only `find_mxgrd`'s loop, 200 trivial reads per large step.
  The interactions, the merges and the sensors visit the levels a puff or a sensor spans, not the empty ones. The
  setting's cost is in the split length and the time-step limits (DN-028 ADDENDUM-13 section 3), not in the levels.

## csx night at 1.25 m: the top lowered to the run's own boundary-layer depth (`tops_csx_night.tsv`)

The run's boundary layer is class F's PGT layer, zi 65 m (its record's assumptions; the engine's `MET TURB` reads 65 m
every hour). Tops: 250 m (shipped), 130 m (twice zi), 65 m (zi).

| Top | Levels | Hour 1 on the page | Whole run | Contours equal to the shipped run's | AEGL-1 / AEGL-2 / AEGL-3 area reached, km2 |
|---|---|---|---|---|---|
| 250 m | 200 | 132.6 s | 208.5 s | (shipped) | 557.09 / 392.95 / 55.56 |
| 130 m | 104 | 143.7 s | 225.2 s | no, 284 of 288 differ | 558.34 / 396.00 / 58.95 |
| 65 m | 52 | 131.1 s | 193.7 s | no, 288 of 288 differ | 559.75 / 398.49 / 57.48 |

**A lower top is not faster and does not give the same answer.** The times are within the load's noise (194 to
225 s); the areas move by up to 6 percent (AEGL-3 at 130 m). Nothing is proposed.

## i81-md-pa-line-day: the top raised toward the engine's own daytime boundary layer (`tops_i81_day.tsv`)

The engine computes the day's boundary layer (`BL_TYPE CALC`); its `MET TURB` sensor reads zi 1,035 m and 1,100 m in
the run's first two hours, four times the 250 m top. Tops: 250 m (shipped), 500 m and 1,000 m. At this build's 200
levels a taller top coarsens the cell: 2.5 m and 5 m.

| Top | Cell | Hour 1 | Whole run | AEGL-1 / AEGL-2 / AEGL-3 area reached, km2 |
|---|---|---|---|---|
| 250 m | 1.25 m | 9.1 s | 21.9 s | 17.22 / 6.94 / 1.49 |
| 500 m | 2.5 m | 5.1 s | 13.1 s | 16.40 / 5.93 / 1.47 |
| 1,000 m | 5 m | 3.6 s | 10.1 s | 15.80 / 6.22 / 1.43 |

**Mass above 250 m in the shipped run:** none is held: the domain ends at 250 m, below the engine's own 1,035 to
1,100 m layer. **Does the 250 m top explain the AEGL-1 fall (20,954 to 12,401 residents, HB-189 `day_counts.tsv`)?**
Not on this evidence: raising the top shrinks the AEGL-1 area further (17.22 to 15.80 km2) instead of restoring it,
though each taller top also coarsens the cell, so the two cannot be separated in this build. A taller top at 1.25 m
needs an engine with more than 200 vertical levels (`MAXGZ`). No change is proposed and no Conditions-of-use sentence
is added; the proposed measurement is in the RESULT.
