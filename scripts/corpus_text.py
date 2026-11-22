"""Text, page counts and license markings from held corpus files.

**No network, no model.**

Shared by `build_corpus_manifest.py` (license markings, page and character counts) and
the tests. PDFs are read with pypdfium2, the reader Squiddy's own acquire stage uses
(`squiddy/pdftext.py`), so a character count here is the count Squiddy would size a
document by. HTML is reduced to visible text with the standard library's `html.parser`.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path

#: Phrases that mark a document's reuse terms. Matched case-insensitively; each hit is
#: recorded with its location so the manifest states what was SEEN, never what was
#: assumed (HB-01 rule 4).
LICENSE_PATTERNS = (
    r"public domain",
    r"not (?:subject to )?copyright(?:ed)?",
    r"copyright",
    r"©",
    r"all rights reserved",
    r"may be (?:freely )?(?:reproduced|copied|reprinted)",
    r"without permission",
    r"creative commons",
    r"\bCC0\b",
    r"17 U\.?S\.?C\.? (?:§ ?)?105",
    # A bare "license" matched "license numbers" and "licensed practical nurse"
    # (2026-10-20 first build); only a license key in structured metadata or "licensed
    # under" counts.
    r'"license"\s*:',
    r"licensed under",
)
_LICENSE_RE = re.compile("|".join(f"(?:{p})" for p in LICENSE_PATTERNS), re.IGNORECASE)
SNIPPET_CHARS = 90
MAX_MARKINGS = 4


class _Visible(HTMLParser):
    """Visible text: everything outside <script>, <style>, <noscript> and <template>."""

    SKIP = {"script", "style", "noscript", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth, self.parts = 0, []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.depth += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if not self.depth:
            self.parts.append(data)


def html_text(raw: bytes) -> str:
    parser = _Visible()
    parser.feed(raw.decode("utf-8", "replace"))
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()


def pdf_pages(path: Path) -> list:
    """One string per page."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(path))
    try:
        pages = []
        for i in range(len(doc)):
            page = doc[i]
            textpage = page.get_textpage()
            pages.append(textpage.get_text_range())
            textpage.close()
            page.close()
        return pages
    finally:
        doc.close()


