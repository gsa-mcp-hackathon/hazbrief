# HB-119 step 7: the acceptance draw, outside the seed set, resolved live once and replayed

DN-020 ADDENDUM-02 item 5 asks for "item 2's resolver on a material outside the seed set, drawn from the ERG index at
random by the test, run in replay against a recorded fetch". This file is that run.

**The draw.**
- **Pool:** every UN number in the held ERG index (`packs/erg.json` `materials`, ERG 2024) less the eight seeded ones
  (`packs/materials_properties.json`), sorted.
- **Draw:** `random.Random(119).choice` from the pool. The seed is the task's number, stated in
  `test_materials_resolver.py (a test held privately)` (`SEED`) and in `tools/draw.py`. The material's name is its first ERG name.
- **Recording:** `tools/record_resolutions.py` resolved each draw once, live, in `record` mode, under the task's Network
  line (cameochemicals.noaa.gov, pubchem.ncbi.nlm.nih.gov) at 2026-11-07T08:30Z. The exchanges are in
  `pubchem/ (held privately)` and `cameo/ (held privately)`.
- **Replay:** `test_the_acceptance_draw_outside_the_seed_set_replays_its_recorded_fetch` replays them.
- **Evidence:** `tools/acceptance_record.py` replayed every case and wrote `acceptance_record.json`, with each
  resolution record as the evidence store holds it.

## Draw 1: UN3492, "Poisonous by inhalation liquid, corrosive, flammable, n.o.s. (Inhalation Hazard Zone A)"

**Outcome: `Unresolved`; neither source knows it.** As the task says, that outcome is recorded and asserted, and a
second material is drawn.

