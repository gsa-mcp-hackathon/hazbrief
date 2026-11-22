# Knowledge pack format (schema version 8)

**Task:** `HB-03` (HB-03). **Cites:** DN-001
sections 3, 4 (invariants 1-3), 6.3, 7; DN-002 section 4; DN-003 sections 1, 4, 5.

The server reads reference knowledge only from these files. Nothing is read from Neo4j or Squiddy
at runtime (DN-001 section 4 invariant 3). Packs carry reference knowledge (ERG, 49 CFR 172.101,
CAMEO, hazard classes, flag rules, the pack vocabulary), never live data (DN-003 section 1).

## Files

| Path | What |
|---|---|
| `packs/<kind>.json` | One built pack per kind. Written by `scripts/build_packs.py`; never edited by hand. |
| `packs/schema/<kind>.schema.json` | JSON Schema (2020-12) of each kind, generated from the Pydantic models in `src/hazbrief/models.py` by `build_packs.py schema`. A test fails if it drifts from the models. |
| `packs/src/build_config.yaml` | Every locator, source id, seed and version the build uses (standards section 2). |
| `packs/src/flag_rules.yaml` | The authored flag rules, compiled into `flag_rules.json`. |
| `packs/src/vocabulary.yaml` | The pack-side vocabulary: terms and the page anchors their definitions are read from. |

## Envelope (every kind)

| Field | Meaning |
|---|---|
| `schema_version` | Integer. `src/hazbrief/packs.py` refuses a version not in `SUPPORTED_SCHEMA_VERSIONS`. |
| `pack_id`, `kind` | The kind: `erg`, `cfr172`, `cameo`, `hazard_classes`, `flag_rules`, `vocabulary`. A kind with no model is refused. |
| `version` | Content version `<edition of the governing source>.<build revision>` (config `pack_versions`). |
| `built_at` | `YYYY-MM-DDTHH:MM:SSZ`. The newest retrieval instant among the pack's `sources`, not the wall clock, so a rebuild from the same held files is byte-identical. `SOURCE_DATE_EPOCH`, when set, overrides it (the reproducible-builds.org convention). |
| `sha256` | SHA-256 of the canonical form of `data` (below). Verified on every load; a mismatch is refused. |
| `sources[]` | Each held document the pack was parsed from: `doc_id` (the `corpus/sources.yaml` id), `raw_sha256` (of the held bytes), `locator` (where in it the pack reads), `licence`. |
| `attribution` | `credits[]` (title, publisher, edition, url per source, from `corpus/sources.yaml` and the acquisition records) and `notices[]` (reuse notices verbatim from the held document, with a locator). |
| `data` | The kind's content. |

**Licence.** Read from `corpus/sources.yaml` `reuse:`, with `squiddy_intake.py (a build tool held privately)`'s default
(`public-domain`, 17 U.S.C. 105) where the entry states none; the build calls the intake's join, so
there is one rule. It is never read from the Squiddy manifest, which still records
`public-domain` for `erg2024-en-pdf` and `erg2024-methodology` (HB-01c section 1). A source marked
`copyrighted` is refused by the build.

**Canonical form.** `json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`
as UTF-8 (`hazbrief.packs.canonical_json`). Key order and whitespace follow RFC 8785 (JCS); number
formatting does not (Python writes `11.0` where JCS writes `11`). The builder and the loader share the
one function, so the difference never matters inside this repository; another implementation must
reproduce Python's `repr` of floats.

**File form.** `json.dumps(pack, sort_keys=True, indent=1, ensure_ascii=False) + "\n"`.

## Locators

