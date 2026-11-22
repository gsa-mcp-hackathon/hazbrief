#!/usr/bin/env python3
"""Render the operator's acquisition queue: every corpus/sources.yaml row awaiting
a hand fetch, as one self-contained HTML page (HB-147).

**No network, no model.**

DN-002 ADDENDUM-00 sets the acquisition ladder: the allowlisted fetcher (rung 1), the
operator's browser (rung 2), the operator (rung 3). Until HB-147 the rung-2 list lived
in Markdown (corpus/OPERATOR_DOWNLOADS.md, and each task's
`the evidence`). The operator ruled on 2026-11-09 that it must be
a page he opens in a browser and clicks through. This script writes that page from the
manifest alone:

* **The queue is the manifest.** A row is on the page because its `status` is
  `awaiting_operator`, with `refused_by` (why rung 1 did not take it) and
  `requested_by` (the task that asked for it). Nothing else puts a row there.
* **Awaiting** rows render with the link (a new tab), a web and a Scholar search built
  from the title, the refusal, the requesting task, the path to drop the file under
  `corpus/inbox/` with a copy button, and the registrar command.
* **Received** rows are queued rows the operator has fetched: a file in the inbox that
  `scripts/register_inbox.py` identifies by content as the row, a file at the row's
  drop path that it does not identify (with the reason), or a row the registrar marked
  `held` that the corpus graph's intake does not yet name (the next ingest admits it).
* A queued row the logs already hold (fetched at rung 1, or registered) contradicts
  the manifest; the page lists it under "Needs attention" and
  test_acquisition_queue.py fails on it, so nothing held is asked for again.

The page is byte-identical for identical inputs (no clock, no host path), so the gate
can regenerate it (tests/conftest.py) without moving a tracked file nothing changed.
The page's own script computes the inbox's absolute path from its file:// location.

    uv run python scripts/acquisition_queue.py   # exit 1 if a row needs attention
"""

from __future__ import annotations

import argparse
import html
import importlib.util
import json
import os
import re
import sys
import tempfile
import urllib.parse
from pathlib import Path
from typing import NamedTuple

import yaml

REPO = Path(__file__).resolve().parents[1]
CONFIG = Path(__file__).with_suffix(".yaml")


