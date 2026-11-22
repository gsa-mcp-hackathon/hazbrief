# HB-201 Part A: the server image, built from a clean copy with the network

Written by `the HB-201 evidence (held privately) render` from `image_steps.json` (each step's own record).

Clean copy: `git archive HEAD` at `79d46c1e3d2576cc8bb5e9269d618b4e66e29733` extracted into a new temporary directory (no .git, no gitignored data, no key). README's container commands, with README's line numbers: `readme_commands.txt`. They were run as written in the copy, with the network.

## Item 1: the build

| Build | Seconds | Exit | Steps from cache | Image id | Size |
|---|---|---|---|---|---|
| `docker build -t hazbrief-mcp .` | 3.1 | 0 | 12 | `sha256:24d378b4ca2c` | 512.2 MB |
| `docker build --no-cache -t hazbrief-mcp .` | 13.8 | 0 | 3 | `sha256:d3ea63c83cfd` | 512.2 MB |

README's build reuses whatever layers the machine already holds; the `--no-cache` build, run after it from the same copy, is the one a judge's machine with no cache makes: every step rebuilt and `uv sync --locked` downloading from PyPI. `--locked` passing means the lock is not stale.

The dependency steps' own lines, `docker build --no-cache -t hazbrief-mcp .`:

```
#13 0.689 Resolved 102 packages in 4ms
#13 1.005 Downloading numpy (15.2MiB)
#13 1.006 Downloading shapely (2.1MiB)
#13 1.011 Downloading pygments (1.2MiB)
#13 1.016 Downloading beartype (1.5MiB)
#13 1.016 Downloading cryptography (4.5MiB)
#13 1.016 Downloading pydantic-core (2.0MiB)
#13 3.186  Downloaded pygments
#13 3.331  Downloaded beartype
#13 3.488  Downloaded pydantic-core
#13 3.502  Downloaded shapely
#13 3.932  Downloaded cryptography
#13 4.837  Downloaded numpy
#13 4.838 Prepared 79 packages in 4.14s
#13 5.475 Installed 79 packages in 635ms
#19 0.335 Resolved 102 packages in 2ms
#19 1.590       Built hazbrief @ file:///app
#19 1.595 Prepared 1 package in 1.25s
#19 1.597 Installed 1 package in 2ms
```

The README build's last lines:

```

#19 [stage-1  4/12] COPY pyproject.toml uv.lock README.md LICENSE LICENSE-TEMPLATE ./
#19 CACHED

#20 [stage-1 12/12] RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin hazbrief
#20 CACHED

#21 exporting to image
#21 exporting layers done
#21 writing image sha256:24d378b4ca2cbfd3682e94b1d67933c7f349af5fd24cbd9f74641f027f16bcef done
#21 naming to docker.io/library/hazbrief-mcp done
#21 DONE 0.0s

View build details: docker-desktop://dashboard/build/desktop-linux/desktop-linux/umick6ztyw1us3kscu1x0wovh
```

## Item 2: the container, run by README's line, reached from the host

README's line: `docker run --rm -p 127.0.0.1:8080:8080 --env-file .env hazbrief-mcp   # http://localhost:8080/mcp`. Run as `docker run --name hb201-serve --rm -p 127.0.0.1:18080:8080 --env-file .env hazbrief-mcp` (a `--name` added, so the tool can stop it).

Host port: README's `127.0.0.1:8080` was already held on this machine by a process that is not this task's (`Python  1732 brock    4u  IPv4 0x5161dd818764a0d3      0t0  TCP 127.0.0.1:8080 (LISTEN)`), so only the host side of `-p` was changed, to `127.0.0.1:18080`.

- `/health`: RemoteDisconnected after 60.1 s, `Remote end closed connection without response`
- `/version`: RemoteDisconnected, `Remote end closed connection without response`

The container's log, last lines:

```
│                          🎉 Update available: 4.2.1                          │
│                      Run: pip install --upgrade fastmcp                      │
╰──────────────────────────────────────────────────────────────────────────────╯


[11/18/26 12:00:42] INFO     Starting MCP server 'HazBrief MCP  transport.py:358
                             Server' with transport 'http' on                   
                             http://127.0.0.1:8080/mcp                          
INFO:     Started server process [1]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8080 (Press CTRL+C to quit)
```

## Item 2, diagnostic: the same line with `-e MCP_HOST=0.0.0.0` after `--env-file` (not README's command)

README's line: `docker run --rm -p 127.0.0.1:8080:8080 --env-file .env hazbrief-mcp   # http://localhost:8080/mcp`. Run as `docker run --name hb201-serve --rm -p 127.0.0.1:18080:8080 --env-file .env -e MCP_HOST=0.0.0.0 hazbrief-mcp` (a `--name` added, so the tool can stop it; `MCP_HOST=0.0.0.0` added to test the cause).

Host port: README's `127.0.0.1:8080` was already held on this machine by a process that is not this task's (`Python  1732 brock    4u  IPv4 0x5161dd818764a0d3      0t0  TCP 127.0.0.1:8080 (LISTEN)`), so only the host side of `-p` was changed, to `127.0.0.1:18080`.

- `/health`: 200 after 3.3 s, `{"status":"healthy","service":"hazbrief-mcp"}`
- `/version`: 200, `{"version":"0.1.0"}`
- `/mcp` initialise: server `HazBrief MCP Server` 4.1.1, protocol 2026-07-28
- tools listed (7): assess_incident, build_ics_201, facilities_in_footprint, material_response_guidance, population_at_risk, protective_action_footprint, receiving_hospitals
- `assess_incident` with README's arguments: 20 fields README prints compared, every one equal

The container's log, last lines:

```
[11/18/26 12:03:03] INFO     Starting MCP server 'HazBrief MCP  transport.py:358
                             Server' with transport 'http' on                   
                             http://0.0.0.0:8080/mcp                            
INFO:     Started server process [1]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8080 (Press CTRL+C to quit)
INFO:     172.17.0.1:65362 - "GET /health HTTP/1.1" 200 OK
INFO:     172.17.0.1:65366 - "GET /version HTTP/1.1" 200 OK
INFO:     172.17.0.1:65372 - "POST /mcp HTTP/1.1" 200 OK
INFO:     172.17.0.1:65372 - "POST /mcp HTTP/1.1" 200 OK
INFO:     172.17.0.1:65372 - "POST /mcp HTTP/1.1" 200 OK
```

## Item 3: every tool once, `--network=none`, from inside the container

Container: `docker run -d --rm --network=none --env-file .env --name hb201-inside hazbrief-mcp`; calls made by `docker exec -i hb201-inside python -` reading `tools/inside_calls.py`, over the container's own `http://127.0.0.1:8080/mcp`. Arguments: `tests/test_json_string_args.py` (one offline test that calls every tool through the MCP client; the I-81 point, UN1017, the stylebook's worked-example wind), sent as objects.

