# Security considerations

**Task:** `HB-26` (HB-26).
**For:** the evaluation document's security section (DN-001 section 1).

This note describes the controls that exist, read from the code, and the ones that do not.
* HB-26 wrote it at commit `ed26c53`, and HB-34 updated sections 8 and 9.
* HB-42 rechecked it at `5282b29` and added the evidence store (section 3). For it, HB-42 added one
  control: the store refuses a record that holds a configured secret.
* HB-89 unpublished the HTTP route and bounded a caller's footprint (section 10), closing the
  review findings L3-1, L3-2, L3-5, L3-7 and L6-5 by their unpublish branch.

Section 9 lists what is not done. The system it describes is in [`ARCHITECTURE.md`](ARCHITECTURE.md).

## 1. Posture

The server answers questions about public federal data. It holds no personal data and no
credentials of its users. It writes nothing upstream and calls no model. Its one secret is the
operator's free Census Data API key. The main risks are therefore not disclosure. They are a
wrong answer presented as authoritative, a request that turns the server into a proxy or an
amplifier against the federal services it reads, and the operator's key leaking into a committed
file.

## 2. The trust boundary

**Inbound.** An MCP client calls seven tools, one prompt and three resources (`app.py`). Every tool
is annotated `readOnlyHint: true`. No tool takes a URL, a file path or a query string: a tool names
an API, and the origin comes from configuration (`config.py` `upstream_base_url`). Over HTTP, the
transport accepts any caller that can reach it, which by default is a caller on the same machine
(section 10).

**Outbound.** Every upstream call goes through one client (`utils.py` `fetch_json`,
`fetch_bytes`), which keeps the template's outbound boundary:

* The path must be relative. A scheme, a host, a query, a fragment, a leading slash, a `.` or
  `..` segment, or an encoded form of any of these is refused before a socket opens
  (`_validate_relative_path`, decoded up to three times).
* No redirect is followed, and no proxy or netrc is read from the environment (`trust_env=False`).
* A next URL named by a response (the NWS `points` response) is followed only under the same
  configured origin (`relative_to_origin`), so a response cannot steer the client.
* Every call has a timeout (`UPSTREAM_TIMEOUT_SECONDS`, 30) and a response size cap
  (`UPSTREAM_MAX_RESPONSE_BYTES`, 5,000,000), enforced while streaming.
* A failure becomes an `UpstreamServiceError` whose message carries no upstream text.
* A binary response of a media type not asked for is refused (`fetch_bytes`).

`tests/test_http_security.py` holds a regression test for each item, including metadata-service,
localhost, traversal and double-encoded paths.

**The six origins** (`config.py`): `api.weather.gov`, `api.census.gov`, `tigerweb.geo.census.gov`,
`carto.nationalmap.gov`, `hydro.nationalmap.gov`, `services.arcgis.com`. Each is an operator
setting; whoever sets the environment chooses them.

## 3. Secrets (DN-004)

* **One key.** `CENSUS_API_KEY` is the only credential the server reads (`config.py`; the
  unused healthdata.gov token setting was removed by HB-95). No other key is required (DN-001 section 4
  invariant 3).
* **Layered dotenv.** Precedence, highest first: an exported variable, the repository's `.env`,
  the master file `~/.secrets/master.env` (or `HAZBRIEF_MASTER_ENV`). A blank value is ignored, so a
  copied `.env.example` does not hide a master key. A path named by `HAZBRIEF_MASTER_ENV` must
  exist, or the server stops at import. `tests/test_config_layering.py` checks the precedence in a
  fresh interpreter per case.
* **Not committed.** `.gitignore` excludes `.env` and the deploy kits' `.env` and `eval.env`.
  `.env.example` names both credentials, blank, and the settings an operator usually sets, with
  their defaults. It holds no credential value.
* **Not in the container.** `.dockerignore` excludes `.env`, and the Dockerfile copies no dotenv
  file. The master file lives outside the repository, so no build context holds it. A container
  receives only the variables `.env.example` names, by `docker run --env-file` or the platform's
  secret store.