def _module(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


#: The registrar: its format table and its content identification are the page's, so the
#: page never says a file is identified when the registrar would not take it.
R = _module("register_inbox")
F = R.F

#: Keys the configuration must carry (engineering standards section 4: fail at load, by
#: name).
CONFIG_KEYS = (
    "sources",
    "fetch_log",
    "operator_downloads",
    "intake_candidates",
    "inbox",
    "tasks_dir",
    "output",
    "title",
    "status",
    "commands",
    "search",
    "save_as",
)
#: A task id as the project numbers them (HB-147, HB-142R, HB-01b).
TASK_ID = re.compile(r"^HB-[0-9]+[A-Za-z]?$")
#: The `url` an operator download states when its file URL is not known (HB-01b
#: ADDENDUM-01; test_corpus_intake.py), always with a `source_page`.
UNRESOLVED = "unresolved"
#: Errors a single inbox file can raise while it is read for identification; each is
#: shown on the page against that file, never swallowed.
FILE_ERRORS = (OSError, ValueError, RuntimeError, R.RegistrationError)


class QueueError(RuntimeError):
    """The manifest or the configuration cannot be rendered; the message says which row
    or key."""


class Item(NamedTuple):
    """One queued row as the page shows it."""

    doc_id: str
    title: str
    publisher: str
    edition: str
    url: str | None
    source_page: str | None
    fmt: str
    refused_by: str
    requested_by: str
    task_date: str
    task_file: str
    drop: str
    state: str
    detail: str


def load_config(path: Path = CONFIG) -> dict:
    try:
        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise QueueError(f"cannot read {path}: {exc}") from None
    missing = [k for k in CONFIG_KEYS if k not in cfg]
    if missing:
        raise QueueError(f"{path}: missing keys {missing}")
    for k in ("awaiting", "held", "closed"):
        if not cfg["status"].get(k):
            raise QueueError(f"{path}: status.{k} is not set")
    if not cfg.get("closed_under") or not all(
        isinstance(v, str) and v.strip() for v in cfg["closed_under"].values()
    ):
        raise QueueError(f"{path}: closed_under must name each decision with its text")
    for k in ("register", "render", "commit"):
        if not cfg["commands"].get(k):
            raise QueueError(f"{path}: commands.{k} is not set")
    for s in cfg["search"]:
        if "{query}" not in s.get("url", "") or not s.get("label"):
            raise QueueError(f"{path}: search entry {s!r} needs a label and {{query}}")
    unknown = set(cfg["save_as"]) - set(R.EXTENSIONS)
    if unknown:
        raise QueueError(
            f"{path}: save_as names formats the registrar lacks: {unknown}"
        )
    return cfg


def is_url(value) -> bool:
    """An absolute http(s) URL with a host (RFC 3986 scheme and authority)."""
    if not isinstance(value, str) or any(c.isspace() for c in value):
        return False
    parts = urllib.parse.urlsplit(value)
    return parts.scheme in ("http", "https") and bool(parts.hostname)


def queued(sources: list, cfg: dict) -> list:
    """Every row carrying a `status` the page shows, validated. A row with a status the
    configuration does not name, or an awaiting row missing what the page prints, is
    refused. A `closed` row (HB-150) must name the decision it is closed under and why,
    and is then left off the page."""
    closed = cfg["status"]["closed"]
    allowed = (cfg["status"]["awaiting"], cfg["status"]["held"], closed)
    out = []
    for s in sources:
        if "status" not in s:
            continue
        doc_id = s["doc_id"]
        if s["status"] not in allowed:
            raise QueueError(
                f"{doc_id}: status {s['status']!r} is not one of {allowed}"
            )
        if s["status"] == closed:
            if not s.get("closed_under"):
                raise QueueError(f"{doc_id}: a closed row needs `closed_under`")
            if s["closed_under"] not in cfg["closed_under"]:
                raise QueueError(
                    f"{doc_id}: closed_under {s['closed_under']!r} is not one of "
                    f"{sorted(cfg['closed_under'])}"
                )
            if not str(s.get("closed_note") or "").strip():
                raise QueueError(f"{doc_id}: a closed row needs `closed_note`")
            continue
        for k in ("title", "refused_by", "requested_by"):
            if not s.get(k):
                raise QueueError(f"{doc_id}: a queued row needs `{k}`")
        fmt = R.held_format(s)
        if not TASK_ID.match(str(s["requested_by"])):
            raise QueueError(
                f"{doc_id}: requested_by {s['requested_by']!r} is not a task id "
                "(HB-NNN)"
            )
        if fmt not in R.EXTENSIONS:
            raise QueueError(
                f"{doc_id}: held format {fmt!r} (save_format, else format) cannot be "
                f"registered (register_inbox.EXTENSIONS: {sorted(R.EXTENSIONS)})"
            )
        if fmt not in cfg["save_as"]:
            raise QueueError(f"{doc_id}: save_as has no line for {fmt!r}")
        for k in ("url", "source_page"):
            # HB-150: `url: unresolved` with a source page is the manifest's convention
            # for an operator download whose file URL nobody recorded (HB-01b
            # ADDENDUM-01); the page then links the source page.
            if k == "url" and s.get(k) == UNRESOLVED and is_url(s.get("source_page")):
                continue
            if s.get(k) is not None and not is_url(s[k]):
                raise QueueError(f"{doc_id}: {k} {s[k]!r} is not an http(s) URL")
        out.append(s)
    return out


def task_of(task_id: str, tasks_dir: Path) -> tuple:
    """`(date, file name)` of the task file a task id names: the earliest file
    `YYYY-MM-DD_<id>_*.md` (the task, before its RESULT and addenda)."""
    rx = re.compile(rf"^(\d{{4}}-\d{{2}}-\d{{2}})_{re.escape(task_id)}_.*\.md$")
    hits = sorted(p.name for p in tasks_dir.glob("*.md") if rx.match(p.name))
    if not hits:
        raise QueueError(f"requested_by {task_id}: no task file in {tasks_dir}")
    plain = [h for h in hits if "_RESULT" not in h and "ADDENDUM" not in h]
    name = (plain or hits)[0]
    return rx.match(name).group(1), name


def held_by_logs(row: dict, units: dict, downloads: dict) -> str | None:
    """How the logs hold a row's bytes, or None: a registration in
    corpus/operator_downloads.jsonl, or a `fetched` unit for the row's URL in
    corpus/fetch_log.jsonl (squiddy_intake.py's join, without re-hashing)."""
    dl = downloads.get(row["doc_id"])
    if dl:
        return f"registered {dl['registered_at'][:10]} (sha256 {dl['sha256'][:12]})"
    if row.get("url"):
        unit = units.get(F.unit_key(row["doc_id"], row["url"]))
        if unit and unit.get("outcome") == "fetched":
            return f"fetched at rung 1 {str(unit.get('ts', ''))[:10]}".strip()
    return None


def intake_ids(path: Path) -> set:
    if not path.exists():
        raise QueueError(f"the corpus intake {path} is missing")
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {c["id"] for c in doc.get("candidates") or []}


def inbox_files(inbox: Path, sources: list) -> dict:
    """file name -> `(doc_id or None, detail)`: each inbox file identified by content,
    as `register_inbox.py --dry-run` would. A file that cannot be read says why."""
    if not inbox.is_dir():
        return {}
    table = R.rules(sources)
    out = {}
    for p in sorted(inbox.iterdir()):
        if not p.is_file() or p.name.startswith("."):
            continue
        try:
            out[p.name] = R.identify(p, table)
        except FILE_ERRORS as exc:
            out[p.name] = (None, f"could not be read: {type(exc).__name__}: {exc}")
    return out


def build(repo: Path, cfg: dict) -> tuple:
    """`(awaiting, received, problems)`: the page's model, from the files alone."""
    sources = F.load_sources(repo / cfg["sources"])
    rows = queued(sources, cfg)
    units = F.FetchLog(repo / cfg["fetch_log"]).latest_units()
    downloads = R.registered(repo / cfg["operator_downloads"])
    ingested = intake_ids(repo / cfg["intake_candidates"])
    inbox = inbox_files(repo / cfg["inbox"], sources)
    by_doc: dict = {}
    for name, (doc_id, detail) in inbox.items():
        if doc_id:
            by_doc.setdefault(doc_id, []).append((name, True, detail))
    awaiting_status, held_status = cfg["status"]["awaiting"], cfg["status"]["held"]
    awaiting, received, problems = [], [], []
    for s in rows:
        doc_id = s["doc_id"]
        date, task_file = task_of(str(s["requested_by"]), repo / cfg["tasks_dir"])
        fmt = R.held_format(s)
        drop = f"{cfg['inbox']}/{doc_id}{R.EXTENSIONS[fmt]}"
        held = held_by_logs(s, units, downloads)
        base = dict(
            doc_id=doc_id,
            title=" ".join(str(s["title"]).split()),
            publisher=" ".join(str(s.get("publisher") or "").split()),
            edition=str(s.get("edition") or ""),
            url=None if s.get("url") == UNRESOLVED else s.get("url"),
            source_page=s.get("source_page"),
            fmt=fmt,
            refused_by=" ".join(str(s["refused_by"]).split()),
            requested_by=str(s["requested_by"]),
            task_date=date,
            task_file=task_file,
            drop=drop,
        )
        if s["status"] == held_status:
            if not held:
                problems.append(
                    Item(
                        **base,
                        state="held_without_record",
                        detail="status: held, but corpus/operator_downloads.jsonl "
                        "has no registration and corpus/fetch_log.jsonl no fetched "
                        "unit",
                    )
                )
            elif doc_id not in ingested:
                received.append(
                    Item(
                        **base,
                        state="registered",
                        detail=f"{held}; the next corpus ingest "
                        "(scripts/ingest_corpus.py) admits it",
                    )
                )
            continue
        # `queued` admitted only the two configured values, so this row is awaiting.
        if held:
            problems.append(
                Item(
                    **base,
                    state="held_but_awaiting",
                    detail=f"{held}, but the row still says {awaiting_status}; "
                    f"set its status to {held_status}",
                )
            )
            continue
        hits = list(by_doc.get(doc_id, []))
        drop_name = Path(drop).name
        if drop_name in inbox and inbox[drop_name][0] != doc_id:
            hits.append((drop_name, False, inbox[drop_name][1]))
        if hits:
            states = []
            for name, ok, detail in hits:
                states.append(
                    f"{name}: identified by content ({detail}); run the registrar"
                    if ok
                    else f"{name}: at the drop path, not identified ({detail})"
                )
            received.append(
                Item(
                    **base,
                    state="in_inbox" if all(h[1] for h in hits) else "unidentified",
                    detail="; ".join(states),
                )
            )
            continue
        awaiting.append(Item(**base, state="awaiting", detail=""))

    def order(i):
        return (-int(i.task_date.replace("-", "")), i.requested_by, i.doc_id)

    return sorted(awaiting, key=order), sorted(received, key=order), problems


# ── the page ──────────────────────────────────────────────────────────────────────────


#: A link that opens in a new tab without handing the opened page this one.
NEW_TAB = 'target="_blank" rel="noopener noreferrer"'


def _e(text) -> str:
    return html.escape(str(text), quote=True)


def search_links(item: Item, cfg: dict) -> list:
    out = []
    for s in cfg["search"]:
        q = f'"{item.title}"'
        if s.get("with_publisher") and item.publisher:
            q += f" {item.publisher}"
        out.append(
            (s["label"], s["url"].replace("{query}", urllib.parse.quote_plus(q)))
        )
    return out


def _copy(value: str, label: str = "Copy", rel: bool = False) -> str:
    attr = "data-rel" if rel else "data-copy"
    return (
        f'<button type="button" class="copy" {attr}="{_e(value)}">{_e(label)}</button>'
    )


def _task_cell(item: Item, cfg: dict) -> str:
    href = os.path.relpath(
        Path(cfg["tasks_dir"]) / item.task_file, Path(cfg["output"]).parent
    )
    return (
        f'<a href="{_e(href)}">{_e(item.requested_by)}</a>'
        f'<div class="muted">{_e(item.task_date)}</div>'
    )


def _title_cell(item: Item) -> str:
    sub = ", ".join(x for x in (item.publisher, item.edition) if x)
    return (
        f'<div class="title">{_e(item.title)}</div>'
        + (f'<div class="muted">{_e(sub)}</div>' if sub else "")
        + f'<code class="id">{_e(item.doc_id)}</code>'
    )


def _link_cell(item: Item, cfg: dict) -> str:
    """The row's URL; where it has none, the page it lives on (`source_page`, such as a
    DOI), said so; where it has neither, the search links alone."""
    if item.url:
        link = (
            f'<a class="open" href="{_e(item.url)}" {NEW_TAB}>'
            f"{_e(urllib.parse.urlsplit(item.url).hostname)}</a>"
        )
    elif item.source_page:
        link = (
            f'<a class="open" href="{_e(item.source_page)}" {NEW_TAB}>'
            f"{_e(urllib.parse.urlsplit(item.source_page).hostname)}</a>"
            '<div class="muted">its page (no document URL)</div>'
        )
    else:
        link = '<span class="warn">no URL found: search</span>'

    searches = " ".join(
        f'<a class="search" href="{_e(u)}" {NEW_TAB}>{_e(label)}</a>'
        for label, u in search_links(item, cfg)
    )
    return f'{link}<div class="searches">{searches}</div>'


def _drop_cell(item: Item, cfg: dict) -> str:
    return (
        f'<code class="path" data-path="{_e(item.drop)}">{_e(item.drop)}</code> '
        + _copy(item.drop, rel=True)
        + f'<div class="muted">Save {_e(cfg["save_as"][item.fmt])}.</div>'
    )


#: The page's style and script, inlined so the page is one self-contained file.
STYLE = Path(__file__).with_suffix(".css")
SCRIPT = Path(__file__).with_suffix(".js")


def render(awaiting: list, received: list, problems: list, cfg: dict) -> str:
    out_rel = "/" + cfg["output"]
    inbox_dir = cfg["inbox"] + "/"
    cmds = cfg["commands"]
    awaiting_status, held_status = cfg["status"]["awaiting"], cfg["status"]["held"]
    parts = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        f"<title>{_e(cfg['title'])}</title>",
        f"<style>{STYLE.read_text(encoding='utf-8')}</style>",
        "</head><body><main>",
        f"<h1>{_e(cfg['title'])}: {len(awaiting)} awaiting a hand fetch</h1>",
        '<p class="muted">Every <code>corpus/sources.yaml</code> row with '
        f"<code>status: {_e(awaiting_status)}</code> (DN-002 ADDENDUM-00, rung 2), "
        "newest requesting task first. <code>scripts/acquisition_queue.py</code> "
        "writes this page on every gate and after every registration; edit the "
        "manifest, never this page.</p>",
        '<ol class="recipe">',
        "<li>Open the link (a new tab), or search for the title where no link "
        "works. Save the file into the inbox: "
        f'<code class="path" data-path="{_e(inbox_dir)}">{_e(inbox_dir)}</code> '
        + _copy(inbox_dir, "Copy folder", rel=True)
        + ". The drop path is a suggested name; the registrar identifies a file by "
        "its content, so the site's own name works too (DN-002 section 3).</li>",
        "<li>In a shell at the repository root (or Claude Code with the "
        f'<code>!</code> prefix): <code class="cmd">{_e(cmds["register"])}</code> '
        + _copy(cmds["register"])
        + " It registers only the queued files it identifies, marks their rows "
        f"<code>{_e(held_status)}</code> and re-renders this page; every other "
        "inbox file stays where it is.</li>",
        "<li>Commit, or leave it for the next session: "
        f'<code class="cmd">{_e(cmds["commit"])}</code> '
        + _copy(cmds["commit"])
        + "</li>",
        "</ol>",
    ]
    if problems:
        parts += [
            f'<h2 class="warn">Needs attention: {len(problems)}</h2>',
            '<p class="muted">The manifest contradicts the logs for these rows; '
            "do not fetch them.</p>",
            '<div class="wrap"><table id="problems"><thead><tr><th>Row</th>'
            "<th>Problem</th></tr></thead><tbody>",
        ]
        for i in problems:
            parts.append(
                f'<tr data-doc-id="{_e(i.doc_id)}"><td>{_title_cell(i)}</td>'
                f'<td class="why">{_e(i.detail)}</td></tr>'
            )
        parts.append("</tbody></table></div>")
    parts += [
        f"<h2>Awaiting: {len(awaiting)}</h2>",
        '<div class="wrap"><table id="awaiting"><thead><tr><th>Requested by</th>'
        "<th>Document</th><th>Link</th><th>Why rung 1 did not take it</th>"
        "<th>Drop the file at</th></tr></thead><tbody>",
    ]
    for i in awaiting:
        parts.append(
            f'<tr data-doc-id="{_e(i.doc_id)}"><td>{_task_cell(i, cfg)}</td>'
            f"<td>{_title_cell(i)}</td><td>{_link_cell(i, cfg)}</td>"
            f'<td class="why">{_e(i.refused_by)}</td><td>{_drop_cell(i, cfg)}</td></tr>'
        )
    if not awaiting:
        parts.append('<tr><td colspan="5" class="muted">Nothing is awaiting.</td></tr>')
    parts += [
        "</tbody></table></div>",
        f"<h2>Received: {len(received)}</h2>",
        '<p class="muted">Queued rows the operator has fetched: in the inbox and '
        "not yet registered, or registered and not yet in the corpus graph.</p>",
        '<div class="wrap"><table id="received"><thead><tr><th>Requested by</th>'
        "<th>Document</th><th>State</th></tr></thead><tbody>",
    ]
    for i in received:
        parts.append(
            f'<tr data-doc-id="{_e(i.doc_id)}" data-state="{_e(i.state)}">'
            f"<td>{_task_cell(i, cfg)}</td><td>{_title_cell(i)}</td>"
            f'<td class="why">{_e(i.detail)}</td></tr>'
        )
    if not received:
        parts.append('<tr><td colspan="3" class="muted">Nothing received.</td></tr>')
    parts += [
        "</tbody></table></div>",
        "<script>"
        + SCRIPT.read_text(encoding="utf-8").replace(
            "__PAGE_PATH__", json.dumps(out_rel)
        )
        + "</script>",
        "</main></body></html>",
        "",
    ]
    return "\n".join(parts)


def write_page(repo: Path = REPO, cfg: dict | None = None) -> dict:
    """Render the page from `repo`'s files and write it atomically when its bytes
    changed. Returns the counts and whether the file moved."""
    cfg = cfg or load_config()
    awaiting, received, problems = build(repo, cfg)
    page = render(awaiting, received, problems, cfg).encode("utf-8")
    out = repo / cfg["output"]
    changed = not out.exists() or out.read_bytes() != page
    if changed:
        out.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=out.parent, prefix=f".{out.name}.")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(page)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, out)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
    return {
        "page": str(out),
        "awaiting": len(awaiting),
        "received": len(received),
        "problems": [f"{i.doc_id}: {i.detail}" for i in problems],
        "changed": changed,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", type=Path, default=REPO)
    ap.add_argument("--config", type=Path, default=CONFIG)
    a = ap.parse_args(argv)
    try:
        out = write_page(a.repo, load_config(a.config))
    except (QueueError, F.ConfigError, R.RegistrationError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(out, indent=1))
    # A contradiction between the manifest and the logs is rendered on the page and
    # reported here; the exit says so.
    return 1 if out["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
