# HB-102 Part B: the held SLAB and DEGADIS archives, inventoried, built and run

Everything was unpacked and built under `/tmp/hb102/`, never under the repository. The scripts
that did it are in this directory: `run_slab.sh`, `run_degadis.py`, `compare_outputs.py`, and the
shims in `degadis_shim/`. Their logs and outputs are in `runs/`.

## 1. Toolchain (step 3)

`/opt/homebrew/bin/gfortran`: **GNU Fortran (Homebrew GCC 14.2.0_1) 14.2.0**, on macOS (Darwin
25.5.0), arm64. No other Fortran compiler was found (`f77`, `f95`, `ifort`, `ifx`, `flang` and
`flang-new` are absent). Nothing was installed.

## 2. Archives

| doc_id | file | sha256 (zip) | contents |
|---|---|---|---|
| epa-slab-code | corpus/raw/epa-slab-code.zip | in `docs/sources/manifest.tsv` | `SLAB/`: `SLAB.FOR` (3,569 lines), `Slab.exe` (a DOS/Windows binary, not run), `SLAB.RME` (139 lines), `INPR1`-`INPR4` and `input` (test inputs), `OUTPR1`-`OUTPR4` (reference outputs, CRLF), `slabbat.bat`, `SLABfc.bat` |
| epa-degadis-source | corpus/raw/epa-degadis-source.zip | in `docs/sources/manifest.tsv` | 83 Fortran files (`*.FOR`, one `DEG1.for`; 23,107 lines in all, the largest `DEGINP.FOR` 2,283, `JETINT.FOR` 1,706), 5 `*.PRM` include files, 10 `make_*.mak` files (Intel `ifort`/`nmake`), `RecompilingInst.pdf` |
| epa-degadis-testcases | corpus/raw/epa-degadis-testcases.zip | in `docs/sources/manifest.tsv` | five cases (B9, B9T, EX1, EX2, EX3): batch files, inputs (`*.IN`, `*.INP`, `*.ino`, `EXAMPLE.ER1`-`ER3`, `EXAMPLE.GAS`) and reference outputs (`*.lis`, `*.out`, `*.vel`, `*.ind`, `*.tr2`, `*.TR3`, `*.scl`, `*.PSD`, `*.OBS`; plus `B9.OLD`, `B9.PLT`, `B9.TEC`, `B9.C`, `B9.I`, `B9.SLI`, `B9.DAT`, made by post-processors not in the source archive) |

Full file lists with line and byte counts are in `runs/archive_listing.txt`.

### Executables DEGADIS builds (from the makefiles and `RecompilingInst.pdf`)

`DEGINP` (interactive input, ground-level plume), `DEG1` (source), `DEG2` (transient
observers), `DEG2S` (steady-state), `DEG3` (sort), `DEG4` (dose), `JETINT` (interactive input,
vertical jet), `JETPLUIN`, `JETPLU` (jet/plume), `DEGBRIDG` (jet to ground-level bridge).

### Licence statements inside the archives

- **SLAB** (`SLAB.FOR`, lines 1-20, and again at line 3564):
  > (C) Copyright 1990 the Regents of the University of California. All Rights Reserved. This
  > work was produced under the sponsorship of the U.S. Department of Energy. The Government
  > retains certain rights therein. The user may copy and distribute the SLAB program or include
  > the SLAB program, in whole or in part, in another computer program provided that the
  > following conditions are met: 1. No fee may be charged for copying or distributing the SLAB
  > program or any part thereof. 2. The SLAB program may not be distributed, in whole or in part,
  > as part of any commercial product. This computer program is provided "as is".

  So SLAB is **not** a US Government work in the 17 U.S.C. 105 sense. It is UC copyright under
  these two conditions. The 1991 evaluation's "public domain model" (PDF p94 / 5-32) is EPA's
  description, not the code's licence.
- **DEGADIS** (in 8 source files, e.g. `DEG2.FOR` lines 34-52): a University of Arkansas
  disclaimer of warranty and liability for work "sponsored by the U. S. Coast Guard and the Gas
  Research Institute". There is no copyright notice and no licence grant anywhere in either
  DEGADIS archive (`grep -il copyright` over both: no hits). The readme (`epa-degadis-readme`
  PDF p1) adds that "A Degadis software package for a PC is also available from the Gas Research
  Institute for a fee".