* **Not in a fixture.** A recorded exchange is stored under its url with `key` and `$$app_token`
  removed (`public_url`), keeps only the User-Agent and Accept request headers, and is refused if
  any configured secret value appears anywhere in the record (`_write_exchange`). The urls that tool
  outputs return in their query records are the same stripped urls.
  `test_a_key_parameter_never_reaches_the_file` and
  `test_a_configured_secret_in_a_response_is_not_recorded` cover this.
* **Not in an error.** No error message carries an upstream body or a request url with its key.
* **Not in an evidence record** (HB-39 to HB-42). The application's store (`src/hazbrief/evidence/`)
  holds, per MCP call:
  * the response body;
  * the tool's parameters;
  * the call's times, the server's version and surface hash, and the catalog sources.

  It is local: the working store `evidence/store/` is gitignored. Only the two seeds are committed,
  `evidence/seed/` (built from the already committed exchanges, whose urls carry no key) and
  `evidence/seed_calls/` and `evidence/seed_briefs/` (calls made in replay with a placeholder key).

  The Google Maps key (HB-45) is the application's, never the server's: it is read by
  `src/hazbrief/brief/settings.py` alone, and no server module names it (`test_brief_map.py (a test held privately)`).
  It is a browser key and is written into a brief the CLI builds with it, so it is restricted by HTTP
  referrer in the Google Cloud console. The committed briefs are built with `--no-google`, and a test
  checks that none carries a key.

  No key reaches a record by construction:
  * the server reads `CENSUS_API_KEY` from its own environment, and no tool takes it as a parameter;
  * the client records parameters and responses, never the environment it hands the server.

  `write_record` also refuses, before writing anything, a record or entity in which a configured
  secret value appears, as `_write_exchange` does. The secret values are the operator's settings and
  the key in the environment the client passes. The test is `tests/test_evidence_store.py`
  `test_a_record_holding_a_configured_secret_is_refused_and_nothing_is_written`.

  A scan of the 494 files under the stores, `fixtures/evidence/` and `docs/briefs/` for the
  operator's configured key found none, and no recorded url carries `key=` (HB-42).

## 4. Input validation

* **Pydantic at the boundary** (`models.py`). Every tool input model sets `extra="forbid"`. Strings
  are length-bounded (a material name at most 200 characters, a placard at most 60), coordinates
  and wind are ranged, times must carry a UTC offset, and `IncidentInput` requires exactly one of
  `material`, `placard` and `guide_number`.
* **One parse, no repair.** An object sent as a JSON string is parsed once, and the output says so
  (`ToolInput`, `json_string_notices`). Malformed JSON is rejected with where it stops; a string of
  a string is not parsed twice.
* **No guess.** An input the ERG cannot answer returns `error` with a `hint`, never a nearest match
  presented as the answer (`incident.py`, `material_response_guidance.py`). An unresolved load
  (a name under several ID numbers, a placard several rows match) is drawn once per candidate,
  with the largest marked governing, as the ERG directs (ERG 2024 PDF p. 9).
* **GeoJSON footprints** (`PopulationInput`, `FacilitiesInput`, `ReceivingInput`) are typed as
  `dict` and read by `geo.footprint_shape`, which accepts polygons only and repairs an invalid ring
  with `make_valid`. Their size and area are not bounded (section 9).

## 5. Tool result size

A tool result over the client's cap never reaches the model (LN-07 F1: Claude Code caps a tool
result at 25,000 tokens by default). `build_ics_201` defaults to `response_format: concise`, which
fits that cap. `detailed` with `block` returns the full receipts one part at a time; `detailed` without `block`
is the whole form, 60,000 to 100,000 characters, which is over that cap (`Ics201Input.block`). The SVG sketch is
opt-in (`include_map_svg`), and its description says it goes over the cap. The other tools return
their structured outputs whole. Inbound, each upstream response is capped at 5 MB (section 2).

## 6. What the model never decides

