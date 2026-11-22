# For HB-157: ALOHA's wind-direction confidence lines as the held text states them, and what SCIPUFF does beyond a Gaussian puff

**Status of the construction: held and confirmed.** Every sentence below is read in a held copy and located by page
in `quotes_checked.md` (20 of 20 found; `locate_quotes.txt`). HB-157 ADDENDUM-03 item 1's condition is met: the
construction is held, so ADDENDUM-03 applies.

Sources (doc_id, sha256 prefix):
- **Tech. Doc.**: Jones, Lehr, Simecek-Beatty and Reynolds, *ALOHA® 5.4.4: Technical Documentation*, NOAA Technical
  Memorandum NOS OR&R 43, November 2013 (`noaa-aloha-technical-documentation`, `2f766395…`).
- **Manual**: US EPA OEM and NOAA OR&R, *ALOHA® User's Manual*, February 2007 (`epa-aloha-users-manual-2007`,
  `a3c237e6…`).

## 1. The construction, verbatim

Tech. Doc. §4.5.3 "Confidence contours", p. 57, the whole section:

> Uncertainties in the average wind direction are represented on the threat zone graph as confidence lines. The axis
> of the threat zone is rotated through an angle on either side of the nominal wind direction and the contour of the
> rotated threat zone is drawn. The angle, α, is based on the width of the Guassian plume at a distance 5 minutes
> downwind of the source,

    α = arctan( 2·σ_y / (300·U₃) )

> where U₃ is the wind speed at 3 meters (m s-1).

("Guassian" is the held text's spelling. The formula is read from the rendered page, `page_images/techdoc-65.png`.)

The method's name, as ALOHA gives it: "confidence lines" (Tech. Doc. §4.5.3; the Manual's "Show confidence lines"
option). The Manual also calls them "uncertainty lines" (in quotation marks).

## 2. Enough to implement

Inputs: the threat-zone (footprint) outline as drawn along the nominal downwind axis; the source point; the
nominal wind direction; U₃; and the Pasquill-Gifford stability class.

1. **Distance.** x₅ = 300 · U₃ metres: the distance the wind carries a parcel in 5 minutes (300 s) at U₃. The
   section says "at a distance 5 minutes downwind of the source". It does not write σ_y(300 U₃); that the σ_y in the
   formula is evaluated at x₅ is HB-160's reading of the sentence and the denominator together. Say so on the label
   or in DN-024.
2. **Width.** σ_y = σ_y(x₅), from Tech. Doc. §4.3.1 (p. 43, read from `page_images/techdoc-51.png`):
   σ_y(x) = s_y1·x / √(1 + s_y2·x), with x in metres. Table 13 (p. 45), the same for both roughness classes:

   | Class | A | B | C | D | E | F |
   |---|---|---|---|---|---|---|
   | s_y1 | 0.22 | 0.16 | 0.11 | 0.08 | 0.06 | 0.04 |
   | s_y2 | 0.0001 | 0.0001 | 0.0001 | 0.0001 | 0.0001 | 0.0001 |

   "ALOHA uses only the rural coefficients based on 3-minute averaging times to estimate σy under all surface
   roughness conditions" (p. 44).
