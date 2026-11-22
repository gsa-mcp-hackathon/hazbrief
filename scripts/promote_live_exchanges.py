#!/usr/bin/env python3
"""Promote live recordings into the replay fixtures (HB-15 step 5; HB-05 P-14).

HB-05 part C recorded live exchanges into `fixtures/exchanges_live/<date>/`, which
replay never reads (docs/FIXTURES.md section 7). Promotion copies the ones a scenario's
tools need into `fixtures/exchanges/`, so the scenario replays. It is a decision, taken
in a task, and this script does only what the decision names:

* **Only what replay asks for.** Each named scenario's named tools run in replay (the
  manifest's runners, `scenario_manifest._run`); every exchange replay refuses that the
  live directory holds is copied, and the tools run again, until a pass copies nothing
  (a Census block query's answer names the next queries, so one pass is not enough).
* **Verified, never edited.** A file is copied byte for byte (its as-of headers and
  `recorded_at` with it) only if it records the `api` it is filed under and its url and
  body hash to its file name (`utils.exchange_key`), as `_read_exchange` checks on read.
  A destination that exists with other bytes stops the run: a recording is never
  replaced.
* **Copied, not moved.** The live directory is HB-05's record of its run
  (`calls.jsonl`, `drift.json` name these files); it stays whole.

Usage:
    uv run python scripts/promote_live_exchanges.py \\
        --live 2026-10-21/ \\
        --scenario un1075-fire-i81 --scenario un1203-i83 \\
        --tool population_at_risk --tool facilities_in_footprint [--dry-run]

Prints a JSON report: the files promoted per scenario and api, and the exchanges replay
still refuses that the live directory does not hold. No network: the mode is replay.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
os.environ.setdefault("HAZBRIEF_HTTP_MODE", "replay")
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

#: Passes before the closure is declared not to converge (each pass follows one more
#: link of a query chain; the Census chain is blocks, then tables by county).
MAX_PASSES = 10


class PromotionError(RuntimeError):
    """A live file that is not what its name says, or a destination with other bytes."""


def promote_one(live: Path, dest: Path, api: str, key: str, dry_run=False) -> bool:
    """Copy `live/<api>/<key>.json` to `dest/<api>/<key>.json` after checking it.
    Returns False when the live directory does not hold it; True when it was copied
    or is already there byte for byte."""
    from hazbrief.utils import exchange_key

    src = live / api / f"{key}.json"
    if not src.is_file():
        return False
    raw = src.read_bytes()
    rec = json.loads(raw)
    if rec.get("api") != api:
        raise PromotionError(f"{src}: records api {rec.get('api')!r}, filed as {api}")
    # every recorded exchange is a GET with an empty body (docs/FIXTURES.md section 2)
    if exchange_key(rec.get("method", "GET"), rec["url"]) != key:
        raise PromotionError(f"{src}: its url does not hash to its file name")
    out = dest / api / f"{key}.json"
    if out.exists():
        if out.read_bytes() != raw:
            raise PromotionError(f"{out} exists with other bytes; not replaced")
        return True
    if not dry_run:
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".json.tmp")
        tmp.write_bytes(raw)
        os.chmod(tmp, 0o644)  # as utils._write_exchange leaves a recording
        os.replace(tmp, out)
    return True


async def promote(live: Path, sids: list[str], tools: list[str], dry_run=False):
    import scenario_manifest as SM

    from hazbrief.config import settings

    if settings.hazbrief_http_mode != "replay":
        raise PromotionError("HAZBRIEF_HTTP_MODE must be replay")
    dest = Path(settings.hazbrief_exchanges_dir)
    by_id = {s["id"]: s for s in SM.scenarios()}
    unknown = [s for s in sids if s not in by_id]
    if unknown:
        raise PromotionError(f"unknown scenarios: {unknown}")
    promoted: dict = {}
    missing: dict = {}
    for _ in range(MAX_PASSES):
        copied = 0
        for sid in sids:
            s = by_id[sid]
            fp = await SM._run(s, SM._FIRST, None)
            for tool in tools:
                with SM._watch() as reads:
                    await SM._run(s, tool, fp)
                for api, key in sorted(reads.refused):
                    if promote_one(live, dest, api, key, dry_run):
                        done = promoted.setdefault(sid, {}).setdefault(api, [])
                        if key not in done:
                            done.append(key)
                            copied += 1
                    else:
                        missing.setdefault(sid, {}).setdefault(api, set()).add(key)
        if copied == 0 or dry_run:
            break
    else:
        raise PromotionError(f"no closure after {MAX_PASSES} passes")
    return {
        "live": str(live.relative_to(REPO) if live.is_absolute() else live),
        "dry_run": dry_run,
        "promoted": promoted,
        "files": sum(len(v) for p in promoted.values() for v in p.values()),
        "distinct_files": len(
            {(a, k) for p in promoted.values() for a, ks in p.items() for k in ks}
        ),
        "not_in_live": {
            sid: {a: sorted(k) for a, k in v.items()} for sid, v in missing.items()
        },
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--live", type=Path, required=True)
    ap.add_argument("--scenario", action="append", required=True)
    ap.add_argument("--tool", action="append", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    live = a.live if a.live.is_absolute() else REPO / a.live
    try:
        report = asyncio.run(promote(live, a.scenario, a.tool, a.dry_run))
    except PromotionError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
