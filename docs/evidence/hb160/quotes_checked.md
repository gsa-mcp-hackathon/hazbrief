# HB-160 Part A item 5: every quotation the report attributes, checked against the held text

**Report:** `perplexity-report-scipuff-uncertainty-2026-11-10` (Perplexity, saved by the operator 2026-11-10 19:48
EST). It is a list of leads, never a source. Nothing below is cited from it; each sentence is read in the held work.

**Method.** Every sentence is listed with its held file in `quotes.yaml`. `tools/locate_quotes.py` (HB-156's tool,
with one rule added for the space pdftotext puts before a subscript, "σ y") matched each in the held bytes after
folding whitespace, line-end hyphenation and typographic quotes, page by page. Its output, `locate_quotes.txt`, gives
the PDF page and the file's sha256 for each: 20 of 20 found. The formulas in ALOHA's sections 4.3.1 and 4.5.3 were
read from the rendered pages (`page_images/techdoc-51.png`, `techdoc-65.png`), because pdftotext breaks them across
lines. Sykes's slide was read from its rendered page too, for its overbars; that image is not committed, because the
workbook is NCSU's, all rights reserved (it is cited and quoted, not reproduced).

**Held files** (sha256 prefix): ALOHA 5.4.4 Technical Documentation, NOAA TM NOS OR&R 43, November 2013
(`noaa-aloha-technical-documentation`, `2f766395…`, held since HB-22 from response.restoration.noaa.gov; NOAA's
repository serves the same memorandum as noaa/2669, which the report cites; printed page = PDF page − 8 in chapter
4). ALOHA User's Manual, February 2007 (`epa-aloha-users-manual-2007`, `a3c237e6…`, held since HB-98; printed page =
PDF page). EPA SCRAM's SCIPUFF overview (`epa-scipuff-overview-2000`, `563abf8d…`, 5 pp., held since HB-65). APTI
Workshop T-029 Day 2 (`epa-7th-aqm-conference-technical-highlights-day2-2000`, `563f5bc9…`, 84 pp., fetched by
HB-160).

## The verdicts

| # | The report's quotation | Work | Where (held copy) | Verdict |
|---|---|---|---|---|
| a1 | "Uncertainties in the average wind direction are represented on the threat zone graph as confidence lines." | ALOHA Tech. Doc. | §4.5.3, p. 57 (PDF 65) | Confirmed verbatim |
| a2 | "The axis of the threat zone is rotated through an angle on either side of the nominal wind direction and the contour of the rotated threat zone is drawn." | ALOHA Tech. Doc. | §4.5.3, p. 57 | Confirmed verbatim |
| a3 | "The angle, α, is based on the width of the Guassian plume at a distance 5 minutes downwind of the source …" | ALOHA Tech. Doc. | §4.5.3, p. 57 | Confirmed verbatim, "Guassian" [sic] in the held text; the sentence ends in the formula, which the report omits (below) |
| b | "The 'uncertainty lines' around the longest threat zone enclose the region within which, about 95 percent of the time, the gas cloud is expected to remain." | ALOHA User's Manual | ch. 2 example, step 4, p. 45 | Confirmed verbatim. The report's link is NEPIS's text rendition (P1003UZB.TXT); the held PDF is NEPIS P1003UZB |
| c | "In addition to the average concentration value, the closure model also provides a prediction of the statistical variance in the concentration field resulting from the random fluctuations in the wind field." | SCIPUFF overview | Model Description, p. 1 | Confirmed verbatim |
| c2 | "Planetary boundary layer: Vertical profiles of … can be provided as input by the user or modeled based on boundary layer characteristics." | SCIPUFF overview | Turbulence Data item 1, p. 2 | Confirmed verbatim; the held item continues with the treatment options ("calculated", "observed", "simple diurnal") |
| c3 | "Large scale variability: For long range transport, the mesoscale horizontal velocity fluctuations and turbulence length scale may be specified by the user, computed from a theoretical model or read from a meteorological observation file." | SCIPUFF overview | Turbulence Data item 2, p. 2 | Confirmed verbatim |
| d1 | "Turbulent dispersion implies a random concentration field." | APTI T-029 Day 2 (Sykes) | Presentation 3 p. 4, slide "Concentration Fluctuations" (PDF 36) | Confirmed with a correction: a slide bullet, with no closing period |
| d2 | "The probability distribution of c is then modeled by the clipped normal distribution." | APTI T-029 Day 2 (Sykes) | same slide, bullet 3 | Confirmed with a correction: no closing period. The report's location, "Presentation 3, p. 4", is right |
| d3 | (paraphrase) the next bullet names the mean and the fluctuation variance as closure outputs | APTI T-029 Day 2 (Sykes) | same slide, bullet 2 | Confirmed: "2nd-order closure model gives both fluctuation variance, c′², and c̄" (overbars on the slide) |
| e1 | Figure 12 caption: "View of SCIPUFF probabilistic prediction outputs: contours of the probability that dosage exceeds 60 mg s m−3." | Warner, Platt and Heagy 2004 | — | Not checked: the work is not held (rung 1 refused, HTTP 403) |
| e2 | "The 0.01 probability values are always associated with the widest predictions (most conservative) and the 0.999 probability values are always associated with the narrowest predictions." | Warner, Platt and Heagy 2004 | — | Not checked: not held |
| f1 | "SCIPUFF's modeling accounts for the stochastic uncertainty that results from unresolved atmospheric turbulence." | JAMC 2009 (SCIPUFF with NWP ensembles) | — | Not checked: not held (rung 1 refused, HTTP 403) |
| f2 | "Modeling technology is also in place in SCIPUFF, through the ensemble uncertainty modeling, to account for the uncertainty that results from meteorological input data … however, definitions for all of the modeling parameters are not complete." | JAMC 2009 | — | Not checked: not held |

