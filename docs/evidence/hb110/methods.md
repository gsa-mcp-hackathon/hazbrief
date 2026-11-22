# HB-110 Part A step 1: the two release models, transcribed from the held pages

**Sources.**
- `noaa-aloha-technical-documentation`: ALOHA 5.4.4 Technical Documentation, NOAA TM NOS OR&R 43, November 2013.
  sha256 `2f7663950899c948d1a8ca6ef2e36b31b9d78f6d955b6271bd411d4d0d638c9a`.
- `epa-aloha-users-manual-2007`: ALOHA User's Manual. sha256
  `a3c237e6fef16167946f482e6ca102144f4418fab805e797eef340ea0deeb939`.
- `us-standard-atmosphere-1976`: for air's properties. Its text layer is OCR noise, so it is read from the rendered pages,
  as HB-66 read it.

**Page numbers.** "p. N" is the technical documentation's printed page. The PDF page is N + 8, and the PDF page is
what `orchestrator.yaml` `weather.source_term.constants` and the tests cite. In the manual, the PDF page equals the
printed page.

**Section numbering.** The task names "section 4 (the Tank and Puddle sources)". In this edition the source strength
models are **section 3**, "Source Strength Models", pp. 11 to 34. Section 4 is "Air Dispersion Models". The Tank and
Puddle sources are 3.3 and 3.4. The task's section number is DN-020's, written before the document was read; the
content is the one the task means.

**Reading.** Every equation was read from the rendered page image: the text layer breaks typeset equations into number
fragments. A constant's `quote` in `orchestrator.yaml` is the text-layer fragment where one exists, so a test can find
it on the page. Where no fragment exists, the entry is marked `read_by: rendered_page` and transcribed here.

Correlations are named as the documentation names them. Nothing is cited from memory.

## 1. Two-phase flashing release from a tank (section 3.4)

| Step | Equation as printed | Page | Coefficients and the source the documentation names |
|---|---|---|---|
| Tank temperature (3.4.1) | dT_T/dt = (Q_e L_c + F_Hw A_tw) / (rho_l c_pl V_l) | 22 | wall flux: "2 cm of steel and 10 cm of insulating foam"; no conductivity is printed, so the wall term is **not modelled** (section 5) |
| Evaporation into the head space | Q_e(t) = (Q_T / rho_X) (rho_l rho_g / (rho_l - rho_g)) | 22 | rho_X is the effluent's density |
| Tank pressure (3.4.2) | the tank holds one component at its vapour pressure | 23 | — |
| Phase of the effluent (3.4.3) | DIERS vapour disengagement for ammonia and chlorine; otherwise a head-space rupture swells to a uniform two-phase mixture | 23-24 | DIERS (Fisher et al. 1992); churn-turbulent flow (Leung 1994; Karlins 1994 for ammonia); U_rise = 1.53 (sigma g (rho_l - rho_g))^1/4 / rho_l^1/2; Psi = 2 alpha / (1 - C_0 alpha), C_0 = 1.0; Grolmes and Fisher 1994 for horizontal vessels. **Not modelled** (section 5) |
| Mass flux, superheated or two-phase (3.4.5) | G = L_c / (v_g - v_l) (N c_P T)^-1/2; N = L_c^2 v_l / (2 dP C_dis^2 (v_g - v_l)^2 T c_P) + l / l_e | 27 | the Homogeneous Nonequilibrium Model (Fauske 1985; Fauske and Epstein 1987; Henry and Fauske 1971); l_e = 0.1 m |
| Quality limit | X(max) = P c_P T (v_g - v_l) / L_c | 27 | applies to a two-phase effluent; a bottom hole's effluent is liquid at the hole |
| Hole or short pipe | a hole is l = 0, and the HNE then reduces to Bernoulli; a short pipe is l = 10 cm, approximately the homogeneous equilibrium model | 27-28 | Huff 1985 |
| Large pipes | over 1 m diameter, Bernoulli; between 0.1 and 1 m, interpolated | 28 | — |
| After the release | adiabatic vaporisation down to the ambient boiling point; the rest is a fine aerosol treated as a dense gas; "ALOHA does not allow the liquid to rain out and form a puddle" | 28 | — |
| Flashed fraction | f = C_p (T - T_b) / dH_v, isenthalpic, "somewhat overestimates the fraction that flashes in an adiabatic (isentropic) process" | 68 (section 6.3.2) | printed for the BLEVE; section 3.4.5 describes the same adiabatic flash without an equation |
| Clausius-Clapeyron | T = [1/T_B - (R_c / dH_V) ln(P / P^0)]^-1 | 68 | R_c 8.3144 J/(K mol); P^0 101,000 Pa |
| Gas from the head space (3.4.6) | R_P = P_a / P_T; beta_c = l_h / l_T; R_c = (2/(gamma+1))^(gamma/(gamma-1)) for beta_c > 0.2; R_c^((1-gamma)/gamma) + ((gamma-1)/2) beta_c^4 R_c^(2/gamma) = (gamma+1)/2 for beta_c <= 0.2 | 28-29 | LEAKR (Belore and Buist 1986) |
| Choked flow | Q = C_dis A_h (rho_g P_T gamma (2/(gamma+1))^((gamma+1)/(gamma-1)))^1/2 | 29 | Shapiro 1953; Blevins 1984 |
| Unchoked flow | Q = C_dis A_h (2 rho_g P_T (gamma/(gamma-1)) [(P_a/P_T)^(2/gamma) - (P_a/P_T)^((gamma+1)/gamma)])^1/2 | 30 | — |
| Source duration | at most one hour; at least one minute, "termed an instantaneous release"; up to 150 time steps, averaged into five or fewer | 11 | — |

