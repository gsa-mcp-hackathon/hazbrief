"""Deterministic checker for the commander stylebook (HB-02 deliverable 4).

The eval harness (HB-05) calls `check(text)` on every brief the server drafts. There is
no model: each finding is a pattern match against `docs/stylebook/STYLECHECK.yaml`
(thresholds, units, word lists) and `docs/stylebook/VOCABULARY.yaml` (forbidden
synonyms, never-written terms), and carries the id of the stylebook rule it breaches. It
returns findings, never a score; what a finding costs is the harness's decision, not the
checker's.

Reading conventions the checker relies on, each stated in the stylebook:
  - one sentence per line or bullet (SB-SEN-01); Markdown headings and HTML comments are
    skipped;
  - a source tag in square brackets at the end of the sentence (SB-NUM-04); numbers
    inside a tag are citations and are not checked for units;
  - a unit, or the noun that names what is counted, directly after each number
    (SB-NUM-01).
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import yaml

from hazbrief.stylebook_files import STYLECHECK_CONFIG, VOCABULARY, read_shipped

# The stylebook rules this module enforces, in the order findings are reported within a
# sentence. Every other rule is `Check: review` in the stylebook
# (test_stylebook.py keeps the two lists equal).
RULES: dict[str, str] = {
    "SB-SEN-01": "sentence longer than the limit",
    "SB-TRM-02": "forbidden synonym",
    "SB-NEV-01": "dispersion language",
    "SB-NUM-01": "number without a unit",
    "SB-NUM-02": "estimate without its margin of error",
    "SB-NUM-03": "live value without an as-of date",
    "SB-NUM-04": "number without a source tag",
    "SB-NUM-06": "clock time without a time zone",
    "SB-NEV-03": "confidence word without a source",
    "SB-NEV-04": "contact detail",
    "SB-STR-07": "public alert over its length limit",
}

_STYLECHECK_KEYS = (
    "max_sentence_words",
    "source_tag_open",
    "source_tag_close",
    "as_of_marker",
    "margin_of_error_marker",
    "margin_of_error_sources",
    "live_value_terms",
    "units",
    "counted_nouns",
    "identifier_prefixes",
    "identifier_list_prefixes",
    "time_zones",
    "confidence_words",
    "contact_patterns",
    "public_alert_limits",
)

# Lines that are structure, not prose.
_HEADING = re.compile(r"^\s*#")
_COMMENT = re.compile(r"^\s*<!--.*-->\s*$")
_LIST_MARK = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
# A dotted abbreviation ("U.S.", "e.g.") ends in a full stop that does not end the
# sentence.
_DOTTED_ABBREVIATION = re.compile(r"(?:^|\s)(?:[A-Za-z]\.){2,}$")
# Clock times and dates are not quantities (SB-NUM-06 checks times separately).
_TIME = re.compile(r"(?<![\d:])(\d{1,2}):(\d{2})(?![\d:])")
_DATE = re.compile(r"(?<![\d/])\d{1,2}/(?:\d{1,2}/)?\d{4}(?![\d/])")
# A number: a fraction as the ERG prints one ("1/2 mile"), digits with thousands commas
# or a decimal part, and the ERG's "+" ("11.0+"). A digit run glued to a letter, hyphen,
# slash or colon on its left is an identifier (UN1017, I-81).
_NUMBER = re.compile(
    r"(?<![\w.,/:\-])(?:\d+/\d+|\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\+?(?![\d,]*\d)"
)
_RANGE_TAIL = re.compile(r"^\s?[-–]\s?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\+?")
_GLUED_LETTER = re.compile(r"^[A-Za-z]")
_DOTTED = re.compile(r"\d+\.\d+")
# Private-use marks that stand in for a source tag while a line is split into sentences,
# so a full stop inside a tag ("U.S. Geological Survey") never ends a sentence.
_MARK_OPEN, _MARK_CLOSE = chr(0xE000), chr(0xE001)
_MASK = re.compile(f"{_MARK_OPEN}(\\d+){_MARK_CLOSE}")


@dataclass(frozen=True)
class Finding:
    """One breach: the stylebook rule, the 1-based sentence, the text, and why."""

    rule: str
    sentence: int
    excerpt: str
    message: str


# A pattern that matches nothing: an empty word list must never compile to one that
# matches everywhere.
_NOTHING = re.compile(r"(?!)")
# An abbreviation ("PIH", "PADs") is matched in its own case, so "pad" and "par" stay
# plain words.
_ABBREVIATION = re.compile(r"^[A-Z]{2,}s?$")


def _phrases(words, flags=re.I) -> re.Pattern:
    """Whole-word, whole-phrase alternation; longest first, so a phrase wins."""
    alts = sorted({w.strip() for w in words if w.strip()}, key=len, reverse=True)
    if not alts:
        return _NOTHING
    body = "|".join(r"\s+".join(map(re.escape, w.split())) for w in alts)
    return re.compile(rf"(?<![\w-])(?:{body})(?![\w-])", flags)


def _require(data: dict, key: str, path: Path):
    if key not in data:
        raise KeyError(f"{path}: required key {key!r} is missing")
    return data[key]


@dataclass(frozen=True)
class StyleConfig:
    """The checker's parameters, loaded from STYLECHECK.yaml and VOCABULARY.yaml."""

    max_sentence_words: int
    tag_open: str
    tag_close: str
    as_of_marker: str
    margin_of_error_marker: str
    margin_of_error_sources: tuple[str, ...]
    live_value_terms: tuple[str, ...]
    units: tuple[str, ...]
    identifier_prefixes: tuple[str, ...]
    identifier_list_prefixes: tuple[str, ...]
    time_zones: tuple[str, ...]
    confidence_words: tuple[str, ...]
    contact_patterns: tuple[tuple[str, str], ...]
    public_alert_limits: dict[str, int]
    # (synonym, the vocabulary term to write instead)
    forbidden: tuple[tuple[str, str], ...]
    # (term, rule id)
    never_written: tuple[tuple[str, str], ...]

    @cached_property
    def tag_re(self) -> re.Pattern:
        o, c = re.escape(self.tag_open), re.escape(self.tag_close)
        return re.compile(rf"{o}[^{o}{c}]*{c}")

    @cached_property
    def unit_re(self) -> re.Pattern:
        alts = sorted(set(self.units), key=len, reverse=True)
        return re.compile(
            rf"^\s?(?:{'|'.join(map(re.escape, alts))})(?![A-Za-z0-9])", re.I
        )

    @cached_property
    def prefix_re(self) -> re.Pattern:
        alts = sorted(set(self.identifier_prefixes), key=len, reverse=True)
        body = "|".join(r"\s+".join(map(re.escape, p.split())) for p in alts)
        return re.compile(rf"(?:^|[^\w])(?:{body})\s*$", re.I)

    @cached_property
    def list_prefix_re(self) -> re.Pattern:
        """A dotted identifier list still open before a number: "Division 1.1, 1.2,
        1.3 or " (HB-17)."""
        alts = sorted(set(self.identifier_list_prefixes), key=len, reverse=True)
        body = "|".join(map(re.escape, alts))
        item, sep = r"\d+\.\d+", r"(?:,\s*|,?\s+(?:or|and)\s+)"
        return re.compile(
            rf"(?:^|[^\w])(?:{body})\s+{item}(?:{sep}{item})*{sep}$", re.I
        )

    @cached_property
    def zone_re(self) -> re.Pattern:
        return re.compile(rf"^\s*(?:{'|'.join(map(re.escape, self.time_zones))})\b")

    @cached_property
    def live_re(self) -> re.Pattern:
        return _phrases(self.live_value_terms)

    @cached_property
    def moe_source_re(self) -> re.Pattern:
        return _phrases(self.margin_of_error_sources, flags=0)

    @cached_property
    def confidence_re(self) -> re.Pattern:
        return _phrases(self.confidence_words)

    @cached_property
    def contact_res(self) -> tuple[re.Pattern, ...]:
        return tuple(re.compile(p) for _, p in self.contact_patterns)

    @cached_property
    def forbidden_res(self) -> tuple[re.Pattern, re.Pattern]:
        abbreviations = [s for s, _ in self.forbidden if _ABBREVIATION.match(s)]
        words = [s for s, _ in self.forbidden if not _ABBREVIATION.match(s)]
        return _phrases(words), _phrases(abbreviations, flags=0)

    @cached_property
    def forbidden_term(self) -> dict[str, str]:
        return {" ".join(s.lower().split()): t for s, t in self.forbidden}

    @cached_property
    def never_re(self) -> re.Pattern:
        return _phrases(t for t, _ in self.never_written)

    @cached_property
    def never_rule(self) -> dict[str, str]:
        return {" ".join(t.lower().split()): r for t, r in self.never_written}


