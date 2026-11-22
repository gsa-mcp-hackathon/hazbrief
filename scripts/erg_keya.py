#!/usr/bin/env python3
"""Key A of the HB-03b triple keying: the ERG 2024 PDF's text layer, through pdfplumber.

    uv run python scripts/erg_keya.py            # every table into packs/build/keyA/
    uv run python scripts/erg_keya.py table1     # one table

**No model, no network.** One JSONL file per table (`yellow`, `blue`, `table1`,
`table2`, `table3`, `guides`), one row per printed row, each with its PDF `page` and the
raw cell strings (`raw`). Row schemas are shared with Key B and Key C
(`scripts/erg_join.py`).

Why pdfplumber and not PyMuPDF: pdfplumber exposes every ruling line and rectangle the
page draws (`page.lines`, `page.rects`) beside each character's box and font, which is
what reading column and record boundaries from the printed rules needs; it is
MIT-licensed (pdfminer.six underneath), where PyMuPDF is AGPL-3.0 and this repository is
MIT. pypdfium2, which HB-03's parsers use, gives text but no rules, so Key A is also a
second text reader independent of the seed parse.

How each table is read:

* Rotated pages (Tables 1 and 3 print landscape on a portrait page): every character and
  rule is mapped into the reading frame (`derotate`), so "a row" and "a column" mean
  what they mean on the printed table.
* Tables 1 and 3: each record lies between two horizontal rules; the leftmost long
  vertical rule separates the identity columns (ID, guide, name; or the container) from
  the distances. Several names under one ID line up with their ID lines; a line with no
  ID continues the name above.
* Yellow and blue indexes, Table 2: no record rules, so a row starts at a line with an
  ID number (yellow, Table 2) or a guide number (blue), and the columns are the header
  labels' positions; the vertical rule between the two halves of an index page is read
  from the page.
* Orange guides: one item per printed heading or bullet, a bullet's wrapped lines joined
  (positional: a continuation line is indented past the bullet), headings by font
  weight.

Range checks (Day, Fayers and Harvey 1998; config `range_checks`): every distance's
imperial twin is checked against its metric value, and a failure is written on the row
(`range_failures`). It does not change the value; it sends the page to Key B.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "packs" / "src" / "erg_keys.yaml"
TABLES = ("yellow", "blue", "table1", "table2", "table3", "guides")


class KeyAError(RuntimeError):
    """A page whose structure is not what its locator says."""


def load_config(path: Path = CONFIG) -> dict:
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    for k in ("paths", "keya", "range_checks", "keyc", "keyb"):
        if k not in cfg:
            raise KeyAError(f"{path}: missing required key {k!r}")
    return cfg


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def join_parts(parts: list) -> str:
    """Wrapped lines of one name or bullet as one string. A line that ends in a hyphen
    breaks inside a word ("non-" / "flammable", "1,2,2,2-" / "tetrafluoroethane"), so
    the next line follows it without a space."""
    out = ""
    for p in (norm(x) for x in parts):
        if not p:
            continue
        out = p if not out else (out + p if out.endswith("-") else f"{out} {p}")
    return out


# ------------------------------------------------------------------ geometry
def derotate(objs: list, height: float) -> list:
    """Characters or rules of a page printed landscape (text running upward) mapped into
    the reading frame: reading direction left to right, lines top to bottom."""
    out = []
    for o in objs:
        d = dict(o)
        d["x0"], d["x1"] = height - o["bottom"], height - o["top"]
        d["top"], d["bottom"] = o["x0"], o["x1"]
        if "upright" in d:
            d["upright"] = True
            # A rotated glyph's `size` is its advance (the box's extent along the old
            # vertical), which differs per letter and would split every word; the font
            # size is the box's extent across the line.
            d["size"] = o["x1"] - o["x0"]
        out.append(d)
    return out


def page_frame(page) -> tuple[list, list, list, float]:
    """(chars, rules, rects, width) in the reading frame. A page is rotated when most of
    its characters are not upright."""
    chars = page.chars
    rotated = sum(1 for c in chars if not c["upright"]) > len(chars) / 2
    if not rotated:
        # An upright page's few rotated characters are the side tab ("TABLE 2"),
        # which is page furniture.
        chars = [c for c in chars if c["upright"]]
    rules = list(page.lines)
    rects = list(page.rects)
    if rotated:
        chars = derotate([c for c in chars if not c["upright"]], page.height)
        return (
            chars,
            derotate(rules, page.height),
            derotate(rects, page.height),
            (page.height),
        )
    return list(chars), rules, rects, page.width


def words_of(chars: list, gap: float) -> list:
    from pdfplumber.utils import extract_words

    return extract_words(
        chars,
        x_tolerance=gap,
        y_tolerance=gap,
        keep_blank_chars=False,
        extra_attrs=["fontname", "size"],
    )


def lines_of(words: list, tol: float) -> list:
    """Words grouped into printed lines by their top, each line sorted left to right. A
    word set lower and smaller (a subscript) joins the line it overlaps."""
    lines: list = []
    for w in sorted(words, key=lambda w: (round(w["top"], 1), w["x0"])):
        for ln in lines:
            if abs(ln["top"] - w["top"]) <= tol or (
                w["top"] > ln["top"] and w["bottom"] <= ln["bottom"] + tol
            ):
                ln["words"].append(w)
                ln["bottom"] = max(ln["bottom"], w["bottom"])
                break
        else:
            lines.append({"top": w["top"], "bottom": w["bottom"], "words": [w]})
    for ln in lines:
        ln["words"].sort(key=lambda w: w["x0"])
        ln["x0"] = ln["words"][0]["x0"]
    return sorted(lines, key=lambda ln: ln["top"])


def join_words(words: list) -> str:
    """Words as one string; a word that touches the one before it (a subscript, "H" "2"
    "S") is joined without a space."""
    out = ""
    prev = None
    for w in words:
        # A word space is wider than an eighth of the type size; a narrower gap is
        # tracking or a subscript.
        size = float(w.get("size") or 0)
        if prev is not None and w["x0"] - prev["x1"] > max(0.6, size / 8):
            out += " "
        out += w["text"]
        prev = w
    return out


def is_bold(words: list) -> bool:
    return all("Bold" in w["fontname"] or "Demi" in w["fontname"] for w in words)


def _collinear(segments: list, min_len: float) -> list:
    """Positions of rules drawn as several collinear segments: segments within 1 pt of
    one position are one rule, and its length is the union of their intervals. A rule
    whose union is at least `min_len` is kept."""
    groups: list = []
    for pos, a, b in sorted(segments):
        if groups and pos - groups[-1]["pos"] <= 1.0:
            groups[-1]["iv"].append((a, b))
        else:
            groups.append({"pos": pos, "iv": [(a, b)]})
    out = []
    for g in groups:
        total, end = 0.0, None
        for a, b in sorted(g["iv"]):
            if end is None or a > end:
                total += b - a
                end = b
            elif b > end:
                total += b - end
                end = b
        if total >= min_len:
            out.append(g["pos"])
    return out


def horizontal_rules(rules: list, min_len: float) -> list:
    """Tops of horizontal rules whose drawn length is at least `min_len`."""
    return _collinear(
        [
            (r["top"], r["x0"], r["x1"])
            for r in rules
            if abs(r["bottom"] - r["top"]) < 1.5
        ],
        min_len,
    )


def vertical_rules(rules: list, min_len: float) -> list:
    """x positions of vertical rules whose drawn length is at least `min_len`."""
    return _collinear(
        [
            (r["x0"], r["top"], r["bottom"])
            for r in rules
            if abs(r["x1"] - r["x0"]) < 1.5
        ],
        min_len,
    )


def identity_split(rules: list, chars: list) -> float | None:
    """The rule between the identity columns and the distances: the leftmost vertical
    rule clear of the table's left edge (the first printed character), so a frame drawn
    around the table is not taken for a column rule."""
    left = min(c["x0"] for c in chars) + 15
    xs = [x for x in vertical_rules(rules, 20) if x > left]
    return xs[0] if xs else None


def record_bands(rules: list, rects: list, width: float, share: float) -> list:
    """Horizontal record boundaries: long rules, plus the top and bottom edges of thin
    rule-like rectangles (some rules are drawn as filled rectangles)."""
    thin = [
        {"top": r["top"], "bottom": r["top"], "x0": r["x0"], "x1": r["x1"]}
        for r in rects
        if (r["bottom"] - r["top"]) < 1.5
    ]
    return horizontal_rules(rules + thin, width * share)


# ------------------------------------------------------------------ range checks
_KM_PAIR = re.compile(r"^([\d.]+)(\+?)$")


def check_m_ft(m: int, ft: int, rc: dict) -> str | None:
    lo, hi = rc["ft_per_m"]
    if not m or not lo <= ft / m <= hi:
        return f"{m} m printed as {ft} ft"
    return None


def check_km_mi(km: float, mi: float, rc: dict) -> str | None:
    if abs(mi - km * rc["mi_per_km"]) > rc["mi_tolerance"]:
        return f"{km} km printed as {mi} mi"
    return None


# ------------------------------------------------------------------ distances
_DIST = re.compile(
    r"(\d+) m \((\d+) ft\) ([\d.]+\+?) km \(([\d.]+\+?) mi\) "
    r"([\d.]+\+?) km \(([\d.]+\+?) mi\)"
)


def km_value(km: str, mi: str) -> dict:
    return {
        "km": float(km.rstrip("+")),
        "mi": float(mi.rstrip("+")),
        "plus": km.endswith("+") or mi.endswith("+"),
    }


def spill_value(g: tuple) -> dict:
    return {
        "isolate": {"m": int(g[0]), "ft": int(g[1])},
        "protect_day": km_value(g[2], g[3]),
        "protect_night": km_value(g[4], g[5]),
    }


def spill_range_failures(s: dict, rc: dict, label: str) -> list:
    out = []
    f = check_m_ft(s["isolate"]["m"], s["isolate"]["ft"], rc)
    if f:
        out.append(f"{label}.isolate: {f}")
    for k in ("protect_day", "protect_night"):
        if s[k]["plus"]:
            continue  # "11.0+ km (7.0+ mi)" is the table's printed ceiling (p. 283)
        f = check_km_mi(s[k]["km"], s[k]["mi"], rc)
        if f:
            out.append(f"{label}.{k}: {f}")
    return out


QUALIFIER = re.compile(r"\s*\((when spilled (?:in water|on land))\)\s*$", re.I)


def split_qualifier(printed: str) -> tuple[str, str | None]:
    """A Table 1 name and its printed spill-surface qualifier ("(when spilled in
    water)", ERG p. 30 Note 1), or None."""
    m = QUALIFIER.search(printed)
    if not m:
        return norm(printed), None
    return norm(printed[: m.start()]), m.group(1).lower()


