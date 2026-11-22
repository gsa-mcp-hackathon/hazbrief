"""The corpus graph's concept-layer downstream test: eight topics and their reading.

HB-20. A commander's or a design note's topic question ("what does the corpus say about
protective action distances") is answered by the concept layer: the topic's concepts,
the claims whose text names one of them, and the works those claims belong to. This
module holds the eight topics, pre-registered before the layer was built, and the one
reading of a release export that ranks works under a topic.
`test_corpus_concepts.py` reports the ranks and `concept_serve_check.py`
records them with the served verbs' answers. Pure standard library, so both
interpreters (this package's and Squiddy's) import it.

**The layer** (the corpus graph, HB-20): the kit's base-schema concept
edge, (Concept)-[:MENTIONS]->(Claim | Work), written by `squiddy.mentions` (S-008) over
each claim's `text` and each work's `title`. A label located more than once in one
field is a recorded miss; a label too short or too common is flagged `stopword` and
kept (S-008 rules section 4).

**The reading.** A topic names one or more concepts by vocabulary and preferred label.
Its mentions are the Mentions edges from those concepts that are not flagged `stopword`
(the flag "governs traversal", S-008). A work's score is the number of its claims
(Asserts) that a mention reaches, plus one when its own title is mentioned; works are
ranked by score, then id. The topic passes when its expected work is ranked 1 to
`PASS_RANK` and its expected claim is one the mentions reach.

**The expected answers** come from this repository's record, named per topic
(`source`): the document the server's own code or the stylebook vocabulary cites for
the topic, and the claim of that work that states the topic most nearly as a
definition, with no rater or adjudicator `no` ruling on it. They were chosen before the
layer existed. Works are admitted documents; claims are content keys
(`claim:<doc>:<hash>`), so they survive any later extraction run.
"""

from __future__ import annotations

#: The task's pass rule: the expected work at rank 1 to 5 (HB-20 step 2).
PASS_RANK = 5

#: The ICS 201 form's terms in the stylebook vocabulary: the form and its blocks.
ICS201_TERMS = (
    "Incident Briefing",
    "Incident Name",
    "Incident Number",
    "Date/Time Initiated",
    "Map/Sketch",
    "Situation Summary and Health and Safety Briefing",
    "Prepared by",
    "Current and Planned Objectives",
    "Current and Planned Actions, Strategies, and Tactics",
    "Current Organization",
    "Resource Summary",
)

TOPICS = [
    {
        "id": "protective-action-distances",
        "topic": "protective action distances",
        "concepts": [("erg", "protective action distance")],
        "work": "erg2024-en-pdf",
        "claim": "claim:erg2024-en-pdf:213686a5464e",
        "source": "src/hazbrief/incident.py (ERG 2024 Table 1); "
        "test_corpus_claims.py erg-day-night",
    },
    {
        "id": "margins-of-error",
        "topic": "margins of error",
        "concepts": [("census", "margin of error")],
        "work": "census-acs-general-handbook-2020",
        "claim": "claim:census-acs-general-handbook-2020:3ab7fa734e7b",
        "source": "src/hazbrief/census.py (ACS handbook chapter 8); "
        "test_corpus_claims.py acs-moe-sum",
    },
    {
        "id": "group-quarters",
        "topic": "group quarters",
        "concepts": [("census", "group quarters")],
        "work": "census-acs-general-handbook-2020",
        "claim": "claim:census-acs-general-handbook-2020:e7d46b949092",
        "source": "docs/stylebook/VOCABULARY.yaml group quarters "
        "(census-acs-general-handbook-2020#b916)",
    },
    {
        "id": "water-reactive-materials",
        "topic": "water-reactive materials",
        "concepts": [("erg", "water-reactive material")],
        "work": "erg2024-en-pdf",
        "claim": "claim:erg2024-en-pdf:ad08759df095",
        "source": "docs/stylebook/VOCABULARY.yaml water-reactive material "
        "(erg2024-en-pdf#b4585)",
    },
    {
        "id": "toxic-inhalation-hazard",
        "topic": "toxic inhalation hazard",
        "concepts": [("erg", "TIH")],
        "work": "erg2024-en-pdf",
        "claim": "claim:erg2024-en-pdf:1cbdc99d8b8b",
        "source": "docs/stylebook/VOCABULARY.yaml TIH (the ERG 2024 glossary)",
    },
    {
        "id": "ics-201-blocks",
        "topic": "the ICS 201 blocks",
        "concepts": [("ics", t) for t in ICS201_TERMS],
        "work": "ics-201",
        "claim": "claim:ics-201:f6c5558257d0",
        "source": "src/hazbrief/ics201.yaml; test_corpus_claims.py ics201-block4",
    },
    {
        "id": "wind-speed-and-direction",
        "topic": "wind speed and direction",
        "concepts": [
            ("erg", "wind speed"),
            ("erg", "wind direction"),
            ("erg", "low wind"),
            ("erg", "moderate wind"),
            ("erg", "high wind"),
        ],
        "work": "erg2024-en-pdf",
        "claim": "claim:erg2024-en-pdf:7879062625c1",
        "source": "src/hazbrief/incident.py (ERG 2024 Table 3); "
        "test_corpus_claims.py erg-wind-bands",
    },
    {
        "id": "community-resilience-components",
        "topic": "community resilience components",
        "concepts": [("census", "components of social vulnerability")],
        "work": "cre-2024-techdoc",
        "claim": "claim:cre-2024-techdoc:bd39978b957b",
        "source": "test_corpus_claims.py cre-three-or-more",
    },
]


