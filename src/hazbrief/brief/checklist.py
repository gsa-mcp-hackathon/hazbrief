"""The operator checklist, the replay banner's dates, the ICS 201's "Operator checks"
annex and the guide panels of the live page (DN-019 ADDENDUM-02 sections 1 and 3;
HB-141; register records HBD-217, HBD-218, HBD-219 and HBD-224).

The checklist takes the alerts panel's place (HB-131R item 1) and its events. Its items
are the stream's own: each `alert` (a cue line, a flag, a degraded label, or one of the
standing integrity items the orchestrator sends after `run_started`) and one Sources
line per channel (the first `channel_started` of each tool), keyed by its stream id,
the SSE `id:` it was sent with. They are grouped by `orchestrator.yaml`
`checklist.groups`, in that order, and within a group by kind in the group's order, then
in arrival order. A
withdrawn item stays, struck through, with the record that withdrew it; a tick on it
stays visible.

A tick is an event too: the live page's server appends `check` or `uncheck` (the item's
id and the server's time, `orchestrator.Check`) to the brief's stream, and the page
draws each box from the stream alone. `ChecksLog` writes each such event, at its place
in the stream, to a JSONL file before it is sent, so `--checks FILE` replays them at the
same places. Nothing gates on a check.

`items` here is the model the tests hold `static/live.js` to; the page builds the same
groups from the same events as they arrive.

This module reads no orchestrator state at import (the orchestrator imports the
renderer, which imports this), only event dictionaries (`BriefEvent.to_json` with the
stream id added) and the configuration.
"""

from __future__ import annotations

import html
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hazbrief.evidence import labels as L

#: the event types that are operator actions on an item
ACTIONS = ("check", "uncheck")
#: HB-155: the operator's other recorded actions, written to the same checks file and
#: replayed at their places: a moved point (or a point put back on its suggestion) and
#: an Area radius step. They name no checklist item.
RECORDED = ("site_moved", "area_radius_set")


def _events(events: list) -> list[dict]:
    """The stream as dictionaries, each with its stream id: `BriefEvent`s (their
    place in the list) or dictionaries that already carry `id`."""
    out = []
    for i, ev in enumerate(events):
        d = ev.to_json() if hasattr(ev, "to_json") else dict(ev)
        d.setdefault("id", i)
        out.append(d)
    return out


def items(events: list, cfg: dict) -> list[dict]:
    """The checklist as the page draws it: one dictionary per group in
    `checklist.groups` order (`id`, `title`, `items`), each item with its stream `id`,
    `kind`, `text`, `receipt`, `section`, `withdrawn` (the withdrawing receipt, or
    None), `checked` (the last action's) and `actions` (every check and uncheck on it,
    in order, with their times)."""
    spec = cfg["checklist"]
    by_id: dict[int, dict] = {}
    order: list[int] = []
    tools: dict[str, int] = {}
    for d in _events(events):
        t = d["type"]
        if t == "alert":
            by_id[d["id"]] = {
                "id": d["id"],
                "kind": d["kind"],
                "text": d["text"],
                "receipt": d["receipt"],
                "section": d["section"],
                "withdrawn": None,
                "checked": False,
                "actions": [],
            }
            order.append(d["id"])
        elif t == "alert_withdrawn" and d["alert"] in by_id:
            by_id[d["alert"]]["withdrawn"] = d["receipt"]
        elif t == "channel_started" and d["tool"] not in tools:
            tools[d["tool"]] = d["id"]
            by_id[d["id"]] = {
                "id": d["id"],
                "kind": "source",
                "tool": d["tool"],
                "state": None,
                "text": spec["source_line"].format(
                    tool=d["tool"].replace("_", " "), state=spec["source_pending"]
                ),
                "receipt": spec["source_receipt"],
                "section": None,
                "withdrawn": None,
                "checked": False,
                "actions": [],
            }
            order.append(d["id"])
        elif t == "channel_settled" and d["tool"] in tools:
            it = by_id[tools[d["tool"]]]
            if it["state"] is None:
                it["state"] = d["state"]
                it["text"] = spec["source_line"].format(
                    tool=d["tool"].replace("_", " "), state=d["state"]
                )
        elif t in ACTIONS:
            it = by_id.get(d["item"])
            if it is None:
                raise ValueError(
                    f"stream id {d['id']}: a {t} names item {d['item']}, which is no "
                    "checklist item sent before it"
                )
            it["checked"] = t == "check"
            it["actions"].append({"action": t, "time": d["time"], "id": d["id"]})
    groups = []
    for g in spec["groups"]:
        rank = {k: i for i, k in enumerate(g["kinds"])}
        mine = [by_id[i] for i in order if by_id[i]["kind"] in rank]
        mine.sort(key=lambda it: (rank[it["kind"]], it["id"]))
        groups.append({"id": g["id"], "title": g["title"], "items": mine})
    return groups


def item_ids(events: list) -> set[int]:
    """The stream ids a check may name: every alert and each tool's first
    `channel_started`."""
    out, seen = set(), set()
    for d in _events(events):
        if d["type"] == "alert":
            out.add(d["id"])
        elif d["type"] == "channel_started" and d["tool"] not in seen:
            seen.add(d["tool"])
            out.add(d["id"])
    return out


def unticked_verify(groups: list[dict]) -> tuple[int, int]:
    """(unticked, total) over the Verify group's standing items (not withdrawn): the
    report's first line (section 3 item 5)."""
    verify = next(g for g in groups if g["id"] == "verify")
    standing = [it for it in verify["items"] if it["withdrawn"] is None]
    return sum(1 for it in standing if not it["checked"]), len(standing)


