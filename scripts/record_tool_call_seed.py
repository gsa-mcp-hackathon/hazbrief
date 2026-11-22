#!/usr/bin/env python3
"""Record the tool-call seed (HB-40 ADDENDUM-00 point 1): the seven tools on one
scenario.

    uv run python scripts/record_tool_call_seed.py               # into
    evidence/seed_calls/ uv run python scripts/record_tool_call_seed.py --store DIR

The recording client (`hazbrief.evidence.client`) spawns the server over stdio in replay
mode and makes each of the seven tools' calls on the scenario `evidence.yaml` names, in
the order `scenario_manifest.py` runs them (the footprint first, `build_ics_201`
last). Each record's `used` holds:
* the footprint record, for a call that takes the footprint as its input;
* the exchange records of `evidence/seed/` that the scenario manifest says the cell read
  (`fixtures/scenarios.yaml`, tool `exchanges`). For `build_ics_201` that is its own
  exchanges and every component cell's, because it runs them.

Idempotent: a call the store already holds (same tool, same parameters, a `used` that
names at least this call's, `records_for`; HB-99) is not made again, and its stored
entity is used in its place. A second run therefore writes nothing, and the files are
byte-identical. No network (replay), no model. Seven
calls take seconds, so the store itself is the checkpoint.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from hazbrief.brief.live_exchanges import run_tool  # noqa: E402,F401  (HB-208: moved there; read_by_call and the location recorder call it from here)
from hazbrief.brief.orchestrator import params_for  # noqa: E402
from hazbrief.evidence.client import RecordingClient  # noqa: E402
from hazbrief.evidence.store import (  # noqa: E402
    all_records,
    config,
    read_entity,
    records_for,
    repo_path,
    write_crate_manifest,
)
from hazbrief.utils import exchange_key  # noqa: E402

#: Replay mode reads only recorded exchanges. The population tool refuses to run
#: without a key, and replay never sends one, so a placeholder keeps the operator's
#: real key out of the process entirely.
ENV = {"HAZBRIEF_HTTP_MODE": "replay", "CENSUS_API_KEY": "replay-only-not-a-key"}
#: scenario_manifest's order: the footprint first (others read it), build_ics_201 last.
ORDER = (
    "protective_action_footprint",
    "assess_incident",
    "material_response_guidance",
    "population_at_risk",
    "facilities_in_footprint",
    "receiving_hospitals",
    "build_ics_201",
)
FOOTPRINT_READERS = (
    "population_at_risk",
    "facilities_in_footprint",
    "receiving_hospitals",
)


def scenario(sid: str) -> dict:
    doc = yaml.safe_load(
        (REPO / "fixtures" / "scenarios.yaml").read_text(encoding="utf-8")
    )
    for s in doc["scenarios"]:
        if s["id"] == sid:
            return s
    raise SystemExit(f"FATAL: no scenario {sid!r} in fixtures/scenarios.yaml")


def exchange_entities(seed: Path) -> dict[str, str]:
    """{exchange file key: the seed entity its record holds}."""
    out = {}
    for r in all_records(seed):
        if r["activity"]["type"] == "upstream_exchange":
            out[exchange_key("GET", r["activity"]["params"]["url"])] = r["entity"][
                "sha256"
            ]
    return out


def cell_exchanges(s: dict, tool: str, by_key: dict[str, str]) -> list[str]:
    """The seed entities the scenario manifest says this cell read. A key with no seed
    record is a seed defect, and stops the run naming it."""
    cells = [tool] + (
        [t for t in ORDER if t != "build_ics_201"] if tool == "build_ics_201" else []
    )
    out = []
    for cell in cells:
        for api, keys in (s["tools"][cell].get("exchanges") or {}).items():
            for k in keys:
                if k not in by_key:
                    raise SystemExit(
                        f"FATAL: {cell} read {api}/{k}, which the seed lacks"
                    )
                out.append(by_key[k])
    return sorted(set(out))


def _manifest_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "scenario_manifest", REPO / "scripts" / "scenario_manifest.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


async def read_by_call(name: str, params: dict, by_key: dict[str, str]) -> list[str]:
    """The exchange-seed entities this call reads (HB-140): the tool's body run in this
    process, in replay, under the scenario manifest's watch (`_watch`), on the brief's
    own parameters. The manifest's cells list what the manifest's request reads; a
    brief whose request differs (its wind record replaced the stated wind, HB-133) reads
    other exchanges, and its record's `used` must name those, since the map draws the
    geometry `used` holds (`layers.py`). An exchange replay refuses is not read, so it
    is not named; the server's own replay answers the same refusal."""
    from hazbrief import utils
    from hazbrief.config import settings

    watch = _manifest_module()._watch
    mode = settings.hazbrief_http_mode
    settings.hazbrief_http_mode = "replay"
    try:
        with watch() as reads:
            try:
                await run_tool(name, params)
            except utils.UpstreamServiceError:
                pass  # recorded as the server answers it (allow_errors)
    finally:
        settings.hazbrief_http_mode = mode
    missing = sorted(k for _, k in reads.read if k not in by_key)
    if missing:
        raise SystemExit(
            f"FATAL: {name} read exchanges the seed lacks {missing}; run "
            "scripts/migrate_exchanges_to_store.py"
        )
    return sorted({by_key[k] for _, k in reads.read})