def load_config(
    stylecheck_path: Path = STYLECHECK_CONFIG, vocabulary_path: Path = VOCABULARY
) -> StyleConfig:
    """Read both files; a missing key is a KeyError naming the file and the key."""
    sc = yaml.safe_load(read_shipped(stylecheck_path))
    vocab = yaml.safe_load(read_shipped(vocabulary_path))
    for key in _STYLECHECK_KEYS:
        _require(sc, key, stylecheck_path)
    limit = sc["max_sentence_words"]
    if not isinstance(limit, int) or limit < 1:
        raise ValueError(
            f"{stylecheck_path}: max_sentence_words must be a positive integer"
        )
    # An empty list would compile to a pattern that matches every position (a unit after
    # every number, a time zone after every time), silently passing what it should
    # check.
    for key in (
        "units",
        "counted_nouns",
        "identifier_prefixes",
        "identifier_list_prefixes",
        "time_zones",
    ):
        if not isinstance(sc[key], list) or not sc[key]:
            raise ValueError(f"{stylecheck_path}: {key} must be a non-empty list")
    forbidden = tuple(
        (syn, t["term"])
        for t in _require(vocab, "terms", vocabulary_path)
        for syn in _require(t, "forbidden_synonyms", vocabulary_path)
    )
    never = tuple(
        (e["term"], e["rule"])
        for e in _require(vocab, "never_written", vocabulary_path)
    )
    return StyleConfig(
        max_sentence_words=limit,
        tag_open=sc["source_tag_open"],
        tag_close=sc["source_tag_close"],
        as_of_marker=sc["as_of_marker"].lower(),
        margin_of_error_marker=sc["margin_of_error_marker"].lower(),
        margin_of_error_sources=tuple(sc["margin_of_error_sources"]),
        live_value_terms=tuple(sc["live_value_terms"]),
        units=tuple(sc["units"]) + tuple(sc["counted_nouns"]),
        identifier_prefixes=tuple(sc["identifier_prefixes"]),
        identifier_list_prefixes=tuple(sc["identifier_list_prefixes"]),
        time_zones=tuple(sc["time_zones"]),
        confidence_words=tuple(sc["confidence_words"]),
        contact_patterns=tuple(sc["contact_patterns"].items()),
        public_alert_limits={k: int(v) for k, v in sc["public_alert_limits"].items()},
        forbidden=forbidden,
        never_written=never,
    )


