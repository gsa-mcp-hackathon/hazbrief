# HB-102 Part A: the 1991 evaluation, read

**Document.** `epa-dense-gas-evaluation-1991` (corpus/raw/epa-dense-gas-evaluation-1991.pdf, sha256
`2c467e8f0f04cb41bc6524bd646726e575444d99ef5dedc157bb5642e5b4eaad`, 114 PDF pages, the SCRAM copy
`DenseGasEvaluations.pdf`).

**Correction to the task's premise.** The task names it "Hanna, Chang and Strimaitis". The held
document is a different report: *Evaluation of Dense Gas Simulation Models*, James G. Zapert,
Richard J. Londergan and Harold Thistle, TRC Environmental Consultants, for EPA OAQPS, EPA
contract 68-02-4399, report **EPA-450/4-90-018, May 1991** (title page PDF p1; report-data page
PDF p113, "5. REPORT DATE May 1991"). Hanna, Chang and Strimaitis's comparison is not held. This
file reads what is held.

**How it was read.** The PDF is a scan with no text layer: `pdftotext -layout` returns 0
characters on all 114 pages. The corpus parse (`the corpus graph (held privately)
epa-dense-gas-evaluation-1991.json`, docling OCR) drops runs of words on many lines, so it was
used only to map headings to pages (`dump_parsed_pages.py`). Every quotation below was re-read
from a 300 dpi rendering OCR'd by tesseract 5.5.0 (`ocr_pages.sh`). PDF pages rendered and OCR'd:
11, 12, 15, 16, 37, 38, 41, 42, 51, 52, 53, 57-61, 63, 67-71, 74, 76-78, 80, 83-98, 106-109.
Every number in a table below was transcribed by eye from the rendered page image, not from OCR:
PDF pp. 68, 70, 76, 78, 83, 85, 87, and p. 90 (Table 5-8, printed sideways, rotated before
reading). OCR artefacts (stray `|`, `:`, `.`) are removed from quotations; the words are the
page's own.

Citation form: **PDF page / printed page**.

## 1. Models evaluated and field trials used

- Models: "two public domain models (DEGADIS and SLAB) and five proprietary models (AIRTOX,
  CHARM, FOCUS, SAFEMODE, and TRACE)" (PDF p12 / 1-2). Versions: "DEGADIS Version 2.1 was used
  for this evaluation. It includes the Ooms module for predicting the trajectory and dilution of
  an elevated dense gas jet" (PDF p15 / 2-3). SLAB carries no version number in the report. The
  other versions are "CHARM Version 5", "TRACE II" and "FOCUS Version 1.0" (PDF p15 / 2-3).
  Considered and not evaluated: HEGADAS, MESOCHEM, EAHAP. ALOHA appears in Table 2-1's
  list of models considered (PDF p14 / 2-2) and is not evaluated.
- Field trials: three, all continuous releases. "controlled releases of ammonia (Desert
  Tortoise), liquefied natural gas (Burro), and hydrofluoric acid (Goldfish)" (PDF p12 / 1-2).
  - Desert Tortoise NH3 (1983), tests 1, 2 and 4: pressurized horizontal releases, 14.9 to
    60.3 m³ at 7.0 to 10.3 m³/min, arcs at 100 m and 800 m (PDF p21 / 3-3; PDF p22 / 3-4).
  - Burro LNG (1980, China Lake), tests 3, 5 and 8, spills onto water, arcs at 57, 140, 400 and
    800 m (PDF p22 / 3-4; Table 3-1, PDF p25 / 3-7).
  - Goldfish HF (Blewitt et al., 1987), tests 1 to 3: horizontal liquid jets from heated, pressurized storage,
    arcs at 300, 1,000 and 3,000 m (PDF p28 / 3-10; PDF p30 / 3-12).
- **Not used:** Coyote, Maplin Sands and Thorney Island. The report's database is EPA's MESS
  archive. It says MESS holds six air-toxics databases and that the three above were chosen
  because they "involved dense gas releases that have similar source scenarios (continuous
  releases)" (PDF p19 / 3-1).
