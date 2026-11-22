# HB-127 Part A: acquisition record

**Task:** `HB-127`.
**Network:** the task's Network line (`SELDON_NETWORK_ALLOWLIST`), rung 1 only, `scripts/fetch_allowlisted.py`. The 13
hosts not already in `corpus/allowlist.txt` were added under an HB-127 header. **Fetched:** 2026-11-08 02:11 to 02:16 UTC
(2026-11-07 local). No nested session, no browser: the Desktop works rung 2 from the list below.

Corpus rows log to `corpus/fetch_log.jsonl`. Discovery and refusal probes (not corpus rows) log to
`corpus/landing_fetch_log.jsonl` under `hb127-probe-*` ids (the HB-52 rule: the corpus log names only `sources.yaml` ids).

## What each wanted item came to

| # | Item | doc_id | Outcome | next_rung |
|---|---|---|---|---|
| 1 | PHMSA Hazmat Biennial Report, Jan 2021 | `phmsa-hazmat-biennial-report-2021` | **refused_by_host** (HTTP 403, hazmat.dot.gov). The same path on www.phmsa.dot.gov also 403s (`hb127-probe-phmsa-biennial-2021-www`), and so does the newer 2019-2020 report, February 2023 (`hb127-probe-phmsa-biennial-2019-2020-www`, `https://www.phmsa.dot.gov/sites/phmsa.dot.gov/files/2023-06/2019-2020-Biennial-Report.pdf`). | browser (rung 2) |
| 2 | BTS TSAR 2024 Table 5-5: page | `bts-tsar-2024-t5-5-page` | **refused_by_host** (HTTP 403, www.bts.gov) | browser |
| 2 | BTS TSAR 2024 Table 5-5: workbook | `bts-tsar-2024-t5-5-xlsx` | **refused_by_host** (HTTP 403, www.bts.gov) | browser |
| 2 | BTS TSAR 2024, the report | `bts-tsar-2024` | **fetched** from the National Transportation Library (ROSAP, `rosap.ntl.bts.gov/view/dot/79039`), another rung-1 copy of the report www.bts.gov hosts. Table 5-5 is on PDF p.161 (printed 5-24). It prints incidents by mode, not deaths, injuries or damages. | — |
| 3 | BTS NTS Table 2-6 | `bts-nts-table-2-6` | **refused_by_host** (HTTP 403, www.bts.gov) | browser |
| 4 | PHMSA 10 Year Incident Summary Reports | none (no file in the inbox) | **blocked_host**: portalpublic.phmsa.dot.gov is off the Network line and is an OBIEE application (`hb127-probe-phmsa-10yr-portal`). `corpus/inbox/` held no `phmsa-10yr-*` file at launch (it holds `965071.pdf`, `ERG2020 Data Files  PHMSA.md`, `Readiness_Diagnostic_Rollup.pdf`, `cdc_16279_DS6.pdf`, none of them this task's). Nothing was registered. | browser (rung 2): save "All Modes" and "Rail" as `corpus/inbox/phmsa-10yr-*.{pdf,html}` with the date saved |
| 5 | ATSDR, chlorine releases 1993-2000 | `atsdr-hsees-chlorine-1993-2000` | **fetched** (CDC Stacks). It is the authors' submitted manuscript of JOEM 2002;44:906-13, marked public domain on its first page. | — |
| 6 | ATSDR HSEES cumulative 1993-1997 | `atsdr-hsees-cumulative-1993-1997` | **failed** (HTTP 404 at `https://atsdr.cdc.gov/HS/hsees/Cum93-97.PDF`). www.atsdr.cdc.gov is off the Network line (`hb127-probe-atsdr-cum93-97-www`, blocked_host). A capture of the report's HTML page is in the UNT End of Term 2008 archive: `https://webarchive.library.unt.edu/eot2008/20090506144140mp_/http:/www.atsdr.cdc.gov/HS/HSEES/Cum1993-1997.html`. | rung 1 again, with webarchive.library.unt.edu on a task's Network line; else browser |
| 7 | ATSDR HSEES biennial 1999-2000 | `atsdr-hsees-biennial-1999-2000` | **fetched**. The Stacks record (`hb127-probe-stacks-131321`) links `cdc_131321_DS1.pdf`. | — |
| 8 | CDC MMWR, HSEES 1990-1992 | `cdc-mmwr-hsees-1990-1992` | **fetched** (HTML, 37,823 bytes, passes the HTML check). | — |
| 9 | EPA RIA, 2024 RMP rule (docket 0587) | `epa-rmp-sccap-ria-2024` | **refused_by_host** (HTTP 403, downloads.regulations.gov). www.regulations.gov also 403s (`hb127-probe-regs-2022-0174-0003`). | browser |
| 9 | EPA's own copy of the 2024 final rule | `epa-rmp-sccap-final-rule-2024-prepub` | **fetched** (www.epa.gov). Its preamble prints the RIA's damages table (Table 3, PDF p.21, $540.23 million per year). EPA's final-rule page links no RIA (`hb127-probe-epa-rmp-final-rule-page`): the RIA is only on regulations.gov. | — |
| 10 | EPA 2016 NPRM Technical Background Document | none | **not found on epa.gov**. The RMP final-rule, proposed-rule and publications pages (`hb127-probe-epa-rmp-*`) link no TBD. A web search of epa.gov found none for 2016 (it found the 2022 TBD, cited by the 2024 rule, footnote 7, PDF p.13, as holding the 2004-2020 accident list in Appendix A). Both are on regulations.gov (dockets EPA-HQ-OEM-2015-0725 and EPA-HQ-OLEM-2022-0174), which refuses this client. The 2016 NPRM preamble is 81 FR 13637 (2016-03-14) on www.govinfo.gov, which is in `corpus/allowlist.txt` but not on this task's Network line. No row was added: no document URL was established. | rung 1 with www.govinfo.gov on a task's Network line (the NPRM); browser for the TBD |
| 11 | NTSB Graniteville RAR-05/04 | `ntsb-rar-05-04-graniteville` | **already held** (HB-22, operator download, text indexed). Not re-fetched. | — |
| 12 | NTSB East Palestine RIR-24/05 | `ntsb-rir-24-05-east-palestine` | **already held** (HB-22). Not re-fetched. | — |
| 12 | Norfolk Southern's stated total cost | none | **blocked_host**: www.sec.gov is off the Network line (`hb127-probe-sec-nsc-10k`, the EDGAR 10-K list for CIK 702165). The cost cell is the Desktop's. | browser, or rung 1 with www.sec.gov on a task's Network line |

## The Desktop's rung-2 list (copy-paste)

For the Desktop thread, in the operator's Chrome, saving into `corpus/inbox/` with the date saved (then
`scripts/register_inbox.py --inbox <a scratch dir holding only these files>`, the HB-98 scoping):

