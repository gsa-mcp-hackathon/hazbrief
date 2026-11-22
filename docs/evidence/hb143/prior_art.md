# HB-143: how nearby surface stations become one point wind. The prior art, searched before any code

**Task:** HB-143 ADDENDUM-01 section 2 (the method is chosen from prior art first). The decision this replaces is
`hazbrief-mcp:HBD-275`: the method is undecided, and the inverse-distance vector mean is a candidate.
`hazbrief-mcp:HBD-220` (the base task's F5, the inverse-distance vector mean) is superseded by HBD-275. It is cited
here as history, not as the ruling this implements.
**Written:** 2026-11-09, before any code of this task (git history: this file's first commit precedes the code's).

## 1. The search, in ADDENDUM-01's order

### 1.1 `seldon prior-art search`, both arms, four queries

Each receipt file is the command's full output, in `the HB-143 evidence (held privately)`.

| Query | Internal arm (the operator's repositories) | Library arm (squiddy library graph) |
|---|---|---|
| station wind interpolation | 0 hits in 7 repositories (`internal_1_*.txt`) | 43 hits, all ML papers (context-window "position interpolation", GAN interpolation, a "Boy Who Harnessed the Wind" film list): lexical noise (`library_1_*.txt`) |
| vector averaging wind direction | 0 hits (`internal_2_*.txt`) | 46 hits, embedding averaging and stock-direction SVMs: noise (`library_2_*.txt`) |
| surface analysis objective analysis Barnes Cressman | 0 hits (`internal_3_*.txt`) | 43 hits, an "Objective Analysis Agent" class and red-teaming objectives: noise (`library_3_*.txt`) |
| representative wind for dispersion modelling site | 0 hits (`internal_4_*.txt`) | noise of the same kind (`library_4_*.txt`) |

Neither arm holds the field. The prior art is in the held corpus (1.2) and the published literature (1.3).

### 1.2 The held corpus: what wind a dispersion run expects

Page numbers are the PDF's own page index. They were found by `the HB-143 evidence (held privately)`, and its
outputs are `pages_*.tsv`.

**EPA, Meteorological Monitoring Guidance for Regulatory Modeling Applications** (`epa-mmgrma-1999`,
EPA-454/R-99-005). This is the EPA guidance ADDENDUM-01 names for representative meteorological data. It is already
held.
- Section 3.1, PDF p. 29: in steady-state applications, "measurements for a single location, somewhere near the
  source, are assumed to apply, without change, at all points in the modeling domain".
- Same page, on gridded non-steady-state applications that "blend available NWS data" over several sites: "Site
  selection for such applications (often more than one location is needed) falls in the category of network design
  and is beyond the scope of this document".
- Section 3.1.2, PDF p. 30: representativeness "is dependent on the proximity of the meteorological monitoring site
  to the 'area-of-interest'", and yet "representativeness is not simply a function of distance".
- Section 3.2.1.3, PDF p. 32: "A single well-located measurement site can be used to provide representative wind
  measurements for non-coastal, flat terrain, rural situations."
- Section 3.5, PDF p. 40, on the steady-state models, which "recognize only a single value for each input variable on
  an hourly basis": "the use of a single site is necessary. At the very least, the single site should be located as
  close as possible to the source in question."
- Section 6.2.2, PDF p. 54: the resultant vector mean, (Ve, Vn) from u sin(theta) and u cos(theta), then
  `ATAN2(Ve, Vn)`. It averages a sequence of observations at one site over time, not several sites.

**ALOHA** (`epa-aloha-users-manual-2007`; `noaa-aloha-technical-documentation`).
- User's manual, PDF p. 29: "ALOHA allows you to enter only single values for wind speed and wind direction. It then
  assumes that wind speed and direction remain constant (at any given height) throughout the area downwind".
- User's manual, PDF p. 123, on a live station during an incident: "place your SAM so that its readings will be as
  representative as possible of the whole area through which the pollutant cloud may travel".
- Technical documentation, PDF p. 12: "ALOHA uses a wind field that does not vary with time or horizontal position".

**HPAC** (`osd-ncbdp-specialized-radiological`).
- PDF p. 4: "meteorological observations are very representative of the real world at the time and location where
  the data are taken. Assuming the weather does not change, reasonable results may be obtained for a period of two to
  four hours after the surface observations are taken".
- Same page: "A single set of meteorological observations becomes less representative with distance from the
  observation site, with time from which the data are taken, around complex terrain, near sunrise and sunset, near
  weather fronts, near urban areas, and near land and/or water interfaces."

**SLAB** (`epa-slab-users-guide-1990`). Section 3.1.5.3, parsed page 60: "UA—Ambient wind speed (m/s). This is the
average ambient wind speed at the height ZA above ground level." One value, at one height.

**The 1991 evaluation** (`epa-dense-gas-evaluation-1991`). Section 3.2, Burro, printed page 3-9; the parsed text has
no page, char_span 27061-27488: "Meteorological data were collected using standard cup and vane anemometers 2m above
the ground, located at 20 stations upwind and downwind of the spill source. Wind data from the 20 cup and van
anemometers were averaged to obtain single values of wind speed and direction". The evaluation did combine stations,
but they were a dense on-site network built for the test, inside the cloud's own area. They were not airports 10 to
40 km away.

### 1.3 The published methods, through the fetcher

The fetcher's run is `prior_art_fetch.out`, with its fsynced log `prior_art_fetch_log.jsonl` and the rows drafted in
`prior_art_sources.yaml`. It refused all four, because this session's network is `api.weather.gov` alone
(`SELDON_NETWORK_ALLOWLIST`, intersected with `corpus/allowlist.txt`). Each refusal names rung 2, the browser:

| Work | Rung-2 URL | Outcome |
|---|---|---|
| Barnes, S. L. (1964), "A Technique for Maximizing Details in Numerical Weather Map Analysis", J. Appl. Meteor. 3, 396-409 | https://journals.ametsoc.org/view/journals/apme/3/4/1520-0450_1964_003_0396_atfmdi_2_0_co_2.xml | `blocked_host` |
| Cressman, G. P. (1959), "An Operational Objective Analysis System", Mon. Wea. Rev. 87, 367-374 | https://journals.ametsoc.org/view/journals/mwre/87/10/1520-0493_1959_087_0367_aooas_2_0_co_2.xml | `blocked_host` |
| Shepard, D. (1968), "A two-dimensional interpolation function for irregularly-spaced data", Proc. 1968 ACM National Conference, 517-524 | https://dl.acm.org/doi/10.1145/800186.810616 | `blocked_host` |
| EPA, Guideline on Air Quality Models (40 CFR 51 App. W, 2017), section 8.4, meteorological input data | https://www.epa.gov/sites/default/files/2020-09/documents/appw_17.pdf | `blocked_host` |

No browser tools are connected to this headless session, and the task's Spend line allows no nested session. So rung
2 waits for the Desktop thread. The three methods are cited **by title, not held**. What follows is their standard
statement, and the task's own text names them the same way ("Shepard 1968, cited by title until held"):
- Cressman's successive correction weights each station by (R² − r²)/(R² + r²) inside a radius of influence R, over
  scans of shrinking R.
- Barnes weights by a Gaussian, exp(−r²/κ), with κ set from the station spacing.
- Shepard weights by 1/r^p.

All three build a **field** (a grid analysis or an interpolated surface) from a **network**, and their one parameter
(R, κ, p) is tuned to the network's density. None is offered as the wind input of a steady-state dispersion run.

## 2. The method chosen, and why

**The record is the wind of one representative station: the nearest, by great-circle distance from the incident
point, of the N nearest NWS stations whose latest observation reports a wind within the tolerance of the brief's
hour. The other stations are not averaged in. Their winds are carried as a spread: the smallest arc that holds their
bearings and the range of their speeds. The label names the method and its source (EPA-454/R-99-005 section 3.1).**

Why this method and not the inverse-distance vector mean:
1. **Every held engine takes one wind**, as one value uniform over the area: ALOHA (UM p. 29, TD p. 12), SLAB (UA, one
   value at ZA), and the steady-state models in EPA's guidance (section 3.5: "a single value for each input variable").
   The brief's puff and SLAB deck are steady and uniform in the same way. The input the prior art describes is a
   representative measurement, not a combined one.
2. **EPA's guidance says how that measurement is chosen**: one site, as close to the source as possible (section 3.5,
   p. 40), with the caveat that representativeness "is not simply a function of distance" (p. 30). It sends
   multi-site blending to gridded, non-steady-state processors and to network design, "beyond the scope" (p. 29).
3. **The weighted-mean methods are field analyses** (1.3). With the 2 or 3 stations an incident has within reach,
   10 to 40 km apart and often in different terrain, their weights reduce to a weighted mean. That mean is a wind no
   anemometer measured, and it hides disagreement. Two stations reading 090 and 270 at equal distance average to a
   calm that neither reported, and the record would orient the footprint on it.
4. **The spread answers HPAC's warning** (p. 4: an observation "becomes less representative with distance ... around
   complex terrain"). The reader sees whether the nearby stations agree, without a second wind on the map. HB-133's
   one wind record (`hazbrief-mcp:HBD-307`) is kept.
5. **Where combining is done, it is done on a dense on-site network** (the 1991 evaluation's Burro tests: 20
   anemometers around the spill). The NWS stations an incident sees are not that network.

ADDENDUM-01 section 2 named this outcome: "If it supports a single representative station with the others shown as
a spread, the record carries the nearest station's wind and the spread (min and max bearing and speed across the
stations), and the label says so."

