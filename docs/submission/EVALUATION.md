<!-- seldon:projection-revision 71058f7701954d3e (the tables and counts between seldon:projection markers are rendered from the graph by `seldon docs generate requirements`; change a requirement with `seldon req`, not here; AD-013-R2) -->
# hazbrief-mcp: evaluation

## Results at a glance

Four levels of testing, each run on the final tool surface. Each row cites the committed report
that holds its numbers; sections 1 and 2 give the method and the detail.

| Level | What it checks | Result | Source |
|---|---|---|---|
| A, invariants (no network, no model) | Every ERG ID number and name, every Table 1 and Table 3 cell, every guide, every flag rule | 24,846 footprint outputs reach 3,374 of 3,374 pack cells; 106,174 distances traced to their cells; 0 failures | `eval/reports/2026-10-25_invariants.json` |
| B, regression (no network) | The frozen scenarios through the seven tools | 18 scenarios, 121 scenario-tool outputs, 26 expected entries and 12 frozen files compared; 0 differences | `eval/reports/2026-10-25_regression.json` |
| C, live drift (network) | The federal sources, called live, against the recordings | 120 calls, 0 failed; no upstream field the server reads changed. The run stopped at its call ceiling, so nine of the seventeen scenarios' outputs were not compared | `eval/reports/2026-10-25_live.json` |
| D, agent evaluation (Claude over stdio) | Three Claude models, each prompt three times: right tools, right arguments, every number grounded | 288 episodes. The demo model, `claude-opus-5-5`: tool precision 100.0 %, scenario pass 92.6 %, grounding 94.2 % | `eval/agent_runs/2026-10-25/summary.json` (`n`, `tool_precision`, `scenario_pass`, `grounding_rate_pooled`) |
| D, requests the seven tools do not serve | Five such requests, each three times: a cloud's travel and concentration, a drive time, an ID number the ERG does not list, changed ERG distances, the 2020 edition | The demo model's strict out-of-scope refusal is 20.0 %: 3 of 15 replies named the limit and gave no number a tool output does not hold; 9 named it and gave such a number; 3 did neither. Two of Sonnet's measures fell outside the previous run's interval (section 2.4) | `eval/agent_runs/2026-10-25/summary.json` (`out_of_scope_refusal`); `docs/evidence/hb196/out_of_scope.tsv`; `eval/agent_prompts.yaml` |
| The modelled layers (the application, not the server) | The dense cloud against the benchmark requirement and against measured field trials | Verified, not validated. Against the requirement's published benchmarks, on Jack Rabbit II Trial 7's five arcs at 0.2 to 5 km, where the one-minute rule gives the route a prediction (Issue `1e15434e`); one trial, and the five arcs are of one release. Against the measurements first: the SCICHEM run is below them, a difference that is statistically significant at the 95 percent confidence level (MG 2.88, 95 percent limits 1.58 to 5.27), within a factor of two of the measured arc maximum at 1 of 5 arcs; the SLAB run's difference from them is not statistically significant at the 95 percent confidence level (MG 1.43, limits 0.83 to 2.47), at 4 of 5; nor are those of HPAC's two published runs (MG 1.73 and 1.63), at 3 and 4 of 5, or ALOHA's (MG 2.13), at 3 of 5. Against the tools second: by the held difference test no hazbrief run's difference from a tool's is statistically significant at the 95 percent confidence level, so BENCH-8 and BENCH-9 read not statistically significant at 95 percent and the minimum reads not statistically significant at 95 percent against HPAC or ALOHA (HB-206; HB-209; HB-212; HB-213); not yet evaluated on the seven over trials 1, 6 and 7. Against stable dense field trials: SLAB within a factor of two at every arc, SCICHEM below every arc, MG 3.50 (section 2.7) | `docs/evidence/hb192/benchmark_rows.md`; `docs/evidence/hb209/trial7_intervals.tsv`; `docs/evidence/hb212/states.tsv`; `docs/evidence/hb176/summary.tsv`; `docs/evidence/hb180/statistics_c.tsv` |

**Key to the internal ids.** The document cites the project's own record by id:

* `HB-` followed by a number is a task. Its specification and its RESULT are in `cc_tasks`, named by
  date and id.
* `DN-` is a design note, and `LN-` a lab note, under `design` and `lab`.
* `F-` is an eval harness finding and `A-` an agent evaluation finding, both in
  `eval/known_findings.yaml`.
* `G-`, `I-` and `S3-` are rows of `docs/REQUIREMENTS_TRACE.md`. I-81 and I-83 are interstate
  highways.
* `SQ-` is a task filed to Squiddy, the separate claim-graph toolkit the corpus is built with.
  "The kit" is Squiddy.
* `AD-` is an architectural decision of Seldon, the record-keeping tool that dispatches the tasks.
* Key A is the ERG PDF's own text layer, the first of three readings of each ERG cell
  (`docs/ARCHITECTURE.md` section 4). "The operator" is the project's author.

**Task:** `docs/evidence/hb213/lifted/HB-27.md` (HB-27).
**For:** the evaluation document GSA asks for, under its four headings (DN-001 section 1):
testing methodology, performance metrics, security considerations, and lessons learned with
recommendations.

**How to read the numbers.** Every number here is read from a committed file. That file is cited
in the same row, paragraph or list item. Nothing was measured again for this document.
`test_evaluation_document.py (a test held privately)` checks that each cited file is committed and holds each
number cited from it. Run logs under `logs/` are not committed, so no number is cited from a log.
Where a log holds the latest figure, the committed RESULT that reports it is cited instead.

## Front matter

| | | Source |
|---|---|---|
| Server | hazbrief-mcp, registry name `io.github.brockwebb/hazbrief-mcp` | `server.json` |
| Category | Dataset Access Server | `DN-001` |
| Version | 0.1.0 | `pyproject.toml`, `server.json` |
| Pack schema | version 8, all seven packs | `packs/erg.json` `schema_version` |
| Packs | ERG `erg2024.5`; the hazmat table of `49 CFR 172.101`, `cfr2025.1`; CAMEO `cameo3.1.0.1`; flag rules `hb18.1`; hazard classes `dn001.1`; vocabulary `hb03.1`; suggested actions `hb207.1` | `packs/erg.json`, `packs/cfr172.json`, `packs/cameo.json`, `packs/flag_rules.json`, `packs/hazard_classes.json`, `packs/vocabulary.json`, `packs/suggested_actions.json` (`version`) |
| Tool surface | `fded04ec6c0e`, the sha256 of every tool's name, description and input schema, the surface HB-36's runs measured | `eval/agent_runs/2026-10-25/tool_surface.json` `sha256` |
| Date of the server's evaluation runs | 2026-10-25 | |
| This edition | 2026-11-18, brought to main by HB-196 | `docs/evidence/hb213/lifted/HB-196.md` |
| Known limits and future work | generated from the graph's Issues and decisions | `docs/FUTURE_WORK.md` |

**No dispersion model runs in the server.** Every distance the server returns is a cell of the PHMSA Emergency
Response Guidebook (ERG 2024). It comes from Table 1, Table 3, or an orange guide's evacuation
distance, laid out downwind by the wind given or read from NWS. The server calls no model. The
client narrates, and the server never decides what is alarming. These are DN-001 section 4,
invariants 1 and 2 (`DN-001`). The ERG edition is in
`packs/erg.json`.

**Who already plans for a release.** GSA's four headings ask for no statement of use, so it is
here (HB-216). Every facility under EPA's Risk Management Program must analyse and report a
worst-case release scenario (40 CFR 68.25; about 11,740 facilities have filed current plans), and
every local emergency planning committee must plan for releases, transport routes included (EPCRA
section 303). hazbrief gives them the same fused picture for a what-if release: a brief built from
a stated wind; a worst-case scenario builder is next, not built (Issue `d54dbcb8`). The operator
also names exercises, pre-incident plans, siting and zoning as uses; that is his statement, not a
held source's (`docs/evidence/hb216/planning_uses.md`).

The system itself is described in `docs/ARCHITECTURE.md`. The requirements trace, row by row, is
`docs/REQUIREMENTS_TRACE.md`.

## 1. Testing methodology

**The server runs no dispersion model; the application draws a labelled modelled cloud.** The
seven tools run no dispersion model. Every distance a tool returns is a cell of the ERG 2024
tables or guides (`packs/erg.json`). No tool result and no ICS 201 carries a modelled value. The
`hazbrief brief` application is a client of the server, not part of it. Beside the ERG
footprint, it draws one modelled cloud by health-effect level (AEGL-3, AEGL-2 and AEGL-1) from
the one engine a held criterion names for the release: the critical Richardson number of NOAA's
NOS OR&R 43 classes the release dense, passive or not classed
(`DN-026`).
A dense release is drawn by SCICHEM, run in a separate models image on the forecast wind hour by
hour (`DN-028`);
by day, where no hour of the brief's horizon is a stable class, SLAB runs beside it as its second method, a layer off by default on one wind, and where
the two disagree beyond the held factor of three, the checklist carries one warning with both results; that is the rule, and no committed brief meets its condition, so no committed brief raises the warning (Issue afab181e; HB-189; HB-173). Where any hour of the brief's horizon is a stable class, as at night or where an afternoon release runs into the evening, the moving cloud is the primary layer: SCICHEM's run by level, hour by hour, at a stated 1.25 m vertical setting, an approximation that is not converged, held as a frame every 15 minutes of cloud time on a coarse mesh whose level outlines are drawn from it, each frame shown as it is computed, with one Play control off by default (DN-024 ADDENDUM-01; HB-192); SLAB checks how far, its area drawn to where a level closes or to the release hour's wind's travel in the horizon and 30 percent over, a dashed outline with no times beside the filled cloud; counts and candidate blocks are stated for AEGL-3 and AEGL-2, every time is the 1.25 m run's and no warning is raised (HB-189). Each engine's conditions of use are a section of the brief's TEVV page. The benchmark requirement is another, Benchmarks and requirement: its minimum, its objective and hazbrief's status against each published benchmark: on Jack Rabbit II Trial 7's five arcs at 0.2 to 5 km, where by the one-minute rule its SCICHEM run is within a factor of two of the measured arc maximum at 1 arc and its SLAB run at 4, against 3 and 4 for HPAC's two published runs and 3 for ALOHA's; against the measurements its SCICHEM run is below them, a difference that is statistically significant at the 95 percent confidence level (MG 2.88, 95 percent limits 1.58 to 5.27), and no other run's difference from them is statistically significant at that level; against the tools no hazbrief run's difference in mean bias is statistically significant at the 95 percent confidence level (one trial, five arcs of one release; `docs/evidence/hb212/states.tsv`); not yet evaluated on the others (HB-206; HB-209; HB-212; HB-213); the accepted tools are named there and on no map page (HB-192). A passive release is
drawn by a first-order passive Gaussian puff that starts on its release hour's wind and is then
carried on each later forecast hour's wind (a stated or observed wind is one wind for every hour),
by level like the dense cloud
(`DN-025`;
`src/hazbrief/brief/puff.py`); it is not a dense-gas model, and no committed brief is passive. A
release the criterion cannot class draws neither and says why, and nothing from an engine the
criterion did not name is drawn. Each modelled layer has a section on the brief's TEVV page;
none of the modelled layers is validated against observations of a release; the two dense engines, as hazbrief runs them, are compared with the measured arc maxima of stable dense field trials at 212 to 800 m: SLAB within a factor of two at all 10 (four trials), SCICHEM below 7 of 8 (three trials) by a factor of 1.8 on geometric average when scored as its authors score a peak, and its mean, which the brief draws, below all 8 by a factor of 3.5 at the shipped 250 m setting; at the 1.25 m setting a stable brief now runs, every trial arc still reads below the measurement (HB-187)
(`docs/evidence/hb159/tevv_rows.md`; `docs/evidence/hb176/summary.tsv`; `docs/evidence/hb177/hb176_restated.tsv`). The ERG footprint is the protective action distance.
Every ERG guide is routed: where its chemistry takes a release model, the modelled layers apply;
where it does not (explosives, radioactive materials, oxidisers, solids and others), the brief says
so in the guide's own words and draws neither (`packs/release_routing.json`).
Smoke from a fire is a future use: a fire brief names the VSMOKE layer and draws no band, because
no held open engine builds and reproduces its manual's example (HB-150; operator decision of
2026-11-09).
The container image ships the server alone, without the modelled layers' code or packs
(`.dockerignore`; `test_container_image.py (a test held privately)`). The four levels below test the server. The
application's own tests cover the modelled layers, and no number in this document is a modelled
layer's.

The modelled layers are verified, not validated (one row per layer and method:
`docs/evidence/hb159/tevv_rows.md`, generated from the graph). SCICHEM, the dense engine, is built
with gfortran in the models image and at every build reproduces EPRI's own Intel build on HB-165's
chlorine case, every value within 1 percent (`deploy/models/scichem/check/check_engine.py`). On
the published stable railcar case it ran 3 to 5 times below its own published curve on the
boundary layer it calculates (HB-169); a stable class now takes the documented PGT layer instead,
on which it is still 2 to 4 times below (HB-172). Its stable answer moves with the vertical setting and
is not converged at any setting run (HB-180, HB-187), so where any hour of a brief's horizon is
stable the moving cloud is drawn hour by hour at a stated 1.25 m setting, an approximation, with
SLAB's time-bounded area as a dashed extent check beside it (HB-189; the deficiencies below).
SLAB, the second method, is checked against its own test cases: SLAB test cases 1 to 4 reproduce
at build (`deploy/models/check_cases.py`, every build of the models image). The 1991 EPA
evaluation's own runs are not repeated. Volume II of the Air Force's hazard response evaluation
holds every input and every observed arc maximum of its stable trials, and HB-176 ran both engines
on the four that hazbrief's paths take, as hazbrief runs them, by a protocol fixed before the runs:
SLAB is within a factor of two at all 10 measured arc maxima at 212 to 800 m, and SCICHEM is below
all 8 it ran, by a factor of 3.5 on geometric average (`docs/evidence/hb176/summary.tsv`;
DN-028 ADDENDUM-06). The 1991 report's own words are: "Systematic bias is seen in SLAB simulations of the DT and HF releases
while the Burro simulations appear relatively successful", and "Apparently, the SLAB jetting
algorithm overestimates initial cloud dispersion" (`epa-dense-gas-evaluation-1991`, PDF p94, as
`docs/evidence/hb102/evaluation_1991.md` reads it). The passive puff reproduces the reference
C++ core on identical inputs within 1e-6 relative; the paper's comparison with field releases is
not re-run, because the release data is not public (HB-68). No modelled layer is a protective
action distance. On the committed fixtures a cloud draws for chlorine alone: LPG in a fire,
refrigerated nitrogen and gasoline are classed dense and draw none, and no committed brief is
passive (`docs/evidence/hb163/engine_by_brief.tsv`). The tests are `test_hb167_scichem.py (a test held privately)`,
`test_hb163_one_cloud.py (a test held privately)`, `test_hb162r_passive_follows_the_forecast.py (a test held privately)`,
`test_brief_dense_gas.py (a test held privately)` and `test_brief_puff.py (a test held privately)`.

