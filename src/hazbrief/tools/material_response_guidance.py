"""`material_response_guidance`: what to do about this material, from its ERG orange
guide, by section, every line with its locator (HB-11; DN-001 section 7; DN-006
section 3.2).

Data source: the ERG 2024 orange guides as `packs/erg.json` holds them
(`ErgGuide.sections`, every guide line triple keyed by HB-03b, each section with its PDF
page). Nothing else is read: no model, no network, no other text of the guide. Update
cadence: the pack changes with a server release (ERG editions are four years apart).
As-of: `pack_versions`.

Lines are printed as the ERG prints them, in printed order, with sub-headings kept as
headings, and marked as quotations: an ERG line is exempt from the stylebook's
vocabulary rules (HB-12 RESULT premise 8). The incident selects among them, and every
line left out is named in `selection.omitted` with the reason:

* fire involved: the fire subsection moves first in its section (FIRE OR EXPLOSION,
  FIRE), and the guide's fire evacuation (EVACUATION, "Fire") is printed; with no fire,
  the fire evacuation is left out;
* spill size: a "Small Spill" block is left out for a large spill and a "Large Spill"
  block for a small one; an unknown size keeps both and says so;
* the sentence about materials "designated with a (P)" only when the material's guide
  number carries the P (ERG p. 347);
* a spill in water: the Table 2 note, for a material Table 2 lists;
* the General First Aid section the guide refers to is named with its page, not printed.

The PHMSA ERG app link is not here; it goes with the map (SB-STR-09).
"""

from __future__ import annotations

import re

from hazbrief import stylecheck
from hazbrief.ics201 import config
from hazbrief.incident import (
    AssessmentError,
    Material,
    basis,
    guide_key,
    identified_by,
    identify_incident,
    identity_basis,
)
from hazbrief.models import (
    ErgData,
    GuideSection,
    IncidentInput,
    SpillSize,
    with_notices,
)
from hazbrief.packs import default_packs

#: HB-15: a spill in water for a load with no ID number (written to the stylebook;
#: build_ics_201 prints it).
UNIDENTIFIED_WATER_LIMIT = (
    "The material is not identified, so {label} Table 2 cannot say whether it gives "
    "off toxic gas in water."
)
#: HB-17: a yellow-index name with no ID number, the explosives.
NO_ID_WATER_LIMIT = (
    "{label} Table 2 lists by ID number, so it cannot say whether this one makes "
    "toxic gas in water."
)
#: The orange guide's three sections in the ERG's own order (ERG p. 348: "Each guide is
#: divided into 3 main sections"; SB-STR-08).
SECTIONS = ("potential_hazards", "public_safety", "emergency_response")


def _page(locator: str) -> int:
    return int(locator.rsplit("#p", 1)[1])


def _is_top(item: dict) -> bool:
    """A top-level subsection heading: printed in capitals (FIRE, SPILL OR LEAK, FIRST
    AID, HEALTH, PROTECTIVE CLOTHING, EVACUATION). Sub-headings are in mixed case
    ("Small Fire", "Large Spill", "Immediate precautionary measure")."""
    t = item["text"]
    return item["kind"] == "heading" and t == t.upper() and any(c.isalpha() for c in t)


def _items(sec: GuideSection, doc: str) -> tuple[list[dict], int]:
    page = _page(sec.locator)
    out, unresolved = [], 0
    for i in sec.items:
        if i.text is None:
            unresolved += 1
            continue
        out.append(
            {
                "text": i.text,
                "page": page,
                "kind": i.kind,
                "locator": f"{doc}#p{page}",
                "quotation": True,
            }
        )
    return out, unresolved


def _drop_blocks(items: list[dict], starts, reason: str, section: str, omitted: list):
    """Remove each sub-block whose heading `starts(text)` matches: the heading and the
    lines up to the next heading."""
    out, i = [], 0
    while i < len(items):
        it = items[i]
        if it["kind"] == "heading" and starts(it["text"]):
            j = i + 1
            while j < len(items) and items[j]["kind"] != "heading":
                j += 1
            omitted.append(
                {
                    "section": section,
                    "heading": it["text"],
                    "reason": reason,
                    "items": j - i,
                }
            )
            i = j
            continue
        out.append(it)
        i += 1
    return out


