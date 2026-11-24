<!-- seldon:projection-revision 6bdea59961c0d1b7 (the tables and counts between seldon:projection markers are rendered from the graph by `seldon docs generate rtm`; change a requirement with `seldon req`, not here; AD-013-R2) -->
# Requirements trace

**Task:** `HB-26` (HB-26).
**Sources of the rows:**
* DN-001 (`DN-001`) sections 3, 4, 5 and 7;
* GSA's four judging criteria, as HB-26 states them for 2026-10-20;
* from HB-42, DN-009's application constraints C1 to C6, DN-010 D1 to D7 and DN-011 D1 to D7;
* from HB-134R2, the view: every panel and layer of the brief that DN-019 and DN-022 govern, in its own table
  ([`VIEW_REQUIREMENTS.md`](VIEW_REQUIREMENTS.md)), summarised in the last section here.

From HB-144, each table whose rows come from a design note section carries a `Decision` column: the
active records of the decision register (`the decision register (held privately)`, ids `hazbrief-mcp:HBD-NNN`, written by
`seldon decision`) that state the row's ruling. `seldon decision show hazbrief-mcp:<id>` prints one.

Each row names what satisfies the requirement, what checks it, and its state. The DN-001 and GSA
rows were read at commit `ed26c53` (HB-26), updated where a later task changed them, and rechecked by
HB-42. The application rows were read at `5282b29` (HB-42).
Each state was checked against the code, not taken from a note. The states are:

* **met**: the code does it, and a test or an evaluation checks it. Where no automated check
  exists, the row says so.
* **partial**: the code does part of it, and the row says what is missing.
* **not met**: the code does not do it. Where a design note ruled it out, the row cites the ruling.
* **evidence in place** (from HB-149): the row was called met, but no test edge verifies it; the State reads
  `evidence in place: met ...` until a test carries `@pytest.mark.verifies("<id>")`, or, for a row checked by
  inspection, an Issue or Result records the inspection (`seldon req update <id> --evidence`).

From HB-149 (seldon SEL-035, AD-013 ADDENDUM 02) the `Decision`, `Satisfied by` and `Checked by` cells are computed
from the requirement's edges, and the State cell is its state's label followed by its note. The words those cells held
that no edge carries (harness parts, code paths, bare test names) are in the note, after `verified by:` and
`satisfied by:`. Change a row with `seldon req update`, never in the table.

A "not met" row is a finding, not a failure. The trace kit (`trace__*`) is not installed beside
this repository, so this table is written by hand with the kit's columns. The system the rows
point into is described in [`ARCHITECTURE.md`](ARCHITECTURE.md); "D-n" refers to that note's
section 10.

## DN-001 section 3: scope

