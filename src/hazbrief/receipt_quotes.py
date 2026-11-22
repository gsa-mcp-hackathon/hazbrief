"""A receipt's quote against the index row it names (HB-19).

A receipt is a Squiddy index row plus the passage it locates, quoted: the W3C Web
Annotation Data Model's TextPositionSelector paired with its TextQuoteSelector (sections
4.2.4 and 4.2.5; Phelps and Wilensky, *Robust intra-document locations*, WWW9 2000). The
row is a position in the graph's text of record; the quote is what makes it checkable.

The text of record is the parse intermediate (`index.text_of_record: parsed`, HB-14,
squiddy SQ-028R), so a row id is a parsed block, `doc#b<block>:<start>-<end>`. The
quotes were taken from the page text the index was cut from before, and the parse
renders some passages differently. Matching is therefore a cascade, as Hypothesis's
anchoring is (exact first, then a looser match, each recorded):

* `exact`: whitespace, Unicode compatibility forms and curly quotes normalised (`norm`);
* `rendering`: also the three rendering differences HB-19 observed in the parse, applied
  to both sides (`rendering_norm`). The quote itself is never edited.

A quote that neither tier finds in its row does not resolve.
"""

from __future__ import annotations

import re
import unicodedata

#: The parsed index's row id (`squiddy.text_of_record.parsed_rows`).
ROW_ID = re.compile(
    r"^(?P<doc>[a-z0-9][a-z0-9-]*)#b(?P<block>\d+):(?P<start>\d+)-(?P<end>\d+)$"
)

#: The page-text index's row id, before HB-14 declared `text_of_record: parsed`
#: (`squiddy.index.paragraph_rows`). Receipts HB-19 could not re-anchor keep it.
PAGE_ROW_ID = re.compile(
    r"^(?P<doc>[a-z0-9][a-z0-9-]*)"
    r"#p(?P<page>\d+):(?P<row>\d+):(?P<start>\d+)-(?P<end>\d+)$"
)

#: List enumerators the parse drops from a list item's text: the block keeps
#: `kind: list_item` and no marker (ics-201 block 1 reads "Incident Name:" where the
#: page printed "1. Incident Name:"; nws-10-518 "1) type of hazard"; ar-25-50 "(1) Use
#: short words."). Matched only after the start or a space and before a space.
LIST_MARKER = re.compile(
    r"(?:(?<=^)|(?<=\s))(?:\d{1,2}\.|\(\d{1,2}\)|\d{1,2}\)|[a-z]\.|•)\s+"
)
#: The parse puts a space before some punctuation (nims-doctrine-2017: "Incident : An
#: occurrence").
SPACE_BEFORE_PUNCT = re.compile(r"\s+([:;,.)])")

EXACT = "exact"
RENDERING = "rendering"


def norm(s: str) -> str:
    """Whitespace- and quote-normalised text: the `exact` tier."""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("’", "'").replace("‘", "'")
    s = s.replace("“", '"').replace("”", '"')
    return " ".join(s.split())


def rendering_norm(s: str) -> str:
    """`norm`, then the parse's rendering differences removed: list enumerators,
    whitespace before punctuation, and double quotation marks (the parse prints
    'initial isolation distance' where the page printed “initial isolation
    distance”)."""
    s = norm(s)
    s = LIST_MARKER.sub("", s)
    s = SPACE_BEFORE_PUNCT.sub(r"\1", s)
    s = s.replace('"', "'")
    return " ".join(s.split())


def quote_tier(quote: str, text: str) -> str | None:
    """The first tier under which `quote` is in `text`, or None."""
    if norm(quote) in norm(text):
        return EXACT
    if rendering_norm(quote) in rendering_norm(text):
        return RENDERING
    return None
