# ruff: noqa: E501  (docstring and comments kept whole)
"""HB-220: the accepted pitch deck lands as an accepted file, with a record and a check.

The pitch deck (`docs/submission/pitch_deck.pdf` and `.html`) was built by hand and accepted by
the operator on 2026-11-22 (Issue 42e7a88a). It is not generated, so nothing here rebuilds it;
these tests hold it to its acceptance record (`docs/submission/pitch_deck.accepted.yaml`):
each file is the accepted bytes, every number the deck prints is still in the held file it was
read from, the PDF has its 15 pages, and the deck's text names neither "the author" nor "the
operator". A failure here means the deck or its source moved: report it, do not edit the deck.
"""

from __future__ import annotations

import hashlib
import html
import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
RECORD = REPO / "docs" / "submission" / "pitch_deck.accepted.yaml"
PDF = REPO / "docs" / "submission" / "pitch_deck.pdf"
HTML = REPO / "docs" / "submission" / "pitch_deck.html"


def _record() -> dict:
    return yaml.safe_load(RECORD.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _html_text() -> str:
    """The deck's visible text: no style or script, no tags, entities resolved."""
    raw = HTML.read_text(encoding="utf-8")
    raw = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", raw, flags=re.S | re.I)
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    return re.sub(r"\s+", " ", text)


def _readme_tool_rows() -> int:
    """The rows of README's Tools table (its first table after `## Tools`)."""
    section = (REPO / "README.md").read_text(encoding="utf-8").split("\n## Tools\n", 1)
    assert len(section) == 2, "README has no '## Tools' section"
    rows = []
    for line in section[1].splitlines():
        if line.startswith("|"):
            rows.append(line)
        elif rows:
            break
    return len(rows[2:])  # the header and its rule are not tools


ALL_FILES = [f["path"] for f in _record()["files"] + _record()["sources"]]


@pytest.mark.parametrize("rel", ALL_FILES)
def test_each_file_is_the_accepted_bytes(rel: str) -> None:
    want = {f["path"]: f["sha256"] for f in _record()["files"] + _record()["sources"]}
    path = REPO / rel
    assert path.is_file(), f"{rel} is not in the tree"
    assert _sha256(path) == want[rel], f"{rel} is not the accepted file"


def test_the_record_names_its_acceptance() -> None:
    acc = _record()["accepted"]
    assert acc["at"] == "2026-11-22 13:14 EST"
    assert acc["issue"] == "42e7a88a"
    assert acc["session"] == "Desktop hz-24"


@pytest.mark.parametrize("n", _record()["numbers"], ids=lambda n: n["printed"])
def test_each_number_is_printed_and_still_held(n: dict) -> None:
    assert n["printed"] in _html_text(), f"the deck no longer prints {n['printed']!r}"
    held = REPO / n["file"]
    assert held.is_file(), f"{n['file']} is gone"
    if n["match"] == "exact":
        assert n["held"] in held.read_text(encoding="utf-8"), (
            f"{n['file']} no longer holds {n['held']!r}"
        )
    elif n["match"] == "rounded":
        # The deck prints "about 66" a day; base_rates.tsv holds 66.5, which is 24,265 / 365
        # = 66.48 at one decimal. The printed whole number is within half a unit of the held
        # value, and 24,265 / 365 rounds to 66.
        assert re.search(rf"\t{re.escape(n['held'])}\t", held.read_text("utf-8")), (
            f"{n['file']} no longer holds {n['held']!r}"
        )
        assert abs(float(n["printed"]) - float(n["held"])) <= 0.5
        assert round(24265 / 365) == int(n["printed"])
    elif n["match"] == "count":
        # "Seven tools": README's Tools table has one row per tool.
        words = {"Seven": 7}
        assert _readme_tool_rows() == words[n["printed"].split()[0]]
    else:
        pytest.fail(f"unknown match {n['match']!r}")


def test_the_pdf_has_fifteen_pages() -> None:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(PDF))
    try:
        assert len(doc) == 15 == _record()["files"][0]["pages"]
    finally:
        doc.close()


@pytest.mark.parametrize("phrase", ["the author", "the operator"])
def test_the_deck_names_no_author_or_operator(phrase: str) -> None:
    assert phrase not in _html_text().lower()
