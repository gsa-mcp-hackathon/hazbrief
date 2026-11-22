# HB-128 acquisition record

Rung 1 only, through `scripts/fetch_allowlisted.py`, on the task's Network line (2026-11-08 UTC). Corpus rows are logged
to `corpus/fetch_log.jsonl`. Discovery and refusal probes are not corpus rows, so they are logged to
`corpus/landing_fetch_log.jsonl` under `hb128-probe-*` ids (the HB-52 rule). The PLACES tract slice is a data file, not
a document, and is logged there too (`cdc-places-tract-gis-2025-dc-md-pa-va-wv`; `tools/fetch_places_slice.py`).
Web search was used for titles and URLs only. No value comes from a search result.

**Hosts added to `corpus/allowlist.txt`:** 11 of the 15 on the Network line. `epa.gov`, `www.epa.gov`, `www.cdc.gov` and
`www.ecfr.gov` were already listed (ADDENDUM-01 section 3).

## Outcomes

| # | Wanted | Row | Outcome | Next rung |
|---|---|---|---|---|
| 1 | Lavdas 1996, VSMOKE Users Manual, GTR SRS-6 | `usfs-lavdas-1996-vsmoke-users-manual` | **robots_disallowed**. research.fs.usda.gov's robots.txt reads `User-agent: *` / `Disallow: /`, and allows only its named crawlers. The record page (`hb128-probe-vsmoke-treesearch-1561`) and the PDF (`hb128-probe-vsmoke-manual-pdf`) are both refused. The old Treesearch path on www.fs.usda.gov answers 404 (`hb128-probe-fs-treesearch-pubs-1561`). | browser (rung 2) |
| 2 | The VSMOKE Fortran source, as the Forest Service distributes it | `usfs-srs-vsmoke-download-page` | **robots_unreachable**. `webcam.srs.fs.usda.gov` has no address record. Google's resolver answers NOERROR with no A record and the fs.usda.gov SOA (`dig @8.8.8.8`, 2026-11-08). The tools page (`hb128-probe-vsmoke-tools-page`) and the download page (`hb128-probe-vsmoke-download-page`) were never contacted. A web search names the download page, `/tools/vsmoke/download.shtml`, and says its interface ships as `smoke.zip` (a Windows setup program). Whether it carries the Fortran source is not established. No other copy of the source was found. | browser, if the operator's network resolves the host; otherwise the operator asks the Southern Research Station for the source |
| 3 | Harms and Lavdas 1997, VSMOKE-GIS, RP SRS-6 | `usfs-harms-lavdas-1997-vsmoke-gis` | **robots_disallowed**, as row 1 | browser |
| 3 | The VSMOKE interface PDF | `usfs-srs-vsmoke-interface-pdf` | **robots_unreachable**, as row 2 | as row 2 |
| 3 | Southern Fire Exchange fact sheet 2011-6 | `sfe-factsheet-2011-6-vsmoke` | **refused_by_host** (HTTP 403, both the page and the PDF: `hb128-probe-sfe-factsheet-2011-6`, `hb128-probe-sfe-2011-6-pdf`). The row is `reuse: reference-only`: the Southern Fire Exchange is not a federal author, and no permissive marking was seen. | browser |
| 4 | EPA, Wildfire Smoke: A Guide for Public Health Officials, current revision | `epa-wildfire-smoke-guide-2019` | **fetched** from document.airnow.gov, the PDF its AirNow page links. Its cover reads "Revised 2019, EPA-452/R-21-901, September 2021" (88 pages). | — |
| 4 | The guide's AirNow publication page | `airnow-wildfire-smoke-guide-page` | **fetched** | — |
| 5 | The PM2.5 AQI breakpoints in force: 40 CFR part 58 Appendix G from eCFR, with its "up to date as of" line | `ecfr-40-cfr-58-appendix-g` | **blocked_host**. eCFR redirects this client to `unblock.federalregister.gov`, its bot wall, as it did for 49 CFR 172.101 (HB-01e). The "up to date as of" line is therefore not held. | browser (the HB-98 clipping route) |
| 5 | (the same table, from EPA) | `epa-aqi-technical-assistance-2026` | **fetched**. EPA's Technical Assistance Document for the Reporting of Daily Air Quality, EPA-403/B-26-003, May 2026. Its first page says it applies "according to 40 CFR Appendix G to Part 58". Table 6 prints the PM2.5 breakpoints as revised in 2024 (Good 0.0-9.0 µg/m³). | — |
| 6 | CDC PLACES measure definitions: current asthma, COPD, CHD | `cdc-places-measure-definitions-health-outcomes` | **fetched** | — |
| 6 | CDC PLACES methodology (the model-based caveat) | `cdc-places-methodology` | **fetched** | — |
| 6 | CDC PLACES data dictionary | `cdc-places-data-dictionary` | **fetched** (data.cdc.gov `m35w-spkz`, CSV). Its newest release column is "PLACES Release 2024"; it does not list the 2025 release. | — |
| 6 | The 2025 tract file's metadata (release, description, columns) | `cdc-places-tract-gis-2025-metadata` | **fetched** (data.cdc.gov `yjkw-uj5s`, JSON) | — |
| 6 | The tract file for the fixtures' states | `cdc-places-tract-gis-2025` (`deferred_bulk_data`) | **fetched**: the slice for DC, MD, PA, VA and WV, 7,784 tracts, 5,182,406 bytes. It was fetched twice and returned the same sha256, `5ca49c41…`, both times (the probe and `tools/fetch_places_slice.py`). | — |

