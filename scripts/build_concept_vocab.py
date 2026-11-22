#!/usr/bin/env python3
"""Derive the corpus graph's concept vocabularies from the stylebook vocabulary (HB-20).

    PY=/Users/brock/GitHub/squiddy/.venv/bin/python
    $PY scripts/build_concept_vocab.py           # write the graph's corpus/vocab/*.yaml
    $PY scripts/build_concept_vocab.py --check   # exit 1 if a file on disk differs

`docs/stylebook/VOCABULARY.yaml` is the controlled vocabulary of the authorities this
server speaks for (ERG, NIMS, the ICS forms, the Census Bureau): each term with its
authority, a receipt into a held document and the authority's words. The corpus graph
imports it as one Squiddy `form: manual` vocabulary per authority
(`squiddy.vocab.parse_manual`: "a hand-entered term list from a published source that
is not a fetchable file"). Which file each authority goes to is the graph's
declaration: an entry of `domain.vocabularies` in `graph.yaml` with its `authority`. An
authority no entry names is fatal unless `corpus/concept_vocab.yaml` lists it as not
imported, with its reason.

**What a Concept carries.** `name` is the term. `definition` is the stylebook's
statement of it, and because that is this project's sentence and not the authority's,
`definition_source` says so and gives the receipt and the authority's verbatim words
(the Squiddy schema: `definition_source` is "present only when the definition is NOT
the source's verbatim text"). `group` is the authority.

**Alternative labels** are what the mention layer matches besides the term, so each is
a name the authority itself prints, with the parsed index row it is printed in:

1. the `alt_labels` a term lists in VOCABULARY.yaml, each located in its receipt row;
2. the other grammatical number of every label (ANSI/NISO Z39.19-2005 section 6.5,
   singular and plural forms), formed on the head noun (the word before the first
   "of", else the last word) and kept only where a row of one of the authority's held
   documents prints it ON ITS OWN: not inside a longer label of the vocabulary at that
   place ("Protective Action" inside "Protective Action Distances" is that term
   printed, not this one). The authority's documents are those its receipts name. The
   label is kept as the row prints it, and the first such row in document and block
   order is its receipt.

A variant that is another term's label is not added (one label, one concept), and is
reported. Matching is `squiddy.mentions`' own (`label_key`, `locate`), so a label found
here is a label the mention layer can find. Zero model calls; no network.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path

import yaml
from squiddy import mentions as mn

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "corpus" / "concept_vocab.yaml"
ROW_DOC = re.compile(r"^([^#]+)#")
#: The head noun's other number is formed only on a plain alphabetic word.
_ALPHA = re.compile(r"^[A-Za-z]+$")
_SIBILANT = ("s", "x", "z", "ch", "sh")
_ROWS_SQL = (
    "SELECT row_id, text FROM rows WHERE doc_id = ? AND unit = 'paragraph' "
    "ORDER BY para_index"
)


def load_config() -> dict:
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    for key in ("source", "graph", "index_db", "not_imported", "term_type"):
        if key not in cfg:
            raise SystemExit(f"FATAL: {CONFIG} has no `{key}`")
    return cfg


def vocabulary_specs(graph_dir: Path) -> list[dict]:
    """The graph's `domain.vocabularies`, each with the authority it imports."""
    spec = yaml.safe_load((graph_dir / "graph.yaml").read_text(encoding="utf-8"))
    vocabs = (spec.get("domain") or {}).get("vocabularies") or []
    if not vocabs:
        raise SystemExit(
            f"FATAL: {graph_dir / 'graph.yaml'} declares no domain.vocabularies"
        )
    for v in vocabs:
        for key in ("prefix", "form", "path", "authority"):
            if not v.get(key):
                raise SystemExit(f"FATAL: vocabulary {v} has no `{key}`")
        if v["form"] != "manual":
            raise SystemExit(
                f"FATAL: vocabulary {v['prefix']} is form {v['form']!r}; "
                "this script writes manual lists"
            )
    return vocabs


def head_index(words: list[str]) -> int:
    """An English noun phrase's head noun: before the first "of", else the last word."""
    lowered = [w.lower() for w in words]
    return lowered.index("of") - 1 if "of" in lowered[1:] else len(words) - 1


