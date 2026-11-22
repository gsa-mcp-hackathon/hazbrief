#!/usr/bin/env python3
"""Key A of the ERG 2024 Table of Markings, Labels and Placards (HB-15 step 1), and the
two-key comparison that admits the table into `packs/erg.json`.

The table (PDF pp. 10-11, printed pp. 8-9) is a drawing: placards grouped around black
circles that hold guide numbers. The placard art is image-only; the PDF's text layer
holds only the circled numbers (white Helvetica Bold, set several times over for the
print shadow) and the notes. So the keys are:

* **Key A** (this module): every circled guide number on each page and its centre, read
  from the text layer; and each row's ERG prose sentence (`prose`), whose page text must
  hold it and whose guide number must be the row's.
* **Key B** (`packs/src/erg_placards_keyB.yaml`): a reading of the rendered pages, every
  circle with its number and centre, and every placard drawn beside each.

`key` refuses (KeyingError) unless every Key B circle has a Key A circle on its page
with the same number within `tolerance_pt`, and Key A reads no circle Key B lacks. For a
table this small there is no third key and no adjudication: a disagreement stops the
build, as HB-03b's "unresolved" would, and is fixed at its cause. The placard-to-circle
association is Key B's alone except where `prose` states it; each row says which
(`association`). This is double data entry (Day, Fayers and Harvey 1998, HB-03b section
2) with one key mechanical.

No model, no network. pdfplumber is a dev dependency (HB-03b section 9 item 5).
"""

from __future__ import annotations

import re
from pathlib import Path

#: The circled numbers' glyphs: a 3-digit guide set at this size (points), within
#: SIZE_TOL; the notes and page numbers are set smaller or larger.
CIRCLE_SIZE = 9.7
SIZE_TOL = 0.3
#: The shadow copies of one glyph sit within this many points of each other, and the
#: digits of one number are under this far apart (they are about 4.5 pt apart).
CLUSTER_PT = 12.0


#: A glyph's successor in one copy of a number starts where the glyph ends (its
#: advance), less any pair kerning: from KERN_PT before that point to ADVANCE_TOL after
#: it ("11" is kerned 0.92 pt in this face; the shadow's copies sit at other tops or
#: further off).
KERN_PT = 1.2
ADVANCE_TOL = 0.6
#: Half the digits' cap height, to put a centre on a glyph row given by its top.
CAP_PT = 7.0


def _read(grp: list) -> str:
    """One copy of the number: on the top-most row of glyphs, from the left-most glyph,
    each next glyph the one starting where the last ends. The shadow's copies are
    offset from each other, sometimes by less than a number's width, so a plain sort
    by x would interleave them."""
    top = min(g[2] for g in grp)
    row = sorted(g for g in grp if g[2] == top)
    cur, text = row[0], row[0][3]
    while True:
        nxt = [g for g in row if -KERN_PT <= g[0] - cur[1] <= ADVANCE_TOL]
        if not nxt:
            return text
        cur = min(nxt, key=lambda g: abs(g[0] - cur[1]))
        text += cur[3]


class KeyingError(ValueError):
    """Key A and Key B disagree, or Key B is malformed: the build stops."""


def _norm(text: str) -> str:
    return " ".join(text.split())


def circles(pdf_path: Path, page: int) -> list[dict]:
    """The circled guide numbers on a PDF page: `{guide, at: (x, y)}`, the centre in
    points from the page's top left. Chars outside the page box are the facing page's
    (the spread shares one text layer) and are dropped."""
    import pdfplumber

    with pdfplumber.open(pdf_path) as pdf:
        pg = pdf.pages[page - 1]
        chars = [
            c
            for c in pg.chars
            if abs(c["size"] - CIRCLE_SIZE) <= SIZE_TOL
            and c["text"].isdigit()
            and 0 <= c["x0"] < pg.width
            and 0 <= c["top"] < pg.height
        ]
    # one glyph per distinct position (the shadow repeats each glyph, some copies offset
    # by a few points), then the positions grouped into numbers by proximity
    glyphs = sorted(
        {
            (round(c["x0"], 2), round(c["x1"], 2), round(c["top"], 2), c["text"])
            for c in chars
        }
    )
    groups: list[list] = []
    for g in glyphs:
        for grp in groups:
            if any(
                abs(g[0] - h[0]) < CLUSTER_PT and abs(g[2] - h[2]) < CLUSTER_PT
                for h in grp
            ):
                grp.append(g)
                break
        else:
            groups.append([g])
    out = []
    for grp in groups:
        out.append(
            {
                "guide": _read(grp),
                "at": (
                    (min(g[0] for g in grp) + max(g[1] for g in grp)) / 2,
                    (min(g[2] for g in grp) + max(g[2] for g in grp)) / 2 + CAP_PT / 2,
                ),
            }
        )
    return sorted(out, key=lambda c: (c["at"][1], c["at"][0]))


def page_text(pdf_path: Path, page: int) -> str:
    import pdfplumber

    with pdfplumber.open(pdf_path) as pdf:
        return pdf.pages[page - 1].extract_text() or ""