# ------------------------------------------------------------------ Table 1
_ID = re.compile(r"^(\d{4}|—)$")
_GUIDE = re.compile(r"^\d{3}P?$")


def table1_page(page, pno: int, cfg: dict) -> list:
    ka = cfg["keya"]
    chars, rules, rects, width = page_frame(page)
    words = words_of(chars, ka["word_gap"])
    bands = record_bands(rules, rects, width, ka["rule_min_span"])
    split = identity_split(rules, chars)
    if len(bands) < 2 or split is None:
        raise KeyAError(f"ERG p. {pno}: Table 1 page has no record rules")
    rows = []
    for top, bottom in zip(bands, bands[1:]):
        inside = [w for w in words if top < (w["top"] + w["bottom"]) / 2 < bottom]
        ident = [w for w in inside if w["x1"] <= split + 0.5]
        dist = [w for w in inside if w["x0"] > split + 0.5]
        lines = lines_of(ident, ka["line_tolerance"])
        names: list = []
        for ln in lines:
            toks = ln["words"]
            if toks and _ID.match(toks[0]["text"]):
                i = 1
                if toks[0]["text"] == "—" and len(toks) > 1 and toks[1]["text"] == "—":
                    i = 2
                guide = toks[i]["text"] if i < len(toks) else ""
                if not _GUIDE.match(guide):
                    raise KeyAError(f"ERG p. {pno}: Table 1 ID line without a guide")
                names.append(
                    {
                        "id": toks[0]["text"],
                        "guide": guide,
                        "parts": [join_words(toks[i + 1 :])],
                    }
                )
            elif names:
                names[-1]["parts"].append(join_words(toks))
        if not names:
            continue  # header band
        dtext = norm(" ".join(join_words(ln["words"]) for ln in lines_of(dist, 3.0)))
        found = list(_DIST.finditer(dtext))
        refer = "Refer to Table 3" in dtext
        if not found or len(found) + (1 if refer else 0) != 2:
            raise KeyAError(
                f"ERG p. {pno}: Table 1 record {[n['id'] for n in names]} distances "
                f"{dtext!r} do not parse"
            )
        small = spill_value(found[0].groups())
        large = None if refer else spill_value(found[1].groups())
        rc = cfg["range_checks"]
        fails = spill_range_failures(small, rc, "small")
        if large:
            fails += spill_range_failures(large, rc, "large")
        for n in names:
            printed = join_parts(n["parts"])
            name, qual = split_qualifier(printed)
            rows.append(
                {
                    "table": "table1",
                    "page": pno,
                    "id": n["id"],
                    "guide": n["guide"],
                    "printed_name": printed,
                    "name": name,
                    "qualifier": qual,
                    "small": small,
                    "large": large,
                    "large_refer_to_table3": refer,
                    "range_failures": fails,
                    "raw": {"identity": printed, "distances": dtext},
                }
            )
    return rows