def other_number(word: str) -> list[str]:
    """The other grammatical number of a regular English noun (Z39.19-2005 s. 6.5)."""
    if not _ALPHA.match(word):
        return []
    w = word.lower()
    if w.endswith("ies") and len(w) > 3:
        return [word[:-3] + "y"]
    if w.endswith("ss"):
        return [word + "es"]
    if w.endswith("es") and w[:-2].endswith(_SIBILANT):
        return [word[:-2]]
    if w.endswith("s"):
        return [word[:-1]]
    if w.endswith("y") and len(w) > 1 and w[-2] not in "aeiou":
        return [word[:-1] + "ies"]
    if w.endswith(_SIBILANT):
        return [word + "es"]
    return [word + "s"]


def number_variants(label: str) -> list[str]:
    words = label.split()
    if not words:
        return []
    i = head_index(words)
    return [" ".join([*words[:i], v, *words[i + 1 :]]) for v in other_number(words[i])]


def rows_of(db: Path, docs: list[str]) -> list[tuple[str, str]]:
    """(row_id, text) of every paragraph row of `docs`, in document then block order."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        out = []
        for d in docs:
            out += con.execute(_ROWS_SQL, (d,)).fetchall()
        return out
    finally:
        con.close()


def located(label: str, text: str) -> tuple[int, int] | None:
    """The first span of `label` in `text` under the mention layer's normalization."""
    key = mn.label_key(label)
    idx = {key: [{"iri": "", "label": label, "vocabulary": ""}]}
    spans = mn.locate(text, idx, key.count(" ") + 1).get(key)
    return spans[0] if spans else None


def located_alone(
    label: str, text: str, every: dict, longest: int
) -> tuple[int, int] | None:
    """The first span of `label` in `text` that no longer label of `every` contains."""
    key = mn.label_key(label)
    found = mn.locate(text, every, longest)
    others = [sp for k, spans in found.items() if k != key for sp in spans]
    for s, e in found.get(key, []):
        if not any(s2 <= s and e <= e2 and (s2, e2) != (s, e) for s2, e2 in others):
            return s, e
    return None


def doc_of(row_id: str) -> str:
    m = ROW_DOC.match(row_id)
    if not m:
        raise SystemExit(f"FATAL: {row_id!r} is not a row id")
    return m.group(1)


def definition_source(t: dict) -> str:
    return (
        "hazbrief-mcp docs/stylebook/VOCABULARY.yaml: this project's statement of "
        f"the passage at {t['receipt']}, where the authority's words are "
        f'"{t["quote"]}"'
    )


def file_header(spec: dict, source: str, n_terms: int) -> str:
    return (
        f"# {spec['path']}: GENERATED by scripts/build_concept_vocab.py\n"
        f"# from {source} (HB-20). Do not edit; edit the stylebook\n"
        "# vocabulary and re-run the script (test_corpus_concepts.py checks\n"
        "# that the two agree).\n"
        f"# Authority: {spec['authority']}. {n_terms} term(s). A squiddy\n"
        "# `form: manual` vocabulary: squiddy.vocab.parse_manual reads name,\n"
        "# definition, definition_source, alt_labels, group and term_type;\n"
        "# `receipt` and `alt_label_receipts` are this file's record of where\n"
        "# each label is printed.\n"
    )