def read_pages(path: Path) -> list | None:
    """Text by page (HTML, JSON, CSV and text count as one page), or None for a binary
    format with no text layer this module reads (xlsx, xls, zip)."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return pdf_pages(path)
    raw = path.read_bytes()
    if suffix in (".html", ".htm"):
        return [html_text(raw)]
    if suffix == ".json":
        return [json.dumps(json.loads(raw), ensure_ascii=False)]
    if suffix in (".csv", ".txt", ".xml", ".md"):
        return [raw.decode("utf-8", "replace")]
    return None


def license_markings(pages: list) -> list:
    """Up to MAX_MARKINGS `{"where", "text"}` hits, each a snippet around the match."""
    hits = []
    for n, text in enumerate(pages, 1):
        for m in _LICENSE_RE.finditer(text):
            lo = max(0, m.start() - SNIPPET_CHARS // 2)
            snippet = re.sub(
                r"\s+", " ", text[lo : m.end() + SNIPPET_CHARS // 2]
            ).strip()
            where = f"page {n}" if len(pages) > 1 else "document"
            hits.append({"where": where, "text": snippet})
            if len(hits) >= MAX_MARKINGS:
                return hits
    return hits


# ------------------------------------------------------------------ text derivatives
# HB-01b: Squiddy reads a PDF, or a `.txt` whose pages are separated by a form feed
# (squiddy/pdftext.py PAGE_BREAK; texts.py). The index cuts each page into paragraph
# units (pdftext.paragraphs_of), so a held HTML page reduced to one line of text
# (`read_pages`) would be ONE search unit. `text_blocks` instead returns one block per
# structural unit, each a single line; written joined by form feeds, each block is one
# unit with its own receipt. Shape from the HB-01b spike's converter (one block per
# block-level element, each table one block with "; "-separated rows and " | "-separated
# cells).

PAGE_BREAK = "\f"
#: A block shorter than this that ends in ":" (CAMEO's "ERG Table 3:") is a heading for
#: the table that follows, and is folded into it so the heading and its rows are one
#: unit (the spike ranked a guide page above CAMEO's Table 3 because the heading sat
#: alone).
HEADING_MAX_CHARS = 80
#: JSON values longer than this are split into one block per member or item; shorter
#: ones are one block. 2,000 characters is twice the index's `text_max_chars` display
#: width (the corpus graph), so a block is never cut
#: mid-member for display by more than one screen.
JSON_BLOCK_MAX_CHARS = 2000
#: A table whose text is longer than this is written one block per row, each row
#: prefixed by the table's heading and header row, so a 2,770-row index (PubChem's ERG
#: UN index) is 2,770 self-describing units instead of one; a shorter table stays one
#: unit (a CAMEO Table 3 with its rows). Same bound as a JSON block, for the same
#: reason.
TABLE_BLOCK_MAX_CHARS = JSON_BLOCK_MAX_CHARS
#: CFR XML elements that are one block each (GPO's CFR bulk DTD): paragraphs, headings
#: and one GPOTABLE row, the unit 49 CFR 172.101's Hazardous Materials Table is read by.
XML_BLOCK_TAGS = {
    "P",
    "FP",
    "HD",
    "SECTNO",
    "SUBJECT",
    "ROW",
    "NOTE",
    "EXTRACT",
    "TTITLE",
}


class _Blocks(HTMLParser):
    SKIP = {"script", "style", "noscript", "template"}
    BLOCK = {
        "p",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "section",
        "article",
        "header",
        "footer",
        "nav",
        "ul",
        "ol",
        "dl",
        "dt",
        "dd",
        "caption",
        "blockquote",
        "pre",
        "br",
        "hr",
        "form",
        "title",
        "thead",
        "tbody",
    }
    HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6", "caption", "title"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth, self.table, self.blocks, self.cur = 0, 0, [], []
        self.last_heading = False
        self.heading, self.rows = "", []

    def _end_row(self) -> None:
        text = re.sub(r"\s+", " ", "".join(self.cur)).strip(" |;")
        self.cur = []
        if text:
            self.rows.append(text)

    def _end_table(self) -> None:
        self._end_row()
        rows, head, self.rows, self.heading = self.rows, self.heading, [], ""
        if not rows:
            return
        whole = " ; ".join(rows)
        if len(head) + len(whole) <= TABLE_BLOCK_MAX_CHARS:
            self.blocks.append(f"{head} ; {whole}" if head else whole)
        else:
            prefix = " ; ".join(x for x in (head, rows[0]) if x)
            self.blocks.append(prefix)
            self.blocks += [f"{prefix} ; {r}" for r in rows[1:]]
        self.last_heading = False

    def flush(self, heading: bool = False) -> None:
        text = re.sub(r"\s+", " ", "".join(self.cur)).strip(" |;")
        self.cur = []
        if text:
            self.blocks.append(text)
            self.last_heading = heading or (
                len(text) <= HEADING_MAX_CHARS and text.endswith(":")
            )

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.depth += 1
        elif tag == "table":
            if not self.table:
                self.flush()
                if self.blocks and self.last_heading:
                    self.heading = self.blocks.pop()
            self.table += 1
        elif tag in self.BLOCK and not self.table:
            self.flush()
        elif tag == "tr" and self.table:
            self._end_row()
        elif tag in ("td", "th"):
            self.cur.append(" | ")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.depth:
            self.depth -= 1
        elif tag == "table":
            self.table = max(0, self.table - 1)
            if not self.table:
                self._end_table()
        elif tag in self.BLOCK and not self.table:
            self.flush(heading=tag in self.HEADINGS)

    def handle_data(self, data):
        if not self.depth:
            self.cur.append(data)


def html_blocks(raw: bytes) -> list:
    parser = _Blocks()
    parser.feed(raw.decode("utf-8", "replace"))
    parser.close()
    parser.flush()
    return parser.blocks


def _json_blocks(obj, prefix: str, out: list) -> None:
    text = json.dumps(obj, ensure_ascii=False)
    if isinstance(obj, str) and len(text) > JSON_BLOCK_MAX_CHARS:
        # One scalar longer than a block (the Census API's 99 KB `concept` string): cut
        # at commas or spaces into blocks of at most JSON_BLOCK_MAX_CHARS.
        piece = ""
        for tok in re.split(r"(?<=[, ])", obj):
            if piece and len(piece) + len(tok) > JSON_BLOCK_MAX_CHARS:
                out.append(f"{prefix}: {piece.strip()}")
                piece = ""
            piece += tok
        if piece.strip():
            out.append(f"{prefix}: {piece.strip()}")
        return
    if (
        len(text) <= JSON_BLOCK_MAX_CHARS
        or not isinstance(obj, (dict, list))
        or not obj
    ):
        out.append(f"{prefix}: {text}" if prefix else text)
        return
    if isinstance(obj, dict):
        items = obj.items()
    else:
        # A list item that names itself (a string `id`) is prefixed by that name, so a
        # block of the API catalog reads `apis[census_data].auth`, not `apis.1.auth`.
        # Numeric ids (ArcGIS layers, Socrata columns) keep the index, so derivatives
        # written before this rule (HB-01b) are unchanged.
        items = [
            (f"[{v['id']}]" if isinstance(v, dict) and isinstance(v.get("id"), str)
             else str(i), v)
            for i, v in enumerate(obj)
        ]  # fmt: skip
    for k, v in items:
        sep = "" if str(k).startswith("[") else "."
        _json_blocks(v, f"{prefix}{sep}{k}" if prefix else str(k), out)


def json_blocks(raw: bytes) -> list:
    out: list = []
    _json_blocks(json.loads(raw), "", out)
    return out


def csv_blocks(raw: bytes) -> list:
    """One block per row, each cell labelled by its header: a row is self-describing."""
    import csv
    import io

    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig", "replace"))))
    if not rows:
        return []
    head = rows[0]
    out = [" | ".join(head)]
    for r in rows[1:]:
        cells = [f"{h}: {v}" for h, v in zip(head, r) if v.strip()]
        if cells:
            out.append(" | ".join(cells))
    return out


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def xml_blocks(path: Path) -> list:
    """One block per XML_BLOCK_TAGS element (a ROW's cells joined by " | "), streamed
    with iterparse so a 10 MB CFR volume is never a DOM. An XML with none of those tags
    falls back to one block per element that carries text of its own."""
    from xml.etree import ElementTree

    out, fallback = [], []
    for _, el in ElementTree.iterparse(str(path), events=("end",)):
        tag = _local(el.tag)
        if tag in XML_BLOCK_TAGS:
            if tag == "ROW":
                text = " | ".join(
                    re.sub(r"\s+", " ", "".join(c.itertext())).strip() for c in el
                )
            else:
                text = re.sub(r"\s+", " ", "".join(el.itertext())).strip()
            if text.strip(" |"):
                out.append(text)
            el.clear()
        elif el.text and el.text.strip() and not len(el):
            fallback.append(re.sub(r"\s+", " ", el.text).strip())
    return out or fallback


def xlsx_blocks(path: Path) -> list:
    """One block per non-empty row of every sheet, prefixed by the sheet name. Shared
    and inline strings are resolved; numbers are kept as written."""
    import zipfile
    from xml.etree import ElementTree

    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    rel = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    out = []
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ElementTree.fromstring(z.read("xl/sharedStrings.xml"))
            shared = [
                "".join(t.text or "" for t in si.iter(f"{ns}t"))
                for si in root.iter(f"{ns}si")
            ]
        rels = ElementTree.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        targets = {r.get("Id"): r.get("Target") for r in rels}
        book = ElementTree.fromstring(z.read("xl/workbook.xml"))
        for sheet in book.iter(f"{ns}sheet"):
            target = targets[sheet.get(rel)].lstrip("/")
            target = target if target.startswith("xl/") else f"xl/{target}"
            root = ElementTree.fromstring(z.read(target))
            for row in root.iter(f"{ns}row"):
                cells = []
                for c in row.iter(f"{ns}c"):
                    v = c.find(f"{ns}v")
                    if c.get("t") == "s" and v is not None:
                        cells.append(shared[int(v.text)])
                    elif c.get("t") == "inlineStr":
                        cells.append("".join(t.text or "" for t in c.iter(f"{ns}t")))
                    elif v is not None and v.text is not None:
                        cells.append(v.text)
                cells = [
                    re.sub(r"\s+", " ", x).strip() for x in cells if x and x.strip()
                ]
                if cells:
                    out.append(f"{sheet.get('name')}: " + " | ".join(cells))
    return out


def _col_index(ref: str) -> int:
    """0-based column of an A1-style cell reference ("C12" -> 2)."""
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def xlsx_rows(path: Path, sheet_index: int = 0) -> list:
    """Every row of one sheet as a list of cell strings by column position (empty cells
    are ""), so a column keeps its meaning where `xlsx_blocks` would close the gap
    (HB-03b Key C). Shared and inline strings resolved; numbers as written."""
    import zipfile
    from xml.etree import ElementTree

    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    rel = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ElementTree.fromstring(z.read("xl/sharedStrings.xml"))
            shared = [
                "".join(t.text or "" for t in si.iter(f"{ns}t"))
                for si in root.iter(f"{ns}si")
            ]
        rels = ElementTree.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        targets = {r.get("Id"): r.get("Target") for r in rels}
        book = ElementTree.fromstring(z.read("xl/workbook.xml"))
        sheet = list(book.iter(f"{ns}sheet"))[sheet_index]
        target = targets[sheet.get(rel)].lstrip("/")
        target = target if target.startswith("xl/") else f"xl/{target}"
        root = ElementTree.fromstring(z.read(target))
        out = []
        for row in root.iter(f"{ns}row"):
            cells: dict = {}
            for c in row.iter(f"{ns}c"):
                v = c.find(f"{ns}v")
                if c.get("t") == "s" and v is not None:
                    text = shared[int(v.text)]
                elif c.get("t") == "inlineStr":
                    text = "".join(t.text or "" for t in c.iter(f"{ns}t"))
                elif v is not None and v.text is not None:
                    text = v.text
                else:
                    text = ""
                cells[_col_index(c.get("r"))] = text
            width = max(cells) + 1 if cells else 0
            out.append([cells.get(i, "") for i in range(width)])
    return out


def xls_rows(path: Path, sheet_index: int = 0) -> list:
    """Every row of one BIFF8 sheet as cell strings by column position (`_xls_cell`)."""
    import xlrd

    sheet = xlrd.open_workbook(path).sheet_by_index(sheet_index)
    return [[_xls_cell(c) for c in sheet.row(r)] for r in range(sheet.nrows)]


def _xls_cell(cell) -> str:
    """A cell as the sheet shows it. xlrd reads every number as a float; an integral one
    (a UN number, a distance in feet) is written without the ".0" the page never had."""
    import xlrd

    if cell.ctype == xlrd.XL_CELL_NUMBER and float(cell.value).is_integer():
        return str(int(cell.value))
    if cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
        return ""
    return str(cell.value)


def xls_blocks(path: Path) -> list:
    """One block per non-empty row of every sheet of a BIFF8 (`.xls`) workbook,
    prefixed by the sheet name, as `xlsx_blocks` does for OOXML. HB-01d: PHMSA ships
    three ERG2020 tables only in this format; xlrd is its reader (the standard library
    has none)."""
    import xlrd

    out = []
    book = xlrd.open_workbook(path)
    for sheet in book.sheets():
        for r in range(sheet.nrows):
            cells = [_xls_cell(c) for c in sheet.row(r)]
            cells = [re.sub(r"\s+", " ", x).strip() for x in cells if x and x.strip()]
            if cells:
                out.append(f"{sheet.name}: " + " | ".join(cells))
    return out


#: A browser clipping's own artifacts (HB-01d ADDENDUM-00): links and images that point
#: into the clipper extension (`chrome-extension://...`), not at the page's content. An
#: image wrapped in such a link goes whole; a text link keeps its text.
_CLIP_LINKED_IMAGE = re.compile(r"\[!\[[^\]]*\]\([^)]*\)\]\(chrome-extension://[^)]*\)")
_CLIP_IMAGE = re.compile(r"!\[[^\]]*\]\(chrome-extension://[^)]*\)")
_CLIP_LINK = re.compile(r"\[([^\]]*)\]\(chrome-extension://[^)]*\)")
_FRONT_MATTER = re.compile(r"\A\ufeff?---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
#: MarkDownload's `created:` form, "2026-10-21T08:01:40 (UTC -04:00)".
_CLIP_CREATED = re.compile(
    r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d) \(UTC ([+-]\d\d:\d\d)\)$"
)


def strip_clipping_artifacts(text: str) -> str:
    text = _CLIP_LINKED_IMAGE.sub("", text)
    text = _CLIP_IMAGE.sub("", text)
    return _CLIP_LINK.sub(r"\1", text)


def clipping_front_matter(text: str) -> dict:
    """The `key: value` lines of a clipping's leading front matter (`source:`, the page
    URL; `created:`, the save time as ISO 8601 with its offset), or {} if none."""
    m = _FRONT_MATTER.match(text)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep and value.strip():
            out[key.strip()] = value.strip()
    c = _CLIP_CREATED.match(out.get("created", ""))
    if c:
        out["created"] = c.group(1) + c.group(2)
    return out


def paragraph_blocks(raw: bytes) -> list:
    """Blank-line-separated paragraphs, whitespace collapsed (text and Markdown)."""
    text = raw.decode("utf-8", "replace")
    return [
        re.sub(r"\s+", " ", b).strip() for b in re.split(r"\n\s*\n", text) if b.strip()
    ]


# ------------------------------------------------------------------ OCR of a scan
# HB-122: a scan with no text layer (the 1991 dense-gas evaluation: 0 characters on 114
# pages) is read by the kit's own OCR, which drops runs of words (HB-102). The kit's
# route for any form it should not read itself is the consumer's converter (squiddy
# docs/KIT_BOUNDARY.md, "Limits a consumer meets"): this renders each page (pdftoppm)
# and reads it with tesseract, HB-102's settings (`docs/evidence/hb102/ocr_pages.sh`).
# The blocks are one per PDF page, so page N of the form-feed text is page N of the PDF
# and a receipt's page is the printed scan's. The engine, its version, the dpi and the
# page segmentation mode are config (`corpus/ingest_config.yaml` `ocr:`); an installed
# engine of another version is refused, because the text record names the version that
# read it.


class OcrError(RuntimeError):
    pass


def tesseract_version(binary: str = "tesseract") -> str:
    """The installed tesseract's version (the first line of `tesseract --version`)."""
    import subprocess

    r = subprocess.run(
        [binary, "--version"], capture_output=True, text=True, check=False
    )
    first = (r.stdout or r.stderr).strip().splitlines()
    if r.returncode != 0 or not first:
        raise OcrError(f"`{binary} --version` failed (rc {r.returncode})")
    return first[0].split()[-1]