<!-- seldon:projection view="table" section="DN-001 section 3: scope" headers="ID|Decision|Requirement|Satisfied by|Checked by|State" -->
| ID | Decision | Requirement | Satisfied by | Checked by | State |
|---|---|---|---|---|---|
| S3-1 | HBD-002 | Four hazard classes (TIH gases, flammable liquefied gases, flammable liquids, cryogenic asphyxiants), each with its own rule set | — | test_packs.py (a test held privately)::test_every_flag_rule_names_known_classes_and_a_rule_set; test_packs.py (a test held privately)::test_hazard_class_membership_is_computed_from_the_packs | partial (HB-95, review L1-8): four rule sets exist, but two are the same seven fusion rules. `rules.flammable_liquefied_gas` and `rules.cryogenic_asphyxiant` are identical (FR-CRE-01, FR-GQ-01, FR-HOSP-01, FR-LEP-01, FR-RAIL-01, FR-SCH-01, FR-VEH-01). The TIH set adds FR-TIH-01 and the flammable liquid set FR-WATER-01. A class's own hazard concerns arrive through its guides' rule sets (`guide_rule_sets`; `flags.applicable` takes both), and the cryogenic low-lying-area rules among them are dormant (S3-2); verified by: `test_packs.py (a test held privately)` `test_hazard_class_membership_is_computed_from_the_packs`, `test_every_flag_rule_names_known_classes_and_a_rule_set`; harness A part 1 (LN-05); satisfied by: `packs/hazard_classes.json` (four classes, members computed from the ERG and CFR packs); `packs/flag_rules.json` `rule_sets` (four); `assess_incident` returns the rule set |
| S3-2 | HBD-002 | Each class's own concerns: BLEVE radius and evacuation (LPG); spill, fire, storm drains and waterways (flammable liquids); low-lying areas and cold (cryogenics) | — | test_facilities.py (a test held privately)::test_the_four_facility_rules_are_live_and_fire_on_these_inputs | partial: the 26 guide rules that read `low_lying_areas_in_footprint` are dormant because no tool supplies that input; storm drains are not an input; source water protection areas are not an input (D-4); verified by: `test_facilities.py (a test held privately)` `test_the_four_facility_rules_are_live_and_fire_on_these_inputs`; harness A part 4; satisfied by: the guide's fire evacuation circle (`protective_action_footprint`, `material_response_guidance`); FR-WATER-01 over 3DHP waterways; guide flags for heavier-than-air materials |
| S3-3 | HBD-002 | Any UN number resolves through the ERG guide pages | — | tests/test_erg_any_un.py | met: verified by: harness A part 1 (every ID number and name) and part 3 (every guidance input); `tests/test_erg_any_un.py`; satisfied by: `packs/erg.json` (every yellow-index ID number, 62 guides); `incident.py` |
| S3-4 | HBD-003 | Modes: highway and rail | — | test_facilities.py (a test held privately) | met: Each rule's `modes` field is not read (D-7); the container carries the mode; verified by: the CSX Point of Rocks scenarios (harness B); `test_facilities.py (a test held privately)`; satisfied by: ERG Table 3 containers (rail tank car, highway tank truck or trailer) in `IncidentInput.container`; NTAD rail lines and FRA grade crossings in `facilities_in_footprint`; FR-RAIL-01 |
| S3-5 | HBD-004 | Scenarios synthetic only; no historic incidents in the demo | HB-08 assess and footprint tools | test_scenario_manifest.py (a test held privately) | met: Nothing checks that a scenario is not a historic incident, and no fixture file says the scenarios are synthetic. The points are corridor crossings HB-08 chose (the provenance comment in `scenario_points.yaml`); verified by: `test_scenario_manifest.py (a test held privately)` (every scenario declared); satisfied by: `fixtures/scenarios.yaml` (18 synthetic scenarios), `fixtures/scenario_points.yaml` |
| S3-6 | HBD-005 | Fixture corridors: I-81, I-83, Capital Beltway, one rail line in the same region | — | none | evidence in place: met; verified by: harness B over all 18 scenarios; satisfied by: `fixtures/scenario_points.yaml` (I-81 and I-83 at the MD-PA line, the Wilson Bridge, CSX at Point of Rocks) |
| S3-7 | HBD-001, HBD-006 | Output: footprint GeoJSON | — | test_protective_action_footprint.py (a test held privately) | met: verified by: `test_protective_action_footprint.py (a test held privately)`; harness A parts 2 and 5 (every drawn zone lies at its distance); satisfied by: `protective_action_footprint` `footprint`; `geometry.py` |
| S3-8 | HBD-006 | Output: flags with value, source, as-of date, margin of error where it exists, and the rule that fired | — | test_build_ics_201.py (a test held privately)::test_every_receipt_resolves; test_flag_rules_mined.py (a test held privately)::test_every_alarm_has_a_consequence_a_response_and_a_priority | met: The as-of rides in each value's source tag rather than as a separate field; verified by: `test_build_ics_201.py (a test held privately)` `test_every_receipt_resolves`; `test_flag_rules_mined.py (a test held privately)` `test_every_alarm_has_a_consequence_a_response_and_a_priority`; harness A part 4 (MC/DC); satisfied by: `flags.py`; `build_ics_201` "Fired on" sentences (each input's value, its source tag with vintage, its MOE) and the `flags` output (rule id, receipts, consequence, response) |
| S3-9 | HBD-001, HBD-006 | Output: an ICS 201 draft | — | test_build_ics_201.py (a test held privately) | met: verified by: `test_build_ics_201.py (a test held privately)` (blocks in the form's order, blank blocks labelled, every sentence of Blocks 5, 7 and 10 with a receipt, stylecheck); frozen forms in `fixtures/ics201/` (harness B); satisfied by: `build_ics_201` |
| S3-10 | HBD-006 | Output: a Protective Action Decision recommendation with its ERG basis | — | test_build_ics_201.py (a test held privately) | partial: the action, area and ERG basis are stated, but no evacuate-or-shelter recommendation is made. The stylebook gives that choice to the Incident Commander (SB-STR-06). There is no separate PAD output; verified by: `test_build_ics_201.py (a test held privately)`; frozen forms; satisfied by: Block 7 of `build_ics_201`: isolate the initial isolation zone, protect the protective action zone (distance and direction), the ERG crosswind and decision-factors sentences, and "Choose evacuation or shelter-in-place for <zone> from the ERG decision factors" with its page |
<!-- /seldon:projection -->

## DN-001 section 4: invariants

<!-- seldon:projection view="table" section="DN-001 section 4: invariants" headers="ID|Decision|Requirement|Satisfied by|Checked by|State" -->
| ID | Decision | Requirement | Satisfied by | Checked by | State |
|---|---|---|---|---|---|
| I-1 | HBD-007 | No dispersion model: distances from ERG Table 1, Table 3 and the orange guides, oriented by NWS wind | — | none | evidence in place: met; verified by: harness A part 5: every distance in every enumerated output traces to its pack cell, and no distance is computed from another (LN-05); satisfied by: `incident.py` (table choice), `geometry.py` (the ERG's circle and square), `nws.py` |
| I-2 | HBD-008 | "Plume" appears in no tool name or output; the term is "protective action footprint" | — | tests/test_assess_incident.py::test_no_output_writes_plume; test_packs.py (a test held privately)::test_pack_text_never_writes_plume; test_protective_action_footprint.py (a test held privately)::test_no_output_writes_plume | met: satisfied by: tool names; pack text |
| I-3 | HBD-009, HBD-302 | Flags are deterministic; every flag is a rule in a pack with a source; the model never decides what is alarming | — | test_flag_rules_mined.py (a test held privately)::test_the_tools_flag_inputs_are_the_registrys_supplied_inputs; tests/test_requirements.py::test_no_server_module_reaches_a_model_and_no_runtime_pin_is_a_model_sdk | met: verified by: `tests/test_requirements.py` `test_no_server_module_reaches_a_model_and_no_runtime_pin_is_a_model_sdk` (every server module: no model SDK import, no MCP sampling call, no model SDK runtime pin; HB-96); `test_flag_rules_mined.py (a test held privately)` `test_the_tools_flag_inputs_are_the_registrys_supplied_inputs` (HB-96); harness A part 4 (every cause by MC/DC; every receipt verbatim on its page); satisfied by: `packs/flag_rules.json`; `flags.py`; no model call in the server |
| I-4 | HBD-010 | No Neo4j at runtime; the server ships exported packs | — | test_packs.py (a test held privately) | met: The packs are parsed from held files, not exported from the graph (D-1); verified by: `test_packs.py (a test held privately)` (round trip, sha256 refusal); satisfied by: `packs.py` reads `packs/*.json` only; no database driver in the runtime dependencies |
| I-5 | HBD-010 | The packs are bundled in the container | HB-34 the image a judge reaches and four stale documents | test_container_image.py (a test held privately) | met: (HB-34; was partial, D-11); verified by: `test_container_image.py (a test held privately)`: every path the runtime reads is copied or exempt with a reason; HB-34 ran part B regression inside the built image (0 differences); satisfied by: `Dockerfile` copies `packs/`, `docs/stylebook/`, `fixtures/lodes/` and `fixtures/cms/` |
| I-6 | HBD-010 | Two commands to run | — | tests/test_server.py | met: verified by: `tests/test_server.py` (import, registration, default stdio); satisfied by: `uv sync`; `uv run python main.py` (README) |
| I-7 | HBD-011 | One free key, `CENSUS_API_KEY`, for the live population tools; without it a structured error with the signup URL; every other tool works; no other key | — | test_build_ics_201.py (a test held privately)::test_without_a_census_key_every_other_block_fills; tests/test_config_layering.py; test_population_at_risk.py (a test held privately)::test_without_a_key_the_tool_returns_the_signup_url | met: satisfied by: `config.py`; `population_at_risk` `CensusKeyMissing` branch |
<!-- /seldon:projection -->

## DN-001 section 5: data sources

<!-- seldon:projection view="table" section="DN-001 section 5: data sources" headers="ID|Decision|Requirement|Satisfied by|Checked by|State" -->
| ID | Decision | Requirement | Satisfied by | Checked by | State |
|---|---|---|---|---|---|
| D5-1 | HBD-012 | PHMSA ERG, current edition: guide pages, Table 1, Table 3 | — | tests/test_erg_any_un.py; test_packs.py (a test held privately); tests/test_unidentified_load.py | met: verified by: `test_packs.py (a test held privately)`, `tests/test_erg_any_un.py`, `tests/test_unidentified_load.py`; harness A; satisfied by: `packs/erg.json` (ERG 2024, triple keyed), with Table 2, the placard table and the unnumbered explosives |
| D5-2 | HBD-012 | 49 CFR 172.101 hazmat table | — | test_packs.py (a test held privately) | partial: rows for the eight seed materials only; any other ID number returns `coverage: erg`; verified by: `test_packs.py (a test held privately)` (cross-checks); satisfied by: `packs/cfr172.json` |
| D5-3 | HBD-012 | NOAA CAMEO Chemicals response data | — | test_packs.py (a test held privately) | partial: datasheets for the eight seed materials only; satisfied by: `packs/cameo.json` |
| D5-4 | HBD-012 | NWS api.weather.gov wind at the incident point, no key | — | test_protective_action_footprint.py (a test held privately)::test_nws_wind_is_replayed_with_its_as_of | met: satisfied by: `nws.py`; `protective_action_footprint` |
| D5-5 | HBD-012 | ACS 5-year: population, age 65+, disability, no-vehicle households (B08201), limited-English households | — | test_population_at_risk.py (a test held privately); tests/test_population_moe.py | met: verified by: `test_population_at_risk.py (a test held privately)`, `tests/test_population_moe.py` (the ACS Handbook worked example); satisfied by: `population_sources.yaml` (B01001, B18101, B08201, C16002); `census.py` with derived MOEs |
| D5-6 | HBD-012 | Group quarters | — | test_population_at_risk.py (a test held privately)::test_configured_group_quarters_types_are_the_held_p18_labels | met: satisfied by: 2020 DHC P18 by block, by type |
| D5-7 | HBD-012 | LEHD LODES (daytime workers) | — | test_population_at_risk.py (a test held privately)::test_a_state_with_no_cached_lodes_file_is_reported | partial: cached for MD, PA, VA and DC only; elsewhere the tool reports the state in `missing_states`; satisfied by: `lodes.py` over `fixtures/lodes/` (LODES8 WAC 2023) |
| D5-8 | HBD-012 | Community Resilience Estimates | — | test_population_at_risk.py (a test held privately) | met: satisfied by: CRE 2024 by tract; FR-CRE-01 |
| D5-9 | HBD-012 | TIGER roads and rail | — | tests/test_ics201_map.py | partial: roads appear only in the Block 4 image; rail comes from BTS NTAD, not TIGER (D-2); satisfied by: TIGERweb `Transportation` export (Block 4 image) |
| D5-10 | HBD-012 | Commodity Flow Survey hazmat tables (base rates for the deck) | — | none | not met: not acquired; no base rate is computed; satisfied by: `corpus/sources.yaml` `cfs-2022-hazmat-tables` (`plan: deferred_bulk_data`) |
| D5-11 | HBD-012 | ATSDR Social Vulnerability Index (tract) | — | none | not met: no SVI in any tool. CRE (D5-8) is the vulnerability measure the tools carry; satisfied by: `corpus/sources.yaml` `svi-2022-tract-data` (deferred: host not allowlisted, download page is a JavaScript app) |
| D5-12 | HBD-012, HBD-026 | USGS National Map Structures: hospitals, fire/EMS, police, schools, nursing homes, prisons | — | test_facilities.py (a test held privately) | partial: nursing homes come from CMS (DN-002 section 4); prisons are not listed as facilities, and their residents are counted as group quarters (D-3); satisfied by: `facilities_in_footprint` (schools, colleges, hospitals, fire and EMS, ambulance, police) |
| D5-13 | HBD-012, HBD-025, HBD-290 | CMS Provider of Services licensed beds | — | test_facilities.py (a test held privately)::test_the_cms_files_carry_their_as_of_and_match_rate | met: satisfied by: `fixtures/cms/hospitals.json` (Hospital General Information joined to POS beds); `receiving_hospitals` |
| D5-14 | HBD-012, HBD-025 | HHS/NHSN live hospital capacity, only after its 2024 coverage change is verified; otherwise licensed beds, said so | — | test_facilities.py (a test held privately) | not met (ruled out): DN-002 section 4 found no public facility-level source after the 2024 change; the fallback DN-001 names is what is built; satisfied by: `receiving_hospitals` reports licensed beds with the CMS release date and its `limits` |
| D5-15 | HBD-012, HBD-028 | USGS NHD waterways | — | test_facilities.py (a test held privately)::test_a_waterbodys_river_is_the_main_path_through_it | met: satisfied by: USGS 3DHP flowlines and waterbodies (DN-002 section 4: NHD retired, 3DHP its successor) |
| D5-16 | HBD-012, HBD-027 | EPA drinking water intakes (flammable-liquid rules) | — | test_facilities.py (a test held privately)::test_the_limits_pass_the_stylebook | not met (ruled out): DN-002 section 4. The source water protection areas DN-002 names instead are not an input either (D-4); satisfied by: `facilities_in_footprint` `limits`: "Drinking water intakes are not published" (SDWA section 1433) |
| D5-17 | HBD-012 | PHMSA hazmat incident database and FRA rail data, for base rates in the deck | — | none | not met: no base rate is computed. FRA grade crossings are used at runtime (NTAD), but not as base rates; satisfied by: `corpus/sources.yaml` `phmsa-incident-statistics`, `fra-safety-data` (held as reference pages) |
<!-- /seldon:projection -->

## DN-001 section 7: tool shape

<!-- seldon:projection view="table" section="DN-001 section 7: tool shape" headers="ID|Decision|Requirement|Satisfied by|Checked by|State" -->
| ID | Decision | Requirement | Satisfied by | Checked by | State |
|---|---|---|---|---|---|
| T-1 | HBD-017 | The seven tools: `assess_incident`, `protective_action_footprint`, `population_at_risk`, `facilities_in_footprint`, `receiving_hospitals`, `material_response_guidance`, `build_ics_201` | — | tests/test_agent_surface.py; tests/test_server.py::test_tools_register_without_error | met: satisfied by: `src/hazbrief/tools/` |
| T-2 | HBD-017 | One file per tool | — | inspection: none | evidence in place: met; verified by: inspection; satisfied by: one module per tool, each with `register(mcp)` |
| T-3 | HBD-017 | Pydantic inputs | — | tests/test_json_string_args.py; tests/test_unidentified_load.py::test_exactly_one_of_material_guide_and_placard | met: satisfied by: `models.py` (`extra="forbid"`, bounds, the one-load validator) |
| T-4 | HBD-017 | Each docstring states the data source, update cadence and as-of behaviour | — | inspection: none | evidence in place: met; verified by: inspection only; no test asserts it; satisfied by: every tool's module and function docstring |
| T-5 | HBD-017 | The ICS 201 prompt sequences the tools | — | test_stylebook.py (a test held privately)::test_prompt_sequences_the_tools_and_binds_the_stylebook | met: One description names prisons the tool does not list (D-6); satisfied by: `prompts/ics201_brief.py` `TOOL_SEQUENCE` |
<!-- /seldon:projection -->

## GSA judging criteria

<!-- seldon:projection view="table" section="GSA judging criteria" headers="ID|Criterion|Satisfied by|Checked by|State" -->
| ID | Criterion | Satisfied by | Checked by | State |
|---|---|---|---|---|
| G-1a | Technical quality: readability and maintainability | HB-26 architecture note requirements trace and security; HB-34 the image a judge reaches and four stale documents; HB-42 engineering documents for the application layer | none | evidence in place: met. The three stale shipped documents HB-26 found (D-8, D-9, `eval/README.md` in D-5) were fixed by HB-34; HB-42 rechecked the four engineering documents and corrected what was stale (its RESULT); verified by: the local gate: the dispatcher runs `uv run pytest tests/ -q -p no:cacheprovider` before every merge (`the Seldon configuration (held privately)` `dispatch.gate_command`). `.github/workflows/ci.yml` (ruff check, ruff format check, the test suite) runs only when a person starts it (HB-85); satisfied by: thin `app.py`, one module per item, settings in `config.py` and YAML, `ARCHITECTURE.md`, `packs/SCHEMA.md`, `docs/FIXTURES.md`, design and lab notes |
| G-1b | Technical quality: performance and reliability, with the submitter's own evaluation setup and results | — | none | partial: correctness and reliability are measured, and committed per run under `eval/reports/` (HB-36). Latency: per upstream call in harness C's 120-call run (LN-05); per section and per brief in the brief CLI's status line (HB-41), a measurement of one run, not a benchmark. On the seed scenario through the real server in HTTP replay, the map, footprint and flags settle at 1.26 s and the brief at 3.87 s (HB-41 RESULT section 4). What a benchmark would add: repeated runs per scenario, live upstream time rather than replay, a distribution (median and 95th percentile) per tool and per brief, and a committed report. Open; verified by: the harness and agent runs themselves; the slow invariants, locally or by hand in CI; satisfied by: `eval_harness.py (a build tool held privately)` A, B, C (LN-05); `scripts/agent_eval.py` (LN-07) |
| G-1c | Technical quality: adherence to MCP design principles (Pydantic inputs; goal-shaped tools, not REST wrappers) | — | tests/test_agent_surface.py | met: verified by: the agent evaluation (tool precision and recall, argument match, refusal; LN-07 part 2); `tests/test_agent_surface.py`; satisfied by: seven goal-shaped tools with annotations; `response_format` concise and detailed with `block` paging; `error` with `hint`; one prompt; three resources |
| G-2 | Innovation | — | inspection: none | evidence in place: verified by: judged, not tested; satisfied by: the fusion DN-001 section 2 describes; flags as ISA-18.2 alarms (DN-006); a receipt on every briefing sentence; the triple-keyed ERG and the ERG 2024 unit findings (LN-04) |
| G-3 | Mission alignment | — | inspection: none | evidence in place: verified by: judged, not tested; satisfied by: the FEMA ICS 201 form's own blocks; ERG 2024 distances and text; the commander stylebook (NIMS, ICS); public federal data only, with each source's attribution |
| G-4 | Presentation | HB-38 the deck is generated from the evidence | test_deck.py (a test held privately) | met: (HB-38; was not met); verified by: `test_deck.py (a test held privately)` (every number and quote traced to a committed file; the committed HTML equals a fresh build); satisfied by: README; this trace; the architecture and security notes; the evaluation document (HB-27); the slide deck `docs/submission/deck.html` and `deck.pptx`, generated from the evidence by `build_deck.py (a build tool held privately)` (HB-38) |
<!-- /seldon:projection -->

## Not-met rows

Five DN-001 rows are not met. Two are ruled out by a design note:

* **D5-10, D5-17:** the deck's base rates (CFS hazmat tables; PHMSA incident and FRA rail data).
  These were for the deck, not the server; none is computed.
* **D5-11:** the ATSDR SVI. The tract file was never acquired; CRE is the vulnerability measure
  the tools carry.
* **D5-14 (ruled out):** NHSN live capacity. DN-002 section 4.
* **D5-16 (ruled out):** EPA drinking water intakes. DN-002 section 4.

G-4, the slide deck, was the sixth until HB-38 built it. Of the application rows, C5 (location
derivation) is not met, three findings are open (F-1 to F-3), F-4 is a result, not a defect, and F-5 is
fixed (HB-99).

The partial row that changes what a judge would see in a running server is S3-2 (the dormant
low-lying-areas rules). I-5, the container that omitted the CMS and LODES caches, was the other
until HB-34 fixed it. S3-10 is partial by the stylebook's design.

## DN-009: the application's constraints (C1 to C6)

Added by HB-42 at commit `5282b29` and after, from the code HB-39 to HB-41 wrote. The application is described in
[`ARCHITECTURE.md`](ARCHITECTURE.md) section 11.

<!-- seldon:projection view="table" section="DN-009: the application's constraints (C1 to C6)" headers="ID|Decision|Requirement|Satisfied by|Checked by|State" -->
| ID | Decision | Requirement | Satisfied by | Checked by | State |
|---|---|---|---|---|---|
| C1 | HBD-074, HBD-119 | Every value carries its label: provenance class, source and endpoint, as-of, staleness against a per-source horizon, margin where one exists | — | tests/test_brief.py::test_the_committed_brief_carries_its_labels_and_the_requesters_wind; test_evidence_labels.py (a test held privately) | met: for the brief's sections and the ICS 201 blocks. A label is per tool call, not per number: a section's values share their call's label; verified by: `test_evidence_labels.py (a test held privately)` (each class; stale either side of the horizon; payload as-of; margins; the caller's wind); `tests/test_brief.py` `test_the_committed_brief_carries_its_labels_and_the_requesters_wind`; satisfied by: `evidence/labels.py` `label_for` (five classes, DN-010 ADDENDUM-00; `sources[]` per source); `docs/sources/catalog.yaml` (every horizon); `brief/render.py` (a Sources line on every section) |
| C2 | HBD-075 | Evidence files are first class: every MCP call writes an artifact; a section cites hashes; an evidence appendix; replay from hashes; PROV and RO-Crate | — | test_evidence_replay.py (a test held privately)::test_every_seed_record_replays_to_its_entity; tests/test_evidence_store.py::test_the_crate_manifest_lists_every_entity_and_record_and_is_deterministic; test_recording_client.py (a test held privately) | met: satisfied by: `evidence/client.py` `RecordingClient`; `evidence/store.py` (PROV record, RO-Crate 1.1 manifest); `labels.appendix` |
| C3 | HBD-076 | Sections degrade one at a time; per-channel timeout; the map and tables first | — | test_orchestrator_harness.py (a test held privately) | met: verified by: `test_orchestrator_harness.py (a test held privately)` (a), (b), (b'), (e); satisfied by: `brief/orchestrator.py` (channels, blackboard, `degraded_label`); `orchestrator.yaml` |
| C4 | HBD-077, HBD-130 | The model authors narrative only; it never decides what is alarming or produces a coordinate | — | tests/test_brief.py::test_no_author_writes_only_the_servers_text; tests/test_evidence_store.py::test_no_server_module_imports_the_application | met: trivially: no model authors anything yet. A model-backed author is a later task with its own spend line (DN-011 D4); satisfied by: `brief/author.py` `NoAuthor`, the only author: it writes nothing of its own |
| C5 | HBD-078, HBD-155 | A location records how it was derived, with resolution confidence | — | none | not met: no location resolution exists. A scenario's point is given as coordinates (E3, DN-009) |
| C6 | HBD-079, HBD-128 | The orchestrator has a harness: partial arrival, a stream that never answers, a stale source, replay from hashes | — | none | evidence in place: met; verified by: the harness itself, committed red at `9dcc7c1` before the orchestrator existed; satisfied by: `tests/fake_mcp_server.py`; `test_orchestrator_harness.py (a test held privately)` |
<!-- /seldon:projection -->

## DN-010: the evidence store and the labels (D1 to D7)

<!-- seldon:projection view="table" section="DN-010: the evidence store and the labels (D1 to D7)" headers="ID|Decision|Requirement|Satisfied by|Checked by|State" -->
| ID | Decision | Requirement | Satisfied by | Checked by | State |
|---|---|---|---|---|---|
| E-D1 | HBD-111 | W3C PROV vocabulary | — | tests/test_evidence_store.py::test_every_record_written_validates_against_the_schema | met: satisfied by: the record's fields (`entity`, `activity`, `startedAtTime`, `endedAtTime`, `used`, `wasRevisionOf`); `docs/schema/evidence_record.schema.json` |
| E-D2 | HBD-112 | Content-addressed, append-only store under the application | — | tests/test_evidence_store.py::test_an_entity_is_written_once_and_each_activity_is_its_own_record; tests/test_evidence_store.py::test_no_server_module_imports_the_application | met. The record name carries the activity id, an image entity is `.bin` (D-12), and the seeds are stores of their own (D-14); verified by: `test_an_entity_is_written_once_and_each_activity_is_its_own_record`; `test_no_server_module_imports_the_application`; satisfied by: `evidence/store.py` (`<sha>.json` or `.bin`, `<sha>.<activity id>.prov.json`; never rewritten) |
| E-D3 | HBD-113 | The record holds what replay and C1 need, and nothing the model wrote | — | tests/test_evidence_store.py::test_a_narrated_value_is_never_a_record; tests/test_evidence_store.py::test_the_schema_refuses_a_narrated_class_and_an_unknown_field | met; verified by: `test_the_schema_refuses_a_narrated_class_and_an_unknown_field`; `test_a_narrated_value_is_never_a_record`; satisfied by: the schema; `write_record` |
| E-D4 | HBD-114 | A label is a view of a record, computed at render time | — | test_evidence_labels.py (a test held privately)::test_the_erg_guidance_label_is_the_pack_class_and_nothing_else | met: satisfied by: `labels.label_for` |
| E-D5 | HBD-115 | The model never writes a record | — | test_evidence_labels.py (a test held privately)::test_a_value_with_no_record_or_a_narrated_one_cannot_be_labelled; tests/test_evidence_store.py::test_a_narrated_value_is_never_a_record | met; verified by: `test_a_narrated_value_is_never_a_record`; `test_a_value_with_no_record_or_a_narrated_one_cannot_be_labelled`; satisfied by: `write_record` refuses `narrated_by_model`; `label_for` raises with no record |
| E-D6 | HBD-116 | The appendix renders from records; replay is the test; RO-Crate packaging | — | test_evidence_labels.py (a test held privately)::test_each_tool_call_replays_to_its_entity; test_evidence_labels.py (a test held privately)::test_the_fixtures_equal_a_fresh_render; test_evidence_replay.py (a test held privately)::test_a_replayed_body_that_moved_is_a_mismatch_not_a_pass; test_evidence_replay.py (a test held privately)::test_every_seed_record_replays_to_its_entity | met; verified by: `test_the_fixtures_equal_a_fresh_render`; `test_every_seed_record_replays_to_its_entity`; `test_each_tool_call_replays_to_its_entity`; `test_a_replayed_body_that_moved_is_a_mismatch_not_a_pass`; satisfied by: `labels.appendix`; `store.write_crate_manifest` |
| E-D7 | HBD-073, HBD-117 | Nothing crosses the frozen surface before 2026-11-20 | — | test_double_wrap_hint.py (a test held privately)::test_every_block_that_cites_a_tool_carries_its_labels; test_double_wrap_hint.py (a test held privately)::test_the_tool_surface_is_hb36s | met: satisfied by: the store and labels are client-side; `render_ics201` leaves the tool's response unchanged |
<!-- /seldon:projection -->

## DN-011: the orchestrator and its harness (D1 to D7)

<!-- seldon:projection view="table" section="DN-011: the orchestrator and its harness (D1 to D7)" headers="ID|Decision|Requirement|Satisfied by|Checked by|State" -->
| ID | Decision | Requirement | Satisfied by | Checked by | State |
|---|---|---|---|---|---|
| O-D1 | HBD-120 | One process, asyncio, per-source channels with their own timeouts; the blackboard holds hashes | — | tests/test_brief.py::test_every_channel_reads_the_catalogs_rows_for_its_tool; test_orchestrator_harness.py (a test held privately) | met: The timeouts are per-tool defaults, because the catalog states none (D-13); satisfied by: `brief/orchestrator.py` `assemble`; `orchestrator.yaml` `channels` |
| O-D2 | HBD-121 | Eight sections that degrade one at a time with an `unavailable` label; no retry inside an assembly | — | none | evidence in place: met; verified by: harness (b), (b'); `test_a_replay_with_no_record_degrades_and_says_so`; satisfied by: `sections`, `degraded_label`; `resolve` |
| O-D3 | HBD-123 | A render order, not a completion order; channels start when their inputs exist (ADDENDUM-00) | — | none | evidence in place: met; verified by: harness (a), (e); satisfied by: `render_order`; `needs` |
| O-D4 | HBD-124 | The model authors nothing in this cut; `NarrativeAuthor` with `NoAuthor` | — | tests/test_brief.py::test_no_author_writes_only_the_servers_text | met; verified by: `test_no_author_writes_only_the_servers_text`; satisfied by: `brief/author.py` |
| O-D5 | HBD-125 | A CLI that writes one HTML file with the house style, the map first, the appendix beside it, and a status line with timings | — | tests/test_brief.py | met: The map's roads are the TIGERweb image `build_ics_201` recorded, embedded from the store; verified by: `tests/test_brief.py` (the committed brief byte for byte; it opens from `file://`; the console script routes `brief`); satisfied by: `brief/cli.py`, `brief/render.py`, `command.py` |
| O-D6 | HBD-126 | The orchestrator calls the server over MCP with no import from `hazbrief.tools`; every call recorded | — | test_recording_client.py (a test held privately) | met: verified by: `test_recording_client.py (a test held privately)`; harness (all against a spawned server); satisfied by: `RecordingClient` over `PythonStdioTransport` |
| O-D7 | HBD-128 | The harness first and red: partial arrival, a hang, a stale source, replay from hashes, render order | — | none | evidence in place: met; verified by: red at `9dcc7c1`, green at `47a842b`; satisfied by: `test_orchestrator_harness.py (a test held privately)` |
<!-- /seldon:projection -->

## Open findings carried from HB-39 to HB-41

| ID | Finding | State |
|---|---|---|
| F-1 | The footprint reads 49 CFR 172.101 (its basis carries the hazard class tag), but its MCP description names only the ERG. The description is part of the frozen surface. | open, for E8 after 2026-11-20. The catalog lists the read under `undocumented_readers` |
| F-2 | C5, location derivation, has no implementation | open, E3 |
| F-3 | The deck's table trace checks a number under its row's key path, which ends at the measure's object. A number that equals another number of the same row (its interval's bound) passes. Per-cell key paths would close it (HB-38 RESULT section 4) | open |
| F-4 | Sections of the committed briefs read stale, two to six per brief (`docs/briefs/*/brief.html`; `docs/evidence/hb95/brief_states.txt`). On all 23, the hospitals section: the cached CMS hospital file is older than its quarterly horizon. Since HB-94, the sections that name the 49 CFR 172.101 table (map, footprint, flags, guidance, ICS 201; all five on 11 briefs, four on 7, the ICS 201 alone on 5): the pack is the annual edition revised as of 10/01/2025, past its one-year horizon at the fixture instant, 2026-10-26 (HB-94 RESULT, Part A) | a result, not a defect. The fixes are a cache refresh (`scripts/fetch_cms.py`) and the 2026 annual edition of the 172.101 pack, neither done |
| F-5 | Four committed briefs (`guide-111-wilson-bridge`, `placard-2-3-i81`, `propane-unresolved-i81`, `un1057-fire-unresolved-i81`) cite in their appendix a footprint record from another scenario. The values are right; the provenance row names the other scenario's call (`docs/evidence/hb94/footprint_citations.txt`; Issue `e4074961`; HB-94 RESULT, step 7) | fixed by HB-99. Two causes. The appendix printed each cited hash's newest record, which for a body other scenarios' calls also returned was another scenario's call; it now prints the record the brief read (`labels.appendix_rows` `records`). And a held call is keyed by `(tool, params, used)` (`store.records_for`), so `un1746-small-i81-water`, a fifth brief that shared its land twin's reader records, holds its own. The same appendix fix corrected 12 briefs' guidance rows, which printed another scenario's location (`docs/evidence/hb99/appendix_diff.txt`). Checked by `tests/test_brief_footprint_citation.py` |

## DN-019 and DN-022: the view (VR-001 to VR-148)

Added by HB-134R2 at commit `f199b101`. The view has its own table, [`VIEW_REQUIREMENTS.md`](VIEW_REQUIREMENTS.md),
for three reasons:
* **Size.** Its rows outnumber this document's. Every layer of the map, every panel DN-022 adds, the stream and the
  static page each get a row.
* **Validation.** Its rows record the review finding or operator answer that confirmed or changed the row (the TEVV
  loop of DN-019 section 1 and HB-133 ADDENDUM-01 section 4). Until HB-149 that was a `Validated by` column; no
  graph edge computes it, so it is now the `validated by:` record in the row's note, shown in its Status cell.
* **Process.** Its rows change at each review cycle. A finding becomes a row change in the task that fixes it.

It keeps this document's conventions:
* an id with a prefix and a number;
* a state checked against the code, not taken from a note;
* a row with no automated check says so ("none yet", counted);
* the trace kit's columns written by hand, since the kit (`trace__*`) is not installed beside this repository.

Its states map to this document's:
* `satisfied` is **met**;
* `open` is **partial** or **not met**;
* `changed` marks a row a review finding changed, verified by its test and awaiting the next review;
* `withdrawn` keeps a row a later governing text removed;
* `implemented` (from HB-149) is **evidence in place**: the row was called satisfied or changed, but no test verifies
  it yet, so its Status reads `implemented: <the old word>` until a test carries `@pytest.mark.verifies("VR-NNN")`.

The table at HB-141: <!-- seldon:projection view="counts" document="docs/VIEW_REQUIREMENTS.md" -->183 rows: 139 satisfied, 21 open, 14 changed, 4 withdrawn; 27 verified by "none yet"; 0 not yet specified<!-- /seldon:projection -->. HB-131R satisfied the panels and the question box (VR-101 to VR-104, VR-114 to VR-117, VR-119 to VR-127).
HB-140R satisfied VR-013 on the reference pair, recorded live under its one-wind footprints. HB-139 built the weather
source (VR-022, VR-024 and the new VR-149 satisfied; VR-026 changed under Issue `473bdfeb`'s ruling; VR-023 open on
its MCP clause and VR-025 on the observed client). HB-141 restated VR-102 to VR-104 for the operator checklist, VR-123
and VR-125 for the question route the page no longer calls, changed VR-027 (F1, the wind field) and VR-146 (F2, the docked
layer control), met the chips clause of VR-148 (F10), and added VR-150 to VR-154: the ticks, the ICS 201 annex, the
replay banner, the street basemap and the guide panels (VR-154 open on Issue `bf171525`).
The open rows are mostly HB-132R's load read and entry form, not yet built, and live findings against the first screen:
* VR-002: the map does not span the full width;
* VR-022: the legend has no wind entry;
* VR-030: the neighbour cells read another day (`1d2af494`);
* VR-032: the stepper does not move the modelled layers;
* VR-058: the two engines read different tiers and durations (`74492d10`).

The matrix, the backward trace and the orphans are exported to
[`evidence/hb134/rtm.md`](evidence/hb134/rtm.md). `test_view_requirements.py (a test held privately)` holds the table, the export and the
counts in this paragraph together.
