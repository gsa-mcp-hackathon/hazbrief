"""The load read, a standing render step (HB-132R Part A; HB-115 ADDENDUM-01 section 3;
DN-022 sections 6 and 7).

HB-115 read five served briefs once, by hand, against four rules and cut what could be
cut. This module runs the same four rules on every brief, at the one point both the
static page and the live page read: `render.page_parts`. A section's fragment is read
before it is streamed (`section_settled`) and before the static page is assembled from
it, so the two carry the same text (DN-022 section 3: the final page hashes to the
static render).

**The rules** are `load_read_rules.yaml`, HB-115's rule set with its thresholds and
patterns unchanged:

- R1, a duplicated sentence; R3, a label that restates its value; R4, three receipts
  where one carries the fact. Lexical, deterministic.
- R2, a sentence about the sentence before it. HB-115's lexical screen finds the
  candidate; the model decides it (`Judge`), one recorded call per candidate pair
  through HB-131R's route (`model_author.ModelAuthor`: its transcript format, its key,
  its fsync-before-use and its resume). A replay reads the transcript and makes no call.

Each rule yields a candidate with the sentence, the rule and the reason.

**What is cut.** A candidate is cut only when (1) its rule cuts (R1 within one section,
R2 when the model says so; R3 and R4 never, `load_read_rules.yaml` says why); (2) it is
in none of the protected places (the ICS 201's text, a modelled layer's label, a
sentence another task's test pins: HB-115 RULES.md's three classes); (3) the sentence
can be removed from one text run of the fragment's HTML; and (4) the section's numbers
and receipts are the same sets after the cut as before it. Numbers are read by
`model_author.numbers`, HB-131R's normalisation, so the two checks agree on what a
number is. HB-131R's number check is global, over the brief's whole record set; this
one is per section, over the section's own text. Every other candidate is proposed:
kept in the text, and listed with why it was not cut, for an Issue.

**What it reports** (`Read.report`): the rules file's sha256, the cuts applied and the
cuts proposed, the candidates per rule, the words per section before and after, and the
calls made. The brief's appendix prints the words and the hash (`cli.write_outputs`).

The application's code, not the server's: the container image ships without
`src/hazbrief/brief/` (`.dockerignore`).
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from functools import cache
from html.parser import HTMLParser
from pathlib import Path

import yaml

from hazbrief.brief import model_author
from hazbrief.config import REPO_ROOT

RULES_FILE = Path(__file__).with_name("load_read_rules.yaml")


# ── the rule file ─────────────────────────────────────────────────────────────────────


@cache
def _raw_rules() -> dict:
    r = yaml.safe_load(RULES_FILE.read_text(encoding="utf-8"))
    for key in (
        "min_words",
        "rules",
        "receipt_pattern",
        "block_tags",
        "skip_tags",
        "protected",
    ):
        if key not in r:
            raise RuntimeError(f"{RULES_FILE} is missing {key!r}")
    if set(r["rules"]) != {"R1", "R2", "R3", "R4"}:
        raise RuntimeError(f"{RULES_FILE}: the rules are R1 to R4, HB-115's four")
    cuts = {
        "R1": {"later_in_same_section"},
        "R2": {"the_sentence"},
        "R3": {"never"},
        "R4": {"never"},
    }
    for rid, allowed in cuts.items():
        if r["rules"][rid].get("cut") not in allowed:
            raise RuntimeError(
                f"{RULES_FILE}: {rid}.cut is one of {sorted(allowed)}, "
                f"not {r['rules'][rid].get('cut')!r}"
            )
    return r


def rules() -> dict:
    """A fresh copy of the rule file, checked."""
    return copy.deepcopy(_raw_rules())


@cache
def rules_sha256() -> str:
    """The rule file's sha256, which the brief's appendix prints."""
    return hashlib.sha256(RULES_FILE.read_bytes()).hexdigest()


# ── reading a fragment (HB-115's tool, per section) ──────────────────────────────────


def sentences(text: str) -> list[str]:
    """HB-115's sentence split: after . ! or ? and before a capital, a quote or a
    bracket."""
    return [
        s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z\"(])", text) if s.strip()
    ]


def fold(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def words(s: str) -> int:
    """HB-115's word count."""
    return len(re.findall(r"[A-Za-z0-9][\w'.,/-]*", s))


@dataclass
class Block:
    """A list item, a cell, a paragraph: its visible text, its tag, and why it may not
    be cut (an ancestor's protected class or id), or None."""

    tag: str
    text: str
    protected: str | None
    #: the headings read before it in its fragment: blocks with the same scope sit
    #: under the same heading
    scope: int = 0


