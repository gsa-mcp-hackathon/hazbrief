# HB-180 item 11: the verdict, by the protocol

Each hypothesis of `protocol.md` (and ADDENDUM-01's), with what the check showed and the file that shows it. Parts A
and B used no measured value; Part C read the measurements once, after `protocol_measurements.md` was committed.

| Hypothesis | Verdict | What shows it |
|---|---|---|
| H1 mass or units | **ruled out** | The engine's moving puffs carry exactly CMASS x t at every dump, to 1 part in 1,000, in all five cases (`mass_closure.tsv`, check A); the static puffs are a separate near-source representation on top. Every field's unit matches the user's guide (`units_audit.tsv`); the guide's word "diameter" for SIGY and SIGZ is not what the code does (it squares them as standard deviations, as hazbrief writes them). Check B, the flux through a plane from sensor doses, is an estimate (0.2 to 0.9 of the release) and decides nothing. |
| H2 numerical resolution | **confirmed for the vertical grid; small or none for the rest** | The shipped request leaves the vertical grid at the engine's default, 250 m (the run's own log, "zmin,zmax,dz: 0, 2500, 250"), for a cloud 2 to 27 m deep. The engine caps the grid at 200 levels, so finer needs a lower top (ZMAX alone moves nothing). Refined, the arcs rise and do not converge: at 1.25 m csx night is x1.3 to x2.6 (125 m and 250 m tops), Desert Tortoise 4 x1.5, Thorney Island 047 x1.1 to x1.6; at 0.625 m csx night is x2.0, x3.0, x4.3 and x3.0 at 100 m, 500 m, 1 km and 5 km and Thorney Island 047 x1.05 to x1.95, both still rising (csx night's 0.625 m run took 53 minutes) (`convergence.tsv`, `vertical` rows). DELT: 3 to 18 percent from 60 s to 1 s, no trend (not converged by the 5 percent convention, small). The domain: csx night identical at 15, 30 and 60 km (a plateau); 10 km moves its 100 m arc by 32 percent, because the domain also sets the single 60 km observation cell. HRES, MGRD, ZMAX and NZBL: converged. STATIC: an option, 7 to 13 percent. DT_SMP: output only. |
| H3 the source's initial size and state | **ruled out as the cause** | At the first dump the moving mass equals the release (`mass_closure.tsv`); the night deficit grows with distance rather than starting at the source (`decomposition.tsv`). The engine's first-dump temperature excess (ctb/c, a concentration-weighted mean over each puff) is -1.1 to -8.4 K on every dense brief and trial, so the 100 K floor is never reached (`handoff.tsv`). |
| HA the hand-off (ADDENDUM-01) | **ruled out** | The held deficit does not order with speed / u(1 m) (`handoff.tsv`, `plot_handoff.svg`: Desert Tortoise 4 at 0.28 is low, Thorney Island 047 at 1.56 is low, Thorney Island 045 at 0.94 and csx day at 1.22 agree, csx night at 4.0 is low). Run with the area made consistent with the 1 m wind, every arc at 200 m or more moves by -11 to +6 percent, at csx night by -9 to -11 percent (`handoff_runs.tsv`). On the daytime trials the shipped SCICHEM is low as the hand-off predicted, but SLAB, which has no hand-off, is as low (`statistics_c.tsv`). |
| H4 stable-layer mixing | **confirmed in its signature; located in the dense terms, not the ambient layer** | At csx night SCICHEM's cloud is 3.0 to 4.9 times SLAB's depth and narrower than SLAB's to 1 km; on Thorney Island 047 3.6 to 4.2 times; by day at csx it is no deeper than SLAB's (`decomposition.tsv`). Under class F the SLAB/SCICHEM ratio at 100 m falls from 7.6 at 0.5 m/s to 1.9 at 5 m/s while SLAB's own value hardly moves, and SCICHEM's depth falls from 11.2 to 2.3 m (`sweep.tsv`). With the dense terms off, the same stable layer keeps the cloud at about 7.6 m (`factorial.tsv`), so the extra depth is the dense terms', not the layer's. |
| H5 the dense-gas terms are not acting | **ruled out: they act, and they deepen the stable cloud** | With DENSE_GAS off, csx night's arc maxima are x1.4, x2.2, x2.8 and x6.2 at 100 m, 500 m, 1 km and 5 km; the cloud stays near 7.6 m deep where the dense run grows from 5.8 to 26.6 m; widths change by 15 percent or less (`factorial.tsv`). An engine rebuilt with the dense puff's self-generated diffusion off (step_pturb's qpdiff) gives x4.6, x1.9, x1.4 and x1.3 (`engine_variants.tsv`, `__nodenseturb`): that term carries most of the excess near the source; beyond 1 km the rest of the dense branch carries it. |
| H6 what is compared | restated | HB-177: mean against peak, MG 3.50 to 1.80 (`docs/evidence/hb177/hb176_restated.tsv`); reproduced here (`statistics_c.tsv`, stable rows). |
| H7 the compiler on a stable case | **ruled out** | EPRI's Intel build and the gfortran build agree at every compared value of csx night and Thorney Island 047 within 0.03 percent (`compiler.tsv`). |
| H8 the documentation against the code | **a mismatch, not the factor** | Technical documentation section 5.3.3: C_d2 = 10 in F_d = 1 / (1 + C_d2 Ri_d) (Eq. 240) and Ri_d's denominator V_d^2 + V^2 (Eq. 241); the code has FAC_DENSE = 15 and 4 V_d^2 + V^2 (`step_p_dyn.f90`). Rebuilt with the documented form, csx night moves x1.5 at 100 m and within 10 percent beyond; Thorney Island 045 x0.76 to x0.97 (`engine_variants.tsv`, `__docform`). The other coefficients match: CQB 0.4, CVRTX 3, the 1.5 length factor, the 1/pi velocity scale, the 30 percent Puttock speed reduction. The repository's examples (TVA, Four Corners, NO2, SO2) hold no dense case. |
| H9 two conventions | **small** | The code reads DENSITY as the gas density at 293 K and 1 atm (`rhogas*pgas*293./tgas`); hazbrief writes it at the air temperature, so the gas is read denser by 293 / T_air (csx night 1.045; `units_audit.tsv`). The nominal air density 1.2 kg/m3 against Desert Tortoise's 0.891 atm. |
| H10 a release with no liquid given the boiling point | **a defect of the path, by reading** | `jet_source` gives Thorney Island's gas, released at air temperature, BUOY = (T_boil - T_air) x volume (-158 K m3/s for TC45). HB-177 ran the authors' source (`source_ti`): MG 4.00, away from 1, so it is not the stable deficit. |
| H11 the puff-interaction grid | **ruled out** | With one surface station the met grid is a single 60 km cell; HRES at 2, 0.5 and 0.1 km and MGRD at 1 and 0 change no arc (`convergence.tsv`). |
| Part B item 6, the passive check | **within 1.5 of the curve for width; up to 2.05 deep** | Through hazbrief's builder, passive and neutral: width 0.80 to 1.49 of the Pasquill-Gifford class D sigma_y at 100 m to 10 km; depth 1.34 to 2.05 of sigma_z (above 1.5 at 1 and 3 km; the 320 m column truncates at 10 km) (`passive_check.tsv`). |

## The factor's dimension (Part C item 8)

`decomposition.tsv`, `plot_decomposition.svg`: the stable deficit is carried by **depth**. SCICHEM over SLAB, depth:
csx night 3.9, 4.6, 4.9 and 3.0 at 100 m, 500 m, 1 km and 5 km; Thorney Island 047 3.6 to 4.2; Desert Tortoise 4 at
800 m 2.0. Width works the other way near the source (SCICHEM narrower: csx night 0.35 to 0.49 to 1 km, Thorney Island
047 0.48 to 0.88). Transport speed 0.5 to 1.7 (Thorney Island 045's SCICHEM cloud is slower than SLAB's, the others faster). The remainder (the profiles' shapes and averaging) is 0.76 to 3.0. Thorney Island 045, the trial SCICHEM matches best, has a depth factor of only 1.4 to 1.6.

## The unseen daytime trials (Part C item 10; `statistics_c.tsv`)

| Regime | Configuration | Statistic | n | MG (observed over predicted) | 95 percent limits | VG | FAC2 |
|---|---|---|---|---|---|---|---|
| daytime | shipped | mean | 11 | 4.33 | 3.28 to 5.71 | 14.0 | 0.18 |
| daytime | shipped | authors' expected maximum | 11 | 2.66 | 1.98 to 3.59 | 3.43 | 0.27 |
| daytime | vres (2.5 m grid) | mean | 11 | 3.37 | 2.43 to 4.67 | 9.63 | 0.27 |
| daytime | vres (2.5 m grid) | authors' expected maximum | 11 | 2.21 | 1.54 to 3.18 | 3.14 | 0.45 |
| daytime | SLAB as hazbrief runs it | centreline | 11 | 2.65 | 2.44 to 2.88 | 2.83 | 0.18 |
| stable | shipped | mean | 8 | 3.50 | 2.87 to 4.27 | 5.29 | 0.13 |
| stable | shipped | authors' expected maximum | 8 | 1.80 | 1.42 to 2.28 | 1.63 | 0.38 |
| stable | vres (2.5 m grid) | mean | 8 | 3.07 | 2.59 to 3.62 | 3.83 | 0.13 |
| stable | vres (2.5 m grid) | authors' expected maximum | 8 | 1.86 | 1.54 to 2.25 | 1.68 | 0.50 |
| stable | SLAB as hazbrief runs it | centreline | 8 | 0.87 | 0.76 to 1.00 | 1.10 | 1.00 |

On the daytime trials both engines, as hazbrief runs them, are low by the same factor (SCICHEM scored as its authors
score a peak 2.66; SLAB 2.65): what is low by day is shared, not SCICHEM's. By night SCICHEM is low and SLAB is not.
The hand-off's prediction (the shipped setup low near the source, by 0.29 to 0.44) holds in direction for SCICHEM and
equally for SLAB, which has no hand-off, so it does not single out SCICHEM's source.

## The verdict

**A defect found by a check that used no measurement: the vertical grid is not converged.** The shipped request
computes a cloud 2 to 27 m deep on the engine's default 250 m vertical grid. Refining it raises the stable arcs at
every halving below 10 m and had not stopped at the finest grid run (0.625 m: csx night x2.0 to x4.3, Thorney Island
047 x1.05 to x1.95). Against csx night's SLAB/SCICHEM ratios (5.0, 7.7, 8.7 and 6.5), the grid alone accounts for
a factor of 2 to 4 of them at 0.625 m, and more is left to a finer grid. A converged value was not found within the engine's 200-level cap and the run time
the task allowed (Desert Tortoise 4 at 1.25 m took 23 minutes). On the unseen trials the one refined grid the protocol
allowed (2.5 m) moved the daytime statistic from 2.66 to 2.21 and the stable from 1.80 to 1.86; the larger moves come
at the finer grids, which the protocol did not score.

**What else is located, not decided.** The stable deficit lives in the cloud's depth, and the depth is made by the
engine's own dense-gas terms (H5; the self-generated diffusion of a puff in dense ground effect near the source, the
rest of the dense branch beyond 1 km). Whether those terms deepen the cloud because the vertical grid is unresolved
(the self-generated diffusion's length scale is the puff's own vertical size, which the grid sets) or because the
model as documented does so, is **not decided**: deciding it needs the vertical grid converged, or shown not to
converge, on the stable cases (a lower top with a finer grid, at a run time measured first).

**No change is made.** Nothing under `src/hazbrief/`, no record and no brief moved.