- Measures (Table 4-9, PDF p60 / 4-28): average difference of maximum values (obs − pred) with
  95 percent confidence interval; fractional bias of maximum values; average difference of
  half-width values; RMS error of maximum values; number within a factor of 2; Pearson
  correlation (all distances combined only). The report prints **no geometric mean bias and no
  geometric variance**.
- Sign of the fractional bias, as the report applies it: "The fractional bias of -0.29 for
  TRACE indicates overprediction by a factor of 1.34" (PDF p67 / 5-5). That is
  FB = 2(O − P)/(O + P): negative means the model over-predicts, and |FB| = 0.67 means a factor
  of 2 ("fractional bias values greater than 0.67 (exceeding a factor of 2 difference ...)",
  docling text of PDF p69 / 5-7).
- Averaging time: "all of these models were run with the averaging time specified as the
  release duration" (PDF p58 / 4-26). Model predictions are compared with the 1 m samplers; DEGADIS
  gives ground level only (PDF p57 / 4-25).

## 2. SLAB and DEGADIS statistics, as printed

Concentrations in ppm; half-widths in m. "—" means the report prints no value in that cell.

### Desert Tortoise NH3: Table 5-1 (maximum concentration, PDF p68 / 5-6) and Table 5-2 (half-width, PDF p70 / 5-8)

| arc (N) | avg observed | model | FB | avg diff (obs−pred) | 95% CI | RMSE | within 2× | half-width obs / avg diff |
|---|---|---|---|---|---|---|---|---|
| 100 m (3) | 53,485 | DEGADIS | -1.57 | -387,762 | (275,990) | 403,366 | 0/3 | 22 / -37 |
| | | SLAB | 0.89 | 33,051 | (25,849) | 34,651 | 0/3 | 22 / 9 |
| 800 m (3) | 10,176 | DEGADIS | -0.28 | -3,310 | (5,425) | 3,966 | 3/3 | 120 / -134 |
| | | SLAB | 0.93 | 6,445 | (6,679) | 6,983 | 0/3 | 120 / 26 |
| combined (6) | 31,830 | DEGADIS | -1.51 | -195,536 | (218,050) | 285,236 | 3/6 | 71 / -86 |
| | | SLAB | 0.90 | 19,748 | (16,087) | 25,408 | 0/6 | 71 / 17 |

Correlation coefficient, combined: DEGADIS 0.926, SLAB 0.955.

### Goldfish HF: Table 5-3 (maximum concentration, PDF p76 / 5-14) and Table 5-4 (half-width, PDF p78 / 5-16)

| arc (N) | avg observed | model | FB | avg diff | 95% CI | RMSE | within 2× | half-width obs / avg diff |
|---|---|---|---|---|---|---|---|---|
| 300 m (3) | 17,112 | DEGADIS | 0.45 | 6,242 | (3,045) | 6,361 | 3/3 | 42 / -16 |
| | | SLAB | 1.11 | 12,245 | (11,782) | 13,132 | 0/3 | 42 / 16 |
| 1,000 m (3) | 2,142 | DEGADIS | — (cell blank on the page) | 707 | (999) | 814 | 2/3 | 95 / -7 |
| | | SLAB | 0.92 | 1,347 | (1,170) | 1,428 | 0/3 | 95 / 20 |
| 3,000 m (1) | 411 | DEGADIS | 0.01 | 3 | — | 3 | 1/1 | 112 / -83 |
| | | SLAB | 0.76 | 226 | — | 226 | 0/1 | 112 / -47 |
| combined (7) | 8,311 | DEGADIS | 0.44 | 2,979 | (2,736) | 4,198 | 6/7 | 75 / -22 |
| | | SLAB | 1.09 | 5,858 | (5,885) | 8,648 | 0/7 | 75 / 9 |

Correlation, combined: DEGADIS 0.994, SLAB 0.987. Table 5-4's combined row labels its units
"(ppm)" though it is a half-width; transcribed as printed. The SLAB 1,000 m FB glyph is smudged
and reads 0.92.