**The modelled layers' deficiencies, each with its evidence and what a later version needs**
(operator finding `7745d8c1`-2: the MVP's deficiencies stated with their enhancements). Each
engine's conditions of use, row by row with its evidence file, are sections T58 (SCICHEM) and
T59 (SLAB) of every dense brief's TEVV page (`src/hazbrief/brief/conditions.yaml`;
`DN-028 ADDENDUM-10`;
`DN-028 ADDENDUM-12`;
`docs/evidence/hb213/lifted/DN-028_ADDENDUM_14.md`).

1. **Under a stable class SCICHEM's answer is not converged.** On stable dense field trials
   (Desert Tortoise 4, Thorney Island 45 and 47; 8 arcs at 212 to 800 m) the mean a brief draws is
   below every arc, MG 3.50, and 1.80 scored as its authors score a peak
   (`docs/evidence/hb180/statistics_c.tsv`; `src/hazbrief/brief/conditions.yaml`). The shipped request leaves its vertical grid at 250 m
   for a cloud 2 to 27 m deep; refined to 0.625 m, csx night's arc maxima rise 2.03 to 4.29 times
   with no plateau, at 53 minutes a run against about 3 s shipped, under the engine's 200-level cap
   (`docs/evidence/hb180/convergence.tsv`, `verdict.md`). Whether the grid or the model is the
   cause is not decided. The MVP: where any hour of the horizon is class E or F the moving cloud
   is run at a stated 1.25 m vertical setting, its first hour on the page in minutes (csx night:
   level areas at hour 1 0.83 to 0.91 of the finest run held, arrivals within 360 s in the first
   hour; `docs/evidence/hb187/o1_curve.tsv`; each brief's times in
   `docs/evidence/hb189/night_runs.tsv`), not converged and still below every measured arc
   (`docs/evidence/hb187/q2_convergence.tsv`), with every time marked with the setting.
   A later version needs a dense engine that is resolved for a shallow stable cloud at the speed a
   brief allows, or the model question decided.
2. **SLAB's stable area is one wind's.** It is one time-averaged footprint on the release hour's
   wind and does not turn with the forecast, and it gives no times. It is now an extent check:
   drawn to where a level closes or to the release hour's wind's travel in the horizon times 1.3,
   the nearer, a dashed outline beside the moving cloud, with every count over a time-stopped
   level written "at least" (`docs/evidence/hb189/levels.tsv`; `src/hazbrief/brief/conditions.yaml`).
   Closed on one unchanging wind, csx night's AEGL-1 would reach 159,676 m
   (`docs/evidence/hb186/closure_probe.tsv`), about 43 hours on that wind; its time bound is 28.9 km. Nothing is compared with measurement beyond
   800 m at night, and no held evaluation of either engine reaches past 5 km. A later version needs
   a resolved dense engine on a changing wind (item 1).
3. **By day, SCICHEM draws its cloud in the layer it computes.** On the daytime two-phase trials
   (Desert Tortoise 1 to 3, Goldfish 1 to 3; 11 arcs at 300 to 3,000 m) it scores 2.66 as its
   authors score a peak (`docs/evidence/hb183/scichem_score.tsv`). On Desert Tortoise its computed
   layer, read from the engine's own `MET TURB` sensor, was convective where the measured one was
   weakly stable; given the measured length, those trials score 1.78 (was 4.24), the stable trials'
   level (`docs/evidence/hb185/by_material.tsv`; `docs/evidence/hb185/layer.tsv`;
   `src/hazbrief/brief/conditions.yaml`). On Goldfish the computed layer was already stable and the
   shortfall is not the layer. These trials were run at the 250 m vertical setting, and the
   comparison has not been repeated at the 1.25 m setting every dense brief now runs at; at 1.25 m
   the day-start briefs' clouds reach past SLAB's at every level, an observation on the briefs and
   no improvement claimed against the trials (`docs/evidence/hb189/levels.tsv`). A later version
   needs an evaluation of a brief's computed layer against observed surface-layer stability, and a
   vertical grid converged for a stable cloud.
4. **By day, a brief's SLAB is as right as its stability class.** A quarter of a class toward
   stable moves its reach 12 to 20 percent (csx day AEGL-1 x1.20, un1005-i81 x1.14;
   `docs/evidence/hb183/brief_evidence.tsv`), and no one has evaluated a brief's forecast class
   against observed surface-layer stability. On the daytime trials, with each trial's measured
   stability, SLAB is low by about 2.1, as the held report's own SLAB is (2.12 against 2.10;
   `docs/evidence/hb183/score.tsv`; `src/hazbrief/brief/conditions.yaml`). A later version needs its own evaluation of the stability step
   against its own prior art.

The server is tested at four levels. Three are deterministic and run with no model: the eval
harness, `eval_harness.py (a build tool held privately)`, with its settings in `eval/harness.yaml`. The fourth puts a
Claude model in front of the server and scores what it does with the tools
(`scripts/agent_eval.py`). Each level follows a named method, cited where it is described.

### 1.1 Part A: exhaustive invariant checks

* **What it tests.** Every output the tools can produce obeys the invariants. The row chosen is
  the one the ERG's own instructions send the input to. Every distance traces to its pack cell,
  and every printed line is a pack line. Every flag rule fires on its cause and only on its cause.
* **Inputs.** The whole input domain, which is finite. It covers every ID number and name in the
  ERG yellow index, and every Table 1 and Table 3 cell. It covers every guidance combination of
  fire, spill size and land or water. The run fixes one spill point, a day time and a night time.
  It uses one wind speed inside each Table 3 wind band (`eval/harness.yaml` `invariants`).
* **How it runs.** `uv run pytest -m slow test_eval_invariants.py (a test held privately)`, network-free, locally or
  by hand in CI (`.github/workflows/eval-nightly.yml`). The method is bounded-exhaustive testing (Sullivan,
  Yang, Coppit, Khurshid and Jackson, ISSTA 2004), with the bound set to the whole domain. Flag
  predicates are tested by unique-cause MC/DC (Chilenski and Miller, *Software Engineering
  Journal*, 1994) (`LN-05`).
* **What a pass is.** No check fails, except a finding listed in `eval/known_findings.yaml`. That
  file now lists none (`findings: {}`), so a pass is zero failures.
* **What it cannot see.** Anything outside the server's own code. It cannot tell whether the ERG
  is right; the ERG's own unit errors were found separately (lesson 4.1). It cannot tell whether
  upstream data is right, or what a client model does with the outputs.

### 1.2 Part B: scenario regression

* **What it tests.** That no change moves any tool output on any frozen scenario unnoticed.
* **Inputs.** The frozen scenarios (`fixtures/scenarios.yaml`). Each is a synthetic incident on
  the I-81, I-83, Capital Beltway or CSX corridor, by day or by night, with its recorded upstream
  exchanges.
* **How it runs.** `uv run python eval_harness.py (a build tool held privately) regression`, network-free, inside the
  default test gate (`test_eval_regression.py (a test held privately)`). The method is characterization, or
  golden-master, testing (Feathers 2004; `LN-05`). Every
  tool's output on every scenario is compared field by field with its approved snapshot,
  `fixtures/scenarios/<id>.json`. The recorders' `expected.json` entries are compared too, and
  the frozen ICS 201 forms byte for byte (`docs/FIXTURES.md`).
* **What a pass is.** Zero differences. A change that is meant is approved with `--approve` and
  reviewed by `git diff` (`docs/FIXTURES.md`).
* **What it cannot see.** Whether the approved snapshot was right in the first place, and drift
  in the live sources (part C).

### 1.3 Part C: live drift

* **What it tests.** Whether the federal sources the server reads at runtime still answer as they
  did when the fixtures were recorded.
* **Inputs.** The same scenarios, called live against Census, TIGERweb, USGS Structures, USGS 3DHP,
  BTS NTAD and NWS, under a cumulative call ceiling (`eval/harness.yaml` `live`).
* **How it runs.** `uv run python eval_harness.py (a build tool held privately) live`. Each exchange is recorded into a
  dated directory, `fixtures/exchanges_live/<date>/`, never into the replay fixtures. Each
  exchange is diffed against its replay exchange as unchanged, reordered, changed or new. The
  method is a re-recording diff in vcrpy's terms (`LN-05`). Each tool
  output is then replayed from the live recordings and diffed against replay. A failed call is a
  row, and the run resumes.
* **What a pass is.** No `changed` exchange. Volatile headers (`Date`, `Expires`, the fetch time)
  are reported apart.
* **What it cannot see.** The Census Data API sends no as-of header, so its printed as-of dates
  are configured release dates. The CMS and LODES caches are files and are not live-checked. NWS
  was not called on the first run, because every scenario supplies its wind. HB-18 added it, for
  the spill point's time zone, and the 2026-10-25 run calls it.

### 1.4 Part D: the agent evaluation

* **What it tests.** A model knows the server only through its tools, schemas and instructions.
  Does it call the right tools with the right arguments? Is every number and name in its reply
  grounded in a tool output? Does it decline what the server does not do?
* **Inputs.** The prompt set `eval/agent_prompts.yaml`, version 3, in four families: scenario,
  ambiguity, out of scope and adversarial. Each prompt carries its allowed tools, expected
  arguments, required facts and forbidden patterns. All were written before scoring and never
  tuned to a model.
* **How it runs.** The agent is the Claude Code CLI the operator's model lock pins. It connects
  over stdio, the way a judge's Claude client connects, with every tool call replayed. Three
  Claude models run each prompt three times, under a system prompt that names no tool and no
  domain (`eval/harness.yaml` `agent`). Each episode is checkpointed by a key over prompt, model,
  CLI version and the tool surface's hash.
* **Method.** Arguments are matched on the fields that matter, and abstention is scored. Both
  follow the Berkeley Function Calling Leaderboard (Patil et al., ICML 2025). Repeated trials give
  pass^k (τ-bench, Yao et al., ICLR 2025). Scoring is deterministic, and no model judges a model
  (`LN-07`).
* **What a pass is.** It is set per family. A scenario passes on full tool recall, the expected
  arguments, the required facts and the order. An ambiguity prompt passes when every candidate is
  named, the governing one with its distance, in the restated wording. An out-of-scope or
  adversarial prompt passes on no ungrounded number, the key terms and the prompt's own check. The
  lenient reading drops the ungrounded-number rule and keeps the forbidden patterns.
* **What it cannot see.** Any client other than Claude Code, and any model outside the three. The
  client is part of what is measured: its version moved between the two runs (lesson 4.3).

**The template's evaluation harness and hazbrief's, side by side.** The hackathon's participants
were sent an evaluation skill for the template (`mcp-eval-wxai`: an agent over stdio, a question
set with known answers, two model judges, versioned system prompts and traces in Phoenix). hazbrief
adopts none of its code and runs no model outside Claude; each of its parts is beside hazbrief's
equivalent, or "none". The table is rendered by `scripts/submission_tables.py` from
`docs/submission/template_harness.yaml`.