async def brief_request(s: dict) -> dict:
    """The scenario as a brief asks the server about it (HB-133): its one wind record
    resolved from the held forecast at the incident point and the as-given hour, the
    request's `wind` replaced by it when the record is the forecast cell
    (`hazbrief.brief.wind_record`). Replay only: no network."""
    from hazbrief.brief import wind_record
    from hazbrief.brief.orchestrator import _point_of, load_config
    from hazbrief.evidence import labels as L
    from hazbrief.evidence.store import parse_time

    cfg = load_config()
    now = parse_time(L.config()["fixture_now"])
    rec, _ = await wind_record.resolve(s, _point_of(s), cfg, now=now, replay=True)
    return wind_record.request_scenario(s, rec)


async def record(
    store: Path,
    seed: Path,
    sid: str,
    *,
    allow_errors: bool = False,
    brief: bool = False,
    held_in: tuple[Path, ...] = (),
) -> dict:
    """The seven calls on scenario `sid` into `store`. With `allow_errors` (the
    scenario-brief seed, HB-45), a tool that answers a structured error is recorded as
    it answered, and the tools that read the footprint are not called when the
    footprint itself is an error; otherwise an error stops the run. With `brief`, the
    calls are the ones a brief makes (`brief_request`, HB-133), not the manifest's own;
    a call any of `held_in` already holds is read there, not made again."""
    s = scenario(sid)
    manifest_request = s
    if brief:
        s = await brief_request(s)
    # HB-140: the manifest's cells name what the manifest's request read; when the
    # brief's request differs, each call's `used` is what the brief's call reads
    watched = s != manifest_request
    by_key = exchange_entities(seed)
    counts = {
        "scenario": sid,
        "calls_made": 0,
        "calls_already_held": 0,
        "records": {},
        "errors": {},
        "not_called": [],
    }
    fp, fp_sha = None, None
    async with RecordingClient(store, env=ENV) as rc:
        for tool in ORDER:
            if tool in FOOTPRINT_READERS and fp_sha is None:
                counts["not_called"].append(tool)
                continue
            params = params_for(tool, s, fp)
            used = (
                await read_by_call(tool, params, by_key)
                if watched
                else cell_exchanges(s, tool, by_key)
            )
            if tool in FOOTPRINT_READERS:
                used = sorted(set(used) | {fp_sha})
            # keyed by `used` as well (HB-99): UN1746 on land and in water hand the
            # readers the same parameters but not the same footprint
            held, where = records_for(store, tool, params, used), store
            for other in held_in:
                if not held:
                    held, where = records_for(other, tool, params, used), other
            if held:
                sha = held[0]["entity"]["sha256"]
                payload = read_entity(where, sha)
                counts["calls_already_held"] += 1
            else:
                sha, payload = await rc.call(tool, params, used=used)
                counts["calls_made"] += 1
            if isinstance(payload, dict) and "error" in payload:
                if not allow_errors:
                    raise SystemExit(
                        f"FATAL: {tool} answered an error: {payload['error']}"
                    )
                counts["errors"][tool] = payload["error"]
                counts["records"][tool] = sha
                continue
            if tool == "protective_action_footprint":
                fp, fp_sha = payload, sha
            counts["records"][tool] = sha
    write_crate_manifest(store)
    return counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--store", type=Path, default=None)
    ap.add_argument("--seed", type=Path, default=None)
    ap.add_argument("--scenario", default=None)
    ap.add_argument(
        "--allow-errors",
        action="store_true",
        help="record a tool's structured error as answered (the scenario-brief seed)",
    )
    args = ap.parse_args(argv)
    counts = asyncio.run(
        record(
            args.store or repo_path("seed_calls_store_dir"),
            args.seed or repo_path("seed_store_dir"),
            args.scenario or config()["seed_calls_scenario"],
            allow_errors=args.allow_errors,
        )
    )
    print(json.dumps(counts, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