DN-001 section 4 invariant 2: the model narrates; it never decides what is alarming.

* No model runs inside the server. Flags are rules in `packs/flag_rules.json`, each with its ERG
  source, fired by a predicate over tool values (`flags.py`). A rule whose inputs are missing does
  not fire and names them.
* Every ICS 201 sentence is a template filled from a tool output value, or an ERG sentence quoted
  from a pack, with receipts. A sentence of Blocks 5, 7 or 10 without one fails the build
  (`tools/build_ics_201.py`, `ics201.py`).
* Every distance traces to an ERG pack cell. The harness checks this over every output it can
  enumerate (LN-05 part A item 5). There is no dispersion model and no interpolation.
* Packs are verified at startup by sha256 and schema (`packs.py`); an altered pack stops the
  server.
* The Incident Commander's blocks (2, 8, 9 and the signature) are left blank, and Block 7 leaves
  the choice between evacuation and shelter-in-place to the Incident Commander (SB-STR-06).

The agent evaluation (LN-07) measures what a client model does with these outputs. That is
outside the server's control. The server's part is that every value it returns carries its source.

## 7. Build-time controls

* **The fetcher** (`scripts/fetch_allowlisted.py`). The host must be on `corpus/allowlist.txt`,
  compared exactly, before any socket opens. The same check runs on every redirect hop and on the
  `robots.txt` read. When `SELDON_NETWORK_ALLOWLIST` is set the effective list is the
  intersection. `robots.txt` is read first and obeyed (RFC 9309); `Crawl-delay` is honoured; 429
  and 503 back off within a bound. Each document is a checkpointed unit with an fsynced log row.
  `scripts/fetch_lodes.py` and `scripts/fetch_cms.py` use the same client.
* **Corpus binaries** in `corpus/raw/` are not committed; provenance is url plus sha256.
* **The handoff secret scan** (AD-039; `~/GitHub/CLAUDE.md` section 6.1). A handoff is run through
  `python -m squiddy.secret_scan` before it is committed. Seldon's `commit-governed` path runs the
  scanner only over the roots a repository's `the Seldon configuration (held privately)` names under `desktop_commit.scan`. HB-33
  added that block to this repository's `the Seldon configuration (held privately)` (`roots: [a session handoff (held privately)]`), so the scan runs on
  every governed handoff commit. Run over `a session handoff (held privately)` at HB-42, it reports `scanned 10 file(s);
  exit 0`.
* **The commit gate** (`the git hooks of the repository (held privately)`): Seldon's pre-commit and commit-msg hooks gate design notes
  on their prior-art verdict. They do not scan for secrets.

## 8. Continuous integration (the template's)

`.github/workflows/ci.yml`, kept from the template, runs `ruff check`, `ruff format --check` and
`pytest tests/`. `.github/workflows/eval-nightly.yml` runs the exhaustive invariant tests. Since
HB-85 neither has a push, pull request or schedule trigger; a person starts either by hand from
the Actions tab, and the dispatcher's local suite run before every merge
(`uv run pytest tests/ -q -p no:cacheprovider -n auto --maxprocesses 6 --dist loadfile -m 'not slow and not
load_sensitive' && uv run pytest tests/ -q -p no:cacheprovider -n 3 --dist loadgroup -m 'load_sensitive and not slow'
&& uv run ruff check . && uv run ruff format --check .`, `the Seldon configuration (held privately)` `dispatch.gate_command`; lint joined it in
HB-105, parallel workers in HB-164, the second step for the `load_sensitive` tests in HB-194) is the gate. Neither runs a dependency vulnerability audit, a
secret scanner or static security analysis. Since HB-34 the actions are pinned by commit sha,
with the release in a trailing comment (`actions/checkout` v4.4.0, `astral-sh/setup-uv` v4.2.0).
uv itself is still installed at `latest` in CI.

## 9. What is not done