## 3. Input and output formats, as the manual and readme describe them

**SLAB** (SLAB user's guide, `epa-slab-users-guide-1990`, PDF p49 / printed 43 to PDF p51 / 45;
SLAB.RME). The input file name is fixed as `INPUT` and the output as `PREDICT`, and `PREDICT` is
opened `status='new'` (SLAB.FOR:177-178). The guide: "There are 30 possible input parameters ...
The first two input parameters (IDSPL and NCALC) use an I5 integer format. The remaining input
parameters all use a floating point format with 10 characters". Table 1 order: IDSPL, NCALC;
WMS, CPS, TBP, CMEDO, DHE, CPSL, RHOSL, SPB, SPC; TS, QS, AS, TSD, QTIS, HS; TAV, XFFM, ZP(1-4);
Z0, ZA, UA, TA, RH, STAB, ALA. IDSPL takes four source types: "1—evaporating pool release,
2—horizontal jet release, 3—vertical jet or stack release, and 4—instantaneous or short duration
evaporating pool release". In the distributed inputs, a line `-1.` after the met block ends the
problem. The output is fixed-format text: the problem input, the derived properties, then
tables of instantaneous and time-averaged cloud parameters and concentrations by downwind
distance x and crosswind ratio y/bbc.

**DEGADIS** (`epa-degadis-readme`, PDF pp. 6-12). There are two input routes. (a) Jet releases:
`JETINT` (interactive) writes `RUN_NAME.IN`, and `JETPLUIN`/`JETPLU` read it: TITLE1-4; U0 Z0;
ZR; INDVEL ISTAB RML; TAMB PAMB RELHUM; TSURF; GASNAM; GASMW; AVTIME; TEMJET; GASULC GASLLC
GASZZC; INDHT CPK CPP; NDEN (−1 isothermal-as-air, 0 nonisothermal, >0 that many density
triples follow); ERATE; ELEJET DIAJET; TEND; DISTMX. When the jet touches down, `DEGBRIDG`
writes the ground-level `.INP`. (b) Nonjet (ground-level) releases: `DEGINP` (interactive)
writes `RUN_NAME.INP`: TITLE1-4; U0, Z0, ZR; ISTAB; OODIST, AVTIME; INDVEL, RML; TAMB, PAMB,
HUMID, RELHUM; ISOFL, TSURF; IHTFL, HTCO; IWTFL, WTCO; GASNAM; GASMW, GASTEM, GASRHO; CPK, CPP;
GASULC, GASLLC, GASZZC; [NP rows of mole fraction, concentration, density, enthalpy,
temperature]; YCLOW; GMASS0; NT rows of (PTIME, ET, R1T, PWC, PTEMP, PFRACV); CHECK4; TINP. For
steady state, NT = 4 with the times 0, 60230, 60231 and 60232 s. Numerical parameters come
from `RUN_NAME.ER1`/`.ER2`/`.ER3`, copied from `EXAMPLE.ER*`. The program chain is DEG1 then
DEG2S (steady state), or DEG1, DEG2 and DEG3 (transient). Each program writes its own files:
`.scl`, `.tr2`, `.sr3`, `.TR3`, `.PSD`, `.OBS`. The batch files concatenate them into `.lis`.

## 4. The test problems