@functools.lru_cache(maxsize=1)
def _default_config() -> StyleConfig:
    return load_config()


def sentences(text: str, config: StyleConfig | None = None) -> list[str]:
    """Prose sentences: each line end ends one, and so does ". " outside a tag."""
    cfg = config or _default_config()
    out: list[str] = []
    for line in text.splitlines():
        if not line.strip() or _HEADING.match(line) or _COMMENT.match(line):
            continue
        line = _LIST_MARK.sub("", line, count=1)
        tags = cfg.tag_re.findall(line)
        masked = cfg.tag_re.sub(
            lambda _m, n=iter(range(len(tags))): f"{_MARK_OPEN}{next(n)}{_MARK_CLOSE}",
            line,
        )
        for part in _split(masked):
            part = _MASK.sub(lambda m: tags[int(m.group(1))], part).strip()
            if part:
                out.append(part)
    return out


def _split(line: str) -> list[str]:
    """Split at sentence-ending punctuation, but not after a dotted abbreviation."""
    parts, start = [], 0
    for m in _SENTENCE_END.finditer(line):
        if _DOTTED_ABBREVIATION.search(line[start : m.start()]):
            continue
        parts.append(line[start : m.start()])
        start = m.end()
    parts.append(line[start:])
    return parts


def _quantities(body: str, cfg: StyleConfig) -> list[tuple[str, bool]]:
    """Each quantity in a sentence body, and whether a unit follows it."""
    for pattern in cfg.contact_res:
        body = pattern.sub(" ", body)
    body = _TIME.sub(" ", _DATE.sub(" ", body))
    found = []
    for m in _NUMBER.finditer(body):
        rest = body[m.end() :]
        tail = _RANGE_TAIL.match(rest)
        if tail:
            rest = rest[tail.end() :]
        before = body[: m.start()]
        if _GLUED_LETTER.match(rest) or cfg.prefix_re.search(before):
            continue  # an identifier ("3D", "Guide 124"), not a quantity
        if _DOTTED.fullmatch(m.group(0)) and cfg.list_prefix_re.search(before):
            continue  # a division in a list ("Division 1.1, 1.2 or 1.5")
        found.append((m.group(0), bool(cfg.unit_re.match(rest))))
    return found