| Not done | Template provides it? | Enabled here? |
|---|---|---|
| **Authentication on the HTTP transport.** `/mcp`, `/health` and `/version` answer any caller. | The template's `deploy/README.md` says every kit exposes the endpoint with no authentication by default, except Databricks, which sits behind workspace SSO, and advises fronting it with auth beyond a hackathon. FastMCP 4.1.1, the locked version, ships auth providers (`fastmcp/server/auth/`). | No. `app.py` passes no `auth`. A Databricks deployment would inherit the workspace's SSO from the platform, not from this server. |
| **Rate limiting.** No limit per caller or per tool. | FastMCP 4.1.1 ships rate-limiting middleware (`fastmcp/server/middleware/rate_limiting.py`); the template does not configure it. | No. |
| **Audit log of tool calls.** The server writes no log of who called what. | FastMCP 4.1.1 ships logging middleware; the template does not configure it. | No. The package has no logging calls. |
| **TLS.** The server speaks plain HTTP; TLS is the host's (cloud.gov, Code Engine, Databricks). | The deploy kits rely on the platform's TLS. | Platform only. |

The HTTP transport binds `127.0.0.1` by default (`MCP_HOST`); the container widens it inside its
own network namespace and is published on the host's loopback only (section 10).

**Closed by HB-89**, and so no longer a row of the table: the bound on caller footprints (section
10).

**Closed by HB-34**, and so no longer rows of the table. The image runs as a non-root user
(`hazbrief`, uid 10001). It installs from `uv.lock` with `uv sync --locked`, and copies uv's image
pinned by version and digest. `requirements.txt`, which buildpack hosts install from, is the
lockfile's export and names `shapely`. The image now holds the CMS and LODES caches it was missing
(ARCHITECTURE section 10, D-11). `test_container_image.py (a test held privately)` and `tests/test_requirements.py`
hold each of these.

## 10. The HTTP route's exposure (HB-89)

The route is unpublished until authentication lands. HB-87's scope item 3 offered two branches,
authentication and rate limiting with a recorded deployment, or unpublishing; HB-89 took the
second, because the submission's story is two commands and a local client and nothing depends on a
hosted endpoint. As it now is:

* **No published remote.** `server.json` lists no `remotes` (its earlier
  `hazbrief-mcp.app.cloud.gov` entry had no recorded deployment; review L6-5). The registry entry
  describes the repository alone. `test_route_exposure.py (a test held privately)` holds it.
* **`server.json` names no package and no remote, and the registry does not require either.** It
  validates against the 2025-09-29 registry schema its `$schema` names, and against the newest
  HB-95 found, 2025-12-11 (`docs/evidence/hb95/server_json_validation.txt`). Both schemas make
  `packages` and `remotes` optional. The registry's server.json reference says so of an entry
  with neither: "For MCP servers that follow a custom installation path or are embedded in
  applications without standalone packages, use the `websiteUrl` field to direct users to setup
  documentation". Its example carries only `name`, `description`, `websiteUrl` and `version`
  (`docs/reference/server-json/generic-server-json.md`, "Server with Custom Installation Path").
  The publisher guide asks for `remotes` only of a remote-only server: "Your `server.json` must
  include a `remotes` entry and can omit `packages`" (`docs/modelcontextprotocol-io/quickstart.mdx`,
  "Remote-only servers"). The registry's validator (`internal/validators/validators.go`) checks
  each package and remote it is given and requires neither. All three are from the
  `modelcontextprotocol/registry` repository's main branch, fetched 2026-11-04 and held with their
  sha256 in `the HB-100 evidence (held privately)` (HB-100). The earlier statement here, that the publish check needs one
  of them, was wrong and is withdrawn. No entry has been submitted, so the registry's other
  publish-time checks (the namespace login, the schema version it accepts) have not been run on
  this one.
