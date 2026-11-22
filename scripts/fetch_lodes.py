#!/usr/bin/env python3
"""Cache LEHD LODES8 workplace area characteristics (WAC) state files for
`population_at_risk` (HB-09), into `settings.hazbrief_lodes_dir` (fixtures/lodes/).

**Zero model spend.** One GET per state file, through `scripts/fetch_allowlisted.py`'s
`PoliteClient`: the allowlist checked before any socket opens, robots.txt first, one
identified user agent, per-host pacing and bounded backoff. The client's log is
`<dir>/fetch_log.jsonl`. Each file is named as LEHD names it (the requested citation
names the file; corpus/api_catalog.yaml `lodes`), written via an fsynced temporary file
and an atomic rename, and recorded with its url, sha256 and bytes in
`<dir>/MANIFEST.json` before the next file starts.

Checkpoint plan (constitution section 15). A unit is one state file, its key the url.
Re-running is the resume: a file whose bytes match its manifest row is skipped. A
gzip signature is required, so a saved error page is never cached. Ceilings are the
fetcher's own `ceiling_document_bytes` and `ceiling_wall_clock_seconds`
(corpus/fetch_config.yaml). There is no pilot: a run is a handful of files of known size
(0.1 to 2.4 MB for the corridor states, 2026-10-21).

    uv run python scripts/fetch_lodes.py md pa va dc
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from hazbrief import lodes  # noqa: E402
from hazbrief.census import sources  # noqa: E402
from hazbrief.config import settings  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "fetch_allowlisted", REPO / "scripts" / "fetch_allowlisted.py"
)
F = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(F)

GZIP_MAGIC = b"\x1f\x8b"


def _manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _write_atomic(path: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def run(states: list[str], directory: Path) -> int:
    cfg = F.load_config(REPO / "corpus" / "fetch_config.yaml")
    allowlist = F.load_allowlist(REPO / "corpus" / "allowlist.txt")
    directory.mkdir(parents=True, exist_ok=True)
    log = F.FetchLog(directory / "fetch_log.jsonl")
    client = F.PoliteClient(cfg, allowlist, log)
    manifest_path = directory / "MANIFEST.json"
    manifest = _manifest(manifest_path)
    t0, failures = time.monotonic(), 0
    for n, postal in enumerate(states, 1):
        if time.monotonic() - t0 > cfg["ceiling_wall_clock_seconds"]:
            print("[lodes] STOPPED: ceiling_wall_clock_seconds", file=sys.stderr)
            return 3
        name, url = lodes.file_name(postal), lodes.file_url(postal)
        target = directory / name
        row = manifest.get(name)
        if row and target.is_file():
            if hashlib.sha256(target.read_bytes()).hexdigest() == row["sha256"]:
                print(f"[lodes] {n}/{len(states)} {name}: already cached")
                continue
        client.doc_id = f"lodes-wac-{postal}"
        r = client.get(url)
        body = r.get("body")
        if r["outcome"] != "response" or r.get("status") != 200 or not body:
            failures += 1
            print(f"[lodes] {name}: {r['outcome']} {r.get('status')} {r.get('reason')}")
            continue
        if not body.startswith(GZIP_MAGIC):
            failures += 1
            print(f"[lodes] {name}: not gzip (leading bytes {body[:8]!r}); not cached")
            continue
        _write_atomic(target, body)
        lo = sources()["lodes"]
        manifest[name] = {
            "url": url,
            "sha256": hashlib.sha256(body).hexdigest(),
            "bytes": len(body),
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "lodes_version": lo["version"],
            "year": lo["year"],
            "citation": f'U.S. Census Bureau, "{name}," LEHD Origin-Destination '
            f"Employment Statistics, LODES {lo['version']}, "
            "https://lehd.ces.census.gov/data/lodes, accessed on "
            f"{datetime.now(timezone.utc).date().isoformat()}.",
        }
        _write_atomic(
            manifest_path,
            (json.dumps(manifest, indent=1, sort_keys=True) + "\n").encode("utf-8"),
        )
        print(f"[lodes] {n}/{len(states)} {name}: cached, {len(body):,} bytes")
    return 1 if failures else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("states", nargs="+", help="lowercase postal codes (md pa va dc)")
    ap.add_argument("--dir", type=Path, default=settings.hazbrief_lodes_dir)
    a = ap.parse_args(argv)
    unknown = sorted(set(a.states) - set(lodes.STATE_POSTAL.values()))
    if unknown:
        print(f"refused: unknown state code(s) {unknown}", file=sys.stderr)
        return 2
    return run(a.states, a.dir)


if __name__ == "__main__":
    sys.exit(main())