# ------------------------------------------------------------------ Table 3
_T3_HEAD = re.compile(r"^UN(\d{4}) (.+?): Large Spills$")
_NUMERIC = re.compile(r"\d+(?:\.\d+)?\+?")


def table3_page(page, pno: int, cfg: dict) -> list:
    ka = cfg["keya"]
    chars, rules, rects, width = page_frame(page)
    words = words_of(chars, ka["word_gap"])
    bands = record_bands(rules, rects, width, ka["rule_min_span"])
    split = identity_split(rules, chars)
    if len(bands) < 2 or split is None:
        raise KeyAError(f"ERG p. {pno}: Table 3 page has no record rules")
    rows, current = [], None
    rc = cfg["range_checks"]
    for top, bottom in zip(bands, bands[1:]):
        inside = [w for w in words if top < (w["top"] + w["bottom"]) / 2 < bottom]
        text = norm(" ".join(join_words(ln["words"]) for ln in lines_of(inside, 3.0)))
        if not text:
            continue
        heads = list(re.finditer(r"UN(\d{4}) (.+?): Large Spills", text))
        if heads:
            # A block may head two ID numbers that share its rows (p. 344: UN1040
            # Ethylene oxide and UN1040 Ethylene oxide with nitrogen; UN1050 and
            # UN2186). The first ID keys the block; `uns` lists every ID it heads.
            current = {
                "un": heads[0].group(1),
                "uns": list(dict.fromkeys(h.group(1) for h in heads)),
                "heading": "; ".join(norm(h.group(0)) for h in heads),
            }
            continue
        if current is None:
            continue
        cont = [w for w in inside if w["x1"] <= split + 0.5]
        nums = sorted(
            (w for w in inside if w["x0"] > split + 0.5), key=lambda w: w["x0"]
        )
        container = norm(
            " ".join(join_words(ln["words"]) for ln in lines_of(cont, 3.0))
        )
        ntext = " ".join(w["text"] for w in nums)
        if re.sub(r"[\d.+()\s]", "", ntext):
            if not container and not _NUMERIC.search(ntext):
                continue
            raise KeyAError(f"ERG p. {pno}: Table 3 cells {ntext!r}")
        vals = _NUMERIC.findall(ntext)
        if not container or len(vals) != 14:
            if container in ("TRANSPORT CONTAINER",) or not vals:
                continue
            raise KeyAError(
                f"ERG p. {pno}: Table 3 row {container!r} has {len(vals)} values"
            )
        iso = {"m": int(vals[0]), "ft": int(vals[1])}
        pairs = [km_value(vals[2 + 2 * k], vals[3 + 2 * k]) for k in range(6)]
        bands_ = ("low", "moderate", "high")
        fails = []
        f = check_m_ft(iso["m"], iso["ft"], rc)
        if f:
            fails.append(f"isolate: {f}")
        for k, p in enumerate(pairs):
            if p["plus"]:
                continue  # the printed ceiling, as in Table 1
            f = check_km_mi(p["km"], p["mi"], rc)
            if f:
                fails.append(f"{('day', 'night')[k // 3]}.{bands_[k % 3]}: {f}")
        rows.append(
            {
                "table": "table3",
                "page": pno,
                "un": current["un"],
                "uns": current["uns"],
                "heading": current["heading"],
                "container": container,
                "isolate": iso,
                "day": dict(zip(bands_, pairs[:3])),
                "night": dict(zip(bands_, pairs[3:])),
                "range_failures": fails,
                "raw": {"container": container, "values": vals},
            }
        )
    return rows


