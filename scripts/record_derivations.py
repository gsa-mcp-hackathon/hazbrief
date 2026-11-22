#!/usr/bin/env python3
"""Record the upstream answers the workbench derivations read (DN-015, DN-016).

    HAZBRIEF_HTTP_MODE=record uv run python scripts/record_derivations.py \
        [--scenario ID] [--max-calls N]

For each committed brief (`scripts/build_scenario_briefs.py`: the replayable fixture
scenarios and the location scenarios), the brief is assembled from the stores as the
committed brief is (`--replay`: no tool is called), and only the derivations
(`hazbrief.brief.derive.run`) reach upstream, through the one client in `record` mode:
TIGERweb's roads in the footprint's extent, the 3DHP flowlines within D of the spill and
along the path, NLDI's position and navigation (HB-54), and the 3DHP River polygons
along 3DHP's own path that measure the width NLDI's path is held to (HB-58); County
Business Patterns, the USGS elevation service at every terrain point and the NLCD class
at the spill (HB-55), the elevation now one 3DEP getSamples call per sample set (HB-59);
the NWS points and gridpoint forecast at the spill, and nowCOAST's radar capabilities
(HB-56; the committed briefs replay without radar, so that one exchange is read by the
tests only); and the NWS station list the points answer names and the nearest station's
latest observation (HB-60); and the land cover, the Annual NLCD COG mirror's file head,
tile directory entries and tiles under the footprint and the path, each byte range one
exchange (HB-59 ADDENDUM-03); and nowCOAST's satellite capabilities and the NWS
gridpoint answers of every cell the wind field draws, the spill's cell and its
neighbours over the footprint's box plus one cell (HB-103; recorded on the day of the
run, so their grids do not cover a scenario's past hours, which the field leaves blank
and counts). No snapshot
is taken in record mode: a recording run reads the capabilities it recorded, whose scans
are past every scenario's time.
Every exchange is written once to `fixtures/exchanges/<api>/`, and the committed briefs
replay them.

Checkpoint plan (constitution section 15):
* **Unit and checkpoint.** One upstream exchange, written atomically by the client's
  recorder (`hazbrief.utils`, vcrpy's `new_episodes`). Re-running the same command is
  the resume: a recorded exchange is served from its file and never called again.
* **Ceiling.** `--max-calls` bounds every live GET in this process (the client's
  `_get_live` is wrapped, as the other recorders wrap it); the run stops before the call
  that would pass it and exits 3, and what it recorded stays.
* **Timeout.** NLDI's position query answered in 116 s on the HB-54 probe, past the
  client's 30 s, so this process raises the client's timeout to
  `derive.record_timeout_s` (orchestrator.yaml). Replay is unaffected.
* **Pilot.** The first scenario's live calls and seconds are printed and projected onto
  the rest before they run.
* **Progress.** One line per scenario, to stdout and `logs/<date>_HB-103_record.log`
  (HB-54's to HB-60's runs logged to `_HB-54_record.log`, `_HB-55_record.log`,
  `_HB-56_record.log`, `_HB-58_record.log`, `_HB-59_record.log` and
  `_HB-60_record.log`).
* **Failures.** A derivation that fails (a timeout, an error object) is recorded as the
  brief shows it, with its reason; the run continues, and a re-run retries what was not
  recorded. The recorder writes answers only, never a failure (HB-58): a failure is
  retried by the re-run, and the live brief's bounded NLDI wait is tested on an httpx
  mock transport instead (`test_brief_derive.py`).
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from hazbrief import utils  # noqa: E402
from hazbrief.brief import cli  # noqa: E402
from hazbrief.brief.orchestrator import assemble, load_config  # noqa: E402
from hazbrief.config import settings  # noqa: E402
from hazbrief.evidence import labels as L  # noqa: E402
from hazbrief.evidence import store as S  # noqa: E402

LOG = REPO / "logs" / f"{datetime.now(timezone.utc):%Y-%m-%d}_HB-103_record.log"


class CallCeiling(RuntimeError):
    """The next live call would pass `--max-calls`."""


def ceiling(max_calls: int) -> dict:
    """Wrap the client's live GET: count every call, refuse the one past `max_calls`."""
    count = {"calls": 0}

    def bound(live):
        async def bounded(*a, **kw):
            if count["calls"] >= max_calls:
                raise CallCeiling(
                    f"{count['calls']} live calls, the ceiling is {max_calls}"
                )
            count["calls"] += 1
            return await live(*a, **kw)

        return bounded

    # Every live GET passes through `_get_raw`: the JSON answers, the radar
    # capabilities (`fetch_bytes`; HB-56) and the land-cover byte ranges, which call it
    # directly (`fetch_range`; HB-59 ADDENDUM-03).
    utils._get_raw = bound(utils._get_raw)
    return count