class _Blocks(HTMLParser):
    """HB-115's `_Text`, for one fragment: its visible text in blocks, its two-cell
    table rows, and each block's protection (`protected.classes` and `protected.ids`
    of an enclosing element)."""

    def __init__(self, r: dict):
        super().__init__(convert_charrefs=True)
        self.r = r
        self.block_tags = set(r["block_tags"])
        self.skip_tags = set(r["skip_tags"])
        self.skip = 0
        self.blocks: list[Block] = []
        self.rows: list[list[tuple[str, str]]] = []
        self.buf: list[str] = []
        self.tags: list[str] = []
        self.row: list[tuple[str, str]] = []
        #: the open elements, each with the protection it opened (or None)
        self.open: list[tuple[str, str | None]] = []
        #: the protection the last heading opened (`protected.headings`), which holds
        #: until the next heading
        self.heading: str | None = None
        self.scope = 0
        self.headings = [
            (re.compile(pat), why)
            for pat, why in (r["protected"].get("headings") or {}).items()
        ]

    def _protection(self) -> str | None:
        for _, why in reversed(self.open):
            if why:
                return why
        return self.heading

    def _flush(self) -> None:
        text = re.sub(r"\s+", " ", "".join(self.buf)).strip()
        self.buf = []
        if text:
            tag = self.tags[-1] if self.tags else "?"
            if tag in _HEADINGS:
                self.scope += 1
                self.heading = next(
                    (why for pat, why in self.headings if pat.search(text)), None
                )
            self.blocks.append(Block(tag, text, self._protection(), self.scope))
            if tag in ("th", "td"):
                self.row.append((tag, text))

    def handle_starttag(self, tag, attrs):
        if tag in self.skip_tags:
            self.skip += 1
            return
        if self.skip:
            return
        a = dict(attrs)
        prot = self.r["protected"]
        why = None
        for c in (a.get("class") or "").split():
            why = why or (prot.get("classes") or {}).get(c)
        why = why or (prot.get("ids") or {}).get(a.get("id") or "")
        if tag not in _VOID:
            self.open.append((tag, why))
        if tag in self.block_tags:
            self._flush()
            self.tags.append(tag)
        if tag == "tr":
            self.row = []

    def handle_endtag(self, tag):
        if tag in self.skip_tags:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag in self.block_tags:
            self._flush()
            if self.tags:
                self.tags.pop()
        if tag == "tr" and self.row:
            self.rows.append(self.row)
            self.row = []
        # close the innermost open element of this tag (HTML's own forgiveness: an
        # unclosed inline element does not keep its protection past its parent)
        for i in range(len(self.open) - 1, -1, -1):
            if self.open[i][0] == tag:
                del self.open[i:]
                break

    def handle_data(self, data):
        if not self.skip:
            self.buf.append(data)


#: the tags that open a heading's scope (`protected.headings`)
_HEADINGS = {"h1", "h2", "h3", "h4"}
#: elements with no end tag, which never enclose text
_VOID = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "source",
    "track",
    "wbr",
}


@dataclass
class Parsed:
    blocks: list[Block]
    rows: list[list[tuple[str, str]]]

    def words(self) -> int:
        return sum(words(b.text) for b in self.blocks)


def parse(fragment: str, r: dict | None = None) -> Parsed:
    p = _Blocks(r or _raw_rules())
    p.feed(fragment)
    p.close()
    p._flush()
    return Parsed(p.blocks, p.rows)


def receipts(text: str, r: dict | None = None) -> set[str]:
    """Every receipt in `text` (HB-115's RECEIPT pattern), as a set."""
    pat = re.compile((r or _raw_rules())["receipt_pattern"])
    return set(pat.findall(text))


def held(fragment: str, r: dict | None = None) -> tuple[set[str], set[str]]:
    """A section's numbers (`model_author.numbers`) and receipts, over its visible
    text: what a cut may not change."""
    text = model_author.visible_text(fragment)
    return model_author.numbers(text), receipts(text, r)


# ── cutting one sentence out of a fragment's HTML ─────────────────────────────────────

_TOKEN = re.compile(r"(<!--.*?-->|<[^>]*>)", re.S)
_ESCAPED = {
    "&": "(?:&amp;|&)",
    "<": "&lt;",
    ">": "&gt;",
    '"': '(?:"|&quot;|&#34;)',
    "'": "(?:'|&#x27;|&#39;)",
}