3. **Angle.** α = arctan(2·σ_y(x₅) / x₅). Because x₅ = 300 U₃, the angle depends on stability (through s_y1) and on
   U₃ only weakly through the √(1 + s_y2·x₅) term: 2·σ_y(x₅)/x₅ = 2·s_y1 / √(1 + s_y2·300·U₃). For example, class D,
   U₃ = 3 m/s: x₅ = 900 m, σ_y = 0.08·900/√1.09 = 68.96 m, α = arctan(137.9/900) = 8.71°. (HB-160's arithmetic, a
   seeded value for HB-157's red-first test, not a figure from the held text.)
4. **Drawing.** Rotate the whole threat-zone contour about the source point by +α and by −α from the nominal wind
   direction, and draw each rotated contour as a line. "The axis of the threat zone is rotated through an angle on
   either side of the nominal wind direction and the contour of the rotated threat zone is drawn." The lines are the
   rotated contours, not straight rays.
5. **U₃.** The wind speed at 3 m, from ALOHA's wind profile (Tech. Doc. §4.2.3, pp. 39-40): ALOHA "uses the entered
   wind speed and reference height along with atmospheric stability and ground roughness data to compute a wind
   profile". If hazbrief's puff takes a 10 m wind and has no 3 m profile, the difference is one of ADDENDUM-03 item
   2's "differences the construction depends on": state it.

## 3. Its stated interpretation, and its limits

- **What the lines enclose, and how often** (Manual, ch. 2 example, step 4, p. 45, quoted exactly as the label
  should carry it): "The "uncertainty lines" around the longest threat zone enclose the region within which, about 95
  percent of the time, the gas cloud is expected to remain."
- The same, in ch. 4 (p. 152): "The "uncertainty lines" around the threat zone enclose the region within which, about
  19 out of 20 times, the chemical cloud is expected to remain."
- **It is a statement about the wind direction** (Manual p. 28): "To show how much a dispersion threat zone's
  position could change if the wind were to shift direction, under the particular weather conditions that you enter,
  ALOHA draws two dashed lines, one along each side of the threat zone. ALOHA predicts that about 95 percent of the
  time, the wind will not shift direction enough to move the hazard outside of either line." It bounds where the
  footprint goes, not the concentration inside it, and it is not a confidence interval on the model.
- **Low wind** (Manual p. 152): "The lower the wind speed, the more the wind changes direction, so as wind speed
  decreases, the uncertainty lines become farther apart. They form a circle when wind speed is very low." And (p. 28):
  "At the lowest wind speeds acceptable to ALOHA (about 2 knots, or 1 meter per second, at a height of 10 meters),
  these lines form a circle to indicate that the wind could blow from any direction." **Gap:** neither text gives the
  rule that turns the lines into a circle. The formula alone keeps α below 90°. HB-157 must not invent a threshold;
  say the circle is not drawn because its rule is not held, or take it from a held source.
- **Scope of speed** (Tech. Doc. §1.2, p. 4): "ALOHA is applicable to cases where the wind speed is greater than 1
  meter per second (at 10 meters); it should not be used for very low wind speeds or calm conditions."
- **Which footprints** (ADDENDUM-03 item 5). The Manual says "On ALOHA's threat zone plot for all dispersion
  scenarios, the dashed lines along both sides of the threat zone represent uncertainty in the wind direction" (p.
  152), and its worked chlorine example, which ran the heavy gas model ("Model Run: Heavy Gas", step 5, p. 45), shows
  them. So the held text applies the lines to ALOHA's heavy-gas footprint too. The angle is still computed from the
  Gaussian σ_y (§4.5.3: "the width of the Guassian plume"), whichever model drew the footprint. The Tech. Doc. sets
  §4.5.3 under §4.5 "Threat zone", which covers every dispersion model's threat zone.
- **Which zone.** Every worked example in the Manual has the user check that "Show confidence lines only for the
  longest threat zone" is selected (ch. 2 example, step 3, and the later examples), and the p. 45 sentence speaks of
  "the longest threat zone". The held text does not say whether that is ALOHA's default.
- **Validation** (ADDENDUM-03 item 3). The held Manual prints no confidence-line angle or line geometry for any
  worked example (searched: "degree", "confidence", "uncertainty lines"), so the construction cannot be checked
  against ALOHA's output from the held copies. State that it is implemented from the text.

## 4. What SCIPUFF does that a plain Gaussian puff cannot

SCIPUFF's second-order closure predicts, besides the mean concentration, "a prediction of the statistical variance in
the concentration field resulting from the random fluctuations in the wind field" (EPA SCRAM overview, p. 1), so every
point carries a mean and a fluctuation variance, not one value. It then models the concentration's probability
distribution as "the clipped normal distribution" (Sykes, APTI T-029 Day 2, Presentation 3 p. 4), which turns that
mean and variance into a probability of exceeding a threshold at each point; a plain Gaussian puff predicts the mean
alone and has no distribution to take a probability from.

How HPAC displayed this (probability-of-exceedance contours, Warner, Platt and Heagy 2004, figure 12) and what the
2009 NWP-ensemble paper says the variance does and does not cover are **not held** (both refused at rung 1); DN-024
may name them only as unverified leads.
