# HB-111 evidence: slabx tried first, the SLAB image, its gate, and the client

Scratch work was under `/tmp/hb111/`, never in the repository. The SLAB archive
(`corpus/raw/epa-slab-code.zip`, sha256 `0d19cf8e…3e4e`) was unpacked there; its source and
test files are not committed.

## 1. Part 0 (ADDENDUM-00): slabx 1.0.7 against SLAB's four cases

**What slabx is.** The held page (`corpus/raw/pypi-slabx.md`, clipped by HB-107; the
`docs/evidence/hb107/ports/hb107_pypi-slabx.md` copy) says: "slabx 1.0.7", "Released: Sep 12,
2026". It is "A Python reimplementation of SLAB", "not a clean-room implementation". The licence
is "MIT, for this implementation", and "The original SLAB source is not included". The
repository is https://github.com/lyullee/slabx and the concept DOI 10.5281/zenodo.22023625.
`uv add --optional brief slabx==1.0.7` resolved it from PyPI. The sdist's sha256 is
`41e17c17d0482edbf3752fc8fb74d7b124932258869f370e77648f5df303d347` and the wheel's
`f677b305bfa36816a9baded09a7c9653f8aa4ba46f09040b7f9e1c413815aaf4`, both from `uv.lock`. The
sdist was downloaded once more to `/tmp` and hashed to the same value. It brings numpy and scipy.
The installed wheel's licence file is the MIT text.

**How it was run.** The wheel ships no deck reader (`slabx/io/` is empty). Its own Fortran
comparison harness (`golden/`, `examples/`) is not in the sdist either. So
`slabx/run_slabx_cases.py` maps each deck field to slabx's API (Substance, the four source
classes, Atmosphere); the mapping is in its docstring. It runs `run_dispersion` with `x_max`
= XFFM and `concentration_field(z="max", t_avg=TAV)`. It then compares, at every x SLAB prints,
two of SLAB's tables: the instantaneous cloud table and the maximum-centreline table. slabx's
values are interpolated linearly in log x.

**Results** (`slabx/run.log`, `slabx/by_column.md`, `slabx/five_percent.txt`, all rows in
`slabx/rows_PR*.json`):

| case | values compared | over one unit (3rd sig. fig.) | concentrations over 5 % | median rel. |
|---|---|---|---|---|
| PR1 problem 1 (pool) | 793 | 327 | 2 of 122 | 0.33 % |
| PR1 problem 2 (pool) | 767 | 244 | 2 of 118 | 0.20 % |
| PR2 (horizontal jet) | 793 | 339 | 0 of 122 | 0.22 % |
| PR3 (instantaneous) | 741 | 238 | 10 of 114 | 0.18 % |
| PR4 (vertical jet, chlorine) | 793 | 548 | **47 of 122** | 1.8 % |

* **HB-102's third-significant-figure tolerance cannot judge a port on another grid.** The same
  log-x interpolation, run on SLAB's own table with every other row held out, puts 20 to 56
  percent of the held-out values over one unit (`by_column.md`, "interpolation floor"). So the
  tier that decides is DN-020 ADDENDUM-00 item 2, a port's tier: concentrations within 5
  percent at every reported distance.
* **On that tier slabx is not admitted.**
  * PR4 misses by 5 to 24 percent from 1 m to 36 m on both concentration tables.
  * PR3's centreline misses by 5 to 8 percent from 13 m to 46 m.
  * PR1's two misses are the upwind edge of the pool (x = -31.5 m and -12.8 m, where SLAB prints
    0). They are an artefact of the comparison, not counted against it.
  * PR2 reproduces within 5 percent everywhere.
* **Grid-independent, it does well far out.** PR4's distances to 1E-02 through 1E-05 agree
  within 2.4 percent (`by_column.md`).

**Decision (0c): any case does not reproduce, so Parts A to C were done as written.** No later
task wants slabx (`grep -l slabx *`: only HB-102, 105, 107, 116 and 118, all
reading or registering it). So `uv remove --optional brief slabx`, with `pyproject.toml` and
`uv.lock` back to HEAD byte for byte. `test_slabx_reproduces_slab.py (a test held privately)` re-runs PR4 wherever
slabx 1.0.7 is installed and asserts the recorded 47. It passed while slabx was installed
(`slabx/test_while_installed.txt`). It skips now, with the reason.

## 2. Part A: the image, and a second residue the Linux build found

`deploy/models/Dockerfile` has two stages:

1. `gcc:14.2.0@sha256:b99b86a2…`, the compiler version HB-102 used. It checks the archive's
   sha256, unpacks it, and runs `gfortran -std=legacy -O0 -static`.
2. The server's own `python:3.11-slim@sha256:b7a9e5f6…`, already cached. It holds the static
   binary, the four cases and `/licenses/SLAB` (SLAB.FOR lines 1 to 20). It runs the gate
   (`deploy/models/check_cases.py`) through the shipped driver and binary, as uid 10001, and
   has no compiler.

The only network was pulling the gcc base layer.

**The first build failed its own gate.** `build_models_image.log` is the final, passing build.
The failing run printed:

```
PR1 line 352 field 10: 5.28E-07 / 5.09E-07 (19.00 units)
PR1 line 353 field 10: 5.35E-07 / 5.17E-07 (18.00 units)
```

