<p align="center"><img src="docs/assets/hazbrief-mark.svg" width="180" alt="hazbrief logo"></p>

# hazbrief-mcp

An MCP server for the GSA Model Context Protocol Server and SI Agent Government
Hackathon (2026), Dataset Access Server category. Given a transported-hazmat
accident (material, container, location, time), it fuses public federal data into
a structured protective action footprint, a set of sourced flags, and a draft
ICS 201 Incident Briefing. The server never runs a dispersion model: distances trace
to the PHMSA Emergency Response Guidebook (ERG). The server returns structured data
and GeoJSON; the client narrates and renders.

**Who already plans for a release.** Every facility under EPA's Risk Management Program must
analyse and report a worst-case release scenario (40 CFR 68.25; about 11,740 facilities have filed
current plans), and every local emergency planning committee must plan for releases, transport
routes included (EPCRA section 303). hazbrief gives them the same fused picture for a what-if
release: a brief built from a stated wind; a worst-case scenario builder is next, not built (Issue
`d54dbcb8`). The operator also names exercises, pre-incident plans, siting and zoning as uses;
that is his statement, not a held source's (`docs/evidence/hb216/planning_uses.md`).

**The server runs no dispersion model; the application draws a labelled modelled cloud.** The
seven tools run no dispersion model. Every distance a tool returns is a cell of the ERG 2024
tables or guides. No tool result and no ICS 201 carries a modelled value. The `hazbrief brief`
application is a client of the server, not part of it. Beside the ERG footprint, it draws one
modelled cloud by health-effect level (AEGL-3, AEGL-2 and AEGL-1) from the one engine a held
criterion names for the release: the critical Richardson number of NOAA's NOS OR&R 43 classes the
release dense, passive or not classed
(DN-026).
A dense release is drawn by SCICHEM, run in a separate models image on the forecast wind hour by
hour (DN-028);
by day, where no hour of the brief's horizon is a stable class, SLAB runs beside it as its second method, a layer off by default on one wind, and where
the two disagree beyond the held factor of three, the checklist carries one warning with both results; that is the rule, and no committed brief meets its condition, so no committed brief raises the warning (Issue afab181e; HB-189; HB-173). Where any hour of the brief's horizon is a stable class, as at night or where an afternoon release runs into the evening, the moving cloud is the primary layer: SCICHEM's run by level, hour by hour, at a stated 1.25 m vertical setting, an approximation that is not converged, held as a frame every 15 minutes of cloud time on a coarse mesh whose level outlines are drawn from it, each frame shown as it is computed, with one Play control off by default (DN-024 ADDENDUM-01; HB-192); SLAB checks how far, its area drawn to where a level closes or to the release hour's wind's travel in the horizon and 30 percent over, a dashed outline with no times beside the filled cloud; counts and candidate blocks are stated for AEGL-3 and AEGL-2, every time is the 1.25 m run's and no warning is raised (HB-189). Each engine's conditions of use are a section of the brief's TEVV page. The benchmark requirement is another, Benchmarks and requirement: its minimum, its objective and hazbrief's status against each published benchmark: on Jack Rabbit II Trial 7's five arcs at 0.2 to 5 km, where by the one-minute rule its SCICHEM run is within a factor of two of the measured arc maximum at 1 arc and its SLAB run at 4, against 3 and 4 for HPAC's two published runs and 3 for ALOHA's; against the measurements its SCICHEM run is below them, a difference that is statistically significant at the 95 percent confidence level (MG 2.88, 95 percent limits 1.58 to 5.27), and no other run's difference from them is statistically significant at that level; against the tools no hazbrief run's difference in mean bias is statistically significant at the 95 percent confidence level (one trial, five arcs of one release; `docs/evidence/hb212/states.tsv`); not yet evaluated on the others (HB-206; HB-209; HB-212; HB-213); the accepted tools are named there and on no map page (HB-192). A passive release is
drawn by a first-order passive Gaussian puff that starts on its release hour's wind and is then
carried on each later forecast hour's wind (a stated or observed wind is one wind for every hour),
by level like the dense cloud
(DN-025);
it is not a dense-gas model, and no committed brief is passive. A release the criterion cannot
class draws neither and says why, and nothing from an engine the criterion did not name is drawn.
Each modelled layer has a section on the brief's TEVV page; none of the modelled layers is
validated against observations of a release; the two dense engines, as hazbrief runs them, are compared with the measured arc maxima of stable dense field trials at 212 to 800 m: SLAB within a factor of two at all 10 (four trials), SCICHEM below 7 of 8 (three trials) by a factor of 1.8 on geometric average when scored as its authors score a peak, and its mean, which the brief draws, below all 8 by a factor of 3.5 at the shipped 250 m setting; at the 1.25 m setting a stable brief now runs, every trial arc still reads below the measurement (HB-187) (`docs/evidence/hb159/tevv_rows.md`; `docs/evidence/hb176/summary.tsv`; `docs/evidence/hb177/hb176_restated.tsv`). The ERG
footprint is the protective action distance.
Every ERG guide is routed: where its chemistry takes a release model, the modelled layers apply;
where it does not (explosives, radioactive materials, oxidisers, solids and others), the brief
says so in the guide's own words and draws neither (`packs/release_routing.json`).
Smoke from a fire is a future use: a fire brief names the VSMOKE layer and draws no band,
because no held open engine builds and reproduces its manual's example (HB-150; operator
decision of 2026-11-09).
The container image ships the server alone,
without the modelled layers' code or packs.