**PubChem**
- `name 'Poisonous by inhalation liquid, corrosive, flammable, n.o.s. (Inhalation Hazard Zone A)'`: not found (404).
- `name 'Poisonous by inhalation liquid'` (the name up to its first comma, the ERG's qualifier convention): not found
  (404).
- The held NIOSH Pocket Guide prints no CAS number for UN3492, so there was no CAS lookup.

**CAMEO Chemicals:** no datasheet located. The resolver reaches CAMEO's datasheet through PubChem's reference to it,
and PubChem does not identify the material. CAMEO's own UN route is its `/search`, which robots.txt disallows
(`sources.md` section 1).

**What it means.** This is a generic "n.o.s." shipping entry, a class of materials, not a compound. No property
database has a record for it, and the brief's modelled-tier entry is "not available" with both reasons named
(DN-020 ADDENDUM-02 item 4, third state).

## Draw 2: UN1753, "Chlorophenyltrichlorosilane"

**Outcome: `Properties`, `provenance: fetched`.**
- Sources read: CAMEO Chemicals and PubChem.
- `fetched_at` 2026-11-07T08:30:13Z.
- Resolution record `69f87447309e7d62d69b54ca169976cd1d8bf37d62686f5b6f149379313fa9fa`, the same hash live and in
  replay: the record is built from the exchanges alone.

| Step | Exchange | Answer |
|---|---|---|
| identify | PUG REST `compound/name/Chlorophenyltrichlorosilane/cids/JSON` | CID 70002 (4-Chlorophenyltrichlorosilane) |
| computed properties | PUG REST `compound/cid/70002/property/MolecularWeight,MolecularFormula,Title/JSON` | molecular weight 246.0 |
| experimental section | PUG View `data/compound/70002/JSON?heading=Experimental Properties` | two headings only, Physical Description and Kovats Retention Index; references name CAMEO Chemicals datasheet 2907 |
| CAS | PUG View `…?heading=CAS` | 26571-79-9, 825-94-5 |
| CAMEO datasheet | `chemical/2907` | "CHLOROPHENYLTRICHLOROSILANE", CAS 26571-79-9, UN/NA 1753; every Physical Properties field prints "data unavailable" |

**What each source returned for the fields:**
- **Molecular weight:** 246.0 g/mol from PubChem (computed), labelled "properties fetched at 2026-11-07T08:30:12Z from
  PubChem, not benchmark-validated". CAMEO prints none.
- **Everything else is absent, named:** boiling point, heat of vaporisation, both heat capacities, specific gravity,
  liquid density, vapour pressure and the critical point. CAMEO's datasheet prints "data unavailable" for each, and
  PubChem's experimental section has no such heading. `missing` = normal boiling point, heat of vaporisation, liquid
  heat capacity, vapour heat capacity, liquid density, saturation-pressure (Antoine) constants.
- **Heat capacities (ADDENDUM-01):** vapour heat capacity not resolved; liquid heat capacity not resolved. Neither
  source prints either.
- **Thresholds:** the compiled AEGL table and the NIOSH Pocket Guide have no entry for its CAS, UN or name, so no toxic
  level. No LFL was resolved. The oxygen-deficiency level (29 CFR 1910.134, the seed's block) is attached, as for any
  material; the dense-gas channel takes it only for the cryogenic class.

**What the brief would say.** The resolver identifies the material and holds what the two sources print, which is its
molecular weight. The source term's line for it is "not available: the properties fetched from CAMEO Chemicals and
PubChem do not hold normal boiling point, heat of vaporisation, liquid heat capacity, vapour heat capacity, liquid
density, saturation-pressure (Antoine) constants for UN1753 CHLOROPHENYLTRICHLOROSILANE". That is DN-020
ADDENDUM-02 item 4's third state, with the missing properties named. It is not the item-5 outcome a reader may have
hoped for: a randomly drawn ERG entry is often a material no free source characterises. The draw is the honest test
of "any material".

## The three path cases (step 6), beside the draws

| Case | Ref | Outcome | Sources | Resolution record | Heat capacities |
|---|---|---|---|---|---|
| CAMEO hit | UN1017 "Chlorine", seed withheld | Properties | CAMEO Chemicals, PubChem | `8454ab1c…19f6` | vapour 33.93 J/mol/K at 298.15 K, from PubChem (HSDB: "Heat capacity at constant pressure (gas, 25 °C): 8.11 cal/mol °C"); liquid absent |
| CAMEO miss | "Ibuprofen" (no UN) | Properties | PubChem | `c0e2125c…271a` | both absent; PubChem prints none |
| neither | "Hazbrief test nonexistent material" | Unresolved | (CAMEO Chemicals, PubChem named) | none | none |

**Chlorine against the seed's own values.** The fetched entry reads, from CAMEO (`chemical/2862`):
- boiling point 238.54 K ("-30.3°F at 760 mmHg"), the seed's value from the held copy of the same page;
- specific gravity 1.424 at 288.15 K;
- vapour pressure 7600 mmHg at 303.15 K.

From PubChem:
- heat of vaporisation 20,410 J/mol at 239.12 K (HSDB, "20.41 kJ/mol at -34.03 °C", the row nearest the boiling
  point);
- vapour heat capacity 33.93 J/mol/K at 298.15 K.

Thresholds and checks:
- AEGL-2 2.8, 2.8 and 2.0 ppm at 10, 30 and 60 minutes, from the compiled table p. 43, the seed's cells.
- The boiling-point cross-check records CAMEO against PubChem's taken row as **disputed**: HSDB −34.04 °C and ICSC −34
  °C agree with each other and differ from CAMEO's −30.3 °F by 0.57 K. HB-109 found the same dispute against the NIST
  WebBook.
- Liquid heat capacity and liquid density stay absent. Neither source prints them in a form this reads; the seed holds
  them from NIST Fluid Systems and the SLAB guide (HB-124).

A reader of the label sees "properties fetched at … from CAMEO Chemicals, not benchmark-validated" beside each fetched
value, and the held page beside each seed value.

## What this run does not do

- The brief does not yet call the resolver. `derive.puff` and `derive.dense_gas` read the seed pack directly, and
  `with_resolved` is the join they would use. Wiring them needs HB-120's routing table, because a fetched entry carries
  no DN-001 dispersion class. Filed as an Issue.
- Every fetched material lacks Antoine constants: neither source prints a saturation-pressure correlation. The source
  term therefore reports "not available" for any fetched material until a correlation source or the Clausius–Clapeyron
  form through (T_b, P_v(T)) is ruled on. Filed as an Issue.