def _check_b(kb: dict) -> None:
    for k in ("doc_id", "pages", "tolerance_pt", "circles", "placards"):
        if k not in kb:
            raise KeyingError(f"Key B lacks {k!r}")
    ids = [c["id"] for c in kb["circles"]]
    if len(ids) != len(set(ids)):
        raise KeyingError("Key B: duplicate circle id")
    keys = [p["placard"] for p in kb["placards"]]
    if len(keys) != len(set(keys)):
        raise KeyingError("Key B: duplicate placard")
    for p in kb["placards"]:
        if p["circle"] not in ids:
            raise KeyingError(f"Key B: {p['placard']} names no circle {p['circle']!r}")


def key(pdf_path: Path, kb: dict) -> tuple[list[dict], dict]:
    """The admitted rows, each `{placard, words, hazard_class, shows, guide, locator,
    association, keyed_by}`, and the keying report. Raises KeyingError on any
    disagreement."""
    _check_b(kb)
    tol = float(kb["tolerance_pt"])
    doc = kb["doc_id"]
    a_circles = {p: circles(pdf_path, p) for p in kb["pages"]}
    matched: dict[str, dict] = {}
    used: set = set()
    for c in kb["circles"]:
        near = [
            (i, a)
            for i, a in enumerate(a_circles[c["page"]])
            if abs(a["at"][0] - c["at"][0]) <= tol
            and abs(a["at"][1] - c["at"][1]) <= tol
        ]
        if len(near) != 1:
            raise KeyingError(
                f"{c['id']}: Key A reads {len(near)} circles within {tol} pt of "
                f"{c['at']} on p. {c['page']}"
            )
        i, a = near[0]
        if a["guide"] != c["guide"]:
            raise KeyingError(
                f"{c['id']}: Key B reads guide {c['guide']}, Key A {a['guide']}"
            )
        used.add((c["page"], i))
        matched[c["id"]] = {**c, "key_a_at": [round(v, 1) for v in a["at"]]}
    unmatched = [
        {"page": p, **a}
        for p, cs in a_circles.items()
        for i, a in enumerate(cs)
        if (p, i) not in used
    ]
    if unmatched:
        raise KeyingError(f"Key A reads circles Key B lacks: {unmatched}")
    texts: dict[int, str] = {}
    rows = []
    for p in kb["placards"]:
        c = matched[p["circle"]]
        prose = p.get("prose")
        if prose:
            pg = prose["page"]
            texts.setdefault(pg, _norm(page_text(pdf_path, pg)))
            if _norm(prose["quote"]) not in texts[pg]:
                raise KeyingError(
                    f"{p['placard']}: the prose is not on p. {pg}: {prose['quote']!r}"
                )
            stated = re.findall(r"GUIDE (\d{3})", prose["quote"])
            if stated != [c["guide"]]:
                raise KeyingError(
                    f"{p['placard']}: the prose states guides {stated}, the circle "
                    f"{c['guide']}"
                )
        rows.append(
            {
                "placard": p["placard"],
                "words": list(p["words"]),
                "hazard_class": p["hazard_class"],
                "shows": _norm(p["shows"]),
                "guide": c["guide"],
                "locator": f"{doc}#p{c['page']}",
                "association": "prose" if prose else "drawing",
                "prose": (
                    {
                        "quote": _norm(prose["quote"]),
                        "locator": f"{doc}#p{prose['page']}",
                    }
                    if prose
                    else None
                ),
                "keyed_by": ["A", "B"],
                "adjudicated": False,
                "unresolved": False,
                "unresolved_fields": [],
            }
        )
    report = {
        "circles_key_a": sum(len(v) for v in a_circles.values()),
        "circles_key_b": len(kb["circles"]),
        "unmatched": unmatched,
        "rows": len(rows),
        "rows_by_association": {
            k: sum(r["association"] == k for r in rows) for k in ("prose", "drawing")
        },
        "max_offset_pt": round(
            max(
                max(
                    abs(m["key_a_at"][0] - m["at"][0]),
                    abs(m["key_a_at"][1] - m["at"][1]),
                )
                for m in matched.values()
            ),
            1,
        ),
        "circles": [
            {k: m[k] for k in ("id", "page", "guide", "at", "key_a_at")}
            for m in matched.values()
        ],
    }
    return rows, report


def main(argv=None) -> int:
    """Print the keying report (the RESULT's table): `uv run python
    scripts/erg_placards.py`."""
    import argparse
    import json

    import yaml

    repo = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--pdf", type=Path, default=repo / "corpus/raw/erg2024-en-pdf.pdf")
    ap.add_argument(
        "--key-b", type=Path, default=repo / "packs/src/erg_placards_keyB.yaml"
    )
    a = ap.parse_args(argv)
    try:
        _, report = key(a.pdf, yaml.safe_load(a.key_b.read_text(encoding="utf-8")))
    except KeyingError as exc:
        print(f"refused: {exc}")
        return 2
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
