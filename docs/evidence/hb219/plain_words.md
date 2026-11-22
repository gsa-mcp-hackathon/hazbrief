# HB-219: the deck in plain words

**Task:** `HB-219` and its ADDENDUM-01.
**From:** the operator's statement of 2026-11-21 22:26 EST: "We should never be using jargon. That is anti-Heilmeier
question practice, that we should be able to explain things simply without jargon, especially on briefing slides."

This is the record the deck quotes where a slide line is said in plain words (`docs/submission/deck.yaml`, each such
line's `source`). Each numbered line below is what the slide prints. Under it, each sentence it restates is quoted
from its file, and that file stays on the slide's sources line (the line's `restates`). The words change; no number,
no source and no claim does (HB-219 item 4). `test_hb219_plain_words.py (a test held privately)` holds each quoted sentence to its file,
each number of a plain line to the sentences it restates, and the record to the slides.

Where a line spells out or explains an acronym, the expansion is the name its body uses: the Emergency Response
Guidebook (ERG) and the Acute Exposure Guideline Levels (AEGL) are named so in README and the commander stylebook; the
Incident Command System (ICS) form 201 is the Incident Briefing (`docs/stylebook/COMMANDER_STYLEBOOK.md`, its receipt
from the held ICS 201 form); HPAC (Hazard Prediction and Assessment Capability) is named so in HB-188's review of
the held SCIPUFF slides (`docs/evidence/hb188/review.tsv`); ALOHA (Areal Locations of Hazardous Atmospheres) in the
benchmark table's definitions (`docs/evidence/hb214/benchmark_table.md`); SCICHEM is the Electric Power Research
Institute's model ("EPRI SCICHEM 3.4", `docs/evidence/hb213/lifted/decisions.md`); the geometric mean (MG) in the same table's
definitions. Nothing else is expanded: the other acronyms the deck printed are said in plain words instead.

## Slide `title`

1. A Model Context Protocol (MCP) server for a 2026 government hackathon, in its Dataset Access Server category.
   - `DN-001`: "An MCP server for the GSA Model Context Protocol Server and SI Agent Government Hackathon (2026), Dataset Access Server category."

## Slide `problem`

2. From 2016 to 2025, 146 rail incidents released hazmat in the contiguous United States; 4 of them in the Mid-Atlantic region our test scenarios cover.
   - `docs/incidents/incident_hotspots.md`: "From 2016 to 2025, 146 rail incidents released hazmat in the conterminous U.S.; 4 of them in the Mid-Atlantic region the fixtures cover."
3. Today's tools draw the area at risk; they do not say who is inside it: residents, workers, schools in session, hospitals.
   - `DN-001`: "Those tools stop at the footprint. They do not say who is inside it, which group quarters cannot be moved, which schools are in session, which hospital is inside the zone and therefore a casualty site rather than a receiver, or what the daytime worker population is against the residential count."
4. Today the incident's planning staff put that picture together by hand.
   - `DN-001`: "That fusion is done today by a Situation Unit by hand."
5. This server automates that work, not the physics.
   - `DN-001`: "This server automates the fusion, not the physics."

## Slide `solution`

6. Given a hazmat accident in transport (material, container, place, time), it gathers public federal data into the area to protect, warnings that each name their source, and a draft Incident Command System briefing form (ICS 201).
   - `DN-001`: "Given a transported-hazmat accident (material, container, location, time), it fuses public federal data into a structured protective action footprint, a set of sourced flags, and a draft ICS 201 Incident Briefing."
7. Every distance comes from the federal Emergency Response Guidebook (ERG).
   - `DN-001`: "Distances trace to the PHMSA Emergency Response Guidebook (ERG)."

## Slide `solution-clock`

8. The application draws one modelled cloud for each level of health effect (Acute Exposure Guideline Levels AEGL-3, AEGL-2 and AEGL-1), from the one model a published test chooses for the release.
   - `README.md`: "it draws one modelled cloud by health-effect level (AEGL-3, AEGL-2 and AEGL-1) from the one engine a held criterion names for the release"
9. The cloud is drawn for every 15 minutes of its time, each step shown as soon as it is computed, with a Play control.
   - `README.md`: "held as a frame every 15 minutes of cloud time on a coarse mesh whose level outlines are drawn from it, each frame shown as it is computed, with one Play control off by default"
10. The protective action distance is the guidebook's.
   - `README.md`: "The ERG footprint is the protective action distance."

## Slide `solution-timeline`