## 2. Non-boiling liquid from a tank (3.4.4) and the evaporating pool (3.3)

| Step | Equation as printed | Page | Coefficients and the source the documentation names |
|---|---|---|---|
| Bernoulli (3.4.4.1) | Q_T(t) = C_dis A_f (2 (P_h - P_a) rho_l)^1/2 | 25 | C_dis = 0.61; P_h is held at 1.01 P_a once it falls to it (Belore and Buist 1986; Dodge, Bowels and White 1980); a hole the level intersects: P_h = P_a plus the head above the hole's bottom |
| Spreading (3.4.4.2) | dr_p/dt = (2 g d_p)^1/2; spreading ends at 5 mm depth; the area never shrinks | 26 | Briscoe and Shaw 1980; "When the tank release rate is greater than the computed evaporation rate, ALOHA predicts that the puddle will spread" |
| Largest puddle | "up to a maximum diameter of 200 meters" | manual p. 56 | — |
| Brighton's flux (3.3.1) | E(x,t) = C_s U_* j(x); j-bar = (1/D_P) integral j dx; j_c = -j-bar (P_a/P_v) ln(1 - P_v/P_a); E-bar = C_s U_* j_c | 13 | Brighton 1985; the upper limit is the correction factor reaching 4 (footnote 3, p. 12) |
| Friction velocity | U_* = 0.03 U (10/z)^n | 13 | Deacon 1973 |
| Power-law exponent | n by stability class: A 0.108, B 0.112, C 0.120, D 0.142, E 0.203, F 0.253 | 14 | Table 7; Havens and Spicer 1985 |
| Mass transfer coefficient | j-bar = (k/Sc_T)(1+n) [1/2 - (1/pi) arctan(ln(e^Lambda X_1)/pi) + (1 - gamma_e)/(ln^2(e^Lambda X_1) + pi^2) + (1 + (1 - gamma_e)^2 + pi^2/6) ln(e^Lambda X_1) / (ln^2(e^Lambda X_1) + pi^2)^2] | 14 | k = 0.4 |
| Dimensionless distance | X_1 = n k^2 D_P / (Sc_T z_0 e^(1/n)) | 14 | — |
| Lambda | Lambda = 1/n + 1 + 2 ln(1+n) - 2 gamma_e + (k/Sc_T)(1+n) f(Sc) | 15 | Brutsaert 1982; gamma_e = 0.577; Sc_T = 0.85 (Fackrell and Robins 1982) |
| f(Sc) | (3.85 Sc^1/3 - 1.3)^2 + (Sc_T/k) ln(0.13 Sc) for Re_0 < 0.13 (smooth); 7.3 Re_0^1/4 Sc^1/2 - 5 Sc_T for Re_0 > 2 (rough); linear between | 15 | Re_0 = U_* z_0 / nu |
| Diffusivity | kappa_c = kappa_w (M_w / M_c)^1/2 | 15 | Graham's law (Thibodeaux 1979); kappa_w = 2.39 x 10^-5 m2/s |
| Laminar Schmidt number | **see section 4** | 15 | — |
| Boiling puddle (3.3.2) | the temperature is held at the boiling point, and evaporation balances the heat fluxes; ALOHA compares this with Brighton at its limit and takes the larger | 16 | — |
| Energy balance (3.3.3) | dT_p/dt = (F_S + F_down + F_up + F_G + F_H + F_E) / (rho_l c_pl d_p); for a fed puddle, + F_dM = Q_T c_pl (T_T - T_P) / (pi r_p^2) | 17, 26 | — |
| Solar | F_S = 1111 (1 - 0.0071 CI^2)(sin phi_s - 0.1) when sin phi_s > 0.1, else 0 | 17 | Raphael 1962 |
| Longwave | F_up = -eps sigma T_p^4 (eps 0.97, sigma 5.67 x 10^-8); F_down = (1 - r) B sigma T_a^4 (r 0.03); B = a + b e_w | 18 | Thibodeaux 1979; Table 8 gives a and b by cloudiness index |
| Water vapour pressure | e_w = 99.89 (RH/100) exp(21.66 - 5431.3/T_a) | 19 | — |
| Ground (land) | F_G = -alpha_G dT/dz at z = 0, by the heat equation; error-function solution for a constant puddle temperature, finite differences otherwise | 19-20 | Table 9 with the ×9 correction (Briscoe and Shaw 1980): dry sandy soil 2.34 W/(m K) and 1.74 x 10^-6 m2/s; concrete 8.28 and 3.74 x 10^-6; default soil 8.64 and 4.13 x 10^-6; moist sandy soil 5.31 and 3.02 x 10^-6 |
| Ground (water) | F_G = 500 dT, for a puddle colder than the water | 19 | Webber 1991 |
| Evaporative | F_E = L_C E-bar | 21 | — |
| Sensible | F_H = rho_a c_p,a C_H U_* (T_a - T_p); c_p,a = 1,004; C_H = j_c (thermal diffusivity / molecular diffusivity)^2/3 | 21 | Brighton 1985, 1990 |
| Open Country roughness | z_0 = 0.03 m | 40 | — |

