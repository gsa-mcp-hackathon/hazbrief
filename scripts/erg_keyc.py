#!/usr/bin/env python3
"""Key C of the HB-03b triple keying: the PHMSA ERG2020 data files, in Key A's row
schema.

    uv run python scripts/erg_keyc.py            # every table into packs/build/keyC/

**No model, no network.** The six workbooks HB-01d registered and inspected
(`corpus/erg2020_datafiles.md` section 1) are read by column position
(`corpus_text.xlsx_rows`, `xls_rows`) and written one JSONL file per table with the same
fields Key A writes (`scripts/erg_keya.py`), so `scripts/erg_join.py` compares like with
like. They are the **2020** edition: a row where Key C agrees with Key A is corroborated
across editions; a row where it differs is an edition change or a Key A error, and Key B
decides. Each row carries `row` (the 1-based workbook row) as its locator.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import corpus_text  # noqa: E402
import erg_keya as A  # noqa: E402

TABLES = A.TABLES


class KeyCError(RuntimeError):
    """A workbook whose layout is not what corpus/erg2020_datafiles.md records."""


def _id(cell: str) -> str:
    c = A.norm(cell)
    if re.fullmatch(r"—\s*—|——", c):
        return "—"
    if not re.fullmatch(r"\d{4}", c):
        raise KeyCError(f"ID cell {cell!r}")
    return c


def _guide(cell: str) -> str:
    c = A.norm(cell).replace(".0", "")
    if not A._GUIDE.match(c):
        raise KeyCError(f"guide cell {cell!r}")
    return c


def index_rows(rows: list, kind: str) -> list:
    """Yellow (ID, guide, name, TIH, WR, CB) or blue (name, guide, ID, TIH, WR, CB).
    `highlighted` is any of the TIH, WR, CB marks (the workbook's own note in H1: "If
    there is an X, W or Z ... the entry must be highlighted in Green")."""
    out = []
    head = [A.norm(c) for c in rows[0]]
    cols = {
        "id": head.index("ID No."),
        "guide": head.index("Guide No."),
        "name": head.index("Name of material"),
        "marks": [head.index("TIH"), head.index("WR"), head.index("CB")],
    }
    for n, r in enumerate(rows[1:], start=2):
        if not any(A.norm(c) for c in r):
            continue
        cell = lambda i: r[i] if i < len(r) else ""  # noqa: E731
        marks = "".join(A.norm(cell(i)) for i in cols["marks"])
        out.append(
            {
                "table": kind,
                "row": n,
                "id": _id(cell(cols["id"])),
                "guide": _guide(cell(cols["guide"])),
                "name": A.norm(cell(cols["name"])),
                "highlighted": bool(marks),
                "marks": marks,
                "raw": {"cells": [A.norm(c) for c in r[:8]]},
            }
        )
    return out


_M = re.compile(r"^(\d+) m$")
_FT = re.compile(r"^\((\d+) ft\)$")
_KM = re.compile(r"^([\d.]+\+?) km$")
_MI = re.compile(r"^\(([\d.]+\+?) mi\)$")


def _spill(cells: list) -> dict:
    c = [A.norm(x) for x in cells]
    try:
        m, ft = _M.match(c[0]).group(1), _FT.match(c[1]).group(1)
        km = [_KM.match(c[i]).group(1) for i in (2, 4)]
        mi = [_MI.match(c[i]).group(1) for i in (3, 5)]
    except AttributeError:
        raise KeyCError(f"Table 1 distance cells {c}") from None
    return A.spill_value((m, ft, km[0], mi[0], km[1], mi[1]))


def table1_rows(rows: list) -> list:
    """Data rows of `eng_units`: ID, guide, name, then two spill groups of six cells
    (m, (ft), day km, (mi), night km, (mi)); a large spill printed "Refer to table 3"
    has no distances."""
    out = []
    for n, r in enumerate(rows, start=1):
        r = list(r) + [""] * 15
        ident = A.norm(r[0])
        if not re.fullmatch(r"\d{4}|—\s*—", ident):
            continue
        printed = A.norm(r[2])
        name, qual = A.split_qualifier(printed)
        small = _spill(r[3:9])
        rest = " ".join(A.norm(x) for x in r[9:15])
        refer = bool(re.search(r"refer to table 3", rest, re.I))
        large = None if refer else _spill(r[9:15])
        out.append(
            {
                "table": "table1",
                "row": n,
                "id": _id(r[0]),
                "guide": _guide(r[1]),
                "printed_name": printed,
                "name": name,
                "qualifier": qual,
                "small": small,
                "large": large,
                "large_refer_to_table3": refer,
                "raw": {"cells": [A.norm(x) for x in r[:15]]},
            }
        )
    return out


def table2_rows(rows: list) -> tuple[list, list]:
    out, legend = [], []
    in_legend = False
    for n, r in enumerate(rows, start=1):
        r = list(r) + [""] * 4
        first = A.norm(r[0])
        if first.startswith("Chemical Symbols"):
            in_legend = True
            continue
        if in_legend:
            cell = A.norm(r[2])
            m = re.match(r"^(\S+) (.+)$", cell)
            if m:
                legend.append((m.group(1), m.group(2)))
            continue
        if not re.fullmatch(r"\d{4}", first):
            continue
        out.append(
            {
                "table": "table2",
                "row": n,
                "id": first,
                "guide": _guide(r[1]),
                "name": A.norm(r[2]),
                "gases": A.norm(r[3]).split(),
                "raw": {"cells": [A.norm(x) for x in r[:4]]},
            }
        )
    return out, legend


def table3_rows(rows: list) -> list:
    out, current = [], None
    bands = ("low", "moderate", "high")
    for n, r in enumerate(rows, start=1):
        r = list(r) + [""] * 15
        heads = list(re.finditer(r"UN(\d{4}) (.+?): Large Spills", A.norm(r[1])))
        if heads:
            current = {
                "un": heads[0].group(1),
                "uns": list(dict.fromkeys(h.group(1) for h in heads)),
                "heading": "; ".join(A.norm(h.group(0)) for h in heads),
            }
            continue
        if current is None or not A.norm(r[0]) or not A.norm(r[1]):
            continue
        vals = [A.norm(x).strip("()") for x in r[1:15]]
        if not all(re.fullmatch(r"[\d.]+\+?", v) for v in vals):
            continue
        pairs = [A.km_value(vals[2 + 2 * k], vals[3 + 2 * k]) for k in range(6)]
        out.append(
            {
                "table": "table3",
                "row": n,
                "un": current["un"],
                "uns": current["uns"],
                "heading": current["heading"],
                "container": A.norm(r[0]),
                "isolate": {"m": int(vals[0]), "ft": int(vals[1])},
                "day": dict(zip(bands, pairs[:3])),
                "night": dict(zip(bands, pairs[3:])),
                "raw": {"cells": [A.norm(x) for x in r[:15]]},
            }
        )
    return out


def guide_rows(rows: list) -> tuple[list, dict]:
    """One cell per printed line (corpus/erg2020_datafiles.md): `GUIDE nnn`, the title,
    section headings and bullet lines ("· ..."). Item kinds as Key A's: `section` for
    the three section headings, `bullet` for a "·" line, `heading` for a short line in
    capitals or a known sub-heading, `text` otherwise."""
    out, meta = [], {}
    guide = None
    section = None
    order: dict = {}
    expect_title = False
    for n, r in enumerate(rows, start=1):
        cell = A.norm(r[0] if r else "")
        if not cell:
            continue
        m = re.fullmatch(r"GUIDE (\d{3})", cell)
        if m:
            guide, section, expect_title = m.group(1), None, True
            meta[guide] = {"title": None, "row": n}
            continue
        if guide is None:
            continue
        if expect_title:
            meta[guide]["title"] = cell
            expect_title = False
            continue
        if cell in A.SECTIONS:
            section = cell
            kind, text = "section", cell
        elif section is None:
            continue
        elif cell.startswith("·") or cell.startswith("•"):
            kind, text = "bullet", A.norm(cell.lstrip("·• "))
        else:
            kind, text = "heading", cell
        key = (guide, section)
        k = order.get(key, 0)
        order[key] = k + 1
        out.append(
            {
                "table": "guides",
                "row": n,
                "guide": guide,
                "title": meta[guide]["title"],
                "section": section,
                "order": k,
                "kind": kind,
                "text": text,
                "raw": {"text": cell},
            }
        )
    return out, meta


def extract(table: str, cfg: dict) -> dict:
    sys.path.insert(0, str(REPO / "scripts"))
    import build_packs as B

    bcfg = B.load_config(REPO / "packs" / "src" / "build_config.yaml")
    src = B.SourceSet(bcfg, REPO)
    doc = cfg["keyc"][table]
    path = src.path(doc)
    rows = (
        corpus_text.xlsx_rows(path)
        if path.suffix.lower() == ".xlsx"
        else corpus_text.xls_rows(path)
    )
    meta = {"doc_id": doc, "raw_sha256": src.raw_sha256(doc)}
    if table in ("yellow", "blue"):
        out = index_rows(rows, table)
    elif table == "table1":
        out = table1_rows(rows)
    elif table == "table2":
        out, meta["legend"] = table2_rows(rows)
    elif table == "table3":
        out = table3_rows(rows)
    elif table == "guides":
        out, meta["guides"] = guide_rows(rows)
    else:
        raise KeyCError(f"unknown table {table!r}")
    return {"rows": out, "meta": meta}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("tables", nargs="*", default=list(TABLES))
    a = ap.parse_args(argv)
    cfg = A.load_config()
    out = REPO / cfg["paths"]["keyc_dir"]
    for t in a.tables:
        res = extract(t, cfg)
        A.write_jsonl(out / f"{t}.jsonl", res["rows"])
        (out / f"{t}.meta.json").write_text(
            json.dumps(res["meta"], ensure_ascii=False, indent=1, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        print(f"[keyC] {t}: {len(res['rows'])} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
