# Fixtures: the scenario fixture format as built

DN-001 section 6 item 4 asked for frozen inputs, recorded upstream responses and expected outputs,
so that the evaluation replays without the network. The format was built piecemeal, HB-08 to
HB-11b. HB-04 documents it here, from the code. Each claim names the file and function that makes
it true. The format follows two prior-art patterns:

* **The recorder is vcrpy's.** `record` is vcrpy's `new_episodes` mode and `replay` is its `none`
  mode (DN-005 section 2, which carries the receipts).
* **`expected.json` and the frozen forms are characterization tests** (Feathers, *Working
  Effectively with Legacy Code*, 2004; also called "golden master"). Each records what the code
  did once, after a review. A later run must reproduce it.

## 1. Layout

| Path | What | Written by |
|---|---|---|
| `fixtures/exchanges/<api>/<key>.json` | One recorded upstream GET (section 2) | `hazbrief.utils._write_exchange`, in `record` mode |
| `fixtures/scenario_points.yaml` | The four corridor points (I-81, I-83, the Wilson Bridge, CSX at Point of Rocks) | authored, HB-08 |
| `fixtures/population/expected.json` | `population_at_risk` counts per HB-09 scenario, with the footprint each was counted in | `scripts/record_population_fixtures.py` `run` |
| `fixtures/facilities/expected.json` | `facilities_in_footprint` and `receiving_hospitals` summaries for the same scenarios | `scripts/record_facilities_fixtures.py` `run` |
| `fixtures/ics201/<scenario>.md`, `.svg` | Frozen ICS 201 Markdown and Block 4 sketch, for six scenarios (12 files) | `record_ics201_fixtures.py (a build tool held privately)` `freeze` |
| `fixtures/lodes/*.csv.gz`, `MANIFEST.json`, `fetch_log.jsonl` | LEHD LODES WAC state files; the manifest carries url, sha256, bytes, `retrieved_at` and the LEHD citation | `scripts/fetch_lodes.py` |
| `fixtures/cms/hospitals.json`, `nursing_homes.json` | CMS files, joined and geocoded once, each with a `meta` block (`as_of`, `released`, `built_at`, the CSV url) | `scripts/fetch_cms.py` |
| `fixtures/scenarios.yaml` | The scenario manifest (section 6). Derived; do not edit | `scenario_manifest.py (a build tool held privately)` `derive` |
| `fixtures/scenario_gaps.yaml` | Why each scenario and tool cell that does not replay is a gap. Authored | by hand, read by `scenario_manifest.derive` |
| `fixtures/scenarios/<scenario>.json` | Golden-master snapshot of every tool's output on the scenario (HB-05 part B; section 7) | `eval_harness.py (a build tool held privately) regression --approve` |
| `fixtures/exchanges_live/<date>/<api>/<key>.json`, `calls.jsonl`, `progress.log`, `drift.json` | HB-05 part C's live recordings, same schema as section 2, never read by replay; one row per live call; the drift report (section 7) | `eval_harness.py (a build tool held privately) live` |
| `fixtures/exchanges/<api>/<key>.json`, promoted | A live recording copied byte for byte into the replay fixtures, after checking its api and that its url hashes to its name (section 7, Promotion) | `scripts/promote_live_exchanges.py` |
| `evidence/seed/<sha[:2]>/<sha>.json` (or `.bin`), `<sha>.<activity id>.prov.json`, `ro-crate-metadata.json` | The evidence seed (HB-39, DN-010 s3.4). Each exchange is an entity and its PROV record. The seed reads the exchanges and never moves them. `test_evidence_replay.py (a test held privately)` replays every record to its hash | `scripts/migrate_exchanges_to_store.py` |
| `evidence/seed_calls/` | The tool-call seed (HB-40): the seven tools on `csx-point-of-rocks-day`. The recording client made each call in replay mode, and its `used` names the exchange-seed entities it read. Idempotent, so a held call is not made again | `scripts/record_tool_call_seed.py` |
| `evidence/seed_briefs/` | The scenario-brief seed (HB-45): the seven tools on every other scenario that replays end to end, recorded as the tool-call seed is, with a structured error held as answered (`--allow-errors`) | `scripts/build_scenario_briefs.py` |
| `fixtures/location_scenarios.yaml` | The scenarios located by a milepost or a crossing, not a point (HB-49): each a copy of a manifest scenario (`base`) with `given` in place of its location, and the channels it does not call (`not_run`, with the reason its sections print). Authored. Not in the manifest, which runs each tool once at one point; a shape is one footprint call per sample plus one call of each other tool over the union | by hand |
| `evidence/seed_briefs/`, located scenarios | Their calls: the footprint at each sample and the other tools over the union, each call's `used` naming the exchange-seed records it read, found by running the tool in-process under the manifest's `_watch`. The server is asked in replay mode; this process records what the calls lack (a call ceiling, `--max-calls`) | `scripts/record_location_scenarios.py` |
| `census_geocoder_outage_synthetic.json (a test held privately)` | A synthetic geocoder outage response (`"synthetic": true`): the 302 to `outage.census.gov` HB-48's fetch log recorded, on the address scenario's request. Kept out of `fixtures/exchanges/`, so replay and the evidence seed never read it as real (HB-50) | by hand |
| `fixtures/exchanges/census_geocoder/` | The Census Geocoder's one-line answers the address derivation reads (HB-50; `corpus/workbench_api_catalog.yaml` `census_geocoder_locations`) | `scripts/record_location_scenarios.py`, `scripts/probe_hb50.py` |
| `fixtures/exchanges/{pasda_penndot,mdot_sha_milepoints,vdot_lrs}/` | The state linear-referencing services' exchanges the location resolver reads (HB-49; `corpus/workbench_api_catalog.yaml`); the manifest lists them among those no scenario reads, since only the located scenarios read them | `scripts/record_location_scenarios.py`, `scripts/probe_hb49.py` |
| `docs/briefs/<scenario>/` | One brief per replayable scenario: `scenario.json`, `brief.html`, `appendix.html`, `appendix.txt`, built at `fixture_now` with `--no-google`; golden masters in `tests/test_brief.py` | `scripts/build_scenario_briefs.py` |
| `fixtures/evidence/appendix_seed.{txt,md,html}`, `ics201_labelled_<scenario>.md` | The evidence appendix of the tool-call seed and its labelled ICS 201, rendered at `labels.yaml`'s fixed instant; `test_evidence_labels.py (a test held privately)` compares each to a fresh render | `scripts/render_evidence_fixtures.py` |