**Air's properties.** These come from `us-standard-atmosphere-1976`, rendered pages. Viscosity is Sutherland's
mu = beta T^3/2 / (T + S), with beta = 1.458 x 10^-6 kg/(s m K^1/2) and S = 110.4 K: printed p. 19 (PDF 35), equation
(51). Table 2 prints S as 110 K, and the held text's appended errata says 110.4. Conductivity is
k_t = 2.64638 x 10^-3 T^3/2 / (T + 245.4 x 10^-(12/T)), equation (53). Air's molecular weight is the sum of F_i M_i over
Table 3, 28.9644 kg/kmol (PDF p. 19). Water's is H2 + O2/2 from the same table, 18.01534 kg/kmol.

## 3. The worked examples

Each example's inputs and printed outputs, page by page, are in `worked_examples.yaml`. Its stand-ins for inputs it does
not print are listed under `not_printed`. The runs and their comparison are in `worked_examples_result.json`,
written by `tools/run_examples.py`, and `test_source_term.py (a test held privately)` checks the comparison against a fresh run.

| Example | Printed rate | Computed (largest 1-minute mean) | Printed duration | Computed | Printed total | Computed |
|---|---|---|---|---|---|---|
| Chlorine, 1 ton, 0.5 in short pipe at mid-height (manual pp. 38-41) | 172 lb/min | 175.6 (+2.1 %) | 33 min | 31.9 (−3.5 %) | 827 lb | 739 (−10.6 %) |
| Propane, 33,800 gal tank car, 40 x 0.1 in seam at the bottom (pp. 70-76) | 5,730 lb/min | 6,135 (+7.1 %) | 26 min | 25.1 (−3.5 %) | 140,200 lb | 140,200 (0 %) |
| Benzene, 500 gal tank, 6 in hole, puddle on concrete (pp. 49-57) | 77.2 lb/min | 75.3 (−2.4 %) | 46 min | 41.5 (−9.7 %) | 3,082 lb | 3,069 (−0.4 %) |

