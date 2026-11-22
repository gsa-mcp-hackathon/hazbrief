# HB-206 protocol: a release under one minute, the rule that classes it, and Trial 7 run once by that rule

Written and committed before any run record of this task (task item 2; `test_hb206_trial7.py (a test held privately)` holds that this
file's one commit precedes every record under `runs/` by author date, and that it never changed after). Nothing below
is revised after a run. A departure found later is reported in the RESULT beside this text, not written into it.
HB-199's protocol, record and RESULT (`docs/evidence/hb199/`) are not edited: they are what the route did before this
rule.

**What was computed before this was written, and so is known to its author.** `tools/runs206.py prepare` computes,
without calling any engine, the criterion's two forms on Trial 7's release and every declared unit's input with its key
(`prepared.json`, committed with this file). Its numbers are in section 2. No engine output for Trial 7 was seen by
this session before the runs; HB-199 ran none.

## 1. What the held sources say (`prior_art.md`)

ALOHA never models a release shorter than a minute: it models it as one minute, a constant steady release of the mass
over that minute, and calls that one-minute release "instantaneous" (prior_art A1, A3, A5, A6). As an input,
"instantaneous" is the Direct source's option (A4); a tank's release reaches the dispersion models as one to five
averaged steps of at least a minute, each a finite-duration steady release (A2, A3, A7, A8). The criterion has an
instantaneous form, H = V0 / A0, which needs the source's area, and a form "for continuous or semi-continuous sources
other than the puddle source", H = sqrt(E pi / (4 rho U10)) (A9); a tank's source is a point source with no area (A8).
**No held page says which form ALOHA applies to a tank release its averaging has floored to one minute.** So the task's
third case applies: evaluate both.

SLAB's jet and SCICHEM's continuous release, as the route drives them, each take a finite duration directly (prior_art
S1 to S4, C1, C2). The comparison gave every modeller one source, Trial 7's 259 kg/s for 33.3 s (J1 to J3).

## 2. The rule

**Both forms on Trial 7's release as the route computes it** (`prepared.json` `criterion_forms`; the source term of
HB-199 section 3.1, unchanged: 9,100 kg emptied in a computed 22 s, floored to 60 s, 151.7 kg/s, the release density
after the flash 22.36 kg/m3, air 1.209 kg/m3, U* 0.1167 m/s at class E):

| Form | H | Ri_c | Class |
|---|---|---|---|
| continuous, at the one-minute rate (E = 151.7 kg/s) | 1.157 m | 14,564 | dense |
| instantaneous, V0 = 9,100 kg / 22.36 kg/m3 = 407.0 m3, at the one area the route computes for this source (the flashed jet's, 1.278 m2) | 318.6 m | 4,010,589 | dense |
| instantaneous, the largest A0 that still gives dense (Ri_c = 1) | 0.0794 mm | 1 | dense for any A0 below 5,123,685 m2 (5.1 km2) |

The two forms agree: dense, unless the source were a layer under a tenth of a millimetre spread over more than 5 km2.
So the choice does not matter here, and the rule is the task's for that case:

> **A release the source term floors to one minute (computed shorter than one minute, ALOHA's "instantaneous"
> release) is classed by the continuous form of the critical Richardson number at its one-minute rate (its mass over
> one minute), because it is modelled as a one-minute release (prior_art A5, A6: ALOHA models it as "a single
> one-minute steady-state release"). Its mass is unchanged. The criterion records that it was floored and the
> computed duration.**

The route's criterion (`engine_rule.classify`) takes this rule (task item 4), and the engines it names follow from the
class as for any release (dense under a stable class: SCICHEM's moving cloud with SLAB checking how far). The rule is
recorded as a decision (`seldon decision accept`, HB-192's route) with this section as its source and `prior_art.md`
as its receipt.

## 3. The runs, all declared now

Each is run once, in the models image, with no network (`tools/runs206.py run <unit>`); each is held as one record,
`runs/<unit>.json.gz`, with its wall time, whatever it returned. A run that does not finish is reported as that, and
gives no prediction. A run ended by a dispatcher stop is reported as "not completed, stopped by the dispatcher
(<reason>)" with the stop's numbers, is not a result, and is not scored (HB-199 ADDENDUM-02). No input is changed after
a result is seen, no run is repeated, and no factor is put on a concentration.

**P, the primary: hazbrief's route with the rule.** The source term from `docs/evidence/hb199/trial7.yaml` (HB-199
section 3.1), the release modelled as one minute (151.7 kg/s for 60 s), each engine the criterion names, at the
setting a brief takes under class E:

- `P_scichem`: SCICHEM, the request HB-199's protocol section 3 item 5 describes, byte for byte (`prepared.json`
  `units.P_scichem.input_sha256` equals HB-199's `request_sha256`, a1abcc5a...): the stable treatment (1.25 m
  vertical, 250 m top, class E's PGT layer), sensors on crosswind lines at the six arcs (41 points over max(100 m,
  x/2)) at the samplers' 0.3 m, a 1 s sensor interval, the unheld humidity, sky cover and mixing height columns
  removed, the wind at its 2 m reference height.
- `P_slab_rh20`, `P_slab_rh80`: SLAB, the deck `dense_gas.slab_input` writes for this release (TSD 60 s, QS 151.7
  kg/s, the flashed jet), with the read-out set as HB-199 set SCICHEM's: TAV 1 s (the averaging time the comparison
  asked every model for, m17 p. 4), the receptor at the samplers' 0.3 m (m17 p. 15), not a brief's level minutes at
  the ground. XFFM stays the route's 10 km, so SLAB gives no value at the 11 km arc.

