# Operator downloads

**Written by:** `HB-01d` step 3, 2026-10-21. **Rule:**
DN-002 section 3. A person in a browser is not a crawler. Save each file as the site names it,
unrenamed, into `corpus/inbox/` (gitignored). `scripts/register_inbox.py` identifies it by content
(format signature and title text), never by its name. A page saved as a browser clipping
(Markdown whose front matter records `source:`) is accepted, as the two PHMSA pages of 2026-10-21
were. When files arrive, the next task adds an `identify` rule to each entry from the saved title
page and registers them.

Each row gives the `corpus/sources.yaml` doc_id, the exact URL the fetcher tried, the page it lives
on, what the fetcher got, and why the project wants it. Outcomes are the latest `unit_done` row in
`corpus/fetch_log.jsonl`.

**Closed by:** `HB-01e`, 2026-10-21. All thirteen
wanted entries below landed in the inbox on 2026-10-21 (with Esri's ERG Materials CSV, which no
entry named) and were registered by `scripts/register_inbox.py`; each row's provenance is its
`registered` row in `corpus/operator_downloads.jsonl` (the sha256 below is the first 12
characters of it). Two entries are open, both added by HB-01e (last section).

## Landed in inbox (registered by HB-01d)

Each row's provenance is in `corpus/operator_downloads.jsonl`. The two clippings record the
`source:` and `created:` of their front matter, not a fetch log line (ADDENDUM-00).

| doc_id | Host | Status |
|---|---|---|
| `erg2020-yellow-numerical-xlsx`, `erg2020-blue-alphabetical-xlsx`, `erg2020-orange-guides-xls`, `erg2020-table1-xlsx`, `erg2020-table2-xls`, `erg2020-table3-xls` (the six English ERG2020 data files) | www.phmsa.dot.gov | landed in inbox 2026-10-21; registered |
| `phmsa-erg-api-definition` (ERG Sharing and Collaboration API page, clipping) | www.phmsa.dot.gov | landed in inbox 2026-10-21 (saved 08:01:40 -04:00); registered |
| `erg2024-landing` (ERG main page, clipping) | www.phmsa.dot.gov | landed in inbox 2026-10-21 (saved 08:03:05 -04:00); registered; text held back from the graph (see the note at the end) |
| `census-acs-general-handbook-2020` | www.census.gov (not tried by the fetcher) | landed in inbox 2026-10-20; registered |

## Landed 2026-10-21: HB-01d sources, by host (registered by HB-01e)

"Landed" gives the date and the held file's sha256 (first 12 hex characters; the full value and
the byte count are in `corpus/operator_downloads.jsonl`). The URL column is the URL the fetcher
tried; where the saved page's own `source:` differs, the registration row keeps both
(`source_url`, `requested_url`).

### www.phmsa.dot.gov (403 to this client)

| doc_id | Title | URL tried | Landed | Why |
|---|---|---|---|---|
| `phmsa-erg2020-data-files-page` | ERG2020 data files (download page) | https://www.phmsa.dot.gov/training/hazmat/erg/erg2020-data-files | landed 2026-10-21, sha256 `b5d09f45ae1f`, navigation only; **superseded 2026-10-28** by `6f00261611fa`, the page body with its file table and "Last updated: Thursday, April 4, 2024", saved by the session in the operator's Chrome (DN-002 ADDENDUM-00 rung 2, HB-62) | The six data files' own URLs and the page's "updated" date. The clipping holds the site's menus and a one-line excerpt; the file table and the date did not save. |
| `erg2016-anl-technical-report` | Development of the Table of Initial Isolation and Protective Action Distances for the 2016 ERG (Argonne, ANL/GSS-17/1, August 2017) | https://www.phmsa.dot.gov/sites/phmsa.dot.gov/files/docs/research-and-development/hazmat/reports/71026/2016-erg-technical-document.pdf | landed 2026-10-21, sha256 `944f8d9b9024` | The method behind the ERG 2016 Table 1 rows. |

### es.calwater.com (404 to this client's identity)

| doc_id | Title | URL tried | Landed | Why |
|---|---|---|---|---|
| `calwater-paws21-appendix-f` | Projection Analysis Work Sheets for Stockton District 2015 (printed 2016-05-02), served as PAWS-21 Appendix F | https://es.calwater.com/wp-content/uploads/2025/01/Appendix_F_-_Projection_Analysis_Worksheets_PAWS-21.pdf | landed 2026-10-21, sha256 `7f7a069edc5d` | The block-centroid reading of MARPLOT's count: its MARPLOT disclaimer, PDF p. 38 (Worksheet 12). |