The tolerance is 10 % on rate and duration. `test_source_term.py (a test held privately)`'s docstring gives the grounds: the averaging
window ALOHA does not print, and minutes printed whole.

The benzene duration is checked against the isothermal run's implied 39.9 minutes (printed total over printed rate),
not against ALOHA's 46. The manual prints no heat capacity for benzene, so the puddle cannot cool, and its rate cannot
fall as ALOHA's graph (p. 57) shows it falling. The puddle's diameter is 20.3 m against the printed 21.7 yd (19.8 m),
+2.3 %.

The chlorine example's total is 10.6 % low. After the liquid falls below the mid-height valve, ALOHA's DIERS swelling
model decides whether the head space vents gas or a two-phase mixture, and the method here vents gas (section 5). The
two-phase stage, which carries the rate, reproduces.

## 4. The laminar Schmidt number: the document disagrees with itself, and its worked example decides

p. 15 defines Sc in words as "the ratio of the molecular kinematic viscosity of air to the molecular diffusivity of the
contaminant gas in air", which is nu / kappa_c. The typeset equation beneath it is **Sc = kappa_c / nu**. The two
differ by a factor of Sc^2.

The manual's Example 1 is ALOHA's own output for a non-boiling puddle: 77.2 lb/min.
- The typeset form reproduces it: 75.3 lb/min, −2.4 %.
- The worded form misses it: 55.8 lb/min, −27.8 %. Its duration is 55.8 min against the printed 46.

The record of both runs is `benzene_puddle` and `benzene_puddle_worded_schmidt` in `worked_examples_result.json`.

So the source term follows the form ALOHA's printed output shows it computes. The choice is `schmidt_form: typeset`
in `orchestrator.yaml`, with its grounds, and `test_the_worded_schmidt_number_misses_the_puddle_example` holds it.
This affects only the Brighton branch: the non-boiling pool and the sensible heat coefficient. The two-phase release does
not read it.

## 5. What the method here leaves out of ALOHA, and why

Each item is said on the label where it applies (`omitted`).

- **The tank-wall heat flux (3.4.1).** The documentation states the wall's construction but no conductivity. The tank
  cools by evaporation alone. Leaving the wall's heat out makes the tank cool faster than ALOHA's, so the computed rate
  falls sooner. How much is not measured here. The label says the wall is not modelled.
- **DIERS swelling (3.4.3).** A head-space hole vents gas by LEAKR's equations. The fixtures' declared hole is at the
  bottom (`assumptions.md`), where the effluent is liquid, so no fixture reaches this branch.
- **Solar and longwave fluxes when the scenario gives no sky cover, solar altitude or humidity.** The brief gives sky
  cover and solar altitude (HB-57's stability inputs). It gives no relative humidity: the NWS layer is not read, and
  adding it would change every brief's forecast table. So longwave is left out both ways. For a cryogenic pool on soil
  it is under 1 % of the ground flux.
- **The finite-difference ground model.** Each ring of a spreading puddle takes the error-function solution for a
  constant surface temperature, integrated exactly over each one-second step. That is exact for a boiling pool, whose
  temperature is constant, and an approximation for a cooling one.
- **The tank's head and geometry on a fixture.** A fixture states a container class, not dimensions. The hole is at the
  bottom, and the liquid head above it is not added. At chlorine's 7 bar vapour pressure, a 3 m head of liquid is about
  6 % of the driving pressure, or 3 % of the rate. The worked examples state their geometry and use it.

## 6. A cryogenic pool on soil boils off in seconds

ALOHA's ground model on default soil uses 9 times the measured conductivity (p. 20, Briscoe and Shaw), and the doc's
model includes no film-boiling limit. Under that model, 20,000 kg of liquid nitrogen spilled at once evaporates in
about 21 s. ALOHA's shortest source is one minute (p. 11), so the source term reports an instantaneous release over
one minute, and the label says so. This is the documented method's result, not a measured one. HB-112's display review
should see it beside the 1991 Burro trials, which DN-020 ADDENDUM-01 item 5 names for this class.

## Prior art

The prior art is the held corpus: ALOHA's technical documentation and user's manual (NOAA and EPA). The task file
names both. Each method above is theirs, cited by page. No new method was designed.
