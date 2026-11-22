# Operations

**Task:** `HB-42` (HB-42).

The runbook for the server and the application that calls it. Every command here was run at the
commit that wrote this page. The design is in [`ARCHITECTURE.md`](ARCHITECTURE.md) (section 11 for the
application), the controls in [`SECURITY.md`](SECURITY.md).

## 1. Run the server

```bash
uv sync --group dev            # install (runtime + dev)
uv run python main.py          # the MCP server, stdio
```

`uv run hazbrief` does the same: the console script runs the server for any argument but `brief`
(`src/hazbrief/command.py`). The container runs `python -m hazbrief.app`. The population tools need
`CENSUS_API_KEY` (free, `https://api.census.gov/data/key_signup.html`). Without it they return a
structured error with the signup URL, and every other tool works.

## 2. Run a brief

**From the stores, with no call.** This rebuilds a committed brief byte for byte:

```bash
uv run hazbrief brief docs/briefs/csx-point-of-rocks-day/scenario.json \
  --out docs/briefs/csx-point-of-rocks-day --replay --now 2026-10-26T12:00:00Z --no-google
```

Every fixture scenario that replays end to end has one, under `docs/briefs/<id>/`. Rebuild them all
(recording any call the scenario-brief seed lacks), or check them against a fresh build:

```bash
uv run python scripts/build_scenario_briefs.py
uv run python scripts/build_scenario_briefs.py --check
```

**Live.** This spawns the server over stdio and makes the seven tool calls through the recording
client:

```bash
uv run hazbrief brief docs/briefs/csx-point-of-rocks-day/scenario.json --out /tmp/brief
```

**The input.** A scenario JSON holds `incident`, `wind` (optional), `as_given` and `id`. A scenario
snapshot, `fixtures/scenarios/<id>.json`, resolves through `fixtures/scenarios.yaml`.

**The output, in `--out`:**
* `brief.html`, one file. It is rewritten as each section settles, so the first thing written is the
  map. The first screen is the workbench (HB-45): the map full screen under the EXERCISE banner, the
  scenario, its as-given time and each section's state; the first actions (the footprint's distances
  and the orange guide's public-safety lines) and the layer list beside it. The sections follow,
  collapsed; a state in the header opens its section.