11. The timeline is evidence, and the list of events for an exercise; it is not the commander's view for decisions.
   - `README.md`: "The timeline is evidence and the exercise events list, not the commander's decision view"
12. The checklist exists to remind the reader to think critically about the brief and the quality of its information.
   - `docs/ARCHITECTURE.md`: "It exists to remind the reader to think critically about the brief and the quality of its information"
13. A line that later data made false is struck through, not removed.
   - `docs/ARCHITECTURE.md`: "a line a later settle made false is struck through, not removed."

## Slide `thesis`

14. This is the author's stated position; it is a contention, and this evaluation does not test it.
   - `docs/submission/EVALUATION.md`: "This is the operator's stated position, recorded as his decisions; it is a contention, and this evaluation does not test it."

## Slide `uses`

15. A quick answer: the material's four-digit number and a place in, first actions out, short enough to read aloud.
   - `DN-022`: "Quick-answer mode (UN plus location in, first actions out, short enough to read aloud)"
16. A drill generator: practice scenarios placed along a named rail line or road.
   - `docs/evidence/hb213/lifted/decisions.md`: "a drill generator seeds scenarios along a named corridor."
17. The list of events for an exercise, filled from the timeline: each event's number, time and message.
   - `docs/briefs/csx-point-of-rocks-night/timeline.html`: "hazbrief fills the event number, time and message from this timeline"
18. Who is there by day: workers as well as residents.
   - `DN-001`: "what the daytime worker population is against the residential count."

## Slide `tools`

The table's rows: each row's two cells, the tool's own name and what it reads, and the cell it restates.

19. `assess_incident` | bundled reference data; sunrise and sunset by the federal solar equations
   - `docs/ARCHITECTURE.md`: "packs; sunrise and sunset by the NOAA equations (`astral`)"
20. `protective_action_footprint` | bundled reference data; the National Weather Service forecast when no wind is given
   - `docs/ARCHITECTURE.md`: "packs; NWS forecast grid when no wind is given"
21. `population_at_risk` | Census Bureau maps and population counts; a cached file of where people work
   - `docs/ARCHITECTURE.md`: "TIGERweb, Census Data API (DHC, ACS, CRE); `fixtures/lodes/`"
22. `facilities_in_footprint` | federal maps of buildings, water and transport; a cached file of hospitals and nursing homes
   - `docs/ARCHITECTURE.md`: "USGS Structures, USGS 3DHP, BTS NTAD; `fixtures/cms/`"
23. `receiving_hospitals` | the cached file of hospitals and nursing homes only
   - `docs/ARCHITECTURE.md`: "`fixtures/cms/` only"
24. `material_response_guidance` | bundled reference data only
   - `docs/ARCHITECTURE.md`: "packs only"
25. `build_ics_201` | the six tools above; Census Bureau places, counties and roads; National Weather Service points
   - `docs/ARCHITECTURE.md`: "the six tools above, TIGERweb places, counties and roads, NWS points"

## Slide `architecture`

26. It reads six checked data files, two cached file sets and six live federal services. It writes nothing back and calls no model.
   - `docs/ARCHITECTURE.md`: "It reads six verified JSON packs, two cached file sets and six live federal services. It writes nothing upstream and calls no model."

## Slide `engines`

27. A published test (the critical Richardson number) classes the release as a dense gas, a gas that drifts with the air, or not classed.
   - `README.md`: "the critical Richardson number of NOAA's NOS OR&R 43 classes the release dense, passive or not classed"
28. A dense gas is modelled by SCICHEM, a dispersion model from the Electric Power Research Institute, on the forecast wind, hour by hour.
   - `README.md`: "A dense release is drawn by SCICHEM, run in a separate models image on the forecast wind hour by hour"
29. A release the test cannot class is not modelled, and the brief says why.
   - `README.md`: "A release the criterion cannot class draws neither and says why"
30. Every number carries its source: the tool output it came from, with its value, or a document and page.
   - `docs/ARCHITECTURE.md`: "A receipt is a tool output path with its value, or a document and page."

## Slide `decisions`

31. A rule the language model is expected to follow is a hope. A rule the server applies, with its reason in the output, is a guarantee, and the model only narrates it.
   - `docs/submission/EVALUATION.md`: "A rule the client is expected to follow is a hope. A rule the server applies, with its reason in the output, is a guarantee, and the client only narrates it."
32. A tool result that is correct but over the model's size limit never reaches the model.
   - `docs/submission/EVALUATION.md`: "A tool result that is correct but over the client's cap never reaches the model."