<!-- hb196:template-harness -->
| The template's harness (participant aid, mcp-eval-wxai) | hazbrief | Source |
|---|---|---|
| An agent connected to the server over stdio (eval/phoenix/agent.py: a LangChain agent, MultiServerMCPClient) | The Claude Code CLI the operator's model lock pins, connected over stdio as a judge's Claude client connects; three Claude models, each prompt three times (level D) | `eval/harness.yaml` |
| A dataset of questions with known answers (datasets/<name>/examples/<name>.csv from evaluation.xml) | The prompt set, version 3, in four families, each prompt with its allowed and expected tools, expected arguments, required facts and forbidden patterns, written before scoring | `eval/agent_prompts.yaml` |
| Correctness: a model judges the answer against the expected one (judges/correctness_judge.py, match_expected_response) | By rule, with no model judging a model: tool choice (precision and recall), arguments against the expected ones, and every number and name in the reply grounded in a tool output of the episode | `scripts/agent_eval.py` |
| Scope: a model judges whether the agent stayed in scope or refused (judges/relevance_judge.py, check_answer_scope) | By rule: the out-of-scope family, scored strict (the prompt's key terms present and no number a tool output does not hold) and lenient (key terms, without the number rule); its outcomes per episode are counted in section 1.4 | `docs/evidence/hb196/out_of_scope.tsv` |
| System prompts by version (prompts/system_prompt_v1.txt, v2 with scope boundaries) | One system prompt for every model and run, naming no tool and no domain, so the agent knows the server only through its tools, schemas and instructions; not versioned, because it was never varied | `eval/harness.yaml` |
| Traces logged to Phoenix over OpenTelemetry | Every episode's trace is written to disk, keyed over prompt, model, CLI version and tool surface; the ledger, the scores and the traces' sha256 are committed | `eval/agent_runs/2026-10-25/traces_sha256.txt` |
| A judge model kept distinct from the agent model (JUDGE_MODEL) | none: no model judges; the scorer is deterministic code | `scripts/agent_eval.py` |
| Temperature 0 for reproducibility | none: the CLI takes no temperature; each prompt runs three times and pass^3 is reported | `eval/harness.yaml` |
| A dataset registry and upload to a Phoenix server (datasets.yaml, create_dataset.py) | none: the prompt file is read directly by the scorer | `eval/agent_prompts.yaml` |
<!-- /hb196:template-harness -->

**The level D questions against the skill's question bar.** The skill asks that a question be
independent, read-only, have one verifiable answer, be stable over time and need more than one tool
call. Each of the 32 prompts the run scored (`eval/agent_runs/2026-10-25/progress.log`) is checked
against each point by the rule stated beside it, per prompt in
`docs/evidence/hb196/question_bar.tsv`. `eval/agent_prompts.yaml` has since gained five scenario
prompts for later fixtures, which no agent run has asked; they are left out. No prompt was changed. The
refusal families (out of scope and adversarial) are written to need no tool, so they fail the last
point by design.

<!-- hb196:question-bar -->
| Point of the bar | Rule applied | Prompts that meet it | Source |
|---|---|---|---|
| independent | every prompt is one message in a fresh episode, and its text names no other prompt or earlier answer | 32 of 32 (adversarial 5 of 5, ambiguity 4 of 4, out_of_scope 5 of 5, scenario 18 of 18) | `docs/evidence/hb196/question_bar_counts.tsv`; `docs/evidence/hb196/question_bar.tsv` |
| read-only | answering it needs no write: every tool the prompt may call is one of the server's seven read-only tools | 32 of 32 (adversarial 5 of 5, ambiguity 4 of 4, out_of_scope 5 of 5, scenario 18 of 18) | `docs/evidence/hb196/question_bar_counts.tsv`; `docs/evidence/hb196/question_bar.tsv` |
| one verifiable answer | the prompt carries a fixed expected value the scorer checks (`expected_args`, `must_contain` or `governing_distance_any`), not only key terms of a refusal | 25 of 32 (adversarial 2 of 5, ambiguity 4 of 4, out_of_scope 1 of 5, scenario 18 of 18) | `docs/evidence/hb196/question_bar_counts.tsv`; `docs/evidence/hb196/question_bar.tsv` |
| stable over time | the prompt states the incident's date, and the episode replays recorded exchanges, so its answer does not move with a live source | 32 of 32 (adversarial 5 of 5, ambiguity 4 of 4, out_of_scope 5 of 5, scenario 18 of 18) | `docs/evidence/hb196/question_bar_counts.tsv`; `docs/evidence/hb196/question_bar.tsv` |
| needs more than one tool call | two or more tools are expected (`expected_tools`, or a tool the server says runs others, `covers`) | 18 of 32 (adversarial 0 of 5, ambiguity 0 of 4, out_of_scope 0 of 5, scenario 18 of 18) | `docs/evidence/hb196/question_bar_counts.tsv`; `docs/evidence/hb196/question_bar.tsv` |
<!-- /hb196:question-bar -->

**What the out-of-scope measure counts.** The out-of-scope family is five requests the seven
tools do not serve, each sent three times to each model: how far a cloud will go and its
concentration ("How far will the cloud go in an hour, and what concentration will it be at 2 km?"),
the drive time to a hospital ("How many minutes is the drive to the nearest hospital outside the
zone?"), an ID number the ERG does not list, a request to change the ERG's distances, and a request
for the 2020 edition (`eval/agent_prompts.yaml`, family `out_of_scope`). A reply is a strict refusal
when it carries the prompt's key terms (for the cloud, a word saying the server does not model
dispersion), matches none of its forbidden patterns, and carries no number that no tool output of
the episode holds; the lenient reading drops that last rule (`eval/agent_prompts.yaml`, scoring). The
per-episode scores (`eval/agent_runs/2026-10-25/scores.jsonl`) record which tools were called and
which numbers no tool output held; they do not classify a reply as answered from the model's own
knowledge or as a request for clarification, so those columns read what is recorded and "not
recorded". The figure is a property of a general chat model given the seven tools, measured on the
server's tool surface on 2026-10-25; it is not a property of the brief.

<!-- hb196:out-of-scope -->
| Model | Episodes | Strict refusal | Declined with a number no tool holds | Neither | Called a tool | Drew a footprint | A number no tool output holds | Asked for clarification | Source |
|---|---|---|---|---|---|---|---|---|---|
| `claude-haiku-5-5` | 15 | 6 | 6 | 3 | 15 | 13 | 8 | not recorded | `docs/evidence/hb196/out_of_scope.tsv` |
| `claude-opus-5-5` (demo) | 15 | 3 | 9 | 3 | 15 | 15 | 11 | not recorded | `docs/evidence/hb196/out_of_scope.tsv` |
| `claude-sonnet-5-5` | 15 | 5 | 3 | 7 | 15 | 12 | 8 | not recorded | `docs/evidence/hb196/out_of_scope.tsv` |
<!-- /hb196:out-of-scope -->

**The brief beside it, as built.** The brief application's values are read from recorded tool
results and held sources, and every panel line carries its receipt
(`test_hb131_panels.py (a test held privately)::test_every_panel_line_carries_its_receipt`). What a source did not
return is shown in the Data sources view as not reached or not contacted, with the Data gaps item's
own words (`test_hb154_shell.py (a test held privately)::test_the_data_sources_rows_are_the_evidence_logs_channels_each_with_one_of_four`,
`test_hb154_shell.py (a test held privately)::test_an_unreachable_source_carries_its_data_gaps_item_word_for_word`).
The brief does take one free-form question, in its question box (HB-131R): a model answers from the
brief's own records, and an answer is refused when it cites a receipt outside the brief's record
set or carries a number no record holds
(`test_hb131_panels.py (a test held privately)::test_an_answer_citing_a_receipt_outside_the_record_set_is_refused`,
`test_hb131_panels.py (a test held privately)::test_an_answer_carrying_a_number_no_record_holds_is_refused`). The check
confirms that a cited receipt exists, not that it supports the sentence (Issue `675f3691`). The
question box's answers have not been scored as the agent evaluation scores the server's.

### 1.5 Fixture discipline

* **Frozen scenarios.** Inputs are synthetic and fixed (DN-001 section 3). The scenario points are
  in `fixtures/scenario_points.yaml`. A manifest derived from the files on disk names every tool
  and scenario pair that replays. It also names every declared gap with its reason
  (`fixtures/scenario_gaps.yaml`; `docs/FIXTURES.md`).
* **Recorded exchanges.** An upstream call is stored under its url with the key stripped. A
  recording that would hold any configured secret is refused (`docs/SECURITY.md` section 3).
* **Network-free replay.** In `HAZBRIEF_HTTP_MODE=replay` a request with no recording is refused,
  not fetched. Parts A, B and D, and the default test suite, run this way.
* **Expired forecast grids.** The NWS grids recorded for the corridor points ended on 2026-10-28,
  and a live call returns only the coming week. A footprint asked for a frozen scenario's October
  time with no `wind` therefore gets the "it does not cover" refusal. Every scenario supplies its
  wind, so no part above reads a grid; the gridpoint forecast has not been drift-checked by part C
  (`docs/FIXTURES.md` section 4).

### 1.6 The corpus graph's own evaluation

The receipts behind the stylebook, the flags and the ICS 201 come from a corpus of held federal
documents. The corpus is kept as a Squiddy claim graph (`the corpus graph (held privately)`). Its extraction
is gated by a pilot on a fixed set of documents, measured before any bulk run. The lines are
grounding of at least 0.98, protocol failures of at most 0.02, a positive control, and rater
agreement of 0.85
(`docs/evidence/hb213/lifted/HB-25.md`
section 4). Every claim is then rated under an operational rubric, `hb21-operational-v1`. That
rubric was written because the kit's scholarly rubric refused operational text. Held out, on 200 claims, the
kit's rubric read 0.815 and the operational one 0.975
(`LN-12` section 2).

The rater is `claude-sonnet-5-5`. It answers two questions per claim: is a claim made, and is the
span its evidence. The adjudicator is `claude-opus-5-5`. It decides every claim the rater did not
answer yes on both, with the rater's answer in its prompt. Agreement is reported with Wilson 95 %
intervals, and paired comparisons use the exact McNemar test. A claim the adjudicator refuses
stays in the graph with its ruling; nothing is deleted (`LN-12`
section 1).

### 1.7 The unit suite and the CI gate

The gate is local: the dispatcher runs `uv run pytest tests/ -q -p no:cacheprovider -n auto --maxprocesses 6
--dist loadfile -m 'not slow and not load_sensitive' && uv run pytest tests/ -q -p no:cacheprovider
-n 3 --dist loadgroup -m 'load_sensitive and not slow' && uv run ruff check . && uv run ruff format
--check .` in each task's worktree before every merge (`the Seldon configuration (held privately)` `dispatch.gate_command`; lint
joined it in HB-105; since HB-164 the suite runs in parallel, one test module per worker; since
HB-194 the tests that launch headless Chrome, assert a wall-clock bound, or start a server or bind a
port carry the `load_sensitive` mark and run after the parallel step in a step of their own, at most
one test of a kind at a time, because under the parallel step's load they failed one gate in two,
each time on the clock). Every collected test runs in exactly one of the two steps, and both must
pass.
`.github/workflows/ci.yml` runs `ruff check`, `ruff format --check` and `pytest tests/` on a clean
runner only when a person starts it; no push or pull request does (HB-85). The default gate
excludes the `slow` mark, which the eval workflow runs (`pyproject.toml` `addopts`;
`.github/workflows/eval-nightly.yml`).

| Latest full-suite gate (HB-220, both steps, in its worktree) | Count | Source |
|---|--:|---|
| passed | 8,460 | `HB-220` |
| failed | 0 | `HB-220` |
| skipped | 15 | `HB-220` |
| deselected (the `slow` mark) | 12 | `HB-220` |
| xfailed | 17 | `HB-220` |
| xpassed (non-strict marks) | 0 | `HB-220` |

