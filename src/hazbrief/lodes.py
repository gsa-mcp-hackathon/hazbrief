"""Daytime workforce for `population_at_risk` (HB-09): LEHD LODES8 workplace area
characteristics (WAC), read from the state files `scripts/fetch_lodes.py` caches in
`settings.hazbrief_lodes_dir`.

A WAC file counts jobs by the census block of the workplace (`w_geocode`); `C000` is
"Total number of jobs" (lodes8-techdoc-8-4, WAC file structure). A person with two jobs
counts twice, and a job counts where it is located, not where the worker is at the
incident hour. LODES is static files, not an API (corpus/api_catalog.yaml `lodes`), so
nothing is downloaded per incident. A state whose file is not cached is reported in
`missing_states`, and its blocks contribute nothing.
"""

from __future__ import annotations

import csv
import gzip
import io
from functools import lru_cache
from pathlib import Path

from hazbrief.census import Unit, sources
from hazbrief.config import settings

#: State FIPS code -> the lowercase postal code LODES names its files by (FIPS 5-2 /
#: ANSI INCITS 38 state codes; the 50 states, DC and Puerto Rico).
STATE_POSTAL = {
    "01": "al", "02": "ak", "04": "az", "05": "ar", "06": "ca", "08": "co", "09": "ct",
    "10": "de", "11": "dc", "12": "fl", "13": "ga", "15": "hi", "16": "id", "17": "il",
    "18": "in", "19": "ia", "20": "ks", "21": "ky", "22": "la", "23": "me", "24": "md",
    "25": "ma", "26": "mi", "27": "mn", "28": "ms", "29": "mo", "30": "mt", "31": "ne",
    "32": "nv", "33": "nh", "34": "nj", "35": "nm", "36": "ny", "37": "nc", "38": "nd",
    "39": "oh", "40": "ok", "41": "or", "42": "pa", "44": "ri", "45": "sc", "46": "sd",
    "47": "tn", "48": "tx", "49": "ut", "50": "vt", "51": "va", "53": "wa", "54": "wv",
    "55": "wi", "56": "wy", "72": "pr",
}  # fmt: skip


def file_name(postal: str) -> str:
    lo = sources()["lodes"]
    return f"{postal}_wac_{lo['segment']}_{lo['job_type']}_{lo['year']}.csv.gz"


def file_url(postal: str) -> str:
    lo = sources()["lodes"]
    return lo["url_template"].format(
        st=postal, segment=lo["segment"], job_type=lo["job_type"], year=lo["year"]
    )


@lru_cache(maxsize=8)
def _read(path: Path, column: str) -> dict[str, float]:
    with gzip.open(path, "rb") as fh:
        reader = csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8"))
        if "w_geocode" not in (reader.fieldnames or []) or column not in (
            reader.fieldnames or []
        ):
            # The file's name, never its path: the message can reach a client
            # (HB-89; review L3-5).
            raise RuntimeError(f"{path.name} is not a LODES WAC file with {column}")
        return {r["w_geocode"]: float(r[column]) for r in reader}


def jobs(blocks: list[Unit], lodes_dir: Path | None = None) -> dict:
    """Jobs located in the footprint: each block's C000 times its area share."""
    lo = sources()["lodes"]
    directory = Path(lodes_dir or settings.hazbrief_lodes_dir)
    total = partial = 0.0
    missing: set[str] = set()
    files = {}
    for b in blocks:
        postal = STATE_POSTAL.get(b.state)
        path = directory / file_name(postal) if postal else None
        if path is None or not path.is_file():
            missing.add(postal or b.state)
            continue
        files[postal] = path.name
        n = _read(path, lo["column"]).get(b.geoid, 0.0) * b.share
        total += n
        if b.kind == "partial":
            partial += n
    return {
        "jobs": total,
        "from_partial_blocks": partial,
        "files": sorted(files.values()),
        "missing_states": sorted(missing),
    }