def ocr_pdf_blocks(path: Path, ocr: dict) -> list:
    """One OCR text per page of a PDF, in page order. `ocr` is the config section:
    `engine` (tesseract), `version`, `dpi`, `psm`."""
    import subprocess
    import tempfile

    for key in ("engine", "version", "dpi", "psm"):
        if key not in ocr:
            raise OcrError(f"ocr config lacks `{key}`")
    if ocr["engine"] != "tesseract":
        raise OcrError(f"ocr engine {ocr['engine']!r}: only tesseract is wired")
    installed = tesseract_version(ocr["engine"])
    if installed != str(ocr["version"]):
        raise OcrError(
            f"the config declares tesseract {ocr['version']} and {installed} is "
            "installed; re-declare the version (a new text, a new record)"
        )
    path = Path(path).resolve()
    from pypdfium2 import PdfDocument

    doc = PdfDocument(str(path))
    try:
        n = len(doc)
    finally:
        doc.close()
    blocks = []
    # tesseract 5.5.0 cannot open an absolute /tmp image path (HB-102), so it runs from
    # the scratch directory on a relative name.
    with tempfile.TemporaryDirectory(prefix="hb_ocr_") as tmp:
        for p in range(1, n + 1):
            stem = f"img{p}"
            r = subprocess.run(
                ["pdftoppm", "-r", str(ocr["dpi"]), "-gray", "-f", str(p), "-l", str(p)]
                + ["-png", str(path), stem],
                cwd=tmp,
                capture_output=True,
                text=True,
                check=False,
            )
            imgs = sorted(Path(tmp).glob(f"{stem}-*.png"))
            if r.returncode != 0 or not imgs:
                raise OcrError(
                    f"{path.name} p{p}: pdftoppm rc {r.returncode}: {r.stderr[-300:]}"
                )
            out = f"p{p}"
            r = subprocess.run(
                [ocr["engine"], imgs[0].name, out, "--psm", str(ocr["psm"])],
                cwd=tmp,
                capture_output=True,
                text=True,
                check=False,
            )
            txt = Path(tmp) / f"{out}.txt"
            if r.returncode != 0 or not txt.exists():
                raise OcrError(
                    f"{path.name} p{p}: tesseract rc {r.returncode}: {r.stderr[-300:]}"
                )
            blocks.append(txt.read_text(encoding="utf-8").rstrip("\n"))
            imgs[0].unlink()
    return blocks


