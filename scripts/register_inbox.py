#!/usr/bin/env python3
"""Register the operator's browser downloads: identify each `corpus/inbox/` file by its
content, record its provenance, and move it to `corpus/raw/<doc_id><ext>`.

**No network, no model.**

DN-002 section 3 (DN-002): a
person in a browser is not a crawler. The operator saves each file as the site names it,
unrenamed, into `corpus/inbox/` (gitignored). This script never trusts that name. A file
is matched to a `corpus/sources.yaml` entry by

* its **format signature** (the same leading bytes `fetch_allowlisted.py` checks, so a
  saved error page is not taken for the document), and
* its **title-page text**: the entry's `identify.text` regular expression, searched
  case-insensitively over the whitespace-normalized text of the first
  `IDENTIFY_PAGES` pages (PDF; an entry may name its own `identify.pages`), the shared
  strings of a workbook (xlsx), the cells of a BIFF8 workbook (xls), the whole of a
  Markdown clipping (md) or a CSV (csv), the document re-serialized (json), or the
  root element's name and attributes followed by its text (xml).

HB-01d added xls and md. PHMSA ships three ERG2020 tables only as `.xls`, and the
operator saved two PHMSA pages this client is refused as browser clippings: Markdown
whose front matter names the page's `source:` URL. Markdown has no format signature;
a file is taken for it only if it is UTF-8 and does not open as markup (`<`), so a
saved error page is not taken for the clipping, as for every other format.

HB-01e added json, xml and csv (an API's OpenAPI document and an eCFR section the
hosts' robots.txt disallows to this client, and Esri's ERG Materials table), and
`identify.pages` (Argonne's 2016 report has image-only cover pages). JSON counts only
if it parses; XML only if it is well formed, declares no entities (no entity
expansion of a saved file) and is not an HTML page. CSV, like Markdown, is UTF-8 text
with no signature: a text file is a candidate for an entry of either format, and the
entry's own rule decides.

HB-147 added txt (PHMSA's Incident Report Search exports to a tab-delimited text file)
and the acquisition queue. A row the operator is asked for carries `status:
awaiting_operator` in `corpus/sources.yaml`, and `docs/evidence/acquisition/queue.html`
lists it (`scripts/acquisition_queue.py`). `--queue` registers only the inbox files
identified as such rows and leaves every other file where it is (the inbox holds
leftovers: an old clipping there would supersede a held entry). On a successful
registration the row's status becomes `held`, the one value a script writes in the
manifest, by a one-line edit that keeps the file's comments; a run that died between the
registration row and that edit finishes it on the next run. The page is then rendered
again, so the row leaves the awaiting table.

Exactly one entry must match. No match, or more than one, leaves the file in the inbox
and is reported; the manifest is the source of truth and a filename is never a load
point (DN-002 section 3).

For a match, one row is appended to `corpus/operator_downloads.jsonl` (fsynced): doc_id,
`acquisition: operator_download`, `acquired_by: operator`, `original_filename`, sha256,
bytes, `source_url`, the retrieval date (the file's mtime, unless the operator states
one with `--retrieved DOC_ID=YYYY-MM-DD`) and the rule that identified it. The file is
copied to `corpus/raw/` via an fsynced temp file and an atomic rename BEFORE the row is
written, and removed from the inbox only after. A kill at any point leaves either the
inbox file or a held file with its row; re-running finishes the job (a held file whose
row exists and whose sha256 matches is skipped; a different sha256 for a registered
doc_id is a new edition and gets a new row, which supersedes the old one).

    uv run python scripts/register_inbox.py --dry-run     # identify, move nothing
    uv run python scripts/register_inbox.py --queue       # the queue's files only
    uv run python scripts/register_inbox.py
    uv run python scripts/register_inbox.py --url ar-25-50=https://... \
        --retrieved ar-25-50=2026-10-20
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from corpus_text import clipping_front_matter, pdf_pages, xls_blocks  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "fetch_allowlisted", REPO / "scripts" / "fetch_allowlisted.py"
)
F = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(F)

#: Pages of a PDF searched for the identifying text. A title page and its verso carry
#: the title, edition and issuing body in every document DN-002 section 3 names; three
#: pages tolerates a cover image page with no text layer.
IDENTIFY_PAGES = 3
#: Stored extension by declared format.
EXTENSIONS = {
    "pdf": ".pdf",
    "xlsx": ".xlsx",
    "xls": ".xls",
    "json": ".json",
    "xml": ".xml",
    "md": ".md",
    "csv": ".csv",
    "txt": ".txt",
}
#: Formats with a format signature (leading bytes), checked in this order: xlsx before
#: zip-like files, as `fetch_allowlisted.SIGNATURES` declares them.
BINARY_FORMATS = ("pdf", "xlsx", "xls")
#: Plain UTF-8 text with no signature (HB-01e): which one a file is, is decided by the
#: identify rule of an entry declaring the format. HB-147: `txt`, a portal's text
#: export.
PLAIN_TEXT_FORMATS = ("md", "csv", "txt")
ACQUISITION = "operator_download"
ACQUIRED_BY = "operator"
#: HB-147: the acquisition queue's configuration, which names the manifest's two queue
#: states (`status.awaiting`, `status.held`) and the page.
QUEUE_CONFIG = REPO / "scripts" / "acquisition_queue.yaml"


class RegistrationError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def held_format(entry: dict) -> str | None:
    """The format the held file takes: the entry's `save_format` where it states one
    (HB-147: a web page whose `format` is html is saved as a Markdown clipping, a book
    whose `format` is n/a as a PDF), else its `format`. `save_format` is a queue field,
    never carried onto the corpus graph's candidate, so stating it revises no work."""
    return entry.get("save_format") or entry.get("format")