# ------------------------------------------------------------------ indexes
def _half_split(rules: list, chars: list, width: float, height: float) -> float:
    """The vertical rule between the two halves of an index page: a rule at least half
    the page tall in the middle of the page that no character crosses (a page may draw
    a second stroke nearby, through the text, as part of a highlight)."""
    xs = [
        x for x in vertical_rules(rules, height * 0.5) if width * 0.3 < x < width * 0.7
    ]
    clear = [x for x in xs if not any(c["x0"] < x < c["x1"] for c in chars)]
    # Two clear strokes a few points apart bound the same gutter.
    if not clear or clear[-1] - clear[0] > 6:
        raise KeyAError(f"index page: dividers at {xs}, {clear} clear of the text")
    return sum(clear) / len(clear)


def _header(lines: list, labels: tuple) -> tuple[int, dict]:
    """The header line (the first carrying every label) and each label's x0, per
    half."""
    for i, ln in enumerate(lines):
        texts = [w["text"] for w in ln["words"]]
        if all(lab in texts for lab in labels):
            return i, ln
    raise KeyAError(f"no header line with {labels}")


#: A highlight cell is one row tall, or a few lines for a wrapped name; taller fills are
#: page furniture (the yellow tab).
HIGHLIGHT_MAX_HEIGHT = 60.0