## What step 1 asked to record verbatim

- **The PLACES release year:** the 2025 release. The dataset's title is "PLACES: Census Tract Data (GIS Friendly Format),
  2025 release". Its rows were updated 2025-12-04 (`rowsUpdatedAt` 1764844763), and the methodology page is dated
  "Dec. 7, 2025".
- **The model-based-estimate caveat, verbatim:**
  - the dataset's description: "This dataset contains model-based census tract level estimates in GIS-friendly
    format.";
  - the methodology page: "PLACES uses a multilevel regression and poststratification (MRP) method to generate
    estimates of each measure at the county, place (incorporated and census designated), census tract, and ZIP Code
    Tabulation Area (ZCTA) levels for adults ≥18 years in the United States.";
  - each measure definition, for asthma, COPD and CHD alike: "Model-based measure".
- **Inputs (the description):** "The 2025 release uses 2023 BRFSS data for 35 measures and 2022 BRFSS data for 5
  measures". Each of the three columns is described as "Model-based estimate for crude prevalence of … among adults,
  2023".

## Findings

1. **PLACES 2025 has no asthma, COPD or CHD estimate for any Pennsylvania tract.** The held slice has 3,408 of 3,408
   PA tracts empty for all three measures. The metadata counts 4,707 null of 83,522 tracts nationally. The I-81 and I-83
   fixtures straddle the Maryland-Pennsylvania line, so HB-129's overlay will have no estimate on the PA side.
   `hazbrief.brief.places` reports such a tract as `None`, never 0. Why PA is missing is not held.
2. **The wildfire-smoke guide's PM2.5 ranges predate the 2024 revision.** Its Table 5 (PDF p.58) prints Good as
   "0–12" and Moderate as "12.1–35.4". The AQI document in force prints 0.0-9.0 and 9.1-35.4. The parsed table takes the
   breakpoints from the AQI document. It keeps the guide's ranges as `guide_printed_pm25`, so the drift is visible.
3. **The AQI document prints two PM2.5 cells in parentheses with a superscript 3:** "(55.5 - 125.4)3" and
   "(125.5 - (225.4)3" (PDF p.19). Footnote 3 is about SO2. The values are recorded as printed. They agree with the
   2024 revision's breakpoints, but those are not held from the regulation itself (row 5).
4. **Step 3 did not run.** The task says: "if the source is not reachable at rung 1, record the refusal and stop Part
   B after step 4 with the reason, because the container builds from held bytes only." Row 2 is that refusal. Without
   the manual (row 1), the input file VSMOKE.IPT and the output tables are also unknown, so step 4's driver takes and
   checks its inputs, labels, and records and replays runs, but writes no deck and reads no output.

## The Desktop's rung-2 list, in order

1. `usfs-lavdas-1996-vsmoke-users-manual`: save `https://research.fs.usda.gov/download/treesearch/1561.pdf` as
   `corpus/inbox/usfs-lavdas-1996-vsmoke-users-manual.pdf`, then run `uv run python scripts/register_inbox.py`.
2. `usfs-srs-vsmoke-download-page`: open `https://webcam.srs.fs.usda.gov/tools/vsmoke/download.shtml`. If it resolves,
   save the page and every archive it offers into `corpus/inbox/`. If the host does not resolve there either, the source
   needs the operator: a request to the Southern Research Station.
3. `usfs-harms-lavdas-1997-vsmoke-gis`: `https://research.fs.usda.gov/download/treesearch/136.pdf`.
4. `usfs-srs-vsmoke-interface-pdf`: `https://webcam.srs.fs.usda.gov/tools/vsmoke/VSMOKE_Interface.pdf`.
5. `ecfr-40-cfr-58-appendix-g`: clip the eCFR page, including its "up to date as of" line (the HB-98 route).
6. `sfe-factsheet-2011-6-vsmoke`: `https://southernfireexchange.org/wp-content/uploads/2011-6.pdf`.