SLAB (inputs `INPR1`-`INPR4`; each run's echo of its own input, `runs/slab/nuout*`):

| case | IDSPL | material (WMS, kg/mol) | release |
|---|---|---|---|
| PR1 | 1 evaporating pool | methane, 0.016043 (Burro-like LNG) | QS 117 kg/s, AS 657 m², TSD 107 s |
| PR2 | 2 horizontal jet | ammonia, 0.017031 (Desert Tortoise-like) | QS 107.87 kg/s, AS 0.93 m², TSD 381 s, HS 1.00 m, CMED0 0.81, TS 239.57 K |
| PR3 | 4 instantaneous | methane, 0.016043 | QTIS 6,000 kg |
| PR4 | 3 vertical jet | chlorine, 0.070906 | QS 3.33 kg/s, TSD 300 s |

DEGADIS (`epa-degadis-readme` PDF p2-3): B9, "steady state, ground-level plume" (Burro 9); B9T,
"transient, ground-level plume"; EX1, a "steady state, vertically oriented jet that does not
return to ground level" (methyl isocyanate); EX2, the same with touchdown and "subsequent
ground-level plume" (Enid, Oklahoma ammonia pipeline); EX3, as EX2 "using a simplified
relationship between contaminant concentration and air mixture density". DEG4 (dose), DEG4S,
DEG4MW, and the interactive DEGINP and JETINT are built but no held test case exercises them.

## 5. Builds and runs (step 5)

### SLAB: builds unmodified, reproduces all four test cases

`gfortran -std=legacy -O0 -o slab SLAB.FOR` → exit 0. The only diagnostic is the linker's
`overriding deployment version` note; there are no Fortran warnings (`runs/slab/compile.log`).
Each case was run as `slabbat.bat` runs it (copy `INPRn` to `input`, run, rename `predict`) and
compared with `OUTPRn` after stripping CR (`runs/slab/diff_OUTPRn.txt`) and number by number
(`runs/slab/compare_OUTPRn.json`). Every run exited 0. Line counts are identical (908, 523, 454,
453).

| case | lines differing | numeric tokens differing (excluding signed zero) | max relative difference | signed zeros (0.00E+00 vs -0.00E+00) |
|---|---|---|---|---|
| PR1 | 114 | 17 | 0.562 (see below); next largest 0.0085 | 102 |
| PR2 | 1 | 1 | 0.0012 | 0 |
| PR3 | 60 | 0 | 0 | 60 |
| PR4 | 10 | 11 | 0.0075 | 0 |

Every difference is one unit in the third printed significant figure (for example `9.21E+01`
against `9.20E+01`, or `3.77E+03` against `3.78E+03`), with one exception. In PR1, five tokens
differ by 56 percent: the cloud-centre coordinate `x` printed as `7.63E-06` (reference) against
`3.34E-06` (here), on the row of a table whose neighbouring `x` values are ±6.29E+00. This is the
value SLAB.RME itself documents as varying between builds ("2.38E-06 vs 7.63E-06 ... The
differences are caused by executing 16-bit vs 32-bit programs"). It is a rounding residue of
x = 0. **Finding: SLAB compiles unchanged under gfortran and reproduces its four distributed
test outputs to the printed precision.**

### DEGADIS: does not build unmodified; with platform shims and three syntax edits it builds but DEG1 misreads one input; with one further input-routine edit it reproduces all five test cases

`run_degadis.py` makes five builds of all ten executables. The `make_*.mak` flags were translated
to gfortran: `/noauto` → `-fno-automatic`; `/fp:strict` → `-O0` with no fast-math; `-std=legacy`
added. Per-build logs are `runs/degadis/compile_<build>_<exe>.log`; the summary is
`runs/degadis/summary.json`.

| build | what changes | result |
|---|---|---|
| unmodified | nothing | **all 10 executables fail.** `RUNNAME.FOR` calls Microsoft FORTRAN 5.0's three-argument `GETARG(n, buffer, status)` ("Too many arguments in call to 'getarg'"); `DATTIM.FOR` calls Microsoft's `GETTIM`/`GETDAT` (undefined symbols); `DEG1.for` ends in a DOS end-of-file byte 0x1A ("Non-numeric character in statement label"); `TUPF.FOR` declares `FUNCTION TUPF` and `FUNCTION TDNF` with no argument list ("Expected formal argument list") |
| shimmed | `degadis_shim/RUNNAME.f` replaces `RUNNAME.FOR` (`GET_COMMAND_ARGUMENT`); `MSCLOCK.f` supplies `GETTIM`/`GETDAT` from `DATE_AND_TIME`; `SYSTEMQQ.f` supplies Intel's `SYSTEMQQ` (DEGBRIDG calls it once, as `SYSTEMQQ('exit /b')`) | 8 of 10 build; DEG1 (the ^Z byte) and DEG2 (TUPF) still fail |
| patched | shimmed, plus three byte-exact syntax edits (`DIALECT_EDITS`): drop the trailing 0x1A from `DEG1.for`; `FUNCTION TUPF` → `FUNCTION TUPF()` and the same for `TDNF` (their only caller, `SSSUP.FOR:112-113`, already writes `TUPF()`, `TDNF()`) | all 10 build, 24-199 warnings each. The jet cases reproduce. **DEG1 prints `Air entrainment coefficient used: 0.000` where the reference prints `0.590`**, and every ground-level output differs (table below) |
| patched_packed | patched, plus `-fno-align-commons` | DEG1 fails: "Equivalence for 'epsilon' does not match ordering of COMMON 'error'" (`ESTRT1.FOR:30`) |
| ported | patched, plus two edits to `ESTRT1.FOR` (`PORT_EDITS`): remove the `EQUIVALENCE` of `RLBUFI(1)`, `RLBUFI(2)` onto COMMON `/ERROR/` `CRFGER`, `EPSILON`, and assign `crfger = rlbufi(1)`, `epsilon = rlbufi(iiiend)` once `RLBUFI` is read | all 10 build; **all five test cases reproduce** (table below) |

**Diagnosis of the patched build's 0.000.** `ESTRT1.FOR` reads the `.ER1` numerical parameters
into local arrays that are `EQUIVALENCE`d onto COMMON `/ERROR/`. Under gfortran's default COMMON
alignment, `ESTRT1` pads `/ERROR/` by 20 bytes before `CRFGER`, where every other unit pads 4
(the build's `-Walign-commons` warnings: `ESTRT1.FOR:30:13 Padding of 20 bytes required before
'crfger'`; every other warning for `/ERROR/`, 4 bytes). So `EPSILON`, the air-entrainment
coefficient read from `EXAMPLE.ER1` (`epsilon 0.59`), is stored at one offset and read back as 0
by `HEAD`, `DEG1`'s source routines and the rest. Packing the COMMON (Microsoft FORTRAN's layout)
is rejected by gfortran's EQUIVALENCE ordering check. The code therefore depends on a COMMON
layout that gfortran gives in neither mode. **Finding: DEGADIS 2.1 as distributed does not build
under gfortran. With platform shims and syntax-only edits it builds, but it silently runs the
ground-level stage with a zero air-entrainment coefficient. That is a wrong answer with exit
code 0.** The `ported` build is outside the task's "recorded, not fixed" line. It was made only to
learn whether anything else stands between the code and its test cases: nothing does. Its edit
is in `run_degadis.py` (`PORT_EDITS`), applied only under `/tmp`.

Test cases, run in the order of their `.bat` files (EX1: `jetplu`, `degbridg`; EX2, EX3: `jetplu`,
`degbridg`, `deg1`, `deg2s`; B9: `deg1`, `deg2s`; B9T: `deg1`, `deg2`, `deg3`). Every program
exited 0 in both the patched and the ported build. Each produced file with a distributed
counterpart was compared after stripping CR and the date-time stamp lines, which the `.bat` files
say will differ, and after dropping the DOS 0x1A byte that `copy a+b` appends to the reference
`.lis` files. `.PSD` files are list-directed output: the reference was wrapped at 80 columns with
15 digits, and gfortran writes one 17-digit record. They are compared as flattened number
streams. Full table: `runs/degadis/comparison_table.md`.

| build | jet stage (`.out`, `.vel`, `.ind`, `.INP`; EX1-3) | ground-level stage (`.tr2`, `.scl`, `.TR3`, `.OBS`, `.PSD`, `.lis`; EX2, EX3, B9, B9T) |
|---|---|---|
| patched | identical, or equal values printed differently (`0.000000000000000E+000` vs `0.0000000000000000`); max relative difference 2.8e-12 | **does not reproduce**: B9 `.tr2` 82 lines against 73; B9T `.scl` 512 against 206, `.tr2` 364 against 134, `.PSD` 17,303 numbers against 17,321; B9T `.TR3` 31 tokens off by >1%, max 15%; `.OBS` max 14%; EX3 `.tr2` max 8.4% |
| ported | as patched | **reproduces**: same line and token counts in every file; max relative difference 8.1e-07 (`b9t.tr2`), 3.5e-10 (`b9t.PSD`); `b9t.OBS` and `b9t.TR3` byte-identical apart from stamps |

The readme's own standard for a successful run (`epa-degadis-readme` PDF p5-6) allows "date and
time differences, ... the same values printed differently such as 0.005 versus .005, and/or ...
very minor differences in values such as 12.3456789 versus 12.3456791". The ported build meets
it. The patched build does not.

One platform note: on the EX1 path (the jet never touches down), DEGBRIDG shells out to DOS
`copy` and `del`. Here they print `sh: copy: command not found`. The `.lis` the `.bat` expects is
made by the driver instead, as `ex1.bat` itself does (`runs/degadis/cases_*/run_ex1_degbridg.stdout`).
