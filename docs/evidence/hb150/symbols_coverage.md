# HB-150 Part B item 7: which map classes the held FGDC HSWG set covers

Rule (operator decisions 2026-11-09 21:34 and 22:42): use the free FGDC HSWG set where its documentation maps a
glyph; otherwise hazbrief draws its own symbol, labelled as its own; no paid standard. "Held statement" here means
Seldon Issue b1f7dc08 (FGDC `Operations_ref.htm` as read 2026-11-09; page not held), the only one. Fonts are the
`ersV2txt` files; S1..S4 draw the same pictogram in four frames (`glyph_notes.md`). Evidence: `hswg_glyphs.tsv`,
`glyphs/`.

| class | symbols.yaml symbol | coverage |
|---|---|---|
| spill | Hazardous Material Incident | glyph present but unnamed in held material: Incidents font, diamond hazard pictograms (e.g. `L` flame, `V` flask, `W` corrosive, `Y` explosive); which one, if any, is "Hazardous Material Incident" is unverified |
| schools | Education Facility | glyph present but unnamed in held material: Infrastructures_S1..S4 `B` (mortarboard), also `A` (book); unverified |
| care | Medical Facility | glyph present but unnamed in held material: Operations `B` (house with star of life) or `E` (building with cross); unverified |
| emergency_services | Emergency Services | no glyph: hazbrief draws its own, labelled as its own (no single generic glyph seen) |
| receiving_hospitals | Hospital | held: Operations_S1..S4 `F` "Hospital" |
| nearby_fire | Fire Station | held: Operations_S1..S4 `Y` "Fire Station" (draws a fire engine) |
| nearby_ems | Emergency Medical Service | held: Operations_S1..S4 `A` "Emergency Medical Operation" (held name differs from the map's) |
| nearby_police | Law Enforcement | held: Operations_S1..S4 `g` "Police"; also `Z` "Law Enforcement Operation" |
| nearby_hospital | Hospital | held: Operations_S1..S4 `F` "Hospital" |
| command post | - | held: Operations_S1..S4 `N` "Emergency Incident Command Center" |
| triage | - | held: Operations_S1..S4 `K` "Triage" |
| staging | - | held: Operations_S1..S4 `R` "Emergency Staging Areas" |
| decontamination | - | no glyph: hazbrief draws its own, labelled as its own (none seen in any sheet) |
| roadblock | - | glyph present but unnamed in held material: Operations `b` (officer at barrier arm); Infrastructures_S1..S4 `p` (car at barrier gate), `q` (traffic cone); unverified |
| evacuation point | - | held: Operations_S1..S4 `M` "Emergency Collection Evacuation Point" |

Licence and status. The readme (`readme.txt`, `readme.htm`) does not state a licence or status. Every font's name
table does (nameID 0 and 13, all 22 files): "The symbols, in any form, are considered a Government work, and
therefore not subject to copyright protection." and "these symbols are a draft prototype [...] In all products that
incorporate one or more of the symbols, the user agrees to characterize the symbols as a draft prototype." This
confirms the Issue's three points from held bytes: a product that draws these glyphs must call them a draft
prototype.