**Relative humidity.** No held Jack Rabbit II source states it for Trial 7 (HB-199 `trial7_inputs.tsv`; this task's
reading of M17, SIM, Fox and Weil found none). So each SLAB run is made at two declared values, 20 and 80 percent, and
both are reported. SCICHEM's request carries none (HB-199 section 3 item 5).

**S, beside it: the same engines on the comparison's prescribed source as given** (M17 Table 3 p. 7, single source:
259 kg/s for 33.3 s, -37.4 C, vapour fraction 0.172, area 0.323 m2), every other input as P's. Both engines take a
finite duration directly (prior_art S3, C1), so S is run as a 33.3 s release, not floored: `S_scichem`,
`S_slab_rh20`, `S_slab_rh80`. S shows the engines on the inputs HPAC and ALOHA were given. **It gives no status
word.**

## 4. The statistics and the observations

HB-199's, unchanged, by `the HB-199 evidence (held privately)` (its `statistics`, `meets`, `status` and `CRITERIA`,
imported, not copied): FB, MG, NMSE, VG, FAC2, FAC5 on the observed arc maxima of M17 Table 5 p. 20, the saturated 1
and 11 km values scored as printed; the 0.2 to 5 km reading sets the word and the six-arc reading is printed beside
it; a missing prediction (SLAB's 11 km arc, or a run that did not finish) is left out of every statistic. Each run's
prediction at an arc is its arc maximum: SCICHEM's largest mean over the line's points and the run (HB-199's
`reduce`, in ppm by hazbrief's molar volume, HB-176), SLAB's time-averaged centreline concentration in the plane
nearest 0.3 m between its printed rows (HB-176's `interpolate`). SCICHEM's mean is scored because it is what a brief
draws.

## 5. The status word

HB-199 section 5's rule, unchanged, applied to each P run against each tool (HPAC, ALOHA): below where the run fails a
criterion the tool meets; exceeds where it meets one the tool fails and fails none the tool meets; otherwise equals.
P names more than one run, so **the row takes the worse of P's runs' words** (below before equals before exceeds):
SCICHEM, SLAB at 20 percent and SLAB at 80 percent. This is the task's "the status word takes the worse" carried to
every run P is made of, so that no choice among P's engines is made after the results. S's words are printed and set
nothing.

**Arrival** (HB-199 item 8): each run's time of its arc maximum (SCICHEM's sensor time; SLAB's printed time of the
maximum, between rows) beside the observed and HPAC's (Simpson Table 7 p. 16), as a ratio to the observed. No held
source states a criterion for it; it sets no word.

**A factor of ten** (task item 7): a run outside a factor of ten of the observation at any arc is not diagnosed and
not rerun; an Issue is filed with its arc values, and the score is reported as it is.

## 6. Outputs

`runs/<unit>.json.gz`; `trial7_scores.tsv` (per arc: observed, HPAC, ALOHA and every run, with ratios; the statistics
of every model on both readings, P and S side by side; arrival) and `status.tsv` (each criterion, each P run against
each tool, the row's word), both by `tools/score206.py`; `README.md` in plain words. BENCH-8 and BENCH-9 take the word
`status.tsv` gives, never "met".
