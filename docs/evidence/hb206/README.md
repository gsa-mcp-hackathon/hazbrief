# HB-206: a release under one minute is classed, and Jack Rabbit II Trial 7 is run and scored

**In one line:** with the one-minute rule, hazbrief's route names its engines on Trial 7 and both ran; SLAB as the route
runs it scores better than HPAC and ALOHA on the paper's own statistics, SCICHEM (the layer a stable brief draws first)
is low at every arc, and by the rule committed before the runs the row takes the worse: **below** HPAC and ALOHA.

## The rule (protocol.md section 2; decision HBD-464)

ALOHA never models a release shorter than a minute: it models it as one minute, a steady release of the mass over that
minute, and calls that "instantaneous" (`prior_art.md` A1 to A6). No held page says which form of the critical
Richardson number ALOHA applies to a tank release floored that way, so both were evaluated before any run
(`prepared.json`): the continuous form at the one-minute rate gives Ri_c 14,564; the instantaneous form gives dense for
any source area below 5.1 km2. They agree, so the route now classes a floored release by the continuous form at its
one-minute rate, its mass unchanged (`src/hazbrief/brief/engine_rule.py`). Before this rule the route named no engine on
Trial 7 (HB-199, `docs/evidence/hb199/runs/route.json.gz`, kept as it was).

## The runs (each once, models image, no network; `runs/`)

| Unit | What | Wall time | Status |
|---|---|---|---|
| `P_scichem` | the route: 9,100 kg as 151.7 kg/s for 60 s (computed 22 s), SCICHEM at the stable 1.25 m setting, 1 s sensors on the six arcs at 0.3 m | 10,740 s | completed |
| `P_slab_rh20`, `P_slab_rh80` | the route's SLAB deck, TAV 1 s, receptor 0.3 m, RH 20 and 80 percent | 0.26 s, 0.17 s | completed |
| `S_scichem` | the comparison's source, 259 kg/s for 33.3 s (8,625 kg), as a 33.3 s release | 10,042 s | completed |
| `S_slab_rh20`, `S_slab_rh80` | the same for SLAB | 0.17 s each | completed |

The two SCICHEM units ran side by side; the SLAB units ran alone, before them (`disk.txt`).

## Arc maxima, ppm (`trial7_scores.tsv`; observed and tools: 17-model Table 5 p. 20)

| Arc | Observed | HPAC | ALOHA | P SCICHEM | P SLAB 20 % | P SLAB 80 % | S SCICHEM | S SLAB 20 % | S SLAB 80 % |
|---|---|---|---|---|---|---|---|---|---|
| 0.2 km | 72,580 | 31,372 | 52,300 | 23,260 | 56,002 | 57,028 | 29,541 | 62,180 | 61,111 |
| 0.5 km | 22,686 | 6,314 | 14,100 | 6,466 | 12,502 | 12,877 | 6,807 | 13,578 | 14,487 |
| 1 km (saturated) | 2,621 | 2,633 | 3,470 | 1,924 | 3,540 | 3,633 | 2,022 | 3,468 | 3,630 |
| 2 km | 1,417 | 1,005 | 497 | 532 | 957 | 961 | 488 | 878 | 907 |
| 5 km | 373 | 278 | 41 | 74.3 | 159 | 157 | 74.8 | 144 | 145 |
| 11 km (saturated) | 50 | 66 | 6 | 14.9 | 32.6 | 32.6 | 13.4 | none | none |

## The statistics, 0.2 to 5 km (the 17-model statistic's arcs; HB-199's code)

| Model | FAC2 | FAC5 | MG | VG | FB | NMSE | Word against HPAC | Word against ALOHA |
|---|---|---|---|---|---|---|---|---|
| HPAC | 0.60 | 1.00 | 1.73 | 1.66 | 0.82 | 2.37 | | |
| ALOHA | 0.60 | 0.80 | 2.13 | 3.59 | 0.34 | 0.35 | | |
| P SCICHEM | 0.20 | 0.80 | 2.88 | 3.69 | 1.02 | 4.19 | below | below |
| P SLAB 20 % | 0.80 | 1.00 | 1.43 | 1.32 | 0.31 | 0.26 | exceeds | exceeds |
| P SLAB 80 % | 0.80 | 1.00 | 1.41 | 1.32 | 0.29 | 0.23 | exceeds | exceeds |
| S SCICHEM | 0.20 | 1.00 | 2.74 | 3.35 | 0.88 | 2.71 | below | below |
| S SLAB 20 % | 0.80 | 1.00 | 1.44 | 1.35 | 0.22 | 0.12 | exceeds | exceeds |
| S SLAB 80 % | 0.80 | 1.00 | 1.40 | 1.33 | 0.22 | 0.13 | exceeds | exceeds |

MG is observed over predicted, so every model here under-predicts on average. The six-arc reading gives the same words
(`status.tsv`).

## The status word and why

HB-199's rule, unchanged: below where a run fails a criterion the tool meets. HPAC and ALOHA each meet Simpson's FAC2 >=
0.50 and NMSE <= 3; P's SCICHEM run fails both (FAC2 0.20, NMSE 4.19), so it is below each. P's SLAB runs meet every
criterion the tools meet and also FAC2 > 0.6, which neither tool meets, so each is "exceeds". The protocol, committed
before the runs, gives the row the worse of P's runs: **below against HPAC (BENCH-8) and below against ALOHA
(BENCH-9).** S gives no word; its words are the same as P's.

## Arrival of the arc maximum (Simpson Table 7 p. 16; no held criterion, so no word)

Relative to the observed arrival at 0.5, 1, 2, 5 and 11 km: HPAC 1.74, 1.06, 1.07, 1.00, 0.99; P SCICHEM 1.73, 1.02,
1.12, 1.01, 1.05; P SLAB (20 %) 1.91, 1.16, 1.15, 1.01, 0.99. SCICHEM's timing is as close to the observed as HPAC's.

## What stretching to one minute does here

The floor keeps the mass and spreads it over 60 s instead of 22 s. P and S differ in duration (60 s against 33.3 s) and
also in mass (the route's 9,100 kg, the tank's inventory, against the measured 8,625 kg). P over S at 0.2, 0.5, 1, 2 and
5 km: SCICHEM 0.79, 0.95, 0.95, 1.09, 0.99; SLAB (20 %) 0.90, 0.92, 1.02, 1.09, 1.11. So the longer release lowers the
peak at 0.2 km by 10 to 21 percent; from 1 km out the larger mass sets it and P is equal or higher. **At no arc do P and
S differ by more than a factor of two.** By Volume II's criterion (u T / x at most 0.6) P is instantaneous beyond 398 m
and S beyond 221 m (`prior_art.md` section 5).

## What this shows and does not

- One trial, six arcs, two saturated. SCICHEM's shortfall here (P/observed 0.20 to 0.73) is the same kind HB-176 found on
  stable trials at 212 to 800 m; it is not diagnosed here. No run was outside a factor of ten at any arc, so item 7's
  Issue was not needed.
- The SCICHEM read-out is HB-199's: 1 s sensors, the comparison's averaging time, which made each run take about 3 hours
  against the route's 4 hour bound. A brief samples at 120 s.
- **A departure from the protocol's text** (reported here, not written into it): section 3 said SLAB would give no value
  at 11 km because XFFM is 10 km. SLAB prints rows past XFFM; P's rows reach 20.2 km and give a value at 11 km, S's end at
  10.7 to 10.9 km and give none. Each run is scored on what it gave, as section 4 says.
