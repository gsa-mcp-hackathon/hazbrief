"""Does the Census key work? One real data request, the answer read (HB-215 ADDENDUM-02
item 2; Issue 89d222a4).

    uv run python scripts/census_key_check.py
    # prints "key works ..." (exit 0), or why not (exit 1)

The key is the one the server resolves (`settings.census_api_key`: the environment, then
the project `.env`, then the master secrets file; README "The key"), and the request is
the server's own (`census.table_rows`, the dataset and total-population variable the
population tools read), for the one county in `census_key_check.yaml`. A value that is
empty or a `<...>` placeholder fails before any request; a key the Census Data API
refuses fails on its answer (the API answers a missing or invalid key with a page, not a
table). The key is never printed.

The check it replaces, `test -n "$CENSUS_API_KEY"`, printed "set" for the literal
placeholder `<key>` (HB-209's preflight; the operator, 2026-11-20 22:52 EST).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import yaml

from hazbrief import census
from hazbrief.config import settings
from hazbrief.utils import UpstreamServiceError

CONFIG = Path(__file__).with_suffix(".yaml")


def _placeholder(value: str) -> bool:
    v = value.strip()
    return not v or (v.startswith("<") and v.endswith(">"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.parse_args(argv)
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    key = settings.census_api_key or ""
    if _placeholder(key):
        print(
            "key not usable: CENSUS_API_KEY is empty or a placeholder; "
            f"request one at {census.KEY_SIGNUP_URL}"
        )
        return 1
    d = census.sources()["dhc"]
    try:
        rows = asyncio.run(
            census.table_rows(d["dataset"], [d["total"]], cfg["for"], cfg["in"])
        )
    except UpstreamServiceError as exc:
        print(f"key refused: the Census Data API answered without a table ({exc})")
        return 1
    if not rows or d["total"] not in rows[0]:
        print("key refused: the answer holds no total-population row")
        return 1
    print(
        f"key works: {d['label']} {d['total']} = {rows[0][d['total']]} "
        f"for {cfg['name']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
