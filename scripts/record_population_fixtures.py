"""Record the exchanges the HB-09 tests replay, and the counts they must reproduce.

Scenarios: each point of `fixtures/scenario_points.yaml`, by day and by night, with
HB-08's chlorine (UN1017) large-spill footprint in a moderate wind (from the west at
13 km/h, the stylebook worked example's wind): a highway tank truck on the road
corridors, a rail tank car on the rail line. Plus one footprint over open water, which
no block overlaps. For each scenario the footprint is drawn by
`protective_action_footprint` (no network: the wind is supplied), then
`population_at_risk` runs with HAZBRIEF_HTTP_MODE=record: an exchange that has a file is
served from it, so re-running this command is the resume (DN-005 section 2). The LODES
state files the blocks need are cached by `scripts/fetch_lodes.py`. The outputs are
written to `fixtures/population/expected.json`, which the tests reproduce from replay.

Checkpoint plan (constitution section 15). Unit: one exchange, written atomically as it
completes (`hazbrief.utils._write_exchange`); a scenario is a sequence of them.
Resume: re-run; recorded exchanges are not called again. Ceiling: `--max-calls` binds
every live call (the client's live GET is wrapped), so a run stops before the call that
would exceed it, exits 3, and what it recorded stays. Pacing: `--pace-seconds` between
live calls (the Census Data API publishes no rate; this is courtesy). Pilot: the first
scenario; its live calls are measured and projected onto the rest before they run.
Progress: one line per scenario, to stdout and to `logs/<date>_HB-09_record.log`.

Usage: uv run python scripts/record_population_fixtures.py [--max-calls N]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
POINTS = REPO / "fixtures" / "scenario_points.yaml"
EXPECTED = REPO / "fixtures" / "population" / "expected.json"
DAY = "2026-10-21T14:00:00-04:00"
NIGHT = "2026-10-22T02:00:00-04:00"
#: The stylebook worked example's wind (COMMANDER_STYLEBOOK.md section 7), moderate.
WIND = {
    "speed_kmh": 13,
    "direction_deg_from": 270,
    "observed_at": "2026-10-20T13:40:00-04:00",
    "source": "worked example wind",
}
#: Open water off the Delmarva coast, beyond any tabulation block: the empty case.
OPEN_WATER = {
    "type": "Polygon",
    "coordinates": [
        [[-72.0, 37.0], [-71.99, 37.0], [-71.99, 37.01], [-72.0, 37.01], [-72.0, 37.0]]
    ],
}


class CallCeiling(RuntimeError):
    pass


def scenarios() -> list[dict]:
    points = yaml.safe_load(POINTS.read_text(encoding="utf-8"))["points"]
    out = []
    for p in points:
        container = (
            "Rail tank car"
            if p["corridor"].startswith("rail")
            else "Highway tank truck or trailer"
        )
        for period, when in (("day", DAY), ("night", NIGHT)):
            out.append(
                {
                    "id": f"{p['id']}-{period}",
                    "point": p,
                    "container": container,
                    "period": period,
                    "incident_time": when,
                }
            )
    return out


def summary(result: dict) -> dict:
    """The counts a replay must reproduce (no urls, no prose)."""
    if "error" in result:
        return {"error": result["error"]}
    g = result["geography"]
    out = {
        "geography": {k: g[k] for k in ("blocks", "block_groups", "tracts")},
        "nighttime": {
            k: result["nighttime"].get(k)
            for k in ("total", "from_partial_blocks", "share_from_partial_blocks")
        }
        | {"group_quarters": result["nighttime"]["group_quarters"].get("by_type")},
        "daytime": {
            k: result["daytime"].get(k)
            for k in ("workers", "from_partial_blocks", "missing_states")
        },
        "characteristics": {
            n: {"estimate": c["estimate"], "moe": c["moe"]}
            for n, c in result["characteristics"].items()
        },
        "resilience": {
            k: result["resilience"].get(k)
            for k in ("count", "universe", "rate", "national_rate")
        },
        "primary": result["primary"],
    }
    if "reason" in result:
        out["reason"] = result["reason"]
    return out


async def run(max_calls: int, pace: float, log_path: Path) -> int:
    os.environ["HAZBRIEF_HTTP_MODE"] = "record"
    # Imported after the mode is set: settings are read once, at import.
    from hazbrief import utils
    from hazbrief.config import settings
    from hazbrief.models import IncidentInput, PopulationInput, WindObservation
    from hazbrief.tools.population_at_risk import count
    from hazbrief.tools.protective_action_footprint import footprint

    if settings.hazbrief_http_mode != "record":
        raise RuntimeError("HAZBRIEF_HTTP_MODE did not take effect")
    if not settings.census_api_key:
        raise RuntimeError("CENSUS_API_KEY does not resolve; nothing can be recorded")

    calls = {"n": 0}
    live = utils._get_live

    async def counted(base, path, params, headers):
        if calls["n"] >= max_calls:
            raise CallCeiling(f"--max-calls {max_calls} reached")
        calls["n"] += 1
        if pace:
            await asyncio.sleep(pace)
        return await live(base, path, params, headers)

    utils._get_live = counted
    log_path.parent.mkdir(parents=True, exist_ok=True)
    expected, failures = {}, 0
    plan = scenarios()
    with log_path.open("a", encoding="utf-8") as log:

        def say(line: str) -> None:
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            print(f"{stamp} {line}", flush=True)
            log.write(f"{stamp} {line}\n")
            log.flush()

        say(f"start: {len(plan) + 1} scenarios, --max-calls {max_calls}")
        t0 = time.monotonic()
        try:
            for i, s in enumerate(plan, start=1):
                before = calls["n"]
                fp = await footprint(
                    IncidentInput.model_validate(
                        {
                            "material": "UN1017",
                            "container": s["container"],
                            "location": {
                                "latitude": s["point"]["latitude"],
                                "longitude": s["point"]["longitude"],
                            },
                            "incident_time": s["incident_time"],
                            "fire_involved": False,
                            "spill_size": "large",
                        }
                    ),
                    WindObservation.model_validate(WIND),
                )
                if "error" in fp:
                    raise RuntimeError(f"{s['id']}: footprint failed: {fp['error']}")
                result = await count(
                    PopulationInput.model_validate(
                        {
                            "footprint": fp["footprint"],
                            "incident_time": s["incident_time"],
                            "period": fp["day_night"]["period"],
                        }
                    )
                )
                if "error" in result:
                    failures += 1
                expected[s["id"]] = {
                    "scenario": {k: v for k, v in s.items() if k != "point"}
                    | {"point_id": s["point"]["id"], "wind": WIND},
                    "footprint": fp["footprint"],
                    "period": fp["day_night"]["period"],
                    "table_row": fp["table_row"],
                    "result": summary(result),
                }
                made = calls["n"] - before
                say(
                    f"[{i}/{len(plan) + 1}] {s['id']}: {made} live calls; "
                    f"night {result.get('nighttime', {}).get('total')}, day "
                    f"{result.get('daytime', {}).get('workers')}; total calls "
                    f"{calls['n']}; {time.monotonic() - t0:.0f} s"
                )
                if i == 1:
                    say(
                        f"pilot: {made} live calls for one scenario; at most "
                        f"{made * len(plan)} for {len(plan)} (overlap makes it fewer)"
                    )
            result = await count(
                PopulationInput.model_validate(
                    {"footprint": OPEN_WATER, "incident_time": DAY}
                )
            )
            expected["open-water-day"] = {
                "scenario": {"id": "open-water-day", "incident_time": DAY},
                "footprint": OPEN_WATER,
                "period": result.get("primary"),
                "result": summary(result),
            }
            say(f"[{len(plan) + 1}/{len(plan) + 1}] open-water-day: {summary(result)}")
        except CallCeiling as exc:
            say(f"STOPPED: {exc}; recorded exchanges stay; re-run to resume")
            return 3
        finally:
            utils._get_live = live
        EXPECTED.parent.mkdir(parents=True, exist_ok=True)
        EXPECTED.write_text(
            json.dumps(expected, indent=1, sort_keys=True) + "\n", encoding="utf-8"
        )
        say(f"done: {calls['n']} live calls, {failures} failed; wrote {EXPECTED}")
    return 1 if failures else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--max-calls", type=int, default=400)
    ap.add_argument("--pace-seconds", type=float, default=0.25)
    args = ap.parse_args(argv)
    day = datetime.now().strftime("%Y-%m-%d")
    log = REPO / "logs" / f"{day}_HB-09_record.log"
    return asyncio.run(run(args.max_calls, args.pace_seconds, log))


if __name__ == "__main__":
    sys.exit(main())