## Slide `testing`

The table's rows: each row's two cells, the level and what it tests, and the cells they restate.

33. Part A: fixed rules on every output | Every output the tools can produce obeys the server's fixed rules.
   - `docs/submission/EVALUATION.md`: "Part A: exhaustive invariant checks"
   - `docs/submission/EVALUATION.md`: "Every output the tools can produce obeys the invariants."
34. Part B: saved scenarios rerun | No change moves any tool output on any saved scenario unnoticed.
   - `docs/submission/EVALUATION.md`: "Part B: scenario regression"
   - `docs/submission/EVALUATION.md`: "That no change moves any tool output on any frozen scenario unnoticed."
35. Part C: live sources | Whether the federal sources the server reads still answer as they did when the test scenarios were recorded.
   - `docs/submission/EVALUATION.md`: "Part C: live drift"
   - `docs/submission/EVALUATION.md`: "Whether the federal sources the server reads at runtime still answer as they did when the fixtures were recorded."
36. Part D: the language model's replies | Is every number and name in its reply backed by a tool output?
   - `docs/submission/EVALUATION.md`: "Part D: the agent evaluation"
   - `docs/submission/EVALUATION.md`: "Is every number and name in its reply grounded in a tool output?"

## Slide `benchmarks`

37. HPAC (Hazard Prediction and Assessment Capability) and ALOHA (Areal Locations of Hazardous Atmospheres) are tools responders rely on; SLAB is hazbrief's second dense-gas model.
   - `docs/evidence/hb214/benchmark_table.md`: "Why HPAC and ALOHA, the operator: "the community tools that people have been relying on ... the gold standard for the community.""
   - `docs/evidence/hb214/benchmark_table.md`: "ALOHA's (Areal Locations of Hazardous Atmospheres) published run of the trial in the 17-model comparison."
   - `README.md`: "SLAB runs beside it as its second method"

## Slide `demo-outline`

38. The start page lists the prepared scenarios: tests, each with a brief recorded at a past date.
   - `README.md`: "The first lists the prepared scenarios that have a recorded brief: the place, the material by its ERG name and ID number, the container, the time the run is for and whether it is day or night, each read from the scenario's record."
   - `docs/submission/EVALUATION.md`: "That no change moves any tool output on any frozen scenario unnoticed."
39. Open one as it was recorded, with its recorded weather.
   - `src/hazbrief/brief/orchestrator.yaml`: "Open the recorded run as it was recorded, with its recorded weather;"
40. Or run the same one with today's conditions: now, on today's forecast, every field open to change.
   - `README.md`: ""Run it with today's conditions" copies the scenario's material, container, quantity and place into the entry form, with now as the start time and today's forecast as the weather; every field can be changed, the place included, before Build."
41. Or enter a new incident: a point on the map and a situation line.
   - `src/hazbrief/brief/orchestrator.yaml`: "The entry form: a point on the map and a situation line."
42. Then the brief page, its checklist, its test and evaluation page, and what is next.
   - `docs/submission/demo/OUTLINE.md`: "The brief page"
   - `docs/submission/demo/OUTLINE.md`: "The checklist and the TEVV page"
   - `docs/submission/demo/OUTLINE.md`: "What is next"
43. The server on its own also answers any MCP client.
   - `README.md`: "The server speaks MCP over stdio."

## Slide `demo-fallback`

44. Before a fix, the instructions' run line started a server that did not answer: the connection closed after 60.1 s.
   - `docs/evidence/hb201/image.md`: "`/health`: RemoteDisconnected after 60.1 s, `Remote end closed connection without response`"
45. After the fix, the lines run: the health check answers, 7 tools are listed, and 0 of 20 fields compared differ.
   - `docs/evidence/hb197/readme_container.md`: "`/health` from the host | 200 after 4.5 s"
   - `docs/evidence/hb197/readme_container.md`: "7: assess_incident, build_ics_201, facilities_in_footprint, material_response_guidance, population_at_risk, protective_action_footprint, receiving_hospitals"
   - `docs/evidence/hb197/readme_container.md`: "20 fields compared, 0 differences"

## Slide `backup-model-use`

46. MG: the geometric mean of measured over predicted concentration; 1 means no difference.
   - `docs/evidence/hb214/benchmark_table.md`: "Ratio: against the measurements, the geometric mean of measured over predicted concentration (MG); against a tool, the run's MG divided by the tool's. 1 means no difference; above 1 means the run's concentrations are lower."