def build(cfg: dict) -> tuple[dict[str, str], dict]:
    """Every vocabulary file's text, by path, and a report."""
    graph_dir = REPO / cfg["graph"]
    db = REPO / cfg["index_db"]
    if not db.is_file():
        raise SystemExit(
            f"FATAL: the local index {db} is not built; alternative labels are "
            "located in it"
        )
    vocab = yaml.safe_load((REPO / cfg["source"]).read_text(encoding="utf-8"))
    specs = vocabulary_specs(graph_dir)
    by_authority = {s["authority"]: s for s in specs}
    terms = vocab["terms"]
    unknown = sorted(
        {t["authority"] for t in terms} - set(by_authority) - set(cfg["not_imported"])
    )
    if unknown:
        raise SystemExit(
            f"FATAL: authorities {unknown} have no vocabulary in graph.yaml and no "
            "not_imported reason"
        )

    # one label, one concept: every term's own label key, so a variant never takes
    # another term's
    owner = {
        mn.label_key(t["term"]): t["term"]
        for t in terms
        if t["authority"] in by_authority
    }
    # every label a row could print, the candidates included, for the "on its own" rule
    every_label = [t["term"] for t in terms] + [
        a["label"] for t in terms for a in t.get("alt_labels") or []
    ]
    every_label += [v for lab in list(every_label) for v in number_variants(lab)]
    every, longest = mn.label_index(
        [{"iri": lab, "pref_label": lab, "vocabulary": ""} for lab in every_label]
    )
    report = {
        "variants_added": 0,
        "variants_not_printed": 0,
        "variants_owned_elsewhere": [],
        "explicit": 0,
    }
    files: dict[str, str] = {}
    for spec in specs:
        mine = [t for t in terms if t["authority"] == spec["authority"]]
        receipts = [t["receipt"] for t in mine] + [
            a["receipt"] for t in mine for a in t.get("alt_labels") or []
        ]
        docs = sorted({doc_of(r) for r in receipts})
        rows = rows_of(db, docs)
        row_text = dict(rows)
        out_terms = []
        for t in mine:
            alts: list[dict] = []
            for a in t.get("alt_labels") or []:
                where = f"{t['term']!r} alt label {a['label']!r}: {a['receipt']}"
                if a["receipt"] not in row_text:
                    raise SystemExit(f"FATAL: {where} is not an index row")
                if located(a["label"], row_text[a["receipt"]]) is None:
                    raise SystemExit(f"FATAL: {where} does not print the label")
                alts.append(
                    {
                        "label": a["label"],
                        "receipt": a["receipt"],
                        "how": "listed in VOCABULARY.yaml",
                    }
                )
                report["explicit"] += 1
            have = {mn.label_key(t["term"])} | {mn.label_key(a["label"]) for a in alts}
            for label in [t["term"], *[a["label"] for a in alts]]:
                for variant in number_variants(label):
                    key = mn.label_key(variant)
                    if key in have:
                        continue
                    if key in owner and owner[key] != t["term"]:
                        report["variants_owned_elsewhere"].append(
                            {"term": t["term"], "variant": variant, "owner": owner[key]}
                        )
                        continue
                    hit = next(
                        (
                            (rid, txt, sp)
                            for rid, txt in rows
                            if (sp := located_alone(variant, txt, every, longest))
                        ),
                        None,
                    )
                    if hit is None:
                        report["variants_not_printed"] += 1
                        continue
                    rid, txt, (s, e) = hit
                    alts.append(
                        {
                            "label": re.sub(r"\s+", " ", txt[s:e]),
                            "receipt": rid,
                            "how": "the other number, as the row prints it",
                        }
                    )
                    have.add(key)
                    report["variants_added"] += 1
            out_terms.append(
                {
                    "name": t["term"],
                    "term_type": cfg["term_type"],
                    "group": t["authority"],
                    "definition": re.sub(r"\s+", " ", t["definition"]).strip(),
                    "definition_source": definition_source(t),
                    "receipt": t["receipt"],
                    "alt_labels": [a["label"] for a in alts],
                    "alt_label_receipts": alts,
                }
            )
        label_source = f"the {spec['authority']} term, as {cfg['source']} records it"
        body = yaml.safe_dump(
            {"label_source": label_source, "terms": out_terms},
            sort_keys=False,
            allow_unicode=True,
            width=10_000,
        )
        header = file_header(spec, cfg["source"], len(out_terms))
        files[str(graph_dir / spec["path"])] = header + body
    return files, report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="compare with the files on disk; write nothing",
    )
    args = ap.parse_args(argv)
    files, report = build(load_config())
    stale = [
        p
        for p, text in files.items()
        if not Path(p).is_file() or Path(p).read_text(encoding="utf-8") != text
    ]
    if args.check:
        for p in stale:
            print(f"STALE: {p}")
        return 1 if stale else 0
    for p, text in files.items():
        Path(p).parent.mkdir(parents=True, exist_ok=True)
        Path(p).write_text(text, encoding="utf-8")
        print(f"wrote {p}")
    print(
        f"alt labels: {report['explicit']} listed, {report['variants_added']} "
        f"other-number forms printed by the authority, "
        f"{report['variants_not_printed']} not printed; "
        f"owned by another term: {report['variants_owned_elsewhere']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
