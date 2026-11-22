"""The source catalog, `docs/sources/catalog.yaml` (DN-010 section 3.2): a row by id, by
an exchange's url, and by tool, and the horizon a record carries.

A record that read several sources carries the shortest of their horizons: a brief built
from an hour-old wind and a year-old census count is stale when the wind is (the label
goes stale when its most perishable input does). `computed` rows have no horizon and do
not shorten it.
"""

from __future__ import annotations

import json
import re
from functools import cache

import yaml

from hazbrief.config import REPO_ROOT
from hazbrief.evidence.store import repo_path

ROW_FIELDS = (
    "id",
    "name",
    "kind",
    "endpoints",
    "tools",
    "named_as",
    "provenance_class",
    "horizon_s",
    "horizon_reason",
    "horizon_basis",
    "terms",
    "rate_limit",
)
HORIZON_REASONS = ("stated", "assumed", "computed")
PROVENANCE_CLASSES = ("recorded_pack", "live_call", "derived_by_code")


@cache
def load() -> dict:
    """The catalog, checked: every row has every field, a known reason and class, and a
    horizon exactly when its reason is not `computed`. A bad row stops the caller."""
    cat = yaml.safe_load(repo_path("catalog").read_text(encoding="utf-8"))
    seen = set()
    for row in cat["sources"]:
        missing = [f for f in ROW_FIELDS if f not in row]
        if missing:
            raise ValueError(f"catalog row {row.get('id')!r} lacks {missing}")
        if row["id"] in seen:
            raise ValueError(f"catalog row {row['id']!r} appears twice")
        seen.add(row["id"])
        if row["horizon_reason"] not in HORIZON_REASONS:
            raise ValueError(f"{row['id']}: horizon_reason {row['horizon_reason']!r}")
        if row["provenance_class"] not in PROVENANCE_CLASSES:
            raise ValueError(
                f"{row['id']}: provenance_class {row['provenance_class']!r}"
            )
        if (row["horizon_s"] is None) != (row["horizon_reason"] == "computed"):
            raise ValueError(f"{row['id']}: horizon_s is null exactly when computed")
        _check_as_of_fields(row)
    return cat


#: `edition_as_of`: the year alone, or a date (catalog header; HB-94).
_EDITION = re.compile(r"\d{4}(-\d{2}-\d{2})?")


def _check_as_of_fields(row: dict) -> None:
    """HB-94 (review L5-4, L5-2): a pack row states its edition's date and a file row
    names the field of the file that holds its as-of, so neither is ever labelled from
    a build or a call instant."""
    if row["kind"] == "pack":
        ed = row.get("edition_as_of")
        if not isinstance(ed, str) or not _EDITION.fullmatch(ed):
            raise ValueError(
                f"{row['id']}: a pack row needs edition_as_of, YYYY or YYYY-MM-DD "
                f"(got {ed!r})"
            )
    elif "edition_as_of" in row:
        raise ValueError(f"{row['id']}: edition_as_of is for kind: pack rows only")
    if "verified_current" in row:
        if row["kind"] != "pack":
            raise ValueError(
                f"{row['id']}: verified_current is for kind: pack rows only"
            )
        _check_verified_current(row)
    if row["kind"] == "file":
        fa = row.get("file_as_of")
        if not (isinstance(fa, dict) and set(fa) == {"path", "field"}):
            raise ValueError(
                f"{row['id']}: a file row needs file_as_of {{path, field}} (got {fa!r})"
            )
    elif "file_as_of" in row:
        raise ValueError(f"{row['id']}: file_as_of is for kind: file rows only")
    ss = row.get("service_stated")
    if ss is not None:
        ok = (
            isinstance(ss, dict)
            and set(ss) == {"read_on", "basis", "values"}
            and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(ss["read_on"]))
            and ss["values"]
            and all(
                isinstance(v, dict) and set(v) == {"path", "field"}
                for v in ss["values"]
            )
        )
        if not ok:
            raise ValueError(
                f"{row['id']}: service_stated needs read_on (YYYY-MM-DD), basis and "
                f"values [{{path, field}}] (got {ss!r})"
            )


VERIFIED_FIELDS = {"record", "checked_on", "against", "as_of"}