def activity(groups: list[dict]) -> list[dict]:
    """Every check and uncheck, in stream order, with its item and group: the annex's
    rows (an ICS 214 activity log's entries)."""
    rows = []
    for g in groups:
        for it in g["items"]:
            for a in it["actions"]:
                rows.append({**a, "group": g["title"], "text": it["text"]})
    return sorted(rows, key=lambda r: r["id"])


def annex_html(cfg: dict, groups: list[dict] | None, tz: str) -> str:
    """The ICS 201's "Operator checks" annex (section 3 item 3; ADDENDUM-01 section
    2). `groups` None: the static page's (no check is recorded in a render); else the
    report's, each check and uncheck with its time in the incident's zone."""
    spec = cfg["checklist"]
    e = html.escape
    lines = [f"<p>{e(spec['annex_form'])}</p>"]
    if groups is None:
        lines.append(f"<p>{e(spec['annex_static'])}</p>")
    else:
        rows = activity(groups)
        if not rows:
            lines.append(f"<p>{e(spec['annex_none'])}</p>")
        else:
            lines.append(
                '<ol class="checks">'
                + "".join(
                    "<li>"
                    + e(
                        spec["annex_row"].format(
                            time=L.when(r["time"], tz),
                            action=spec["actions"][r["action"]],
                            group=r["group"],
                            text=r["text"],
                        )
                    )
                    + "</li>"
                    for r in rows
                )
                + "</ol>"
            )
    lines.append(f"<p>{e(spec['annex_questions'])}</p>")
    return (
        f'<div class="operator-checks"><h3>{e(spec["annex_title"])}</h3>'
        f"{''.join(lines)}</div>"
    )


def recorded_dates(brief, cfg: dict) -> str | None:
    """The date the replayed brief's records were made (each record's
    `activity.endedAtTime`, in the incident's zone), or the first and last, for the
    replay banner (F4; HBD-219). None when the brief holds no record."""
    days = sorted(
        {
            L.when(r["activity"]["endedAtTime"], brief.time_zone)[:10]
            for r in brief.records()
        },
        key=lambda d: (d[6:10], d[0:2], d[3:5]),
    )
    if not days:
        return None
    if len(days) == 1:
        return days[0]
    return cfg["web"]["replay_recorded_range"].format(first=days[0], last=days[-1])


# ── the guide panels (item 6; HBD-224) ────────────────────────────────────────────────

_H4 = re.compile(r"<h4>([^<]*)</h4>")
_STRONG = re.compile(r"<p><strong>([^<]*)</strong></p>")


def _marks(body: str) -> list[tuple[int, int, str]]:
    """(offset, rank, text) of each heading in a section's body: an <h4> is rank 1, a
    <p><strong> line rank 2, in offset order."""
    out = [(m.start(), 1, html.unescape(m.group(1))) for m in _H4.finditer(body)]
    out += [(m.start(), 2, html.unescape(m.group(1))) for m in _STRONG.finditer(body)]
    return sorted(out)


def panel_html(fragment: str, spec: dict) -> str | None:
    """The slice of a section's fragment a panel shows, byte for byte, or None when the
    section does not hold the panel's heading (or is not rendered). The body is what
    follows the section's `</summary>` up to its `</details>`."""
    head = fragment.find("</summary>")
    tail = fragment.rfind("</details>")
    if head < 0 or tail < 0 or 'class="rendered"' not in fragment[:80]:
        return None
    start0 = head + len("</summary>")
    body = fragment[start0:tail]
    if spec.get("whole"):
        return body
    marks = _marks(body)
    hit = [(o, r) for o, r, t in marks if r == spec["rank"] and t == spec["start"]]
    if not hit:
        return None
    at, rank = hit[0]
    after = [o for o, r, _ in marks if o > at and r <= rank]
    end = after[0] if after else len(body)
    return body[at:end]


def panels(parts: dict[str, str], cfg: dict) -> dict[str, dict]:
    """Every configured panel the brief holds: id -> {title, section, html}, from the
    sections' fragments as the static page prints them (`render.page_parts`, after the
    load read; HB-141 ADDENDUM-02 section 2)."""
    out = {}
    for p in cfg["web"]["panels"]:
        got = panel_html(parts.get(p["section"], ""), p)
        if got is not None:
            out[p["id"]] = {"title": p["title"], "section": p["section"], "html": got}
    return out


# ── the checks a served page records (item 2) ─────────────────────────────────────────


@dataclass
class ChecksLog:
    """One served brief's operator checks, one JSON line each (`brief_id`, `at`, the
    event's place in the stream, `type`, `item`, `time`), written and fsynced before
    the event is sent (engineering standards section 15 rule 1). `recorded` is what the
    file held when it was opened: a replay inserts each at its `at` again."""

    path: Path
    brief_id: str
    recorded: list[dict] = field(default_factory=list)

    @classmethod
    def open(cls, path: Path, brief_id: str) -> "ChecksLog":
        rows = []
        if path.exists():
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get("brief_id") != brief_id:
                    raise ValueError(
                        f"{path} line {n} records brief {row.get('brief_id')!r}, "
                        f"not {brief_id!r}: give this brief's checks file"
                    )
                if row.get("type") not in ACTIONS + RECORDED or not isinstance(
                    row.get("at"), int
                ):
                    raise ValueError(
                        f"{path} line {n} is not a check, an uncheck, a moved point "
                        "or an area radius step"
                    )
                rows.append(row)
        rows.sort(key=lambda r: r["at"])
        return cls(path=path, brief_id=brief_id, recorded=rows)

    def append(self, at: int, ev: Any) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row = {"brief_id": self.brief_id, "at": at, **ev.to_json()}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