def _highlighted(rects: list, top: float, bottom: float, x0: float, x1: float) -> bool:
    """The index's green highlight behind a row (ERG p. 30: an entry highlighted in
    green goes to Table 1): a filled cell, a row tall, that holds the row's first line.
    The fill is a spot colour whose tint carries no hue, so it is recognised by shape
    and position, not by colour."""
    mid = (top + bottom) / 2
    for r in rects:
        if not r.get("fill") or r["bottom"] - r["top"] > HIGHLIGHT_MAX_HEIGHT:
            continue
        if r["top"] <= mid <= r["bottom"] and r["x0"] < x1 and r["x1"] > x0:
            return True
    return False


def index_page(page, pno: int, cfg: dict, kind: str) -> list:
    """One yellow (`kind` "yellow": ID, guide, name) or blue ("blue": name, guide, ID)
    index page. The vertical rule between the two halves is read from the page; in each
    half a row starts at a line whose ID and guide stand in their columns (the header
    labels' positions) and match their patterns, and any other line continues the name
    above it. The bold guide number sits flush against the name, so the columns are
    told apart by token and position together, not by a fixed boundary."""
    ka = cfg["keya"]
    chars, rules, rects, width = page_frame(page)
    split = _half_split(rules, chars, width, page.height)
    rows = []
    for lo, hi in ((0, split), (split, width)):
        half = [c for c in chars if lo <= (c["x0"] + c["x1"]) / 2 < hi]
        lines = lines_of(words_of(half, ka["word_gap"]), ka["line_tolerance"])
        hi_idx, head = _header(
            lines, ("ID", "Guide") if kind == "yellow" else ("Name", "Guide")
        )
        xs = {w["text"]: w["x0"] for w in head["words"]}
        guide_x = xs["Guide"]
        cur = None
        for ln in lines[
            hi_idx + 2 :
        ]:  # the header prints two lines ("ID Guide" / "No.")
            ws = ln["words"]
            text = join_words(ws)
            if re.fullmatch(r"Page \d+|ERG 2024", text):
                continue
            start = None
            if kind == "yellow":
                n_id = 2 if len(ws) > 2 and ws[0]["text"] == ws[1]["text"] == "—" else 1
                if (
                    len(ws) > n_id
                    and ws[0]["x0"] < guide_x - COL_TOL
                    and _ID.match(ws[0]["text"])
                    and _GUIDE.match(ws[n_id]["text"])
                ):
                    start = (ws[0]["text"], ws[n_id]["text"], ws[n_id + 1 :])
            else:
                n_id = (
                    2 if len(ws) > 2 and ws[-1]["text"] == ws[-2]["text"] == "—" else 1
                )
                g = len(ws) - n_id - 1
                if (
                    g >= 1
                    and _ID.match(ws[-1]["text"])
                    and _GUIDE.match(ws[g]["text"])
                    and ws[g]["x0"] >= guide_x - COL_TOL
                ):
                    start = (ws[-1]["text"], ws[g]["text"], ws[:g])
            if start:
                cur = {
                    "table": kind,
                    "page": pno,
                    "id": start[0],
                    "guide": start[1],
                    "parts": [join_words(start[2])],
                    "highlighted": _highlighted(rects, ln["top"], ln["bottom"], lo, hi),
                }
                rows.append(cur)
            elif cur is not None:
                cur["parts"].append(text)
    for r in rows:
        r["name"] = join_parts(r.pop("parts"))
        r["raw"] = {"id": r["id"], "guide": r["guide"], "name": r["name"]}
    return rows


