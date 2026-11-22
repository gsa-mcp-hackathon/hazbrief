# HB-216: who already plans for a release, and what hazbrief offers them

**Task:** `HB-216` (HB-216).
**From:** the operator's statement of 2026-11-21 07:17 EST and Issue `69466498` (his statements of 2026-11-10 09:09 EST).
**Read:** `docs/evidence/hb156/claims_checked.md` in full; 42 U.S.C. 11003 (EPCRA section 303) in full, held as
`usc-42-11003-epcra-303-2024` (sha256 9f193f04); EPA's 2024 final rule (`epa-rmp-sccap-final-rule-2024-prepub`) and the
2026 proposed rule (`fr-2026-03633-rmp-common-sense-proposed`), searched for a facility count.

This is the record the deck's planning slide quotes (`docs/submission/deck.yaml`, slide `planning-uses`), and README and
EVALUATION's paragraph on the planning uses. Every held sentence cited here is either in HB-156's
`docs/evidence/hb156/claims_checked.md` or in `docs/evidence/hb216/quotes.yaml`, located in the held bytes by HB-156's
tool (`docs/evidence/hb216/locate_quotes.txt`, which gives each sentence's PDF page and the file's sha256).

## The slide's sentences

HB-219 (ADDENDUM-01 items 1 to 3) said sentences 1, 2, 4 and 5 in plain words: the two citations spelled out, the
Issue id moved to the slide's notes, and "the operator's" said as "the author's", marked as his still. Before HB-219
they read: "Facilities filing a worst-case release scenario (40 CFR 68.25)"; "Local emergency planning committees plan
for releases (EPCRA section 303)."; "Next: a worst-case scenario builder (Issue d54dbcb8)."; "The operator's further
uses: exercises, pre-incident plans, siting, zoning." (`docs/evidence/hb219/before_after.tsv`).

1. Facilities filing a worst-case release scenario (title 40 Code of Federal Regulations, section 68.25): about 11,740.
   - The requirement: 40 CFR 68.20 and 68.25(a); the report, 68.165(a); the statute, 42 U.S.C. 7412(r)(7)(B)
     (HB-156, `claims_checked.md` C1, confirmed as worded). The fixed conditions of the worst case are in 40 CFR
     68.22: a wind speed of 1.5 meters per second and F atmospheric stability class.
   - The count: "Approximately 11,740 facilities have filed current RMPs with EPA and are potentially affected by the
     rule." (EPA's 2024 final rule, pre-publication copy, section I.C, PDF p. 9; quotes.yaml P2-a).
   - A later count, for 2023: EPA's 2026 proposed rule counts 11,510 registered facilities in 2023, down from 12,396
     in 2014 (91 FR 8976, PDF p. 7; quotes.yaml P2-b). The slide prints the final rule's figure, because it counts
     facilities that have filed current plans, which is the filing the slide names; the proposal's is in the notes.
2. Local emergency planning committees plan for releases (Emergency Planning and Community Right-to-Know Act, section 303).
   - Section 303(a): "Each local emergency planning committee shall complete preparation of an emergency plan in
     accordance with this section" (quotes.yaml P1-a).
   - What the plan holds, section 303(c): the routes likely to be used to transport extremely hazardous substances
     ((c)(1), P1-c), "the area or population likely to be affected by such release" ((c)(5), P1-b), and "Methods and
     schedules for exercising the emergency plan" ((c)(9), P1-d).
3. Built: a what-if brief from a stated wind.
   - A brief takes a stated wind in place of the forecast (`hazbrief brief --weather-source stated` with its
     `--stated-*` fields, or the same names on the served page's query; `src/hazbrief/brief/cli.py`, HB-139, DN-019
     ADDENDUM-01). Issue `69466498`'s finding 1: "a stated wind also serves what-if planning". That is the route
     built today: the same fused picture (footprint, population, facilities, hospitals, the modelled cloud) for a
     release that has not happened, under a wind the planner chooses.