`<doc_id>#p<N>` is PDF page N (1-based; the ERG's printed page is N - 2). For a converted file
(HTML, JSON) a receipt's `page` is the form-feed block Squiddy indexes it by
(`corpus_text.text_blocks (a build tool held privately)`). CFR rows are `cfr49-govinfo-bulk#172.101:table<k>:row<n>`
(the k-th GPOTABLE in section 172.101, the n-th ROW in it).

## Cross-checks (`erg`, `cfr172`)

DN-003 section 5: every seed row is compared across the sources that carry it. Each check is
`{field, values: {source role: value as printed, or null where the source does not carry it},
status}`:

* `agree`: every carrying source gives the same value, and at least two carry it;
* `disputed`: two carrying sources differ. The row is written with every value, `disputed: true`
  on its entry, and listed in the task's RESULT;
* `single_source`: one source carries the field. Listed in the RESULT.

Values are compared after Unicode NFKC, folding U+2010 and U+2011 to `-`, and collapsing whitespace
(`pack_parsers.compare_form`); stored values keep the source's characters. Distances are compared in
the imperial form both the ERG and CAMEO print (`200 ft`, `0.2 mi`, `7.0+ mi`); the ERG's metric
value sits in the same printed cell and is parsed with it. Long guide text is compared by a SHA-256
digest of its compare form (`sha256:<16 hex> (<n> chars)`).

Source roles: `erg_pdf` (the ERG 2024 PDF), `pubchem_index` (PubChem's ERG 2024 UN index; it carries
guide numbers, names and the Table 1 highlight, and no distances), `cameo_unna` and
`cameo_unna(<UN>)` (CAMEO UN/NA datasheets), `cameo_guide_pdf` (CAMEO's copy of the orange guide),
`cameo_datasheet(<doc_id>)` (a CAMEO chemical datasheet's "Isolation and Evacuation" excerpt of the
guide), `cfr_xml` (the GovInfo CFR XML).

## Kinds

**`erg`** — `materials` by UN number: `names` (yellow index, with page), `guide`, `tih` (in Table 1),
`table1[]` (per name: small spill `isolate` {m, ft}, `protect_day` and `protect_night` {km, mi, plus};
`large` the same or null with `large_refer_to_table3`), `table3` (heading, locator, rows per
container: `isolate` and `day`/`night` × `low`/`moderate`/`high`), `cross_checks`, `disputed`.
`guides` by number: `title`, `sections` (`potential_hazards`, `public_safety`, `emergency_response`,
each a locator and `items[]` of heading/bullet/text), `evacuation` (immediate precautionary measure,
large-spill downwind, fire isolate and evacuate, each {m, imperial} or null;
`spill_refers_to_table1`). `index` (schema version 2): every ID number in the yellow index, seed or not, with its `names[]` (name, the guide printed beside it, page) and `in_table1` (Table 1 lists the ID number; Table 1 also lists water-reactive materials "(when spilled in water)", ERG PDF p. 30, printed p. 28, Note 1) with the page. Which names under an ID Table 1 prints, and every distance, are read for the seeds only. `name_index`: lower-cased name -> UN numbers, over the whole index (propane -> 1075, 1978).
`table3_wind_bands`: low, moderate, high with mph and km/h bounds (low is below `mph_max`, high above
`mph_min`, moderate between). `plus: true` is the table's "+": "distance can be larger in certain
atmospheric conditions".

**`cfr172`** — `edition` (from the XML title page), `columns` (pack field -> the table's own column
heading), `materials` by UN number: `rows[]` of `symbols`, `description` (column 2 as printed),
`roman_segments` (its Roman-type runs; 172.101(c)(1)-(2): proper shipping names are Roman type, an
italic "or" marks alternatives), `hazard_class`, `identification_number`, `packing_group`,
`label_codes[]`, `special_provisions[]`, `locator`.

**`cameo`** — `response_sections` (the CAMEO field labels surfaced: Isolation and Evacuation,
Firefighting, Non-Fire Response, Protective Clothing, First Aid; the DuPont permeation subsection
is a separate label and is not surfaced), `materials` by UN number: the UN/NA page receipt and every
held chemical datasheet that lists the UN number (matched by the datasheet's own UN/NA cell), each
with its sha256 and its sections' paragraphs.

**`hazard_classes`** — the four DN-001 section 3 classes, each with `rule_set_id`, the `criteria`
from config and the `members` computed from the `erg` and `cfr172` packs (first class whose criteria
a UN number meets, in config order).

**`flag_rules`** — `rules[]`: `rule_id`, `classes`, `modes`, `inputs[]` (name, the DN-001 section 7
tool that produces it, the dataset field, the dataset), `params`, `predicate` (`mode` all/any over
comparisons `{input, op, value | param | ref}`), `template` (stylebook sentence; placeholders are
input or param names), `receipts[]` (doc_id, page, verbatim quote verified on that page at build,
what it supports), `basis` (the design note), `gaps` (what the rule cannot see yet). `rule_sets`:
rule set id -> rule ids.

**`vocabulary`** — `terms[]`: `term` (HB-02's spelling), `definition` (read verbatim from the held
page between two anchors), `authority`, `receipt`, `used_by` (pack fields it labels, and the flag
rules whose sentence uses it). `test_packs.py (a test held privately)` checks agreement with
`docs/stylebook/VOCABULARY.yaml`.

## Changing the schema

A change to a model changes its JSON Schema (regenerate with `build_packs.py schema`). A change a
version-1 loader could not read bumps `schema_version` in `build_config.yaml` and
`SUPPORTED_SCHEMA_VERSIONS` together, with a note here.

**Version 2 (HB-08, 2026-10-20).** `erg.data.index` added and `erg.data.name_index` widened from
the seeds' names to every yellow-index name, so `assess_incident` resolves any ID number in the
ERG for its names, guide and Table 1 membership (`coverage: index_only`). A version-1 loader
forbids the new field, so the version is bumped. The build cross-checks the whole index: the ERG
PDF and PubChem's index list the same 1,983 ID numbers, and every ID PubChem highlights as Table 1
(183) is among the 272 IDs the PDF's Table 1 lists (`build_packs._check_full_index`).

**Version 3 (HB-03b, 2026-10-21).** The `erg` pack covers every ID number in the yellow index
(1,983), not the eight seeds: `materials` has one entry per ID, and `guides` the 62 orange guides
that print text (guides 121 and 167 print none, and the build refuses a material naming either).
Every row is triple keyed (`HB-03b`; `packs/build/`): Key A,
the ERG 2024 PDF's text layer (pdfplumber, `scripts/erg_keya.py`); Key B, a vision read of the
rendered page (`scripts/erg_keyb.py`); Key C, PHMSA's ERG2020 data files
(`scripts/erg_keyc.py`); adjudicated field by field (`scripts/erg_join.py`,
`scripts/erg_adjudicate.py`). New fields:

* every Table 1 entry, Table 2 entry, Table 3 row, index name and guide item carries
  `keyed_by` (the keys whose reading equals the stored value: `A`, `B`, `C`), `adjudicated` (A and
  B differed and C decided), `unresolved` and `unresolved_fields` (A, B and C all differ: the field
  is null, never guessed; `packs/build/UNRESOLVED.md` lists each with its three readings);
* `ErgMaterial.table2` (its Table 2 rows: name, guide, gas symbols, locator; null when Table 2
  does not list it) and `ErgMaterial.where_spilled_matters` (Table 2 lists it, so a spill in water
  changes the answer, ERG pp. 30 and 336); `ErgData.table2_legend` (symbol, name, locator);
* `Table1Entry.printed_name` (the cell as printed), `name` (without the qualifier), `guide`,
  `spilled_in` (`land`, `water` or null) and `water_reactive_note` (the printed qualifier, "(when
  spilled in water)"). ERG p. 30 Note 1: a material that is both TIH and water-reactive has two
  entries, land and water; one that is only water-reactive has one, water, and "if ... the product
  is NOT spilled in water, Table 1 and Table 2 do not apply";
* `ErgMaterial.guide` and `ErgIndexName.guide` are null where the index prints different guides
  under different names of one ID (the names carry theirs) or the guide is unresolved;
  `ErgGuide.title_keyed_by`.

Cross-checks against PubChem and CAMEO (DN-003 section 5) stay on the seed materials and their
guides; for every other ID the keying is the check. A version-2 loader forbids the new fields, so
the version is bumped.

**Version 4 (HB-12, 2026-10-21).** The `flag_rules` pack holds three kinds of rule
(`HB-12`; `packs/src/flag_kinds.yaml`):

* `source_kind: authored`: HB-03's hand-written rules (`packs/src/flag_rules.yaml`), applied by
  hazard class (`rule_sets`), each now with the `kind` `flag_kinds.yaml` assigns it;
* `source_kind: table`: hand-written rules that bind a pack field (`packs/src/flag_rules_table.yaml`:
  Table 2 membership with the spill surface, Table 3 membership), applied to every material
  (`table_rule_set`), each citing the ERG page that defines its table;
* `source_kind: guide`: rules mined from the orange guides by a model and admitted only when the
  trigger text is a verbatim substring (whitespace-normalised) of the Key A text of the page it
  cites (`packs/src/flag_rules_mined.jsonl`, written by `scripts/mine_flag_rules.py admit`),
  applied to the materials of their guide (`guide_rule_sets`, keyed by the guide number without
  its "P"). The template is the ERG's sentence; the kind's predicate over tool values decides
  whether the rule fires.

New fields: `FlagRule.kind`, `source_kind`, `guides`, `dormant` and `dormant_inputs` (inputs no
registered tool supplies yet; such a rule cannot fire until one does); `FlagReceipt.text_layer`
(`pdf_text`, verified on the held page's text as before, or `keyA`, verified by the admission
test); `FlagRulesData.guide_rule_sets`, `table_rule_set`, `kinds`. `src/hazbrief/flags.py` is the
evaluator: deterministic, a rule with an unsupplied input does not fire and says which.

**Version 5 (HB-12b, 2026-10-21; DN-006).** The `flag_rules` pack is rationalized as ANSI/ISA-18.2
prescribes: every flag is an alarm with `consequence` and `response` (ERG sentences by locator,
`FlagStatement`), `priority` (high, medium or low, by DN-006 section 3.5's rule in
`packs/src/flag_kinds.yaml` `priority`), `indication` (true when the ERG gives no response: kept in
the structured output, never printed) and `merged` (the causes of rules consolidated into it; the
flag fires when its own predicate or any merged cause holds). The section kinds HB-12 mined are no
longer flags (response guidance is `ErgGuide.sections`); the six cross-cutting kinds are one flag
per (guide, kind), `FR-G<guide>-<KIND>`, classified by the lexical patterns of `flag_kinds.yaml`
`rationalization` (HB-12's model kinds are the measuring second key, `packs/build/
RATIONALIZATION_DISAGREEMENTS.md`). FR-T2-01 and FR-T3-01 are merged into the guide flags of their
kind; FR-BLEVE-01 and FR-CRYO-01 into the guide flags whose response they duplicate.
`table_rule_set` is empty. `hazbrief.flags.for_briefing` caps a printed briefing at ten alarms.
HB-18 (pack version `hb18.1`, schema unchanged): a table rule with no `merge_into_kind` stands
alone and applies to every input. The one there is FR-AMB-01 (kind
`identification.ambiguous_material`, priority high): the load as reported matches several
yellow-index or placard-table rows. Its consequence is the ERG's most-conservative-guide sentence
(PDF p. 9). Its response is the sentence that settles the candidates once the ID number or name is
known (p. 9). `table_rule_set` is `["FR-AMB-01"]`.

**Version 6 (HB-03c, 2026-10-21).** `MetricDistance` and `KmDistance` carry `unit_note`
(`stale_secondary`, `inconsistent_other` or null): set on the cells of ERG 2024 Tables 1 and 3 whose
printed US-unit value disagrees with the metric value beside it (no unrounded distance rounds up
to both; `erg_units.py (a build tool held privately)`, `LN-04`). Five
cells, all in Table 3. The footprint uses the metric value and says so in `limits` when a cell it
used carries a note.

**Version 7 (HB-15, 2026-10-22).** `ErgData.placards`: the ERG 2024 Table of Markings, Labels and
Placards and Initial Response Guide to Use On-scene (PDF pp. 10-11, printed pp. 8-9), one
`ErgPlacard` row per input of the placard entry point (28 rows): `placard` (the class or division,
a placard word with its own guide, the lithium battery labels, `DANGEROUS`, or `none`), `words`
(the other words printed on its placards), `hazard_class` (the class number printed in the
placard's corner), `shows` (what the table draws), `guide` (the circled guide), `locator`,
`association` and `prose`, and the keying fields. **Two keys**, as for a table this small: Key A
is the PDF text layer (`scripts/erg_placards.py`: the 22 circled guide numbers and their
centres, and the ERG sentences that state a placard's guide, pp. 3 and 9); Key B is a reading of
the rendered pages (`packs/src/erg_placards_keyB.yaml`). The build refuses unless every Key B
circle is a Key A circle with the same number within 20 pt and Key A reads no other. Which
placard is drawn beside which circle is read by B alone (`association: drawing`, 18 rows) except
where the prose states it (`prose`, 10 rows), and the row says which. `keyed_by` is `["A", "B"]`
on every row; there is no Key C and no adjudication. The flag pack's FR-G115-MAY_EXPLODE_WHEN_HEATED
loses its `guide_page` term (`build_packs.absorb`; HB-05 F-4).

**Version 8 (HB-17, 2026-10-22).** `ErgData.unnumbered`: the four yellow-index rows ERG 2024
prints with no ID number (PDF p. 31: "Ammonium nitrate-fuel oil mixtures", "Blasting agent,
n.o.s." and "Explosives, division 1.1, 1.2, 1.3 or 1.5" under Guide 112; "Explosives, division 1.4
or 1.6" under Guide 114), which versions 3 to 7 dropped (`build_erg` keyed the index by ID; HB-15
premise 1). Each `ErgUnnumbered` row carries `name`, `guide`, `locator`, the keying fields (A, B
and C, as HB-03b keyed every index row), `note` (Note 2, p. 30, verbatim: "Explosives are not
individually listed by their ID number") and `aliases` (`ErgNameAlias`: another name a held source
prints with the row's, the sentence verbatim and its locator). One alias: ANFO, from 49 CFR 173.59
("Ammonium-nitrate—fuel oil mixture (ANFO)."), locator `cfr49-govinfo-bulk#173.59`. The build
refuses a note not on its page, an alias quote not in its CFR section, a guide not packed, and a
name that is also a numbered name. `PlacardProse` is reused for `note`: it is any ERG sentence by
locator. A version-7 loader forbids the new field, so the version is bumped.

## The application's packs (HB-66, 2026-10-28)

Three kinds the workbench's first-order puff reads (DN-018 sections 3 to 5): `materials_properties`,
`sigma_curves` and `release_scenarios`. They share the envelope and schema version 8, and `build_packs.py all`
builds them with the server's packs, from `build_config.yaml` `puff`. Their models are
`hazbrief.models.APP_PACK_MODELS`, never `PACK_MODELS`: the server's `load_packs` does not read them, so the tool
surface does not move (DN-009 section 2). The brief reads each with `hazbrief.packs.load_app_pack(kind)`, which
verifies it as `load_pack` does.

**Every number has its page.** Each object that holds a number holds a sibling `receipt` (`ValueReceipt`: `doc_id`,
`page`, `locator` `<doc_id>#p<N>`, `quote`, `read_by`). The build finds the value by its config pattern on that page
and refuses unless the quote is on it (`read_by: text_layer`). `read_by: rendered_page` marks a page with no usable
text layer (the scanned U.S. Standard Atmosphere, 1976): the quote is the recorded reading of the page image, and the
number is parsed from that quote. A value computed from others (the molar volume, the gas constant, the asphyxiant
fraction at the oxygen threshold) carries `derived_from` instead, naming held siblings. A value no held page states
is `status: not_held` (or `not_applicable` where the class draws no such threshold), `value: null`, with `reason`;
nothing is filled from elsewhere. `test_packs_materials.py (a test held privately)` walks every object and enforces this.

**`materials_properties`** — `classes` (DN-018 section 3: thresholds and the dense-gas caveat per class), `air` (the
conversion basis, NIOSH's 25 C and 1 atm, and the Standard Atmosphere's constants, from which the molar volume and the
asphyxiant fraction at 19.5 % oxygen are computed), `materials` by UN number (`name` from the CAMEO datasheet,
`guide` from the ERG pack, `dispersion_class`, `dense_gas_caveat`, `molecular_weight_g_mol`, `lfl_vol_pct`,
`aegl_status`, `aegl_ppm` level to minutes, `oxygen_deficiency_threshold_vol_pct`, `cross_checks`). A cross-check of
numbers agrees when the values are equal at the coarser printed precision.

**`sigma_curves`** — the Pasquill-Gifford sigma-y and sigma-z for rural sources, ISC3 Volume II Tables 1-1 and 1-2:
per class A to F, sigma-y's `c` and `d`, and sigma-z's bands (`x_range_as_printed`, `x_max_km`, `a`, `b`, or
`fixed_m` where the table prints `**`), with the scale constants and the 5,000 m cap. `band_rule` states how a
distance picks a band. `urban` is `not_built` with the reason.

**`release_scenarios`** — EPA's RMP Offsite Consequence Analysis Guidance: the worst-case definition and its
10-minute duration, the alternative-release method, and per fixture container string the worst-case quantity and the
alternative hole size and duration, each `not_held` with the reason where the guidance states none, and `covered`.
`not_adopted` lists held sources considered and why they were not used.

### The thermodynamics, the levels of concern and the licence gate (HB-109, 2026-11-06)

**Receipts name their bytes.** Every `ValueReceipt` in the three application packs also carries `sha256`, the held
file's raw sha256, equal to the pack's `sources[]` entry for that document.

**The licence gate (review L5-10; DN-020 section 2 item 4).** A receipt whose document is `reference-only` (the NIST
WebBook pages) quotes the number and its unit only: every whitespace-separated token of the quote is a printed number
or a unit or separator named in `packs/src/materials_properties.yaml` `reference_only_quote`, and at least one is a
number. The build finds the value by a pattern that may span the row (its label, its reference), keeps only the
number and unit, and refuses a receipt that fails the rule (`build_packs.licence_gate_admits`, applied in `_receipt`).
`test_packs.py (a test held privately)` seeds a prose quote from a reference-only page and asserts the refusal, and walks every committed
application pack.

**`materials_properties.materials[un].thermodynamics`** (`Thermodynamics`) — what a source term needs (DN-020 section
3.1), read from `packs/src/materials_properties.yaml`, which names where each value is printed: the CAMEO datasheet
first, the NIST WebBook page second. Values are `ThermoValue`s: a `HeldValue` with `temperature_k` (the temperature the
value is stated at), `as_printed` and `conversion` where the unit is converted (°F to K, kJ/mol to J/mol), and
`value_range` where a mixture's page prints a range (gasoline's and diesel's boiling ranges, held with `value: null`).

| Field | Unit | Read from |
|---|---|---|
| `molecular_weight_g_mol` | g/mol | the material's own `molecular_weight_g_mol` (HB-66) |
| `normal_boiling_point_k` | K | CAMEO "Boiling Point … at 760 mmHg"; NIST `Tboil` where CAMEO prints none |
| `heat_of_vaporization_j_mol` | J/mol | NIST enthalpy-of-vaporisation table, the row nearest the boiling point; where the species page prints none, the NIST Fluid Systems saturation row nearest the boiling point, h(v) − h(l) (argon); else the SLAB guide's test-case DHE times its WMS (chlorine) |
| `liquid_heat_capacity_j_mol_k` | J/mol/K | NIST Fluid Systems saturation table, `Cp (l, J/mol*K)` in the row nearest the boiling point (HB-124); else the SLAB guide's test-case CPSL times its WMS (chlorine) |
| `vapour_heat_capacity_j_mol_k` | J/mol/K | SLAB's CPS. NIST tabulated Cp,gas, the row nearest the boiling point (propane); where the species page prints none, the NIST Fluid Systems saturation row nearest the boiling point, `Cp (v, J/mol*K)` (HB-126); else the SLAB guide's test-case CPS times its WMS (chlorine) |
| `vapour_heat_capacity_shomate` | J/mol/K | NIST Shomate constants A to E, the lowest-temperature column and its range |
| `liquid_specific_gravity` | relative to water | CAMEO, at its printed temperature |
| `liquid_density_kg_m3` | kg/m3 | NIST Fluid Systems saturation table, `Density (l, kg/m3)` in the row nearest the boiling point (HB-124); else the SLAB guide's test-case RHOSL (chlorine) |
| `vapour_pressure_as_printed` | mmHg | CAMEO, at its printed temperature where it prints one |
| `saturation_pressure_antoine` | bar, K | NIST Antoine constants: every printed row with its range |
| `critical_temperature_k`, `critical_pressure_bar` | K, bar | NIST `Tc`, `Pc` |

A correlation (`Correlation`) has `form` (the equation and units as the page states them, verified on the page),
`status` and `rows` (`CorrelationRow`: `t_min_k`, `t_max_k`, `constants` each a `HeldValue` with the row's receipt).
None is extrapolated: a source term picks the row whose range covers its temperature. The selection rules for a value
printed in several rows are code, stated at the head of `materials_properties.yaml`: a NIST quantity takes the first
row that agrees with another within the larger stated uncertainty, and none where no two agree; a tabulated value
takes the row nearest the normal boiling point. `cross_checks` record every printed row against the value taken.
`missing` lists the `required_fields` not held; the vapour heat capacity counts as held only when
`vapour_heat_capacity_j_mol_k` is (HB-126: no held Shomate row's range reaches down to the boiling point, and none is
extrapolated, so the correlation alone cannot give SLAB's CPS). `proxy` (`ThermoProxy`) marks a mixture drawn with a pure substance's
properties: LPG (UN1075) carries propane's with `label` "propane properties used for LPG" and the LPG datasheet's own
statement of its composition as the receipt (DN-020 ADDENDUM-01 section 2 item 4).

**The liquid properties and the source tier (HB-124, 2026-11-06).** A NIST Fluid Systems saturation table
(`nist-fluid-saturation-<un>`, tab-delimited, one row per kelvin) is read at the row whose temperature is nearest the
pack's taken boiling point (a tie goes to the first printed); the row's temperature is the value's `temperature_k`, and
the receipt quotes the whole row, numbers only (page 1 of the held text). Where a material's species page prints no
enthalpy of vaporisation (argon), it is that row's vapour enthalpy minus its liquid enthalpy, the definition of the
enthalpy of vaporisation applied to two numbers printed in one row; `derived_from` names both columns. Chlorine, which
the Fluid Systems pages do not cover, takes DHE, CPSL and RHOSL from the SLAB user's guide's chlorine test case (PDF
p. 136, printed p. 130, OUTPR4's echo of its input, read from the rendered page), with DHE and CPSL converted from per
kilogram to per mole by the same input's WMS. Every held `ThermoValue` carries `source_tier`: `reference-table` (the
NIST WebBook's pages, CAMEO) or `model-test-input` (a program's test-case input, which is not a benchmark-validated
property; DN-020 ADDENDUM-02). A value not held has none. The brief prints no thermodynamic value yet; when a source
term reads one (HB-110), its label and the appendix print the tier.

**The vapour heat capacity (HB-126, 2026-11-07).** `vapour_heat_capacity_j_mol_k` is SLAB's CPS, read by the dense-gas
client. Where the species page prints no tabulated gas heat capacity (ammonia, nitrogen, argon), it is the
`Cp (v, J/mol*K)` cell of the same Fluid Systems row the liquid fields come from: the saturated vapour at that row's
temperature, the same receipt. Chlorine takes CPS from the same SLAB test-case echo (`CPS = 498.10` J/kg-K, times WMS),
`model-test-input`, and Table 2's CPS column is its `agree` cross-check. Propane keeps its species-page value (the read
order); LPG takes propane's. Gasoline and diesel hold none (no NIST page; a mixture).

**`materials_properties.materials[un].levels_of_concern`** (`LevelOfConcern`) — one entry per DN-001 class rule
(DN-020 ADDENDUM-01 section 2 item 2): `aegl2` (the AEGL-2 cells by averaging minutes), `lfl_fraction` (the material's
`lfl_vol_pct` times the fraction ALOHA's technical documentation states and its reason, `components` `lfl` and
`fraction`, the value `derived_from` both), `oxygen_deficiency` (the 29 CFR 1910.134(b) threshold). `values` is keyed
by averaging minutes for an AEGL and `any` otherwise; `proxy_for` names the material a proxy's entry stands for.

### The release routing table (HB-120, 2026-11-07)

**`release_routing`** — every ERG 2024 orange guide routed to a release model, or to "no dispersion model applies"
(DN-020 ADDENDUM-02 section 2 item 3). The fourth application pack: `APP_PACK_MODELS` `ReleaseRoutingPack`, read by
the brief's `hazbrief.brief.routing` through `load_app_pack`, left out of the image (`.dockerignore`). Authored in
`packs/src/release_routing.yaml` (`build_config.yaml` `paths.release_routing`) and built by
`scripts/build_packs.py release_routing` (or `all`) from that file and the ERG pack, which it reads and never writes;
built alone, it reads the committed `packs/erg.json`.

`guides` is keyed by the guide's three digits (an index entry's `P`, "a polymerization hazard under certain
conditions", is the same orange guide: `rules.polymerization_letter`, erg2024-en-pdf p. 347). Each `GuideRouting`
carries `title`, `hazard_classes` (the 49 CFR 172.101 hazard classes and divisions of the guide's index entries, UN
and NA numbers, parsed from the held CFR table at build), `placard_classes` (the ERG placard table's classes that name
the guide; the only classes a guide with no numbered entry has, Guides 112 and 114) and `rows`. The pack holds no number without a receipt.

A `RoutingRow` is one storage state: `pressure_liquefied`, `refrigerated_liquid` and `ambient_liquid` (the source
term's three, `source_term.CLASS_STATES`), `solid`, or `any` for a guide that routes every state alike (an `any` row
stands alone). `route` is `two_phase_jet`, `evaporating_pool`, `instantaneous` or `not_applicable`. A routed row names
`loc_class` (`toxic`: AEGL-2, else the NIOSH IDLH, HB-119 ADDENDUM-00, the dense-gas channel's `tih_gas`;
`flammable_lfl`; `oxygen_deficiency`) and no reason; a `not_applicable` row names `reason`, a responder's sentence
that quotes the ERG, and no class. Every row's `basis` is a `ValueReceipt`: one of the guide's own POTENTIAL HAZARDS
items, on that section's page. The class a routed row names is the cloud hazard the guide lists first: "Primary
potential hazard is listed first" (`rules.primary_hazard_first`, erg2024-en-pdf p. 348).

The build refuses, naming what is wrong: a guide of the ERG pack with no block, or a block for a guide the pack lacks;
a row with no basis; a basis that is not one of the guide's POTENTIAL HAZARDS items or not on that page of the held
ERG; and, on a guide without an `any` row, a storage state the guide's index names state ("refrigerated liquid",
"solid": `routing.name_state`) with no row. `tests/test_release_routing.py` holds each, and walks the whole ERG index
through the lookup.

The lookup (`routing.route(table, guide, state)`): an `any` row answers every state; a stated state takes its row, or
is not available where the guide has none; with no stated state, the guide's rows decide alone when they agree on
route and class, and otherwise the decision is not available, naming the storage state. A guide the table does not
hold raises `RoutingError`. The storage state is what the ERG name states, else the DN-001 class's
(`routing.storage_state`); nothing else is inferred.