# ------------------------------------------------------------------ Table 2
def column_words(chars: list, bounds: list, gap: float) -> list:
    """Words that never cross a column boundary: each character is assigned to its
    column by its left edge first (`bounds` are the columns' left edges after the
    first), then words are formed inside each column. Two columns printed close together
    ("1162" "155" "Dimethyl...") stay separate words. Each word carries `col`."""
    out = []
    for i in range(len(bounds) + 1):
        lo = bounds[i - 1] if i else float("-inf")
        hi = bounds[i] if i < len(bounds) else float("inf")
        mine = [c for c in chars if lo <= c["x0"] < hi]
        for w in words_of(mine, gap):
            w["col"] = i
            out.append(w)
    return out


#: A gas formula as Table 2 prints it (HCl, H2S, Br2, NO2).
_FORMULA = re.compile(r"^(?:[A-Z][a-z]?\d*){1,3}$")


def table2_page(page, pno: int, cfg: dict) -> tuple[list, list]:
    """(rows, legend): rows are ID, guide, name and the gas symbols; the legend is the
    printed legend lines (pp. 337-341 each print it)."""
    ka = cfg["keya"]
    chars, rules, rects, width = page_frame(page)
    tol = ka["subscript_line_tolerance"]
    lines = lines_of(words_of(chars, ka["word_gap"]), tol)
    hi_idx, head = _header(lines, ("ID", "Guide", "Name"))
    xs = {w["text"]: w["x0"] for w in head["words"]}
    xe = {w["text"]: w["x1"] for w in head["words"]}
    # The ID and gas columns start at their labels; a name starts where its label does
    # in the face of the label, which is set wider, so the boundary between guide and
    # name is the end of the "Guide" label.
    bounds = [xs["Guide"] - COL_TOL, xe["Guide"] + 1, xs["TIH"] - COL_TOL]
    body_top = head["bottom"]
    legend_top = min(
        (
            ln["top"]
            for ln in lines
            if join_words(ln["words"]).replace(" ", "").startswith("ChemicalSymbols")
        ),
        default=None,
    )
    if legend_top is None:
        raise KeyAError(f"ERG p. {pno}: Table 2 page prints no gas legend")
    legend = [join_words(ln["words"]) for ln in lines if ln["top"] > legend_top + 1]
    body = [c for c in chars if body_top + 12 < c["top"] < legend_top - 1]
    rows, cur = [], None
    for ln in lines_of(column_words(body, bounds, ka["word_gap"]), tol):
        text = join_words(ln["words"])
        if re.fullmatch(r"Page \d+", text) or not text:
            continue
        col = {i: [w for w in ln["words"] if w["col"] == i] for i in range(4)}
        if col[0]:
            ident = join_words(col[0])
            if not re.fullmatch(r"\d{4}", ident) or not col[1]:
                raise KeyAError(f"ERG p. {pno}: Table 2 row {text!r}")
            cur = {
                "table": "table2",
                "page": pno,
                "id": ident,
                "guide": join_words(col[1]),
                "parts": [join_words(col[2])],
                "gases": join_words(col[3]).split(),
            }
            rows.append(cur)
        elif cur is not None:
            # A wrapped name may run under the gas column; a word there is a gas only
            # when it is a formula.
            spill = [w for w in col[3] if not _FORMULA.match(w["text"])]
            gases = [w for w in col[3] if _FORMULA.match(w["text"])]
            cur["parts"].append(join_words(col[1] + col[2] + spill))
            cur["gases"] += join_words(gases).split()
    for r in rows:
        r["name"] = join_parts(r.pop("parts"))
        r["raw"] = {"name": r["name"], "gases": " ".join(r["gases"])}
    return rows, legend