4. Next: a worst-case scenario builder.
   - Not built: the worst-case scenario builder is Issue `d54dbcb8`. The operator asked for it on 2026-11-10 (Issue `69466498`, finding 2: "a worst-case scenario
     builder, perhaps a top-five list for exercises and planning"); `docs/FUTURE_WORK.md` F14. A builder would cite 40
     CFR 68.22's fixed conditions (HB-156).
5. The author also proposes: exercises, pre-incident plans, siting, zoning.
   - These are the author's statement of where hazbrief could be used, not a held source's claim. His words,
     2026-11-21 07:17 EST: "Part of the problem/benefit statement should include the (10k ? filing?) that all plants
     and things must do -- and that this could be used for all those things -- including pre-planning for zoning,
     etc." The filing he names is the Risk Management Plan of sentence 1, not a 10-K.
   - Exercises are also in the statute: section 303(c)(9), above. Pre-incident planning is NFPA 1620's subject; its
     text is not held (`nfpa-1620-pre-incident-planning`, reference only, behind an NFPA account).

## README and EVALUATION

The paragraph both carry:

> Every facility under EPA's Risk Management Program must analyse and report a worst-case release scenario (40 CFR
> 68.25; about 11,740 facilities have filed current plans), and every local emergency planning committee must plan
> for releases, transport routes included (EPCRA section 303). hazbrief gives them the same fused picture for a
> what-if release: a brief built from a stated wind; a worst-case scenario builder is next, not built (Issue
> d54dbcb8). The operator also names exercises, pre-incident plans, siting and zoning as uses; that is his statement,
> not a held source's.

## The facility count: in

A held source states it: the 2024 final rule, PDF p. 9 (above). HB-127's base rates hold no facility count
(`docs/evidence/hb127/base_rates.tsv`: accidents, damages and evacuations only).

## Zoning: the operator's statement; no source held

Searched for a held source on land-use or zoning planning near hazardous facilities, 2026-11-21:

| Where | Search | Found |
|---|---|---|
| `corpus/sources.yaml` | zoning, land use, land-use, Seveso, PADHI, PIPA, setback, siting | nothing |
| the corpus texts (`graphs/hazbrief-corpus/texts/`, 174 files) | zoning, land use, land-use planning, siting of, setback distance, consultation zone | 7 files, none on planning near hazardous facilities: land cover classes (NLCD, MRLC), TIGERweb's Special Land Use Areas layer, an LEHD biography, and the land use around HSEES events (CDC MMWR) |
| the raw texts not in that index: 40 CFR part 68, the 2024 final rule and its Federal Register copy, the 2026 proposed rule, EPA's offsite consequence analysis guidance and its appendices | zoning, land use, land-use | two mentions, neither a source for the use (below) |
| `the event log of the graph (held privately)` | zoning | nothing |

The nearest held text:
- The 2024 final rule records a comment that the siting requirement "should be narrowly interpreted to preserve local
  zoning authority" (PDF p. 69; quotes.yaml Z-a), and says its siting requirement contains no setbacks or location
  restrictions "notwithstanding local zoning" (PDF p. 72; Z-b). That is EPA declining to regulate siting, not a source
  for planning it.
- EPA's offsite consequence analysis guidance, Appendix D.1.2, names S.R. Porter's UK Health and Safety Executive paper
  "Risk Mitigation in Land Use Planning: Indoor Releases of Toxic Gases" as the basis of a mitigation factor. The paper
  itself is not held.

So the zoning use stays as the author's statement, and an Issue records that no source is held.

## In the graph

- Issue `214cd9a7`: the operator's 2026-11-21 07:17 statement, held as his, `related_issue` to Issue `69466498`;
  remediated by HB-216 (task `e7211fd1`).
- Issue `53829db1`: no held source on zoning or land-use planning near hazardous facilities (`citation_gap`), `related_issue`
  to Issue `214cd9a7`.