def _sentence_pattern(sentence: str) -> re.Pattern:
    """The sentence as it may stand in one text run of the HTML: its characters as
    `render.esc` escapes them, any whitespace between words, case ignored (R1 folds
    case)."""
    out = []
    for ch in sentence:
        if ch.isspace():
            if not out or out[-1] != r"\s+":
                out.append(r"\s+")
        else:
            out.append(_ESCAPED.get(ch, re.escape(ch)))
    return re.compile("".join(out), re.I)


def cut_last(fragment: str, sentence: str, skip_tags: set[str]) -> str | None:
    """`fragment` with the last printing of `sentence` removed, or None when no text
    run holds it whole (it spans markup, such as a `<code>` inside it). An element the
    cut leaves empty is removed with it."""
    tokens = _TOKEN.split(fragment)
    pat = _sentence_pattern(sentence)
    depth = 0
    found: tuple[int, re.Match] | None = None
    for i, tok in enumerate(tokens):
        if i % 2:  # a tag
            m = re.match(r"<\s*(/?)\s*([a-zA-Z0-9]+)", tok)
            if m and m.group(2).lower() in skip_tags:
                depth += -1 if m.group(1) else 1
                depth = max(depth, 0)
            continue
        if depth:
            continue
        for m in pat.finditer(tok):
            # a whole sentence: not the tail of a longer word, and not followed by one
            before = tok[: m.start()]
            after = tok[m.end() :]
            if before and not before[-1].isspace():
                continue
            if after and not after[0].isspace():
                continue
            found = (i, m)
    if found is None:
        return None
    i, m = found
    tok = tokens[i]
    head, tail = tok[: m.start()], tok[m.end() :]
    # the space the sentence was set off by goes with it
    if tail[:1].isspace():
        tail = tail.lstrip()
        if head and tail:
            tail = " " + tail
    else:
        head = head.rstrip()
    tokens[i] = head + tail
    if not tokens[i].strip() and 0 < i < len(tokens) - 1:
        opening, closing = tokens[i - 1], tokens[i + 1]
        mo = re.match(r"<\s*([a-zA-Z0-9]+)[\s>]", opening)
        mc = re.match(r"<\s*/\s*([a-zA-Z0-9]+)\s*>", closing)
        if mo and mc and mo.group(1).lower() == mc.group(1).lower():
            tokens[i - 1] = tokens[i] = tokens[i + 1] = ""
    return "".join(tokens)


def remove_last_text(text: str, sentence: str) -> str:
    """The same cut over plain text (a narrative event's Markdown)."""
    pat = _sentence_pattern(sentence)
    last = None
    for m in pat.finditer(text):
        last = m
    if last is None:
        return text
    head, tail = text[: last.start()], text[last.end() :]
    return (head.rstrip() + (" " + tail.lstrip() if tail.strip() else "")).rstrip() + (
        "\n" if text.endswith("\n") else ""
    )


# ── R2's reader: the model ───────────────────────────────────────────────────────────


class Judge:
    """R2's decision: is `sentence` about the sentence before it? One call of the
    brief's model route per candidate pair (`entry` `load_read`), recorded; a replay
    reads the transcript and calls nothing. A pair the route cannot answer (no record
    in a replay, the route unavailable, a reply not in the asked shape) is not judged,
    and the read says why: the sentence stays."""

    def __init__(self, author: model_author.ModelAuthor | None):
        self.author = author

    @property
    def calls_made(self) -> int:
        return self.author.calls_made if self.author is not None else 0

    def __call__(self, before: str, sentence: str) -> dict:
        if self.author is None:
            return {"judged": False, "why": "no model route is configured"}
        payload = {"rule": "R2", "before": before, "sentence": sentence}
        try:
            rec = self.author.call("load_read", payload)
        except model_author.ModelRouteError as exc:
            return {"judged": False, "why": str(exc)}
        if not rec["ok"]:
            return {
                "judged": False,
                "why": f"the call failed: {rec['error']}",
                "transcript": rec["key"],
            }
        try:
            obj = model_author.parse_answer(rec["result"])
        except model_author.Refusal as r:
            return {"judged": False, "why": r.detail, "transcript": rec["key"]}
        about, why = obj.get("about_previous"), obj.get("reason")
        if not isinstance(about, bool) or not isinstance(why, str) or not why.strip():
            return {
                "judged": False,
                "why": "the reply is not {about_previous: boolean, reason: text}",
                "transcript": rec["key"],
            }
        return {
            "judged": True,
            "about_previous": about,
            "reason": why.strip(),
            "transcript": rec["key"],
        }