def _check_verified_current(row: dict) -> None:
    """HB-108: a pack row's `verified_current` is honoured only when its record, a
    committed file a script wrote, shows what the label will claim. Refused, naming the
    defect: a block without its four fields; a text no newer than the edition; a record
    of another pack, another build of it (`pack_sha256`), another text or date; and a
    record in which any row a fixture reads differs, or eCFR lists a substantive
    amendment after the text's point in time."""
    vc = row["verified_current"]
    rid = row["id"]
    if not (isinstance(vc, dict) and set(vc) == VERIFIED_FIELDS):
        raise ValueError(f"{rid}: verified_current needs {sorted(VERIFIED_FIELDS)}")
    for k in ("as_of", "checked_on"):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(vc[k])):
            raise ValueError(f"{rid}: verified_current {k} is not YYYY-MM-DD")
    if vc["as_of"] <= str(row["edition_as_of"]):
        raise ValueError(
            f"{rid}: verified_current as_of {vc['as_of']} is not newer than the "
            f"edition ({row['edition_as_of']})"
        )
    if vc["checked_on"] < vc["as_of"]:
        raise ValueError(f"{rid}: verified_current checked_on precedes as_of")
    rec = json.loads((REPO_ROOT / vc["record"]).read_text(encoding="utf-8"))
    pack = json.loads((REPO_ROOT / row["pack_file"]).read_text(encoding="utf-8"))
    against = rec["checked_against"]
    agree = {
        "pack_id": (rec["pack_id"], pack["pack_id"]),
        "pack_sha256": (rec["pack_sha256"], pack["sha256"]),
        "point_in_time": (against["point_in_time"], vc["as_of"]),
        "against": (against["name"], vc["against"]),
        "check_date": (rec["check_date"], vc["checked_on"]),
    }
    for field, (got, want) in agree.items():
        if got != want:
            raise ValueError(
                f"{rid}: verified_current record {vc['record']} {field} is {got!r}, "
                f"not {want!r}"
            )
    if rec["fixture_rows_differing"] or rec["fixture_rows_unchanged"] is not True:
        raise ValueError(
            f"{rid}: verified_current record {vc['record']}: fixture rows differ "
            "between the edition and the text checked; the pack is not shown current"
        )
    if rec["version_history"]["substantive_after_point_in_time"]:
        raise ValueError(
            f"{rid}: verified_current record {vc['record']} lists substantive "
            "amendments after the text checked"
        )


def rows() -> list[dict]:
    return load()["sources"]


def row(source_id: str) -> dict:
    for r in rows():
        if r["id"] == source_id:
            return r
    raise KeyError(f"no catalog row {source_id!r}")


def _specificity(r: dict, url: str) -> tuple | None:
    """How specifically row `r` matches `url`, or None: a row whose `path_suffix` the
    url's path ends with is more specific than one without, then the longer endpoint
    (longest-prefix match, as routing tables choose a route; HB-60: the NWS station
    list sits under the gridpoint forecast's prefix)."""
    path = url.split("?", 1)[0]
    suffix = r.get("path_suffix")
    if suffix and not path.endswith(suffix):
        return None
    lengths = [len(e) for e in r["endpoints"] if url.startswith(e)]
    return (bool(suffix), max(lengths)) if lengths else None


def row_for_exchange(api: str, url: str) -> dict:
    """The row whose `exchanges_api` is `api` that matches `url` most specifically
    (`_specificity`). None, or two equally specific, is a catalog defect, and stops
    the caller naming the url."""
    hits = sorted(
        (
            (s, r["id"], r)
            for r in rows()
            if r.get("exchanges_api") == api and (s := _specificity(r, url)) is not None
        ),
        key=lambda h: h[0],
        reverse=True,
    )
    if not hits or (len(hits) > 1 and hits[0][0] == hits[1][0]):
        raise LookupError(
            f"{len(hits)} catalog rows match {api} {url}: {[h[1] for h in hits]}"
        )
    return hits[0][2]


def rows_for_tool(tool: str) -> list[dict]:
    """Every row a tool reads, in catalog order. A tool with none is a catalog
    defect."""
    hits = [r for r in rows() if tool in r["tools"]]
    if not hits:
        raise LookupError(f"no catalog row lists the tool {tool!r}")
    return hits


def governing_horizon(source_rows: list[dict]) -> tuple[int | None, str | None]:
    """(the shortest horizon among the rows, the row it is from); (None, None) when
    every row is `computed`."""
    timed = [r for r in source_rows if r["horizon_s"] is not None]
    if not timed:
        return None, None
    best = min(timed, key=lambda r: (r["horizon_s"], r["id"]))
    return best["horizon_s"], best["id"]


def provenance_class_of(source_rows: list[dict]) -> str:
    """A call that read any live source is a live call; one that read only packs and
    files is a recorded pack; one that read only computation is derived by code."""
    classes = {r["provenance_class"] for r in source_rows}
    for c in ("live_call", "recorded_pack", "derived_by_code"):
        if c in classes:
            return c
    raise ValueError(f"no provenance class among {classes}")