**What carries over from Part A as written.**
- The N nearest stations (configuration, default 3).
- The freshness rule: the tolerance, `weather.observed.tolerance_minutes`, default 90.
- A calm observation is a true observation. It enters the spread as speed 0 with no bearing, and a calm
  representative station gives a calm record (Issue `473bdfeb`).
- The degrade to forecast below the minimum. The minimum is now 1 station, since the method needs one; see section 3.
- **The 350/010 test stays**, though the method is single-station. The spread's arc must be the 20 degrees through
  north, not the 340 degrees through south. That is the same wrap that a direct average of bearings gets wrong.

## 3. The departures this choice makes, stated for the Desktop

- **From the base task's item 2**, as ADDENDUM-01 allows: no weights and no mean. The record carries the stations, the
  representative one, the spread and the configuration.
- **From the base task's "minimum 2 for a mean"**: the minimum is 1 (`weather.observed.min_stations`). The reason is
  the method's own: a representative station is one station.
- **From `hazbrief-mcp:HBD-211`'s `observed`** ("the archived observation for a stated past hour, degrading with a
  label rather than falling back"). This task builds the **latest** observations of live stations, not an archive
  for a past hour. Item 3 of the base task **falls back to the forecast** below the minimum, which HBD-211 forbids. It
  is built as the task states, the fallback is printed on the first screen, and an Issue carries the conflict to the
  Desktop. DN-019 ADDENDUM-01 is not edited.