The LODES and CMS caches are not exchanges. The tools read them as files
(`settings.hazbrief_lodes_dir`, `settings.hazbrief_cms_dir` in `src/hazbrief/config.py`), in every
mode, so a tool that uses only them is `network_free` in the manifest.

## 2. The exchange file

**Name.** `exchange_key(method, url, body)` in `src/hazbrief/utils.py` gives the sha256 over
`METHOD\nurl\n` and the body. The body is empty for every GET the server makes. The file is
`<settings.hazbrief_exchanges_dir>/<api>/<key>.json` (`exchange_file`). The url is the one stored
in the file, built by `_request`.

**Credentials are never in the url.** `public_url` drops every query parameter in
`SECRET_QUERY_PARAMS`, which are the Census `key` and the Socrata `$$app_token`. The same request
therefore records to the same file whatever key the operator holds.

**Fields** (`_write_exchange`):

| Field | Holds |
|---|---|
| `api` | the configured upstream name (`nws`, `census`, `tigerweb`, `usgs_structures`, `usgs_3dhp`, `bts_ntad`; `Settings.upstream_base_url`) |
| `method` | `GET` |
| `url` | the stored url, without credentials |
| `request_headers` | only `User-Agent` and `Accept` (`RECORDED_REQUEST_HEADERS`) |
| `status` | the HTTP status |
| `response_headers` | the as-of headers: `Date`, `Last-Modified`, `Expires`, `Cache-Control`, `ETag` (`AS_OF_HEADERS`), where the upstream sent them |
| `body` | the parsed JSON body |
| `recorded_at` | UTC time of the fetch, `YYYY-MM-DDTHH:MM:SSZ` (`_now`) |

**Binary exchanges** (HB-11b, `fetch_bytes`): the TIGERweb `export` image. `body` holds the bytes
base64-encoded, with `body_encoding: base64` and `content_type`. `fetch_bytes` refuses a media type
outside `accept` before it records anything. An ArcGIS export that fails answers a JSON error with
HTTP 200, so the refusal keeps that error out of the fixtures.