def _fire_first(items: list[dict], heading: str) -> list[dict]:
    """Move the top-level fire subsection (its heading to the next top-level heading)
    to where the first top-level subsection starts."""
    tops = [n for n, it in enumerate(items) if _is_top(it)]
    start = next((n for n in tops if items[n]["text"] == heading), None)
    if start is None or start == tops[0]:
        return items
    end = next((n for n in tops if n > start), len(items))
    block = items[start:end]
    rest = items[:start] + items[end:]
    first = tops[0]
    return rest[:first] + block + rest[first:]


def _table2_note(mat: Material, erg: ErgData, label: str) -> dict | None:
    rows = [r for r in (mat.material.table2 or []) if not r.unresolved]
    if not rows:
        return None
    legend: dict[str, str] = {}
    for g in erg.table2_legend:
        legend.setdefault(g.symbol, g.name)  # the first name the legend prints
    sentences, entries = [], []
    for r in rows:
        gases = [legend.get(s, s) for s in r.gases or []]
        if not gases:  # the row's gas cell is unresolved: name none
            produced = "toxic inhalation hazard gases"
        elif len(gases) == 1:
            produced = gases[0]
        else:
            produced = f"{', '.join(gases[:-1])} and {gases[-1]}"
        page = _page(r.locator)
        tail = (
            f" produces {produced} when spilled in water "
            f"[{label} Table 2, {mat.id_number}, PDF p. {page}]."
        )
        # HB-15 (F-2): the material's name as Table 2 prints it, unless that makes the
        # sentence longer than SB-SEN-01 allows; then its ID number
        named = r.name + tail
        too_long = any(f.rule == "SB-SEN-01" for f in stylecheck.check(named))
        sentences.append(mat.id_number + tail if too_long else named)
        entries.append({"name": r.name, "gases": r.gases, "locator": r.locator})
    return {"text": " ".join(sentences), "locator": rows[0].locator, "entries": entries}