1. `https://hazmat.dot.gov/sites/phmsa.dot.gov/files/2021-01/HAZMAT%20Biennial%20Report%20-%20Jan%202021.pdf`
   (row `phmsa-hazmat-biennial-report-2021`; it needs an `identify.text` from the title page).
2. `https://www.bts.gov/sites/bts.dot.gov/files/2025-04/T5-5%20Hazmat%20Transport%20Incidents.xlsx` (row
   `bts-tsar-2024-t5-5-xlsx`), and its page
   `https://www.bts.gov/browse-statistical-products-and-data/info-gallery/hazardous-materials-transportation-incidents-1`
   (row `bts-tsar-2024-t5-5-page`).
3. `https://www.bts.gov/content/hazardous-materials-fatalities-injuries-accidents-and-property-damage-data` (row
   `bts-nts-table-2-6`), with the table's own XLSX if the page links one.
4. `https://portalpublic.phmsa.dot.gov/analytics/saw.dll?Portal&PortalPath=/shared/Public%20Website%20Pages/_portal/10%20Year%20Incident%20Summary%20Reports`:
   the "All Modes" and "Rail" summary tables for the latest ten years, as `phmsa-10yr-all-modes-<date>.pdf` and
   `phmsa-10yr-rail-<date>.pdf` (new rows needed).
5. `https://www.regulations.gov/document/EPA-HQ-OLEM-2022-0174-0587`, its PDF (row `epa-rmp-sccap-ria-2024`).
6. The 2016 NPRM Technical Background Document in docket EPA-HQ-OEM-2015-0725 on regulations.gov (new row needed).
7. Norfolk Southern's latest 10-K on sec.gov, for the East Palestine total cost (new row needed).

## Provenance probes (`corpus/landing_fetch_log.jsonl`)

| probe id | URL | outcome |
|---|---|---|
| `hb127-probe-epa-rmp-final-rule-page` | `https://www.epa.gov/rmp/risk-management-program-safer-communities-chemical-accident-prevention-final-rule` | fetched; links no RIA or TBD |
| `hb127-probe-epa-rmp-rulemakings-page` | `https://www.epa.gov/rmp/rulemakings-and-federal-register-notices-risk-management-program` | failed, HTTP 404 (a guessed URL) |
| `hb127-probe-regs-0587-pdf` | `https://downloads.regulations.gov/EPA-HQ-OLEM-2022-0174-0587/content.pdf` | refused_by_host, 403 |
| `hb127-probe-stacks-131321` | `https://stacks.cdc.gov/view/cdc/131321` | fetched; links `cdc_131321_DS1.pdf` |
| `hb127-probe-epa-rmp-sccap-proposed-page` | `https://www.epa.gov/rmp/risk-management-program-safer-communities-chemical-accident-prevention-proposed-rule` | fetched; links regulations.gov documents 0003, 0065, 0066, 0093 only |
| `hb127-probe-epa-rmp-publications-page` | `https://www.epa.gov/rmp/chemical-accident-prevention-publications` | fetched; no RMP accident-history document |
| `hb127-probe-bts-t5-5-page` | the Table 5-5 page | refused_by_host, 403 |
| `hb127-probe-atsdr-cum93-97-www` | `https://www.atsdr.cdc.gov/HS/HSEES/Cum93-97.PDF` | blocked_host (off the Network line) |
| `hb127-probe-phmsa-biennial-2021-www` | the 2021 report on www.phmsa.dot.gov | refused_by_host, 403 |
| `hb127-probe-phmsa-biennial-2019-2020-www` | `https://www.phmsa.dot.gov/sites/phmsa.dot.gov/files/2023-06/2019-2020-Biennial-Report.pdf` | refused_by_host, 403 |
| `hb127-probe-phmsa-10yr-portal` | the OBIEE portal | blocked_host |
| `hb127-probe-sec-nsc-10k` | `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000702165&type=10-K` | blocked_host |
| `hb127-probe-regs-2022-0174-0003` | `https://www.regulations.gov/document/EPA-HQ-OLEM-2022-0174-0003` | refused_by_host, 403 |

URL discovery used web search (titles and URLs only, no page content taken as evidence). Every value in
`base_rates.tsv` is read from a held file.
