# ERG data files: inspection record

**Written by:** `HB-01d` step 6, 2026-10-21. **For:** HB-03b
(to be written). Nothing was built from these files. **Read with:** `scripts/corpus_text.py`
(`xlsx_blocks`; `xls_blocks` through xlrd 2.0.2), on the held bytes in `corpus/raw/`. The sha256 of
each file is in `corpus/operator_downloads.jsonl` or `corpus/fetch_log.jsonl`. "Rows" counts
non-empty rows. "Data rows" excludes titles, headers, footers and legends.

## 1. PHMSA ERG2020 data files (English)

Operator downloads, 2026-10-21, from https://www.phmsa.dot.gov/training/hazmat/erg/erg2020-data-files
(the page refuses this client; the files' own URLs are not known, so each entry says `url:
unresolved`). Encoding: the three `.xlsx` files are OOXML workbooks (zip; UTF-8 XML; shared
strings), written by Microsoft Excel. The three `.xls` files are BIFF8 (OLE2 compound file; xlrd
reports BIFF version 80 and `utf_16_le` strings). None carries a licence or reuse marking in its
cells.

| doc_id | File (as saved) | Format | Sheet(s) | Rows | Data rows | Columns (header row as printed) |
|---|---|---|---|--:|--:|---|
| `erg2020-yellow-numerical-xlsx` | ERG2020_Pages_29-91_Numerical_ID_Yellow_pages - English.xlsx | xlsx | `Sheet1` (A1:T2907) | 2,907 | 2,906 (1,981 distinct ID numbers) | `ID No.`, `Guide No.`, `Name of material`, `TIH`, `WR`, `CB`, `Order #`, plus a production note in H1 ("If there is an X, W or Z in columns D, E, F, the entry must be highlighted in Green ...") |
| `erg2020-blue-alphabetical-xlsx` | ERG2020_Pages_93-155_Alphabetical_Material_Blue_pages_English.xlsx | xlsx | `Sheet1` (A1:AD2907) | 2,907 | 2,906 | `Name of material`, `Guide No.`, `ID No.`, `TIH`, `WR`, `CB`, `Order #`, the same note |
| `erg2020-orange-guides-xls` | ERG2020_Pages_158-285_Orange_Guide_pages_English.xls | xls | `Sheet1` (4,136 x 7) | 4,132 | 64 guides (`GUIDE 111` to `GUIDE 174`) | No header. One cell per printed line: `GUIDE nnn`, the title, section headings (`POTENTIAL HAZARDS`, `FIRE OR EXPLOSION`, ...), then bullet lines (`· ...`). B1 carries a production note ("Must make sure that the bottom of each orange guide page, it says ERG 2020, not ERG 2016"). |
| `erg2020-table1-xlsx` | ERG2020_Pages_296-343_TIHWR_Green_Table_1_English.xlsx | xlsx | `eng_units` (A1:U601) | 599 | 593 (273 distinct ID numbers; 10 with large spills "Refer to table 3") | A four-row header: title; `SMALL SPILLS` / `LARGE SPILLS`; `First ISOLATE in all Directions` / `Then PROTECT persons Downwind during`; then `ID No.`, `Guide`, `NAME OF MATERIAL`, and per spill size `Meters`, `(Feet)`, `DAY Kilometers (Miles)`, `NIGHT Kilometers (Miles)`. Each distance is two cells, a unit-suffixed value (`60 m`, `0.3 km`, `11.0+ km`) and its parenthesized equivalent (`(200 ft)`, `(0.2 mi)`). Two footer rows are production notes. |
| `erg2020-table2-xls` | ERG2020_Pages_345-349_TIHWR_Green_Table_2_English.xls | xls | `Table 2` (132 x 4) | 128 | 109 | `ID No.`, `Guide No.`, `Name of Material`, `TIH Gas(es) Produced`; then an 18-row legend of gas symbols (`Cl2 Chlorine`, `SO2 Sulfur dioxide`, ...) and "Use this list only when material is spilled in water." |
| `erg2020-table3-xls` | ERG2020_Pages_351-353_TIHWR_Green_Table_3_English.xls | xls | `Sheet1` (41 x 15) | 34 | 22 container rows for six gases | A five-row header: title; isolate/protect; `DAY` / `NIGHT`; the three wind bands each (`Low wind (<6 mph = <10 km/h)`, `Moderate wind (6-12 mph = 10-20 km/h`, `High wind (>12 mph = >20 km/h)`); units `Meters`, `(Feet)`, then `km`, `(Miles)` six times. Per gas a heading row (`TRANSPORT CONTAINER`, `UN1017 Chlorine: Large Spills`), then one row per container: name, isolate m, (ft), then six km/(mi) pairs (day low, moderate, high; night low, moderate, high). Values are bare numbers; `11+` keeps its plus. Gases: UN1005 (4 containers), UN1017 (4), UN1040 (3), UN1050/UN2186 (4), UN1052 (3), UN1079 (4). |

**How they relate to `packs/schema/erg.schema.json` (schema version 2).**

- The yellow and blue files are the `index` (`ErgIndexEntry`: `un`, `names[]` of `ErgIndexName`
  `{name, guide, locator}`, `in_table1`) and `name_index` in tabular form. `TIH`/`WR`/`CB` marks
  (`X`, `W`, `Z`) are what the schema derives `in_table1` from. The schema reads the ERG 2024 PDF's
  yellow pages. These are the ERG 2020 rows, keyed by `Order #` as well as ID.
- The Table 1 file maps onto `ErgMaterial.table1` (`Table1Entry`: `name`, `small`/`large`
  `{isolate {m, ft}, protect_day {km, mi, plus}, protect_night {km, mi, plus}}`,
  `large_refer_to_table3`). The cell pairs are the schema's metric/imperial pairs. A trailing `+`
  is `plus: true`. "Refer to table 3" is `large_refer_to_table3`.
- The Table 3 file maps onto `ErgMaterial.table3` (`Table3Row`: `container`, `isolate {m, ft}`,
  `day` / `night` each `{low, moderate, high}` of `{km, mi, plus}`). Its wind-band header row is
  `table3_wind_bands` (`WindBand`: `band`, `label`, `mph_min/max`, `kmh_min/max`).
- The orange file is the text of `ErgGuide.sections`. `GuideEvacuation` distances sit in its
  `PUBLIC SAFETY` and `EVACUATION` bullet lines, as in the PDF.
- Table 2 has no counterpart in the schema (the pack does not carry water-reactive gases).

**Edition caution, measured.** These are ERG **2020** values. The packs are ERG **2024**. Table 3
changed between the editions. UN1017 Chlorine, rail tank car, day, low wind: 10.1 km (6.3 mi) in
this file, 9.6 km (6.0 mi) in `packs/erg.json` (erg2024-en-pdf p. 343). Table 1 changed too:
UN1017 small spill, night: 1.4 km (0.9 mi) here, 1.5 km (0.9 mi) in ERG 2024 (p. 292). So a
disagreement between these files and the ERG 2024 pack is expected, and only rows that did not
change between editions can corroborate each other. The files' real use is as PHMSA's own
statement of the table *structure*. The ERG 2024 Summary of Changes (`erg2024-summary-of-changes`)
is what says which rows changed.

## 2. `Esri/solutions-erg-widget` bundled table

`esri-solutions-erg-widget-materials`: `EmergencyResponseGuide/guide/materials.json` at master
0fb5697 (tag APR2018), 167,514 bytes, UTF-8 JSON (stored as `corpus/raw/...materials.txt` because
raw.githubusercontent.com serves it as `text/plain`; the bytes are the JSON). The widget's
`Version.txt` says "ArcGIS Solutions - September 2016 Release", and `guide/ERG Sources.pdf` names
`ERG2016.pdf` (PHMSA) as its source.

**What it encodes.** A list of 679 objects, one per material row (`IDNum`, `GuideNum`,
`Material`), with Table 1 distances as bare integers **in metres** (`SM_ISO`, `SM_DY`, `SM_NTE`,
`LG_ISO`, `LG_DY`, `LG_NTE`: small/large isolate, day and night protect), `FIRE_ISO`, flags
(`TIH`, `TABLE2`, `TABLE3`, `POLYMERIZE`, `ATM`, `BLEVE`), and for the 8 Table 3 materials one
key per container, time and wind band (`RAIL_ISO`, `RAILDYLOW` ... `RAILNTEHI`; `SEMI*` for highway
tank truck, `MTON*` multiple ton cylinders, `STON*` small cylinders or single ton cylinder, `AG*`
agricultural nurse tank, `MSM*` multiple small cylinders). Eight objects carry BLEVE distances by
tank volume (`BLV100L` ... `BLV140000L`). Chlorine (`IDNum` 1017): `RAILDYLOW` 9900, against
10.1 km in ERG 2020 and 9.6 km in ERG 2024.

**Relation to the schema.** Field for field the same content as `ErgMaterial.table1`/`table3`,
flattened, metric only, no miles, no `plus` flag (a "+" distance is a bare number), and no
locator. It cannot be a source of record. As a cross-check it is a fifth, ERG 2016, rendering
(LN-01 s6), usable only for rows unchanged since 2016. Its BLEVE table is the one thing it carries
that the pack schema does not.

**ERG 2016 method (HB-01e).** The 2016 technical report is held (`erg2016-anl-technical-report`,
ANL/GSS-17/1, August 2017, `corpus/raw/erg2016-anl-technical-report.pdf`). Its appendices give the
values, not the method: Appendix A, Table A.1, is Table 1 (PDF pp. 133-154), and Appendix B,
Tables B.1-B.6, is Table 3 (PDF pp. 157-160). The method is in the body: "The 90th percentile
safe distance values for each of these groups are the PADs that appear in Table 1" (abstract,
PDF p. 18), worked in section 5.1.1 (PDF p. 113, printed p. 97).