* **The basemap.** With `GOOGLE_MAPS_API_KEY` set in the application settings (`.env` or the master
  file; `src/hazbrief/brief/settings.py`, never the server's), the map is the Google Maps JavaScript
  API. The key is written into the page, so restrict it by HTTP referrer. Without it, or with
  `--no-google`, or when Google does not load, the map is Leaflet (inlined in the page) over the USGS
  National Map, with OpenStreetMap as a second base layer. With no network every layer still draws;
  the map says the tiles did not load and switches on the TIGERweb roads image Block 4 drew. The
  committed briefs are built with `--no-google` and carry no key.
* `appendix.html` and `appendix.txt`, the evidence appendix.
* A status line per section on stdout, with its state and the seconds it took to settle.

The exit code is 0 when every section rendered and 2 when any degraded.

**Where the records go.**
* A live run writes them to `evidence/store/` (gitignored), or to `HAZBRIEF_EVIDENCE_STORE` if it is
  set.
* `--replay` reads `evidence/seed_calls/`, `evidence/seed_briefs/` and `evidence/seed/`.
* `--now` holds the instant the labels are read at. Without it, the wall clock is used.

To exercise the client without the network, run the server in replay mode. It reads only the
recorded exchanges, and a placeholder key satisfies the population tool, because replay never sends
it:

```bash
HAZBRIEF_HTTP_MODE=replay CENSUS_API_KEY=replay-only-not-a-key \
HAZBRIEF_EVIDENCE_STORE=/tmp/store \
  uv run hazbrief brief docs/briefs/csx-point-of-rocks-day/scenario.json --out /tmp/brief
```

## 3. Read the brief

Each section ends with a grey **Sources** line, one entry per source the section's values came
from. Each entry gives:
* the source as it names itself;
* its as-of in the incident's time zone;
* `current` or **stale**;
* the record's hash prefix.

A value the request supplied (a wind the caller gave) reads "wind as given by the requester". It has
no horizon: it cannot go stale, it can only be wrong.

**Stale is a result, not a failure.** A source is stale when `now - as_of` passes its horizon, and
every horizon lives in `docs/sources/catalog.yaml`. On the committed briefs two to six sections read stale
(`docs/evidence/hb95/brief_states.txt`). `receiving_hospitals` does on all of them, because the cached CMS Hospital General Information file is as of
07/22/2026, and the catalog gives CMS a quarter. The map, footprint, flags, guidance and ICS 201 do,
where the brief carries them, because they name the 49 CFR 172.101 pack, the annual edition revised as of 10/01/2025, a year past
at the fixture instant (HB-94). The briefs still render every section. The fixes are to refresh the
cache (`scripts/fetch_cms.py`) and to build the 2026 CFR edition's pack, not to hide the flag.

**A degraded section** prints, in orange, "unavailable: \<source\>, \<reason\>, attempted at
\<time\>". The reasons:

| Reason | What it means | What to do |
|---|---|---|
| `timed out after N s` | the channel's tool did not answer within its `timeout_s` (`orchestrator.yaml`) | Retry the brief. A retry is a new assembly; nothing retries inside one. If it recurs, check the upstream service, or raise the channel's timeout with a reason. |
| `error: ...` | the tool answered a structured error (for example, no Census key) or MCP marked the result an error | Read the error. The no-key case names the signup URL. |
| `needs the protective action footprint, which is unavailable` | the footprint degraded, and this channel takes the footprint as its input | Fix the footprint first. |
| `no record in the store` | `--replay`, and the store holds no record for this tool with these parameters | Run live, or record the seed (section 5). |

A brief with a degraded section still writes. Block 10 of the ICS 201, for example, prints the
hospitals' label in place of their sources.

## 4. Read the evidence

**The store.** `evidence/store/` (or the override) holds one entity per response body,
`<sha[:2]>/<sha>.json`, or `.bin` for an image. Beside each entity are its records,
`<sha>.<activity id>.prov.json`, one per call that returned those bytes. Nothing is ever rewritten.

**A record** holds:
* the entity (hash, bytes, media type);
* the activity (tool or `GET <api>`, parameters, start and end times, the server's HTTP mode,
  `is_error`);
* the server (version and tool surface hash);
* the catalog sources it read;
* its provenance class, as-of, horizon, `used` and `wasRevisionOf`.

The schema is `docs/schema/evidence_record.schema.json`. To read one:

```bash
uv run python -c "
from hazbrief.evidence import store as S
st = S.repo_path('seed_calls_store_dir')
for r in S.all_records(st):
    print(r['activity']['name'], r['entity']['sha256'][:12], r['provenance_class'], r['as_of'])
"
```

**A label** is computed from a record at render time, never stored (DN-010 D4):

```bash
uv run python -c "
from hazbrief.evidence import store as S, labels as L
st = S.repo_path('seed_calls_store_dir')
r = next(x for x in S.all_records(st) if x['activity']['name'] == 'receiving_hospitals')
lab = L.label_for(r, S.parse_time('2026-10-26T12:00:00Z'), S.read_entity(st, r['entity']['sha256']))
print(lab['stale'], [(s['id'], s['as_of'], s['stale']) for s in lab['sources']])
"
```

**The crate manifest.** `ro-crate-metadata.json` at a store's root is RO-Crate 1.1:
* every entity and record is a `File`;
* every activity is a `CreateAction` with its `result` and `object` (what it used);
* an entity another store holds is named `sha256:<hash>`.

Any RO-Crate reader opens it.

**The appendix** lists, in hash order:
* every record the brief cites;
* under each, indented once, the records it used and any value the request supplied.

Its columns are Source, What was asked, As of, Current or stale, and Record.

## 5. Seeds, fixtures and the committed brief

The two seeds are committed, and the working store is not.

| What | Command | Notes |
|---|---|---|
| The exchange seed, `evidence/seed/` | `uv run python scripts/migrate_exchanges_to_store.py` | One record per `fixtures/exchanges` file. Idempotent and byte-deterministic; run after recording new exchanges. |
| The tool-call seed, `evidence/seed_calls/` | `uv run python scripts/record_tool_call_seed.py` | The seven tools on `csx-point-of-rocks-day`, in replay. Idempotent: a call already held is not made again, so a second run reports `calls_made: 0`. To re-record after a tool's output changes, remove `evidence/seed_calls/` first. The calls then carry new times, so the fixtures and the brief change too. |
| The scenario-brief seed, `evidence/seed_briefs/` | `uv run python scripts/build_scenario_briefs.py` | The seven tools on every other scenario that replays end to end (HB-45), recorded with `--allow-errors`: an unresolved material's structured error is held as answered, and its brief shows the section degraded. Idempotent like the tool-call seed. |
| The label fixtures, `fixtures/evidence/` | `uv run python scripts/render_evidence_fixtures.py` (write) or `--check` | Rendered at `labels.yaml` `fixture_now`. |
| The committed briefs, `docs/briefs/<id>/` | `scripts/build_scenario_briefs.py` (section 2) | `tests/test_brief.py` compares each byte for byte, and checks every replayable scenario has one. |

## 6. Add a channel

E2, E3 and E5 add sources as channels. Most of a channel is configuration; three places are code.

1. **The catalog.** Add one row per new source to `docs/sources/catalog.yaml`. Every field is
   required: `name`, `endpoints`, `tools`, `named_as`, `horizon_s` with `horizon_reason` (`stated`
   with the source's own cadence, or `assumed` with why) and `horizon_basis`, `terms`, `rate_limit`
   and `provenance_class`. `test_source_catalog.py (a test held privately)` checks the new tool's description names the
   row.
2. **The channel.** Add it in `src/hazbrief/brief/orchestrator.yaml` `channels`:
   * `timeout_s`, from the source's own bound;
   * `needs`, the channel whose output is its input, or null;
   * `sources`, its catalog rows. `tests/test_brief.py` checks they equal the catalog's rows for the
     tool.
3. **The section.** Add it in `sections`, with `title`, `channels` and, for a section that reads other
   sections, `after`. Add it to `render_order`.
4. **The code.**
   * The tool's MCP arguments: a branch in `params_for` (`src/hazbrief/brief/orchestrator.py`).
   * The section's HTML: a function in `SECTION_BODY` (`src/hazbrief/brief/render.py`), or a narrative
     through `NarrativeAuthor`.
5. **The tests.** `test_orchestrator_harness.py (a test held privately)` runs every channel against the fake server. A
   new channel needs no new harness test unless it adds a new way to fail.

**A derived channel** reads what the brief already holds and calls no tool, so it has no catalog row
and no `channels` entry. The first-order puff (HB-67; DN-018) is the pattern:

* **Config:** a block under the section it prints in (`weather.puff` in `orchestrator.yaml`), with its own
  `timeout_s`.
* **Code:** a function in `src/hazbrief/brief/derive.py` (`puff`), called from `derive.run` after the derivations
  it reads; its inputs are `derive.run`'s own entries and the application packs (`hazbrief.packs.load_app_pack`).
* **Display:** a panel in `render.py` (`_puff_html`) and its map layers in `layers.py` (`_puff_layers`), never in
  the ICS 201, the export or the first actions.
* **Degradation:** a missing input writes no geometry and one line naming it, "Puff not drawn: <what>" (the material
  not in the pack, the class not determined, no forecast wind, a molecular weight or threshold not held, a container
  the release pack does not cover, the channel's own timeout). The line is printed in the panel and beside the layer
  list's "Not drawn"; the ERG footprint and every other section are untouched.
* **Evidence:** every run, drawn or not, carries its run record and its sha256 (`evidence`), with the packs' hashes;
  `appendix.txt` lists it under "Derived: the first-order puff".
* **Rebuilding the packs it reads:** `uv run python scripts/build_packs.py all` (HB-66; `packs/SCHEMA.md`), then the
  briefs.
