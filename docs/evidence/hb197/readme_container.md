# HB-197: README's container lines after `.env.example` stopped setting MCP_HOST

Written by `the HB-197 evidence (held privately) render` from `readme_container.json`. Issue `260116a9` (HB-201, `docs/evidence/hb201/image.md` item 2): README's run line gave a container whose server bound its own loopback, because `.env.example` set `MCP_HOST=127.0.0.1` and `--env-file` carried it over the image's `0.0.0.0`. HB-197 made that line a comment stating the default.

## 1. The copy and the build

`git archive` of `761533d3968f` into a new temporary directory; README's block (`readme_commands.txt`) run there. `cp .env.example .env`; the copied `.env` sets MCP_HOST on 0 uncommented lines; its commented line: `# MCP_HOST=127.0.0.1`.

README's line `docker build -t hazbrief-mcp .` run as `docker build --network=none -t hazbrief-mcp .` (the one flag added: this task's Network line is none, so no RUN step may reach the network). Exit 1, 28.6 s, 4 steps CACHED.

**The build asked for the network.** It stopped at `RUN uv sync --locked`: only 4 steps came from the cache, and the dependency step, whose inputs are unchanged since HB-201's build, ran again and could not reach PyPI. The likely reason, not tested here: BuildKit keys a RUN step on its network mode, so a `--network=none` build cannot reuse a layer built with the network. As item 0d directs, the run line was run against the image HB-201 left: `hazbrief-mcp` and `hazbrief-mcp:hb201` both name `sha256:d3ea63c83cfd...` (one image). The image holds nothing `.env.example` changes: the file is not copied into it, and nothing the Dockerfile copies has changed since HB-201's build (`git diff 79d46c1e` over those paths is empty).

Its last lines:

```
22.41         `fastmcp` (v4.1.1) which depends on `fastmcp-slim[server]` (v4.1.1)
22.41         which depends on `jsonschema-path` (v0.5.0) which depends on `attrs`
------
Dockerfile:48
--------------------
  46 |     # copy of the software carries (HB-87R).
  47 |     COPY pyproject.toml uv.lock README.md LICENSE LICENSE-TEMPLATE ./
  48 | >>> RUN uv sync --locked --no-dev --no-install-project
  49 |     
  50 |     COPY src ./src
--------------------
ERROR: failed to build: failed to solve: process "/bin/sh -c uv sync --locked --no-dev --no-install-project" did not complete successfully: exit code: 1

View build details: docker-desktop://dashboard/build/desktop-linux/desktop-linux/82jm1hkxoe3nkhgju2nrvin7w
```

## 2. README's run line, as written

`docker run --rm -p 127.0.0.1:8080:8080 --env-file .env hazbrief-mcp   # http://localhost:8080/mcp`, run as `docker run --name hb197-serve --rm -p 127.0.0.1:18080:8080 --env-file .env hazbrief-mcp`.

README's host port 8080 was held on this machine, so only the host side of `-p` changed, to 18080 (as HB-201 did). The listener on 8080: `Python  1732 brock    4u  IPv4 0x5161dd818764a0d3      0t0  TCP 127.0.0.1:8080 (LISTEN)`.

| Check | Result |
|---|---|
| `/health` from the host | 200 after 4.5 s: `{"status":"healthy","service":"hazbrief-mcp"}` |
| `/version` | 200 |
| tools listed over `/mcp` | 7: assess_incident, build_ics_201, facilities_in_footprint, material_response_guidance, population_at_risk, protective_action_footprint, receiving_hospitals |
| `assess_incident` against README | 20 fields compared, 0 differences |

The container's log, its last lines:

```
[11/18/26 14:18:34] INFO     Starting MCP server 'HazBrief MCP  transport.py:358
                             Server' with transport 'http' on                   
                             http://0.0.0.0:8080/mcp                            
INFO:     Started server process [1]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8080 (Press CTRL+C to quit)
INFO:     172.17.0.1:58274 - "GET /health HTTP/1.1" 200 OK
INFO:     172.17.0.1:58280 - "GET /version HTTP/1.1" 200 OK
INFO:     172.17.0.1:58290 - "POST /mcp HTTP/1.1" 200 OK
INFO:     172.17.0.1:58290 - "POST /mcp HTTP/1.1" 200 OK
INFO:     172.17.0.1:58290 - "POST /mcp HTTP/1.1" 200 OK
```