**Esri's current table is not this one (HB-01e).** The web tool's `erg_materials.csv`
(`esri-erg-materials-csv`, 2,915 rows, the same field names in snake case) carries ERG **2024**
values, not 2016. Its chlorine rail, day, low-wind cell is 9,600 m. Its Table 3 rows for UN1017,
UN1005 and UN1050 equal the pack in all 42 cells checked, and differ from Argonne's ERG2016
Tables B.1, B.2 and B.4. In Table 1, 540 of its 556 UN-numbered rows equal ERG 2024 and 16 keep
ERG2020 values (chlorine's small-spill night distance among them: 1,400 m against 2024's 1.5 km).

## 3. `Great-Bucket/omni-responder` `data/hazmat_db.json`

`omni-responder-hazmat-db`: main 4426032 (2026-08-19), 1,726 bytes, UTF-8 JSON (stored as `.txt`,
as above). **What it encodes:** a list of **3** objects (UN1017, UN1203, UN1830) with
`chemical_name`, `hazard_class`, `visual_indicators[]`, `initial_isolation_distance_meters`,
`day_protection_distance_km`, `night_protection_distance_km`, `fire_response`, `ppe_required`.
Its chlorine row (100 m, 0.8 km day, 2.3 km night) matches no ERG edition's Table 1 for UN1017
(ERG 2024: 60 m, 0.3 km, 1.5 km small spill; ERG 2020: 60 m, 0.3 km, 1.4 km). It cites no page.

