#!/usr/bin/env python3
"""Record the location scenarios' briefs into the scenario-brief seed (HB-49 step 5).

    uv run python scripts/record_location_scenarios.py [--scenario ID] [--max-calls N]

For each scenario in `fixtures/location_scenarios.yaml`, the workbench assembles its
brief live, as the CLI would, with three differences:

* this process runs in `record` mode (`HAZBRIEF_HTTP_MODE=record`): the location
  resolver's GETs, and each tool run here before the server is asked (below), write
  every upstream exchange the brief needs to `fixtures/exchanges/` once;
* `used_for`: before each call, the tool runs in this process on the same parameters
  (recording what it lacks), the exchanges are migrated into the evidence seed
  (`scripts/migrate_exchanges_to_store.py`, idempotent), and the tool runs once more
  under the scenario manifest's watch (`scenario_manifest.py` `_watch`), which
  lists the exchange files it read. Those seed records are the call's `used`, as the
  scenario manifest gives them for the other committed briefs, so the map draws the
  geometry they hold. The server is then asked in `replay` mode: it can reach nothing;
* `reuse_held`: a tool call the store already holds, and that succeeded, is read, not
  made again, so the scenario-brief seed (`evidence/seed_briefs/`) is its own
  checkpoint.

The brief is then built by `scripts/build_scenario_briefs.py` with `--replay`, like the
other committed briefs.

Checkpoint plan (constitution section 15):
* **Unit and checkpoint.** One upstream exchange (written atomically by the client's
  recorder) and one tool-call record (written by the recording client). A re-run of the
  same command is the resume: recorded exchanges are not called again, held calls are
  not made again.
* **Ceiling.** `--max-calls` binds every live GET in this process (the client's
  `_get_live` is wrapped, as the other recorders wrap it), so a run stops before the
  call that would exceed it and exits 3; what it recorded stays. The server makes no
  live call (replay mode).
* **Pilot.** The first scenario's live calls and seconds are printed and projected onto
  the rest before they run.
* **Progress.** One line per scenario, to stdout and to `logs/<date>_HB-49_record.log`.
* **Failures.** A channel that fails is recorded as the brief shows it (degraded); the
  run continues to the next scenario.
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

# record mode in this process too: the resolver's GETs go through the same recorder
os.environ["HAZBRIEF_HTTP_MODE"] = "record"

import importlib.util  # noqa: E402

import yaml  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from hazbrief import utils  # noqa: E402
from hazbrief.brief.orchestrator import RENDER_ORDER, assemble  # noqa: E402
from hazbrief.evidence import labels as L  # noqa: E402
from hazbrief.evidence import store as S  # noqa: E402

SCENARIOS = REPO / "fixtures" / "location_scenarios.yaml"
EXCHANGES = REPO / "fixtures" / "exchanges"
LOG = REPO / "logs" / f"{datetime.now(timezone.utc):%Y-%m-%d}_HB-49_record.log"
#: two scenarios: the resolver's few GETs, then about 16 for the population and 11 for
#: the facilities (orchestrator.yaml's channel notes) each; twice that, as headroom
DEFAULT_MAX_CALLS = 120
#: the server's environment: replay, and a placeholder key so the operator's real key
#: never reaches the recorded process (record_tool_call_seed.py's ENV)
SERVER_ENV = {"HAZBRIEF_HTTP_MODE": "replay", "CENSUS_API_KEY": "replay-only-not-a-key"}


class CallCeiling(RuntimeError):
    pass


#: `--offline` (HB-133): no live call at all. Each tool reads only the exchanges held;
#: a tool that lacks one is asked anyway, in replay, and its structured error is
#: recorded as the point scenarios' recorder records it (`allow_errors`), so the brief
#: shows that section degraded and names the exchange. A later live run (without the
#: flag) calls again: a failed call is not reused (`assemble`'s `reuse_held`).
OFFLINE = {"on": False}


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MANIFEST = _script("scenario_manifest")
MIGRATE = _script("migrate_exchanges_to_store")
SEED = _script("record_tool_call_seed")


def ceiling(max_calls: int) -> dict:
    """Wrap the client's live GET: count every call, refuse the one past `max_calls`."""
    count = {"calls": 0}
    live = utils._get_live

    async def bounded(*a, **kw):
        if count["calls"] >= max_calls:
            raise CallCeiling(
                f"{count['calls']} live calls, the ceiling is {max_calls}"
            )
        count["calls"] += 1
        return await live(*a, **kw)

    utils._get_live = bounded
    return count


