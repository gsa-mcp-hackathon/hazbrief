# HB-135: acquisition record

**Task:** `HB-135`.
**Network:** the task's Network line (`SELDON_NETWORK_ALLOWLIST`), rung 1 only, `scripts/fetch_allowlisted.py`. The 8 hosts
not already in `corpus/allowlist.txt` were added under an HB-135 header. **Fetched:** 2026-11-08, 19:20 to 20:00 UTC. No
nested session, no browser: the Desktop works rung 2 from the list below. The inbox (`corpus/inbox/`) held no file of
this task's at launch (it holds `965071.pdf`, `ERG2020 Data Files  PHMSA.md`, `Readiness_Diagnostic_Rollup.pdf`,
`cdc_16279_DS6.pdf`, as at HB-127), so nothing was registered from it.

Logs:
- **Corpus rows** (texts): `corpus/fetch_log.jsonl`, 9 units.
- **Data units** (datasets, not documents; HB-52, HB-128 deviation 5): `corpus/landing_fetch_log.jsonl`, 6 units,
  defined in `datasets.yaml`, checked by `tools/check_datasets.py` into `datasets_held.tsv`.
- **Discovery and refusal probes:** `corpus/landing_fetch_log.jsonl` under `hb135-probe-*` ids, 38 probes, stored
  under `/tmp/hb135/probe/out` (scratch), driven by `tools/probe.py`.

URL discovery used web search for titles and URLs only. No value is taken from a search result.

## The ten items