**Writing.** Each file is written atomically: a temporary file, then fsync, then `os.replace`. It
is chmod 644 so that a committed file is readable by any user. Before writing, `_write_exchange`
refuses a record in which any configured secret value appears (`_secret_values`). Keys are sorted
and the indent is one space, so a re-recording diffs cleanly.

**Reading.** `_read_exchange` checks that the file records the same `api` and `url` its name was
computed from, and that the body is binary exactly when binary was asked for. Any mismatch stops
the call with "recorded exchange <path> is unusable", naming the file.

## 3. Modes, and how replay refuses

The mode is `settings.hazbrief_http_mode` (`src/hazbrief/config.py`), read once at import.
`tests/conftest.py` sets `HAZBRIEF_HTTP_MODE=replay` before any test imports the package.

| Mode | A request with a file | A request without one |
|---|---|---|
| `replay` | served from the file | refused: `UnrecordedExchangeError` (`_unrecorded`) |
| `record` | served from the file, and not called | called live, then written |
| `live` | called live, nothing written | called live, nothing written |

`fetch_json` and `fetch_bytes` in `src/hazbrief/utils.py` implement the table.

The refusal message names the url and the file it expected ("record it once with
HAZBRIEF_HTTP_MODE=record"). `UnrecordedExchangeError` is an `UpstreamServiceError`, so each tool
handles it as any upstream failure and returns a structured error:

* `population_at_risk` returns `error` (`tools/population_at_risk.py` `count`);
* `facilities_in_footprint` reports one error per source and still answers from the others
  (`tools/facilities_in_footprint.py` `list_facilities`);
* `place.locate` and `ics201_map.basemap` add an entry to `errors`.

No replayed test can reach the network.

## 4. Recording

There are four recorders, one per tool family. Each sets `HAZBRIEF_HTTP_MODE=record` before
importing the package, and each re-run is its own resume: a recorded exchange is served from its
file and never called again. Every recorder runs the same checkpoint plan (standards section 15):

* **Unit and checkpoint.** One exchange, written atomically as it completes.
* **Ceiling.** `--max-calls` wraps the client's live GET (`utils._get_live`, and `_get_live_bytes`
  for HB-11b). The run stops before the call that would exceed the ceiling and exits 3. What it
  recorded stays.
* **Pacing.** `--pace-seconds` between live calls, as a courtesy: none of these services publishes
  a rate.
* **Pilot.** The first scenario's live calls are counted and projected onto the rest before the
  rest run.
* **Progress.** One line per scenario, to stdout and to `logs/<date>_HB-NN_record.log`.

| Recorder | Records | Default ceiling |
|---|---|---|
| `scripts/record_nws_fixtures.py` | NWS points and forecast grid for each point in `scenario_points.yaml` | 8 |
| `scripts/record_population_fixtures.py` | Census and TIGERweb for HB-09's eight scenarios and open water; writes `fixtures/population/expected.json` | 400 |
| `scripts/record_facilities_fixtures.py` | USGS Structures, USGS 3DHP, BTS NTAD for the same footprints (read from `population/expected.json`); writes `fixtures/facilities/expected.json`. With `--scenario ID` (HB-17), the footprint frozen in `fixtures/scenarios/<ID>.json` instead, and no `expected.json` | 150 |
| `record_ics201_fixtures.py (a build tool held privately) record` | TIGERweb place, county and basemap for every scenario in `test_build_ics_201.py (a test held privately)` `SCENARIOS` | 40 |

**The allowlist (HB-11b).** `record_ics201_fixtures.py` runs the whole ICS 201 assembly. It must
record only TIGERweb, so its `gate` admits a live call only to the TIGERweb origin and one of four
paths (`_allowed_paths`):

* `<places service>/identify`;
* `<places service>/<counties layer>/query`;
* `<map service>/export`;
* the map service's description.

Any other call is raised as `UnrecordedExchangeError`, exactly as replay would raise it. No other
tool's fixtures can change, and no Census Data API call is made. First, `_check_listing` records
the Transportation service description once. It then checks that the configured road layer ids
and the vintage are the service's own. That is the one TIGERweb exchange no scenario reads
(`exchanges_in_no_scenario` in the manifest).