def judge_from_config(cfg: dict, *, replay: bool) -> Judge:
    """R2's judge on the route `orchestrator.yaml` `load_read` names: HB-131R's
    `ModelAuthor` with this read's own prompt file, run name and transcripts."""
    lr = cfg["load_read"]
    mcfg = {
        **cfg,
        "model": {
            **cfg["model"],
            "prompt": lr["prompt"],
            "hold_run": lr["hold_run"],
        },
    }
    return Judge(
        model_author.ModelAuthor(
            mcfg, transcripts=REPO_ROOT / lr["transcripts_dir"], replay=replay
        )
    )


# ── the read ─────────────────────────────────────────────────────────────────────────


@dataclass
class Read:
    """One read of a brief's sections: the cut fragments and the report."""

    parts: dict[str, str]
    report: dict


@dataclass
class Reader:
    """The standing read over a brief's fragments (`apply`). Parsing a fragment and
    cutting it are pure functions of the fragment, so both are kept by its sha256: the
    orchestrator draws the page at every settle, and an unchanged section is not read
    twice. R2's verdicts are kept by pair, so a candidate is asked once per brief."""

    judge: Judge = field(default_factory=lambda: Judge(None))
    r: dict = field(default_factory=rules)
    _parsed: dict[str, Parsed] = field(default_factory=dict, repr=False)
    _cut: dict[tuple[str, str], tuple[str, list[dict]]] = field(
        default_factory=dict, repr=False
    )
    _verdicts: dict[tuple[str, str], dict] = field(default_factory=dict, repr=False)

    def _parse(self, fragment: str) -> Parsed:
        k = hashlib.sha256(fragment.encode("utf-8")).hexdigest()
        if k not in self._parsed:
            self._parsed[k] = parse(fragment, self.r)
        return self._parsed[k]

    def _verdict(self, before: str, sentence: str) -> dict:
        key = (before, sentence)
        if key not in self._verdicts:
            self._verdicts[key] = self.judge(before, sentence)
        return self._verdicts[key]

    def _protected(self, section: str, block: Block | None, sentence: str):
        prot = self.r["protected"]
        why = (prot.get("sections") or {}).get(section)
        if why is None and block is not None:
            why = block.protected
        if why is None:
            for pin in prot.get("pinned") or []:
                if re.search(pin["pattern"], sentence, re.I):
                    why = pin["why"]
                    break
        return why

    def candidates(self, parts: dict[str, str]) -> list[dict]:
        """Every candidate of the four rules over the sections, in render order, with
        where it stands. R1 is counted page-wide, as HB-115 counted it."""
        r = self.r
        min_words = int(r["min_words"])
        screen = re.compile(r["rules"]["R2"]["screen"], re.I)
        label = re.compile(r["rules"]["R3"]["label_pattern"])
        min_receipts = int(r["rules"]["R4"]["min_receipts"])
        seen: dict[str, list[tuple[str, Block, str]]] = defaultdict(list)
        out: list[dict] = []
        for name, frag in parts.items():
            p = self._parse(frag)
            for b in p.blocks:
                ss = sentences(b.text)
                for i, s in enumerate(ss):
                    if words(s) >= min_words:
                        seen[fold(s)].append((name, b, s))
                    if i and screen.search(s):
                        out.append(
                            {
                                "rule": "R2",
                                "section": name,
                                "block": b,
                                "before": ss[i - 1],
                                "sentence": s,
                            }
                        )
                m = label.match(b.text)
                if m and fold(m.group(2)).startswith(fold(m.group(1))):
                    out.append(
                        {
                            "rule": "R3",
                            "section": name,
                            "block": b,
                            "sentence": b.text,
                            "reason": f"the value restates its label {m.group(1)!r}",
                        }
                    )
                n = len(re.findall(r["receipt_pattern"], b.text))
                if n >= min_receipts:
                    out.append(
                        {
                            "rule": "R4",
                            "section": name,
                            "block": b,
                            "sentence": b.text,
                            "reason": f"{n} receipts in one {b.tag}",
                        }
                    )
            for row in p.rows:
                if len(row) == 2 and row[0][0] == "th" and row[1][0] == "td":
                    lab, val = fold(row[0][1]), fold(row[1][1])
                    if lab and (val.startswith(lab) or val == lab):
                        out.append(
                            {
                                "rule": "R3",
                                "section": name,
                                "block": None,
                                "sentence": f"{row[0][1]}: {row[1][1]}",
                                "reason": f"the value restates its label {row[0][1]!r}",
                            }
                        )
        for key, where in seen.items():
            if len(where) < 2:
                continue
            by_section: dict[str, list[tuple[Block, str]]] = defaultdict(list)
            for name, b, s in where:
                by_section[name].append((b, s))
            names = list(by_section)
            for j, name in enumerate(names):
                occ = by_section[name]
                scopes = {b.scope for b, _ in occ}
                if len(occ) > 1 and len(scopes) > 1:
                    # under two headings, each printing is that heading's own
                    # statement (the guide's FIRE and SPILL lines; a panel's "Not
                    # derived" under each of its headings): proposed, never cut
                    out.append(
                        {
                            "rule": "R1",
                            "section": name,
                            "block": occ[-1][0],
                            "sentence": occ[-1][1],
                            "reason": f"printed {len(occ)} times in this section, "
                            f"under {len(scopes)} headings",
                            "headings": True,
                        }
                    )
                elif len(occ) > 1:
                    out.append(
                        {
                            "rule": "R1",
                            "section": name,
                            "block": occ[-1][0],
                            "blocks": [b for b, _ in occ[1:]],
                            "sentence": occ[-1][1],
                            "reason": f"printed {len(occ)} times in this section",
                            "within": len(occ) - 1,
                        }
                    )
                if j:
                    out.append(
                        {
                            "rule": "R1",
                            "section": name,
                            "block": occ[0][0],
                            "sentence": occ[0][1],
                            "reason": "printed again here after the "
                            + ", ".join(names[:j])
                            + " section"
                            + ("s" if j > 1 else ""),
                            "across": True,
                        }
                    )
        return out

    def apply(self, parts: dict[str, str]) -> Read:
        """The cut fragments and the report. A candidate is cut only under the four
        conditions of the module's docstring; every other is proposed."""
        r = self.r
        skip = set(r["skip_tags"])
        before_calls = self.judge.calls_made
        cands = self.candidates(parts)
        counts = {k: 0 for k in ("R1", "R2", "R3", "R4")}
        # R1's count is HB-115's: distinct sentences printed more than once on the page
        r1_sentences = {fold(c["sentence"]) for c in cands if c["rule"] == "R1"}
        counts["R1"] = len(r1_sentences)
        for c in cands:
            if c["rule"] != "R1":
                counts[c["rule"]] += 1
        applied: list[dict] = []
        proposed: list[dict] = []
        judged: list[dict] = []
        wanted: dict[str, list[dict]] = defaultdict(list)
        for c in cands:
            row = {
                "rule": c["rule"],
                "section": c["section"],
                "sentence": c["sentence"],
            }
            rule = r["rules"][c["rule"]]
            if c["rule"] == "R2":
                v = self._verdict(c["before"], c["sentence"])
                row["before"] = c["before"]
                if not v["judged"]:
                    proposed.append(
                        {
                            **row,
                            "reason": "screened as a sentence about the one before it",
                            "why_not": f"not judged: {v['why']}",
                        }
                    )
                    continue
                judged.append({**row, **{k: v[k] for k in v if k != "judged"}})
                if not v["about_previous"]:
                    continue
                row["reason"] = v["reason"]
            else:
                row["reason"] = c["reason"]
            if rule["cut"] == "never":
                proposed.append({**row, "why_not": f"{c['rule']} proposes, never cuts"})
                continue
            section_why = (r["protected"].get("sections") or {}).get(c["section"])
            if section_why:
                proposed.append({**row, "why_not": f"protected: {section_why}"})
                continue
            if c.get("headings"):
                proposed.append(
                    {
                        **row,
                        "why_not": "printed under different headings: each printing is "
                        "its own heading's statement, and a cut leaves a heading "
                        "without it",
                    }
                )
                continue
            if c.get("across"):
                proposed.append(
                    {
                        **row,
                        "why_not": "a duplicate across sections: each section is read "
                        "alone, so its copy is the only one its reader has",
                    }
                )
                continue
            blocks = c.get("blocks") or [c["block"]]
            prose = set(rule.get("prose_tags") or [])
            if prose and any(b is None or b.tag not in prose for b in blocks):
                proposed.append(
                    {
                        **row,
                        "why_not": "not prose: a table cell, caption, heading or "
                        "summary is a data row or a name (HB-115 L-09)",
                    }
                )
                continue
            why = next(
                (
                    w
                    for w in (
                        self._protected(c["section"], b, c["sentence"]) for b in blocks
                    )
                    if w
                ),
                None,
            )
            if why:
                proposed.append({**row, "why_not": f"protected: {why}"})
                continue
            wanted[c["section"]].append({**row, "times": c.get("within", 1)})
        out = dict(parts)
        for name, cuts in wanted.items():
            frag, done, refused = self._cut_section(name, parts[name], cuts, skip)
            out[name] = frag
            applied += done
            proposed += refused
        report = {
            "rules_sha256": rules_sha256(),
            "candidates": counts,
            "applied": applied,
            "proposed": proposed,
            "judged": judged,
            "words": {
                name: [self._parse(parts[name]).words(), self._parse(out[name]).words()]
                for name in parts
            },
            "calls_made": self.judge.calls_made - before_calls,
        }
        return Read(out, report)

    def _cut_section(
        self, name: str, fragment: str, cuts: list[dict], skip: set[str]
    ) -> tuple[str, list[dict], list[dict]]:
        key = (
            hashlib.sha256(fragment.encode("utf-8")).hexdigest(),
            json.dumps(cuts, sort_keys=True),
        )
        if key in self._cut:
            frag, rows = self._cut[key]
            return (
                frag,
                [x for x in rows if "why_not" not in x],
                [x for x in rows if "why_not" in x],
            )
        nums0, recs0 = held(fragment, self.r)
        frag = fragment
        rows: list[dict] = []
        for c in cuts:
            trial = frag
            ok = True
            for _ in range(c["times"]):
                nxt = cut_last(trial, c["sentence"], skip)
                if nxt is None:
                    ok = False
                    break
                trial = nxt
            row = {k: v for k, v in c.items() if k != "times"}
            if not ok:
                rows.append(
                    {
                        **row,
                        "why_not": "no one text run holds the sentence whole (it spans "
                        "markup)",
                    }
                )
                continue
            nums, recs = held(trial, self.r)
            if nums != nums0 or recs != recs0:
                lost = sorted((nums0 - nums) | (recs0 - recs))
                rows.append(
                    {
                        **row,
                        "why_not": "the cut changes the section's numbers or receipts "
                        f"({', '.join(lost) or 'a set grew'})",
                    }
                )
                continue
            frag = trial
            rows.append({**row, "times": c["times"]})
        self._cut[key] = (frag, rows)
        return (
            frag,
            [x for x in rows if "why_not" not in x],
            [x for x in rows if "why_not" in x],
        )