def _check_sentence(n: int, s: str, cfg: StyleConfig) -> list[Finding]:
    tags = cfg.tag_re.findall(s)
    body = cfg.tag_re.sub(" ", s)
    found: list[Finding] = []

    words = [w for w in body.split() if any(ch.isalnum() for ch in w)]
    if len(words) > cfg.max_sentence_words:
        found.append(
            Finding(
                "SB-SEN-01",
                n,
                " ".join(words[:8]) + " ...",
                f"{len(words)} words; the limit is {cfg.max_sentence_words}",
            )
        )
    for pattern in cfg.forbidden_res:
        for m in pattern.finditer(body):
            term = cfg.forbidden_term[" ".join(m.group(0).lower().split())]
            found.append(
                Finding(
                    "SB-TRM-02", n, m.group(0), f"forbidden synonym; write {term!r}"
                )
            )
    for m in cfg.never_re.finditer(s):
        rule = cfg.never_rule[" ".join(m.group(0).lower().split())]
        found.append(
            Finding(
                rule, n, m.group(0), "never written: the server models no dispersion"
            )
        )

    quantities = _quantities(body, cfg)
    for number, has_unit in quantities:
        if not has_unit:
            found.append(
                Finding("SB-NUM-01", n, number, "no unit or counted noun after it")
            )
    if quantities:
        if tags and cfg.moe_source_re.search(" ".join(tags)):
            if cfg.margin_of_error_marker not in body.lower():
                found.append(
                    Finding(
                        "SB-NUM-02", n, tags[-1], "the source carries a margin of error"
                    )
                )
        if cfg.live_re.search(body) and not any(
            cfg.as_of_marker in t.lower() for t in tags
        ):
            found.append(
                Finding(
                    "SB-NUM-03", n, s, "a live value needs an as-of date in its tag"
                )
            )
        if not tags:
            found.append(Finding("SB-NUM-04", n, s, "a number needs a source tag"))
    for m in _TIME.finditer(s):
        if not cfg.zone_re.match(s[m.end() :]):
            found.append(
                Finding("SB-NUM-06", n, m.group(0), "a clock time needs its time zone")
            )
    if not tags:
        for m in cfg.confidence_re.finditer(body):
            found.append(
                Finding("SB-NEV-03", n, m.group(0), "confidence word with no source")
            )
    for pattern in cfg.contact_res:
        for m in pattern.finditer(s):
            found.append(
                Finding("SB-NEV-04", n, m.group(0), "contact details are never written")
            )

    order = list(RULES)
    return sorted(found, key=lambda f: order.index(f.rule))


def check(text: str, config: StyleConfig | None = None) -> list[Finding]:
    """Every breach of a `Check: stylecheck` rule, in sentence order; empty is clean."""
    cfg = config or _default_config()
    out: list[Finding] = []
    for n, s in enumerate(sentences(text, cfg), start=1):
        out.extend(_check_sentence(n, s, cfg))
    return out


def check_public_alert(
    text: str, limit: str = "wea_long", config: StyleConfig | None = None
) -> list[Finding]:
    """SB-STR-07: a public alert within the named Wireless Emergency Alert length."""
    cfg = config or _default_config()
    if limit not in cfg.public_alert_limits:
        configured = sorted(cfg.public_alert_limits)
        raise KeyError(
            f"unknown public alert limit {limit!r}; configured: {configured}"
        )
    n = cfg.public_alert_limits[limit]
    if len(text) <= n:
        return []
    return [
        Finding("SB-STR-07", 1, text[n:], f"{len(text)} characters; {limit} allows {n}")
    ]