| # | Item | Row(s) | Outcome | next_rung |
|---|---|---|---|---|
| 1 | EPCRA section 303 (42 U.S.C. 11003) | `usc-42-11003-epcra-303-2024` | **held** (govinfo, U.S. Code 2024 edition, 138,355 bytes, 2 pp.; the section's PDF opens on the page it shares with 11002's end). § 11003(a), the LEPC's plan, PDF p.1; § 11003(c), what the plan holds (facilities, transport routes for extremely hazardous substances, evacuation plans), pp.1-2. The 2023 edition and the LII copy also answer this client (`hb135-probe-usc-11003-2023`, `hb135-probe-lii-11003`). | — |
| 1 | EPCRA section 312, Tier II (42 U.S.C. 11022) | `usc-42-11022-epcra-312-2024` | **held** (govinfo 2024, 141,704 bytes, 3 pp.). § 11022(a): the inventory form goes to the LEPC, the state commission and the fire department, PDF p.1. EPA's Tier II instructions were already held (`epa-tier2-instructions-2027`, `-2017`). | — |
| 2 | 40 CFR part 68, subpart B (68.20 to 68.42) | `cfr40-part68-govinfo-2025` | **already held** (HB-22; CFR annual edition revised as of 2025-07-01). Not re-fetched. § 68.30 (population) PDF p.11; § 68.39 and § 68.42 p.12. eCFR does not serve this client: its versioner API path is robots-disallowed (`hb135-probe-ecfr-68-subpart-b`) and its current HTML page bounces to a bot challenge on unblock.federalregister.gov (`hb135-probe-ecfr-68-subpart-b-current`). The 2026 proposed rule is held (`fr-2026-03633-rmp-common-sense-proposed`). | eCFR current text: browser, if a later amendment matters |
| 3 | EPA, RMP Guidance for Offsite Consequence Analysis (EPA 550-B-99-009) | `epa-rmp-oca-guidance-2009`, `epa-rmp-oca-guidance-appendices-1999` | **already held** (HB-22): the March 2009 chapters and the 1999 appendices, as EPA serves them. Not re-fetched. Chemical-specific tables for ammonia, chlorine and sulfur dioxide are named on PDF p.18; Reference Tables 1 to 4 (neutrally buoyant, toxic endpoint) from p.58; Reference Table 10 (ammonia) p.67; Exhibit 4 (alternative-scenario generic tables) p.92. These are the TEVV reference: a brief's footprint for an RMP material can be run under the guidance's assumptions and compared to these tables. | — |
| 4 | NFPA 1620, Standard for Pre-Incident Planning | `nfpa-1620-pre-incident-planning` | **not_public** (copyrighted; reference-only by HB-22 policy, as NFPA 470, 472 and 704). www.nfpa.org is off the Network line (`hb135-probe-nfpa-1620-page`, blocked_host). Waits past submission with the three HF standards unless the operator reads it by hand. | operator (rung 3): NFPA free-access reading room, a free account, `https://www.nfpa.org/codes-and-standards/nfpa-1620-standard-development/1620` |
| 5 | Getis and Ord (1992), Geographical Analysis 24(3), DOI 10.1111/j.1538-4632.1992.tb00261.x | `getis-ord-1992-distance-statistics` | **refused_by_host** (Wiley, HTTP 403). JSTOR's robots bar this client (`hb135-probe-jstor-getis-ord`); the 2010 Springer reprint (ch. 10, DOI 10.1007/978-3-642-01976-0_10) redirects to idp.springer.com, a sign-in host (`hb135-probe-springer-getis-ord-2010-ch10`). No open copy found. | operator (rung 3): library or purchase |
| 5 | Ord and Getis (1995), Geographical Analysis 27(4), DOI 10.1111/j.1538-4632.1995.tb00912.x | `ord-getis-1995-local-spatial-autocorrelation` | **refused_by_host** (Wiley, HTTP 403) | operator (rung 3) |
| 5 | Kernel density on a network | `okabe-satoh-sugihara-2008-network-kde-csis-dp89` | **blocked_host**: the authors' free copy, CSIS Discussion Paper 89 (University of Tokyo), is on www.csis.u-tokyo.ac.jp, off the Network line. The journal version (IJGIS 23(1), 2009) is Taylor and Francis, not open. ROSAP refuses its search page to this client (`hb135-probe-rosap-search-nkde`, 403), so no public DOT report on network KDE was found at rung 1. | rung 1 with www.csis.u-tokyo.ac.jp on a task's Network line |
| 6 | The deck's future-uses slide | none | **no such slide at HEAD**: `docs/submission/deck.yaml` (`27360c05`) has no slide naming LEPC, RMP, pre-incident plan or hotspot analysis. The sentence-to-row table below is for the slide when it is written. | — |
| 7 | PHMSA hazmat incident reports (Form 5800.1) | `phmsa-hazmat-incident-reports` | **not held**. The data are only on the PHMSA OBIEE portal. data.transportation.gov `rxrf-q3m4` and `5vv3-mqcv` are `href` entries pointing at that portal, not data (`hb135-probe-dot-rxrf-q3m4-meta`, `-5vv3-mqcv-meta`). The portal's search path timed out on connect twice (`hb135-probe-phmsa-portal-search`); its root returns a 13-character script shell (`hb135-probe-phmsa-portal-root`). Locating fields, from the held form (`phmsa-dot-f-5800-1-form`, item 7, PDF p.1): city, county, state, ZIP code (if known), and street address, mile marker, yard, airport, body of water or river mile; no coordinates on that (01-2004) edition. | browser (rung 2): see the list below |
| 8 | FRA rail equipment accidents (Form 6180.54) | `fra-form54-rail-equipment-accidents`, field list `dot-fra-form54-85tf-25kj-metadata` | **held as data**: data.transportation.gov `85tf-25kj` (Public Domain U.S. Government), every report dated 2016-01-01 or later: 26,732 rows, 155 columns, 2016-01-01 to 2026-08-31, 43,165,456 bytes. Latitude and longitude non-empty and non-zero on 26,719 rows; empty before 2002 in the whole table (`fra54_reports_by_year.json`). Hazmat columns: hazmatcars, hazmatcarsdamaged, hazmatreleasedcars (151 rows above 0), personsevacuated. safetydata.fra.dot.gov's download page is a script index (`hb135-probe-fra-downloads`); the DOT portal is FRA's own published copy. | — |
| 9 | EPA RMP facility list | `epa-rmp-facility-list` (with `epa-rmp-how-to-access-information`, `epa-rmp-federal-reading-rooms`) | **not held**. EPA's RMP Public Data Tool "is offline" (the held how-to-access page). Envirofacts's FRS program table returns no RMP rows (`hb135-probe-ef-frs-pf-rmp-md`, `-rmp-contains`: `[]`), and Envirofacts has no RMP table (`hb135-probe-ef-rmp-facility`, 404). FRS's state CSV files are on ordsext.epa.gov, off the Network line (`hb135-probe-frs-state-csv-page`). **The offsite consequence analysis sections of RMP filings (the filed distances) are restricted by statute to the Federal Reading Rooms and are not acquired** (the held reading-rooms page; CAA 112(r)(7)(H) and 40 CFR part 1400, CSISSFRRA, on the held 2024 final rule, `epa-rmp-sccap-final-rule-2024-prepub`, PDF pp.186 and 194). The facility locations and inventories are public and are what the planning view plots. | rung 1 with ordsext.epa.gov on a task's Network line (FRS locations); FOIA or a reading room for non-OCA chemicals and quantities (rung 3) |
| 10 | LEHD LODES WAC, latest year | `lodes8-wac-2024`, documentation `lodes8-techdoc-8-5` | **held as data**: LODES 8, 2024 (createdate 20261014), S000 JT00, DC, MD, PA, VA and WV; 210,087 blocks, 13,927,716 jobs in all. The Census Bureau's documentation is held: LODES Technical Documentation 8.5 (`lodes8-techdoc-8-5`), "WAC – Workplace Area Characteristic data, jobs are totaled by work Census Block", PDF p.1; years 2002-2024, p.3. | — |
| 11 | A manifest row per dataset | the four `deferred_bulk_data` rows | URL, sha256 (in `datasets_held.tsv` and the row's notes), vintage (`edition`), licence (public domain, U.S. Government), the field list and the map task's use, in each row. Tabular data are held, not parsed and not extracted: the ingest records each dataset row as metadata only (`index_text_rows: 0`). | — |

## Datasets held (`datasets_held.tsv`)

| unit | sha256 | bytes | rows | measures |
|---|---|---:|---:|---|
| `fra-form54-rail-equipment-accidents-2016-2026` | `a18b348a2dc1dfb8…` | 43,165,456 | 26,732 | 26,719 with lat/lon; 151 with hazmat cars released; 2016-01-01 to 2026-08-31 |
| `lodes8-wac-2024-dc` | `8a700b12cab90319…` | 114,781 | 4,083 | C000 672,632 |
| `lodes8-wac-2024-md` | `ca4b51e8a5d5868d…` | 802,584 | 31,099 | C000 2,648,251 |
| `lodes8-wac-2024-pa` | `df77635bf1d0d0d2…` | 2,436,190 | 102,831 | C000 5,957,234 |
| `lodes8-wac-2024-va` | `e131faac86e95903…` | 1,356,318 | 56,342 | C000 3,957,886 |
| `lodes8-wac-2024-wv` | `5c95dc552bd54630…` | 360,486 | 15,732 | C000 691,713 |

The bytes stay in `corpus/raw/` (gitignored; provenance is url + sha256; HB-127 deviation 1). `check_datasets.py`
re-hashes each file against its logged sha256 before it measures.

## The institutions the future-uses slide may name, and the row that backs each

| Institution in a sentence | Backing row(s) | Where |
|---|---|---|
| LEPC emergency plan | `usc-42-11003-epcra-303-2024` | § 11003(a) and (c), PDF pp.1-2 |
| Tier II inventory the plan reads | `usc-42-11022-epcra-312-2024`; `epa-tier2-instructions-2027` | § 11022(a), PDF p.1 |
| RMP worst-case and alternative scenarios, the endpoint, the population | `cfr40-part68-govinfo-2025` | §§ 68.20-68.42; § 68.30 p.11 |
| RMP offsite consequence lookup tables (the TEVV comparison) | `epa-rmp-oca-guidance-2009`, `epa-rmp-oca-guidance-appendices-1999` | p.18, pp.58-61, p.67, p.92 |
| RMP filed distances are reading-room only | `epa-rmp-federal-reading-rooms`; `epa-rmp-sccap-final-rule-2024-prepub` | the page; PDF pp.186, 194 |
| Pre-incident plan | `nfpa-1620-pre-incident-planning` (**not_public**) | cite by title and edition only |
| Hotspot analysis (Getis-Ord Gi*) | `getis-ord-1992-distance-statistics`, `ord-getis-1995-local-spatial-autocorrelation` (**not held**) | cite by DOI only until held |
| Kernel density on a network | `okabe-satoh-sugihara-2008-network-kde-csis-dp89` (**not held**) | cite by DOI only until held |
| Daytime population | `lodes8-wac-2024`, `lodes8-techdoc-8-5` | techdoc p.1 |
| Incident locations | `fra-form54-rail-equipment-accidents` (held); `phmsa-hazmat-incident-reports` (not held) | `datasets_held.tsv` |

## The Desktop's rung-2 and rung-3 list (copy-paste)

In the operator's Chrome, saving into `corpus/inbox/` with the date saved, then
`uv run python scripts/register_inbox.py --inbox <a scratch dir holding only these files>` (the HB-98 scoping):

1. **PHMSA incidents (rung 2).** Open
   `https://portalpublic.phmsa.dot.gov/analytics/saw.dll?Portal&PortalPath=/shared/Public%20Website%20Pages/_portal/Hazmat%20Incident%20Report%20Search`,
   set the date range 2016-01-01 to the latest date, all modes, and export the result to a text file. Save it as
   `phmsa-incident-reports-2016-01-01-<to>-<date saved>.txt` (row `phmsa-hazmat-incident-reports`; a data unit: record
   its sha256 in `docs/evidence/hb135/datasets_held.tsv` by adding a unit to `datasets.yaml`, or hand it to HB-136).
2. **Getis and Ord 1992 and Ord and Getis 1995 (rung 3).** Through a library or purchase, the PDFs at
   `https://doi.org/10.1111/j.1538-4632.1992.tb00261.x` and `https://doi.org/10.1111/j.1538-4632.1995.tb00912.x`
   (rows `getis-ord-1992-distance-statistics`, `ord-getis-1995-local-spatial-autocorrelation`; each needs an
   `identify.text` from its first page; copyrighted, held reference-only).
3. **NFPA 1620 (rung 3).** Read in the free-access viewer at
   `https://www.nfpa.org/codes-and-standards/nfpa-1620-standard-development/1620`; record the edition in the row. Not
   downloaded.
4. **Rung 1 again, with a wider Network line:** `www.csis.u-tokyo.ac.jp` for
   `https://www.csis.u-tokyo.ac.jp/wp-content/uploads/2017/06/89.pdf` (row
   `okabe-satoh-sugihara-2008-network-kde-csis-dp89`), and `ordsext.epa.gov` for the FRS state files
   `https://ordsext.epa.gov/FLA/www3/state_files/state_single_{dc,md,pa,va,wv}.zip` (facility locations; whether they
   carry an RMP program link is unchecked).

## Probes (`corpus/landing_fetch_log.jsonl`, `hb135-probe-*`)

| probe id | outcome |
|---|---|
| `hb135-probe-usc-11003-2023`, `-usc-11022-2023`, `-usc-11003-2024`, `-usc-11022-2024` | fetched (govinfo section PDFs) |
| `hb135-probe-lii-11003` | fetched (LII HTML) |
| `hb135-probe-ecfr-68-subpart-b` | robots_disallowed (eCFR versioner API) |
| `hb135-probe-ecfr-68-subpart-b-current` | blocked_host (redirect to unblock.federalregister.gov) |
| `hb135-probe-dot-85tf-25kj-meta` | fetched (FRA Form 54 metadata) |
| `hb135-probe-dot-rxrf-q3m4-meta`, `-5vv3-mqcv-meta` | fetched; both `viewType: href` to the PHMSA portal |
| `hb135-probe-fra54-years` | fetched; reports, located reports and hazmat cars released by year, 1975-2026 |
| `hb135-probe-fra-downloads` | fetched; a script index, no file links |
| `hb135-probe-wiley-getis-ord-1992`, `-wiley-ord-getis-1995` | refused_by_host, 403 |
| `hb135-probe-springer-getis-ord-2010-ch10` | blocked_host (redirect to idp.springer.com) |
| `hb135-probe-jstor-getis-ord` | robots_disallowed |
| `hb135-probe-rosap-search-nkde` | refused_by_host, 403 |
| `hb135-probe-nfpa-1620-page` | blocked_host (www.nfpa.org) |
| `hb135-probe-phmsa-portal-search` | failed twice, ConnectTimeout |
| `hb135-probe-phmsa-portal-root` | script_rendered (13 visible characters) |
| `hb135-probe-lehd-lodes-root`, `-lodes8-md-wac-dir` | fetched; LODESTechDoc8.5 and the 2024 WAC files listed |
| `hb135-probe-envirofacts-services`, `-ef-dev-services`, `-ef-data-downloads`, `-ef-additional-datasets` | fetched; no RMP dataset named |
| `hb135-probe-ef-frs-pf-sample` | fetched; the FRS program-facility table answers (RCRAINFO sample) |
| `hb135-probe-ef-frs-pf-rmp-md`, `-ef-frs-pf-rmp-contains` | fetched, `[]`: no RMP rows |
| `hb135-probe-ef-frs-pf-md-count` | failed, HTTP 500 |
| `hb135-probe-ef-rmp-facility` | failed, HTTP 404 (no `rmp` schema) |
| `hb135-probe-frs-state-csv-page`, `-frs-geospatial-download` | fetched; files on ordsext.epa.gov |
| `hb135-probe-epa-rmp-access`, `-epa-rmp-how-access`, `-epa-rmp-reading-rooms` | fetched (the last two are now corpus rows) |
| `hb135-probe-cfr40-part1400-2025-v36`, `-v37` | redirected_elsewhere (govinfo error page: guessed volumes) |