### Burro LNG: Table 5-5 (maximum concentration, PDF p83 / 5-21) and Table 5-6 (half-width, PDF p85 / 5-23)

| arc (N) | avg observed | model | FB | avg diff | 95% CI | RMSE | within 2× | half-width obs / avg diff |
|---|---|---|---|---|---|---|---|---|
| 57 m (3) | 140,289 | DEGADIS | -1.30 | -516,044 | (166,515) | 520,380 | 0/3 | 34 / 4 |
| | | SLAB | -0.48 | -88,711 | (82,670) | 94,748 | 1/3 | 34 / -4 |
| 140 m (2) | 51,088 | DEGADIS | -1.25 | -169,413 | — | 170,828 | 0/2 | 36 / 2 |
| | | SLAB | 0.31 | 13,688 | — | 15,175 | 2/2 | 36 / 10 |
| 400 m (2) | 18,914 | DEGADIS | -0.84 | -27,221 | — | 27,534 | 1/2 | 98 / 27 |
| | | SLAB | -0.32 | -7,086 | — | 8,853 | 2/2 | 98 / 0 |
| 800 m (3) | 8,071 | DEGADIS | -0.28 | -2,590 | (3,850) | 3,018 | 1/3 | 52 / -42 |
| | | SLAB | 0.17 | 1,238 | (3,666) | 1,926 | 3/3 | 52 / -57 |
| combined (10) | 58,508 | DEGADIS | -1.25 | -194,917 | (158,654) | 295,346 | 2/10 | 53 / -5 |
| | | SLAB | -0.35 | -24,922 | (33,037) | 52,498 | 8/10 | 53 / -16 |

Correlation, combined: DEGADIS 0.867, SLAB 0.909. Table 5-6 labels its half-widths "(ppm)";
transcribed as printed.

### Across trials: Table 5-7, average fractional bias by distance (PDF p87 / 5-25)

| distance | model | Burro | Tortoise | Goldfish | combined (all experiments) |
|---|---|---|---|---|---|
| near field (≤300 m) | DEGADIS | -1.27 | -1.55 | 0.47 | -0.78 |
| | SLAB | -0.24 | 0.87 | 1.10 | 0.58 |
| far field (>300 m) | DEGADIS | -0.88 | -0.25 | 0.37 | -0.25 |
| | SLAB | -0.03 | 0.89 | 0.93 | 0.60 |
| all distances | DEGADIS | -1.07 | -0.90 | 0.42 | -0.52 |
| | SLAB | -0.13 | 0.88 | 1.01 | 0.59 |

The MANOVA reading of Table 5-7 (PDF p88 / 5-26): "differences between near-field and far-field
fractional bias, across all experiments, are significant for DEGADIS and TRACE, but not for AIRTOX
and SLAB", and "Results indicate significant differences in fractional bias for DEGADIS and SLAB,
compared to TRACE". The report's own caution: "Because the size of the data set is extremely
limited (three experiments per data base), results should be viewed with caution."

### Per test: Table 5-8, observed and predicted centreline maximum (ppm) and FB (PDF p90 / 5-28)