The NWS exchanges are read only by the NWS-wind tests (`test_protective_action_footprint.py (a test held privately)`).
Every scenario supplies its wind, so no scenario reads them.

**The recorded grids have expired.** The forecast grids recorded for the four corridor points end
at 2026-10-28T01:00Z (each file's `validTimes`, `fixtures/exchanges/nws/`). A live NWS call
returns only the coming week's forecast. So a call that omits `wind` gets the footprint's "it
does not cover" refusal in two cases: in replay, for an incident time after the recorded grid
ends; live, for any of the frozen scenarios' October incident times. The remedy is one line:
supply `wind` (`speed_kmh`, `direction_deg_from`, `observed_at`, `source`; each scenario file
holds one), or run live with an incident time inside the coming week.

## 5. Expected outputs and frozen forms

**`expected.json`.** Each recorder writes its whole file at the end of a complete run. A ceiling
stop writes nothing. The values are what the recorder's `summary` function keeps: counts, names,
zones and ranks, with no urls and no prose. The tests replay the tool and compare
`recorder.summary(output)` with the file:

* `test_population_at_risk.py (a test held privately)` `test_every_count_reproduces_from_replay`;
* `test_facilities.py (a test held privately)` `test_every_scenario_reproduces_from_replay`.

**Regenerate an `expected.json`** by re-running its recorder. When every exchange is already
recorded, the run makes no call and rewrites the file from replay. Review means reading the
`git diff` of the file and accounting for every changed value in the task's RESULT. Each file has
been written exactly once: `population/expected.json` by HB-09 (commit a85a8b0) and
`facilities/expected.json` by HB-10 (commit 12a264f).

**Frozen forms.** `record_ics201_fixtures.py freeze` runs `build_ics_201`'s `assemble` in replay
for each id in `test_build_ics_201.py (a test held privately)` `FROZEN_FORMS` (`i81-md-pa-line-day`,
`i495-wilson-bridge-night`, and HB-15's unidentified loads `placard-2-3-i81` and
`guide-111-wilson-bridge`). It writes `fixtures/ics201/<id>.md`, which embeds its sketch by the
relative path `<id>.svg`, and `<id>.svg`.
`test_the_frozen_forms_and_sketches_are_byte_stable` compares both byte for byte.

**Review by eye** means rendering the Markdown with its SVG and reading the whole form once, as
the Incident Commander would, before it is frozen. HB-11 RESULT section 4a and HB-11b RESULT
section 4 record that review and print the forms. Re-freeze only when a task changes the form on
purpose. Its RESULT then shows the before and after, and says that the new form was read by eye.

## 6. The scenario manifest (`fixtures/scenarios.yaml`)

**Where the scenarios come from.** `scenario_manifest.py (a build tool held privately)` `scenarios()` takes:

* the 15 incident scenarios in `test_build_ics_201.py (a test held privately)` `SCENARIOS`, the same source the ICS
  201 recorder uses. HB-09's eight are built there from `fixtures/population/expected.json` and
  `scenario_points.yaml`. HB-08's three, HB-08b's two and HB-15's two (a load known only by its
  placard or a guide number) are written there, and their origins are in `EXTRA_ORIGINS`;
* HB-09's open-water footprint, from `population/expected.json`.

**How it is derived.** `derive()` runs in replay only. It runs every registered tool's body on
every scenario: the footprint first, `build_ics_201` last. It wraps `utils._read_exchange` and
`utils._unrecorded` to see which files each tool opens and which requests replay refuses
(`_watch`).

**What a record carries:**

| Field | Holds |
|---|---|
| `id`, `origin` | the scenario, and the task that wrote it (HB-08, HB-08b, HB-09) |
| `incident` | the `IncidentInput` as given, or null for open water |
| `wind` | the `WindObservation` as given |
| `as_given` | the incident time string as given |
| `footprint` | open water only: the polygon given |
| `tools.<tool>.status` | `replayed` (every exchange it asked for has a file), `network_free` (it asked for none), `unrecorded` (replay refused at least one), or `not_run` (the scenario has no input the tool takes) |
| `tools.<tool>.exchanges` | the files the tool read, by api. For `build_ics_201`, only those beyond the tools it runs: the TIGERweb place and basemap |
| `tools.<tool>.unrecorded` | the files replay looked for and did not find |
| `tools.<tool>.expected` | the `expected.json` entries that check the tool (`file#scenario`) |
| `tools.<tool>.frozen` | the frozen form files |
| `gaps` | each `unrecorded` or `not_run` tool, with the reason `fixtures/scenario_gaps.yaml` declares |