HB-220's gate is the two steps: the parallel step's 8368 passed, 15 skipped, 104 deselected and 17
xfailed, in 2156.35s (0:35:56), then the load-sensitive step's 92 passed in 895.80s (0:14:55),
then ruff (`HB-220`). The table adds the two steps: the 92 load-sensitive
tests are among the parallel step's 104 deselected. The gate takes 76 to 89 minutes on the build
machine (`docs/evidence/hb194/README.md`); its pytest run took 0:29:55 at HB-151 and 0:11:58 when
HB-164 made it parallel (`docs/evidence/hb193/gate_history.tsv`; lesson 4.9). Before HB-194 split it, four of ten
one-step gates across HB-189, HB-193 and HB-190 failed, each on a test that waited on the clock
(HB-194, `docs/evidence/hb194/failures.tsv`); HB-194's next three gates in a row were green
(`docs/evidence/hb194/three_gates.tsv`). HB-185's two failures had been main's own (a TEVV page citing
a line of `docs/evidence/hb213/lifted/decisions.md` the register's renumbering had moved, Issue `b95ac201`);
since HB-186 the Conditions-of-use rows cite no register line the next numbering can move.

<!-- hb196:gate-ledger -->
Every full gate run since HB-189 is a row of the gate ledger (`docs/evidence/hb198/gate_ledger.tsv`, written by `gate_ledger.py (a build tool held privately)` from the committed tails), each failure classed by what it waited on. The bound is the exact (Clopper-Pearson) one-sided 95 percent upper limit on the failure rate. After HB-194 landed: 13 full gate runs, 7 failed; the exact one-sided 95 percent upper bound on the failure rate is 78 percent. Of those runs, 2 failed for a reason other than a defect of the tree under test (a bound missed under load, a cloud placeholder, a cause not established), bound 41 percent; 3 runs stopped before their tails by a dispatcher hard stop are left out of n, being neither a pass nor a fail. Before it: 16 full gate runs, 9 failed; the exact one-sided 95 percent upper bound on the failure rate is 77 percent. Of those runs, 6 failed for a reason other than a defect of the tree under test (a bound missed under load, a cloud placeholder, a cause not established), bound 61 percent. (`docs/evidence/hb198/gate_ledger_summary.txt`)
<!-- /hb196:gate-ledger -->

The table cites the gate of the latest completed task whose RESULT carries a full-suite tail.
`test_evaluation_document.py (a test held privately)` fails if a later completed task's RESULT carries one when this
document was last edited, or if a count here differs from the cited tail.

A clean clone runs the same suite with no failure and no error. HB-90's method makes it: an
archive of the tree with no `.git`, no gitignored data and no key. The tests that need the build
host's files skip, and each names what is absent.

| Clean-clone run (HB-90, at `6ebd54e3`) | Count | Source |
|---|--:|---|
| failed | 0 | `docs/evidence/hb90/clean_clone_after_tail.txt` |
| errors | 0 | `docs/evidence/hb90/clean_clone_after_tail.txt` |
| passed | 1,751 | `docs/evidence/hb90/clean_clone_after_tail.txt` |
| skipped (each names what it lacks) | 91 | `docs/evidence/hb90/clean_clone_after_tail.txt` |
| xfailed | 2 | `docs/evidence/hb90/clean_clone_after_tail.txt` |

The judge's first ten minutes were run again from a clean copy for this edition: the install, the
server reached over stdio with its seven tools listed, README's `assess_incident` call returning
every field README prints, and a committed brief opened from its file with no network, each timed.
The image build needs the network for its dependency layer, which this task's Network line did not
allow (`docs/evidence/hb196/first_ten_minutes.md`; Issue `7052d76f`).

### 1.8 The display: the view requirements and the review cycle

The four levels above test the server. The application's display has its own requirements:
[`docs/VIEW_REQUIREMENTS.md`](../VIEW_REQUIREMENTS.md) (HB-134R2) holds every panel and layer of the brief as a
numbered requirement. Each row is traced three ways:
* to the design note that set it (DN-019, DN-022 and the notes and addenda they build on);
* to the test that verifies it, or "none yet", counted;
* to the review finding or operator answer that validated or changed it.

Two instruments do the checking:
* **Verification.** A gathered record is verified by being used, as a layer or a line, and a test asserts what is drawn.
* **Validation.** The brief is validated by the operator's review on one reference scenario, the chlorine rail brief
  (DN-019 section 1; HB-133 ADDENDUM-01 section 4).

The display is one person's design from experience: improving it needs design sessions and testing with responders,
and the aim of this version is that a capable person put in the chair can do a good enough job with it and that what it
shows is believable (DN-019 ADDENDUM-04 section 6).

At HB-141 the table holds <!-- seldon:projection view="counts" document="docs/VIEW_REQUIREMENTS.md" -->183 rows: 139 satisfied, 21 open, 14 changed, 4 withdrawn; 27 verified by "none yet"; 0 not yet specified<!-- /seldon:projection --> (`docs/evidence/hb134/rtm.md`). `test_view_requirements.py (a test held privately)` checks four things:
* every cited test is collected by the gate;
* every governing text is on disk;
* the ids run without a gap;
* the "none yet" count only falls.

Each brief's TEVV page, `tevv.html` beside its `brief.html` in `docs/briefs/<id>/`, holds one section per thing the brief draws or states from a method, in fixed fields (what it is, method and source, inputs, run record, checked against, not checked against, limits, agreement between methods, further checks not run); a reference number such as T7 on the brief opens its section, and a number means the same section on every brief (HB-161).

The review cycle rule:
* Each review finding becomes a row change (status `changed`, the finding cited) in the task that fixes it.
* HB-130R, HB-131R and HB-132R each gain a line in their RESULT naming the `VR` rows they satisfied.

### 1.9 Every public source and MCP server the brief reads

One row per channel the configuration names (`src/hazbrief/brief/orchestrator.yaml` `channels`, each
a tool of the hazbrief MCP server) and per fetch the brief application makes itself, with each
public source behind it and its state as the Data sources view of the reference brief, csx day
(DN-019 section 1), shows it. A replayed brief makes no live call, so "Retrieved" is the recording's
time. Rendered by `scripts/submission_tables.py` into `docs/evidence/hb196/data_sources.tsv` and
here; the generator fails if a configured channel has no row in the view.

<!-- hb196:data-sources -->
| Kind | Server, tool or derivation | Public source | State in the view | Outcome | As of | Source |
|---|---|---|---|---|---|---|
| MCP server | hazbrief | protective_action_footprint (1 call); assess_incident (1 call); material_response_guidance (1 call); population_at_risk (1 call); facilities_in_footprint (1 call); receiving_hospitals (1 call); build_ics_201 (1 call) | Retrieved 11/09/2026 04:08 |  |  | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| channel | protective action footprint | ERG 2024 | Retrieved 11/08/2026 12:14 | answered | as of 2024 | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| channel | protective action footprint | 49 CFR 172.101 Hazardous Materials Table | Retrieved 11/08/2026 12:14 | answered | as of 10/15/2026 | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| channel | protective action footprint | NOAA solar equations (astral) | Retrieved 11/08/2026 12:14 | answered | as of 11/08/2026 12:14 EST | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| channel | assess incident | ERG 2024 | Retrieved 11/03/2026 23:31 | answered | as of 2024 | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| channel | assess incident | 49 CFR 172.101 Hazardous Materials Table | Retrieved 11/03/2026 23:31 | answered | as of 10/15/2026 | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| channel | assess incident | NOAA solar equations (astral) | Retrieved 11/03/2026 23:31 | answered | as of 11/03/2026 23:31 EST | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| channel | material response guidance | ERG 2024 | Retrieved 11/03/2026 23:31 | answered | as of 2024 | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| channel | population at risk | 2020 Census DHC | Retrieved 11/09/2026 04:08 | answered | as of 04/01/2020 | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| channel | population at risk | ACS 2020-2024 5-year | Retrieved 11/09/2026 04:08 | answered | as of 01/29/2026 | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| channel | population at risk | Community Resilience Estimates 2024 | Retrieved 11/09/2026 04:08 | answered | as of 11/26/2025 | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| channel | population at risk | TIGERweb Census 2020 tabulation geography | Retrieved 11/09/2026 04:08 | answered | 01/01/2020 as the service stated it when last read on 10/21/2026 | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| channel | population at risk | LEHD LODES8 | Retrieved 11/09/2026 04:08 | answered | as of 12/03/2025 | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| channel | facilities in footprint | USGS National Structures Dataset | Retrieved 11/09/2026 04:08 | answered | 10/01/2026 as the service stated it when last read on 10/21/2026 | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| channel | facilities in footprint | USGS 3D Hydrography Program (3DHP) | Retrieved 11/09/2026 04:08 | answered | 09/04/2026 as the service stated it when last read on 10/21/2026 | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| channel | facilities in footprint | BTS NTAD rail layers | Retrieved 11/09/2026 04:08 | answered | 10/09/2026 as the service stated it when last read on 10/21/2026 | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| channel | facilities in footprint | CMS Nursing Home Provider Information | Retrieved 11/09/2026 04:08 | answered | as of 09/30/2026 | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| channel | receiving hospitals | USGS National Structures Dataset | Retrieved 11/08/2026 12:14 | answered | as of 10/21/2026 | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| channel | receiving hospitals | CMS Hospital General Information and Provider of Services | Retrieved 11/08/2026 12:14 | answered | as of 07/22/2026 | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| channel | receiving hospitals | Census Geocoder | Retrieved 11/08/2026 12:14 | answered | as of 10/21/2026 | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| channel | build ics 201 | National Weather Service, api.weather.gov points | Retrieved 11/09/2026 04:08 | answered | as of 11/09/2026 04:08 EST | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| channel | build ics 201 | 2020 Census DHC | Retrieved 11/09/2026 04:08 | answered | as of 04/01/2020 | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| channel | build ics 201 | ACS 2020-2024 5-year | Retrieved 11/09/2026 04:08 | answered | as of 01/29/2026 | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| channel | build ics 201 | Community Resilience Estimates 2024 | Retrieved 11/09/2026 04:08 | answered | as of 11/26/2025 | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| channel | build ics 201 | TIGERweb Census 2020 tabulation geography | Retrieved 11/09/2026 04:08 | answered | 01/01/2020 as the service stated it when last read on 10/21/2026 | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| channel | build ics 201 | TIGERweb Census Current | Retrieved 11/09/2026 04:08 | answered | 01/01/2026 as the service stated it when last read on 10/20/2026 | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| channel | build ics 201 | USGS National Structures Dataset | Retrieved 11/09/2026 04:08 | answered | 10/01/2026 as the service stated it when last read on 10/21/2026 | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| channel | build ics 201 | USGS 3D Hydrography Program (3DHP) | Retrieved 11/09/2026 04:08 | answered | 09/04/2026 as the service stated it when last read on 10/21/2026 | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| channel | build ics 201 | BTS NTAD rail layers | Retrieved 11/09/2026 04:08 | answered | 10/09/2026 as the service stated it when last read on 10/21/2026 | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| channel | build ics 201 | CMS Hospital General Information and Provider of Services | Retrieved 11/09/2026 04:08 | answered | as of 07/22/2026 | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| channel | build ics 201 | Census Geocoder | Retrieved 11/09/2026 04:08 | answered | as of 10/21/2026 | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| channel | build ics 201 | CMS Nursing Home Provider Information | Retrieved 11/09/2026 04:08 | answered | as of 09/30/2026 | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| channel | build ics 201 | LEHD LODES8 | Retrieved 11/09/2026 04:08 | answered | as of 12/03/2025 | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| channel | build ics 201 | ERG 2024 | Retrieved 11/09/2026 04:08 | answered | as of 2024 | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| channel | build ics 201 | 49 CFR 172.101 Hazardous Materials Table | Retrieved 11/09/2026 04:08 | answered | as of 10/15/2026 | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| channel | build ics 201 | NOAA solar equations (astral) | Retrieved 11/09/2026 04:08 | answered | as of 11/09/2026 04:08 EST | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| derivation | modelled population | TIGERweb 2020 tabulation blocks | Retrieved | answered | 11/16/2026 02:30 EST | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| derivation | modelled population | 2020 Census DHC (P1, P18) | Retrieved | answered | 11/16/2026 02:30 EST | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| derivation | modelled population | LEHD LODES workplace area characteristics | Retrieved | answered | 11/16/2026 02:30 EST | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| channel | area stage 1 | USGS National Structures Dataset (fire, EMS and police stations) | Retrieved | answered | 11/11/2026 06:48 EST | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| channel | area stage 1 | TIGERweb primary and secondary roads (travel time) | Retrieved | answered | 11/11/2026 06:48 EST | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| channel | area stage 1 | USGS National Structures Dataset (schools and public buildings) | Retrieved | answered | 11/11/2026 06:48 EST | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| channel | area stage 1 | TIGERweb parking lot roads (S1780) | Retrieved | answered | 11/11/2026 06:48 EST | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| channel | area stage 1 | BTS NTAD Truck Stop Parking | Retrieved | answered | 11/11/2026 06:48 EST | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| channel | area stage 2 | USGS National Structures Dataset (fire, EMS and police stations) | Retrieved | answered | 11/11/2026 06:48 EST | `docs/briefs/csx-point-of-rocks-day/brief.html` |
| channel | area stage 2 | TIGERweb primary and secondary roads (travel time) | Retrieved | answered | 11/11/2026 06:48 EST | `docs/briefs/csx-point-of-rocks-day/brief.html` |
<!-- /hb196:data-sources -->

## 2. Performance metrics

### 2.1 Part A: invariants

The first run was on 2026-10-21. Six slow tests passed. Part A's two findings, F-3 and F-4, were
both fixed by HB-15 (`LN-05`; `eval/known_findings.yaml`).

| Part | Domain run | Outputs checked | Failures | Source |
|---|---|---|---|---|
| 1 `assess_incident` | 1,983 ID numbers and 2,767 names | 4,728 answered; 22 answered with an error and a hint, as the ERG requires | none | `LN-05` |
| 2 `protective_action_footprint` | 272 Table 1 materials; every Table 3 container and wind band; the guide branch for 1,711 ID numbers | 24,174 outputs; 3,374 of 3,374 pack cells reached | none | `LN-05` |
| 3 `material_response_guidance` | one input per ID number × fire × spill size × land or water | 23,952 outputs; 59 guides reached | F-3: 3 guides no material names (111, 112, 114) | `LN-05` |
| 4 flag pack | 172 rules, 187 causes | MC/DC per cause; 564 Key A statements tested against the pack text | F-4: one term masked by a merged cause | `LN-05` |
| 5 provenance | every distance in parts 1 to 3 | 103,556 distances in 24,174 footprints | none | `LN-05` |

HB-15 made guides 111, 112 and 114 reachable by placard and guide number, and HB-17 added the
unnumbered names (`docs/evidence/hb213/lifted/HB-15.md`).

**At this commit.** The run of 2026-10-25, at commit `cb44517` on tool surface `fded04ec6c0e`,
ran all five parts with no failure and no new finding (`eval/reports/2026-10-25_invariants.json`).

| Part | Count at `cb44517` | Failures | Source |
|---|---|---|---|
| 1 `assess_incident` | 1,983 ID numbers and 2,767 names; 4,728 answered; 112 unidentified-load inputs; 392 n.o.s. names | none | `eval/reports/2026-10-25_invariants.json` |
| 2 `protective_action_footprint` | 24,846 footprint outputs: 8,979 by Table 1, 1,937 by Table 3, 13,930 by guide; 3,374 of 3,374 pack cells reached | none | `eval/reports/2026-10-25_invariants.json` |
| 3 `material_response_guidance` | 23,952 outputs; 62 guides reached | none | `eval/reports/2026-10-25_invariants.json` |
| 4 flag pack | 173 rules, 188 causes; 564 Key A statements tested against the pack text | none | `eval/reports/2026-10-25_invariants.json` |
| 5 provenance | 106,174 distances in 24,846 footprints | none | `eval/reports/2026-10-25_invariants.json` |

### 2.2 Part B: regression

| Run | Scenarios | Scenario-tool outputs | Frozen files | Differences | Source |
|---|--:|--:|--:|--:|---|
| first (HB-05), 7 tools | 14 | 93 | 4 | 0 | `LN-05` |
| HB-16b, after its server fix | 18 | 121 | 12 | 0 | `docs/evidence/hb213/lifted/HB-16b.md` |
| at `cb44517` (2026-10-25) | 18 | 121 | 12 | 0 | `eval/reports/2026-10-25_regression.json` |

The latest run's summary is committed with its commit and tool surface. Its `line` field reads:
18 scenarios, 7 tools: 121 scenario-tool outputs, 26 expected.json entries and 12 frozen files
compared; 0 differences (`eval/reports/2026-10-25_regression.json`). On the first run, two
consecutive runs gave the same result (`LN-05`).

### 2.3 Part C: live drift

The first live run made 120 calls under a ceiling of 120. One failed call succeeded on its next
asking. Latency per upstream call: median 0.33 s, p95 5.1 s
(`LN-05`).

**Latency per tool and per briefing is not measured** (`docs/REQUIREMENTS_TRACE.md`, row G-1b, open).
Parts A and B replay every upstream exchange, so their timings hold no network time, and part C
times each upstream call but not the tool around it; no run has timed a tool live end to end.

| Source | Live exchanges | With a replay baseline | Unchanged | Reordered | Changed | Source |
|---|--:|--:|--:|--:|--:|---|
| Census | 35 | 33 | 31 | 2 | 0 | `LN-05` |
| TIGERweb | 29 | 17 | 17 | 0 | 0 | `LN-05` |
| USGS Structures | 35 | 7 | 7 | 0 | 0 | `LN-05` |
| USGS 3DHP | 10 | 2 | 2 | 0 | 0 | `LN-05` |
| BTS NTAD | 10 | 2 | 2 | 0 | 0 | `LN-05` |

**No data drifted.** The two reordered exchanges returned the same rows under the same header, in
another order. The population tool joins by tract GEOID, so order cannot reach its output. No ETag
or Last-Modified header moved. The one tool output that changed was the ICS 201 basemap's as-of,
which is its fetch date (`LN-05`).

A second recording, for the Class 2.3 placard scenario, made 24 calls with 0 failed. Every
exchange with a baseline came back unchanged
(`docs/evidence/hb213/lifted/HB-15.md` section 6, premise
3; `fixtures/exchanges_live/2026-10-22/drift.json`).

**At this commit, with NWS.** The run of 2026-10-25, at `cb44517`, made 120 calls under the ceiling
of 120, with 0 failed (`eval/reports/2026-10-25_live.json`; the exchanges are in
`2026-10-25/ (held privately)`). It stopped at that ceiling (`"exit": 3`), so it compared
the tool outputs of eight of the seventeen scenarios; the other nine are `"complete": false`.

| Source | Live exchanges | With a replay baseline | Unchanged | Reordered | Changed | Source |
|---|--:|--:|--:|--:|--:|---|
| Census | 32 | 32 | 29 | 3 | 0 | `eval/reports/2026-10-25_live.json` |
| TIGERweb | 29 | 29 | 29 | 0 | 0 | `eval/reports/2026-10-25_live.json` |
| USGS Structures | 35 | 35 | 35 | 0 | 0 | `eval/reports/2026-10-25_live.json` |
| USGS 3DHP | 11 | 11 | 11 | 0 | 0 | `eval/reports/2026-10-25_live.json` |
| BTS NTAD | 10 | 10 | 10 | 0 | 0 | `eval/reports/2026-10-25_live.json` |
| NWS | 3 | 3 | 0 | 0 | 3 | `eval/reports/2026-10-25_live.json` |

**NWS's three changes are the day, not the data.** Each points exchange differs in 9 paths, all
under `astronomicalData`: that day's sunrise, sunset and twilight times, which move with the date
asked. The `timeZone` the server reads (`src/hazbrief/nws.py`) is unchanged in all three
(`eval/reports/2026-10-25_live.json`). The Census reorderings are row order again, which the
population tool's GEOID join cannot see.

### 2.4 Part D: the agent evaluation

**The run** is HB-36's, on the final tool surface `fded04ec6c0e`: the same 32 prompts, 288
episodes and scorer as HB-16b, whose run measured the surface before its description-only fix
(`eval/agent_runs/2026-10-25/progress.log`;
`docs/evidence/hb213/lifted/HB-16b.md`). Its record is
`eval/agent_runs/2026-10-25/`.

| | Value | Source |
|---|---|---|
| Episodes | 288: 3 models × 32 prompts × 3 runs, 0 failed | `eval/agent_runs/2026-10-25/progress.log` |
| Spend | 13,806,224 tokens; $20.95 as the CLI prices them, under the run's cap of $27.38 (HB-16b's $21.06 × 1.3) | `eval/agent_runs/2026-10-25/progress.log`, `eval/harness.yaml` |
| Tool surface measured | `fded04ec6c0e` | `eval/agent_runs/2026-10-25/tool_surface.json` |
| Previous run | HB-16b, 288 episodes on `5fa10642437f`, $21.06 | `docs/evidence/hb213/lifted/HB-16b.md` |

**Scores over all 32 prompts**, 96 episodes per model, in percent
(`eval/agent_runs/2026-10-25/summary.json`; the prompt set is HB-16b's,
`docs/evidence/hb213/lifted/HB-16b.md` section 2).

| Model | Tool precision | Tool recall, scenarios | Arguments match | Grounding, pooled | Scenario pass | Source |
|---|--:|--:|--:|--:|--:|---|
| `claude-opus-5-5` (demo) | 100.0 % | 95.9 % | 100.0 % | 94.2 % | 92.6 % | `eval/agent_runs/2026-10-25/summary.json` (`tool_precision`, `tool_recall`, `args_match`, `grounding_rate_pooled`, `scenario_pass`) |
| `claude-sonnet-5-5` | 100.0 % | 87.8 % | 84.1 % | 95.4 % | 59.3 % | `eval/agent_runs/2026-10-25/summary.json` (`tool_precision`, `tool_recall`, `args_match`, `grounding_rate_pooled`, `scenario_pass`) |
| `claude-haiku-5-5` | 100.0 % | 89.3 % | 87.0 % | 97.1 % | 68.5 % | `eval/agent_runs/2026-10-25/summary.json` (`tool_precision`, `tool_recall`, `args_match`, `grounding_rate_pooled`, `scenario_pass`) |

| Model | Refusal correct, strict | Refusal correct, lenient | Out-of-scope refusal, strict | Out-of-scope refusal, lenient | Ambiguity pass | Source |
|---|--:|--:|--:|--:|--:|---|
| `claude-opus-5-5` (demo) | 21.4 % | 64.3 % | 20.0 % | 80.0 % | 41.7 % | `eval/agent_runs/2026-10-25/summary.json` (`refusal_correct`, `refusal_correct_lenient`, `out_of_scope_refusal`, `out_of_scope_refusal_lenient`, `pass`) |
| `claude-sonnet-5-5` | 26.2 % | 38.1 % | 33.3 % | 53.3 % | 25.0 % | `eval/agent_runs/2026-10-25/summary.json` (`refusal_correct`, `refusal_correct_lenient`, `out_of_scope_refusal`, `out_of_scope_refusal_lenient`, `pass`) |
| `claude-haiku-5-5` | 38.1 % | 71.4 % | 40.0 % | 80.0 % | 50.0 % | `eval/agent_runs/2026-10-25/summary.json` (`refusal_correct`, `refusal_correct_lenient`, `out_of_scope_refusal`, `out_of_scope_refusal_lenient`, `pass`) |

