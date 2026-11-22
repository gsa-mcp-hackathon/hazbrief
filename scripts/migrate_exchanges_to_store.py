#!/usr/bin/env python3
"""Migrate the recorded exchanges into the evidence seed (DN-010 s3.4, HB-39 step 6).

    uv run python scripts/migrate_exchanges_to_store.py            # into evidence/seed/
    uv run python scripts/migrate_exchanges_to_store.py --store DIR

Reads every `fixtures/exchanges/<api>/<key>.json` (DN-005 section 2; `hazbrief.utils`
wrote them in `record` mode) and writes one record per exchange: the activity is the
upstream GET, the entity its body, the source the catalog row its url falls under. The
exchanges are read, never moved. As-of is the source's own Last-Modified when the
exchange carries one, else the time it was recorded (DN-010 D3). A body two exchanges
share is one entity with two records.

Idempotent: a record's activity id is a hash of the activity, so a second run writes
nothing and reports every exchange as already held. No network, no model; the run is
seconds, so it carries no checkpoint beyond the store itself (constitution 15 scopes
loops over two minutes or paid calls).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from hazbrief.evidence.exchange_records import record_exchange  # noqa: E402
from hazbrief.evidence.store import repo_path, write_crate_manifest  # noqa: E402


def migrate(exchanges_dir: Path, store: Path) -> dict:
    """Every exchange file under `exchanges_dir` as a record in `store`, by
    `hazbrief.evidence.exchange_records.record_exchange` (HB-208 moved the record's
    construction there, unchanged, so the live brief writes its exchanges the same
    way)."""
    files = sorted(exchanges_dir.glob("*/*.json"))
    if not files:
        raise SystemExit(f"FATAL: no exchange under {exchanges_dir}")
    counts = {
        "exchanges_read": 0,
        "records_written": 0,
        "records_already_held": 0,
        "entities_written": 0,
        "entities_deduplicated": 0,
        "by_source": {},
    }
    entities_seen: set[str] = set()
    for f in files:
        ex = json.loads(f.read_text(encoding="utf-8"))
        if ex["api"] != f.parent.name:
            raise SystemExit(
                f"FATAL: {f} records api {ex['api']!r}, not {f.parent.name!r}"
            )
        counts["exchanges_read"] += 1
        got = record_exchange(ex, store)
        sha = got["sha256"]
        if got["entity_new"]:
            counts["entities_written"] += 1
        elif sha in entities_seen:
            counts["entities_deduplicated"] += 1
        entities_seen.add(sha)
        counts["records_already_held" if got["record_held"] else "records_written"] += 1
        sid = got["source_id"]
        counts["by_source"][sid] = counts["by_source"].get(sid, 0) + 1
    write_crate_manifest(store)
    counts["by_source"] = dict(sorted(counts["by_source"].items()))
    return counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--store", type=Path, default=None, help="default: evidence.yaml seed_store_dir"
    )
    ap.add_argument("--exchanges", type=Path, default=None)
    ap.add_argument(
        "--json", type=Path, default=None, help="also write the counts here"
    )
    args = ap.parse_args(argv)
    store = args.store or repo_path("seed_store_dir")
    counts = migrate(args.exchanges or repo_path("seed_exchanges_dir"), store)
    text = json.dumps(counts, indent=1)
    print(text)
    if args.json:
        args.json.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