* **Local by default.** Both HTTP paths in `app.py` (`PORT` or `DATABRICKS_APP_PORT`, and
  `MCP_TRANSPORT=streamable-http`) bind `MCP_HOST`, default `127.0.0.1`. The platform-port path no
  longer binds `0.0.0.0` unconditionally (L3-1). The container sets `MCP_HOST=0.0.0.0` inside its
  own network namespace, which a published port needs, and the README publishes it with
  `-p 127.0.0.1:8080:8080`, so the host's other interfaces do not carry it. `.env.example` leaves
  `MCP_HOST` unset, a comment stating its default of `127.0.0.1`: a value there would reach the
  container through `--env-file` over the image's `0.0.0.0`, and the published port would reach
  nothing (Issue `260116a9`, HB-197).
* **Host and Origin checked.** Every HTTP run passes `host_origin_protection=True` to fastmcp
  4.1.1, its strict mode (`fastmcp/server/http.py` `HostOriginGuardMiddleware`): a request whose
  `Host` is not `127.0.0.1`, `localhost`, `::1`, the bound host or a name in `MCP_ALLOWED_HOSTS`
  gets 421, and a browser `Origin` that does not match gets 403. A web page cannot reach a local
  server by DNS rebinding (L3-7). `MCP_ALLOWED_HOSTS` is empty by default.
* **Masked errors.** `FastMCP(..., mask_error_details=True)`: an exception a tool raises reaches
  the client as a generic message, never its text, so no path, key name or stack frame leaves the
  server (L3-5). A tool's expected failures are returned values with `error` and `hint`; the
  missing `CENSUS_API_KEY` still returns its signup URL (DN-003 section 1). A zone that crosses the
  antimeridian is now one of those returned errors (`protective_action_footprint._drawn`), and the
  LODES and CMS file errors name a file and a setting, not a directory.
* **Bounds on a caller's footprint** (L3-2), refused before any upstream call
  (`geo.footprint_shape`) and returned by `population_at_risk` and `facilities_in_footprint` as
  `error` and `hint`:
  * area: `MAX_FOOTPRINT_AREA_KM2`, 381 km2, the disk of the ERG 2024's largest Table 3 protective
    action distance (11.0 km; pi x 11.0^2 = 380.1). The largest footprint the server draws is
    under 132 km2;
  * vertices: `MAX_FOOTPRINT_VERTICES`, 4,096; the server's own footprints have fewer than 400;
  * pages per layer: `max_features_per_layer`, 50,000 features, in `population_sources.yaml`
    (TIGERweb) and `facilities_sources.yaml` (`arcgis`); a layer's query reads at most
    ceil(50,000 / page size) pages and then stops with `PageCapExceeded`. Each file states the
    derivation.

  `test_route_exposure.py (a test held privately)` passes one case over each bound.