#: HB-150: a full sha256, lower-case hex, as `identify.sha256` must state it.
SHA256 = re.compile(r"[0-9a-f]{64}")


def rules(sources: list) -> list:
    """`(doc_id, entry, matcher)` for each entry declaring `identify`: a compiled regex
    for `identify.text`, or the hex digest for `identify.sha256` (HB-150).

    A digest rule is for a scan whose text layer holds no title (Barnes 1964 as AMS
    serves it carries only the download watermark): a session reads the page image,
    states what it saw in `identify.seen`, and names the sha256 of those bytes. It
    matches only those exact bytes, so it is narrower than any text rule; the format
    signature is still checked first."""
    out = []
    for e in sources:
        ident = e.get("identify")
        if not ident:
            continue
        if not isinstance(ident, dict) or (
            bool(ident.get("text")) == bool(ident.get("sha256"))
        ):
            raise RegistrationError(
                f"{e['doc_id']}: `identify` needs one of a `text` pattern or a "
                "`sha256` digest"
            )
        fmt = held_format(e)
        if ident.get("sha256"):
            if not SHA256.fullmatch(str(ident["sha256"])):
                raise RegistrationError(
                    f"{e['doc_id']}: identify.sha256 must be 64 lower-case hex digits"
                )
            if not str(ident.get("seen") or "").strip():
                raise RegistrationError(
                    f"{e['doc_id']}: identify.sha256 needs `seen`, what the page "
                    "image shows"
                )
            if fmt not in EXTENSIONS:
                raise RegistrationError(
                    f"{e['doc_id']}: identify supports formats {sorted(EXTENSIONS)}, "
                    f"not {fmt!r}"
                )
            out.append((e["doc_id"], e, ident["sha256"]))
            continue
        if fmt not in EXTENSIONS:
            raise RegistrationError(
                f"{e['doc_id']}: identify supports formats {sorted(EXTENSIONS)}, "
                f"not {fmt!r}"
            )
        pages = ident.get("pages", IDENTIFY_PAGES)
        if not isinstance(pages, int) or isinstance(pages, bool) or pages < 1:
            raise RegistrationError(
                f"{e['doc_id']}: identify.pages must be a positive integer, "
                f"not {pages!r}"
            )
        out.append((e["doc_id"], e, re.compile(ident["text"], re.IGNORECASE)))
    return out


def _pages(entry: dict) -> int:
    return entry["identify"].get("pages", IDENTIFY_PAGES)


def xlsx_text(path: Path) -> str:
    """A workbook's shared strings and sheet names, joined: what its title cells say."""
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    parts = []
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        if "xl/workbook.xml" in names:
            root = ElementTree.fromstring(z.read("xl/workbook.xml"))
            parts += [s.get("name", "") for s in root.iter(f"{ns}sheet")]
        if "xl/sharedStrings.xml" in names:
            root = ElementTree.fromstring(z.read("xl/sharedStrings.xml"))
            parts += [t.text or "" for t in root.iter(f"{ns}t")]
    return " ".join(parts)


