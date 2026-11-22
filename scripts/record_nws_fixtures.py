"""Record the NWS exchanges the HB-08 tests replay (DN-005 section 2).

For each point in `fixtures/scenario_points.yaml`, calls the NWS points endpoint and the
forecast grid it names, with HAZBRIEF_HTTP_MODE=record: an exchange that already has a
file is served from it and not called again, so re-running this command is the resume
command (standards section 15 items 1-2). Each exchange is written atomically as it
completes (`hazbrief.utils._write_exchange`).

Checkpoint plan (standards section 15). Unit: one point (two GETs). Checkpoint: the
exchange files themselves. Resume: re-run; recorded exchanges are skipped. Pilot: none;
eight calls in all is below the default pilot size of twenty. Ceiling: `--max-calls`
(default 8, HB-08's allowlist budget of two gridpoint calls per point); the run stops
before a point that could exceed it and exits non-zero. Progress: one line per point to
stdout and to `logs/<date>_HB-08_record_nws_fixtures.log`.

Usage: uv run python scripts/record_nws_fixtures.py [--max-calls N]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
POINTS = REPO / "fixtures" / "scenario_points.yaml"


def load_points(path: Path = POINTS) -> list[dict]:
    points = yaml.safe_load(path.read_text(encoding="utf-8"))["points"]
    for p in points:
        for key in ("id", "corridor", "latitude", "longitude"):
            if key not in p:
                raise KeyError(f"{path}: point {p!r} lacks {key!r}")
    return points


async def run(max_calls: int, log_path: Path) -> int:
    os.environ["HAZBRIEF_HTTP_MODE"] = "record"
    # Imported after the mode is set: settings are read once, at import.
    from hazbrief import nws
    from hazbrief.config import settings
    from hazbrief.utils import UpstreamServiceError

    if settings.hazbrief_http_mode != "record":
        raise RuntimeError("HAZBRIEF_HTTP_MODE did not take effect")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    nws_dir = Path(settings.hazbrief_exchanges_dir) / nws.API
    calls, failures = 0, 0
    points = load_points()
    with log_path.open("a", encoding="utf-8") as log:

        def say(line: str) -> None:
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            print(f"{stamp} {line}", flush=True)
            log.write(f"{stamp} {line}\n")
            log.flush()

        for i, p in enumerate(points, start=1):
            if calls + 2 > max_calls:
                say(f"ceiling: {calls} live calls made, --max-calls {max_calls}; stop")
                return 3
            before = len(list(nws_dir.glob("*.json"))) if nws_dir.is_dir() else 0
            failed = False
            try:
                wind = await nws.wind_at(
                    p["latitude"], p["longitude"], datetime.now(timezone.utc)
                )
                origin = f"{wind.points.origin}/{wind.gridpoint.origin}"
                rel = wind.points.body["properties"].get("relativeLocation", {})
                where = rel.get("properties", {})
                detail = (
                    f"grid {wind.grid} tz {wind.time_zone} wind "
                    f"{wind.speed_kmh:.1f} km/h from "
                    f"{wind.direction_deg_from:.0f} deg; "
                    f"near {where.get('city')}, {where.get('state')} "
                    f"({origin})"
                )
            except (UpstreamServiceError, nws.WindUnavailable) as exc:
                failures += 1
                failed = True
                detail = f"FAILED {type(exc).__name__}: {exc}"
            after = len(list(nws_dir.glob("*.json"))) if nws_dir.is_dir() else 0
            # A written file is one call made; a failure is one more call that wrote
            # nothing, counted so the ceiling holds.
            calls += after - before + (1 if failed else 0)
            say(f"[{i}/{len(points)}] {p['id']}: {detail}; live calls so far {calls}")
        say(f"done: {len(points)} points, {calls} live calls, {failures} failed")
    return 1 if failures else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--max-calls", type=int, default=8)
    args = ap.parse_args(argv)
    day = datetime.now().strftime("%Y-%m-%d")
    log = REPO / "logs" / f"{day}_HB-08_record_nws_fixtures.log"
    return asyncio.run(run(args.max_calls, log))


if __name__ == "__main__":
    sys.exit(main())