"Not found" applies to none: every quotation from a held work was found. "Not checked" means the work could not be
held at rung 1, so the quotation is neither confirmed nor refuted; under HBD-313 nothing hazbrief writes may rest on
it except as "unverified".

## (a) ALOHA section 4.5.3: the construction, and every condition the held texts put on it

Section 4.5.3, "Confidence contours", printed p. 57, in full:

> Uncertainties in the average wind direction are represented on the threat zone graph as confidence lines. The axis
> of the threat zone is rotated through an angle on either side of the nominal wind direction and the contour of the
> rotated threat zone is drawn. The angle, α, is based on the width of the Guassian plume at a distance 5 minutes
> downwind of the source,
>
> α = arctan( 2σ_y / (300 U₃) ),
>
> where U₃ is the wind speed at 3 meters (m s-1).

That is the whole section. The conditions on α, as the held texts state them:

1. **σ_y** is the Gaussian model's crosswind dispersion parameter (§4.3.1, p. 43): σ_y(x) = s_y1·x / √(1 + s_y2·x),
   Briggs's rural form, with s_y1 = 0.22, 0.16, 0.11, 0.08, 0.06, 0.04 for stability classes A to F and s_y2 = 0.0001
   for every class (Table 13, p. 45). "ALOHA uses only the rural coefficients based on 3-minute averaging times to
   estimate σy under all surface roughness conditions" (p. 44).
2. **The distance.** 300 U₃ is the distance in metres a parcel travels in 5 minutes (300 s) at U₃. The section says σ_y
   is taken "at a distance 5 minutes downwind of the source", so σ_y is σ_y(300 U₃). This is HB-160's reading of the
   formula: the section names the distance in words and does not write σ_y(300 U₃).
3. **U₃** is the wind speed at 3 m, from ALOHA's wind profile (§4.2.3, pp. 39-40), which ALOHA computes from the
   entered wind speed and reference height with stability and roughness.
4. **Scope.** "ALOHA is applicable to cases where the wind speed is greater than 1 meter per second (at 10 meters); it
   should not be used for very low wind speeds or calm conditions" (§1.2 "Design criteria and limitations", p. 4, PDF 12).
5. **What the Tech. Doc. does not say:** a probability for the lines, whether they apply to the heavy-gas model, and
   what happens at low speed. The User's Manual says those three things (below). Neither text gives the rule by which
   the lines become a circle; the formula alone caps α below 90°.

## (b) The User's Manual: what the lines enclose, and how often

- Ch. 2 example, step 4 (p. 45): "The 'uncertainty lines' around the longest threat zone enclose the region within
  which, about 95 percent of the time, the gas cloud is expected to remain." (That run is ALOHA's heavy gas model,
  per step 5.)
- Ch. 4, Threat zone plot (p. 152): "On ALOHA's threat zone plot for all dispersion scenarios, the dashed lines along
  both sides of the threat zone represent uncertainty in the wind direction." … "about 19 out of 20 times, the
  chemical cloud is expected to remain. The lower the wind speed, the more the wind changes direction, so as wind
  speed decreases, the uncertainty lines become farther apart. They form a circle when wind speed is very low."
- Ch. 2, Conditions that can produce unreliable results (p. 28): "ALOHA predicts that about 95 percent of the time,
  the wind will not shift direction enough to move the hazard outside of either line." … "At the lowest wind speeds
  acceptable to ALOHA (about 2 knots, or 1 meter per second, at a height of 10 meters), these lines form a circle to
  indicate that the wind could blow from any direction."

The report quoted only the first. The others add the "all dispersion scenarios" scope, the low-speed circle, and the
interpretation (a statement about the wind direction, "about 95 percent", not a confidence interval on the
concentration).

## (c) and (d) SCIPUFF

(c), the overview's variance sentence, is verbatim. (d), the clipped-normal sentence, is verbatim apart from the
period. Two report claims beyond the quotations, checked: the report's location for (d) is right; and its formula for
a zero-clipped normal, P(c > c*) = 1 − Φ((c* − a)/b), is its own explanation, as it says itself. No held text states
SCIPUFF's fitting equations; the slide names the distribution only.

## (e) Warner, Platt and Heagy (2004) and the 2009 paper

Both refused at rung 1 (`corpus/fetch_log.jsonl`, HTTP 403 from journals.ametsoc.org, whose robots.txt allows the
path). Both rows are closed `unobtainable` under HBD-312 to HBD-314 with their citation metadata; their abstracts are
not held, because the article pages are on the same host. Nothing was queued for the operator.

## The report's other claims, not quotations

- "ALOHA itself includes a Gaussian dispersion model for neutrally buoyant gases": confirmed, Tech. Doc. §4.3, "Gaussian model for neutrally buoyant gases" (p. 41).
- "For the specific shortcut '±1.96 σθ' … none found": the held texts do not use σθ at all; ALOHA's angle comes from
  σ_y at 5 minutes, which is the report's own point.
- The HPAC display (question 4) rests on the 2004 paper only, which is not held, so it is unverified here.