def _key(node_ref: str) -> tuple[str, str]:
    """`Label::key` as a node-link export writes an edge end, split."""
    label, _, key = str(node_ref).partition("::")
    return label, key


def topic_ranks(export: dict) -> list[dict]:
    """Each topic read from a release export (node-link JSON): works ranked, verdict."""
    concepts = {
        (n.get("vocabulary"), n.get("pref_label")): n["key"]
        for n in export["nodes"]
        if n.get("label") == "Concept"
    }
    work_of: dict[str, str] = {}
    mentions: dict[str, list[tuple[str, str, bool]]] = {}
    for e in export.get("links") or []:
        if e.get("type") == "Asserts":
            work_of[_key(e["target"])[1]] = _key(e["source"])[1]
        elif e.get("type") == "Mentions":
            src, tgt = _key(e["source"]), _key(e["target"])
            mentions.setdefault(src[1], []).append(
                (tgt[0], tgt[1], bool(e.get("stopword")))
            )
    out = []
    for t in TOPICS:
        missing = [c for c in t["concepts"] if c not in concepts]
        iris = [concepts[c] for c in t["concepts"] if c in concepts]
        claims, titled = set(), set()
        flagged = 0
        for iri in iris:
            for label, key, stopword in mentions.get(iri, []):
                if stopword:
                    flagged += 1
                    continue
                if label == "Claim":
                    claims.add(key)
                elif label == "Work":
                    titled.add(key)
        score: dict[str, int] = {}
        for c in claims:
            if c in work_of:
                score[work_of[c]] = score.get(work_of[c], 0) + 1
        for w in titled:
            score[w] = score.get(w, 0) + 1
        ranked = sorted(score, key=lambda w: (-score[w], w))
        rank = ranked.index(t["work"]) + 1 if t["work"] in score else None
        claim_reached = t["claim"] in claims
        out.append(
            {
                "id": t["id"],
                "topic": t["topic"],
                "concepts_missing": missing,
                "mentions_claims": len(claims),
                "mentions_titles": len(titled),
                "stopword_edges_skipped": flagged,
                "works": len(ranked),
                "top": [(w, score[w]) for w in ranked[:PASS_RANK]],
                "expected_work": t["work"],
                "work_rank": rank,
                "expected_claim": t["claim"],
                "claim_reached": claim_reached,
                "passed": bool(
                    rank and rank <= PASS_RANK and claim_reached and not missing
                ),
            }
        )
    return out