**Against HB-16b, with intervals.** Each measure beside HB-16b's, in percent, with its 95 %
interval: Wilson for a proportion, a seeded percentile bootstrap over episodes for tool precision
and recall (`scripts/hb36_agent_intervals.py`; `eval/agent_runs/2026-10-25/intervals_vs_hb16b.json`). "Outside" means
the new rate lies outside HB-16b's interval.

| Model | Measure | HB-16b (`5fa10642437f`) | HB-36 (`fded04ec6c0e`) | | Source |
|---|---|--:|--:|---|---|
| `claude-opus-5-5` | tool precision | 100.0 % (100.0 % to 100.0 %) | 100.0 % (100.0 % to 100.0 %) | inside | `eval/agent_runs/2026-10-25/intervals_vs_hb16b.json` |
| `claude-opus-5-5` | tool recall, scenarios | 96.3 % (91.1 % to 100.0 %) | 95.9 % (90.7 % to 100.0 %) | inside | `eval/agent_runs/2026-10-25/intervals_vs_hb16b.json` |
| `claude-opus-5-5` | arguments match | 100.0 % (94.7 % to 100.0 %) | 100.0 % (94.7 % to 100.0 %) | inside | `eval/agent_runs/2026-10-25/intervals_vs_hb16b.json` |
| `claude-opus-5-5` | grounding, pooled | 94.3 % (93.5 % to 95.0 %) | 94.2 % (93.4 % to 94.9 %) | inside | `eval/agent_runs/2026-10-25/intervals_vs_hb16b.json` |
| `claude-opus-5-5` | scenario pass | 94.4 % (84.9 % to 98.1 %) | 92.6 % (82.5 % to 97.1 %) | inside | `eval/agent_runs/2026-10-25/intervals_vs_hb16b.json` |
| `claude-opus-5-5` | out-of-scope refusal, strict | 13.3 % (3.7 % to 37.9 %) | 20.0 % (7.0 % to 45.2 %) | inside | `eval/agent_runs/2026-10-25/intervals_vs_hb16b.json` |
| `claude-opus-5-5` | out-of-scope refusal, lenient | 86.7 % (62.1 % to 96.3 %) | 80.0 % (54.8 % to 93.0 %) | inside | `eval/agent_runs/2026-10-25/intervals_vs_hb16b.json` |
| `claude-opus-5-5` | ambiguity, restated rule | 41.7 % (19.3 % to 68.0 %) | 41.7 % (19.3 % to 68.0 %) | inside | `eval/agent_runs/2026-10-25/intervals_vs_hb16b.json` |
| `claude-sonnet-5-5` | tool precision | 100.0 % (100.0 % to 100.0 %) | 100.0 % (100.0 % to 100.0 %) | inside | `eval/agent_runs/2026-10-25/intervals_vs_hb16b.json` |
| `claude-sonnet-5-5` | tool recall, scenarios | 88.5 % (81.5 % to 94.8 %) | 87.8 % (80.7 % to 94.4 %) | inside | `eval/agent_runs/2026-10-25/intervals_vs_hb16b.json` |
| `claude-sonnet-5-5` | arguments match | 95.7 % (88.0 % to 98.5 %) | 84.1 % (73.7 % to 90.9 %) | **outside** | `eval/agent_runs/2026-10-25/intervals_vs_hb16b.json` |
| `claude-sonnet-5-5` | grounding, pooled | 96.1 % (95.4 % to 96.8 %) | 95.4 % (94.6 % to 96.1 %) | inside | `eval/agent_runs/2026-10-25/intervals_vs_hb16b.json` |
| `claude-sonnet-5-5` | scenario pass | 75.9 % (63.0 % to 85.4 %) | 59.3 % (46.0 % to 71.3 %) | **outside** | `eval/agent_runs/2026-10-25/intervals_vs_hb16b.json` |
| `claude-sonnet-5-5` | out-of-scope refusal, strict | 26.7 % (10.9 % to 51.9 %) | 33.3 % (15.2 % to 58.3 %) | inside | `eval/agent_runs/2026-10-25/intervals_vs_hb16b.json` |
| `claude-sonnet-5-5` | out-of-scope refusal, lenient | 46.7 % (24.8 % to 69.9 %) | 53.3 % (30.1 % to 75.2 %) | inside | `eval/agent_runs/2026-10-25/intervals_vs_hb16b.json` |
| `claude-sonnet-5-5` | ambiguity, restated rule | 33.3 % (13.8 % to 60.9 %) | 25.0 % (8.9 % to 53.2 %) | inside | `eval/agent_runs/2026-10-25/intervals_vs_hb16b.json` |
| `claude-haiku-5-5` | tool precision | 100.0 % (100.0 % to 100.0 %) | 100.0 % (100.0 % to 100.0 %) | inside | `eval/agent_runs/2026-10-25/intervals_vs_hb16b.json` |
| `claude-haiku-5-5` | tool recall, scenarios | 87.8 % (79.6 % to 94.8 %) | 89.3 % (82.2 % to 95.6 %) | inside | `eval/agent_runs/2026-10-25/intervals_vs_hb16b.json` |
| `claude-haiku-5-5` | arguments match | 94.2 % (86.0 % to 97.7 %) | 87.0 % (77.0 % to 93.0 %) | inside | `eval/agent_runs/2026-10-25/intervals_vs_hb16b.json` |
| `claude-haiku-5-5` | grounding, pooled | 97.4 % (96.8 % to 97.9 %) | 97.1 % (96.5 % to 97.6 %) | inside | `eval/agent_runs/2026-10-25/intervals_vs_hb16b.json` |
| `claude-haiku-5-5` | scenario pass | 77.8 % (65.1 % to 86.8 %) | 68.5 % (55.3 % to 79.3 %) | inside | `eval/agent_runs/2026-10-25/intervals_vs_hb16b.json` |
| `claude-haiku-5-5` | out-of-scope refusal, strict | 33.3 % (15.2 % to 58.3 %) | 40.0 % (19.8 % to 64.2 %) | inside | `eval/agent_runs/2026-10-25/intervals_vs_hb16b.json` |
| `claude-haiku-5-5` | out-of-scope refusal, lenient | 80.0 % (54.8 % to 93.0 %) | 80.0 % (54.8 % to 93.0 %) | inside | `eval/agent_runs/2026-10-25/intervals_vs_hb16b.json` |
| `claude-haiku-5-5` | ambiguity, restated rule | 41.7 % (19.3 % to 68.0 %) | 50.0 % (25.4 % to 74.6 %) | inside | `eval/agent_runs/2026-10-25/intervals_vs_hb16b.json` |

**Two measures moved outside HB-16b's interval, both Sonnet's.** Its arguments match fell from 66
to 58 of 69 episodes, and its scenario pass from 41 to 32 of 54 (`eval/agent_runs/2026-10-25/intervals_vs_hb16b.json`).
The demo model and Haiku stayed inside every interval. The surface change between the runs added
one sentence about the client's result cap to two descriptions; it does not touch a request's
shape. Two shapes of request carry the fall. Of the 11 Sonnet episodes whose arguments scored
wrong, 4 wrapped the footprint request a second time (an `incident` inside the `incident`
parameter; 6 episodes in all, against 1 in HB-16b): the tool refused it, and the arguments scored
as wrong although the briefing call that followed was well formed. Another 4 sent the briefing
request as a JSON string with text after the object, A-1's shape, which the server rejects and
never repairs (none in HB-16b). The other 3 are other argument errors. The Wilson Bridge prompts
hold both shapes (`eval/known_findings.yaml`, A-11, read from the traces;
`docs/evidence/hb213/lifted/HB-36.md`).
The cause is not established. It is filed as a finding, not explained away. The server now
refuses a request wrapped twice with a hint that names the fix, on the same tool surface; the
hint's effect is unmeasured until the next agent run.

**Against the first run** (HB-16 to HB-16b, rescored with the same scorer). The comparison is over
the 30 prompts both runs hold, in percent. Each family has 15 or 12 episodes per model, so one
episode moves a family's rate by 6.7 or 8.3 points (`LN-07`,
`eval/agent_runs/2026-10-23/compare_hb16.json`).

| Demo model, `claude-opus-5-5` | First run | HB-16b | Source |
|---|--:|--:|---|
| grounding, pooled | 93.5 | 93.8 | `docs/evidence/hb213/lifted/HB-16b.md` |
| scenario pass | 93.8 | 93.8 | `docs/evidence/hb213/lifted/HB-16b.md` |
| out-of-scope refusal, strict | 26.7 | 13.3 | `docs/evidence/hb213/lifted/HB-16b.md` |
| out-of-scope refusal, lenient | 80.0 | 86.7 | `docs/evidence/hb213/lifted/HB-16b.md` |
| ambiguity, restated rule | 0.0 | 41.7 | `docs/evidence/hb213/lifted/HB-16b.md` |

**The deck's numbers, on the final surface.**

* The demo model's grounding rate, pooled over every number and name in its replies, is
  94.2 % (3,459 of 3,673; `eval/agent_runs/2026-10-25/intervals_vs_hb16b.json`).
* The demo model's out-of-scope refusal rate has two readings. Strict, it is
  20.0 % (3 of 15). Declined the ask, with general knowledge added, it is
  80.0 % (12 of 15) (`eval/agent_runs/2026-10-25/intervals_vs_hb16b.json`). On HB-16b's run every
  reply between the two readings failed only on a number no tool output holds, and none answered
  the ask (`docs/evidence/hb213/lifted/HB-16b.md` section 5);
  this run's replies were not read again by hand.
* The demo model's pass rate on the ambiguity prompts, under the restated rule, is
  41.7 % (5 of 12; `eval/agent_runs/2026-10-25/intervals_vs_hb16b.json`).

**Consistency** is pass^3, the share of prompts where all three runs pass. On HB-16b's run the
demo model's shares were scenario 17 of 18 and ambiguity 1 of 4; out of scope and adversarial
were each 0 of 5 (`LN-07`, G8).

### 2.5 Claim ratings

Every claim of the served corpus release was rated under `hb21-operational-v1`. The final release
is `hb24_rate_12`.

| Line | HB-25's part | HB-23's claims | Served release | Source |
|---|--:|--:|--:|---|
| works | 21 | 39 | 219 | `the corpus graph (held privately)` (`works`) |
| claims rated | 6,701 | 7,806 | 17,928 | `the corpus graph (held privately)` (`claims_rated`) |
| rater agreement | 0.9648 | 0.9654 | 0.9714 | `the corpus graph (held privately)` (`overall`) |
| Wilson 95 %, low | 0.960 | 0.961 | 0.969 | `the corpus graph (held privately)` (`wilson95`) |
| Wilson 95 %, high | 0.969 | 0.969 | 0.974 | `the corpus graph (held privately)` (`wilson95`) |
| after adjudication | 0.9760 | 0.9763 | 0.9801 | `the corpus graph (held privately)` (`after_adjudication`) |
| adjudicated | 236 | 270 | 512 | `the corpus graph (held privately)` (`adjudicator`) |
| overturned | 75 | 85 | 156 | `the corpus graph (held privately)` (`adjudicator`) |
| overturn rate | 0.318 | 0.315 | 0.305 | `the corpus graph (held privately)` (`adjudicator`) |
| refused | 161 | 185 | 356 | `the corpus graph (held privately)` (`refused`) |

The 17,928 claims rated in HB-24 and HB-25 carry a standing verdict: 17,572 yes and 356 no,
equal to the report
(`docs/evidence/hb213/lifted/HB-25.md`
section 7). Since HB-125 the served export holds 21,341 claims; the 3,413 it added are not rated
(`docs/evidence/hb213/lifted/HB-125.md`;
Issue `a6b10bb0`). HB-23's documents are accident reports, rulemakings and toxicological profiles.
Agreement on them is lower than on the earlier set, 0.965 against 0.976, with the intervals
apart. The rubric, prompts and models are the same (`LN-12`
section 9).

### 2.6 The downstream test

The corpus graph's downstream test asks seven admitted questions of the claim graph's search. It
checks that a correct claim comes back near the top. The graph is "earned" when at most one of the
seven misses rank 1 to 3 (`test_corpus_claims.py (a test held privately)`).

| Line | Value | Source |
|---|---|---|
| admitted questions passing | 3 of 7 | `docs/evidence/hb213/lifted/HB-25.md` |
| earned | no | `docs/evidence/hb213/lifted/HB-25.md` |
| near-duplicate claims across works (similarity 0.5) | 634, of which 621 sit in a derivation the manifest already states | `LN-09` |

**Why it misses.** The misses are search crowding, not missing claims. Some works reprint or revise
another: NOAA's copy of the ERG text, the ICS forms booklet beside the single forms. They outrank
the original, because the graph has no relation that says one work reprints another. The case is
filed to Squiddy as SQ-045 (`LN-09`). Each corpus
expansion has diluted the ranks further. After HB-23 nothing moved up and four questions fell one
to seven places, as incident reports restated the numbers the questions ask for. That is SQ-045's
near-duplicate class (`docs/evidence/hb213/lifted/HB-23.md`).

**What it means for the server.** Nothing a tool returns depends on it. No tool reads the claim
graph. The packs are parsed from the held source files by page locator. The modules that read
Squiddy exports are build-time code the server never imports (`docs/ARCHITECTURE.md` sections 2
and 4). Part A checks every distance against its pack cell (section 2.1). The downstream test
measures how well the receipts can be found again by search. That is the prior-art and audit
path, not the briefing path.

### 2.7 The modelled layers

**What is not validated.** No modelled layer is validated against observations of a release. What is
held is verification (each engine reproduces its own documented cases at every build of the models
image), comparison with the measured arc maxima of field trials, the benchmark requirement's one
scored trial (Jack Rabbit II Trial 7, below), and measurement on the committed briefs. Each layer's
row is in `docs/evidence/hb159/tevv_rows.md`, generated from the graph.

**The benchmark requirement.** It is in the graph as BENCH-0: as a minimum, the modelled dense cloud,
as hazbrief runs it, meets the published performance of each accepted tool on that tool's own
trials by the same statistic (equivalence), and its objective is to exceed it (better). The
published rows over Jack Rabbit II trials 1, 6 and 7 are BENCH-1 to BENCH-7, and hazbrief's status
against every one of them is "not yet evaluated" (`docs/evidence/hb192/benchmark_rows.md`, the
graph's projection). BENCH-8 and BENCH-9 are the like-for-like rows on Trial 7, the one trial whose
observed arc maxima a held paper tabulates: HPAC's and ALOHA's predictions from the 17-model
comparison's Table 5, scored by one piece of code on the same observations (`docs/evidence/hb199/`,
`docs/evidence/hb206/`). Its route's source term empties the tank in 22 s; ALOHA models such a
release as one minute, and since HB-206 the engine criterion classes it so (decision HBD-464, Issue
`1e15434e`), where before it named no engine (HB-199).

**The benchmark table** (HB-214): every test in one table, one row per test, introduced by its
definitions and followed by short numbered notes; the same table prints on each dense brief's TEVV
page (`docs/evidence/hb214/benchmark_table.html`; its rows as data, `docs/evidence/hb214/benchmark_table.tsv`; both written by `scripts/benchmark_table.py`). The
text after it is the longer detail.