### www.calcupa.org (403)

| doc_id | Title | URL tried | Landed | Why |
|---|---|---|---|---|
| `calcupa-2026-oca-becker` | CalARP Offsite Consequence Analysis (Becker, CUPA 2026, TU-A3, 2026-03-24) | https://www.calcupa.org/CMS15/upload-manager/presentations/CUPA-2026/8263-21257-tu-a3-offsite-consequence-analysis-becker.pdf | landed 2026-10-21, sha256 `2723ccb2553b` | The area-weighted reading, the other side of LN-01's dispute. |

### www.esri.com (403)

| doc_id | Title | URL tried | Landed | Why |
|---|---|---|---|---|
| `esri-erg-web-tool-blog` | Introducing the Emergency Response Guide Web Tool (ArcGIS Blog, 2025-06-04) | https://www.esri.com/arcgis-blog/products/arcgis-solutions/announcements/emergency-response-guide-web-tool-blog | landed 2026-10-21 (clipping), sha256 `39ef7822cf15` | The strongest zone-geometry comparator and its date. |

### community.esri.com (200, script-rendered: the server sends a 50-character shell)

| doc_id | Title | URL tried | Landed | Why |
|---|---|---|---|---|
| `esri-community-erg-web-tool` | Emergency Response Guide Web Tool (Esri Community) | https://community.esri.com/t5/arcgis-solutions-documents/emergency-response-guide-web-tool/m-p/1623484 | landed 2026-10-21 (clipping; its `source:` is https://community.esri.com/en/discussion/1617709/emergency-response-guide-web-tool), sha256 `4cb30797e500` | Names the ERG Materials CSV and the ERG Zones layer. |
| `esri-erg-materials-csv` (new, HB-01e) | ERG Materials CSV (`erg_materials.csv`) | not tried (inside ArcGIS item https://www.arcgis.com/home/item.html?id=96617df0228d42bc963358c583e1788d) | landed 2026-10-21, sha256 `bb9c279b55c5` | The comparator's own distance table. ERG 2024 values with 16 Table 1 rows at ERG2020 values; a comparator, never a pack input. |

### publicdocuments.fortworthtexas.gov (200, a document viewer page, not the PDF)

| doc_id | Title | URL tried | Landed | Why |
|---|---|---|---|---|
| `fortworth-veoci-contract-amendment-a1` (was `fortworth-veoci-contract`; renamed by HB-01e) | First Amendment to Fort Worth City Secretary Contract No. 63688 (Veoci, Inc.; CSC No. 63688-A1), with Exhibits B and C | https://publicdocuments.fortworthtexas.gov/CSODOCS/DocView.aspx?id=352954&dbid=0&repo=City-Secretary | landed 2026-10-21, sha256 `b0a87c0e9d5b` | Public evidence of Veoci's government deployment. 352954 is the Laserfiche document id; the document is an amendment, not the contract. |

### www.d4h.com (not on this task's allowlist; d4h.com redirects there)

| doc_id | Title | URL tried | Landed | Why |
|---|---|---|---|---|
| `d4h-linked-fields` | How to Autocomplete Your ICS Forms (D4H blog) | https://d4h.com/blog/autocomplete-your-ics-forms-by-linking-fields-in-d4h-incident-management | landed 2026-10-21 (clipping; its `source:` is the www.d4h.com URL after the redirect), sha256 `b08cec8c7943` | Linked fields populating ICS forms from a SitRep. |

Not wanted: `cms-hospital-general-info-page` (script-rendered). The metastore record
`cms-hospital-general-info-metastore` carries the same dates and is held.

## Landed 2026-10-21: outstanding from earlier tasks (registered by HB-01e)

| doc_id | Host and outcome | URL | Landed | Why |
|---|---|---|---|---|
| `cre-response-2024-quick-guide` | www2.census.gov, robots disallow (HB-01) | https://www2.census.gov/programs-surveys/demo/technical-documentation/community-resilience/2024/response/2024_CRE_for_Response_Quick_Guide.pdf | landed 2026-10-21, sha256 `5c89a2845e50` ("2024 Community Resilience Estimates, Disaster Response Supplement, Quick Guide, Released April 2026") | CRE for Response, the source HB-09 step 5 prefers if held (DN-003 s4). |
| `cre-response-2024-file-layout` | www2.census.gov, robots disallow (HB-01) | https://www2.census.gov/programs-surveys/demo/technical-documentation/community-resilience/2024/response/2024_CRE_for_Response_File_Layout.xlsx | landed 2026-10-21, sha256 `90a671155175` | Same. The guide and the layout document the supplement; neither is the tract CSV with margins of error (open entry below). |
| `phmsa-incident-statistics` | www.phmsa.dot.gov, 403 (HB-01) | https://www.phmsa.dot.gov/hazmat-program-management-data-and-statistics/data-operations/incident-statistics | landed 2026-10-21 (clipping), sha256 `0e1509f7300b` | Incident data context (DN-001 s5). |
| `nws-api-openapi` | api.weather.gov, robots disallow (HB-01) | https://api.weather.gov/openapi.json | landed 2026-10-21, sha256 `ae478b69cdac` (OpenAPI 3.1.2, info.version 3.12.2) | The NWS API schema. |
| `cfr49-172-101-ecfr-xml` | www.ecfr.gov, robots disallow (HB-01) | https://www.ecfr.gov/api/versioner/v1/full/2026-10-15/title-49.xml?section=172.101 | landed 2026-10-21, sha256 `10d434682842` (well-formed; the XML states no point-in-time date, only a link to the 2026-08-04 amendment, 91 FR 49310) | The current 172.101 table. GovInfo's 2025 annual edition is held (`cfr49-govinfo-bulk`). |

**The graph.** Each of these entries was already in the Squiddy graph as metadata only, so
`scripts/ingest_corpus.py` holds back the twelve whose doc_id did not change: their text does not
reach the graph until Squiddy has a re-admission path (HB-01d RESULT section 6). The renamed
amendment and the new CSV are new units; both are reference-only, so metadata only.

## Open (added by HB-01e)

| doc_id | Title | URL | Page it lives on | Why |
|---|---|---|---|---|
| `cre-response-2024-tract` | CRE for Response 2024 tract estimates (CSV), with margins of error | https://www2.census.gov/programs-surveys/demo/datasets/community-resilience/2024/response/CRE_For_Response_24_Tract.csv | the CRE for Response dataset directory on www2.census.gov (robots-disallowed to this client) | FR-CRE-01's MOE input: `PRED3_M` (and the other `_M` columns the layout names) is in the tract CSV only; the Census Data API's `/data/2024/cre` has no MOE variable (HB-09 RESULT s5). The URL is HB-01's, found in the www2 directory listing (`corpus/sources.yaml`). Neither the quick guide nor the file layout names a path or URL for the CSVs. |
| ~~`phmsa-erg2020-data-files-page` (re-save)~~ **closed by HB-62** (rung 2; the six `url:` fields filled, gap task `740b40c3` closed) | ERG2020 data files (download page) | https://www.phmsa.dot.gov/training/hazmat/erg/erg2020-data-files | itself | The 2026-10-21 clipping saved only the site navigation (link density 0.78; the page body, its file table and "updated" date are absent). Save the page body: print it to PDF, or clip with the reader-view setting so the main content is captured. The six erg2020-* entries keep `url: unresolved` until then. **2026-10-28 re-save** (sha256 `3dd78b038b68`, not registered; HB-61 RESULT ADDENDUM-01): the same text as the 10-21 copy, menus only, link density 0.77; a browser clipping again, not reader view or a PDF. |

## HB-22 (2026-10-23): fetched by the operator's browser

**Written by:** `HB-22` step 2. Every line the fetcher could
not take (off the allowlist, 403, a 404 whose bytes survive only in the Wayback Machine, or a robots disallow) was
fetched in the operator's Chrome on the operator's instruction of 2026-10-23 ("use my web browser to go fetch to the
inbox"), driven by the Claude Code session: the page fetched the document from the URL below, checked its format
signature, computed its sha256, and the browser saved it unrenamed to `~/Downloads`. The terminal is refused
`~/Downloads` by macOS, so the operator moves the files into `corpus/inbox/`, and `scripts/register_inbox.py`
identifies each by content. The page-side record of each file is `logs/2026-10-23_HB-22_browser_acquisition.jsonl`.
"sha256" is the first 12 hex characters of the in-page hash (blank for the three NTSB files, saved before the page
hashed). Status is updated from `corpus/operator_downloads.jsonl` when each file registers.

| Tier | doc_id | Title | Why the fetcher could not | URL fetched | Saved as | Bytes | sha256 | Status | Why |
|---|---|---|---|---|---|--:|---|---|---|
| Tier 1 | `erg2020-anl-technical-report` | Development of the Table of Initial Isolation and Protective Action Distances for the 2020 ERG (ANL/SSS-22/3, April 2022) | www.phmsa.dot.gov, 403 | https://www.phmsa.dot.gov/sites/phmsa.dot.gov/files/2022-04/ERG2020-ANL-report-v2.pdf | `ERG2020-ANL-report-v2.pdf` | 6211356 | `37f004e2e85d` | registered 2026-10-23 by content, `corpus/raw/erg2020-anl-technical-report.pdf` | How the ERG2020 Table 1 distances were derived. |
| Tier 1 | `cameo-chemicals-help-locs` | Help Topics for CAMEO Chemicals: Levels of Concern guide (11 pages, one clipping) | cameochemicals.noaa.gov, robots disallow /help/ | https://cameochemicals.noaa.gov/help/reference/locs_guide/overview.htm | `CAMEO Chemicals Help - Levels of Concern Guide.md` | 50594 | `643b4364719e` | registered 2026-10-23 by content, `corpus/raw/cameo-chemicals-help-locs.md`. The file moved was a 13:11Z re-clipping (57,437 bytes, `4198ecf90f65`), not the 11:10Z one recorded here; its 22 page-script blocks were stripped by one recorded rule before registration (held: 49,895 bytes, `6836bd9a8e75`; `logs/2026-10-23_HB-22_clipping_cleaning.jsonl`) | AEGL, ERPG, PAC, TEEL, IDLH as CAMEO and ALOHA use them. |
| Tier 2 | `atsdr-mmg-ammonia` | Medical Management Guidelines for Ammonia (Wayback capture of the 404 ATSDR PDF) | www.atsdr.cdc.gov, 404 (MMGs archived) | https://web.archive.org/web/20240929203156id_/https://www.atsdr.cdc.gov/mhmi/mmg126.pdf | `mmg126.pdf` | 138637 | `0bff49eb5570` | registered 2026-10-23 by content, `corpus/raw/atsdr-mmg-ammonia.pdf` | Medical management and the exposure limits (the MMGs give no protective distance; they defer to the ERG: HB-22 finding). |
| Tier 2 | `atsdr-mmg-chlorine` | Medical Management Guidelines for Chlorine (Wayback) | www.atsdr.cdc.gov, 404 | https://web.archive.org/web/20240929113633id_/https://www.atsdr.cdc.gov/MHMI/mmg172.pdf | `mmg172.pdf` | 122469 | `4a609843b3e3` | registered 2026-10-23 by content, `corpus/raw/atsdr-mmg-chlorine.pdf` | Same. |
| Tier 2 | `atsdr-mmg-ethylene-oxide` | Medical Management Guidelines for Ethylene Oxide (Wayback; not on the current portal) | www.atsdr.cdc.gov, 404 | https://web.archive.org/web/20241024111512id_/https://www.atsdr.cdc.gov/mhmi/mmg137.pdf | `mmg137.pdf` | 284090 | `068be03dbc67` | registered 2026-10-23 by content, `corpus/raw/atsdr-mmg-ethylene-oxide.pdf` | Same. |
| Tier 2 | `atsdr-mmg-hydrogen-chloride` | Medical Management Guidelines for Hydrogen Chloride (Wayback) | www.atsdr.cdc.gov, 404 | https://web.archive.org/web/20241005185054id_/https://www.atsdr.cdc.gov/MHMI/mmg173.pdf | `mmg173.pdf` | 252683 | `fe2d63ac9795` | registered 2026-10-23 by content, `corpus/raw/atsdr-mmg-hydrogen-chloride.pdf` | Same. |
| Tier 2 | `atsdr-mmg-hydrogen-fluoride` | Medical Management Guidelines for Hydrogen Fluoride (Wayback) | www.atsdr.cdc.gov, 404 | https://web.archive.org/web/20241005192243id_/https://www.atsdr.cdc.gov/mhmi/mmg11.pdf | `mmg11.pdf` | 163681 | `5b273747ff9c` | registered 2026-10-23 by content, `corpus/raw/atsdr-mmg-hydrogen-fluoride.pdf` | Same. |
| Tier 2 | `atsdr-mmg-sulfur-dioxide` | Medical Management Guidelines for Sulfur Dioxide (Wayback) | www.atsdr.cdc.gov, 404 | https://web.archive.org/web/20241112041729id_/https://www.atsdr.cdc.gov/MHMI/mmg116.pdf | `mmg116.pdf` | 132915 | `e42fe2f1e28a` | registered 2026-10-23 by content, `corpus/raw/atsdr-mmg-sulfur-dioxide.pdf` | Same. |
| Tier 3 | `ntsb-rar-05-04-graniteville` | NTSB/RAR-05/04, Graniteville SC chlorine release, 2005-01-06 | www.ntsb.gov, off the allowlist | https://www.ntsb.gov/investigations/AccidentReports/Reports/RAR0504.pdf | `RAR0504.pdf` | 1337655 | `b5489d13779e` | registered 2026-10-23 by content, `corpus/raw/ntsb-rar-05-04-graniteville.pdf` | The reported evacuation radius and the response to a TIH rail release. |
| Tier 3 | `ntsb-rar-14-01-paulsboro` | NTSB/RAR-14/01, Paulsboro NJ vinyl chloride release, 2012-11-30 | www.ntsb.gov, off the allowlist | https://www.ntsb.gov/investigations/AccidentReports/Reports/RAR1401.pdf | `RAR1401.pdf` | 2626264 | `bcc866a72f40` | registered 2026-10-23 by content, `corpus/raw/ntsb-rar-14-01-paulsboro.pdf` | Shelter-in-place and evacuation decisions; incident command findings. |
| Tier 3 | `ntsb-rir-24-05-east-palestine` | NTSB/RIR-24-05, East Palestine OH derailment and vent-and-burn, 2023-02-03 | www.ntsb.gov, off the allowlist | https://www.ntsb.gov/investigations/AccidentReports/Reports/RIR2405%20CORRECTED.pdf | `RIR2405 CORRECTED.pdf` | 6559547 | `8dd310ba15cb` | registered 2026-10-23 by content, `corpus/raw/ntsb-rir-24-05-east-palestine.pdf` | Evacuation zone, vent-and-burn decision, incident command. |
| Tier 3 | `csb-2002-04-i-mo-dpc-festus` | CSB 2002-04-I-MO, DPC Enterprises Festus MO chlorine release | www.csb.gov, off the allowlist | https://www.csb.gov/assets/1/20/dpc_report.pdf | `dpc_report.pdf` | 3128548 | `99dfbf94e6da` | registered 2026-10-23 by content, `corpus/raw/csb-2002-04-i-mo-dpc-festus.pdf` | Chlorine release, community shelter-in-place. |
| Tier 3 | `csb-2004-02-i-az-dpc-glendale` | CSB 2004-02-I-AZ, DPC Enterprises Glendale AZ chlorine release | www.csb.gov, off the allowlist | https://www.csb.gov/assets/1/20/dpc2-_final.pdf | `dpc2-_final.pdf` | 1085231 | `931a3b3a3cce` | registered 2026-10-23 by content, `corpus/raw/csb-2004-02-i-az-dpc-glendale.pdf` | Chlorine release, community evacuation. |
| Tier 3 | `csb-2003-13-i-la-honeywell-baton-rouge` | CSB 2003-13-I-LA, Honeywell Baton Rouge (chlorine, HF) | www.csb.gov, off the allowlist | https://www.csb.gov/assets/1/20/honeywell_report.pdf | `honeywell_report.pdf` | 3750640 | `40ae9d77c79b` | registered 2026-10-23 by content, `corpus/raw/csb-2003-13-i-la-honeywell-baton-rouge.pdf` | Chlorine and HF releases. |
| Tier 3 | `csb-2010-13-a-al-millard-ammonia` | CSB 2010-13-A-AL, Millard Refrigerated Services ammonia release (Safety Bulletin) | www.csb.gov, off the allowlist | https://www.csb.gov/assets/1/20/final_csb_casestudy_millard_0114_0543pm.pdf | `final_csb_casestudy_millard_0114_0543pm.pdf` | 656148 | `5b5643fc7fd9` | registered 2026-10-23 by content, `corpus/raw/csb-2010-13-a-al-millard-ammonia.pdf` | Ammonia release, offsite exposure. |
| Tier 3 | `csb-2017-01-i-ks-mgpi-atchison` | CSB 2017-01-I-KS, MGPI Processing Atchison KS chlorine-gas release (Case Study) | www.csb.gov, off the allowlist | https://www.csb.gov/assets/1/20/mgpi_case_study.pdf | `mgpi_case_study.pdf` | 3268926 | `2e8f0ef9db7b` | registered 2026-10-23 by content, `corpus/raw/csb-2017-01-i-ks-mgpi-atchison.pdf` | Chlorine gas from inadvertent mixing; community shelter-in-place. |
| Tier 3 | `csb-2024-03-i-va-cuisine-solutions-ammonia` | CSB 2024-03-I-VA, Cuisine Solutions Sterling VA ammonia release | www.csb.gov, off the allowlist | https://www.csb.gov/assets/1/20/cuisine_solutions_investigation_report_final_for_pdf1.pdf | `cuisine_solutions_investigation_report_final_for_pdf1.pdf` | 11177300 | `265d3189021d` | registered 2026-10-23 by content, `corpus/raw/csb-2024-03-i-va-cuisine-solutions-ammonia.pdf` | Ammonia release investigation report (2025). |
| Tier 3 | `csb-2024-04-i-ga-biolab-conyers` | CSB 2024-04-I-GA, Bio-Lab Conyers GA decomposition fire and toxic gas release | www.csb.gov, off the allowlist | https://www.csb.gov/assets/1/20/bio-lab_report__public_record_copy_.pdf | `bio-lab_report__public_record_copy_.pdf` | 5568830 | `bdc6fec3c673` | registered 2026-10-23 by content, `corpus/raw/csb-2024-04-i-ga-biolab-conyers.pdf` | Chlorine-bearing plume; a large evacuation and shelter-in-place. |
| Tier 3 | `phmsa-dot-f-5800-1-form` | Hazardous Materials Incident Report, DOT F 5800.1 (01-2004) | www.phmsa.dot.gov, 403 | https://www.phmsa.dot.gov/sites/phmsa.dot.gov/files/docs/IncidentForm010105.pdf | `IncidentForm010105.pdf` | 227569 | `58f1de89705a` | registered 2026-10-23 by content, `corpus/raw/phmsa-dot-f-5800-1-form.pdf` | The vocabulary of the incident data already catalogued. |
| Tier 3 | `phmsa-dot-f-5800-1-instructions` | Guide for Preparing Hazardous Materials Incidents Reports (effective 2005-01-01) | www.phmsa.dot.gov, 403 | https://www.phmsa.dot.gov/sites/phmsa.dot.gov/files/docs/reporting_instructions_rev.pdf | `reporting_instructions_rev.pdf` | 4357025 | `e3d9359fc1aa` | registered 2026-10-23 by content, `corpus/raw/phmsa-dot-f-5800-1-instructions.pdf` | Same. |
| Tier 4 | `nrt-1-hazmat-emergency-planning-guide-2001` | NRT-1 Hazardous Materials Emergency Planning Guide, Updated 2001 | nrt.org, off the allowlist | https://nrt.org/sites/2/files/NRT-1%202001%20update.pdf | `NRT-1 2001 update.pdf` | 1206073 | `c862e9f0ce64` | registered 2026-10-23 by content, `corpus/raw/nrt-1-hazmat-emergency-planning-guide-2001.pdf` | The planning guide LEPC response plans follow. |
| Tier 4 | `fema-elg-0300-student-manual` | E/L/G 0300 ICS 300 Student Manual (State of Nevada DEM copy; FEMA does not publish it) | www.oem.nv.gov, off the allowlist | https://www.oem.nv.gov/uploadedFiles/demnvgov/content/raining/ICS300_Complete_SM.pdf | `ICS300_Complete_SM.pdf` | 13418496 | `e727627c2530` | registered 2026-10-23 by content, `corpus/raw/fema-elg-0300-student-manual.pdf` | The ICS 300 course the 201 is used within. |

Not on this list: the IS-200.c student manual and the sample completed ICS 201 are members of the fetched
ZIP `fema-is-200c-course-zip`, extracted into the inbox by the session (`logs/2026-10-23_HB-22_zip_members.jsonl`).
Not found anywhere (HB-22 inventory, searches recorded): an ACS handbook for emergency management (line 5) and CRE
for Response technical documentation beyond the quick guide (line 7b). NFPA 470/472/704 and ANSI/ISA-18.2 are
reference-only by policy and are not to be acquired.

## HB-23 (2026-10-23): for the operator's browser

**Written by:** `HB-23` step 2. These are the lines the fetcher could
not take: off the allowlist, a 403, or a 404 whose bytes survive only in the Wayback Machine. Save each file into
`corpus/inbox/` unrenamed. `scripts/register_inbox.py` identifies it by a phrase from its own title page, never by
its filename. The HB-22 route (the session driving the operator's Chrome) was not available to this session, because
the Claude in Chrome tools were not connected. So this is a list for the operator's inbox pass. For a web page,
save the page as HTML (File > Save Page As, "Webpage, HTML Only") or clip it to Markdown.

| Tier | doc_id | Title | Why the fetcher could not | URL to fetch | Expected file | Bytes (host-reported) | Status |
|---|---|---|---|---|---|--:|---|
| 5c | `fema-elg-0400-student-manual` | E/L/G 0400 ICS 400 Student Manual, April 2019 v1.0 (State of Nevada DEM copy; FEMA does not publish it) | www.oem.nv.gov, off the allowlist | https://www.oem.nv.gov/siteassets/oem.nv.gov/training/ELG400_Complete_SM.pdf | `ELG400_Complete_SM.pdf` | 11804672 | open |
| 5c | `fema-is-800d-student-manual` | IS-800.d National Response Framework, An Introduction, Student Manual (08/2020); Wayback capture of the 404 FEMA PDF | training.fema.gov, 404 (course "Temporarily Unavailable") | http://web.archive.org/web/20241213094734id_/https://training.fema.gov/emiweb/is/is800d/english/student%20manual/el0800.d%20sm.pdf | `el0800.d sm.pdf` | 2618581 | open |
| 5c | `phmsa-hmr-overview-page` | PHMSA "Hazardous Materials Regulations" page (a clipping) | www.phmsa.dot.gov, 403 | https://www.phmsa.dot.gov/standards-rulemaking/hazmat/hazardous-materials-regulations | the saved page (`.html` or `.md`) | | open |
| 5b | `ntsb-rar-04-01-minot` | Derailment of Canadian Pacific Railway Freight Train 292-16 and Subsequent Release of Anhydrous Ammonia Near M | www.ntsb.gov, off the allowlist | https://www.ntsb.gov/investigations/AccidentReports/Reports/RAR0401.pdf | `RAR0401.pdf` | 1520861 | open |
| 5b | `ntsb-rar-06-03-macdona` | Collision of Union Pacific Railroad Train MHOTU-23 With BNSF Railway Company Train MEAP-TUL-126-D With Subsequ | www.ntsb.gov, off the allowlist | https://www.ntsb.gov/investigations/AccidentReports/Reports/RAR0603.pdf | `RAR0603.pdf` | 3791764 | open |
| 5b | `ntsb-hzm-02-01-riverview` | Hazardous Materials Release From Railroad Tank Car With Subsequent Fire at Riverview, Michigan, July 14, 2001 | www.ntsb.gov, off the allowlist | https://www.ntsb.gov/investigations/AccidentReports/Reports/HZM0201.pdf | `HZM0201.pdf` | 996430 | open |
| 5b | `ntsb-hzm-04-01-calamus` | Nurse Tank Failure With Release of Hazardous Materials Near Calamus, Iowa, April 15, 2003 | www.ntsb.gov, off the allowlist | https://www.ntsb.gov/investigations/AccidentReports/Reports/HZM0401.pdf | `HZM0401.pdf` | 471223 | open |
| 5b | `ntsb-hzb-04-01-middletown` | Hazardous Materials Accident Brief: Release of Hazardous Materials From Cargo Tank, Middletown, Ohio, August 2 | www.ntsb.gov, off the allowlist | https://www.ntsb.gov/investigations/AccidentReports/Reports/HZB0401.pdf | `HZB0401.pdf` | 341013 | open |
| 5b | `ntsb-hzm-12-01-sum-swansea` | Cargo Hose Rupture and Release of Anhydrous Ammonia During Offloading of a Werner Transportation Services Carg | www.ntsb.gov, off the allowlist | https://www.ntsb.gov/investigations/AccidentReports/Reports/HZM1201S.pdf | `HZM1201S.pdf` | 969601 | open |
| 5b | `ntsb-hzm-19-01-new-martinsville` | Rupture of a DOT-105 Rail Tank Car and Subsequent Chlorine Release at Axiall Corporation, New Martinsville, We | www.ntsb.gov, off the allowlist | https://www.ntsb.gov/investigations/AccidentReports/Reports/HZM1901.pdf | `HZM1901.pdf` | 1682868 | open |
| 5b | `ntsb-hzir-22-01-beach-park` | Hazardous Materials Investigation Report: Anhydrous Ammonia Release from a Nurse Tank Trailer During Transport | www.ntsb.gov, off the allowlist | https://www.ntsb.gov/investigations/AccidentReports/Reports/HZIR2201.pdf | `HZIR2201.pdf` | 697091 | open |
| 5b | `ntsb-hir-25-06-teutopolis` | Cargo Tank Combination Vehicle Roadway Departure, Rollover, and Release of Anhydrous Ammonia, Teutopolis, Illi | www.ntsb.gov, off the allowlist | https://www.ntsb.gov/investigations/AccidentReports/Reports/HIR2506.pdf | `HIR2506.pdf` | 3201466 | open |
| 5b | `ntsb-rir-26-07-bordulac` | Canadian Pacific Kansas City Railroad Derailment with Subsequent Hazardous Materials Release and Fire, Bordula | www.ntsb.gov, off the allowlist | https://www.ntsb.gov/investigations/AccidentReports/Reports/RIR2607.pdf | `RIR2607.pdf` | 5193266 | open |
| 5b | `csb-2004-11-i-ca-sterigenics-ontario` | Investigation Report: Sterigenics | www.csb.gov, off the allowlist | https://www.csb.gov/assets/1/20/sterigenics_report.pdf | `sterigenics_report.pdf` | 1103203 | open |
| 5b | `csb-2023-03-i-la-dow-plaquemine` | Explosions, Fires, and Toxic Ethylene Oxide Release at Dow Louisiana Operations, Plaquemine, Louisiana, Incide | www.csb.gov, off the allowlist | https://www.csb.gov/assets/1/20/dow_investigation_report-final_(002).pdf | `dow_investigation_report-final_(002).pdf` | 3042444 | open |
| 5b | `csb-2019-04-i-pa-pes-philadelphia` | Fire and Explosions at Philadelphia Energy Solutions Refinery Hydrofluoric Acid Alkylation Unit, Philadelphia, | www.csb.gov, off the allowlist | https://www.csb.gov/assets/1/20/pes_final_report_published_october_2022_r1.pdf | `pes_final_report_published_october_2022_r1.pdf` | 7503916 | open |
| 5b | `csb-2023-02-i-la-honeywell-geismar` | Three Catastrophic Hydrogen Fluoride Incidents at Honeywell Geismar, Geismar, Louisiana | www.csb.gov, off the allowlist | https://www.csb.gov/assets/1/20/honeywell_geismar_investigation_report_-_final.pdf | `honeywell_geismar_investigation_report_-_final.pdf` | 8419362 | open |
| 5b | `csb-2008-06-i-tx-goodyear-houston` | Case Study: Heat exchanger rupture and ammonia release in Houston, Texas | www.csb.gov, off the allowlist | https://www.csb.gov/assets/1/20/case_study.pdf | `case_study.pdf` | 808139 | open |
| 5b | `csb-2003-11-i-ky-dd-williamson-louisville` | Investigation Report: Catastrophic Vessel Failure | www.csb.gov, off the allowlist | https://www.csb.gov/assets/1/20/dd_report.pdf | `dd_report.pdf` | 713719 | open |
| 5b | `csb-2020-05-i-la-biolab-westlake` | Chemical Reaction, Decomposition, and Toxic Gas Release at Bio-Lab, Inc., Westlake, LA, Incident Date August 2 | www.csb.gov, off the allowlist | https://www.csb.gov/assets/1/20/biolab_investigation_report_2023-4-24_r11.pdf | `biolab_investigation_report_2023-4-24_r11.pdf` | 15058893 | open |
| 5b | `csb-2005-06-i-la-chlorine-esd-bulletin` | Safety Bulletin: Emergency Shutdown Systems for Chlorine Transfer (No. 2005-06-I-LA) | www.csb.gov, off the allowlist | https://www.csb.gov/assets/1/20/csbchlorineshutdownbulletin.pdf | `csbchlorineshutdownbulletin.pdf` | 381320 | open |
| 5b | `csb-2009-14-i-tx-citgo-corpus-christi-urgent-recs` | Urgent Recommendations | www.csb.gov, off the allowlist | https://www.csb.gov/assets/1/20/urgent_recommendations_to_citgo_-_final_board_vote_copy1.pdf | `urgent_recommendations_to_citgo_-_final_board_vote_copy1.pdf` | 22689 | open |

## HB-46 (2026-10-25): what DN-012 cites

Save into `corpus/inbox/` unrenamed, then run `uv run python scripts/register_inbox.py` from the repository root.

| Tier | doc_id | Title | Why the fetcher could not | URL to fetch | Expected file | Bytes (host-reported) | Status |
|---|---|---|---|---|---|--:|---|
| DN-012 | `klein-1988-ari-tr-796-fireground` | Rapid Decision Making on the Fire Ground (ARI Technical Report 796, June 1988) | apps.dtic.mil, HTTP 403 to the fetcher (robots.txt included) | https://apps.dtic.mil/sti/pdfs/ADA199492.pdf | `ADA199492.pdf` | | open |