def guidance(incident: IncidentInput, resolved=None) -> dict:
    """The tool body, apart from registration so tests and build_ics_201 call it.
    `resolved` (HB-18) is one candidate of an ambiguous input (`incident.Material`): the
    governing one, which build_ics_201 prints the guidance of."""
    packs = default_packs()
    erg = packs.erg.data
    cfg = config()["guidance"]
    doc, label = cfg["erg_doc"], cfg["erg_label"]
    try:
        mat = resolved or identify_incident(incident, erg)
    except AssessmentError as exc:
        return exc.as_dict()
    key = guide_key(mat.guide)
    g = erg.guides.get(key)
    if g is None:
        return {
            "error": f"The packs hold no orange guide {mat.guide} for {mat.id_number}.",
            "hint": "Read the guide in the ERG; the pack holds 62 guides (121 and 167 "
            "print no guidance).",
        }
    fire = incident.fire_involved
    size = incident.spill_size
    small = re.compile(cfg["spill_headings"]["small"], re.I)
    large = re.compile(cfg["spill_headings"]["large"], re.I)
    omitted: list[dict] = []
    out: dict = {}
    for name in SECTIONS:
        items, unresolved = _items(g.sections[name], doc)
        if unresolved:
            omitted.append(
                {
                    "section": name,
                    "heading": None,
                    "reason": "unresolved in the pack: the three keyings disagree",
                    "items": unresolved,
                }
            )
        if not mat.guide.endswith("P"):
            kept = [i for i in items if cfg["p_sentence"] not in i["text"]]
            if len(kept) < len(items):
                omitted.append(
                    {
                        "section": name,
                        "heading": None,
                        "reason": "the guide number carries no P, so the sentence on "
                        "materials designated with a (P) does not apply (ERG p. 347)",
                        "items": len(items) - len(kept),
                    }
                )
            items = kept
        if size == SpillSize.SMALL:
            items = _drop_blocks(
                items, large.search, "spill_size is small", name, omitted
            )
        elif size == SpillSize.LARGE:
            items = _drop_blocks(
                items, small.search, "spill_size is large", name, omitted
            )
        fe = cfg["fire_evacuation"]
        if not fire and name == fe["section"]:
            items = _drop_blocks(
                items,
                lambda t, h=fe["heading"]: t == h,
                "fire_involved is false",
                name,
                omitted,
            )
        if fire and name in cfg["fire_subsections"]:
            items = _fire_first(items, cfg["fire_subsections"][name])
        out[name] = items

    gfa = cfg["general_first_aid"]
    refers = any(gfa["marker"] in i["text"] for i in out["emergency_response"])
    general_first_aid = (
        {"refer": True, "locator": gfa["locator"], "title": gfa["title"]}
        if refers
        else None
    )
    note = None
    limits = [
        "Each line is printed as the ERG prints it, with its PDF page, as a quotation.",
        "The incident selects the lines; `selection.omitted` names every line left "
        "out and why.",
    ]
    if size == SpillSize.UNKNOWN:
        limits.append(
            "The spill size is unknown, so the small and the large spill lines are "
            "both printed."
        )
    if incident.where_spilled == "water":
        if mat.material is not None and mat.material.where_spilled_matters:
            note = _table2_note(mat, erg, label)
        elif not mat.identified:
            no_id = mat.entry_point == "index_name"
            limit = NO_ID_WATER_LIMIT if no_id else UNIDENTIFIED_WATER_LIMIT
            limits.append(limit.format(label=label))
        else:
            limits.append(
                f"A spill in water changes nothing here: {label} Table 2 does not "
                "list this material."
            )
    if general_first_aid:
        limits.append(
            "The guide refers to the General First Aid section, which is not "
            "reprinted here."
        )
    out_basis = [
        *identity_basis(mat),
        *(
            basis(
                f"guide section {s}",
                f"{label} Guide {mat.guide}",
                g.sections[s].locator,
            )
            for s in SECTIONS
        ),
    ]
    if general_first_aid:
        out_basis.append(
            basis("General First Aid", f"{label} General First Aid", gfa["locator"])
        )
    if note:
        out_basis.append(
            basis(
                "spill in water",
                f"{label} Table 2, {mat.id_number}",
                note["locator"],
            )
        )
    return {
        "material": {
            "un_number": mat.un,
            "id_number": mat.id_number,
            "names": [n.name for n in mat.entry.names],
            "matched_name": mat.matched_name,
        }
        if mat.identified
        else None,
        "identified_by": identified_by(mat),
        "guide": {
            "number": mat.guide,
            "pack_key": key,
            "title": g.title,
            "locators": {s: g.sections[s].locator for s in SECTIONS},
        },
        "order": list(SECTIONS),
        **out,
        "selection": {
            "fire_involved": fire,
            "spill_size": size.value,
            "where_spilled": incident.where_spilled,
            "omitted": omitted,
        },
        "table2_note": note,
        "general_first_aid": general_first_aid,
        "basis": out_basis,
        "limits": limits,
        "pack_versions": {"erg": packs.erg.version},
    }


def register(mcp) -> None:
    default_packs()  # a missing or altered pack stops the server at startup
    config()  # so does a malformed ics201.yaml

    @mcp.tool(
        name="material_response_guidance",
        annotations={
            "title": "Material Response Guidance",
            "readOnlyHint": True,
            "openWorldHint": False,
        },
    )
    def material_response_guidance(incident: IncidentInput) -> dict:
        """What to do about this material: its ERG orange guide by section (potential
        hazards; public safety; emergency response), each a list of lines `{text, page,
        kind, locator, quotation}` as the ERG prints them, in printed order,
        sub-headings kept.

        The incident selects the lines: with `fire_involved` the fire subsection comes
        first and the guide's fire evacuation is printed; `spill_size` keeps the Small
        Spill or the Large Spill lines (unknown keeps both); `where_spilled` water adds
        the Table 2 note for a water-reactive material; the sentence on materials
        "designated with a (P)" only when the guide number carries the P.
        `selection.omitted` names every line left out and why. `general_first_aid` names
        the ERG section the guide refers to, with its page.

        For a load known only by its placard or a guide number (`placard` or
        `guide_number` instead of `material`), the guide the ERG's Table of Markings,
        Labels and Placards gives, with `identified_by` saying how and `material` null.

        Data source: ERG 2024 orange guides (the server's packs). Update cadence: with a
        server release. As-of: `pack_versions`. No network call, no model. An unknown
        material returns `error` with a `hint` and the nearest index names.
        """
        return with_notices(guidance(incident), incident=incident)