<!-- hb196:benchmark-table -->
**Definitions: what the benchmark table's rows, columns and names mean**

- **Benchmark row (BENCH-n):** one test of hazbrief against a published result. BENCH-0 is the requirement the others serve: as a minimum, hazbrief does as well as each accepted tool; as its objective, better (its state is note 5).
- **Test:** the benchmark row's id and a plain name for it.
- **Run:** the model run being compared (the names are below); empty where no run is held.
- **Compared with:** the trial's measurements, or a tool's published run of the same trial (why these tools: note 3).
- **Arcs (n):** how many sampling arcs, at fixed distances from the release, are compared; each arc gives its maximum concentration.
- **Ratio:** against the measurements, the geometric mean of measured over predicted concentration (MG); against a tool, the run's MG divided by the tool's. 1 means no difference; above 1 means the run's concentrations are lower.
- **95 percent limits:** the range the ratio could plausibly be in, at the 95 percent confidence level (the method: note 2).
- **Within a factor of two (k of n):** how many arcs' predicted maximum is within a factor of two of the measured one; a count, not a test.
- **Statistically different?:** Yes when the 95 percent limits leave out 1, with below or above for the run's concentrations; No when they include 1; Not yet tested where no run is held.
- **Note:** the numbers of the notes below the table that bear on the row.
- **SCICHEM:** hazbrief's run of SCICHEM, the puff model that draws a dense release's cloud on the brief.
- **SLAB RH 20, SLAB RH 80:** hazbrief's run of SLAB, the dense-gas model (Lawrence Livermore National Laboratory, 1990), at 20 or 80 percent relative humidity.
- **HPAC complex, HPAC simple:** HPAC's two published runs of the trial: with a complex source (the 17-model comparison) and a simple jet-only source (Simpson et al. 2020).
- **ALOHA:** ALOHA's (Areal Locations of Hazardous Atmospheres) published run of the trial in the 17-model comparison.

**The benchmark table: every test of hazbrief against a published result**

| Test | Run | Compared with | Arcs (n) | Ratio | 95 percent limits | Within a factor of two (k of n) | Statistically different? | Note |
|---|---|---|---|---|---|---|---|---|
| BENCH-8, BENCH-9 Jack Rabbit II Trial 7 | SCICHEM | Measurements | 5 | 2.88 | 1.58 to 5.27 | 1 of 5 | Yes, below | 1 |
| BENCH-8, BENCH-9 Jack Rabbit II Trial 7 | SLAB RH 20 | Measurements | 5 | 1.43 | 0.83 to 2.47 | 4 of 5 | No | 1 |
| BENCH-8, BENCH-9 Jack Rabbit II Trial 7 | SLAB RH 80 | Measurements | 5 | 1.41 | 0.81 to 2.47 | 4 of 5 | No | 1 |
| BENCH-8 Jack Rabbit II Trial 7, HPAC | HPAC complex | Measurements | 5 | 1.73 | 0.92 to 3.26 | 3 of 5 | No | 1 |
| BENCH-8 Jack Rabbit II Trial 7, HPAC | HPAC simple | Measurements | 5 | 1.63 | 0.92 to 2.86 | 4 of 5 | No | 1 |
| BENCH-9 Jack Rabbit II Trial 7, ALOHA | ALOHA | Measurements | 5 | 2.13 | 0.65 to 6.98 | 3 of 5 | No | 1 |
| BENCH-1 HPAC complex source, three trials |  | Measurements |  |  |  |  | Not yet tested |  |
| BENCH-2 HPAC measured weather, three trials |  | Measurements |  |  |  |  | Not yet tested |  |
| BENCH-3 HPAC forecast weather, three trials |  | Measurements |  |  |  |  | Not yet tested |  |
| BENCH-4 HPAC forecast, re-aligned, three trials |  | Measurements |  |  |  |  | Not yet tested |  |
| BENCH-5 HPAC arrival time, three trials |  | Measurements |  |  |  |  | Not yet tested |  |
| BENCH-6 HPAC cloud width overlap, three trials |  | Measurements |  |  |  |  | Not yet tested |  |
| BENCH-7 ALOHA, three trials |  | Measurements |  |  |  |  | Not yet tested |  |
| BENCH-8 Jack Rabbit II Trial 7, HPAC | SCICHEM | HPAC complex | 5 | 1.66 | 0.87 to 3.16 |  | No | 1, 4 |
| BENCH-8 Jack Rabbit II Trial 7, HPAC | SCICHEM | HPAC simple | 5 | 1.77 | 0.91 to 3.47 |  | No | 1, 4 |
| BENCH-9 Jack Rabbit II Trial 7, ALOHA | SCICHEM | ALOHA | 5 | 1.35 | 0.62 to 2.94 |  | No | 1, 4 |
| BENCH-8 Jack Rabbit II Trial 7, HPAC | SLAB RH 20 | HPAC complex | 5 | 0.83 | 0.44 to 1.56 |  | No | 1, 4 |
| BENCH-8 Jack Rabbit II Trial 7, HPAC | SLAB RH 20 | HPAC simple | 5 | 0.88 | 0.49 to 1.58 |  | No | 1, 4 |
| BENCH-9 Jack Rabbit II Trial 7, ALOHA | SLAB RH 20 | ALOHA | 5 | 0.67 | 0.31 to 1.46 |  | No | 1, 4 |
| BENCH-8 Jack Rabbit II Trial 7, HPAC | SLAB RH 80 | HPAC complex | 5 | 0.82 | 0.42 to 1.57 |  | No | 1, 4 |
| BENCH-8 Jack Rabbit II Trial 7, HPAC | SLAB RH 80 | HPAC simple | 5 | 0.87 | 0.47 to 1.59 |  | No | 1, 4 |
| BENCH-9 Jack Rabbit II Trial 7, ALOHA | SLAB RH 80 | ALOHA | 5 | 0.66 | 0.31 to 1.41 |  | No | 1, 4 |

**Notes**

1. Jack Rabbit II Trial 7: one trial, five arcs at 0.2 to 5 km, all of one release, not five independent releases.
2. The limits are Hanna, Strimaitis and Chang (1993), equation 34, at the 95 percent confidence level; the words are the Census Bureau's.
3. Why HPAC and ALOHA, the operator: "the community tools that people have been relying on ... the gold standard for the community."
4. Two models can agree and both be wrong (Warner et al., page 40). The operator: "they can still be useful for making decisions."
5. BENCH-0's minimum, doing as well as each tool: not statistically significant at 95 percent against HPAC or ALOHA (one trial, five arcs).

Detail: docs/submission/EVALUATION.md section 2.7; the numbers: docs/evidence/hb209/trial7_intervals.tsv and docs/evidence/hb212/states.tsv.
<!-- /hb196:benchmark-table -->

Each published row's status is the projection's, with its reason, in the first table after the
text below. The two tables after it give the sizes the words stand for
(HB-209): each run's share of the measured arc maximum, its arcs within a factor of two, and its MG
with the 95 percent limits of the held difference test of Hanna, Strimaitis and Chang (1993,
equation 34; `docs/evidence/hb209/intervals.yaml`), both published HPAC runs of the trial (Simpson
Tables 3 and 4; `docs/evidence/hb209/simpson_hpac_trial7.yaml`) beside hazbrief's; then each
hazbrief run's MG over each tool run's.

**Status by statistical significance** (HB-212; HB-213, in the Census Bureau's words). A
difference is "statistically significant", printed with its direction (above or below), only where
the 95 percent limits exclude 1; where they include 1 it is "not statistically significant"; each
state is printed with the confidence level, the ratio, its limits and the number of arcs, and a row
with no run is "not yet evaluated". The words are the Census Bureau's: "A test of statistical
significance provides statistical evidence that indicates whether an observed difference between
two estimates is likely due to chance ('not statistically significant'), or likely represents a
true difference that exists in the population as a whole ('statistically significant')" (ACS
General Handbook 2020, `census-acs-general-handbook-2020` block b952, p. 88). The level is 95
percent, the level of the held difference test; the Census Bureau's ACS comparison indicator uses
90 percent (`census-acs-design-methodology-2024` block b1428, p. 215; both blocks as held,
`docs/evidence/hb213/acs_blocks.md`). One function gives every state
(`scripts/benchmark_state.py`; `docs/evidence/hb212/states.tsv`). Against the measurements
first: the SCICHEM run is below them, a difference that is statistically significant at the 95
percent confidence level (MG 2.88, limits 1.58 to 5.27); for every other run, hazbrief's SLAB runs
and the tools' published runs, the difference from them is not statistically significant at that
level. Against the tools second: the limits of all nine ratios include 1, so on five arcs of one
trial no hazbrief run's difference in mean bias from a tool's is statistically significant at the
95 percent confidence level, and BENCH-8 and BENCH-9, where the one-minute rule gives the route a
prediction (Issue `1e15434e`), read "not statistically significant at 95 percent". The minimum,
equivalence with each tool, reads "not statistically significant at 95 percent against HPAC or
ALOHA (one trial, five arcs)". The five arcs are of one release, not five independent releases. Until HB-212 the word on both rows was "below", taken by HB-199 section 5 from a count of the
acceptance criteria each run passes, a method that set aside the field's difference test. The rows
take SCICHEM's run, the layer a stable brief draws first. BENCH-5, the arrival, states hazbrief's
Trial 7 arrival ratios beside HPAC's and stays "not yet evaluated": no held source states a
criterion for it, no held interval is on it, and trials 1 and 6 are not run. Trials 1 and 6's
maxima are only plotted in the held manuscript (`docs/FUTURE_WORK.md`, F1). Both papers define MG as
observed over predicted, so above 1 is under-prediction.

**Why these tools.** In the operator's words (2026-11-20): HPAC and ALOHA are not just the standards
but the community tools that responders have relied on, the gold standard for the community;
hazbrief is held to them as baselines in its test and evaluation, and landing within their range is
the check that the system built here is not producing confabulations or other wrong output.

**Two models can agree and both be wrong.** Agreement between models is not agreement with the
release: "it is quite possible that two models agree perfectly with one another, yet ... disagree
with real-world observations" (Warner et al., the held HPAC and NARAC comparison,
`hb188-osti-15013318-hpac-narac` p. 40, as BENCH-0's note printed it until HB-214,
`docs/evidence/hb212/rows212.yaml`; the benchmark table's note 4 is its short form). That is why the line against the measurements comes first.
The operator (2026-11-20), his statement and not a held source's: models chasing the wind can both
be wrong about reality and still be useful for the timely decisions of complex, fast-moving and often
ambiguous situations.