def xls_text(path: Path) -> str:
    """A BIFF8 workbook's sheet names and cell text, joined: what its titles say."""
    return " ".join(xls_blocks(path))


def _utf8(data: bytes) -> str | None:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None


def _is_plain_text(data: bytes) -> bool:
    text = _utf8(data)
    if text is None:
        return False
    head = text.lstrip("\ufeff \t\r\n")
    return bool(head) and not head.startswith("<")


def _json_doc(data: bytes):
    """The parsed document, or None if the bytes are not one whole JSON document (a
    truncated save is not the document)."""
    text = _utf8(data)
    if text is None or not text.lstrip().startswith(("{", "[")):
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


class _NotXml(ValueError):
    pass


def _xml_root(data: bytes):
    """The root element of a well-formed XML document that declares no entities and is
    not an HTML page; raises `_NotXml` with the reason otherwise."""
    if not any(data.startswith(s) for s in F.SIGNATURES["xml"]):
        raise _NotXml("no XML signature")
    if re.search(rb"<!ENTITY", data[:65536], re.IGNORECASE):
        raise _NotXml("declares entities; an operator-saved file is not expanded")
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise _NotXml(f"not well-formed XML ({exc})") from None
    if root.tag.rsplit("}", 1)[-1].lower() == "html":
        raise _NotXml("an HTML page, not an XML document")
    return root


def format_of(data: bytes) -> tuple:
    """`(formats, detail)`: the formats the bytes can be (empty if none), and why."""
    for fmt in BINARY_FORMATS:
        if any(data.startswith(s) for s in F.SIGNATURES[fmt]):
            return (fmt,), ""
    if _json_doc(data) is not None:
        return ("json",), ""
    detail = ""
    if data.lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"<"):
        try:
            _xml_root(data.lstrip(b"\xef\xbb\xbf \t\r\n"))
            return ("xml",), ""
        except _NotXml as exc:
            detail = f"; {exc}"
    if _is_plain_text(data):
        return PLAIN_TEXT_FORMATS, ""
    return (), detail


def title_text(path: Path, fmt: str, pages: int = IDENTIFY_PAGES) -> str:
    if fmt == "pdf":
        text = " ".join(pdf_pages(path)[:pages])
    elif fmt == "xls":
        text = xls_text(path)
    elif fmt in PLAIN_TEXT_FORMATS:
        text = _utf8(path.read_bytes()) or ""
    elif fmt == "json":
        # Re-serialized, so a rule does not depend on how the file was indented.
        text = json.dumps(_json_doc(path.read_bytes()), ensure_ascii=False)
    elif fmt == "xml":
        root = _xml_root(path.read_bytes().lstrip(b"\xef\xbb\xbf \t\r\n"))
        attrs = " ".join(f'{k}="{v}"' for k, v in root.attrib.items())
        text = f"{root.tag.rsplit('}', 1)[-1]} {attrs} " + " ".join(root.itertext())
    else:
        text = xlsx_text(path)
    return re.sub(r"\s+", " ", text).strip()


def identify(path: Path, table: list) -> tuple:
    """`(doc_id or None, detail)`: the rule that matched, or why none did."""
    data = path.read_bytes()
    formats, why = format_of(data)
    if not formats:
        return None, f"no known format signature (leading bytes {data[:8]!r}){why}"
    texts: dict = {}
    hits = []
    digest = hashlib.sha256(data).hexdigest()
    for doc_id, e, rx in table:
        fmt = held_format(e)
        if fmt not in formats:
            continue
        if isinstance(rx, str):
            if rx == digest:
                hits.append((doc_id, fmt, None))
            continue
        key = (fmt, _pages(e) if fmt == "pdf" else None)
        if key not in texts:
            texts[key] = title_text(path, fmt, key[1] or IDENTIFY_PAGES)
        if rx.search(texts[key]):
            hits.append((doc_id, fmt, rx.pattern))
    if len(hits) == 1:
        doc_id, fmt, pattern = hits[0]
        if pattern is None:
            return doc_id, f"format {fmt}; identify.sha256 {digest}"
        return doc_id, f"format {fmt}; identify.text {pattern!r}"
    if not hits:
        sample = next(iter(texts.values()), "")
        return (
            None,
            f"format {'/'.join(formats)}; no identify.text matched "
            f"(title text: {sample[:160]!r})",
        )
    return None, f"ambiguous: {[h[0] for h in hits]} all matched; refusing to guess"