def scenarios() -> list[dict]:
    spec = importlib.util.spec_from_file_location(
        "build_scenario_briefs", REPO / "scripts" / "build_scenario_briefs.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.replayable() + mod.location_scenarios()


def _log(row: dict) -> None:
    line = json.dumps(row, sort_keys=True)
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


async def record_one(s: dict) -> dict:
    brief = await assemble(
        s,
        now=S.parse_time(L.config()["fixture_now"]),
        replay_stores=cli.replay_stores(),
        derive_replay=False,
    )
    d = brief.derived
    cover = d["terrain"].get("cover") or {}
    return {
        "roads": len(d["roads"].get("candidates") or []),
        "roads_reason": d["roads"].get("reason"),
        "rail": len(d["rail"].get("candidates") or []),
        "downstream_reaches": len(d["downstream"].get("reaches") or []),
        "downstream_reason": d["downstream"].get("reason"),
        "downstream_source": d["downstream"].get("source"),
        "downstream_match": d["downstream"].get("match"),
        "workplace_blocks": len(d["workplaces"].get("jobs") or {}),
        "establishment_rows": len(d["establishments"].get("rows") or []),
        "establishments_reason": d["establishments"].get("reason"),
        "terrain_spill_m": d["terrain"].get("spill_m"),
        "terrain_reason": d["terrain"].get("reason"),
        "terrain_source": d["terrain"].get("elevation_source"),
        "terrain_fallback": d["terrain"].get("elevation_fallback"),
        "cover_spill": (cover.get("point") or {}).get("code"),
        "cover_mix_cells": (cover.get("mix") or {}).get("cells"),
        "cover_reason": d["terrain"].get("cover_reason"),
        "observation_station": d["observation"].get("station"),
        "observation_usable": d["observation"].get("usable"),
        "observation_reason": d["observation"].get("stale_reason")
        or d["observation"].get("reason"),
        "forecast_rows": len(d["forecast"].get("rows") or []),
        "forecast_reason": d["forecast"].get("reason"),
        "radar_time": d["radar"].get("time"),
        "radar_reason": d["radar"].get("reason"),
        "satellite_layer": d["satellite"].get("layer"),
        "satellite_reason": d["satellite"].get("reason"),
        "wind_cells": len(d["wind_field"].get("cells") or []),
        "wind_missing": len(d["wind_field"].get("missing") or []),
        "wind_reason": d["wind_field"].get("reason"),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scenario", action="append", help="only these scenario ids")
    ap.add_argument("--max-calls", type=int, default=1200)
    a = ap.parse_args(argv)
    if settings.hazbrief_http_mode != "record":
        print("FATAL: run with HAZBRIEF_HTTP_MODE=record", file=sys.stderr)
        return 2
    settings.upstream_timeout_seconds = float(
        load_config()["derive"]["record_timeout_s"]
    )
    count = ceiling(a.max_calls)
    todo = [s for s in scenarios() if not a.scenario or s["id"] in a.scenario]
    t0 = time.monotonic()
    for i, s in enumerate(todo, 1):
        before, t = count["calls"], time.monotonic()
        try:
            row = asyncio.run(record_one(s))
        except CallCeiling as exc:
            _log({"event": "ceiling", "scenario": s["id"], "detail": str(exc)})
            return 3
        row.update(
            event="scenario",
            scenario=s["id"],
            n=f"{i}/{len(todo)}",
            live_calls=count["calls"] - before,
            seconds=round(time.monotonic() - t, 1),
        )
        _log(row)
        if i == 1 and len(todo) > 1:
            per = max(row["seconds"], 1.0)
            _log(
                {
                    "event": "pilot",
                    "live_calls": row["live_calls"],
                    "seconds": row["seconds"],
                    "projected_seconds_at_most": round(per * (len(todo) - 1)),
                    "note": "scenarios sharing a spill point reuse its answers",
                }
            )
    _log(
        {
            "event": "end",
            "scenarios": len(todo),
            "live_calls": count["calls"],
            "seconds": round(time.monotonic() - t0, 1),
        }
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
