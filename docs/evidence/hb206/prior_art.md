# HB-206 item 1: what the held sources say about a release shorter than one minute

Read on 2026-11-18 from the held bytes (`corpus/raw/`, sha256 in `corpus/sources.yaml`): the PDFs' text layers by
`pdftotext -layout`, the SLAB guide by the kit's parse (`the corpus graph (held privately)`,
its page numbers the PDF's), and the SCICHEM user's guide from its `.docx` (`word/document.xml`; a docx has no page, so
the section is cited). A statement no held source supports is marked **not held** and nothing below relies on it.

Doc ids: **TD** `noaa-aloha-technical-documentation` (NOAA Technical Memorandum NOS OR&R 43, ALOHA 5.4.4 Technical
Documentation, November 2013; PDF page, printed page = PDF - 8); **UM** `epa-aloha-users-manual-2007` (ALOHA User's
Manual, February 2007; PDF page, which is the printed page); **SG** `epa-slab-users-guide-1990` (Ermak 1990; PDF page,
printed = PDF - 6); **SU** `scichem-users-guide-3-4`; **M17** `mazzola-2020-jack-rabbit-ii-17-dense-gas-models-manuscript`
(PDF page = printed page); **SIM** `simpson-2020-hpac-jack-rabbit-ii-accepted-manuscript` (PDF page); **V2**
`hanna-strimaitis-chang-1993-hazard-response-modeling-uncertainty-vol2` (as `src/hazbrief/brief/agreement.yaml`
`release_kind` already cites it, HB-173).

## 1. ALOHA: what a release under one minute is

| # | Statement | Source |
|---|---|---|
| A1 | "ALOHA limits the duration of any source to one hour, and the shortest source duration allowed in ALOHA is one minute (this is termed an instantaneous release in ALOHA)." | TD PDF p. 19 (printed p. 11) |
| A2 | A time-varying source is computed in up to 150 time steps "reduced to five or fewer steady-state timesteps which are linked to the dispersion models." | TD PDF p. 19 (printed p. 11) |
| A3 | ALOHA averages a puddle, tank or pipeline release "into between one and five release rates, each averaged over a time period of at least 1 minute"; "ALOHA expects a release into the atmosphere to continue for at least 1 minute." | UM p. 41; p. 129; p. 130; p. 158 |
| A4 | The Direct source: "The user can specify an instantaneous release, or a steady-state release of finite duration." "Instantaneous" is an option of the Direct source: "indicate whether the release is instantaneous (lasting one minute) or continuous (lasting more than one minute)." | TD PDF p. 20 (printed p. 12); UM p. 131 |
| A5 | "Release rate for a Direct source, whether it's instantaneous or continuous, will remain constant for the duration of the release. ALOHA expects an instantaneous release to last for 1 minute"; "ALOHA models the release as a constant release with a one minute duration"; glossary: "ALOHA assumes that an instantaneous release lasts 1 minute." | UM p. 157; p. 129; p. 178 |
| A6 | Gaussian model: "An instantaneous release is modeled as a single one-minute steady-state release which gives rise to a single cloud." | TD PDF p. 49 (printed p. 41) |
| A7 | Heavy gas model: "For any non-instantaneous sources in ALOHA, the model generates a five-step release; each step is a finite-duration steady-state release. The Heavy Gas model generates infinite-duration steady-state plumes for each of these sources." | TD PDF p. 53 (printed p. 45) |
| A8 | The Primary Sources (direct, tank, pipeline, puddle) are "generally time dependent and approximated as a series of five finite-duration steady-state sources"; "Most of the Primary Sources in ALOHA are point sources; however, the evaporating puddle has a defined area." | TD PDF p. 56 to 57 (printed pp. 48 to 49) |
| A9 | The criterion: Ri_c = H g_hat / U*^2. "For instantaneous releases, H is the characteristic height of the source, H = V0 / A0, where V0 is the volume of the release and A0 is the area of the source." Puddle: H = E / (rho U10 D). "For continuous or semi-continuous sources other than the puddle source": H = sqrt(E pi / (4 rho U10)). | TD PDF pp. 54 to 55 (printed pp. 46 to 47) |

**What these settle and what they do not.** ALOHA never models a release shorter than a minute: it models it as one
minute (A1, A3, A5), as a constant, steady release at the mass over that minute (A5, A6). Its word "instantaneous" names
that one-minute release, and as an input it is the Direct source's option (A4); a tank's release reaches the dispersion
models as one to five averaged steps of at least a minute each (A2, A3), which the heavy gas model treats as
finite-duration steady releases (A7, A8). The instantaneous form of the criterion needs a source area A0 (A9), which a
tank's point source does not have (A8). **No held page says, in so many words, which form of Ri_c ALOHA applies to a
tank release its averaging has floored to one minute.** So item 2's third case applies: evaluate both forms (protocol.md
section 2).

## 2. SLAB: finite-duration releases