def registered(log: Path) -> dict:
    """doc_id -> its latest registration row."""
    out = {}
    for row in F.FetchLog(log).rows():
        if row.get("event") == "registered":
            out[row["doc_id"]] = row
    return out


def _place(src: Path, dst: Path) -> None:
    """Copy via an fsynced temp file and an atomic rename."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dst.parent, prefix=f".{dst.name}.")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(src.read_bytes())
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, dst)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _parse_pairs(pairs: list, what: str) -> dict:
    out = {}
    for p in pairs or []:
        if "=" not in p:
            raise RegistrationError(f"--{what} takes DOC_ID=VALUE, not {p!r}")
        k, v = p.split("=", 1)
        out[k] = v
    return out


def _first(*pairs) -> tuple:
    """The first `(value, basis)` with a value; the last pair if none has one."""
    return next((p for p in pairs if p[0]), pairs[-1])


def _provenance(stated_url, clip_url, entry_url, stated_date, clip_date, mtime) -> dict:
    """URL and retrieval date, each from the first of: the operator's statement, the
    clipping's front matter, the source list (URL) or the file's mtime (date)."""
    url, url_basis = _first(
        (stated_url, "stated by the operator"),
        (clip_url, "clipping front matter `source:`"),
        (entry_url, "corpus/sources.yaml url"),
    )
    date, date_basis = _first(
        (stated_date, "stated by the operator"),
        (clip_date, "clipping front matter `created:`"),
        (mtime, "file mtime"),
    )
    return {
        "source_url": url,
        "source_url_basis": url_basis,
        "retrieved_date": date,
        "retrieved_date_basis": date_basis,
    }


def rerecord(doc_ids: list, log: Path, repo: Path) -> list:
    """Append a restated row for each registered Markdown clipping, with the provenance
    its front matter carries. The held bytes must still be the registered bytes."""
    prior = registered(log)
    flog = F.FetchLog(log)
    out = []
    for doc_id in doc_ids:
        old = prior.get(doc_id)
        held = repo / old["stored_at"] if old else None
        if not old or held.suffix != ".md" or not held.is_file():
            raise RegistrationError(f"{doc_id}: not a held Markdown clipping")
        data = held.read_bytes()
        if hashlib.sha256(data).hexdigest() != old["sha256"]:
            raise RegistrationError(f"{doc_id}: {held} no longer hashes to its row")
        clip = clipping_front_matter(data.decode("utf-8"))
        if not clip.get("source") or not clip.get("created"):
            raise RegistrationError(
                f"{doc_id}: no `source:` and `created:` front matter"
            )
        row = {
            **old,
            **_provenance(None, clip["source"], None, None, clip["created"], None),
            "supersedes_sha256": None,
            "corrects_registered_at": old["registered_at"],
            "correction": "provenance restated from the clipping's front matter "
            "(HB-01d ADDENDUM-00)",
            "registered_at": _now(),
        }
        flog.write(row)
        out.append(row)
    return out


def queue_statuses(path: Path = QUEUE_CONFIG) -> tuple:
    """`(awaiting, held)`: the manifest's queue states, from the queue's
    configuration."""
    try:
        status = (yaml.safe_load(path.read_text(encoding="utf-8")) or {})["status"]
        return status["awaiting"], status["held"]
    except (OSError, yaml.YAMLError, KeyError, TypeError) as exc:
        raise RegistrationError(
            f"{path}: cannot read status.awaiting and status.held ({exc})"
        ) from None


def mark_held(path: Path, doc_ids: list, statuses: tuple) -> list:
    """Set `status: <held>` on each named row of the source list whose status is
    `<awaiting>`, by editing that one line, so the hand-authored file keeps its
    comments and layout. Atomic (fsynced temp file and rename) and verified by parsing
    the result. Returns the doc_ids it changed; a row already held is left alone."""
    awaiting, held = statuses
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    changed = []
    for doc_id in doc_ids:
        head = f"- doc_id: {doc_id}"
        starts = [i for i, ln in enumerate(lines) if ln.rstrip("\r\n") == head]
        if len(starts) != 1:
            raise RegistrationError(f"{doc_id}: {len(starts)} `{head}` lines in {path}")
        start = starts[0]
        end = next(
            (
                j
                for j in range(start + 1, len(lines))
                if lines[j].startswith("- doc_id:")
            ),
            len(lines),
        )
        at = [
            j
            for j in range(start + 1, end)
            if re.fullmatch(rf"  status: {re.escape(awaiting)}\s*", lines[j])
        ]
        if not at:
            if any(
                re.fullmatch(rf"  status: {re.escape(held)}\s*", lines[j])
                for j in range(start + 1, end)
            ):
                continue
            raise RegistrationError(f"{doc_id}: no `status: {awaiting}` line in {path}")
        if len(at) > 1:
            raise RegistrationError(f"{doc_id}: {len(at)} status lines in {path}")
        lines[at[0]] = f"  status: {held}\n"
        changed.append(doc_id)
    if not changed:
        return []
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("".join(lines))
            fh.flush()
            os.fsync(fh.fileno())
        rows = {e["doc_id"]: e for e in F.load_sources(Path(tmp))}
        wrong = [d for d in changed if rows[d].get("status") != held]
        if wrong:
            raise RegistrationError(f"{wrong}: the edit did not parse as status {held}")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return changed


def run(
    inbox: Path,
    raw: Path,
    sources: list,
    log: Path,
    repo: Path,
    urls: dict | None = None,
    retrieved: dict | None = None,
    dry_run: bool = False,
    statuses: tuple | None = None,
    sources_path: Path | None = None,
    queue_only: bool = False,
) -> dict:
    """Register every inbox file. Returns {"registered": [...], "skipped": [...],
    "unmatched": [...], "left": [...], "marked_held": [...]}.

    HB-147: with `statuses` (`(awaiting, held)`) and `sources_path`, a registered row
    whose status is awaiting is marked held in the source list, and so is any awaiting
    row an earlier run registered but did not mark (a kill between the two). With
    `queue_only`, a file identified as any other row is left in the inbox (`left`)."""
    if (statuses is None) != (sources_path is None):
        raise RegistrationError("statuses and sources_path go together")
    if queue_only and statuses is None:
        raise RegistrationError("--queue needs the queue's statuses")
    table = rules(sources)
    known = {e["doc_id"]: e for e in sources}
    for k in list(urls or {}) + list(retrieved or {}):
        if k not in known:
            raise RegistrationError(f"unknown doc_id {k!r} on the command line")
    prior = registered(log)
    flog = F.FetchLog(log)
    result = {
        "registered": [],
        "skipped": [],
        "unmatched": [],
        "left": [],
        "marked_held": [],
    }
    awaiting_ids = (
        {e["doc_id"] for e in sources if e.get("status") == statuses[0]}
        if statuses
        else set()
    )
    if statuses and not dry_run:
        healed = sorted(awaiting_ids & set(prior))
        if healed:
            result["marked_held"] += mark_held(sources_path, healed, statuses)
    files = sorted(
        p for p in inbox.iterdir() if p.is_file() and not p.name.startswith(".")
    )
    # Identify every file before moving any: two files that claim one doc_id would
    # otherwise land on the same corpus/raw/ path and the second would replace the first
    # (HB-01b: cre_file_layout_2024.pdf and cre_rankings_file_layout_2024.pdf).
    ident = {p: identify(p, table) for p in files}
    claims = {}
    for p, (doc_id, _) in ident.items():
        if doc_id:
            claims.setdefault(doc_id, []).append(p.name)
    for path in files:
        doc_id, detail = ident[path]
        if doc_id and len(claims[doc_id]) > 1:
            doc_id, detail = (
                None,
                f"{claims[doc_id]} all claim {doc_id}; refusing to guess",
            )
        if doc_id is None:
            result["unmatched"].append({"file": path.name, "reason": detail})
            continue
        if queue_only and doc_id not in awaiting_ids:
            result["left"].append(
                {
                    "file": path.name,
                    "doc_id": doc_id,
                    "reason": f"not a queued row (status {statuses[0]})",
                }
            )
            continue
        entry = known[doc_id]
        data = path.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        dst = raw / f"{doc_id}{EXTENSIONS[held_format(entry)]}"
        old = prior.get(doc_id)
        if old and old["sha256"] == sha and dst.exists():
            if hashlib.sha256(dst.read_bytes()).hexdigest() == sha:
                if not dry_run:
                    path.unlink()
                result["skipped"].append({"file": path.name, "doc_id": doc_id})
                continue
        mtime = datetime.fromtimestamp(path.stat().st_mtime).date().isoformat()
        clip = (
            clipping_front_matter(path.read_text(encoding="utf-8"))
            if held_format(entry) == "md"
            else {}
        )
        prov = _provenance(
            (urls or {}).get(doc_id),
            clip.get("source"),
            entry.get("url"),
            (retrieved or {}).get(doc_id),
            clip.get("created"),
            mtime,
        )
        # HB-01e: a clipping that followed a redirect names the page it saved; the URL
        # the source list asked for is kept beside it, so neither is lost.
        requested = entry.get("url")
        row = {
            "event": "registered",
            "doc_id": doc_id,
            "acquisition": ACQUISITION,
            "acquired_by": ACQUIRED_BY,
            "original_filename": path.name,
            "sha256": sha,
            "bytes": len(data),
            **prov,
            "requested_url": requested
            if requested and requested != prov["source_url"]
            else None,
            "identified_by": detail,
            "stored_at": str(dst.relative_to(repo)),
            "supersedes_sha256": old["sha256"]
            if old and old["sha256"] != sha
            else None,
            "registered_at": _now(),
        }
        if dry_run:
            result["registered"].append(row)
            continue
        _place(path, dst)
        flog.write(row)
        path.unlink()
        result["registered"].append(row)
        if doc_id in awaiting_ids:
            result["marked_held"] += mark_held(sources_path, [doc_id], statuses)
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--inbox", type=Path, default=REPO / "corpus" / "inbox")
    ap.add_argument("--raw", type=Path, default=REPO / "corpus" / "raw")
    ap.add_argument("--sources", type=Path, default=REPO / "corpus" / "sources.yaml")
    ap.add_argument(
        "--log", type=Path, default=REPO / "corpus" / "operator_downloads.jsonl"
    )
    ap.add_argument("--repo", type=Path, default=REPO)
    ap.add_argument(
        "--url", nargs="+", metavar="DOC_ID=URL", help="a URL the operator states"
    )
    ap.add_argument(
        "--retrieved",
        nargs="+",
        metavar="DOC_ID=DATE",
        help="a retrieval date the operator states",
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="identify and report; move nothing"
    )
    ap.add_argument(
        "--queue",
        action="store_true",
        help="register only files identified as acquisition-queue rows "
        "(status awaiting_operator); leave every other inbox file in place",
    )
    ap.add_argument(
        "--no-render",
        action="store_true",
        help="do not re-render docs/evidence/acquisition/queue.html afterwards",
    )
    ap.add_argument(
        "--rerecord",
        nargs="+",
        metavar="DOC_ID",
        help="restate registered clippings with their front-matter provenance",
    )
    a = ap.parse_args(argv)
    if a.rerecord:
        try:
            out = {"rerecorded": rerecord(a.rerecord, a.log, a.repo)}
        except RegistrationError as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(out, indent=1, sort_keys=True))
        return 0
    try:
        if not a.inbox.is_dir():
            raise RegistrationError(f"no inbox at {a.inbox}")
        out = run(
            a.inbox,
            a.raw,
            F.load_sources(a.sources),
            a.log,
            a.repo,
            urls=_parse_pairs(a.url, "url"),
            retrieved=_parse_pairs(a.retrieved, "retrieved"),
            dry_run=a.dry_run,
            statuses=queue_statuses(),
            sources_path=a.sources,
            queue_only=a.queue,
        )
    except (RegistrationError, F.ConfigError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(out, indent=1, sort_keys=True))
    if not a.dry_run and not a.no_render:
        # HB-147: the page drops a registered row from its awaiting table now, not at
        # the next gate. Loaded here, not at import: the page's script imports this one.
        spec = importlib.util.spec_from_file_location(
            "acquisition_queue", REPO / "scripts" / "acquisition_queue.py"
        )
        aq = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(aq)
        try:
            page = aq.write_page(a.repo)
        except (aq.QueueError, F.ConfigError, RegistrationError) as exc:
            print(
                f"registered, but the queue page was not rendered: {exc}",
                file=sys.stderr,
            )
            return 1
        print(json.dumps({"queue_page": page}, indent=1))
    # Unmatched files are reported, not an error: the operator may have saved a file no
    # manifest entry names (DN-002 section 3), and it stays in the inbox for the RESULT.
    return 0


if __name__ == "__main__":
    sys.exit(main())