| test | arc (m) | observed | DEGADIS | DEGADIS FB | SLAB | SLAB FB |
|---|---|---|---|---|---|---|
| DT1 | 100 | 42,483 | 288,000 | -1.49 | 18,800 | 0.77 |
| DT1 | 800 | 6,975 | 7,198 | -0.03 | 2,980 | 0.80 |
| DT2 | 100 | 68,664 | 469,740 | -1.49 | 21,100 | 1.06 |
| DT2 | 800 | 8,991 | 13,760 | -0.42 | 3,840 | 0.80 |
| DT4 | 100 | 49,307 | 566,000 | -1.68 | 21,400 | 0.79 |
| DT4 | 800 | 14,562 | 19,500 | -0.29 | 4,374 | 1.08 |
| G1 | 300 | 25,473 | 17,500 | 0.37 | 6,520 | 1.18 |
| G1 | 1000 | 3,098 | 2,321 | 0.29 | 1,340 | 0.79 |
| G1 | 3000 | 411 | 408 | 0.01 | 185 | 0.76 |
| G2 | 300 | 13,347 | 8,050 | 0.50 | 4,490 | 0.99 |
| G2 | 1000 | 1,287 | 1,103 | 0.15 | 600 | 0.73 |
| G3 | 300 | 12,515 | 7,060 | 0.56 | 3,590 | 1.11 |
| G3 | 1000 | 2,042 | 881 | 0.79 | 445 | 1.28 |
| B3 | 57 | 74,000 | 631,000 | -1.58 | 199,000 | -0.92 |
| B3 | 140 | 54,640 | 246,000 | -1.27 | 34,400 | 0.45 |
| B3 | 400 | 3,321 | 26,400 | -1.55 | 5,100 | -0.42 |
| B3 | 800 | 1,167 | 3,760 | -1.05 | 1,180 | -0.01 |
| B5 | 57 | 63,478 | 485,000 | -1.54 | 160,000 | -0.86 |
| B5 | 140 | 47,535 | 195,000 | -1.22 | 40,400 | 0.16 |
| B5 | 800 | 2,236 | 6,723 | -1.00 | 1,820 | 0.21 |
| B8 | 57 | 283,390 | 853,000 | -1.00 | 328,000 | -0.15 |
| B8 | 400 | 34,507 | 65,870 | -0.62 | 46,900 | -0.30 |
| B8 | 800 | 20,810 | 21,500 | -0.03 | 17,500 | 0.17 |

The test labels in the table's left column are partly cut off in the scan. The row order
(DT1, DT2, DT4; G1, G2, G3; B3, B5, B8) is read from the unrotated view of the same page, and
the per-arc counts match Tables 5-1, 5-3 and 5-5 (N = 3, 3; 3, 3, 1; 3, 2, 2, 3).

## 3. The report's conclusions about SLAB and DEGADIS, quoted

DEGADIS (PDF p93 / 5-31 to PDF p94 / 5-32):

> DEGADIS was the best performing model for G-HF and gave intermediate results for DT-NH3 and
> B-LNG. For DT-NH3, DEGADIS gave large overprediction of maximum concentrations at 100 m, but
> relatively good agreement at 800 m. For G-HF, DEGADIS underpredicted maximum concentrations by
> roughly a factor of 1.5 at all distances. For B-LNG, DEGADIS again gave large overprediction at
> 57 m and 140 m, but showed smaller overprediction bias at 400 m and 800 m. DEGADIS overpredicted
> cloud half-widths for both DT-NH3 and G-HF, but showed little bias for B-LNG.

> The DEGADIS model developer provided example run set-ups for the Burro and DT data bases with
> the model literature and indicated that the model had been tested on these experiments. The
> developers have also published test results simulating the Goldfish releases.

> For Desert Tortoise, the near-field overprediction indicates that DEGADIS has systematically
> underestimated the initial cloud dispersion associated with these pressurized releases.

> For the Burro LNG tests, DEGADIS is the only model which accounts for the potential entrainment
> of water from the pool into the vapor cloud, due to the vigorous boiling of the LNG spill.
> Despite this relatively sophisticated treatment, DEGADIS overpredicted maximum concentrations at
> 57 m and 140 m by more than a factor of 4.

SLAB (PDF p94 / 5-32):

> Relative to the other models, SLAB provided the best performance for B-LNG, but was one of the
> poorest performers for both DT-NH3 and G-HF. For DT-NH3, SLAB consistently underpredicted
> maximum concentrations by a factor of 2.5 at both 100 m and 800 m. For G-HF, SLAB underpredicted
> maximum concentrations consistently by a factor of 3 at all distances. For B-LNG, SLAB provided
> relatively good agreement with observed maximum concentrations at 140 m, 400 m and 800 m, with
> overprediction by a factor of 1.6 at 57 m. For cloud half-width, SLAB underpredicted for DT-NH3
> and G-HF, but showed little bias for B-LNG.