def reader_from_config(cfg: dict, *, replay: bool) -> Reader:
    """The read `orchestrator.yaml` `load_read` configures, with R2's judge on the
    brief's model route (reading only transcripts when the brief replays)."""
    return Reader(judge=judge_from_config(cfg, replay=replay))


def apply_cuts(fragment: str, applied: list[dict], section: str) -> str:
    """The applied cuts of `section` made again on another rendering of its text (the
    commander's report prints the ICS 201 section's form outside its fragment)."""
    skip = set(_raw_rules()["skip_tags"])
    for c in applied:
        if c["section"] != section:
            continue
        for _ in range(c.get("times", 1)):
            nxt = cut_last(fragment, c["sentence"], skip)
            if nxt is None:
                break
            fragment = nxt
    return fragment


def apply_text(text: str, applied: list[dict], section: str) -> str:
    """The applied cuts of `section` made on its author's own text (a `narrative`
    event), so the event carries what the section prints."""
    for c in applied:
        if c["section"] != section:
            continue
        for _ in range(c.get("times", 1)):
            text = remove_last_text(text, c["sentence"])
    return text


# ── the record, for replay and for the appendix ──────────────────────────────────────


def summary_lines(report: dict, order: list[str]) -> list[tuple[str, str, str]]:
    """The appendix's rows: the rules file's hash, then each section's words before and
    after, then the cuts applied and proposed."""
    rows = [("Load read rules sha256", report["rules_sha256"], "")]
    for name in order:
        b, a = report["words"].get(name, [0, 0])
        rows.append((f"  words, {name}", f"{b} before, {a} after", ""))
    rows.append(
        (
            "  cuts",
            f"{len(report['applied'])} applied, {len(report['proposed'])} proposed",
            "",
        )
    )
    return rows


def record(report: dict) -> dict:
    """The read as committed per brief (`load_read/<id>.json`): the
    report without anything a replay cannot reproduce."""
    return {k: report[k] for k in sorted(report) if k != "calls_made"}