| # | Statement | Source |
|---|---|---|
| S1 | "The current version of SLAB can treat continuous, finite duration, and instantaneous releases from four types of sources: a ground level evaporating pool, an elevated horizontal jet, a stack or elevated vertical jet, and a ground-based instantaneous release." | SG PDF p. 9 |
| S2 | "In the case of a finite duration release, cloud dispersion is initially described using the steady state plume mode and remains in the steady state plume mode as long as the source is active. Once the source is shut off, the cloud is treated as a transient puff." | SG PDF p. 7 (abstract); p. 9; p. 62; p. 64 |
| S3 | TSD, "Continuous source duration (s)": "the duration of the release from an evaporating pool ... or jet (IDSPL = 2 or 3) source. When an instantaneous release is to be simulated TSD should be set to zero." | SG PDF p. 57 (section 3.1.3.4); field list PDF p. 50 |
| S4 | At the end of the release the puff's half-length is BBX = 0.5 U TSD, so the cloud properties are continuous across the change of mode. | SG PDF p. 68 |

So SLAB's horizontal jet (IDSPL 2, the route's two-phase jet) takes any finite duration TSD directly, 33.3 s or 60 s
alike; it needs no floor.

## 3. SCICHEM: finite-duration releases

| # | Statement | Source |
|---|---|---|
| C1 | `reltyp`: "'C' for continuous, 'I' for instantaneous"; `Tdur`: "Duration (hours) of a continuous release." `cmass`: "mass flux for a continuous release". | SU section 4.1.2, Release Scenario File (the `&SCN` namelist) |
| C2 | The route writes the two-phase jet as `RELTYP = 'C'` with `TDUR` the SLAB problem's TSD in hours. | `src/hazbrief/brief/scichem.py` `jet_source` (`duration_s=problem["tsd"]`) and the scenario writer (`TDUR`, `RELTYP = 'C'`) |

So SCICHEM, as the route drives it, takes any finite duration as a continuous release of that duration; it needs no
floor either.

## 4. Jack Rabbit II: the source every model was given

| # | Statement | Source |
|---|---|---|
| J1 | "All modelers were sent a set of recommended inputs for emissions (Spicer and Miller, 2017) and for meteorology (Hanna, 2018) and were asked to send model outputs of the arc-maximum concentrations (arc-max C) for averaging times of 1 s". | M17 p. 4 lines 98 to 101 |
| J2 | Table 3, "Averaged simplified emission rates", single source, Trial 7: discharge rate 259 kg/s, discharge period 33.3 s, temperature -37.4 C, vapour fraction 0.172, density 18.12 kg/m3, velocity 44.2 m/s, area 0.323 m2. | M17 Table 3 p. 7 |
| J3 | Table 4, Trial 7: mass released 8,625 kg, duration of release 33.3 s, mass rate 259 kg/s. | M17 Table 4 p. 14 |
| J4 | The release was "a two-phase momentum jet from a 15.2 cm diameter hole, with duration of about 20 to 40 seconds". | M17 p. 14 lines 305 to 307 |
| J5 | Phast "allows a range of source terms (evaporating pools, instantaneous releases, finite duration and time-varying releases)"; ADAM (a modified SLAB) adds "the calculation for time-varying releases". | M17 p. 12 lines 258 to 260; p. 8 lines 161 to 162 |
| J6 | HPAC was run with "a 'simple' model with only jetting of material from the orifice" (the MWG's source), Trial 7's heel modelled as a pool appearing 10 minutes after release. | SIM PDF p. 7 lines 186 to 192, 205 to 207; p. 8 lines 227 to 229 |

**Not held:** how each of the 17 models took the 33.3 s source (as a finite-duration release, floored, or otherwise).
M17 says every modeller was sent it (J1) and that two of the models can take a finite-duration or time-varying release
(J5); it does not say what each did with it. How the ALOHA run of the comparison (Rand) took a 33.3 s source is not held.
Nothing below relies on either.

## 5. What a one-minute floor does, from a held criterion

| # | Statement | Source |
|---|---|---|
| V1 | A release is continuous where u T / x is at least 2.5, instantaneous where it is at most 0.6, and between them "Calculate both ways" (u the wind speed, T the release duration, x the distance). | V2 blocks 385 to 388 (`agreement.yaml` `release_kind`) |

At Trial 7's wind (3.98 m/s at 2 m), a 60 s release is instantaneous by V1 beyond 398 m, the 33.3 s source beyond
221 m, and the route's computed 22 s beyond 146 m. Beyond those distances the peak is set by the mass and the spread,
not by the duration; nearer the source a longer release has a lower rate and so a lower peak. This is the property the
task asks to state, not to correct: the floor keeps the mass and lowers the near-source rate (by 22/60 here).

## 6. The searches

The held sources were read in full for the strings `instantaneous`, `one minute`, `1 minute`, `duration`, `Richardson`,
`V0`, `A0`, `TSD`, `TDUR`, `finite duration`, `33.3` and `259` (TD, UM, SG, SU, M17, SIM). Fox's overview and Weil's
IDDM manuscript are held and give Trial 7's inputs (HB-199 `trial7_inputs.tsv`); neither says how ALOHA classes a
floored tank release.