def legend_pairs(lines: list) -> list:
    """[(symbol, name)] from the legend lines, in printed order. The legend is letter-
    spaced, so a subscript reads as its own token ("H 2S", "NO 2"); a digit is joined to
    the letters before it. A formula token starts a pair; the words after it, up to the
    next formula, are its name."""
    text = " ".join(lines).split("Use this list")[0]
    text = re.sub(r"([A-Za-z]) (\d)", r"\1\2", text)
    pairs: list = []
    for tok in text.split():
        if _FORMULA.match(tok):
            pairs.append([tok, []])
        elif pairs:
            pairs[-1][1].append(tok)
    return [(sym, " ".join(words)) for sym, words in pairs if words]


# ------------------------------------------------------------------ guides
#: A value is left-aligned under its column label; it may start this far (points) left
#: of the label, whose face is wider.
COL_TOL = 3.0

SECTIONS = ("POTENTIAL HAZARDS", "PUBLIC SAFETY", "EMERGENCY RESPONSE")


def guide_page(page, pno: int, cfg: dict) -> dict:
    """One orange guide page: the guide number, title, and items (section, kind, text)
    in printed order. Furniture (the GUIDE label, page number, footnotes in the display
    face) is set aside as `notes`."""
    ka = cfg["keya"]
    chars, _, _, _ = page_frame(page)
    lines = lines_of(words_of(chars, ka["word_gap"]), ka["line_tolerance"])
    display = [
        ln for ln in lines if all("AvantGarde" in w["fontname"] for w in ln["words"])
    ]
    head = [ln for ln in display if ln["top"] < 60]
    guide = None
    title_parts = []
    for ln in head:
        for w in ln["words"]:
            if w["text"] == "GUIDE":
                continue
            if _GUIDE.match(w["text"]) and guide is None:
                guide = w["text"]
                continue
            title_parts.append(w)
    if guide is None:
        raise KeyAError(f"ERG p. {pno}: no guide number in the page header")
    title = norm(
        " ".join(
            join_words(ln["words"])
            for ln in lines_of(title_parts, ka["line_tolerance"])
        )
    )
    notes = [
        join_words(ln["words"])
        for ln in display
        if ln["top"] >= 60 and not re.search(r"Page \d+", join_words(ln["words"]))
    ]
    body = [
        ln
        for ln in lines
        if ln not in display
        and not re.fullmatch(
            r"Page \d+ ERG 2024|ERG 2024 Page \d+", join_words(ln["words"])
        )
    ]
    items: list = []
    empty: list = []
    section = None
    item_x = None
    prev_bottom = None
    trailer = False
    for ln in body:
        text = join_words(ln["words"])
        # The guide's text runs as one block; a gap wider than `guide_trailer_gap`
        # starts the page's trailer (the ERAP note on the right page), which is not
        # guide content.
        if trailer or (
            prev_bottom is not None
            and ln["top"] - prev_bottom > ka["guide_trailer_gap"]
        ):
            trailer = True
            notes.append(text)
            continue
        if section is not None or text in SECTIONS:
            prev_bottom = ln["bottom"]
        if re.fullmatch(r"Page \d+.*|.*ERG 2024", text):
            continue
        if text in SECTIONS:
            section = text
            items.append({"section": section, "kind": "section", "text": text})
            item_x = None
            continue
        if section is None:
            # Before the first section heading only furniture prints (p. 154 opens the
            # orange section with its tab label, "Guides (orange section)").
            notes.append(text)
            continue
        if text.startswith("•"):
            item_x = ln["x0"]
            body_text = norm(text.lstrip("• "))
            if not body_text:
                # A bullet whose text the text layer does not carry (p. 281: the last
                # bullet of guide 174). Key A records the gap; it never invents text.
                empty.append(ln["top"])
                item_x = None
                continue
            items.append({"section": section, "kind": "bullet", "text": body_text})
            continue
        prev = items[-1] if items else None
        if (
            prev is not None
            and prev["kind"] != "section"
            and item_x is not None
            and ln["x0"] > item_x + ka["hanging_indent"]
        ):
            # Every guide item is set with a hanging indent: a line indented past the
            # first line of the item above continues it (a bullet, or a CAUTION
            # paragraph, p. 162). A wrapped paragraph is text, whatever its weight.
            prev["text"] = join_parts([prev["text"], text])
            if prev["kind"] == "heading":
                prev["kind"] = "text"
            continue
        kind = "heading" if is_bold(ln["words"]) else "text"
        items.append({"section": section, "kind": kind, "text": norm(text)})
        item_x = ln["x0"]
    return {
        "page": pno,
        "guide": guide,
        "title": title,
        "items": items,
        "notes": notes,
        "empty_bullets": empty,
    }