> SLAB is a public domain model and the source code is available for examination. This model has
> probably been tested against the data bases used in this evaluation.

> Systematic bias is seen in SLAB simulations of the DT and HF releases while the Burro
> simulations appear relatively successful. The primary difference in the input streams between
> these simulations is the release type. DT and HF tests were simulated as horizontal jets, and
> the predictions systematically underestimated observed values. Apparently, the SLAB jetting
> algorithm overestimates initial cloud dispersion.

The study's conclusions that name either model (section 6.0, PDF p97 / 6-1 to PDF p98 / 6-2):

> The initial characterization of the dense gas release is critical for estimating concentrations
> over distances up to 1,000 m from the source. Models which contain very similar treatment of
> atmospheric dispersion and utilize the same meteorological inputs produce concentration
> predictions which differ by more than an order of magnitude, as a consequence of such "initial
> conditions".

> Among the models evaluated in this study, none demonstrated good performance consistently for
> all three experimental programs. ... Over all three programs, two models, TRACE and CHARM,
> provided agreement within a factor of 2 for more than half of the observed and predicted maximum
> values, while DEGADIS and SLAB each provided the best performance for one experimental program.

> Given the differences in model performance obtained for the three experimental programs, and
> the small number of releases considered, it is highly uncertain how well any of these models
> might perform for any other dense gas release scenarios.

And on independence (PDF p89 / 5-27): "Any experimental data which has been used during the
development of a model does not provide an independent test of model performance."

## 4. The source term each model took, as the report describes it

DEGADIS (section 4.2.1, PDF p37 / 4-5 to PDF p38 / 4-6):

> Both experiments [Desert Tortoise and Goldfish] are characterized as jet releases. DEGADIS
> Version 2.1 models only vertical jet releases, but previous analyses (Spicer and Havens, 1988a,
> 1988b) suggested that the jet momentum had a negligible influence on predicted concentrations
> for these experiments.

> DEGADIS requires as input ordered triples consisting of mole fraction, concentration of
> chemical, and air/chemical density. Spicer and Havens calculated the density of an
> ammonia/air/water mixture as a function of ammonia mole fraction using the TRAUMA model. ...
> The Desert Tortoise and Goldfish releases were simulated as steady-state, pure chemical
> releases. The jet releases are modeled as "isothermal" because the TRAUMA module has already
> accounted for heat exchange by generating ordered triplets which are input to DEGADIS. Source
> radius for the jet releases is larger than the orifice area and represents an initial puff size
> as suggested by the model developer.

> The Burro experiments were simulated by DEGADIS using the assumption that the releases were
> non-isothermal, steady-state spills of LNG. Water transfer effects were included. The LNG pool
> size was only measured during Burro Test 9. For each Burro test included in the evaluation,
> pool area is assumed to have the same proportionality to release volume as existed in Test 9.

The release rate is an input, not computed. Table 4-2 (PDF p39 / 4-7) lists "Emission Rate
(kg/s)" for each test: DT1 81, DT2 117.3, DT4 107.9; G1 30.2, G2 10.4, G3 10.4; B3 86.4, B5
79.4, B8 112.6. These values are from the corpus OCR of that page, which was not rendered.

SLAB (section 4.2.2, PDF p38 / 4-6):

> Inputs for the SLAB model were derived primarily from the MESS Archive and experiment reports,
> and from the SLAB User's Guide. ... All the values for the chemical parameters were provided by
> the User's Guide, and there is no internal chemical library. ... The Desert Tortoise and
> Goldfish experiments were modeled by SLAB using similar assumptions. Both cases were run as
> horizontal jets in order to properly characterize the aerosol effects. Aerosol effects were
> accounted for by specifying an initial liquid mass fraction of 0.83 for ammonia and 0.8 for
> hydrogen fluoride. For the Burro tests, the releases are simulated as evaporating pool releases,
> with the release temperature specified as the boiling point temperature of LNG. For the Burro
> releases, initial mass fraction is set to zero, since the releases are evaporating pools.
> Source areas for the Burro tests were computed using the formula: A(s) = q(s)/p(s)w(s)

