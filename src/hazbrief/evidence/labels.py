"""The label on every value, and the evidence appendix (DN-010 D4 to D6; HB-40).

A label is a view of a record, never a second store (D4). `label_for(record, now, body)`
is pure: it reads the record, the entity body when the record is a tool call, and the
catalog.

**Which sources a tool-call label names.** Each tool's docstring gives its as-of as its
`basis` source tags (`build_ics_201`: Annex A's `sources`). A tag names its source as
the source names itself, so the label matches each tag to the catalog rows of the
record's sources by the row's `tag_as` phrases (else its `named_as`). The most specific
phrase wins: a row whose matching phrase another matching row's phrase contains is not
matched, so "TIGERweb Census 2020" beats the bare "TIGERweb". A tag a request parameter
gave, such as a wind the caller supplied ("[worked example wind, as of ...]", the
request's `wind.source`), is a `caller_supplied` source (DN-010 ADDENDUM-00): source
`request`, the parameter's name, as-of the activity's start, and no horizon (it cannot
go stale; it can only be wrong). Any other tag that matches no row is listed in
`unmatched_tags` with its as-of. A source row no tag names is listed in `not_cited`.

**As-of, per source** (`as_of_from`):
* `payload`: the oldest as-of among the source's tags ("as of 04/01/2020", "updated
  2026-10-19", "Data refreshed September 4, 2026", "Data Refreshed October, 2026" read
  as the first of the month, "January 1, 2020 vintage", and a time in a zone of
  `labels.yaml`);
* `pack`: for a pack whose tags carry no date, the catalog row's `edition_as_of`, the
  date the held edition prints (HB-94, review L5-4; precision `year` when it prints
  only the year). The pack's `built_at` is build provenance and is never an as-of;
* `verified_current`: for such a pack whose catalog row carries a `verified_current`
  (HB-108), the point in time of the later text the edition was checked against; the
  label says what it was checked against and cites the check's record;
* `file`: for a cached file (`kind: file`) whose tags carry no date, the field of the
  file the row's `file_as_of` names (HB-94, review L5-2). A file never takes the
  record's as-of: the call that read it says nothing of the file's age;
* `record`: otherwise (an API or a computation), the record's `as_of` (an exchange's
  Last-Modified or recorded time, or a tool call's end).

**Stale** (D4) per source is `store.is_stale` against the source's own horizon. The
label is stale when any of its sources is. Its top-level `source`, `endpoint` and
`as_of` are those of the source that goes stale first. A computed source (`code:astral`)
never goes stale.

**Margin** is present only when the body carries one: every non-null `moe` the tool
returned, by its path (`characteristics.age_65_and_over.moe`).
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timedelta, timezone
from functools import cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from hazbrief.config import REPO_ROOT
from hazbrief.evidence import catalog
from hazbrief.evidence.store import (
    is_stale,
    parse_time,
    read_entity,
    record_by,
)

CONFIG_FILE = Path(__file__).with_name("labels.yaml")
MONTHS = {
    m: i + 1
    for i, m in enumerate(
        "January February March April May June July August September October "
        "November December".split()
    )
}
_MONTH = "|".join(MONTHS)
#: Each date form a source tag prints, as (pattern, how to read it). Tried in order.
_TAG_DATES = [
    # "as of 10/20/2026 22:52 EDT"
    (
        re.compile(r"(\d{2})/(\d{2})/(\d{4}) (\d{2}):(\d{2}) ([A-Z]{2,4})\b"),
        "mdy_hm_zone",
    ),
    # "as of 04/01/2020"
    (re.compile(r"(\d{2})/(\d{2})/(\d{4})"), "mdy"),
    # "as of 2026-09-30", "updated 2026-10-19"
    (re.compile(r"(\d{4})-(\d{2})-(\d{2})"), "ymd"),
    # "Data refreshed September 4, 2026", "January 1, 2020 vintage"
    (re.compile(rf"({_MONTH}) (\d{{1,2}}), (\d{{4}})"), "month_d_y"),
    # "Data Refreshed October, 2026"
    (re.compile(rf"({_MONTH}), (\d{{4}})"), "month_y"),
]


@cache
def config() -> dict:
    cfg = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8"))
    need = {
        "hash_prefix_chars",
        "zone_offsets_h",
        "default_time_zone",
        "fixture_now",
        "fixture_time_zone",
        "appendix_columns",
        "ics201_internal_outputs",
    }
    missing = sorted(need - set(cfg or {}))
    if missing:
        raise RuntimeError(f"{CONFIG_FILE} is missing {missing}")
    return cfg


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def tag_date(tag: str) -> str | None:
    """The as-of a source tag prints, as UTC ISO 8601, or None when it prints none. A
    time in a zone `labels.yaml` does not list is refused, naming it. A date with no
    time reads as 00:00 UTC that day; `tag_precision` says it is a day, so it prints as
    the date alone."""
    for pat, form in _TAG_DATES:
        m = pat.search(tag)
        if not m:
            continue
        g = m.groups()
        if form == "mdy_hm_zone":
            offsets = config()["zone_offsets_h"]
            if g[5] not in offsets:
                raise ValueError(
                    f"tag {tag!r}: zone {g[5]!r} is not in {CONFIG_FILE.name}"
                )
            tz = timezone(timedelta(hours=offsets[g[5]]))
            dt = datetime(
                int(g[2]), int(g[0]), int(g[1]), int(g[3]), int(g[4]), tzinfo=tz
            )
        elif form == "mdy":
            dt = datetime(int(g[2]), int(g[0]), int(g[1]), tzinfo=timezone.utc)
        elif form == "ymd":
            dt = datetime(int(g[0]), int(g[1]), int(g[2]), tzinfo=timezone.utc)
        elif form == "month_d_y":
            dt = datetime(int(g[2]), MONTHS[g[0]], int(g[1]), tzinfo=timezone.utc)
        else:
            dt = datetime(int(g[1]), MONTHS[g[0]], 1, tzinfo=timezone.utc)
        return _iso(dt)
    return None


#: A source tag as the Markdown form prints it: square brackets before the full stop
#: (SB-NUM-04). A Markdown link or image (`](`) is not a tag.
_MD_TAG = re.compile(r"\[([^\[\]]+)\](?!\()")


def tag_precision(tag: str) -> str:
    """`minute` when the tag prints a time, else `day`."""
    return "minute" if _TAG_DATES[0][0].search(tag) else "day"


def payload_tags(body: Any) -> list[str]:
    """The source tags a tool payload carries: `basis[].tag`; for build_ics_201
    detailed, Annex A's `sources[].tag`; for build_ics_201 concise, the bracketed tags
    its Markdown prints (SB-NUM-04). A body that is not a tool's JSON object carries
    none."""
    if not isinstance(body, dict):
        return []
    if isinstance(body.get("annex"), dict):
        return [s["tag"] for s in body["annex"].get("sources") or [] if s.get("tag")]
    if "basis" in body:
        return [b["tag"] for b in body["basis"] if isinstance(b, dict) and b.get("tag")]
    if isinstance(body.get("markdown"), str):
        return list(dict.fromkeys(f"[{t}]" for t in _MD_TAG.findall(body["markdown"])))
    return []


def match_tag(tag: str, rows: list[dict]) -> list[dict]:
    """The rows a tag names, most specific phrase first (module docstring)."""
    hits = []
    for r in rows:
        phrases = [p for p in (r.get("tag_as") or r["named_as"]) if p in tag]
        if phrases:
            hits.append((max(phrases, key=len), r))
    return [r for p, r in hits if not any(p != q and p in q for q, _ in hits)]


def caller_sources(params: Any, path: str = "") -> dict[str, str]:
    """{the `source` a request parameter names: that parameter's path}. A caller that
    hands the tool a value names where it came from in the value's own `source`
    (`WindObservation.source`), and the tool prints that name in its tag."""
    out: dict[str, str] = {}
    if isinstance(params, dict):
        src = params.get("source")
        if path and isinstance(src, str) and src.strip():
            out[src.strip()] = path
        for k, v in params.items():
            out |= caller_sources(v, f"{path}.{k}" if path else k)
    return out


def margins(body: Any, path: str = "") -> dict[str, float]:
    """Every non-null `moe` in the body, by dotted path."""
    out: dict[str, float] = {}
    if isinstance(body, dict):
        for k, v in body.items():
            p = f"{path}.{k}" if path else k
            if k == "moe" and isinstance(v, (int, float)) and not isinstance(v, bool):
                out[p] = v
            else:
                out |= margins(v, p)
    elif isinstance(body, list):
        for i, v in enumerate(body):
            out |= margins(v, f"{path}[{i}]")
    return out


def _edition_as_of(row: dict) -> tuple[str, str]:
    """(as-of, precision) of a pack row: its catalog `edition_as_of`, the date the held
    edition prints (HB-94, review L5-4). A year alone reads as 1 January of it with
    precision `year`. The pack's `built_at` is build provenance, never an as-of."""
    ed = row["edition_as_of"]
    if len(ed) == 4:
        return _iso(datetime(int(ed), 1, 1, tzinfo=timezone.utc)), "year"
    return _iso(datetime.fromisoformat(ed).replace(tzinfo=timezone.utc)), "day"


def _verified_as_of(row: dict) -> tuple[str, str]:
    """(as-of, precision) of a pack row whose edition was checked against a later text
    (HB-108): the text's point in time, the date the check shows the edition still the
    source's. Not the date the check ran, which may be later than the instant a brief
    is rendered at (`fixture_now`); the catalog loader has checked the record."""
    d = row["verified_current"]["as_of"]
    return _iso(datetime.fromisoformat(d).replace(tzinfo=timezone.utc)), "day"


@cache
def _file_field(path: str, field: str) -> str:
    rel = REPO_ROOT / path
    text = rel.read_text(encoding="utf-8")
    doc = json.loads(text) if rel.suffix == ".json" else yaml.safe_load(text)
    for part in field.split("."):
        doc = doc[part]
    if not isinstance(doc, str):
        raise ValueError(f"{path} {field} is {doc!r}, not a date")
    return doc


def _service_stated_dates(row: dict) -> set[str]:
    """The as-of dates (UTC ISO) of the values a row's `service_stated` names: dates the
    service stated in its own description, read once and typed into config (HB-94,
    review L5-3). Empty for a row without one."""
    ss = row.get("service_stated")
    if not ss:
        return set()
    out = set()
    for v in ss["values"]:
        d = tag_date(_file_field(v["path"], v["field"]))
        if d is None:
            raise ValueError(f"{row['id']}: {v['path']} {v['field']} prints no date")
        out.add(d)
    return out


def _file_as_of(row: dict) -> tuple[str, str]:
    """(as-of, precision) of a file row: the field its catalog `file_as_of` names in
    the committed file (HB-94, review L5-2). A date reads as that day; a time, as that
    instant."""
    v = _file_field(row["file_as_of"]["path"], row["file_as_of"]["field"])
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        return _iso(datetime.fromisoformat(v).replace(tzinfo=timezone.utc)), "day"
    return _iso(parse_time(v)), "instant"


def label_for(
    record: dict | None,
    now: datetime,
    body: Any = None,
    *,
    only: list[str] | None = None,
) -> dict:
    """The label of one record (D4). `body` is the entity, read for a tool call's tags
    and margins; a record without its body is labelled from the record alone. `only`
    restricts the label to those catalog rows of the record (a part of build_ics_201's
    output that reads only them); among them, a row no tag names is labelled from the
    record or its pack. A value with no record, or a narrated one, cannot be labelled
    (D5) and raises."""
    if record is None:
        raise ValueError(
            "no record: a value without a record carries no label (DN-010 D5)"
        )
    if record.get("provenance_class") == "narrated_by_model":
        raise ValueError(
            "a narrated value is never a record and has no label (DN-010 D5)"
        )
    rows = [catalog.row(s["id"]) for s in record["agent"]["source"]]
    if only is not None:
        unknown = sorted(set(only) - {r["id"] for r in rows})
        if unknown:
            raise ValueError(f"{unknown} are not sources of this record")
        rows = [r for r in rows if r["id"] in only]
    endpoints = {s["id"]: s["endpoint"] for s in record["agent"]["source"]}
    tool_call = record["activity"]["type"] == "mcp_tool_call"
    tags = (
        payload_tags(body)
        if tool_call and record["entity"]["encoding"] == "json"
        else []
    )
    cited: dict[str, list[str]] = {r["id"]: [] for r in rows}
    unmatched = []
    given = caller_sources(record["activity"].get("params")) if tool_call else {}
    supplied: dict[str, str] = {}
    for tag in tags:
        hit = match_tag(tag, rows)
        for r in hit:
            cited[r["id"]].append(tag)
        if hit:
            continue
        param = next((p for src, p in given.items() if tag.startswith(f"[{src}")), None)
        if param is not None:
            supplied.setdefault(param, tag)
        else:
            unmatched.append(
                {
                    "tag": tag,
                    "as_of": tag_date(tag),
                    "as_of_precision": tag_precision(tag),
                }
            )
    if tags and not any(cited.values()) and only is None:
        raise LookupError(f"no tag of {record['activity']['name']} names a catalog row")
    named = [r for r in rows if cited[r["id"]]] if any(cited.values()) else rows
    if only is not None:
        # a part of the output that reads only these rows: the rest of the record's
        # tags, a caller's value among them, belong to other parts
        unmatched, supplied = [], {}
    sources = []
    for r in named:
        dates = [(d, tag_precision(t)) for t in cited[r["id"]] if (d := tag_date(t))]
        read_on = verified = None
        if dates:
            (as_of, precision), frm = (
                min(dates, key=lambda d: parse_time(d[0])),
                "payload",
            )
            if as_of in _service_stated_dates(r):
                read_on = r["service_stated"]["read_on"]
        elif r["kind"] == "pack" and "verified_current" in r:
            (as_of, precision), frm = _verified_as_of(r), "verified_current"
            verified = r["verified_current"]
        elif r["kind"] == "pack":
            (as_of, precision), frm = _edition_as_of(r), "pack"
        elif r["kind"] == "file":
            (as_of, precision), frm = _file_as_of(r), "file"
        else:
            as_of, precision, frm = record["as_of"], "instant", "record"
        stale = is_stale({"as_of": as_of, "horizon_s": r["horizon_s"]}, now)
        # HB-158 item 5: a past-limit source prints its age and its limit, the fact the
        # word "stale" stood for; the age is the reading's, at `now`
        age_s = (now - parse_time(as_of)).total_seconds()
        sources.append(
            {
                "id": r["id"],
                "name": r["name"],
                "endpoint": endpoints.get(r["id"]),
                "provenance_class": r["provenance_class"],
                "as_of": as_of,
                "as_of_precision": precision,
                "as_of_from": frm,
                "horizon_s": r["horizon_s"],
                "age_s": age_s,
                "stale": stale,
            }
            | ({"service_read_on": read_on} if read_on else {})
            | (
                {"verified_against": verified["against"], "record": verified["record"]}
                if verified
                else {}
            )
        )
    for param, tag in sorted(supplied.items()):
        sources.append(
            {
                "id": "request",
                "name": "request",
                "parameter": param.rsplit(".", 1)[-1],
                "tag": tag,
                "endpoint": None,
                "provenance_class": "caller_supplied",
                "as_of": record["activity"]["startedAtTime"],
                "as_of_precision": "instant",
                "as_of_from": "request",
                "horizon_s": None,
                "stale": False,
            }
        )
    timed = [s for s in sources if s["horizon_s"] is not None]
    first = (
        min(
            timed,
            key=lambda s: parse_time(s["as_of"]) + timedelta(seconds=s["horizon_s"]),
        )
        if timed
        else sources[0]
    )
    label = {
        "provenance_class": record["provenance_class"],
        "source": first["name"],
        "endpoint": first["endpoint"],
        "as_of": first["as_of"],
        "as_of_precision": first["as_of_precision"],
        "as_of_from": first["as_of_from"],
        "stale": any(s["stale"] for s in sources),
        "hash": record["entity"]["sha256"],
        "sources": sources,
        "not_cited": [r["id"] for r in rows if r not in named],
        "unmatched_tags": unmatched,
    }
    m = margins(body) if tool_call else {}
    if m:
        label["margin"] = m
    return label


# ── reading records across the stores a brief cites ──────────────────────────────────


def latest(stores: list[Path], sha: str, by: str | None = None) -> tuple[dict, Any]:
    """(the newest record of entity `sha`, its body) from the first store that holds
    it; with `by`, the newest made no later than `by` (`store.record_by`)."""
    for store in stores:
        try:
            rec = record_by(store, sha, by)
        except FileNotFoundError:
            continue
        return rec, read_entity(store, sha)
    raise FileNotFoundError(f"no store of {[str(s) for s in stores]} holds {sha}")


# ── the appendix (D6) ─────────────────────────────────────────────────────────────────


def when(iso: str, tz: str, precision: str = "instant") -> str:
    """SB-NUM-06: month/day/year, 24-hour clock, the zone: "10/20/2026 13:40 EDT". A
    date the source gave without a time prints as that date alone, unshifted by any
    zone. An edition that prints only its year (HB-94) prints as the year."""
    if precision == "year":
        return parse_time(iso).astimezone(timezone.utc).strftime("%Y")
    if precision == "day":
        return parse_time(iso).astimezone(timezone.utc).strftime("%m/%d/%Y")
    dt = parse_time(iso).astimezone(ZoneInfo(tz))
    return dt.strftime("%m/%d/%Y %H:%M ") + dt.strftime("%Z")


def asked(record: dict) -> str:
    """What the activity asked, in a few plain words."""
    a = record["activity"]
    if a["type"] == "upstream_exchange":
        url = a["params"]["url"].split("?", 1)[0]
        return f"{a['params']['method']} {url}"
    p = a["params"]
    inc = p.get("incident") or (p.get("request") or {}).get("incident") or {}
    what = a["name"].replace("_", " ")
    bits = []
    if inc.get("material"):
        bits.append(str(inc["material"]))
    loc = inc.get("location")
    if loc:
        bits.append(f"{loc['latitude']}, {loc['longitude']}")
    if "area" in p or "footprint" in inc:
        bits.append("in the footprint")
    return what + (f" ({'; '.join(bits)})" if bits else "")


def _row(record: dict, label: dict, tz: str) -> list[str]:
    n = config()["hash_prefix_chars"]
    names = "; ".join(s["name"] for s in label["sources"])
    return [
        names,
        asked(record),
        when(label["as_of"], tz, label["as_of_precision"]),
        state_cell(label),
        label["hash"][:n],
    ]


def _caller_rows(label: dict, tz: str) -> list[list[str]]:
    """One appendix row per value the request gave (DN-010 ADDENDUM-00), under its
    record, so a commander sees which numbers were typed in rather than read."""
    n = config()["hash_prefix_chars"]
    return [
        [
            f"request ({s['parameter']})",
            f"{s['parameter']} as given by the requester",
            when(s["as_of"], tz),
            "as given",
            label["hash"][:n],
        ]
        for s in label["sources"]
        if s["provenance_class"] == "caller_supplied"
    ]


def _location_row(loc: dict, label: dict, tz: str) -> list[str]:
    """The row of a location record (DN-013 section 2; HB-48) under the record whose
    request gave it, beside that request's other values (`_caller_rows`)."""
    n = config()["hash_prefix_chars"]
    return [
        f"{loc['source']} (location)",
        f"location as given by the requester ({loc['derivation']}): {loc['label']}",
        when(loc["as_of"], tz),
        "as given",
        label["hash"][:n],
    ]


def appendix_rows(
    hashes: list[str],
    now: datetime,
    stores: list[Path],
    tz: str | None = None,
    locations: dict[str, dict] | None = None,
    records: dict[str, dict] | None = None,
) -> list[tuple[int, list[str]]]:
    """(depth, cells) per row: each cited record in hash order, then the records it
    used, indented once (depth 1), in hash order. A used hash no store holds is a row
    that says so. `locations` maps a cited record's hash to the location record its
    request gave (the brief's spill point, HB-48), printed beside the request's
    values.

    `records` maps a cited hash to the record the citer read (a brief's channel
    record). A body two scenarios' calls both returned is one entity with a record per
    call, and the newest of them is the other scenario's whenever it was recorded
    later: its `used` names that scenario's footprint (HB-99, Issue e4074961). A hash
    not in `records` reads the newest record (`latest`)."""
    tz = tz or config()["default_time_zone"]
    locations = locations or {}
    records = records or {}
    out = []
    for sha in sorted(set(hashes)):
        rec, body = latest(stores, sha)
        rec = records.get(sha, rec)
        lab = label_for(rec, now, body)
        out.append((0, _row(rec, lab, tz)))
        out += [(1, cells) for cells in _caller_rows(lab, tz)]
        if sha in locations:
            out.append((1, _location_row(locations[sha], lab, tz)))
        for u in rec["used"]:
            try:
                urec, ubody = latest(stores, u, rec["activity"]["startedAtTime"])
            except FileNotFoundError:
                n = config()["hash_prefix_chars"]
                out.append((1, ["not in the store", "", "", "", u[:n]]))
                continue
            out.append((1, _row(urec, label_for(urec, now, ubody), tz)))
    return out


def appendix(
    hashes: list[str],
    now: datetime,
    stores: list[Path],
    tz: str | None = None,
    locations: dict[str, dict] | None = None,
    records: dict[str, dict] | None = None,
) -> dict[str, str]:
    """The evidence appendix as `text`, `markdown` and `html`. Deterministic for a given
    `now`, zone and store contents. `locations`, `records`: as `appendix_rows`."""
    cols = config()["appendix_columns"]
    rows = appendix_rows(hashes, now, stores, tz, locations, records)
    # a used row's first cell is indented two spaces per level
    widths = [
        max([len(c)] + [len(cells[i]) + 2 * depth * (i == 0) for depth, cells in rows])
        for i, c in enumerate(cols)
    ]
    lines = ["  ".join(c.ljust(w) for c, w in zip(cols, widths)).rstrip()]
    lines.append("  ".join("-" * w for w in widths))
    for depth, cells in rows:
        first = ("  " * depth) + cells[0]
        lines.append(
            "  ".join(c.ljust(w) for c, w in zip([first] + cells[1:], widths)).rstrip()
        )
    md = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for depth, cells in rows:
        first = ("↳ " if depth else "") + cells[0]
        md.append("| " + " | ".join(_md_cell(c) for c in [first] + cells[1:]) + " |")
    head = "".join(f"<th>{html.escape(c)}</th>" for c in cols)
    body = []
    for depth, cells in rows:
        cls = ' class="used"' if depth else ""
        tds = "".join(f"<td>{html.escape(c)}</td>" for c in cells)
        body.append(f"<tr{cls}>{tds}</tr>")
    table = (
        f'<table class="evidence-appendix"><thead><tr>{head}</tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table>"
    )
    return {
        "text": "\n".join(lines) + "\n",
        "markdown": "\n".join(md) + "\n",
        "html": table,
    }


def _md_cell(text: str) -> str:
    return text.replace("|", "\\|")


# ── the ICS 201 with its labels beside it (D7: the tool response is unchanged)
# ─────────


def _tools_cited(block: Any) -> list[str]:
    out: list[str] = []
    if isinstance(block, dict):
        if block.get("kind") == "tool" and block.get("tool"):
            out.append(block["tool"])
        for v in block.values():
            out += _tools_cited(v)
    elif isinstance(block, list):
        for v in block:
            out += _tools_cited(v)
    return list(dict.fromkeys(out))


def as_of_phrase(source: dict, tz: str) -> str:
    """How a label source's as-of reads: "as of <when>", or, for a date the service
    stated in a description read once (`service_read_on`; HB-94, review L5-3), "<when>
    as the service stated it when last read on <read date>", so a typed-in date is
    never printed as a bare as-of."""
    w = when(source["as_of"], tz, source["as_of_precision"])
    read_on = source.get("service_read_on")
    if read_on:
        r = when(f"{read_on}T00:00:00Z", tz, "day")
        return f"{w} as the service stated it when last read on {r}"
    return f"as of {w}"


def span_words(seconds: float) -> str:
    """A length of time in the unit a reader counts it in: minutes under two hours,
    hours under two days, else days (HB-158 item 5)."""
    s = max(0.0, float(seconds))
    if s < 7200:
        n, unit = round(s / 60), "minute"
    elif s < 172800:
        n, unit = round(s / 3600), "hour"
    else:
        n, unit = round(s / 86400), "day"
    return f"{n} {unit}{'' if n == 1 else 's'}"


def old_phrase(source: dict) -> str:
    """What DN-010 D4's "stale" says, as the fact (HB-158 item 5; the operator's
    review of 2026-11-10, G9): the source's age at the reading and the limit it is
    past, "96 days old, past its 90-day limit". A source with no age (a label built
    before HB-158 kept it) says only that it is past its limit."""
    h = source.get("horizon_s")
    limit = span_words(h).replace(" ", "-").rstrip("s") if h is not None else None
    lim = f"past its {limit} limit" if limit else "past its limit"
    if source.get("age_s") is None:
        return lim
    return f"{span_words(source['age_s'])} old, {lim}"


def source_phrase(source: dict, tz: str, esc=str, stale: str = "{}") -> str:
    """What follows a source's name in a label line: "as of <when>, current", or, past
    its horizon, "as of <when>, <age> old, past its <limit> limit" (`old_phrase`; HB-158
    item 5 replaced the word "stale" with the fact). A pack checked against a later
    text (HB-108, `verified_against`) reads "current, checked against <text> as of
    <when> (<record>)", or, once that check is past the horizon, "checked against
    <text> as of <when> (<record>), <age> old, past its <limit> limit". `esc` escapes
    the text for the renderer; `stale` is a template the old phrase is put in (a
    renderer's markup, "{}" for plain text)."""
    old = stale.format(esc(old_phrase(source))) if source["stale"] else ""
    if source.get("verified_against"):
        checked = esc(
            f"checked against {source['verified_against']} as of "
            f"{when(source['as_of'], tz, source['as_of_precision'])} "
            f"({source['record']})"
        )
        return f"{checked}, {old}" if source["stale"] else f"current, {checked}"
    return f"{esc(as_of_phrase(source, tz))}, {old if source['stale'] else 'current'}"


def state_cell(label: dict) -> str:
    """The appendix's "Current or old" cell: the label's state, and, when the source
    that heads it is a pack checked against a later text (HB-108), what it was checked
    against and the record that says so. Past its horizon it reads the first such
    source's `old_phrase`, "96 days old, past its 91-day limit" (HB-158 item 5: the
    fact, not the word "stale")."""
    if label["stale"]:
        first = next((s for s in label["sources"] if s.get("stale")), None)
        return old_phrase(first) if first else "past its limit"
    head = next(
        (
            s
            for s in label["sources"]
            if s["name"] == label["source"] and s.get("verified_against")
        ),
        None,
    )
    if head is None:
        return "current"
    return f"current, checked against {head['verified_against']} ({head['record']})"


def label_line(tool: str, record: dict, label: dict, tz: str) -> str:
    n = config()["hash_prefix_chars"]
    parts = [
        f"{s['parameter']} as given by the requester"
        if s["provenance_class"] == "caller_supplied"
        else f"{s['name']}, {source_phrase(s, tz)}"
        for s in label["sources"]
    ]
    return (
        f"- {tool.replace('_', ' ')}: {'; '.join(parts)}. Record {label['hash'][:n]}."
    )


def render_ics201(
    payload: dict,
    records: list[dict],
    now: datetime,
    *,
    stores: list[Path],
    tz: str | None = None,
    unavailable: dict[str, str] | None = None,
) -> str:
    """The ICS 201 Markdown as `build_ics_201` laid it out (HB-11b), with each block's
    labels under it and the evidence appendix after the form. `records` are the records
    of the calls that built it, one per tool, `build_ics_201`'s among them.
    `unavailable` maps a tool the client could not reach to its degraded label (DN-011
    D2), which the block prints in that tool's place. Any other block that cites a tool
    with no record stops the render: a value without a record carries no label (D5)."""
    unavailable = unavailable or {}
    tz = tz or config()["default_time_zone"]
    by_tool = {r["activity"]["name"]: r for r in records}
    if "build_ics_201" not in by_tool:
        raise ValueError("render_ics201 needs the build_ics_201 record")
    cited = {b["number"]: _tools_cited(b) for b in payload["blocks"]}
    lines = payload["markdown"].rstrip("\n").split("\n")
    out, block = [], None

    def close(number):
        tools = cited.get(number) or []
        if not tools:
            return
        internal = config()["ics201_internal_outputs"]
        missing = [
            t
            for t in tools
            if t not in by_tool and t not in internal and t not in unavailable
        ]
        if missing:
            raise ValueError(f"block {number} cites {missing}, which have no record")
        out.append("")
        out.append(f"Sources for block {number}:")
        out.append("")
        for t in tools:
            if t not in by_tool and t in unavailable:
                out.append(f"- {t.replace('_', ' ')}: {unavailable[t]}.")
                continue
            rec = by_tool.get(t) or by_tool["build_ics_201"]
            _, body = latest(stores, rec["entity"]["sha256"])
            lab = label_for(
                rec, now, body, only=internal.get(t) if t not in by_tool else None
            )
            out.append(label_line(t, rec, lab, tz))

    for ln in lines:
        m = re.match(r"^## (\d+)\. ", ln)
        if m or ln.startswith("## Annex"):
            if block is not None:
                close(block)
                out.append("")
            block = int(m.group(1)) if m else None
        out.append(ln)
    if block is not None:
        close(block)
    out += ["", "## Evidence appendix", ""]
    cited = {r["entity"]["sha256"]: r for r in records}
    out.append(appendix(list(cited), now, stores, tz, records=cited)["markdown"])
    return "\n".join(out).rstrip("\n") + "\n"


def source_suffix(path: str, stores: list[Path]) -> str:
    """For the deck's sources line (HB-40 step 5): a cited path that is an entity or
    record file in one of `stores` gets ", as of <as_of>, record <hash prefix>"; any
    other path gets nothing. No `stale`: the deck is built deterministically, and
    staleness is a reading at a given now."""
    p = (REPO_ROOT / path).resolve()
    for store in stores:
        try:
            rel = p.relative_to(store.resolve())
        except ValueError:
            continue
        sha = rel.name.split(".", 1)[0]
        if re.fullmatch(r"[0-9a-f]{64}", sha):
            rec, _ = latest([store], sha)
            n = config()["hash_prefix_chars"]
            return f", as of {rec['as_of']}, record {sha[:n]}"
    return ""