def guides_rows(pages: list) -> list:
    """Guide pages to item rows keyed (guide, section, order); the guide's title and its
    page per section."""
    rows = []
    order: dict = {}
    for gp in pages:
        for it in gp["items"]:
            if it["section"] is None:
                raise KeyAError(f"ERG p. {gp['page']}: an item before any section")
            key = (gp["guide"], it["section"])
            n = order.get(key, 0)
            order[key] = n + 1
            rows.append(
                {
                    "table": "guides",
                    "page": gp["page"],
                    "guide": gp["guide"],
                    "title": gp["title"],
                    "section": it["section"],
                    "order": n,
                    "kind": it["kind"],
                    "text": it["text"],
                    "raw": {"text": it["text"]},
                }
            )
    return rows


# ------------------------------------------------------------------ driver
def extract(table: str, cfg: dict, pdf_path: Path) -> dict:
    """{"rows": [...], "meta": {...}} for one table."""
    import pdfplumber

    first, last = cfg["keya"]["pages"][table]
    rows: list = []
    meta: dict = {"pages": [first, last]}
    with pdfplumber.open(str(pdf_path)) as pdf:
        if table == "table1":
            for p in range(first, last + 1):
                rows += table1_page(pdf.pages[p - 1], p, cfg)
        elif table == "table3":
            for p in range(first, last + 1):
                rows += table3_page(pdf.pages[p - 1], p, cfg)
        elif table in ("yellow", "blue"):
            for p in range(first, last + 1):
                rows += index_page(pdf.pages[p - 1], p, cfg, table)
        elif table == "table2":
            legend: list = []
            for p in range(first, last + 1):
                r, lg = table2_page(pdf.pages[p - 1], p, cfg)
                rows += r
                legend = legend or lg
            meta["legend"] = legend_pairs(legend)
        elif table == "guides":
            pages = [
                guide_page(pdf.pages[p - 1], p, cfg) for p in range(first, last + 1)
            ]
            rows = guides_rows(pages)
            meta["guides"] = {}
            for gp in pages:
                g = meta["guides"].setdefault(
                    gp["guide"], {"title": gp["title"], "pages": [], "notes": []}
                )
                g["pages"].append(gp["page"])
                g["notes"] += gp["notes"]
                if gp["empty_bullets"]:
                    g.setdefault("empty_bullets", []).append(gp["page"])
        else:
            raise KeyAError(f"unknown table {table!r}")
    return {"rows": rows, "meta": meta}


def write_jsonl(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    tmp.replace(path)


def read_jsonl(path: Path) -> list:
    return [
        json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x
    ]


def pdf_path(cfg: dict) -> Path:
    sys.path.insert(0, str(REPO / "scripts"))
    import build_packs as B

    bcfg = B.load_config(REPO / "packs" / "src" / "build_config.yaml")
    return B.SourceSet(bcfg, REPO).path(cfg["keya"]["doc_id"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("tables", nargs="*", default=list(TABLES))
    a = ap.parse_args(argv)
    cfg = load_config()
    src = pdf_path(cfg)
    out = REPO / cfg["paths"]["keya_dir"]
    for t in a.tables:
        res = extract(t, cfg, src)
        write_jsonl(out / f"{t}.jsonl", res["rows"])
        (out / f"{t}.meta.json").write_text(
            json.dumps(res["meta"], ensure_ascii=False, indent=1, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        print(f"[keyA] {t}: {len(res['rows'])} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
