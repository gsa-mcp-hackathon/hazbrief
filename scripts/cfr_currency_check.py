"""HB-108 Part A: is the cfr172 pack's Hazardous Materials Table still the law's?

The pack was built from the GovInfo annual edition of 49 CFR (Revised as of October 1,
2025), whose horizon has run out (docs/sources/catalog.yaml `pack:cfr172`). This script
checks the edition against a later held text of the section, the eCFR versioner XML at a
stated point in time, and against eCFR's version history read after that point:

1. Both tables are parsed by the pack's own readers (`pack_parsers.cfr_hazmat_rows` and
   `ecfr_hazmat_rows`) with no identification-number filter, and diffed row by row
   (HB-105's `hmt_diff.py`, landed here): a row is keyed by (identification number,
   description, hazard class) in the pack's comparison form; rows sharing a key compare
   in table order; a changed row differs in a compared column. Written to the diff TSV.
2. Every row a fixture reads (each material of the pack, and every UN or NA number a
   frozen scenario prints, ambiguous candidates included) is compared exactly, every
   column the pack keeps. A difference stops the check: the served guide could move
   (HB-108 step 1), and no record is written.
3. The version history must list no substantive amendment after the point in time.

On a pass it writes the currency-check record the catalog's `verified_current` cites.
Every input is a held file checked against its sha256; no network, no model call.

    uv run python scripts/cfr_currency_check.py [--check-date DATE] [--config PATH]

Exit 0 with the record written; exit 1 when the check is refused, naming why.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import pack_parsers as PP  # noqa: E402

CONFIG = REPO / "scripts" / "cfr_currency_check.yaml"
#: An identification number as a scenario prints it ("UN1017", "NA 1993").
_IDENT = re.compile(r"\b(UN|NA)\s?(\d{4})\b")


class CheckRefused(RuntimeError):
    """The held texts do not show the pack current; the message says why."""


class Everything:
    """A `wanted` set that contains every identification number."""

    def __contains__(self, _):
        return True


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _held(spec: dict) -> Path:
    path = REPO / spec["path"]
    if not path.is_file():
        raise CheckRefused(f"{spec['doc_id']}: {spec['path']} is not held")
    got = sha256(path)
    if got != spec["sha256"]:
        raise CheckRefused(
            f"{spec['doc_id']}: {spec['path']} sha256 {got} is not {spec['sha256']}"
        )
    return path


def dialect_form(text: str | None) -> str:
    """The pack's comparison form with every space removed: the two XML dialects space
    their italic runs differently ("Urea nitrate , dry" in GovInfo, "Urea nitrate,
    dry" in eCFR; "tetrafluoroethane or" against "tetrafluoroethaneor"), and a space
    is never the whole of a change to a table cell."""
    return re.sub(r"\s+", "", PP.compare_form(text or ""))


#: A Column 4 cell that is an identification number (49 CFR 172.101(e): "UN", "NA" or
#: "ID" and four digits).
_IDENT_CELL = re.compile(r"(UN|NA|ID)\d{4}")


def is_identification(cell: str) -> bool:
    return bool(_IDENT_CELL.fullmatch(cell or ""))


def _keyed(rows: dict) -> dict:
    """Rows by (identification number, description, hazard class), in dialect form.
    Rows whose Column 4 is not an identification number are left out: the GovInfo
    reader keeps a row with an empty one only when its ENT list reaches the column, the
    eCFR reader always (every TD is present), so such rows do not compare; GovInfo's
    repeated column-number row reads "(4)" there; and no material resolves through one
    (the pack is read by identification number)."""
    out = defaultdict(list)
    for ident, rs in rows.items():
        if not is_identification(ident):
            continue
        for r in rs:
            key = (
                ident,
                dialect_form(r["description"]),
                dialect_form(r["hazard_class"]),
            )
            out[key].append(r)
    return out


def table_diff(old: dict, new: dict, compared: list) -> dict:
    """{"added", "removed", "changed"} between two parsed tables' `rows`, by key."""

    def view(r):
        return {k: dialect_form(r.get(k)) for k in compared}

    a, b = _keyed(old), _keyed(new)
    added, removed, changed = [], [], []
    for key in sorted(set(a) | set(b)):
        ra, rb = a.get(key, []), b.get(key, [])
        for i in range(max(len(ra), len(rb))):
            x = ra[i] if i < len(ra) else None
            y = rb[i] if i < len(rb) else None
            if x is None:
                added.append({"un": key[0], "row": y, "fields": {}})
            elif y is None:
                removed.append({"un": key[0], "row": x, "fields": {}})
            elif view(x) != view(y):
                changed.append(
                    {
                        "un": key[0],
                        "row": y,
                        "fields": {
                            k: {"old": view(x)[k], "new": view(y)[k]}
                            for k in compared
                            if view(x)[k] != view(y)[k]
                        },
                    }
                )
    return {"added": added, "removed": removed, "changed": changed}


def fixture_ids(pack: dict, fixtures_dir: Path, prefix: str = "UN") -> list[str]:
    """Every identification number a fixture can read: the pack's materials, and every
    UN or NA number any frozen scenario prints."""
    ids = {f"{prefix}{un}" for un in pack["data"]["materials"]}
    for f in sorted(fixtures_dir.glob("*.json")):
        ids |= {a + b for a, b in _IDENT.findall(f.read_text(encoding="utf-8"))}
    return sorted(ids)


def fixture_differences(old: dict, new: dict, ids: list, columns: list) -> list:
    """The fixture identification numbers whose rows are not identical in every column
    the pack keeps, in table order, with both editions' rows."""
    out = []
    for ident in ids:
        a = [{k: r.get(k) for k in columns} for r in old.get(ident, [])]
        b = [{k: r.get(k) for k in columns} for r in new.get(ident, [])]
        if a != b:
            out.append({"identification_number": ident, "old": a, "new": b})
    return out


def substantive_after(history: dict, point_in_time: str) -> list:
    """The substantive versions eCFR lists dated after `point_in_time`."""
    return [
        v
        for v in history["content_versions"]
        if v.get("substantive") and v["date"] > point_in_time
    ]


def run(cfg: dict, check_date: str) -> tuple[dict | None, dict, list, str | None]:
    """(record or None, table diff, fixture differences, refusal or None)."""
    old_path, new_path = _held(cfg["old"]), _held(cfg["new"])
    hist_path = _held(cfg["version_history"])
    build = yaml.safe_load((REPO / cfg["build_config"]).read_text(encoding="utf-8"))
    cols = build["cfr"]["table_columns"]
    pack_path = REPO / cfg["pack_file"]
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    if build["cfr"]["doc_id"] != cfg["old"]["doc_id"]:
        raise CheckRefused(
            f"the pack is built from {build['cfr']['doc_id']}, "
            f"not {cfg['old']['doc_id']}"
        )
    old = PP.cfr_hazmat_rows(old_path, build["cfr"]["section"], cols, Everything())
    new = PP.ecfr_hazmat_rows(new_path, cols, Everything())
    diff = table_diff(old["rows"], new["rows"], cfg["compared_columns"])
    ids = fixture_ids(
        pack, REPO / cfg["fixtures_dir"], build["cfr"]["identification_prefix"]
    )
    fixtures = fixture_differences(
        old["rows"], new["rows"], ids, cfg["fixture_columns"]
    )
    history = json.loads(hist_path.read_text(encoding="utf-8"))
    later = substantive_after(history, cfg["new"]["point_in_time"])
    refusal = None
    if fixtures:
        refusal = (
            "fixture rows differ between the editions: "
            f"{[f['identification_number'] for f in fixtures]}"
        )
    elif later:
        refusal = (
            "eCFR lists substantive amendments after "
            f"{cfg['new']['point_in_time']}: {[v['date'] for v in later]}"
        )
    if refusal:
        return None, diff, fixtures, refusal
    n_old = sum(len(v) for k, v in old["rows"].items() if is_identification(k))
    n_new = sum(len(v) for k, v in new["rows"].items() if is_identification(k))
    record = {
        "schema": "hazbrief currency_check 1",
        "task": "HB-108",
        "pack_id": cfg["pack_id"],
        "pack_sha256": pack["sha256"],
        "pack_version": pack["version"],
        "edition": old["edition"],
        "checked_against": {
            "doc_id": cfg["new"]["doc_id"],
            "name": cfg["new"]["name"],
            "url": cfg["new"]["url"],
            "point_in_time": cfg["new"]["point_in_time"],
        },
        "version_history": {
            "doc_id": cfg["version_history"]["doc_id"],
            "retrieved_at": cfg["version_history"]["retrieved_at"],
            "latest_amendment_date": history["meta"]["latest_amendment_date"],
            "latest_issue_date": history["meta"]["latest_issue_date"],
            "substantive_after_point_in_time": [],
        },
        "rows_compared": {"old": n_old, "new": n_new},
        "identification_numbers": {
            "old": len([k for k in old["rows"] if is_identification(k)]),
            "new": len([k for k in new["rows"] if is_identification(k)]),
        },
        "rows_differing": {k: len(v) for k, v in diff.items()},
        "fixture_identification_numbers": ids,
        "fixture_rows_differing": [],
        "fixture_rows_unchanged": True,
        "check_date": check_date,
        "read": [
            {
                "doc_id": cfg[k]["doc_id"],
                "path": cfg[k]["path"],
                "sha256": cfg[k]["sha256"],
            }
            for k in ("old", "new", "version_history")
        ],
        "diff": cfg["out"]["diff_tsv"],
        "produced_by": "scripts/cfr_currency_check.py",
        "network": "none",
    }
    return record, diff, fixtures, None


def write_tsv(path: Path, diff: dict, fixtures: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(["kind", "identification_number", "description", "hazard_class",
                    "field", "old", "new"])  # fmt: skip
        for kind in ("added", "removed", "changed"):
            for d in diff[kind]:
                r = d["row"]
                fields = d["fields"] or {"": {"old": "", "new": ""}}
                for f, v in fields.items():
                    w.writerow([kind, d["un"], r["description"], r["hazard_class"], f,
                                v["old"], v["new"]])  # fmt: skip
        for f in fixtures:
            w.writerow(["fixture_row_differs", f["identification_number"], "", "", "",
                        json.dumps(f["old"]), json.dumps(f["new"])])  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", type=Path, default=CONFIG)
    ap.add_argument(
        "--check-date",
        default=datetime.now(timezone.utc).date().isoformat(),
        help="the date the check is recorded as made (default: today, UTC)",
    )
    a = ap.parse_args(argv)
    cfg = yaml.safe_load(a.config.read_text(encoding="utf-8"))
    try:
        record, diff, fixtures, refusal = run(cfg, a.check_date)
    except CheckRefused as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 1
    write_tsv(REPO / cfg["out"]["diff_tsv"], diff, fixtures)
    counts = {k: len(v) for k, v in diff.items()}
    print(f"table diff: {counts}; written {cfg['out']['diff_tsv']}")
    if refusal:
        print(f"REFUSED: {refusal}; no record written", file=sys.stderr)
        return 1
    out = REPO / cfg["out"]["record"]
    out.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
    print(
        f"fixture ids checked {len(record['fixture_identification_numbers'])}, "
        f"all unchanged; written {cfg['out']['record']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