| Tool | Outcome | Seconds | What it said |
|---|---|---|---|
| `assess_incident` | answered in full | 0.0 | fields: basis, cameo_datasheets, cfr172, coverage, day_night, erg_table, guide, hazard_class |
| `protective_action_footprint` | answered in full | 0.0 | fields: basis, day_night, erg_table, flag_inputs, flags, footprint, guide, hazard_class |
| `material_response_guidance` | answered in full | 0.0 | fields: basis, emergency_response, general_first_aid, guide, identified_by, limits, material, order |
| `population_at_risk` | structured error | 0.0 | 1 error(s), 1 distinct: {"error": "CENSUS_API_KEY is not set. The Census Data API requires a key on every data query; request one at https://api.census.gov/data/key_signup.html.", "hint": "Set CENSUS_API_KEY in the project .env or the master secrets file (DN-004); signup: https://ap… |
| `facilities_in_footprint` | structured error | 0.1 | 5 error(s), 3 distinct: {"source": "USGS National Structures Dataset", "error": "Upstream service request failed.", "hint": "Retry; the other sources answered."}; {"source": "USGS 3D Hydrography Program (3DHP)", "error": "Upstream service request failed.", "hint": "Retry; the other sources answered."}; {"source": "NTAD rail", "error": "Upstream service request failed.", "hint": "Retry; the other sources answered."} |
| `receiving_hospitals` | answered in full | 0.2 | fields: basis, hospitals, inside_footprint, limits, max_km, measured_from, more, unplaced_in_states |
| `build_ics_201` | structured error | 0.3 | 10 error(s), 8 distinct: {"tool": "nws_time_zone", "error": "Upstream service request failed."}; {"tool": "population_at_risk", "error": "CENSUS_API_KEY is not set. The Census Data API requires a key on every data query; request one at https://api.census.gov/data/key_signup.html.", "hint": "Set CENSUS_API_KEY in the project .env or the master secrets fil…; {"tool": "facilities_in_footprint", "source": "USGS National Structures Dataset", "error": "Upstream service request failed.", "hint": "Retry; the other sources answered."}; {"tool": "facilities_in_footprint", "source": "USGS 3D Hydrography Program (3DHP)", "error": "Upstream service request failed.", "hint": "Retry; the other sources answered."}; {"tool": "facilities_in_footprint", "source": "NTAD rail", "error": "Upstream service request failed.", "hint": "Retry; the other sources answered."}; {"tool": "tigerweb_place", "error": "pl… |

Failed: none. A file the image does not hold, named in any answer: none. Every structured error above names an upstream host the `--network=none` container cannot reach, or DN-003's no-key error (the copy's `.env` is `.env.example`, with no `CENSUS_API_KEY`).

## Item 4

No tool failed for a path the Dockerfile does not copy, so no `COPY` line was added and the image was not rebuilt for it. The README run line's failure (item 2) is reported as Issue `260116a9-9089-4d28-a3ec-5985407274bf`, importance high, with the output's own lines; its fix (`.env.example`, README or the configuration's precedence) is outside this task's Touches.

## Item 5

Containers `hb201-serve` and `hb201-inside` removed by this step. The image is left tagged `hazbrief-mcp:hb201` (and README's `hazbrief-mcp`); nothing is pushed to any registry.