The file also counts the exchanges on disk by api, and the ones no scenario reads.

**The gate.** `test_scenario_manifest.py (a test held privately)` re-derives the manifest and asserts that the
committed file is byte-identical. It then applies `coverage_problems`, which fails:

* a registered tool (`FastMCP.list_tools` after `register_tools`) that a scenario does not carry
  (a registered tool with no runner in `scenario_manifest._run` stops `derive` sooner, with
  `ManifestError`);
* a gap with no declared reason;
* a declared reason with no gap behind it.

A new tool or scenario therefore fails the suite until its cells replay or are declared.

**After any change to fixtures or tools:**

```bash
uv run python scenario_manifest.py (a build tool held privately)           # rewrite fixtures/scenarios.yaml
uv run python scenario_manifest.py (a build tool held privately) --check   # exit 1 if stale or a gap is undeclared
```

**Closing a gap.** Record the exchanges with the tool family's recorder, re-derive, and delete the
declaration. The gate then fails until the declaration is gone.

## 7. The eval harness's fixtures (HB-05)

**Snapshots** (`fixtures/scenarios/<scenario>.json`). `eval_harness.py (a build tool held privately)` `regression`
rebuilds every tool on every scenario from replay with the manifest's runners
(`scenario_outputs`) and compares each output with its snapshot (`diff`), naming every changed
path with both values. `build_ics_201`'s snapshot leaves out the six tools it runs, which have
their own cells, and holds its sketch by sha256 (`_canonical`). The same command also compares the
`expected.json` entries through the recorders' `summary` functions and the frozen forms byte for
byte. A change to any tool output fails `test_eval_regression.py (a test held privately)` until it is reviewed and
approved: `regression --approve` rewrites the snapshots, and review means reading their `git diff`
and accounting for it in the RESULT, as for `expected.json` (section 5). A missing snapshot is a
failure, not a pass.

**Live recordings** (`fixtures/exchanges_live/<date>/`). `eval_harness.py live` runs each incident
scenario's `build_ics_201` in `record` mode with `settings.hazbrief_exchanges_dir` pointed at the
dated directory (`live_run`). It never writes `fixtures/exchanges/`, and replay never reads the
live directory. The checkpoint plan is in `live_run`'s docstring. In brief:

* **Calls.** `calls.jsonl` holds one row per live call, made or failed. The ceiling is cumulative
  over every run into one directory.
* **Allowlist.** An API outside `eval/harness.yaml` `live.allowed_apis` is refused, as replay
  refuses it.
* **Drift.** `drift.json` holds two comparisons:
  * per source (`exchange_drift`), each live exchange against the replay exchange for the same
    request, with the url mapped back to the configured default origin;
  * per scenario and tool (`output_drift`), the output replayed from the live recordings against
    the output replayed from the fixtures.

`test_eval_live.py (a test held privately)` runs the command against a local stub that serves the replay fixtures,
kills it with SIGKILL mid-run, and checks the resume. A live recording closes a declared gap only
when it is promoted into `fixtures/exchanges/`, and promotion is a separate, recorded decision.

**Promotion** (HB-15, P-14). `scripts/promote_live_exchanges.py --live <dated dir> --scenario
<id> --tool <tool>` runs the named tools on the named scenarios in replay and copies each
exchange replay refuses that the live directory holds, then runs them again, until a pass copies
nothing (a block query's answer names the next queries). A file is copied byte for byte, with
its as-of headers and `recorded_at`, only if it records the api it is filed under and its url
hashes to its file name; a destination that exists with other bytes stops the run. The live
directory is left whole: its `calls.jsonl` and `drift.json` name the files. The report lists what
was promoted per scenario and api and what replay still refuses. HB-15 promoted 58 files from
`2026-10-21/` (HB-04's 15 `unrecorded` gaps, the five HB-08 and HB-08b footprints) and 15 from
`2026-10-22/` (HB-15's I-81 placard scenario, recorded for it under a 40-call ceiling).