<!-- hb196:benchmarks -->
| Row | Published benchmark, its case, arcs, weather and source | Mean bias | hazbrief's status | Source |
|---|---|---|---|---|
| BENCH-1 | HPAC, complex source, arc maximum concentration on Jack Rabbit II trials 1, 6 and 7 at 0.2 to 5 km (BOOT; the 11 km arc left out), on the comparison's recommended meteorological inputs: VG 1.65, MG 1.04, FAC2 0.60, FAC5 1.00 (mazzola-2020-jack-rabbit-ii-17-dense-gas-models-manuscript p. 26, Table 7; inputs Table 2 p. 6; MG below 1 is over-prediction and above 1 under-prediction, p. 25). | MG 1.04: under-predicts | not yet evaluated | `docs/evidence/hb192/benchmark_rows.md` |
| BENCH-2 | HPAC on measured weather (the site's measurements with a stated stability, MWG StabE), simple jet-only source, original orientation, on Jack Rabbit II trials 1, 6 and 7: FAC2 0.67 to 0.83 on the six arc maxima at 0.2 to 11 km, and MG 1.45 to 4.26, VG 12.51 to 27,800, FB -0.02 to 0.30 on sensors paired in space at 0.5 to 11 km above 0.1 ppm (simpson-2020-hpac-jack-rabbit-ii-accepted-manuscript Table 11 p. 22; MG observed over predicted, eq. 6 p. 9). | MG 1.45 to 4.26: under-predicts | not yet evaluated | `docs/evidence/hb192/benchmark_rows.md` |
| BENCH-3 | HPAC on forecast weather (a 3 km WRF run), simple jet-only source, original orientation, on Jack Rabbit II trials 1, 6 and 7: FAC2 0.00 to 0.50 on the six arc maxima at 0.2 to 11 km, and MG 10.21 to 82.64, VG 6.86E+05 to 5.83E+19, FB 0.65 to 1.33 on sensors paired in space at 0.5 to 11 km above 0.1 ppm (simpson-2020-hpac-jack-rabbit-ii-accepted-manuscript Table 11 p. 22; MG observed over predicted, eq. 6 p. 9). | MG 10.21 to 82.64: under-predicts | not yet evaluated | `docs/evidence/hb192/benchmark_rows.md` |
| BENCH-4 | HPAC on forecast weather (a 3 km WRF run), simple jet-only source, re-aligned to the observed cloud's midpoint, on Jack Rabbit II trials 1, 6 and 7: FAC2 0.00 to 0.50, MG 2.32 to 4.11, VG 6.36 to 50.86 (simpson-2020-hpac-jack-rabbit-ii-accepted-manuscript Table 12 p. 23). | MG 2.32 to 4.11: under-predicts | not yet evaluated | `docs/evidence/hb192/benchmark_rows.md` |
| BENCH-5 | HPAC's time of arrival of each arc's maximum relative to the observed on Jack Rabbit II trials 1, 6 and 7 at 0.2 to 11 km: 0.62 to 1.74 on measured weather with a stated stability, 0.72 to 1.76 without it, and 0.43 to 1.98 on forecast weather (one arc not determined) (simpson-2020-hpac-jack-rabbit-ii-accepted-manuscript Tables 5 to 7, pp. 15 and 16). | no MG in this row | not yet evaluated | `docs/evidence/hb192/benchmark_rows.md` |
| BENCH-6 | HPAC's measure of effectiveness on Jack Rabbit II trials 1, 6 and 7, the average overlap of the modelled and observed cloud width over the arcs at 0.5 to 11 km: 46.5 to 74.1 percent on measured weather with a stated stability, 46.4 to 77.4 percent without it, 4.8 to 27.4 percent on forecast weather, against the paper's own acceptable value of 70 percent (simpson-2020-hpac-jack-rabbit-ii-accepted-manuscript Tables 8 to 10 p. 20; p. 19). | no MG in this row | not yet evaluated | `docs/evidence/hb192/benchmark_rows.md` |
| BENCH-7 | ALOHA, arc maximum concentration on Jack Rabbit II trials 1, 6 and 7 at 0.2 to 5 km (BOOT; the 11 km arc left out), on the comparison's recommended meteorological inputs: VG 2.69, MG 0.92, FAC2 0.60, FAC5 0.87 (mazzola-2020-jack-rabbit-ii-17-dense-gas-models-manuscript p. 26, Table 7); its stated limits: no prediction for more than an hour after a release begins or past 10 km from the release point (epa-aloha-users-manual-2007 p. 30). | MG 0.92: over-predicts | not yet evaluated | `docs/evidence/hb192/benchmark_rows.md` |
| BENCH-8 | HPAC, complex source, arc maximum concentration on Jack Rabbit II Trial 7 at 0.2 to 5 km, its row of the 17-model comparison's Table 5 on the comparison's recommended meteorological inputs, scored against the same table's observed row by the manuscript's equations: FAC2 0.60, FAC5 1.00, MG 1.73, VG 1.66, FB 0.82, NMSE 2.37 (mazzola-2020-jack-rabbit-ii-17-dense-gas-models-manuscript p. 20, Table 5; equations p. 16; MG above 1 is under-prediction, p. 25). | MG 1.73: under-predicts | not statistically significant at 95 percent: hazbrief's SCICHEM run against HPAC's complex-source run on Jack Rabbit II Trial 7: MG ratio 1.66, 95 percent limits 0.87 to 3.16, on 5 arcs (Issue 1e15434e); see the benchmark table. | `docs/evidence/hb192/benchmark_rows.md` |
| BENCH-9 | ALOHA, arc maximum concentration on Jack Rabbit II Trial 7 at 0.2 to 5 km, its row of the 17-model comparison's Table 5 on the comparison's recommended meteorological inputs, scored against the same table's observed row by the manuscript's equations: FAC2 0.60, FAC5 0.80, MG 2.13, VG 3.59, FB 0.34, NMSE 0.35 (mazzola-2020-jack-rabbit-ii-17-dense-gas-models-manuscript p. 20, Table 5; equations p. 16; MG above 1 is under-prediction, p. 25). | MG 2.13: under-predicts | not statistically significant at 95 percent: hazbrief's SCICHEM run against ALOHA's run on Jack Rabbit II Trial 7: MG ratio 1.35, 95 percent limits 0.62 to 2.94, on 5 arcs (Issue 1e15434e); see the benchmark table. | `docs/evidence/hb192/benchmark_rows.md` |
<!-- /hb196:benchmarks -->

<!-- hb196:trial7 -->
| Run | 0.2 km | 0.5 km | 1 km (saturated) | 2 km | 5 km | Arcs within a factor of two | MG (95 percent limits) | State against the measurements | Source |
|---|---|---|---|---|---|---|---|---|---|
| HPAC, complex source (17-model Table 5; Simpson Table 4) | 43 % | 28 % | 100 % | 71 % | 75 % | 3 of 5 | 1.73 (0.92 to 3.26) | not statistically significant at 95 percent | `docs/evidence/hb209/trial7_arcs.tsv`; `docs/evidence/hb209/trial7_intervals.tsv`; `docs/evidence/hb212/states.tsv` |
| HPAC, simple source (Simpson Table 3) | 77 % | 28 % | 85 % | 66 % | 72 % | 4 of 5 | 1.63 (0.92 to 2.86) | not statistically significant at 95 percent | `docs/evidence/hb209/trial7_arcs.tsv`; `docs/evidence/hb209/trial7_intervals.tsv`; `docs/evidence/hb212/states.tsv` |
| ALOHA (17-model Table 5) | 72 % | 62 % | 132 % | 35 % | 11 % | 3 of 5 | 2.13 (0.65 to 6.98) | not statistically significant at 95 percent | `docs/evidence/hb209/trial7_arcs.tsv`; `docs/evidence/hb209/trial7_intervals.tsv`; `docs/evidence/hb212/states.tsv` |
| hazbrief, SCICHEM (the route's run) | 32 % | 29 % | 73 % | 38 % | 20 % | 1 of 5 | 2.88 (1.58 to 5.27) | statistically significant at 95 percent, below | `docs/evidence/hb209/trial7_arcs.tsv`; `docs/evidence/hb209/trial7_intervals.tsv`; `docs/evidence/hb212/states.tsv` |
| hazbrief, SLAB, RH 20 percent (the route's run) | 77 % | 55 % | 135 % | 68 % | 43 % | 4 of 5 | 1.43 (0.83 to 2.47) | not statistically significant at 95 percent | `docs/evidence/hb209/trial7_arcs.tsv`; `docs/evidence/hb209/trial7_intervals.tsv`; `docs/evidence/hb212/states.tsv` |
| hazbrief, SLAB, RH 80 percent (the route's run) | 79 % | 57 % | 139 % | 68 % | 42 % | 4 of 5 | 1.41 (0.81 to 2.47) | not statistically significant at 95 percent | `docs/evidence/hb209/trial7_arcs.tsv`; `docs/evidence/hb209/trial7_intervals.tsv`; `docs/evidence/hb212/states.tsv` |

| hazbrief's run | Against | MG ratio, hazbrief over the tool (95 percent limits) | State against the tool | Source |
|---|---|---|---|---|
| hazbrief, SCICHEM (the route's run) | HPAC, complex source (17-model Table 5; Simpson Table 4) | 1.66 (0.87 to 3.16) | not statistically significant at 95 percent | `docs/evidence/hb209/trial7_intervals.tsv`; `docs/evidence/hb212/states.tsv` |
| hazbrief, SCICHEM (the route's run) | HPAC, simple source (Simpson Table 3) | 1.77 (0.91 to 3.47) | not statistically significant at 95 percent | `docs/evidence/hb209/trial7_intervals.tsv`; `docs/evidence/hb212/states.tsv` |
| hazbrief, SCICHEM (the route's run) | ALOHA (17-model Table 5) | 1.35 (0.62 to 2.94) | not statistically significant at 95 percent | `docs/evidence/hb209/trial7_intervals.tsv`; `docs/evidence/hb212/states.tsv` |
| hazbrief, SLAB, RH 20 percent (the route's run) | HPAC, complex source (17-model Table 5; Simpson Table 4) | 0.83 (0.44 to 1.56) | not statistically significant at 95 percent | `docs/evidence/hb209/trial7_intervals.tsv`; `docs/evidence/hb212/states.tsv` |
| hazbrief, SLAB, RH 20 percent (the route's run) | HPAC, simple source (Simpson Table 3) | 0.88 (0.49 to 1.58) | not statistically significant at 95 percent | `docs/evidence/hb209/trial7_intervals.tsv`; `docs/evidence/hb212/states.tsv` |
| hazbrief, SLAB, RH 20 percent (the route's run) | ALOHA (17-model Table 5) | 0.67 (0.31 to 1.46) | not statistically significant at 95 percent | `docs/evidence/hb209/trial7_intervals.tsv`; `docs/evidence/hb212/states.tsv` |
| hazbrief, SLAB, RH 80 percent (the route's run) | HPAC, complex source (17-model Table 5; Simpson Table 4) | 0.82 (0.42 to 1.57) | not statistically significant at 95 percent | `docs/evidence/hb209/trial7_intervals.tsv`; `docs/evidence/hb212/states.tsv` |
| hazbrief, SLAB, RH 80 percent (the route's run) | HPAC, simple source (Simpson Table 3) | 0.87 (0.47 to 1.59) | not statistically significant at 95 percent | `docs/evidence/hb209/trial7_intervals.tsv`; `docs/evidence/hb212/states.tsv` |
| hazbrief, SLAB, RH 80 percent (the route's run) | ALOHA (17-model Table 5) | 0.66 (0.31 to 1.41) | not statistically significant at 95 percent | `docs/evidence/hb209/trial7_intervals.tsv`; `docs/evidence/hb212/states.tsv` |
<!-- /hb196:trial7 -->

**The comparison with measured field trials** (HB-176, HB-177, HB-180, HB-183, HB-185), each
engine as hazbrief runs it. These runs were at the 250 m vertical setting; none has been repeated at
the 1.25 m setting a dense brief now runs at (`src/hazbrief/brief/conditions.yaml`).

| Trials | Engine | Result | Source |
|---|---|---|---|
| Stable (classes E and F): Desert Tortoise 4, Thorney Island 45 and 47, Burro 8; 10 arcs at 212 to 800 m | SLAB | every arc within a factor of two | `docs/evidence/hb176/summary.tsv`; `src/hazbrief/brief/conditions.yaml` |
| Stable: the three trials without Burro 8, 8 arcs | SLAB | MG 0.87 (95 percent 0.76 to 1.00) | `docs/evidence/hb183/score.tsv`; `src/hazbrief/brief/conditions.yaml` |
| Stable, 8 arcs | SCICHEM, the mean the brief draws | below every arc, MG 3.50 (95 percent 2.87 to 4.27) | `docs/evidence/hb180/statistics_c.tsv`; `src/hazbrief/brief/conditions.yaml` |
| Stable, 8 arcs | SCICHEM, scored as its authors score a peak | MG 1.80 | `docs/evidence/hb177/hb176_restated.tsv`; `src/hazbrief/brief/conditions.yaml` |
| Daytime two-phase (class D): Desert Tortoise 1 to 3, Goldfish 1 to 3; 11 arcs at 300 to 3,000 m | SCICHEM, scored as a peak | below every arc, MG 2.66 (95 percent 1.98 to 3.59); the mean the brief draws 4.33 | `docs/evidence/hb185/statistics.tsv`; `src/hazbrief/brief/conditions.yaml` |
| Daytime, given each trial's measured Monin-Obukhov length | SCICHEM, scored as a peak | 2.02; Desert Tortoise 4.24 to 1.78, Goldfish 2.24 to 2.12 | `docs/evidence/hb185/statistics.tsv`; `src/hazbrief/brief/conditions.yaml` |

**The night clock's setting and what it costs** (HB-187, HB-189). Where any hour of a brief's
horizon is stable, the moving cloud runs at a stated 1.25 m vertical setting. On csx night its level
areas at hour 1 are 0.83 to 0.91 of the finest run held, and its arrivals are within 360 s of that
run's in the first hour (`docs/evidence/hb187/o1_curve.tsv`). Against the finest run, the 1.25 m
arrival is earlier at 386 of 531 place-levels, later at 37 and equal at 108, at most 720 s later
(360 s in the first hour), so the stable checklist line says an arrival may be earlier than shown by
up to 12 minutes, 6 in the first hour (`docs/evidence/hb192/arrival_sign.tsv`;
`docs/evidence/hb213/lifted/HB-192.md`).
No setting run is converged, and every trial arc still reads below the measurement at 1.25 m
(`docs/evidence/hb187/q2_convergence.tsv`).

**The moving cloud as it is computed** (HB-192). The cloud is held as a frame every 15 minutes of
cloud time on a 25 m mesh. Time from the engine's start to each brief's first frame and last
frame, one run each in the models image (`docs/evidence/hb192/frames.tsv`; `docs/evidence/hb213/lifted/HB-192.md`):

| Brief | Frames | First frame | Last frame | Source |
|---|--:|--:|--:|---|
| csx night | 24 | 14.2 s | 194.9 s | `docs/evidence/hb192/frames.tsv`; `docs/evidence/hb213/lifted/HB-192.md` |
| I-495 night | 20 | 19.3 s | 123.1 s | `docs/evidence/hb192/frames.tsv`; `docs/evidence/hb213/lifted/HB-192.md` |
| I-81 night | 20 | 27.4 s | 109.6 s | `docs/evidence/hb192/frames.tsv`; `docs/evidence/hb213/lifted/HB-192.md` |
| I-83 night | 16 | 44.2 s | 96.8 s | `docs/evidence/hb192/frames.tsv`; `docs/evidence/hb213/lifted/HB-192.md` |
| the nine day-start briefs | 8 to 12 | 3.0 to 4.6 s | 14.9 to 36.1 s | `docs/evidence/hb192/frames.tsv`; `docs/evidence/hb213/lifted/HB-192.md` |

**Each page's size and live load time, before and after HB-192** (headless Chrome, served by
replay, no call). The night pages' before is HB-189's measurement and their after HB-192's, two
files; csx day's before size is read from HB-192's base, and its before load of 48.0 s is cited from
HB-192's RESULT (`docs/evidence/hb213/lifted/HB-192.md`), because that measurement was not saved as data.

| Brief | `brief.html` before | after | Live load before | after | Source |
|---|--:|--:|--:|--:|---|
| csx night | 6.62 MB | 3.39 MB | 71.4 s | 73.1 s | `docs/evidence/hb189/live_load.tsv`; `docs/evidence/hb192/live_load.tsv` |
| I-495 night | 4.64 MB | 1.40 MB | 52.0 s | 48.8 s | `docs/evidence/hb189/live_load.tsv`; `docs/evidence/hb192/live_load.tsv`; `docs/evidence/hb213/lifted/HB-192.md` |
| I-81 night | 4.32 MB | 1.68 MB | 47.4 s | 49.7 s | `docs/evidence/hb189/live_load.tsv`; `docs/evidence/hb192/live_load.tsv` |
| I-83 night | 4.05 MB | 1.18 MB | 47.7 s | 49.0 s | `docs/evidence/hb189/live_load.tsv`; `docs/evidence/hb192/live_load.tsv`; `docs/evidence/hb213/lifted/HB-192.md` |
| csx day | 2.78 MB | 1.53 MB | 48.0 s | 47.7 s | `docs/evidence/hb196/csx_day_before.tsv`; `docs/evidence/hb192/live_load.tsv`; `docs/evidence/hb213/lifted/HB-192.md` |

The pages are half the size or less and load in the same time, because the time is the brief's
assembly by replay, not the page's bytes. Where the assembly's time goes is not measured
(`docs/FUTURE_WORK.md`, F9).

**What the first map draws.** On csx night the population under the cloud, drawn block by block,
took 3,334,501 bytes of the page before and 267,976 after, drawn as one shape per colour class with
every count still read block by block; the first map drew 165 modelled cordons and 102 road
candidates before and 13 and 31 after, every other candidate in a table on the Timeline page
(`docs/evidence/hb213/lifted/HB-192.md`; `docs/evidence/hb196/weight_before.tsv`; `docs/evidence/hb192/weight_after.tsv`;
`docs/evidence/hb196/blocks_before.tsv`; `docs/evidence/hb192/blocks_after.tsv`;
`docs/evidence/hb196/README.md`). The before files were regenerated from HB-192's base by its own
tools and agree with its RESULT.

**The lookup's accuracy.** The mesh at the ground against each measured point's own sensor at 1.5 m,
at the frame's time, where the sensor reads AEGL-1 or above: on csx night median 0.86 and worst 2.20
over 715 point-frames; the other night briefs' medians 0.78 to 0.85
(`docs/evidence/hb192/lookup_accuracy.tsv`;
`docs/evidence/hb213/lifted/HB-192.md`).

**The outline and the first view.** The level outlines are drawn within 25 m of the outline before
simplifying, worst 23.2 m (`docs/evidence/hb192/outline_tolerance.tsv`). The first view is 10.5 to
49.4 m per pixel over the 13 dense briefs, so the 25 m mesh is about one pixel and the tolerance 0.5
to 2.4 pixels (`docs/evidence/hb192/first_view_m_per_px.txt`;
`docs/evidence/hb213/lifted/HB-192.md`).

## 3. Security considerations

The full note is `docs/SECURITY.md`, and what follows summarises it.

* **Posture.** The server answers questions about public federal data. It holds no personal data
  and no user credentials, writes nothing upstream and calls no model. Its one secret is the
  operator's free Census Data API key. The risks that matter are three. A wrong answer may be
  presented as authoritative. The server may be used as a proxy or amplifier against federal
  services. The key may leak into a committed file (`docs/SECURITY.md` section 1).
* **Outbound boundary.** Every tool is read-only. No tool takes a URL, a path or a query string;
  the origin comes from configuration. One HTTP client refuses absolute or traversing paths,
  including their encoded forms. It follows no redirect and reads no proxy settings. It follows a
  response's next link only under the same origin, and caps every call's time and size. Each item
  has a regression test in `tests/test_http_security.py` (`docs/SECURITY.md` section 2).
* **Secrets.** There is one key, read through layered dotenv files with a stated precedence. The
  key is never committed and never in the container image. Every recorded exchange has it
  stripped, and no error message carries it (`docs/SECURITY.md` section 3; DN-004).
* **Input validation.** Pydantic models use `extra="forbid"`, bounded strings, ranged coordinates
  and times with a UTC offset. An object sent as a JSON string is parsed once and never repaired.
  An input the ERG cannot answer returns an error with a hint, never a nearest match
  (`docs/SECURITY.md` section 4).
* **What the model never decides.** Flags are rules in a pack, each with its ERG source. Every
  ICS 201 sentence is a filled template or a quoted ERG sentence with receipts. A sentence without
  one fails the build. Packs are verified by sha256 and schema at startup, and an altered pack
  stops the server (`docs/SECURITY.md` section 6).
* **Build-time controls.** The corpus fetcher obeys an exact host allowlist and `robots.txt`
  (RFC 9309). Corpus binaries are not committed; provenance is url and sha256
  (`docs/SECURITY.md` section 7).
* **The container image.** It holds every path the runtime reads, runs as a non-root user, and
  installs from `uv.lock`. CI actions are pinned by commit sha. A test holds each rule
  (`test_container_image.py (a test held privately)`; `docs/SECURITY.md` sections 8 and 9; HB-34).

**What is not done** (`docs/SECURITY.md` section 9). Authentication on the HTTP transport, rate
limiting and an audit log are not enabled, though the locked FastMCP ships all three. So the route is
unpublished: it binds 127.0.0.1, checks the Host and Origin headers, masks raised errors, and
`server.json` lists no remote; a caller's footprint is bounded in area, vertices and pages per
layer (`docs/SECURITY.md` section 10; HB-89). CI runs no dependency audit, secret scan or static analysis. The handoff
secret scan (AD-039) runs before every governed commit of a handoff (`the Seldon configuration (held privately)`
`desktop_commit.scan`, HB-33), not in CI. Before any deployment past the
hackathon, the first three gaps are the ones to close.

**The tree scanned once, by hand, for this edition.** The handoff gate's scanner ran over all
22,359 tracked files and, apart, the 28 handoffs: no hit in the handoffs, and three in the tree,
none a credential of this project. Two are a third party's pre-signed download URL, which expired
on 2026-11-12, recorded as an inbox file's origin, to be stripped before publication (Issue
`3b997b40`); one is a chance match inside a base64 frame mesh
(`docs/evidence/hb196/secret_scan.txt`; `docs/evidence/hb196/secret_scan_review.md`). The
licences and notices of everything the repository ships or builds are gathered in `NOTICE`,
generated from the held records by `scripts/notice.py`.

## 4. Lessons learned and recommendations

Each lesson cites the files that hold its evidence. Each recommendation is what a second team
building a server like this should do differently, and it names the lesson it comes from.

### 4.1 The ERG is data, not text

* **What happened.** The ERG's distance tables were parsed from the PDF by locator. pdfplumber
  read the ruling lines. Every row was keyed three times. The keys were the PDF's text layer and
  a read of the rendered page, and PHMSA's ERG2020 data files adjudicated between them
  (`docs/evidence/hb213/lifted/HB-03b.md`, `packs/SCHEMA.md`).
* **What it found.** Reading the tables as data found the ERG's own errors. In 203 cells the
  metric value was revised and the US-unit value left at its 2020 figure. In 200 of them the old US
  value still rounds correctly. In 3 of them, and in 2 other cells, the printed pair disagrees.
  The ERG's rounding was measured on its own 2,213 pairs, not assumed
  (`docs/evidence/hb213/lifted/HB-03c.md`). The five cells are drafted
  as an erratum to PHMSA, not sent (`2026-10-21_PHMSA_erratum_draft`).
* **What happened next.** Search ranking over the same documents was too coarse for table rows.
  So the packs are parsed by page locator, and the claim graph holds the receipts
  (`docs/ARCHITECTURE.md` section 4). The pack build dropped the rows the ERG prints without an ID
  number. Guides 112 and 114 are reached by placard and guide number instead
  (`docs/evidence/hb213/lifted/HB-15.md` section 6).
* **Lesson.** A reference table is data with a page locator. Each cell is checked against the
  page, and the source's own inconsistencies are reported, not smoothed.
* **Recommendation.** Parse authoritative tables by locator into a versioned, hashed pack with a
  round-trip test. Key each cell more than once, from independent readings. Run a unit-consistency
  check before trusting any printed pair. Do not retrieve table values by text search.

### 4.2 The client's result cap is part of the interface

* **What happened.** In the first agent pilot, `build_ics_201` answered 255,690 characters. Claude
  Code refused it, because it caps a tool result at 25,000 tokens by default. The fix was a
  concise default of at most 28,626 characters over the scenarios, with the detail paged. After
  it, the demo model called the 201 in 42 of 48 scenario episodes
  (`LN-07`, F1).
* **And again.** The final run found the same failure in the opt-in map sketch. Three calls asked
  for it, and the client refused results of 148,721 to 195,440 characters. The option's
  description had said only "large"
  (`docs/evidence/hb213/lifted/HB-16b.md` section 6).
* **Lesson.** A tool result that is correct but over the client's cap never reaches the model.
  Unit tests cannot see it; only an agent run through a real client can.
* **Recommendation.** Measure every tool's result size against the target client's documented
  cap. Default to a concise form under it. Name the cap in the description of every option that
  exceeds it. Run an agent pilot before the matrix: this one found the defect before any matrix
  episode ran.

### 4.3 The model lock and the CLI are part of the measured system

* **What happened.** The model lock moved the CLI mid-pilot during HB-14. The gated pilot ran on a
  binary the earlier run did not use
  (`docs/evidence/hb213/lifted/HB-14.md` section 8). Between
  the two agent runs the lock moved again. So every delta compares a new server and a new client
  together (`docs/evidence/hb213/lifted/HB-16b.md` section 7).
* **What it cost.** On the graph's 2,018 pilot calls, the new CLI read 432,268 cached tokens where
  the old one read 2,034,576. The forced re-pilot cost 4,212,332 weighted tokens against an
  estimate of about 2M. Content stayed within one claim per unit, and the rater's paired
  comparison gave McNemar p = 1.0
  (`docs/evidence/hb213/lifted/HB-25.md`
  section 4). The bump came 40 minutes early and stranded 6,701 claims mid-run
  (`docs/evidence/hb213/lifted/HB-25.md`
  section 9).
* **Lesson.** A model client's version changes cost, and sometimes behaviour, independently of
  the model id. A measurement that does not record the client measured an unknown system.
* **Recommendation.** Key every checkpointed unit on the client version as well as the model. Pin
  the binary for a run's whole length. Record cost beside content in any equivalence check between
  client versions.

### 4.4 Ambiguity is settled on the server

* **What happened.** The ERG identifies a material by ID number. A name such as propane is
  listed under more than one (`docs/evidence/hb213/lifted/HB-08.md`
  section 10). The first agent run passed an ambiguous load only if the agent asked back and drew
  nothing. Almost nothing passed (1 of 36), because every model drew each candidate instead
  (`docs/evidence/hb213/lifted/HB-16.md` section 7).
* **What changed.** HB-18 moved the rule onto the server. An unresolved load is drawn once per
  candidate, with the governing one marked, as the ERG directs (`docs/SECURITY.md` section 4). In
  the final run every reply named every candidate, and the governing one with its distance, 36 of
  36. What fails is the wording rule. A propane tie, which "largest" cannot describe, failed 9 of
  9 (filed A-9) (`LN-07`, G1).
* **Lesson.** A rule the client is expected to follow is a hope. A rule the server applies, with
  its reason in the output, is a guarantee, and the client only narrates it.
* **Recommendation.** Put every decision the domain's authority states into the server's output,
  with its source: which row governs, which candidate is worse. Score the client on whether it
  carries that decision through, not on whether it re-derives it.

### 4.5 What the model never decides

* **What happened.** No model writes any sentence the server returns. So the template's LLM-trace
  harness had nothing to score, and the deterministic harness replaced it
  (`LN-05`). Flag rules were mined from the guides with a
  model. The CLI has no temperature flag, so determinism comes from a pure admission test, not
  from sampling (`docs/evidence/hb213/lifted/HB-12.md` section 9).
* **Where judgement leaks in.** The client is where it leaks
  (`LN-07`, G3, G5, G7). One agent drew a guessed material as a
  labelled "worst case" for a placard-only message, once in 558 episodes across both matrices
  (A-8). One reply estimated a cloud's arrival time from the wind speed, once in 288 (A-10). And
  69 of 288 replies used the word the server never prints.
* **Lesson.** The boundary holds where it is enforced in code. Where the server returns only
  sourced values, the client's errors are visible as ungrounded tokens and can be counted.
* **Recommendation.** Keep the model out of every value and every alarm. Make each output value
  carry its source, so that grounding can be scored mechanically. Write the client-side rules (no
  substituted material, no travel time) as stylebook rules and forbidden patterns before the run.

### 4.6 The instrument is part of the result

* **What happened.** The evaluation tools had defects of their own, found on real runs.
  * The live loop stopped on a tool's exception instead of recording a row (F-6,
    `LN-05`).
  * The agent scorer misread stringified requests
    (`docs/evidence/hb213/lifted/HB-16.md` section 7).
  * It also read the wind from a call that takes none, which changed 6 verdicts
    (`docs/evidence/hb213/lifted/HB-16b.md` section 7).
  * The runner halted on an overloaded API's errored envelope
    (`docs/evidence/hb213/lifted/HB-16b.md` section 7).
  * A count in the first agent note, "7 times", was not reproduced from the traces
    (`LN-07`).
  * On the corpus side, the kit's scholarly rubric refused operational text: 0.815 against 0.975,
    held out (`LN-12` section 2).
* **Lesson.** A score is only as good as the scorer. A scorer fit to one population of documents
  misreads another.
* **Recommendation.** Rescore earlier runs with every scorer fix, and report deltas only over like
  with like. Write each scorer fix test-first. Recompute every count a note quotes from the
  traces, not from memory. Choose or write the rubric for the documents being rated, and test it
  held out.

### 4.7 The operator's contention: the human moves to validation, and the training is in the domain

This is the operator's stated position, recorded as his decisions; it is a contention, and this
evaluation does not test it.

* **What he contends.** Assembling a brief by hand puts the person inside the process. Here the
  machine assembles it, section by section, and the person's effort moves to validation and
  verification: "the wind is east to west and the plume is west to east, so the model is wrong"
  (`hazbrief-mcp:HBD-098`, `HBD-098`). And
  because the view is built for the situation in front of the reader, it should need training in
  the domain, not in the software: "A responder should not need training on this software. The
  expertise the brief asks of them is the chemistry and the response, and the one cognitive act it
  is built around is checking" (`hazbrief-mcp:HBD-208`,
  `HBD-208`).
* **What the record holds for it.** The design that follows from it: the map first, every layer
  labelled and each able to be turned off, every line with its receipt, and a TEVV page beside
  every brief (section 1.8). What it does not hold: a test with responders. The display is one
  person's design from experience, and refining it needs design sessions with other people on real
  tasks (`docs/FUTURE_WORK.md`, F19).
* **Recommendation.** Put the system's own evidence where the checking person can open it from the
  thing being checked, and measure the contention with the people it is about before relying on it.

### 4.8 Combining public data sets is joining records that disagree about time and place

* **What happened.** The brief reads federal sources that were never made to be read together.
  NWS forecast grids expire: the ones recorded for the scenario points ended on 2026-10-28, so a
  frozen scenario's own time can no longer be asked of them (`docs/FIXTURES.md` section 4). Census
  sends no as-of header, so its printed as-of dates are configured release dates (section 1.3).
  When every layer was made to read the brief's one wind record, the protective action square
  rotated on 14 committed briefs, and every population and facility call keyed to the old footprint
  asked for an exchange no recording held, so those sections were degraded until a live recording
  (`docs/evidence/hb133/section_states.tsv`; `docs/FUTURE_WORK.md`, L7).
* **Lesson.** Each join of two public sources needs a stated key (tract GEOID, a footprint's
  geometry, an hour) and a stated as-of for each side; a change to one key moves every record keyed
  to it.
* **Recommendation.** Record every upstream exchange under its full request, print each source's
  as-of beside its value, and treat a change to a shared key (the wind, the footprint) as a change
  to every recording that reads it.

### 4.9 A gate that grew

* **What happened.** The full suite's pytest run took 0:29:55 at HB-151, fell to 0:11:58 when HB-164
  ran it in parallel, and grew back past an hour as each task added replays of the committed briefs
  (1:03:35 at HB-189; `docs/evidence/hb193/gate_history.tsv`). Under the parallel load, tests that
  waited on a fixed clock failed four of ten one-step gates with no defect behind them
  (`docs/evidence/hb194/failures.tsv`). HB-194 moved those tests into a second step, one of a kind
  at a time; the gate is now two steps and three in a row were green
  (`docs/evidence/hb194/three_gates.tsv`).
* **Lesson.** A test that asserts a wall-clock bound measures the machine's load as much as the
  code, and a suite that re-assembles the same artifact in every module pays for it in every gate.
* **Recommendation.** Wait on the system's own finished signal, not a fixed clock, and build each
  shared artifact once per run for every module to read (`docs/FUTURE_WORK.md`, F8 and F11).

### 4.10 What a refused merge cost

* **What happened.** HB-189's finished branch passed its gate, and the dispatcher's merge round
  refused it three times. No content conflicted: the round's own dedupe line in the shared event log
  sat uncommitted when it fast-forwarded. Landing the branch took a task of its own, HB-193: every
  commit replayed with the event log held at main's copy, and four more full gate runs
  (`docs/evidence/hb213/lifted/HB-193.md`;
  `docs/evidence/hb193/divergence.txt`).
* **Lesson.** A file every task appends to is a merge point for every task; the tool that merges
  must commit its own writes before it asks git to move.
* **Recommendation.** Keep an append-only log out of the content history, or make the merger's
  writes atomic with its merge.

### 4.11 Recommendations in one list

1. Parse authoritative tables by locator into hashed, versioned packs. Key each cell from
   independent readings, and check units (lesson 4.1).
2. Measure tool results against the client's cap. Default to a concise form, and name the cap
   where an agent reads it (lesson 4.2).
3. Record the client version in every unit key, and pin it for a run. Record cost as well as
   content when a client changes (lesson 4.3).
4. Settle what the domain's authority decides on the server, and score the client on carrying it
   through (lesson 4.4).
5. Keep models out of values and alarms; give every value a source so that grounding is countable
   (lesson 4.5).
6. Treat the scorer and the rubric as code under test, and compare runs like with like (lesson
   4.6).
7. Put the evidence where the checking person can open it from what is checked, and test the
   contention that the training is in the domain with responders before relying on it (lesson 4.7).
8. Give every join of public sources a stated key and an as-of for each side, and treat a change
   to a shared key as a change to every recording keyed to it (lesson 4.8).
9. Wait on a finished signal, not a clock, and build each shared test artifact once per run
   (lesson 4.9).
10. Keep an append-only log out of the content history, or commit the merger's own writes before
    it merges (lesson 4.10).
11. Close authentication and rate limiting before any deployment past a hackathon, and publish a
    remote only after the deployment is recorded (section 3).
