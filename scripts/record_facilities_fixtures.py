"""Record the exchanges the HB-10 tests replay, and the counts they must reproduce.

Scenarios: HB-09's, the same footprints and points
(`fixtures/population/expected.json`: chlorine large spill, moderate wind, each point of
`fixtures/scenario_points.yaml` by day and by night, plus the open-water footprint).
For each, `facilities_in_footprint` runs with HAZBRIEF_HTTP_MODE=record, and
`receiving_hospitals` runs on the cached CMS file (no network). The outputs are
written to `fixtures/facilities/expected.json`, which the tests reproduce from replay.

`--scenario ID` (HB-17) records instead the footprint frozen in
`fixtures/scenarios/<ID>.json` (any scenario, HB-04's format), and writes no
`expected.json`: a scenario's outputs are its golden snapshot, which `eval_harness.py
regression` compares.

Checkpoint plan (constitution section 15). Unit: one exchange, written atomically as it
completes (`hazbrief.utils._write_exchange`); a scenario is a sequence of them.
Resume: re-run; recorded exchanges are not called again. Ceiling: `--max-calls` binds
every live call (the client's live GET is wrapped), so a run stops before the call that
would exceed it, exits 3, and what it recorded stays. Pacing: `--pace-seconds` between
live calls (none of the three services publishes a rate; this is courtesy). Pilot: the
first scenario; its live calls are measured and projected onto the rest before they
run. Progress: one line per scenario, to stdout and to `logs/<date>_HB-10_record.log`.

Usage: uv run python scripts/record_facilities_fixtures.py [--max-calls N]
           [--scenario ID ...]
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

REPO = Path(__file__).resolve().parents[1]
SCENARIOS = REPO / "fixtures" / "population" / "expected.json"
EXPECTED = REPO / "fixtures" / "facilities" / "expected.json"
FROZEN = REPO / "fixtures" / "scenarios"


class CallCeiling(RuntimeError):
    pass


def spill_point(footprint: dict) -> dict | None:
    for f in footprint.get("features") or []:
        if (f.get("properties") or {}).get("zone") == "spill":
            lon, lat = f["geometry"]["coordinates"]
            return {"latitude": lat, "longitude": lon}
    return None


def summary(facilities: dict, receiving: dict | None) -> dict:
    """What a replay must reproduce: counts, names, zones and ranks (no urls)."""
    if "error" in facilities:
        return {"error": facilities["error"]}

    def names(section):
        v = facilities[section]
        return None if v is None else [[r["name"], r["zone"]] for r in v]

    w, r = facilities["waterways"], facilities["rail"]
    out = {
        "counts": facilities["counts"],
        "flag_inputs": facilities["flag_inputs"],
        "schools": names("schools"),
        "hospitals": names("hospitals"),
        "nursing_homes": names("nursing_homes"),
        "emergency_services": names("emergency_services"),
        "waterways": None
        if w is None
        else {
            "named": w["named"],
            "in_isolation_zone": w["in_isolation_zone"],
            "flowline_m": sum(x["length_inside_m"] for x in w["flowlines"]),
            "waterbody_m2": sum(x["area_inside_m2"] for x in w["waterbodies"]),
        },
        "rail": None
        if r is None
        else {
            "owners": r["owners"],
            "length_inside_m": r["length_inside_m"],
            "crossings": [c["crossing_id"] for c in r["crossings"]],
        },
    }
    if "reason" in facilities:
        out["reason"] = facilities["reason"]
    if receiving is not None:
        out["receiving"] = (
            {"error": receiving["error"]}
            if "error" in receiving
            else {
                "top": [
                    [
                        h["name"],
                        h["distance_km"],
                        h["direction"],
                        h["crosses_footprint"],
                    ]
                    for h in receiving["hospitals"][:10]
                ],
                "inside_footprint": [h["name"] for h in receiving["inside_footprint"]],
                "measured_from": receiving["measured_from"]["kind"],
            }
        )
    return out


def frozen_cases(ids: list[str]) -> dict:
    """The footprint each named scenario froze (`fixtures/scenarios/<id>.json`)."""
    out = {}
    for sid in ids:
        path = FROZEN / f"{sid}.json"
        if not path.is_file():
            raise SystemExit(f"no frozen scenario {path}")
        tools = json.loads(path.read_text(encoding="utf-8"))["tools"]
        out[sid] = {"footprint": tools["protective_action_footprint"]["footprint"]}
    return out


async def run(
    max_calls: int, pace: float, log_path: Path, only: list[str] | None = None
) -> int:
    os.environ["HAZBRIEF_HTTP_MODE"] = "record"
    # Imported after the mode is set: settings are read once, at import.
    from hazbrief import utils
    from hazbrief.config import settings
    from hazbrief.models import FacilitiesInput, ReceivingInput
    from hazbrief.tools.facilities_in_footprint import list_facilities
    from hazbrief.tools.receiving_hospitals import rank

    if settings.hazbrief_http_mode != "record":
        raise RuntimeError("HAZBRIEF_HTTP_MODE did not take effect")

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
    scenarios = (
        frozen_cases(only)
        if only
        else json.loads(SCENARIOS.read_text(encoding="utf-8"))
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    expected, failures = {}, 0
    with log_path.open("a", encoding="utf-8") as log:

        def say(line: str) -> None:
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            print(f"{stamp} {line}", flush=True)
            log.write(f"{stamp} {line}\n")
            log.flush()

        say(f"start: {len(scenarios)} scenarios, --max-calls {max_calls}")
        t0 = time.monotonic()
        try:
            for i, (sid, case) in enumerate(sorted(scenarios.items()), start=1):
                before = calls["n"]
                fac = await list_facilities(
                    FacilitiesInput.model_validate({"footprint": case["footprint"]})
                )
                spill = spill_point(case["footprint"])
                rec = (
                    await rank(
                        ReceivingInput.model_validate(
                            {"location": spill, "footprint": case["footprint"]}
                        )
                    )
                    if spill
                    else None
                )
                if "error" in fac or fac.get("errors"):
                    failures += 1
                expected[sid] = {
                    "footprint": case["footprint"],
                    "spill": spill,
                    "result": summary(fac, rec),
                }
                made = calls["n"] - before
                say(
                    f"[{i}/{len(scenarios)}] {sid}: {made} live calls; counts "
                    f"{fac.get('counts')}; errors {fac.get('errors')}; total calls "
                    f"{calls['n']}; {time.monotonic() - t0:.0f} s"
                )
                if i == 1:
                    say(
                        f"pilot: {made} live calls for one scenario; at most "
                        f"{made * len(scenarios)} for {len(scenarios)}"
                    )
        except CallCeiling as exc:
            say(f"STOPPED: {exc}; recorded exchanges stay; re-run to resume")
            return 3
        finally:
            utils._get_live = live
        if only:
            say(f"done: {calls['n']} live calls, {failures} failed; no expected.json")
            return 1 if failures else 0
        EXPECTED.parent.mkdir(parents=True, exist_ok=True)
        EXPECTED.write_text(
            json.dumps(expected, indent=1, sort_keys=True) + "\n", encoding="utf-8"
        )
        say(f"done: {calls['n']} live calls, {failures} failed; wrote {EXPECTED}")
    return 1 if failures else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--max-calls", type=int, default=150)
    ap.add_argument("--pace-seconds", type=float, default=0.25)
    ap.add_argument("--scenario", action="append", help="a frozen scenario's footprint")
    args = ap.parse_args(argv)
    day = datetime.now().strftime("%Y-%m-%d")
    log = REPO / "logs" / f"{day}_HB-10_record.log"
    return asyncio.run(run(args.max_calls, args.pace_seconds, log, args.scenario))


if __name__ == "__main__":
    sys.exit(main())