**Deliverables** (the three GSA asks for):

| Deliverable | Where |
|---|---|
| Repository | this one; start at [Run](#run), then [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| Slide deck | [`docs/submission/pitch_deck.pdf`](docs/submission/pitch_deck.pdf) (the pitch, 15 slides: problem statement, solution overview, technical approach and key decisions, demonstration) and [`docs/submission/pitch_deck.html`](docs/submission/pitch_deck.html) (the same slides; self-contained) |
| Technical appendix to the deck | [`docs/submission/deck.pptx`](docs/submission/deck.pptx) (GSA's template; self-contained) and [`docs/submission/deck.html`](docs/submission/deck.html) (the same slides; needs network for reveal.js): the evidence behind each pitch slide, every number and quote traced to a file |
| Evaluation document | [`docs/submission/EVALUATION.md`](docs/submission/EVALUATION.md); its results at a glance are at the top |

**Status:** all seven DN-001 tools are registered (below). Scope, invariants and
the task order are in DN-001
and DN-005.

## Tools

| Tool | Returns | Data source | As-of |
|------|---------|-------------|-------|
| `assess_incident` | ID number, names, ERG guide, TIH, hazard class rule set, 49 CFR 172.101 class and labels, CAMEO datasheets, which ERG table applies, day or night with sunrise and sunset, source tags; for a load with no ID number or name, the guide its placard sends it to (or the guide number given) and how | ERG 2024 with its Table of Markings, Labels and Placards, 49 CFR 172.101, CAMEO (packs); sunrise and sunset calculated (NOAA solar equations) | `pack_versions`; no network call |
| `protective_action_footprint` | GeoJSON initial isolation zone (circle) and, for a Table 1 material, protective action zone (downwind square); fire isolation circle; distances in metres and as the ERG prints them; the table row; the wind used and its band. A load the ERG answers with several candidates (a name under two ID numbers, an ID number under two guides, a placard several rows match) is drawn once per candidate, the one with the largest distances marked governing, with the `ambiguous_material` flag | ERG 2024 (packs); wind from the caller or the NWS forecast grid (api.weather.gov) | the wind's `as_of` and the NWS response headers |
| `population_at_risk` | Inside a footprint (or any polygon): nighttime residents and group quarters by type and block; daytime jobs; people 65 and over, people with a disability, households with no vehicle, limited English speaking households, group quarters population, each with a derived margin of error; the CRE count of people with three or more vulnerability components; which count the period makes primary; the flag-rule inputs; `limits` | TIGERweb 2020 tabulation blocks, block groups, tracts; 2020 Census DHC P1, P18 (block); ACS 2020-2024 5-year (block group or tract); LEHD LODES8 WAC 2023 (cached state files, `scripts/fetch_lodes.py`); CRE 2024 (tract). Area-weighted allocation; derived MOEs by the ACS Handbook and OnTheMap EM rules. Requires `CENSUS_API_KEY` | each count's `as_of`; `basis` source tags |
| `facilities_in_footprint` | Inside a footprint: schools and colleges, hospitals, nursing homes, fire/EMS, ambulance and police stations (each with zone, source id, as-of); waterways with length or area inside and whether any touches the isolation zone; rail segments (owner, length inside) and at-grade crossings (crossing id); the flag-rule inputs; sourced `limits`; a failed source is reported and the others still answer | USGS National Structures Dataset; CMS Nursing Home Provider Information (cached); USGS 3DHP flowlines and waterbodies; BTS NTAD North American Rail Network Lines and FRA Railroad Grade Crossings | each facility's `as_of`; `basis` source tags |
| `receiving_hospitals` | Hospitals with emergency services outside the footprint, nearest first by straight-line distance from the footprint's upwind edge: beds, type, distance, bearing, and whether the straight line from that edge crosses the protective action zone; hospitals inside the footprint listed apart as casualty sites; `limits` (straight-line, not drive time; no trauma level or burn capability) | CMS Hospital General Information joined to CMS Provider of Services beds on the CCN, placed by the Census Geocoder and, where it fails, the USGS Structures hospital at the same address (cached, `scripts/fetch_cms.py`; 94.4 % placed) | `basis` source tags (CMS release dates) |
| `material_response_guidance` | The material's ERG orange guide by section (potential hazards, public safety, emergency response), every line as printed with its PDF page, marked as a quotation; selected by the incident (fire subsection first and the guide's fire evacuation when fire is involved; the Small or Large Spill lines by spill size; the "(P)" sentence only for a P guide; the Table 2 note for a water-reactive material spilled in water), every line left out named with its reason; the General First Aid section the guide refers to, with its page | ERG 2024 orange guides (packs) | `pack_versions`; no network call |
| `build_ics_201` | A draft FEMA ICS Form 201, block by block in the form's numbering: 1 Incident Name (material, place or county, state, date); 3 Date/Time Initiated with day or night; 4 Map/Sketch, an SVG sketch (footprint, wind arrow and speed, facilities, crossings, receiving hospitals, county line, scale bar, north arrow over TIGERweb roads) plus the same features as GeoJSON, and the ERG app link; 5 where the spill is, the material and its distances, at most ten fired flags (high first; each names the value it fired on, then its ERG consequence and response), population, facilities, and the limits that change how those numbers read; 6 the server and pack versions; 7 the ERG protective action sentences; 10 the nearest five receiving hospitals as a table. Annex A lists every limit and every source with its as-of. Blocks 2, 8 and 9 and the names and signature are left blank for the Incident Commander. Every sentence and table row carries receipts (a tool output path with its value, or an ERG page). By default (`response_format: concise`) the tool returns the Markdown form, every sentence with its source tag, and the GeoJSON, which fits an MCP client's cap on a tool result (Claude Code's is 25,000 tokens by default); `detailed` adds the blocks with their receipts, Annex A and the fired flags, and `block` returns them a part at a time; `include_map_svg` adds the SVG sketch, which puts the result over that cap. Block 3 prints local time beside UTC, in the zone NWS gives for the spill point; an unresolved load is named by its candidates in Block 1 and Block 5, and the sketch dashes the non-governing ones | the six tools above, run on the incident, and the flag rules over their outputs; TIGERweb places and counties (`tigerWMS_Current`) and roads (`Transportation` export); the held ICS 201 form's block list (`src/hazbrief/ics201.yaml`). No model writes any sentence | each sentence's source tag; Annex A |

Every ERG ID number resolves with its ERG rows (Tables 1 to 3 and its guide); CFR rows,
CAMEO and the hazard class rule set are packed for the eight seed materials (UN1005,
1017, 1075, 1202, 1203, 1951, 1977, 1978), and any other ID returns `coverage: erg`. A
load with no ID number or name is given by its `placard` instead of `material`:
the class or division printed on it (2.3), a word printed on it (OXYGEN), DANGEROUS, or
none when no placard can be seen. The ERG's Table of Markings, Labels and Placards
(keyed into the pack by two keys) sends it to a guide, or the caller gives
`guide_number` (111, Mixed Load/Unidentified Cargo; 112 and 114, explosives). The tools
then run that guide, draw its circles, and say that Table 1 needs the material. The
explosives the yellow index lists by name with no ID number ("Blasting agent,
n.o.s.", "Ammonium nitrate-fuel oil mixtures", which answers to ANFO by 49 CFR 173.59,
and the two division rows) are given as `material` and take the same guide branch
(`coverage: unnumbered`). A generic name answers without its ", n.o.s.". An input
the ERG cannot answer returns `error` with a `hint`, never a guess. No tool runs a dispersion
model.

## Run

Install, then check that the suite and the linter pass:

```bash
git clone https://github.com/brockwebb/hazbrief-mcp.git
cd hazbrief-mcp
uv sync --group dev
uv run pytest tests/ -q -n auto --maxprocesses 6 --dist loadfile
uv run ruff check .
```

### Connect an MCP client

The server speaks MCP over stdio. A client starts it with `uv run python main.py` in the
repository. Replace `/path/to/hazbrief-mcp` below with the absolute path of your clone.

Claude Code, one line:

```bash
claude mcp add hazbrief -- uv run --directory /path/to/hazbrief-mcp python main.py
```

Claude Desktop, in `claude_desktop_config.json` (or any client that takes an `mcpServers` block):

```json
{
  "mcpServers": {
    "hazbrief": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/hazbrief-mcp", "python", "main.py"]
    }
  }
}
```

MCP Inspector, to call the tools by hand from a browser:

```bash
npx @modelcontextprotocol/inspector uv run --directory /path/to/hazbrief-mcp python main.py
```

The client lists seven tools. One call: a large chlorine spill from a rail tank car near Point
of Rocks, Maryland, on an October afternoon. `assess_incident` needs no key and no network.

```json
{
  "incident": {
    "material": "UN1017",
    "container": "Rail tank car",
    "location": {"latitude": 39.2756, "longitude": -77.5394},
    "incident_time": "2026-10-21T14:00:00-04:00",
    "spill_size": "large",
    "fire_involved": false
  }
}
```

The first fields of its result, as the server returned them, abridged. `basis` gives each part
of the answer a source tag and a page locator.

```json
{
  "coverage": "full",
  "material": {"un_number": "1017", "id_number": "UN1017", "names": ["Chlorine"], "matched_name": null},
  "guide": {"number": "124", "title": "Gases - Toxic and/or Corrosive - Oxidizing"},
  "tih": true,
  "erg_table": {
    "table": "Table 3",
    "spill_size_used": "large",
    "container": "Rail tank car",
    "also_guide_fire_distances": false,
    "reason": "Large spill of UN1017: Table 1 refers to Table 3, the rail tank car row."
  },
  "day_night": {"period": "day", "sunrise": "2026-10-21T07:26:25-04:00", "sunset": "2026-10-21T18:22:26-04:00"},
  "hazard_class": {"class_id": "tih_gas", "title": "toxic inhalation hazard gases", "rule_set_id": "rules.tih_gas"},
  "basis": [
    {"supports": "ID number, names and guide", "tag": "[ERG 2024 yellow index, UN1017]", "locator": "erg2024-en-pdf#p31"}
  ]
}
```

`protective_action_footprint` and `build_ics_201` take the same `incident` object. Ask the
client for the footprint and the ICS 201 on the same spill. Give them a `wind` beside the
incident too, for example `{"speed_kmh": 13, "direction_deg_from": 270, "observed_at":
"2026-10-21T13:40:00-04:00", "source": "worked example wind"}`. Without one, the footprint reads
the NWS forecast grid, which covers only the coming week, so an October 2026 incident time gets
the refusal "it does not cover". The grids recorded for the frozen scenarios ended on
2026-10-28 ([`docs/FIXTURES.md`](docs/FIXTURES.md)). Supply `wind`, or run live with an incident
time inside the coming week.

### Over HTTP, in a container

The image every HTTP deployment uses (`Dockerfile`) serves `/mcp`, `/health` and `/version` on
port 8080. Create `.env` first: `docker run --env-file` refuses to start without the file.

```bash
cp .env.example .env            # then set CENSUS_API_KEY in .env for the population tools
docker build -t hazbrief-mcp .
docker run --rm -p 127.0.0.1:8080:8080 --env-file .env hazbrief-mcp   # http://localhost:8080/mcp
```

The HTTP route has no authentication, so it is local only: the server binds 127.0.0.1, the
container's port is published on 127.0.0.1, and `server.json` lists no remote
([`docs/SECURITY.md`](docs/SECURITY.md), "The HTTP route's exposure").

Without Docker, set `MCP_TRANSPORT=streamable-http` (or let the host inject `PORT`).

### The application: one brief from the seven tools

The `hazbrief brief` application calls the seven tools as an MCP client and writes one brief,
every value labelled, with an evidence appendix beside it
([`docs/OPERATIONS.md`](docs/OPERATIONS.md)). It runs from a clone, not from the container
image. To start it and reach its start page (HB-208):

```bash
uv run hazbrief brief --serve
```

The start page, at http://127.0.0.1:8790/, has two parts. The first lists the prepared
scenarios that have a recorded brief: the place, the material by its ERG name and ID number,
the container, the time the run is for and whether it is day or night, each read from the
scenario's record. "Open the recorded run" serves that brief as committed, under a banner that
says it is a replay and gives the recording's date. "Run it with today's conditions" copies the
scenario's material, container, quantity and place into the entry form, with now as the start
time and today's forecast as the weather; every field can be changed, the place included,
before Build. The second part, "Enter a new incident", is the entry form. One server serves one
brief: stop it with Ctrl-C and start it again for another.

Each brief can also be written or served on its own:

```bash
uv run hazbrief brief docs/briefs/csx-point-of-rocks-day/scenario.json --out /tmp/brief            # live
uv run hazbrief brief docs/briefs/csx-point-of-rocks-day/scenario.json --out /tmp/brief \
  --replay --now 2026-10-26T12:00:00Z --no-google                                                  # from the stores
uv run hazbrief brief docs/briefs/csx-point-of-rocks-day/scenario.json --serve \
  --replay --now 2026-10-26T12:00:00Z --no-google                                                  # the live page
```

`--serve` writes no file. It serves the brief's live page at http://127.0.0.1:8790/ (loopback
only) and opens it, unless `--no-open` is given. The sections arrive as they settle, and the
finished page checks its hash against the static `brief.html`. Ctrl-C stops it.

The live page's display is one person's design from experience. Improving it needs design
sessions and testing with responders; the aim of this version is that a capable person put in
the chair can do a good enough job with it, and that what it shows is believable.

The `--replay` line uses the flags `docs/OPERATIONS.md` uses, so its `brief.html` equals the
committed `docs/briefs/csx-point-of-rocks-day/brief.html`: `--now` fixes the instant the labels'
staleness is judged at, and `--no-google` draws the map with the vendored Leaflet, never a Google
key.

Each brief writes `tevv.html` beside `brief.html`: its test, evaluation, verification and validation page, one
section per thing the brief draws or states from a method. A reference number such as T7 at the end of a layer's row
or popup opens that section; the same number means the same section on every brief (HB-161).

Each brief also writes `timeline.html` and `timeline.csv` (HB-171, DN-029). The timeline is evidence and the exercise
events list, not the commander's decision view (DN-029 ADDENDUM-00 decision 6). Where the modelled cloud is drawn, the
Timeline page lists what it reaches and when, in time order: one row per place and health-effect level, with the
expected occupancy for that kind of place at that hour (from typical hours, sourced or marked assumed), what held
sources say to consider (quotations with their pages), and who can confirm it. The brief's first view shows the next
three rows; selecting one moves the time control to that moment. `timeline.csv` is the same record as an exercise
events list in HSEEP's MSEL columns, marked EXERCISE, with the planner's columns left empty. Where no cloud is drawn
the page says why in one line.

### The models image (optional)

The application's dense-gas client runs SLAB in a second image, `hazbrief-models`
(`deploy/models/`). The server never uses it, and the two commands above are unchanged without
it. The build compiles SLAB from the held archive, which it checks by sha256. It runs SLAB's
four test cases and fails if any differs from the distributed output beyond one unit in the third
significant figure. Fetch the archive first (`corpus/sources.yaml`, id `epa-slab-code`):

```bash
sh deploy/models/build.sh                       # reads corpus/raw/epa-slab-code.zip; tags hazbrief-models
docker run --rm -i --network none hazbrief-models < deck > predict   # one SLAB run; it opens no port
```

Without the image, the client returns an `error` with this hint. For development,
`HAZBRIEF_SLAB_BIN` can name a local SLAB binary instead
([`docs/SECURITY.md`](docs/SECURITY.md) section 11 has SLAB's licence terms).

The same image builds EPRI's SCICHEM 3.4 (HB-167, DN-028), the engine for a dense release once HB-163 draws
it. `build.sh` first fetches what that build needs into `~/.cache/hazbrief/` (`deploy/models/scichem/fetch_source.sh`:
EPRI's repository at a pinned commit by git, its land-use table by sha256), and the build checks the engine against
EPRI's own Intel build before the image is tagged. Its runs are held in `fixtures/evidence/scichem_runs/`; nothing in a
brief reads them yet.

A live brief runs SLAB and writes its run into the evidence store. A replayed brief
(`--replay`, and every committed brief) reads each run from `fixtures/evidence/slab_runs/`,
keyed by the input deck's sha256, and never starts SLAB. So the committed briefs rebuild byte
for byte on a machine without the image. Set `HAZBRIEF_SLAB_RECORD=1` to record a run a
replayed brief does not hold yet (HB-112).

### The key

The Census Data API has required a free key for data requests since May 2026; get one at
https://api.census.gov/data/key_signup.html and set it as `CENSUS_API_KEY`. Every tool but
the live population tools works without it, and a recorded run replays with no key.
Without it those tools return a structured error carrying the signup URL. No other key
is required (DN-003 section 1). `uv run python scripts/census_key_check.py` makes one
real data request (one county, `scripts/census_key_check.yaml`) and says whether the key
works; a request without a key is redirected to the API's "Missing Key" page
(`docs/evidence/hb215/census_key.tsv`).

## Evaluation

`eval_harness.py (a build tool held privately)` (HB-05; settings in `eval/harness.yaml`; method and first results in
LN-05). The
evaluation document, with every number traced to a committed file, is
[`docs/submission/EVALUATION.md`](docs/submission/EVALUATION.md).

* **A, invariants** (no network): every ERG ID number and name, every Table 1 and Table 3
  cell, every material and guide, every flag rule by MC/DC. Every distance in the outputs
  traces to its pack cell. The latest run (2026-10-25, at `cb44517`, committed as
  `eval/reports/2026-10-25_invariants.json`): 24,846 footprints reaching all 3,374 pack cells,
  62 of 62 guides, 106,174 distances traced, no failure. `eval/known_findings.yaml` lists no
  open part A finding (`findings: {}`). Its `agent_findings` key carries one agent-evaluation
  finding, A-11: one model wrapped a request twice, the cause is not established, the server now
  refuses that shape with a hint, and two follow-ups are left for after the submission.
* **B, regression** (no network): 18 scenarios, 7 tools: 121 scenario-tool outputs, 26
  `expected.json` entries and 12 frozen files compared; 0 differences. That is the `line` of
  `eval/reports/2026-10-25_regression.json`, the committed summary of the report the command
  below writes to `logs/` (gitignored; re-run it to check). HB-34 ran it again inside the
  container image with no network.
* **C, live drift** (network, recorded, ceilinged): the first run (2026-10-21, 120 calls)
  found no data drift in any source: of 61 exchanges with a replay baseline, 59 unchanged and 2
  Census CRE tables reordered. It recorded the five footprints HB-04 lists as gaps, and found and
  fixed an ICS 201 crash that replay could not reach. The 2026-10-25 run
  (`eval/reports/2026-10-25_live.json`) called NWS for the first time and found no drift in any
  field the server reads, but it compared only 8 of the 17 scenarios' outputs: it stopped at its
  ceiling of 120 calls (`"exit": 3`), and the other 9 are `"complete": false`.

```bash
uv run pytest -m slow test_eval_invariants.py (a test held privately)       # A (before a release; by hand in CI)
uv run python eval_harness.py (a build tool held privately) invariants          # A, with its report in logs/
#   add --commit-report to any of A, B, C to write the summary under eval/reports/ (a clean tree only)
uv run python eval_harness.py (a build tool held privately) regression          # B (also in the default test gate)
uv run python eval_harness.py (a build tool held privately) live                # C: needs CENSUS_API_KEY; at most 120 calls
```

## Configuration

Settings come from two dotenv files, layered (DN-004):

1. `~/.secrets/master.env`: the operator's one secrets file, outside every repository
   (mode 600). Set `HAZBRIEF_MASTER_ENV` to use another path. A path set that way must
   exist, but the default may be absent.
2. `.env` at the repository root: this project's values and overrides (gitignored). It
   is found from the package, not the working directory, so a client that launches the
   server from elsewhere (Claude Desktop, MCP Inspector) still reads it.
   Copy `.env.example`, which names the key, with its signup URL, and the settings
   an operator usually sets. Every setting in `config.py` can be set by the variable of its
   name.

The project file wins over the master, and an exported environment variable wins
over both. A variable left blank (`CENSUS_API_KEY=`) is ignored, so a copied
`.env.example` does not hide a master key. `.envrc` does the same layering for
[direnv](https://direnv.net/) shells.

A container never receives the master file. `.dockerignore` excludes `.env`, and the
container gets only the variables `.env.example` names, by `docker run --env-file`
or the platform's secret store.

## Data sources and attribution

The notices each source's terms ask for (DN-003 section 2; the same text the server
serves as its `attribution` resource, `docs/stylebook/ATTRIBUTION.md`). No agency
named here endorses, certifies or is affiliated with this server, and none of their
logos or seals is used.

- **U.S. Census Bureau.** This product uses the Census Bureau Data API but is not
  endorsed or certified by the Census Bureau. Daytime worker counts come from LEHD
  Origin-Destination Employment Statistics (LODES); requested citation form:
  U.S. Census Bureau, "{File Name}," LEHD Origin-Destination Employment Statistics,
  {Vintage}, https://lehd.ces.census.gov/data/lodes, accessed on {Date}. Boundaries
  come from the Census TIGERweb services. Source: U.S. Census Bureau.
- **U.S. Geological Survey.** Facility locations come from The National Map
  Structures service. Credit: U.S. Geological Survey. USGS-authored or produced data
  are in the U.S. public domain.
- **National Weather Service.** Wind at the incident point comes from the National
  Weather Service API (api.weather.gov). NWS web content is in the public domain
  unless specifically noted otherwise, and is provided as is. No endorsement by or
  affiliation with NOAA or the NWS is implied.
- **Centers for Medicare & Medicaid Services.** Licensed bed counts come from the CMS
  Provider of Services data (data.cms.gov). Works of the U.S. Government are in the
  public domain; no government endorsement is implied (42 U.S.C. 1320b-10).
- **Emergency Response Guidebook.** Initial isolation distances, protective action
  distances and guide text come from the Emergency Response Guidebook 2024 (ERG2024),
  U.S. Department of Transportation, Pipeline and Hazardous Materials Safety
  Administration. The server reproduces table values and guide text without
  modification.

Each knowledge pack in `packs/` also carries its own `attribution` block: a credit per
source document and the source's reuse notice verbatim (ERG 2024 p. 382 "Reproduction
and resale"; the CFR edition notice on NARA's seal; the CAMEO Chemicals site owner).
See [`packs/SCHEMA.md`](packs/SCHEMA.md).

## The knowledge base

The server's knowledge base is the exported packs in `packs/`: plain JSON files, read at
run time with no database, no Neo4j and no Squiddy (DN-001 invariant 3). They were built
by `scripts/build_packs.py` from a corpus of held source documents. The corpus graph and
the held source texts are not redistributed; what ships is each source's identity,
[`docs/sources/manifest.tsv`](docs/sources/manifest.tsv): one row per document, with the
URL it was taken from and the sha256 of the bytes held, so any document can be fetched
again and checked against it.

To open a pack, read it as JSON:

```bash
uv run python -c "import json; p = json.load(open('packs/erg.json')); print(sorted(p))"
```

Each pack's format is in [`packs/SCHEMA.md`](packs/SCHEMA.md) and its JSON Schema in
`packs/schema/` (for example `packs/schema/erg.schema.json`); its `attribution` block names
the source documents it was built from.

## Documents

* [`AGENTS.md`](AGENTS.md): for a model asked to review the project: what it is, where each
  part is, how to run it, where each claim's evidence is, and what not to assume.
* [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): the system as built: the runtime, the packs
  and how they are built, the live sources and their as-of, the flag rules, the ICS 201, the
  evaluation, and where the code departs from the design notes. Read it first.
* [`docs/REQUIREMENTS_TRACE.md`](docs/REQUIREMENTS_TRACE.md): every DN-001 scope, invariant,
  data source and tool requirement, and the GSA judging criteria, each with what satisfies it,
  what checks it and its state.
* [`docs/SECURITY.md`](docs/SECURITY.md): the trust boundary, secrets, input validation, result
  size, what the model never decides, and what is not done.
* [`docs/OPERATIONS.md`](docs/OPERATIONS.md): the runbook: run the server, run a brief live or
  from the stores, read a record, the appendix and a degraded section, and add a channel.
* [`docs/submission/EVALUATION.md`](docs/submission/EVALUATION.md): the hackathon evaluation
  document: testing methodology, performance metrics, security, lessons and recommendations.
* [`docs/FUTURE_WORK.md`](docs/FUTURE_WORK.md): the known limits of what ships, each with the
  files that show it, and the future work, each with its Issue; generated from the graph by
  `future_work.py (a build tool held privately)`.
* [`NOTICE`](NOTICE): the licences and notices of everything the repository ships or builds,
  generated from the held records by `scripts/notice.py`.
* design: the design notes, DN-001 (scope) to DN-030, with their addenda.
* lab: the lab notes, LN-01 to LN-12: the prior-art harvest, the ERG
  findings, the eval harness (LN-05), the agent evaluation (LN-07), the concept layer (LN-08) and
  the corpus-claim work.
* [`packs/SCHEMA.md`](packs/SCHEMA.md) and [`docs/FIXTURES.md`](docs/FIXTURES.md): the pack
  format and the fixture format.

## Layout

The server is `main.py` and `src/hazbrief/`, reading `packs/`, `docs/stylebook/` and the
`fixtures/lodes/` and `fixtures/cms/` caches; the working record is `cc_tasks`, `a session handoff (held privately)`,
`docs/evidence/` and `the event log of the graph (held privately)`; the Squiddy corpus graph (`the corpus graph (held privately)`), the Seldon
graph database and the Squiddy kit are build-time only, and the server never reads them.

| Path | What |
|------|------|
| `src/hazbrief/` | The server: `app.py` (thin entry point), `tools/`, `prompts/`, `resources/` (one module per item, each with `register(mcp)`), `config.py`, `models.py`, `utils.py`, `routes.py` |
| `src/hazbrief/evidence/`, `src/hazbrief/brief/` | The application, a client of the server that the server never imports: the evidence store, source catalog, recording client and labels; the orchestrator and the `hazbrief brief` CLI (`docs/ARCHITECTURE.md` section 11) |
| `evidence/` | The committed evidence seeds, `seed/` (the recorded exchanges), `seed_calls/` (seven tool calls) and `seed_briefs/` (the other scenarios' calls, HB-45); `store/` is the local, gitignored working store |
| `docs/briefs/` | The application's output: one committed brief per fixture scenario that replays end to end, each with its appendix, which cites the records that brief read, and the scenario it was built from: the workbench map, first actions and sections, the labelled modelled cloud where the release takes one, and its TEVV page, `tevv.html` (`scripts/build_scenario_briefs.py`) |
| `packs/` | Exported knowledge packs (no database at runtime). The server reads seven: `erg`, `cfr172`, `cameo`, `hazard_classes`, `flag_rules`, `vocabulary`, and `suggested_actions`, the table the `decision_support` prompt carries; the application alone reads five, the puff's `materials_properties`, `sigma_curves`, `release_scenarios`, the modelled tier's `release_routing` and the siting layer's `siting_rules`, which the image leaves out. `*.json` built by `scripts/build_packs.py` from the held corpus, `schema/` (JSON Schemas), `src/` (build config, flag rules, vocabulary), [`SCHEMA.md`](packs/SCHEMA.md) |
| `corpus/` | Source document list (`sources.yaml`), the host allowlist, the API catalog and probe log, fetch configuration and logs; binaries in `corpus/raw/` are not committed. The document manifest (url + sha256) is the Squiddy graph's, `docs/sources/manifest.tsv`; its public form is `docs/sources/manifest.tsv` (`sources_manifest.py (a build tool held privately)`) |
| `scripts/` | Build-time tools: the allowlisted fetcher, the corpus ingest, the pack builder, the cache fetchers, the fixture recorders, the evaluations, the deck builder and the evidence seed scripts |
| `fixtures/scenarios/` | Frozen synthetic scenarios for network-free eval replay |
| `fixtures/exchanges/` | Recorded upstream exchanges (one JSON file per request) that tests replay; recorded once in `record` mode by `scripts/record_nws_fixtures.py`, `record_population_fixtures.py`, `record_facilities_fixtures.py` and `record_ics201_fixtures.py`, and promoted from live runs by `scripts/promote_live_exchanges.py` (DN-005 section 2) |
| `fixtures/scenario_points.yaml` | The four corridor points the NWS exchanges were recorded for |
| `fixtures/scenarios.yaml` | The scenario manifest: every scenario's inputs as given and, per tool, whether it replays; derived by `scenario_manifest.py (a build tool held privately)`, gated by `test_scenario_manifest.py (a test held privately)`; gaps declared in `fixtures/scenario_gaps.yaml`. The fixture format: [`docs/FIXTURES.md`](docs/FIXTURES.md) |
| `design` | Design notes and architectural decisions |
| `docs/stylebook/` | Commander stylebook (shipped as an MCP prompt and resource) |
| `eval/` | Eval harness settings (`harness.yaml`) and filed findings (`known_findings.yaml`); the template's Databricks agent eval kit (`databricks/`) |
| `deploy/` | Deployment kits from the template (IBM Code Engine, Databricks); the cloud.gov manifest is the root `manifest.yaml`; `deploy/models/`, the optional models image, which builds SLAB (HB-111) and SCICHEM (HB-167) from source |
| `cc_tasks` | Claude Code task specifications |

## Origin

The server skeleton (`main.py`, `pyproject.toml`, `requirements.txt`, `Dockerfile`,
`manifest.yaml`, `server.json`, `.env.example`, `.github/workflows/ci.yml`,
`src/hazbrief/`, `tests/`, `eval/`, `deploy/`) is adapted from
[GSA-TTS/mcp-hackathon-template](https://github.com/GSA-TTS/mcp-hackathon-template)
at commit `6e5fb39b4de044de4f39950ded44fa128416f11a`, with the package renamed from
`example_server` to `hazbrief` and the example tool, prompt and resource removed.
The template is MIT licensed; its license is kept verbatim in
[`LICENSE-TEMPLATE`](LICENSE-TEMPLATE).

## License

The project's code, packs, scripts and documents are MIT licensed: [`LICENSE`](LICENSE), the
`license` field of `pyproject.toml`. Vendored code keeps its own license (Leaflet,
`src/hazbrief/brief/vendor/leaflet-1.9.4/LICENSE`). The source documents the packs are built
from keep their own terms (see [Data sources and attribution](#data-sources-and-attribution)).
[`NOTICE`](NOTICE) gathers every licence and notice in one file, each from its held record:
Leaflet's, the FGDC symbols', SLAB's and SCICHEM's (built only in the optional models image), and
the terms of every public source.
