#!/usr/bin/env python3
"""HB-50: probe the Census Geocoder's one-line address and geographies endpoints,
recording each exchange as a fixture (scripts/probe_hb49.py's pattern, its own log).

    uv run python scripts/probe_hb50.py <api> <relative path> ['<params as JSON>']

Each call goes through the server's one upstream client (`hazbrief.utils.fetch_json`)
in `record` mode, so the exchange is written to `fixtures/exchanges/<api>/` with its
as-of headers and is replayed by the tests with no network (HB-08 to HB-10's pattern).
A re-run of a recorded call reads the file and makes no call, so a probe is resumable.
One line per probe is appended to `logs/2026-10-26_HB-49_probe.log`: time, api, url,
status, origin, bytes. At most `CEILING` probes in all (the count is read back from the
log before each call). Declared APIs only (the task's Network line).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
LOG = REPO / "logs" / "2026-10-27_HB-50_probe.log"
#: a probe is a handful of GETs per service; 40 bounds a mistaken loop
CEILING = 40
APIS = {"census_geocoder", "tigerweb"}


def main(argv: list[str]) -> int:
    os.environ["HAZBRIEF_HTTP_MODE"] = "record"
    from hazbrief.utils import UpstreamServiceError, fetch_json

    api, path = argv[1], argv[2]
    params = json.loads(argv[3]) if len(argv) > 3 else None
    if api not in APIS:
        print(f"refused: {api} is not a declared API", file=sys.stderr)
        return 2
    done = len(LOG.read_text().splitlines()) if LOG.exists() else 0
    if done >= CEILING:
        print(f"refused: {done} probes, the ceiling is {CEILING}", file=sys.stderr)
        return 3
    try:
        ex = asyncio.run(fetch_json(api, path, params))
        row = {
            "status": ex.status,
            "origin": ex.origin,
            "url": ex.url,
            "bytes": len(json.dumps(ex.body)),
        }
        out = ex.body
    except UpstreamServiceError as exc:
        row, out = {"status": None, "error": str(exc)}, None
    row = {
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "api": api,
        **row,
    }
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        f.write(json.dumps(row) + "\n")
    print(json.dumps(row))
    if out is not None:
        print(json.dumps(out)[:4000])
    return 0 if row.get("status") == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