def text_blocks(path: Path) -> list | None:
    """The form-feed derivative's blocks for a held file Squiddy cannot read itself, or
    None for a PDF (Squiddy reads it in place) or a format with no converter."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return None
    if suffix in (".html", ".htm"):
        return html_blocks(path.read_bytes())
    if suffix == ".json":
        return json_blocks(path.read_bytes())
    if suffix in (".yaml", ".yml"):
        import yaml

        out: list = []
        _json_blocks(yaml.safe_load(path.read_text(encoding="utf-8")), "", out)
        return out
    if suffix == ".jsonl":
        lines = path.read_text(encoding="utf-8").splitlines()
        return [ln for ln in lines if ln.strip()]
    if suffix == ".csv":
        return csv_blocks(path.read_bytes())
    if suffix == ".xml":
        return xml_blocks(path)
    if suffix == ".xlsx":
        return xlsx_blocks(path)
    if suffix == ".xls":
        return xls_blocks(path)
    # Markdown (HB-01d: the operator's browser clippings of pages this client is
    # refused) is read as the paragraphs it is written in, like plain text, less the
    # clipper's own link artifacts (ADDENDUM-00).
    if suffix == ".md":
        text = path.read_bytes().decode("utf-8", "replace")
        return paragraph_blocks(strip_clipping_artifacts(text).encode("utf-8"))
    if suffix == ".txt":
        return paragraph_blocks(path.read_bytes())
    return None