**Deferred.** The geodesic area and shapely work still runs inside the tools' `async` functions
rather than under `anyio.to_thread.run_sync` (the review's L3-2 fix names it). With one local
caller and the bounds above it blocks nobody; it matters once a hosted route serves concurrent
callers, and it belongs to that task.

**What the hosted route needs before `remotes` returns to `server.json`:**

1. Bearer authentication from the locked fastmcp (`FastMCP(..., auth=...)`, a verifier from
   `fastmcp/server/auth/` fed by a new token setting), with startup failing over HTTP when the
   token is empty (review L3-1).
2. Rate limiting per caller and per tool from `fastmcp/server/middleware/rate_limiting.py`, with
   limits in `config.py`, since every `population_at_risk` call spends the operator's Census key.
3. `MCP_ALLOWED_HOSTS` set to the deployment's host name, and `MCP_HOST` widened only there.
4. The bounds' geometry work moved off the event loop (Deferred, above).
5. A recorded deployment (the `cf push` or equivalent, with its date) and a check that the URL in
   `remotes` answers, before the entry is written (review L6-5).

## 11. The models image (HB-111)

`hazbrief-models` (`deploy/models/`) is a second image, beside the server and never part of it
(DN-020 section 2 item 5). It is optional: the server and its two-command run do not use it, and
only the application's dense-gas client (`src/hazbrief/brief/dense_gas.py`) calls it.

* **What it runs.** SLAB (D. L. Ermak, LLNL, 1990), compiled from the held archive
  `corpus/raw/epa-slab-code.zip` (`epa-slab-code`). The build checks the archive's sha256 against
  the manifest's `raw_sha256` before unpacking it, and fails on any other bytes. It compiles
  `SLAB.FOR` as HB-102 did (`gfortran -std=legacy -O0`, GCC 14.2.0, statically linked). It then
  runs SLAB's four distributed test cases and fails if any printed value differs from the
  distributed output by more than one unit in the third significant figure
  (`deploy/models/check_cases.py`). The entry is a standard-library driver
  (`src/hazbrief/brief/slab_driver.py`): it reads an input deck on stdin, runs SLAB in a fresh
  temporary directory, and writes SLAB's output file to stdout.
* **It never listens.** No port is exposed and no process serves. The client runs it once per
  deck as `docker run --rm -i --network none --pull never hazbrief-models`. The container has
  no network, is removed when SLAB exits, and is never pulled from a registry. It runs as a
  non-root user (`slab`, uid 10001) and holds no compiler: the runtime stage is the server's own
  pinned `python:3.11-slim`, and the GCC stage is discarded.
* **The server image holds none of it.** `.dockerignore` leaves `deploy/` and `deploy/models/`
  out of the server's build context, and `src/hazbrief/brief/` (the driver and the client) with
  them. `test_container_image.py (a test held privately)` (`test_the_image_holds_none_of_the_models_image`)
  builds the server image's file list and asserts that it has no file from `deploy/models/`, no
  SLAB file, no gfortran and no compiler base.
* **SLAB's licence.** SLAB is not a US Government work. `SLAB.FOR` lines 1 to 20 hold "(C)
  Copyright 1990 the Regents of the University of California. All Rights Reserved." The work
  was produced under DOE sponsorship, and "The Government retains certain rights therein." The
  program may be copied and distributed, or included in another program, on two conditions:
  "1. No fee may be charged for copying or distributing the SLAB program or any part thereof.
  2. The SLAB program may not be distributed, in whole or in part, as part of any commercial
  product." It is "provided 'as is'" (issue `f6a72d1d`, corrected by HB-106). The image carries
  those 20 lines verbatim at `/licenses/SLAB`. SLAB's source never enters this repository's
  MIT tree: the image is built from the held archive, which `corpus/raw/` keeps out of git, and
  no SLAB source file is committed (the evidence directories hold run outputs and comparisons,
  as HB-102's `runs/slab/` does). Anyone who distributes the built image takes on the
  two conditions; it is not published here, and it must not be sold or bundled into a commercial
  product.
* **SCICHEM's licence (HB-167).** The models image also builds EPRI's SCICHEM 3.4 (SCIPUFF
  inside) from EPRI's repository at commit `156625ef`, with eleven patches
  (`deploy/models/scichem/`). EPRI's SourceForge project page declares it "BSD License"
  (corpus document `epri-dispersion-sourceforge`); the repository itself carries no licence
  file and no licence text, so no holder or terms are reproduced. The image carries
  `deploy/models/scichem/NOTICE` at `/licenses/SCICHEM`: that declaration, the copyright lines the
  compiled source states (EPRI's version resource "Copyright (C) 2011"; Ramboll ENVIRON's CAMx
  lines; the University of Miami, Carnegie Mellon and Georgia Tech ISORROPIA lines) and the CMAQ
  header, and the rights notice SCICHEM's two manuals carry (theirs, not the code's). As with
  SLAB, the image is built locally from source and is not published here. The licence is as
  EPRI's public page states it; that page is held (fetched 2026-10-29, sha256 `99bfc48a`), and no
  request to EPRI is planned (Issue `4104d9fe`, closed won't-fix).
* **Why not the Python port.** HB-111 Part 0 ran `slabx` 1.0.7 (MIT; a reimplementation that
  ships no SLAB code) on the same four cases. Its concentrations differ from the Fortran's by
  more than DN-020 ADDENDUM-00's 5 percent: on PR4 (chlorine) by up to 24 percent within 46 m
  (`the HB-111 evidence (held privately)`). It is not a dependency.
