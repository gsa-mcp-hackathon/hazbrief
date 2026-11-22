"""The one benchmark table (HB-214), rendered from its record, the same wherever it
prints.

`scripts/benchmark_table.py` writes the record
(`docs/evidence/hb214/benchmark_table.json`: the definitions, the columns, one row per
test and the numbered notes) from HB-209's intervals through
`scripts/benchmark_state.py`. Every place the table prints reads that record through
this module, so it is the same everywhere: the TEVV page's Benchmarks and requirement
section (`hazbrief.brief.tevv`), the evidence page and EVALUATION section 2.7
(`scripts/benchmark_table.py`). The brief reads the record, never the graph (no Neo4j at
runtime, DN-001 section 4). ADDENDUM-01: the definitions come before the table.
"""

from __future__ import annotations

import json
from html import escape as esc
from pathlib import Path

RECORD = Path(__file__).resolve().parents[3] / (
    "docs/evidence/hb214/benchmark_table.json"
)

#: the table's style, beside the TEVV page's Conditions of use tables (HB-184)
CSS = (
    " div.benchmark-table { margin: 6px 0; font-size: 13px; }"
    " div.benchmark-table dl { margin: 4px 0 8px; }"
    " div.benchmark-table dt { font-weight: 700; display: inline; }"
    " div.benchmark-table dd { display: inline; margin: 0; }"
    " div.benchmark-table dd::after { content: '';"
    " display: block; margin-bottom: 2px; }"
    " table.benchmarks { border-collapse: collapse; width: 100%; margin: 6px 0; }"
    " table.benchmarks caption { text-align: left; font-weight: 700; }"
    " table.benchmarks th, table.benchmarks td { text-align: left; vertical-align: top;"
    " border-top: 1px solid #e0e0e0; padding: 3px 8px 3px 0; }"
    " div.benchmark-table ol { margin: 4px 0; padding-left: 20px; }"
)


def load(path: Path = RECORD) -> dict:
    """The table's record: definitions, columns, rows, notes."""
    return json.loads(path.read_text(encoding="utf-8"))


def _dl(cls: str, pairs: list[dict]) -> str:
    return (
        f'<dl class="{cls}">'
        + "".join(
            f"<dt>{esc(p['term'])}:</dt> <dd>{esc(p['text'])}</dd>" for p in pairs
        )
        + "</dl>"
    )


def html(table: dict) -> str:
    """The definitions (what a benchmark row is, each column in the table's order, the
    names in the Run column), then the table, then the numbered notes."""
    cols = table["columns"]
    head = "".join(f"<th>{esc(c['name'])}</th>" for c in cols)
    body = "".join(
        f'<tr data-test="{esc(r["test"])}">'
        + "".join(f"<td>{esc(r[c['key']])}</td>" for c in cols)
        + "</tr>"
        for r in table["rows"]
    )
    notes = "".join(f"<li>{esc(n)}</li>" for n in table["notes"])
    return (
        '<div class="benchmark-table">'
        f"<p><strong>{esc(table['definitions_heading'])}</strong></p>"
        + _dl("definitions", table["definitions"])
        + _dl("columns", [{"term": c["name"], "text": c["text"]} for c in cols])
        + _dl("names", table["names"])
        + f'<table class="benchmarks"><caption>{esc(table["caption"])}</caption>'
        f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
        f"<p><strong>{esc(table['notes_heading'])}</strong></p>"
        f'<ol class="notes">{notes}</ol>'
        f"<p>{esc(table['detail'])}</p></div>"
    )


def markdown(table: dict) -> str:
    """The same as `html`, in Markdown: the definitions as a list, the table, the
    notes."""
    cols = table["columns"]
    out = [f"**{table['definitions_heading']}**", ""]
    for p in table["definitions"]:
        out.append(f"- **{p['term']}:** {p['text']}")
    for c in cols:
        out.append(f"- **{c['name']}:** {c['text']}")
    for p in table["names"]:
        out.append(f"- **{p['term']}:** {p['text']}")
    out += [
        "",
        f"**{table['caption']}**",
        "",
        "| " + " | ".join(c["name"] for c in cols) + " |",
        "|" + "---|" * len(cols),
    ]
    for r in table["rows"]:
        out.append("| " + " | ".join(r[c["key"]] for c in cols) + " |")
    out += ["", f"**{table['notes_heading']}**", ""]
    out += [f"{i}. {n}" for i, n in enumerate(table["notes"], 1)]
    out += ["", table["detail"]]
    return "\n".join(out)
