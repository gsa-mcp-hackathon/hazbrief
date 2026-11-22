"""Step 4c of HB-03b: adjudicate Keys A, B and C field by field, and write the results.

Called by `uv run python scripts/erg_join.py adjudicate`. **No model, no network.**
Reads `packs/build/keyA/`, `keyC/`, `join/` and the Key B checkpoint `keyB/pages.jsonl`;
writes

* `packs/build/adjudicated/<table>.jsonl`: the rows the pack is assembled from, each
  with `keyed_by` (the keys whose reading equals the row's final value on every field),
  `adjudicated` (A and B differed on a field and C decided it), `unresolved` and
  `unresolved_fields` (A, B and C all differ, or B never read a page A and C disagree
  on; the field's value is null), and `page`;
* `packs/build/adjudicated/meta.json`: guide titles and pages, the Table 2 legend,
  counts;
* `packs/build/UNRESOLVED.md`: every unresolved field with the three readings and the
  page;
* `LN-02`: every row where the 2024 value
  differs from the 2020 data files, with both values and the page.

The rule (erg_join.py docstring): A = B wins; A != B with C equal to one of them, that
one wins and the row is `adjudicated`; otherwise the field is unresolved and null. A row
on a page Key B did not read is `C_agrees` by construction and keyed by A and C.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import erg_join as J  # noqa: E402
import erg_keya as A  # noqa: E402

KEY_FIELDS = {
    "yellow": ("id",),
    "blue": ("id",),
    "table1": ("id",),
    "table2": ("id",),
    "table3": ("un", "container", "heading"),
    "guides": ("guide", "section", "kind"),
}


# ------------------------------------------------------------------ Key B to the row
# schema
def _bid(v) -> str:
    s = A.norm(str(v))
    return "—" if s.replace(" ", "") in ("——", "—", "--") else s


def b_rows(table: str, page: int, reading: dict) -> list:
    """A Key B page reading in Key A's row schema. A row that cannot be converted (a
    distance that is not a number) is kept with `b_error` so it is adjudicated as a
    disagreement, never dropped."""
    out = []
    if table in ("yellow", "blue"):
        for r in reading["rows"]:
            out.append(
                {
                    "table": table,
                    "page": page,
                    "id": _bid(r.get("id", "")),
                    "guide": A.norm(str(r.get("guide", ""))),
                    "name": A.norm(str(r.get("name", ""))),
                    "highlighted": bool(r.get("highlighted")),
                }
            )
    elif table == "table1":
        for r in reading["rows"]:
            printed = A.norm(str(r.get("name", "")))
            name, qual = A.split_qualifier(printed)
            row = {
                "table": table,
                "page": page,
                "id": _bid(r.get("id", "")),
                "guide": A.norm(str(r.get("guide", ""))),
                "printed_name": printed,
                "name": name,
                "qualifier": qual,
            }
            try:
                row["small"] = _b_spill(r["small"])
                lg = r.get("large")
                refer = isinstance(lg, str) and "table 3" in lg.lower()
                row["large"] = None if refer else _b_spill(lg)
                row["large_refer_to_table3"] = refer
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                row.update(small=None, large=None, large_refer_to_table3=None)
                row["b_error"] = f"distances: {exc!r}"
            out.append(row)
    elif table == "table2":
        for r in reading["rows"]:
            out.append(
                {
                    "table": table,
                    "page": page,
                    "id": _bid(r.get("id", "")),
                    "guide": A.norm(str(r.get("guide", ""))),
                    "name": A.norm(str(r.get("name", ""))),
                    "gases": [A.norm(str(g)) for g in r.get("gases") or []],
                }
            )
    elif table == "table3":
        bands = ("low", "moderate", "high")
        for r in reading["rows"]:
            vals = [A.norm(str(v)).strip("()") for v in r.get("values") or []]
            row = {
                "table": table,
                "page": page,
                "un": A.norm(str(r.get("un", ""))).removeprefix("UN"),
                "heading": A.norm(str(r.get("heading", ""))),
                "container": A.norm(str(r.get("container", ""))),
            }
            try:
                if len(vals) != 14:
                    raise ValueError(f"{len(vals)} values")
                pairs = [A.km_value(vals[2 + 2 * k], vals[3 + 2 * k]) for k in range(6)]
                row["isolate"] = {"m": int(vals[0]), "ft": int(vals[1])}
                row["day"] = dict(zip(bands, pairs[:3]))
                row["night"] = dict(zip(bands, pairs[3:]))
            except ValueError as exc:
                row.update(isolate=None, day=None, night=None, b_error=str(exc))
            out.append(row)
        # A block may head two ID numbers that share its rows (p. 344). The vision read
        # repeats the rows under each heading; one printed row is one row, keyed by the
        # block's first ID, with every ID it heads in `uns`.
        merged: list = []
        for row in out:
            same = next(
                (
                    m
                    for m in merged
                    if m["container"] == row["container"]
                    and m.get("isolate") == row.get("isolate")
                    and m.get("day") == row.get("day")
                    and m.get("night") == row.get("night")
                ),
                None,
            )
            if same is None:
                merged.append({**row, "uns": [row["un"]]})
            elif row["un"] not in same["uns"]:
                same["uns"].append(row["un"])
        out = merged
    elif table == "guides":
        order: Counter = Counter()
        guide = A.norm(str(reading.get("guide", "")))
        for it in reading["items"]:
            sec = A.norm(str(it.get("section", "")))
            out.append(
                {
                    "table": table,
                    "page": page,
                    "guide": guide,
                    "title": A.norm(str(reading.get("title", ""))),
                    "section": sec,
                    "order": order[sec],
                    "kind": A.norm(str(it.get("kind", ""))),
                    "text": A.norm(str(it.get("text", ""))),
                }
            )
            order[sec] += 1
    return out


def _b_spill(d: dict) -> dict:
    g = (
        d["isolate_m"],
        d["isolate_ft"],
        d["day_km"],
        d["day_mi"],
        d["night_km"],
        d["night_mi"],
    )
    g = tuple(A.norm(str(x)) for x in g)
    for x in g[:2]:
        int(x)
    return A.spill_value(g)


# ------------------------------------------------------------------ adjudication
def decide(a, b, c) -> tuple:
    """(value, winner, adjudicated, unresolved) for one field's three readings. `a`,
    `b`, `c` are None where the key does not carry the row."""
    fa, fb, fc = J.cmp_form(a), J.cmp_form(b), J.cmp_form(c)
    if fa == fb:
        return a, "A", False, False
    if c is not None and fc == fa:
        return a, "A", True, False
    if c is not None and fc == fb:
        return b, "B", True, False
    return None, None, False, True


def _match_b(table: str, arows: list, brows: list) -> list:
    """(a or None, b or None) pairs for one page."""
    if table == "guides":
        pairs = []
        for sec in A.SECTIONS:
            al = [r for r in arows if r["section"] == sec]
            bl = [r for r in brows if r["section"] == sec]
            for i, j in J.align(
                [J.cmp_form(r["text"]) for r in al], [J.cmp_form(r["text"]) for r in bl]
            ):
                pairs.append(
                    (al[i] if i is not None else None, bl[j] if j is not None else None)
                )
        return pairs
    bby: dict = defaultdict(list)
    for b in brows:
        try:
            bby[J.key_of(table, b)].append(b)
        except KeyError:
            continue
    out = []
    for a in arows:
        k = J.key_of(table, a)
        out.append((a, bby[k].pop(0) if bby.get(k) else None))
    for rest in bby.values():
        out += [(None, b) for b in rest]
    return out


def adjudicate_table(table: str, joined: list, bpages: dict) -> tuple[list, list, list]:
    """(final rows, unresolved entries, dropped C rows) for one table. `bpages`: page ->
    Key B rows for every page Key B read."""
    fields = J.FIELDS[table]
    by_page: dict = defaultdict(list)
    for j in joined:
        by_page[j["page"]].append(j)
    final, unresolved, dropped = [], [], []
    for page in sorted(by_page):
        js = by_page[page]
        if page not in bpages:
            for j in js:
                if j["class"] == "C_agrees" and not (j["a"] or {}).get(
                    "range_failures"
                ):
                    final.append(_row(table, j["a"], ["A", "C"], False, [], j["c"]))
                elif j["a"] is not None:
                    unresolved.append(
                        _unres(
                            table,
                            page,
                            j["a"],
                            None,
                            j["c"],
                            list(fields),
                            "Key B did not read this page",
                        )
                    )
                    final.append(
                        _row(table, j["a"], [], False, list(fields), j["c"], null=True)
                    )
                else:
                    unresolved.append(
                        _unres(
                            table,
                            page,
                            None,
                            None,
                            j["c"],
                            ["row"],
                            "a 2020 row with no 2024 partner on a page "
                            "Key B did not read",
                        )
                    )
            continue
        arows = [j["a"] for j in js if j["a"] is not None]
        c_of = {id(j["a"]): j["c"] for j in js if j["a"] is not None}
        missing = [j["c"] for j in js if j["class"] == "A_missing"]
        for a, b in _match_b(table, arows, bpages[page]):
            if a is not None:
                c = c_of[id(a)]
                if b is None:
                    # B does not print this row. C's presence sides with A.
                    if c is not None and not J.field_diffs(table, a, c):
                        final.append(_row(table, a, ["A", "C"], True, [], c))
                    else:
                        unresolved.append(
                            _unres(
                                table,
                                page,
                                a,
                                None,
                                c,
                                ["row"],
                                "Key B does not print this row",
                            )
                        )
                        final.append(
                            _row(table, a, [], False, list(fields), c, null=True)
                        )
                    continue
                out, uf, adj = dict(a), [], False
                for f in fields:
                    v, _, was_adj, unres = decide(
                        a.get(f), b.get(f), c.get(f) if c else None
                    )
                    adj |= was_adj
                    if unres:
                        uf.append(f)
                        unresolved.append(
                            _unres(table, page, a, b, c, [f], "A, B and C differ")
                        )
                    out[f] = v
                keyed = [
                    k
                    for k, r in (("A", a), ("B", b), ("C", c))
                    if r is not None and not uf and not J.field_diffs(table, out, r)
                ]
                final.append(_row(table, out, keyed, adj, uf, c, null=bool(uf)))
            else:
                # B prints a row A did not key. C decides whether A missed it.
                cm = next(
                    (
                        c
                        for c in missing
                        if (
                            table == "guides"
                            and J.cmp_form(c["text"]) == J.cmp_form(b["text"])
                        )
                        or (
                            table != "guides"
                            and J.key_of(table, c) == J.key_of(table, b)
                        )
                    ),
                    None,
                )
                if cm is not None and not J.field_diffs(table, b, cm):
                    missing.remove(cm)
                    final.append(
                        _row(table, {**b, "page": page}, ["B", "C"], True, [], cm)
                    )
                else:
                    unresolved.append(
                        _unres(
                            table,
                            page,
                            None,
                            b,
                            cm,
                            ["row"],
                            "Key B prints a row Key A did not key",
                        )
                    )
        # A 2020 row neither A nor B prints on this page was dropped in 2024.
        dropped += missing
    return final, unresolved, dropped


def _row(table, r, keyed, adjudicated, ufields, c, null=False) -> dict:
    out = {k: v for k, v in r.items() if k not in ("raw", "range_failures", "b_error")}
    if null:
        for f in ufields:
            out[f] = None
    out["keyed_by"] = sorted(keyed)
    out["adjudicated"] = bool(adjudicated)
    out["unresolved"] = bool(ufields)
    out["unresolved_fields"] = list(ufields)
    out["c_2020"] = {f: c.get(f) for f in J.FIELDS[table]} if c else None
    return out


def _unres(table, page, a, b, c, fields, why) -> dict:
    def pick(r):
        if r is None:
            return None
        keep = set(J.FIELDS[table]) | set(KEY_FIELDS[table]) | {"name", "printed_name"}
        return {k: r.get(k) for k in sorted(keep) if k in r}

    return {
        "table": table,
        "page": page,
        "fields": fields,
        "why": why,
        "A": pick(a),
        "B": pick(b),
        "C": pick(c),
    }


# ------------------------------------------------------------------ meta (titles,
# legend)
def adjudicate_meta(cfg: dict, bread: dict) -> tuple[dict, list]:
    ka = REPO / cfg["paths"]["keya_dir"]
    kc = REPO / cfg["paths"]["keyc_dir"]
    ga = json.loads((ka / "guides.meta.json").read_text())["guides"]
    gc = json.loads((kc / "guides.meta.json").read_text())["guides"]
    unresolved = []
    guides = {}
    for g, m in sorted(ga.items()):
        bt = [
            r["title"]
            for (t, p), rows in bread.items()
            if t == "guides"
            for r in rows[:1]
            if r["guide"] == g and p in m["pages"]
        ]
        b = bt[0] if bt else None
        c = gc.get(g, {}).get("title")
        # The title is set in a small-caps face (AvantGardeSC): a reader of the page
        # cannot see letter case, so titles are compared case-folded, and the stored
        # title is Key A's characters, which carry the case.
        fold = lambda x: J.cmp_form(x).casefold() if x is not None else None  # noqa: E731
        if b is None:
            v = m["title"] if fold(m["title"]) == fold(c) else None
            keyed = ["A", "C"] if v is not None else []
        else:
            _, winner, _, _ = decide(fold(m["title"]), fold(b), fold(c))
            v = {"A": m["title"], "B": b}.get(winner)
            keyed = (
                [
                    k
                    for k, x in (("A", m["title"]), ("B", b), ("C", c))
                    if x is not None and fold(x) == fold(v)
                ]
                if v
                else []
            )
        if v is None:
            unresolved.append(
                {
                    "table": "guides",
                    "page": m["pages"][0],
                    "fields": ["title"],
                    "why": "guide title",
                    "A": m["title"],
                    "B": b,
                    "C": c,
                }
            )
        guides[g] = {
            "title": v,
            "pages": m["pages"],
            "title_keyed_by": keyed,
            "title_2020": c,
        }
    la = [tuple(x) for x in json.loads((ka / "table2.meta.json").read_text())["legend"]]
    lc = [tuple(x) for x in json.loads((kc / "table2.meta.json").read_text())["legend"]]
    lb = [
        tuple(x) for (t, _), rows in bread.items() if t == "table2_legend" for x in rows
    ]
    norm = lambda xs: sorted(J.cmp_form(list(x)) for x in xs)  # noqa: E731
    if norm(la) == norm(lc) or (lb and norm(la) == norm(lb)):
        legend = sorted(la)
        lk = (
            ["A"]
            + (["B"] if lb and norm(la) == norm(lb) else [])
            + (["C"] if norm(la) == norm(lc) else [])
        )
    else:
        legend, lk = None, []
        unresolved.append(
            {
                "table": "table2",
                "page": cfg["keya"]["pages"]["table2"][0],
                "fields": ["legend"],
                "why": "gas legend",
                "A": la,
                "B": lb,
                "C": lc,
            }
        )
    return {
        "guides": guides,
        "table2_legend": legend,
        "table2_legend_keyed_by": lk,
    }, unresolved


# ------------------------------------------------------------------ reports
def _fmt(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, dict) and "isolate" in v and "protect_day" in v:
        return (
            f"{v['isolate']['m']} m; day {v['protect_day']['km']}"
            f"{'+' if v['protect_day']['plus'] else ''} km; night "
            f"{v['protect_night']['km']}{'+' if v['protect_night']['plus'] else ''} km"
        )
    if isinstance(v, dict) and set(v) == {"low", "moderate", "high"}:
        return (
            " / ".join(
                f"{v[b]['km']}{'+' if v[b]['plus'] else ''}"
                for b in ("low", "moderate", "high")
            )
            + " km"
        )
    if isinstance(v, dict) and set(v) == {"m", "ft"}:
        return f"{v['m']} m"
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)
    return str(v).replace("|", "/")


def _label(table: str, r: dict) -> str:
    if table == "guides":
        return f"Guide {r['guide']} {r['section'].title()} #{r.get('order')}"
    if table == "table3":
        return f"UN{r['un']} {r['container']}"
    return f"{r.get('id')} {r.get('printed_name') or r.get('name')}"


def write_unresolved(path: Path, entries: list) -> None:
    lines = [
        "# HB-03b unresolved readings",
        "",
        "Every field where Key A (the ERG 2024 PDF text layer), Key B (a vision read "
        "of the "
        "rendered page) and Key C (the ERG2020 data files) give three different "
        "readings, or "
        "where Key B did not read a page A and C disagree on. The pack carries each "
        "such field "
        "as null with `unresolved: true`. Written by `scripts/erg_join.py adjudicate`.",
        "",
        f"**Unresolved entries: {len(entries)}.**",
        "",
    ]
    if entries:
        lines += [
            "| table | page | field(s) | why | A | B | C |",
            "|---|--:|---|---|---|---|---|",
        ]
        for e in entries:

            def cell(r):
                if r is None:
                    return "-"
                if isinstance(r, dict):
                    return "; ".join(f"{k}={_fmt(v)}" for k, v in r.items()).replace(
                        "\n", " "
                    )
                return _fmt(r)

            lines.append(
                f"| {e['table']} | {e['page']} | {', '.join(e['fields'])} | "
                f"{e['why']} | {cell(e['A'])} | {cell(e['B'])} | {cell(e['C'])} |"
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


#: HB-03c: the fields whose change is a distance change (any km, mi, m or ft value).
DISTANCE_FIELDS = ("small", "large", "isolate", "day", "night")
NAME_FIELDS = ("name", "printed_name")
CHANGE_KINDS = (
    "changed_distance",
    "changed_name_case",
    "changed_name_text",
    "changed_other",
)


def change_kind(field: str, then, now) -> str:
    """The LN-02 kind of one changed field (HB-03c step 4): a distance; a name that
    differs only in letter case; a name that differs otherwise; anything else (guide
    text, highlight, guide number, gases, "Refer to Table 3")."""
    if field in DISTANCE_FIELDS:
        return "changed_distance"
    if field in NAME_FIELDS:
        same = J.cmp_form(then).casefold() == J.cmp_form(now).casefold()
        return "changed_name_case" if same else "changed_name_text"
    return "changed_other"


def write_delta(path: Path, finals: dict, dropped: dict, counts: dict) -> int:
    """LN-02 (HB-03b step 7; split by kind in HB-03c step 4)."""
    tallies: dict = {}
    body: list = []
    total = 0
    for t in J.TABLES:

        def changed(r: dict) -> list:
            # an unresolved field has no 2024 value to compare; it is listed in
            # UNRESOLVED.md, not here
            return [
                f
                for f in J.FIELDS[t]
                if f not in r["unresolved_fields"]
                and J.cmp_form(r.get(f)) != J.cmp_form(r["c_2020"].get(f))
            ]

        joined = [r for r in finals[t] if r["c_2020"] is not None]
        ch = [r for r in joined if changed(r)]
        ad = [r for r in finals[t] if r["c_2020"] is None]
        rm = dropped[t]
        by_kind = {k: 0 for k in CHANGE_KINDS}
        for r in ch:
            for k in {change_kind(f, r["c_2020"].get(f), r.get(f)) for f in changed(r)}:
                by_kind[k] += 1
        tallies[t] = {
            **by_kind,
            "added": len(ad),
            "removed": len(rm),
            "joined": len(joined),
        }
        counts[t]["delta"] = tallies[t]
        total += len(ch) + len(ad) + len(rm)
        body += [
            f"## {t}",
            "",
            "| kind | row | field | 2020 | 2024 | page |",
            "|---|---|---|---|---|--:|",
        ]
        for r in ch:
            for f in changed(r):
                k = change_kind(f, r["c_2020"].get(f), r.get(f))
                body.append(
                    f"| {k} | {_label(t, r)} | {f} | {_fmt(r['c_2020'].get(f))} "
                    f"| {_fmt(r.get(f))} | {r['page']} |"
                )
        for r in ad:
            body.append(
                f"| added | {_label(t, r)} | | | {_fmt(r.get(J.FIELDS[t][-1]))} | "
                f"{r['page']} |"
            )
        for c in rm:
            body.append(
                f"| removed | {_label(t, c)} | | {_fmt(c.get(J.FIELDS[t][-1]))} | | |"
            )
        body.append("")
    green = [tallies[t] for t in ("table1", "table3")]
    dist = sum(x["changed_distance"] for x in green)
    joined = sum(x["joined"] for x in green)
    lines = [
        "# LN-02: ERG 2020 to ERG 2024, row by row",
        "",
        "**Lab note.** Written by `scripts/erg_join.py adjudicate` (HB-03b step 7; "
        "kinds "
        "split by HB-03c) from the adjudicated ERG 2024 rows "
        "(`packs/build/adjudicated/`) "
        "and the PHMSA ERG2020 data files (`packs/build/keyC/`, HB-01d). Every row "
        "where "
        "the 2024 value differs from the 2020 file, with both values and the ERG 2024 "
        "PDF "
        "page (printed page = PDF page - 2). This is the edition problem in numbers: a "
        "tool "
        "that reads 2020 data (the ERG2020 app, the Esri widget's 2016 table) answers "
        "differently for these rows.",
        "",
        f"**Headline: {dist} of the {joined} Table 1 and Table 3 rows present in both "
        f"editions ({100 * dist / joined:.0f} %) changed at least one distance.**",
        "",
        "The edition says so itself: the ERG 2024 Summary of Changes "
        '(`erg2024-summary-of-changes`, PDF p. 7) lists for Table 1 "Chemical warfare '
        "agents removed, incorporated into the Criminal or Terrorist Use of Chemical, "
        'Biological and Radiological Agents section" and "Revised the distances". The '
        "guides' `removed` rows are mostly the per-guide first aid bullets ERG 2024 "
        "moved "
        'to its General First Aid section (each guide now prints "Refer to the '
        "'General "
        "First Aid' section\"); the indexes' `removed` rows are mostly the warfare "
        "agents.",
        "",
        "Kinds: `changed_distance` (any km, mi, m or ft value differs), "
        "`changed_name_case` (the name differs only in letter case), "
        "`changed_name_text` "
        "(the name differs otherwise), `changed_other` (guide text, highlight, guide "
        'number, gases, "Refer to Table 3"), `added` (no 2020 row under the key: new '
        "or renamed in 2024), `removed` (a 2020 row the 2024 PDF does not print). A "
        "row "
        "with two kinds of change counts once under each.",
        "",
        "## Counts",
        "",
        "| table | changed_distance | changed_name_case | changed_name_text | "
        "changed_other | added | removed | rows in both editions |",
        "|---|--:|--:|--:|--:|--:|--:|--:|",
    ]
    for t, x in tallies.items():
        lines.append(
            f"| {t} | {x['changed_distance']} | {x['changed_name_case']} | "
            f"{x['changed_name_text']} | {x['changed_other']} | {x['added']} | "
            f"{x['removed']} | {x['joined']} |"
        )
    lines += ["", *body]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return total


# ------------------------------------------------------------------ driver
def main(cfg: dict) -> int:
    kbp = REPO / cfg["paths"]["keyb_dir"] / "pages.jsonl"
    ckpt = (
        [json.loads(x) for x in kbp.read_text().splitlines() if x.strip()]
        if kbp.exists()
        else []
    )
    latest: dict = {}
    for r in ckpt:
        if r.get("ok"):
            latest[(r["table"], r["page"])] = r
    bread: dict = {}
    for (t, p), r in latest.items():
        bread[(t, p)] = b_rows(t, p, r["reading"])
        if t == "table2" and r["reading"].get("legend"):
            bread[("table2_legend", p)] = [tuple(x) for x in r["reading"]["legend"]]
    jd = REPO / cfg["paths"]["join_dir"]
    out_dir = REPO / cfg["paths"]["adjudicated_dir"]
    finals, dropped, unresolved, counts = {}, {}, [], {}
    for t in J.TABLES:
        joined = A.read_jsonl(jd / f"{t}.jsonl")
        bpages = {p: rows for (tt, p), rows in bread.items() if tt == t}
        f, u, d = adjudicate_table(t, joined, bpages)
        finals[t], dropped[t] = f, d
        unresolved += u
        A.write_jsonl(out_dir / f"{t}.jsonl", f)
        counts[t] = {
            "rows": len(f),
            "keyB_pages_read": len(bpages),
            "keyed_by": dict(Counter("+".join(r["keyed_by"]) or "none" for r in f)),
            "adjudicated": sum(r["adjudicated"] for r in f),
            "unresolved_rows": sum(r["unresolved"] for r in f),
            "unresolved_entries": len(u),
            "dropped_2020_rows": len(d),
        }
    meta, mu = adjudicate_meta(cfg, bread)
    unresolved += mu
    write_unresolved(REPO / cfg["paths"]["unresolved"], unresolved)
    delta = write_delta(REPO / cfg["paths"]["delta_note"], finals, dropped, counts)
    meta["counts"] = counts
    meta["unresolved_total"] = len(unresolved)
    meta["delta_rows"] = delta
    meta["keyB_pages_read"] = len(latest)
    meta["keyB_failed_pages"] = sorted(
        {(r["table"], r["page"]) for r in ckpt if not r.get("ok")} - set(latest)
    )
    (out_dir / "meta.json").write_text(
        json.dumps(meta, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    )
    print(
        json.dumps(
            {"counts": counts, "unresolved": len(unresolved), "delta_rows": delta},
            indent=1,
        )
    )
    return 0
