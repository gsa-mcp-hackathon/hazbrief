#!/usr/bin/env python3
"""The HB-03b join, classification and adjudication of the three ERG keys.

    uv run python scripts/erg_join.py join        # A to C; the Key B page set
    uv run python scripts/erg_join.py pilot       # the step 4a pilot page list
    uv run python scripts/erg_join.py adjudicate  # A, B, C -> packs/build/adjudicated/,
                                                  # UNRESOLVED.md, LN-02, the counts

**No model, no network.** Key A (`erg_keya.py`, the ERG 2024 PDF), Key C (`erg_keyc.py`,
the ERG2020 data files) and Key B (`erg_keyb.py`, a vision read of the rendered page,
run under Squiddy's python) share one row schema per table. This module never reads a
page itself.

**Join keys** (task step 3): the indexes on (ID number, name); Table 1 on (ID number,
printed name), and every distance cell is compared under it, which is the task's (ID,
name, container, day/night, small/large); Table 2 on (ID, name); Table 3 on (UN,
container); the orange guides on (guide, section, line order), where line order is an
alignment of the two line sequences (Python's difflib, Ratcliff/Obershelp), so one
inserted line in 2024 does not shift every later line out of its pair.

**Classes** of each Key A row: `C_agrees`, `C_differs` (same key, a field differs),
`C_absent` (no 2020 row: new in 2024, or a Key A misread); and each Key C row with no A
partner, `A_missing` (dropped in 2024, or a Key A miss).

**Adjudication** (step 4c), field by field: A = B wins (`keyed_by` A, B, and C where C
also agrees); A != B with C equal to one of them, that one wins (`adjudicated`); A != B
!= C is unresolved, written to `packs/build/UNRESOLVED.md` with the three readings and
the page, and carried with its value null. A row on a page Key B did not read is
`C_agrees` by construction and is keyed by A and C. No value is ever filled by a guess.

Values are compared in a comparison form only (NFKC; the hyphen, dash, quote and space
variants a typesetter or a transcriber may choose between folded; whitespace collapsed);
every stored value is Key A's or Key B's own characters.
"""

from __future__ import annotations

import argparse
import difflib
import json
import random
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import erg_keya as A  # noqa: E402

TABLES = A.TABLES
#: Fields compared per table (the key fields are not repeated here).
#: Names are keyed case-folded and compared exactly, so an edition that changes only a
#: letter's case ("with Nitrogen" in 2020, "with nitrogen" in 2024) pairs the rows and
#: reports the name as differing, rather than one row dropped and another added.
FIELDS = {
    "yellow": ("name", "guide", "highlighted"),
    "blue": ("name", "guide", "highlighted"),
    "table1": ("printed_name", "guide", "small", "large", "large_refer_to_table3"),
    "table2": ("name", "guide", "gases"),
    "table3": ("isolate", "day", "night"),
    "guides": ("text",),
}

_FOLD = {
    0x2010: "-", 0x2011: "-", 0x2012: "-", 0x2013: "-", 0x2014: "-", 0x2212: "-",
    0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"', 0x00A0: " ", 0x00AD: None,
}  # fmt: skip