async def run_tool(name: str, params: dict):
    """The tool's body in this process, on the MCP parameters the brief sends it
    (`record_tool_call_seed.run_tool`, one runner for both recorders since HB-140)."""
    return await SEED.run_tool(name, params)


async def used_for(name: str, params: dict) -> list[str]:
    """The evidence-seed records of the exchanges the call reads (module docstring)."""
    from hazbrief.config import settings

    seed = S.repo_path("seed_store_dir")
    if not OFFLINE["on"]:
        await run_tool(name, params)
        MIGRATE.migrate(EXCHANGES, seed)
    # the watched run is a replay, so an exchange the recording run could not get (an
    # upstream that failed and made the tool answer a structured error) is refused
    # and named here, instead of the server's replay recording the call as an error
    # (HB-50: the Census API's intermittent answers after the outage)
    settings.hazbrief_http_mode = "replay"
    try:
        with MANIFEST._watch() as reads:
            try:
                await run_tool(name, params)
            except utils.UpstreamServiceError:
                # offline only (below): the exchange is not held; the server's own
                # replay answers the same error, which is what the record keeps
                if not OFFLINE["on"]:
                    raise
    finally:
        settings.hazbrief_http_mode = "record"
    if reads.refused and not OFFLINE["on"]:
        raise SystemExit(f"FATAL: {name} still lacks exchanges {sorted(reads.refused)}")
    by_key = SEED.exchange_entities(seed)
    return sorted({by_key[key] for _, key in reads.read})


def scenarios() -> list[dict]:
    return yaml.safe_load(SCENARIOS.read_text(encoding="utf-8"))["scenarios"]


def _files() -> int:
    return sum(1 for _ in EXCHANGES.glob("*/*.json"))


def _log(row: dict) -> None:
    line = json.dumps(row, sort_keys=True)
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())


async def record_one(s: dict) -> dict:
    store = S.repo_path("seed_briefs_store_dir")
    now = S.parse_time(L.config()["fixture_now"])
    brief = await assemble(
        s,
        now=now,
        store=store,
        env=SERVER_ENV,
        reuse_held=True,
        used_for=used_for,
        # offline (HB-133): the derivations read only what is held, as the replayed
        # build does; they are recorded by scripts/record_derivations.py, not here
        derive_replay=True if OFFLINE["on"] else None,
    )
    return {
        "id": s["id"],
        "sections": {n: brief.sections[n]["state"] for n in RENDER_ORDER},
        "samples": len(brief.samples) + 1,
        "location": brief.location and brief.location["label"],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--scenario", nargs="*", default=None)
    ap.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS)
    ap.add_argument(
        "--offline",
        action="store_true",
        help="no live call: record what the held exchanges answer (HB-133)",
    )
    args = ap.parse_args(argv)
    OFFLINE["on"] = args.offline
    if args.offline:
        args.max_calls = 0
    todo = [s for s in scenarios() if not args.scenario or s["id"] in args.scenario]
    count = ceiling(args.max_calls)
    for i, s in enumerate(todo):
        before, calls, t0 = _files(), count["calls"], time.monotonic()
        try:
            row = asyncio.run(record_one(s))
        except CallCeiling as exc:
            _log({"event": "ceiling", "id": s["id"], "detail": str(exc)})
            return 3
        secs = round(time.monotonic() - t0, 1)
        _log(
            {
                "event": "scenario",
                **row,
                "new_exchanges": _files() - before,
                "live_calls": count["calls"] - calls,
                "seconds": secs,
            }
        )
        if i == 0 and len(todo) > 1:
            _log(
                {
                    "event": "pilot",
                    "projected_live_calls": (count["calls"] - calls) * len(todo),
                    "projected_seconds": secs * len(todo),
                    "measured_on": s["id"],
                }
            )
    S.write_crate_manifest(S.repo_path("seed_briefs_store_dir"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