Table 4-3, "SLAB" input parameters (PDF p41 / 4-9). The rendered page is partly illegible; the
legible rows are given here. Release types: Horiz. jet (DT1, DT2, DT4, G1-G3); Evap. pool (B3,
B5, B8). Initial liquid mass fraction: 0.83 (DT), 0.8 (G). Release height: 0.79 m (DT), 1.00 m
(G), 0.00 m (B). Source area (m²): DT1 0.0052; G 0.0081; B3 488.1; B5 448.6; B8 632.2. Initial
chemical temperature: B 111.70 K. The source area, liquid fraction and release rate are all
supplied by the user. SLAB computes none of them from the container.

How outputs were taken (section 4.3, PDF p51 / 4-19 to PDF p53 / 4-21). For DEGADIS: "The
test-averaged concentrations required for the evaluation are provided in the DEGADIS model output.
DEGADIS assumes that the central portion of the cloud has a uniform cross-wind concentration
distribution. Outside of this region, the plume is assumed to have a Gaussian concentration
distribution." For SLAB: "The test averaged concentrations required for the evaluation are
provided in the SLAB model output as a function of effective half-width distance."

## 5. ALOHA's heavy-gas model and its lineage

From the held ALOHA manual (`epa-aloha-users-manual-2007`, text layer; the PDF page equals the
printed page):

- p. 16: "There are two separate dispersion models in ALOHA: Gaussian and heavy gas."
- p. 17: "The heavy gas dispersion calculations that are used in ALOHA are based on those used in
  the DEGADIS model (Spicer and Havens 1989), one of several well-known heavy gas models. This
  model was selected because of its general acceptance and the extensive testing that was
  carried out by its authors."
- p. 17: a heavy gas begins "behaving like a neutrally buoyant gas. This takes place when the
  concentration of heavy gas in the surrounding air drops below about 1 percent (10,000 parts
  per million)."
- p. 168 (bibliography): "Spicer, Tom and Jerry Havens. 1989. User's Guide for the DEGADIS 2.1
  Dense Gas Dispersion Model. EPA-450/4-89-019." p. 167 also lists Havens and Spicer 1990, *LNG
  Vapor Dispersion Prediction with the DEGADIS Dense Gas Dispersion Model* (GRI).
- p. 128: "ALOHA can model four types of sources. Direct ... Puddle ... Tank ... Gas Pipeline".
  The Tank dialogs (pp. 38-40) ask for tank size and orientation, chemical state and temperature,
  mass in tank, area and type of leak, and height of the opening. ALOHA then "calculates the rate
  of release ... the duration of the release, and the total amount released" (p. 40). p. 144: a
  liquefied gas "will escape through the opening directly into the atmosphere (without forming a
  puddle) as a two-phase flow of gas and aerosol".

The manual says only "based on". The held ALOHA *technical documentation*
(`noaa-aloha-technical-documentation`, section 4.4, PDF p53 / printed 45 to PDF p54 / 46) states
the differences:

> DEGADIS, in turn, is an adaptation of the Shell HEGADIS model described by Colenbrander ...;
> DEGADIS also incorporates some techniques used by van Ulden.

> Some simplifications were introduced into ALOHA-DEGADIS, making it different from the DEGADIS
> model. ALOHA-DEGADIS is limited to releases at ground level, and does not account for the
> initial momentum from a jet release. Some of the numerical methods used in ALOHA-DEGADIS have
> been simplified compared to those used in DEGADIS.

> The ALOHA-DEGADIS model is essentially the DEGADIS steady-state plume model that has been
> adapted to handle time-varying sources. For any non-instantaneous sources in ALOHA, the model
> generates a five-step release; each step is a finite-duration steady-state release.

> ALOHA-DEGADIS threat zones averaged 10% longer than those predicted by DEGADIS. ... It can be
> expected to produce peak concentration estimates for a given point that are, on average, about
> 10% greater than estimates made by the full DEGADIS model.