def cmp_form(value):
    """The comparison form of a value: strings NFKC-normalised, the variants folded,
    whitespace collapsed and the space before punctuation dropped; containers
    recursively."""
    if isinstance(value, str):
        s = unicodedata.normalize("NFKC", value).translate(_FOLD)
        s = re.sub(r"\s+", " ", s).strip()
        return re.sub(r" ([,.;:)])", r"\1", s).replace("( ", "(")
    if isinstance(value, dict):
        return {k: cmp_form(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [cmp_form(v) for v in value]
    return value


def key_of(table: str, r: dict) -> tuple:
    if table in ("yellow", "blue", "table2"):
        return (r["id"], cmp_form(r["name"]).casefold())
    if table == "table1":
        return (r["id"], cmp_form(r["printed_name"]).casefold())
    if table == "table3":
        return (r["un"], cmp_form(r["container"]))
    raise ValueError(table)


def field_diffs(table: str, a: dict, c: dict) -> list:
    return [f for f in FIELDS[table] if cmp_form(a.get(f)) != cmp_form(c.get(f))]


# ------------------------------------------------------------------ join
def join_keyed(table: str, arows: list, crows: list) -> list:
    """Pair rows by key, in order where a key repeats; classify every A row and every
    unpaired C row."""
    cby: dict = defaultdict(list)
    for c in crows:
        cby[key_of(table, c)].append(c)
    out = []
    for a in arows:
        k = key_of(table, a)
        c = cby[k].pop(0) if cby.get(k) else None
        if c is None:
            out.append({"key": list(k), "class": "C_absent", "a": a, "c": None})
            continue
        d = field_diffs(table, a, c)
        out.append(
            {
                "key": list(k),
                "class": "C_differs" if d else "C_agrees",
                "diffs": d,
                "a": a,
                "c": c,
            }
        )
    for k, rest in cby.items():
        for c in rest:
            out.append({"key": list(k), "class": "A_missing", "a": None, "c": c})
    return out


def align(a_texts: list, b_texts: list) -> list:
    """(i or None, j or None) pairs aligning two line sequences in order: equal lines
    pair, a replaced block pairs line by line, the overhang of either side is unpaired.
    difflib's matcher with autojunk off (short sequences, repeated lines such as "Fire"
    are content)."""
    sm = difflib.SequenceMatcher(None, a_texts, b_texts, autojunk=False)
    out = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            out += list(zip(range(i1, i2), range(j1, j2)))
        elif op == "replace":
            n = min(i2 - i1, j2 - j1)
            out += list(zip(range(i1, i1 + n), range(j1, j1 + n)))
            out += [(i, None) for i in range(i1 + n, i2)]
            out += [(None, j) for j in range(j1 + n, j2)]
        elif op == "delete":
            out += [(i, None) for i in range(i1, i2)]
        else:
            out += [(None, j) for j in range(j1, j2)]
    return out


def join_guides(arows: list, crows: list) -> list:
    by_a: dict = defaultdict(list)
    by_c: dict = defaultdict(list)
    for r in arows:
        by_a[(r["guide"], r["section"])].append(r)
    for r in crows:
        by_c[(r["guide"], r["section"])].append(r)
    out = []
    for gs in sorted(set(by_a) | set(by_c)):
        al, cl = by_a.get(gs, []), by_c.get(gs, [])
        pairs = align(
            [cmp_form(r["text"]) for r in al], [cmp_form(r["text"]) for r in cl]
        )
        for i, j in pairs:
            a = al[i] if i is not None else None
            c = cl[j] if j is not None else None
            key = [gs[0], gs[1], a["order"] if a else None, c["order"] if c else None]
            if a and c:
                d = field_diffs("guides", a, c)
                cls = "C_differs" if d else "C_agrees"
                out.append({"key": key, "class": cls, "diffs": d, "a": a, "c": c})
            elif a:
                out.append({"key": key, "class": "C_absent", "a": a, "c": None})
            else:
                out.append({"key": key, "class": "A_missing", "a": None, "c": c})
    return out


def missing_page(table: str, row: dict, arows: list, guide_pages: dict) -> int:
    """The ERG 2024 page an A_missing row would print on: its guide's page for a guide
    line (left page for the hazards and public safety, right for emergency response),
    else the page of the nearest Key A row before it in the table's order."""
    if table == "guides":
        pages = guide_pages[row["guide"]]
        return pages[1] if row["section"] == "EMERGENCY RESPONSE" else pages[0]
    if table == "blue":
        k = cmp_form(row["name"]).lower()
        before = [a for a in arows if cmp_form(a["name"]).lower() <= k]
    else:
        ident = row.get("id") or row.get("un")
        before = [a for a in arows if (a.get("id") or a.get("un")) <= ident]
    return (before[-1] if before else arows[0])["page"]


def run_join(cfg: dict) -> dict:
    ka = REPO / cfg["paths"]["keya_dir"]
    kc = REPO / cfg["paths"]["keyc_dir"]
    jd = REPO / cfg["paths"]["join_dir"]
    gmeta = json.loads((ka / "guides.meta.json").read_text(encoding="utf-8"))["guides"]
    guide_pages = {g: m["pages"] for g, m in gmeta.items()}
    summary: dict = {}
    pages: dict = defaultdict(set)
    for t in TABLES:
        arows = A.read_jsonl(ka / f"{t}.jsonl")
        crows = A.read_jsonl(kc / f"{t}.jsonl")
        joined = (
            join_guides(arows, crows) if t == "guides" else join_keyed(t, arows, crows)
        )
        for j in joined:
            if j["class"] == "A_missing":
                j["page"] = missing_page(t, j["c"], arows, guide_pages)
            else:
                j["page"] = j["a"]["page"]
            if j["class"] != "C_agrees" or (j["a"] and j["a"].get("range_failures")):
                pages[t].add(j["page"])
        A.write_jsonl(jd / f"{t}.jsonl", joined)
        all_pages = range(cfg["keya"]["pages"][t][0], cfg["keya"]["pages"][t][1] + 1)
        summary[t] = {
            "keyA_rows": len(arows),
            "keyC_rows": len(crows),
            "classes": dict(Counter(j["class"] for j in joined)),
            "range_failures": sum(1 for r in arows if r.get("range_failures")),
            "pages": len(all_pages),
            "pages_for_keyB": sorted(pages[t]),
            "pages_all_agree": sorted(set(all_pages) - pages[t]),
        }
    (jd / "summary.json").write_text(
        json.dumps(summary, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def pilot_pages(summary: dict, cfg: dict) -> list:
    """Step 4a: 5 pages from the disagreement set and 5 controls from the all-agree
    pages, each drawn reproducibly (config `pilot_seed`) across every table."""
    rng = random.Random(cfg["keyb"]["pilot_seed"])
    n = cfg["keyb"]["pilot_pages"] // 2
    dis = sorted({(t, p) for t, s in summary.items() for p in s["pages_for_keyB"]})
    ctl = sorted({(t, p) for t, s in summary.items() for p in s["pages_all_agree"]})
    pick = rng.sample(dis, min(n, len(dis))) + rng.sample(ctl, min(n, len(ctl)))
    return [{"table": t, "page": p, "control": (t, p) in ctl} for t, p in pick]


# ------------------------------------------------------------------ manifest
def write_manifest(cfg: dict) -> dict:
    """`packs/build/MANIFEST.json`: every build artifact's sha256, bytes and row count.
    The artifacts are gitignored (over HB-03b's 5 MB line); the manifest is committed,
    so a rebuild can be checked against what built the committed pack. The Key B
    checkpoint is the only artifact a rebuild cannot regenerate without model calls."""
    import hashlib

    root = REPO / cfg["paths"]["build_dir"]
    files = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.name == "MANIFEST.json":
            continue
        data = p.read_bytes()
        files[str(p.relative_to(root))] = {
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "rows": data.count(b"\n") if p.suffix == ".jsonl" else None,
        }
    out = {
        "note": "HB-03b/HB-12 build artifacts; regenerate with scripts/erg_keya.py, "
        "erg_keyc.py, erg_join.py join, erg_keyb.py (model), erg_join.py adjudicate, "
        "mine_flag_rules.py (model).",
        "files": files,
    }
    (root / "MANIFEST.json").write_text(
        json.dumps(out, indent=1, sort_keys=True) + "\n"
    )
    return out


# ------------------------------------------------------------------ CLI
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("command", choices=("join", "pilot", "adjudicate", "manifest"))
    a = ap.parse_args(argv)
    cfg = A.load_config()
    jd = REPO / cfg["paths"]["join_dir"]
    if a.command == "join":
        s = run_join(cfg)
        for t, v in s.items():
            print(
                f"[join] {t}: A {v['keyA_rows']} C {v['keyC_rows']} {v['classes']} "
                f"range {v['range_failures']} -> Key B pages "
                f"{len(v['pages_for_keyB'])}/{v['pages']}"
            )
        total = sum(len(v["pages_for_keyB"]) for v in s.values())
        print(f"[join] Key B pages total: {total}")
    elif a.command == "manifest":
        m = write_manifest(cfg)
        print(f"[manifest] {len(m['files'])} files")
    elif a.command == "pilot":
        s = json.loads((jd / "summary.json").read_text(encoding="utf-8"))
        pages = pilot_pages(s, cfg)
        (jd / "pilot_pages.json").write_text(json.dumps(pages, indent=1) + "\n")
        print(json.dumps(pages))
    else:
        import erg_adjudicate

        return erg_adjudicate.main(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