**Relation to the schema.** A three-row demonstration fixture with untraceable values, not
"ERG-2024-derived" data (LN-01 s2). It is not usable as a cross-check, and HB-03b should not read it.

## 4. The ERG app deep-link API (ADDENDUM-00)

`phmsa-erg-api-definition`: the operator's browser clipping of https://www.phmsa.dot.gov/erg-api-definition
(saved 2026-10-21T08:01:40-04:00; the page says "ERG 2020 Version 3.1, December 2020"). It is not
a data API. It specifies universal links (iOS) and app links (Android) that open the ERG2020 mobile
app, or the DOT web page that offers it, at a material, guide, reference topic, IED or BLEVE
entry. Its `material` path with `showMap=true` draws PHMSA's own protective distance cone for a
scenario. That makes it the authoritative input vocabulary for a protective distance query.

**Parity with `protective_action_footprint`** (`IncidentInput` and `WindObservation` in
`src/hazbrief/models.py`, as of HB-08). Verdicts: `same`, `renamed` (same meaning and values,
another name or shape), `superset` (ours accepts everything PHMSA's does, and more),
`subset` (ours accepts less), `missing` (no input of ours carries it). The tool is not changed
here.

| PHMSA parameter | PHMSA type, values, default | Ours (field, type, values) | Verdict | Note |
|---|---|---|---|---|
| `materialUn` | the UN number, string; either it or `materialName` is required | `incident.material`, str 1-200 chars, accepts `UN1017`, `NA1993`, `1017` or a yellow-index name | superset | One field takes the ID number or the name. NA numbers are accepted. |
| `materialName` | the material name, English or French | `incident.material` (same field) | subset | English only. PHMSA resolves French names too. Exact-name match in both. Where PHMSA falls back to a search list, ours returns an error and a hint. |
| `lat` | decimal degrees, -90 to 90, "." separator; required with `showMap` | `incident.location.latitude`, float, -90 to 90 | renamed | |
| `lon` | decimal degrees, -180 to 180 | `incident.location.longitude`, float, -180 to 180 | renamed | |
| `windDir` | integer degrees, 0 to 360, the direction the wind blows **from**, clockwise from north; required with `showMap` | `wind.direction_deg_from`, float 0 to 360 (from); optional, else the NWS forecast for the point | superset | Same convention ("from", clockwise from true north). Ours takes a decimal and has a source for it when none is given. A link must round it to an integer. |
| `showMap` | `true` or `false`; default `false` (data only) | none | missing | A presentation switch. Ours always returns the geometry and the data. |
| `spillSize` | `small` or `large`; default `large` | `incident.spill_size`, enum `small`, `large`, `unknown` (required) | superset | `unknown` takes the large spill distances, the same answer as PHMSA's default. |
| `timeOfDay` | `day` or `night`; default `night` | none as input; derived from `incident.incident_time` by sunrise and sunset at the point (`day_night.period` in the output) | missing | Ours cannot be told day or night. It computes the answer. A link carries the computed period. |
| `whereSpilled` | `land` or `water`; default `land` (matters for water-reactive materials) | none | missing | A gap. Ours has no spill-in-water input. For Table 1's water-reactive entries ("when spilled in water"), `assess_incident` asks the user to confirm the name in Table 1 instead (`src/hazbrief/incident.py`). |
| `containerType` | the six Table 3 container strings (English) or their French forms; default "first available container" | `incident.container`, str 1-100: the six English strings, a unique start of one (case and spacing ignored), or `unknown` | superset (English), subset (French) | `unknown` takes the row with the largest distances, where PHMSA takes the first container listed. The two can differ. Strings: byte for byte the same (below). |
| `windSpeed` | `low`, `moderate` or `high`; default `low` | `wind.speed_kmh`, float 0 to 400 (or the NWS forecast); the band is derived (`wind.band`) | superset | Ours takes a speed and derives the ERG band. A caller who knows only the band cannot pass it. A link carries the derived band. |
| `mapType` | `normal`, `satellite`, `hybrid` | none | missing | Presentation only. |
| `color` | ARGB hex, default `50FFA500` | none | missing | Presentation only. |
| `hideLabels` | `true` or `false` (WebWISER only) | none | missing | Presentation only. |
| `catId` (substance identification, `165`) | used with the substance parameters instead of the material ones | none | missing | Not a path the ERG tables need. |
| (none) | | `incident.fire_involved`, `incident.incident_time`, `wind.observed_at`, `wind.source` | (ours only) | Fire selects the guide's tank-in-fire isolation. The time and the wind's provenance feed the as-of tags. |

**Container strings, byte for byte.** The six English `containerType` values on the API page
(`Rail tank car`, `Highway tank truck or trailer`, `Agricultural nurse tank`, `Multiple small
cylinders`, `Multiple ton cylinders`, `Multiple small cylinders or single ton cylinder`) are
identical to the container labels in `erg2020-table3-xls` (column A, read raw through xlrd) and
to the `container` values of the ERG 2024 pack (`packs/erg.json`). There is no discrepancy for
HB-03b to absorb here. Caveat: the API page is held as a clipping, its Markdown rendering. The
comparison is of the clipping's text, and these strings are plain ASCII, so HTML escaping
cannot differ.

**URL template** (the `material` path, every parameter the footprint inputs determine;
percent-encode values, "%20" for a space, per the page's formatting notes):

    https://www.phmsa.dot.gov/erg/material?materialName={name}&materialUn={un}&lat={lat}&lon={lon}&windDir={round(direction_deg_from)}&spillSize={small|large}&timeOfDay={day|night}&whereSpilled=land&containerType={container}&windSpeed={low|moderate|high}&showMap=true

`spillSize` is `large` when ours is `unknown`. `containerType` is omitted when ours is `unknown`,
because PHMSA's default (the first container) is not ours (the largest). `whereSpilled=land`
holds until ours has the input.

**Worked example** (HB-08 fixture point `i81-md-pa-line`, 39.722, -77.724. UN1017 Chlorine,
highway tank truck or trailer, large spill, 2026-10-21T14:00-04:00. Wind from the recorded NWS
exchange, `CTP/80,9`, as of 10/20/2026 20:06 EDT: from 0 degrees (north) at 11.1 km/h, moderate
band, daytime. The footprint reads ERG 2024 Table 3, `erg2024-en-pdf#p343`):

    https://www.phmsa.dot.gov/erg/material?materialName=Chlorine&materialUn=1017&lat=39.722&lon=-77.724&windDir=0&spillSize=large&timeOfDay=day&whereSpilled=land&containerType=Highway%20tank%20truck%20or%20trailer&windSpeed=moderate&showMap=true

**Edition caution.** The specification is the ERG2020 app's, and the page claims "All ERG
platforms now support this API". Which edition's distances the app draws for this link (ERG2020
or ERG 2024) is not established by anything held. If 2020, its cone uses the 2020 Table 3 row,
which differs from the footprint's 2024 row (section 1). A `verify_in_erg_app` link should
carry that caveat until it is checked. Not implemented here (ADDENDUM-00).