HB-102's macOS build reproduced those two values. The Linux build (glibc's libm) does not. They
are in the PR1 z = 0 plane table at y/bbc = 2.5, about 9E-07 of the row's centreline value
(5.93E-01). The column is cc(x) (erf(ya) - erf(yb)), and SLAB's `errint` returns real*4
(SLAB.FOR line 3016: `real*4 x,erf,erfc`). No other routine declares a precision. So far out on
the tail, the value is the difference of two single-precision numbers near 1, at the platform's
rounding. The reference column itself is not monotone there: OUTPR1 lines 340 to 343 read
4.36E-07, 4.53E-07, 4.50E-07, 4.46E-07.

The gate now exempts a plane-table value below 1E-05 of its row's centreline, in both files
(`CANCELLATION_RESIDUE_RATIO`, about 100 times real*4's epsilon). This is a second residue of
the kind HB-102 already exempts (x = 0). The gate prints every exemption. In the passing build
these are the five x = 0 residues and these two, all in PR1. It was checked to still pass
HB-102's four macOS outputs and to fail a seeded value two units off
(`test_models_image.py (a test held privately)`). The change is recorded here because a gate loosened after a
failure must say so.

**The two routes** (`routes_and_demo.txt`). The image and the local binary run the same
`slab_driver.run_deck`.

| case | lines that differ | values outside tolerance | bytes identical |
|---|---|---|---|
| PR1 | 42 | 0 | no |
| PR2 | 0 | 0 | yes |
| PR3 | 0 | 0 | yes |
| PR4 | 5 | 0 | no |

The local binary here is a macOS build, so this is libm against libm. Byte identity holds only
for the same binary, which on a Linux host is the image's static binary taken out with
`docker cp`. `test_the_two_routes_agree` asserts identity there and the tolerance here.

## 3. Part B: the client's choices, each grounded

* **AS for a jet.** The guide, section 3.1.3.3 (PDF p. 56, read from the rendered page because
  the text layer drops the formula), defines AS = RHOSL A_r / rho_m, with rho_m = 1 /
  [(1 - CMEDO)/RHOS + CMEDO/RHOSL] and RHOS = WMS P_a / (R_c TBP). A_r is "the actual area of
  the rupture or opening". So the hole's area enters AS and never is AS. A check on PR2: its
  AS of 0.93 m2 is the flashed area of a 0.0070 m2 hole, about 94 mm across, which is Desert
  Tortoise's orifice size.
* **SPB, SPC.** SLAB's form is p/p_atm = exp(spa - spb/(T + spc)), with spa = spb/(tbp + spc)
  (SLAB.FOR lines 315 and 2282; guide PDF p. 53). The pack's NIST Antoine rows map onto it as
  SPB = ln 10 B and SPC = C. But they do not reproduce PR4's own SPB 1978.34 and SPC -27.01
  (they give 1221.73 / -64.639 or 2233.49 / -12.791). They also give 0.92 to 0.97 atm at the
  pack's chlorine TBP, where SLAB forces 1 atm (`antoine_vs_pr4.txt`). So the client takes the
  default, -1 and 0, as PR1 and PR3 do.
* **HS for a jet: 0.** No height above ground is held for HB-110's bottom seam. ALOHA enters 0
  "if the chemical is released at ground level" (epa-aloha-users-manual-2007 p. 132). The value
  is labelled.
* **ZP: 0 m.** ALOHA's level of concern is "a threshold concentration of the gas at ground
  level" (p. 16).
* **TAV: 3600 s.** That is the ERG's 60-minute AEGL-2 basis (DN-020 section 3.2). The level is
  the pack's AEGL-2 cell at TAV/60 minutes: chlorine 2.0 ppm, "AEGL 2 2.8 2.8 2.0 1.0 0.71",
  epa-aegl-compiled-2018 p. 43. TAV is a configuration value; 600 s gives the 10-minute cell.
* **XFFM: 10,000 m**, PR4's own. A level still exceeded at the last row is `beyond_table`.
* **Not defaulted, so an `error`:**
  * CPS for UN1017, UN1977 and UN1005 (ADDENDUM-01 section 3);
  * the LPG proxy;
  * relative humidity. The brief's `Ambient` sets `rh_pct=None`, so every live run errors here
    until the weather carries it.
* **The footprint's shape is faithful.** For PR4 at 1E-04 on the 1 m plane it is two polygons.
  The jet rises above 1 m between 1.49 and 1.77 m (the centreline falls to 5.89E-06) and comes
  down again.

**End to end on the image route** (`routes_and_demo.txt`, part 2):

* HB-110's chlorine, 9,000 kg, two-phase. The live client returns the CPS error.
* With PR4's CPS put in as a labelled test value, the source term is 62.5 kg/s for 144 s, with
  aerosol fraction 0.827 and AS 0.1965 m2.
* At AEGL-2 60 min (2.0 ppm), D stability, 3 m/s, the footprint reaches 6,090 m downwind with a
  379 m half-width, as one polygon.

## Files

* `slabx/`: the slabx harness, its per-row and summary output, and the 5-percent verdict.
* `tools/antoine_vs_pr4.py`: the pack's Antoine rows against PR4's SPB and SPC.
* `tools/guide_grep.py`: searches the kit's parse of the guide.
* `tools/routes_and_demo.py`: the two routes, and chlorine end to end.
* `build_models_image.log`: the passing build.
* `red_first.txt`: the client tests before the module existed.
* `gate_tail.txt`, `verify_tail.txt`, `build_deck.txt`: the gate, `seldon verify` and the deck
  build.
