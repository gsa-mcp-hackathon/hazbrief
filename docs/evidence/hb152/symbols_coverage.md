# HB-152: which map classes draw an FGDC symbol, which draw hazbrief's own

Rule (HBD-315; operator decisions 2026-11-09 21:34 and 22:42): the free FGDC HSWG Emergency Response Symbology v2.20
where an FGDC reference page names the glyph; hazbrief's own symbol, labelled as its own, where none does; no paid
standard. The names, key strokes, row numbers and row markings below are the five reference pages' as fetched on
2026-11-10 (`fetch_sources.yaml`, `fetch_log.jsonl`; read into `ref_glyphs.tsv` by `tools/ref_pages.py`). Glyphs are
the held fonts', Stage 02 (`symbols.yaml` `standard.stage`). HB-150's list (`docs/evidence/hb150/symbols_coverage.md`)
is the one this supersedes for the map.

| class | layer | symbol | FGDC family, key, page row | changed from HB-150's list |
|---|---|---|---|---|
| spill | spill | Hazardous Material Incident | Incidents, U, row 23 (symbolKept) | named: HB-150 had the hazard diamonds unnamed |
| schools | schools | Schools | Infrastructures, C, row 31 (symbolKept) | named: HB-150 guessed B, which the page names College University |
| care_hospital | care (hospitals) | Hospital | Operations, F, row 8 (symbolConsider) | the care layer split by kind |
| care_nursing_home | care (nursing homes) | Elder Care | Infrastructures, ^, row 53 (symbolConsider) | named: the page defines it as "the locus of a nursing home or a residential assisted living facility" |
| emergency_services | emergency_services | hazbrief's own (a beacon light) | none: no page names a generic emergency-services glyph | as HB-150 |
| receiving_hospitals | receiving_hospitals | Hospital | Operations, F, row 8 (symbolConsider) | as HB-150 |
| nearby_fire | nearby_services | Fire Station | Operations, Y, row 27 (symbolConsider) | as HB-150 |
| nearby_ems | nearby_services | EMT Station Locations | Operations, B, row 4 (symbolConsider) | changed: HB-150 had A, the Emergency Medical Operation theme; B is the page's station-level symbol, "the locus of an emergency medical team" |
| nearby_police | nearby_services | Police | Operations, g, row 35 (symbolKept) | as HB-150 |
| nearby_hospital | nearby_services | Hospital | Operations, F, row 8 (symbolConsider) | as HB-150 |
| roadblock_candidates | roadblock_candidates | Traffic Control Point | Infrastructures, q, row 71 (symbolConsider) | named: the page's only traffic-control glyph; its definition ("absolute signals controlled by an operator to regulate and maintain transportation flow") is narrower than a roadblock |
| command_post | none yet (siting task) | Emergency Incident Command Center | Operations, N, row 16 (symbolKept) | as HB-150 |
| triage | none yet (siting task) | Triage | Operations, K, row 13 (symbolKept) | as HB-150 |
| staging | none yet (siting task) | Emergency Staging Areas | Operations, R, row 20 (symbolConsider) | as HB-150 |
| evacuation_point | none yet | Emergency Collection Evacuation Point | Operations, M, row *15 (symbolChanged) | as HB-150 |
| decontamination | none yet | hazbrief's own (a shower head over falling water) | none: no row on any of the five pages mentions decontamination | as HB-150 |

**FGDC: 14 classes. hazbrief's own: 2 (emergency_services, decontamination).**

The row markings (`symbolKept`, `symbolConsider`, `symbolChanged`, ...) are the pages' CSS classes, kept verbatim. The
pages say only "Changed or New symbols are marked by an asterisk (*) and have a light yellow or green background"; what
"Consider" signifies is not stated on them, so it is recorded and not interpreted.

Composition is the pages' own: each family has a "Background Symbol" (key `!`, "the background fill shape") and a
"Frame Symbol" (key `#`); each pictogram glyph carries its frame. An SVG is the background in the layer's colour and
the glyph in white or black, whichever has the higher WCAG 2.1 contrast ratio. hazbrief's own symbols use the
Operations background and frame with a pictogram hazbrief drew.
