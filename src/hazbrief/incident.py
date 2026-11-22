"""ERG reasoning shared by `assess_incident` and `protective_action_footprint`.

Everything here is a lookup in the shipped packs or a solar-position calculation;
there is no model and no interpolation (DN-001 section 4 invariants 1-2). Each function
returns plain values plus `basis` entries, each a stylebook source tag (SB-NUM-04) and
the pack locator it reads, so a client can cite every value it narrates.

Rules, each with the ERG text it follows (PDF pages of `erg2024-en-pdf`; the printed
page is two less):

* Day and night: "DAY is any time after sunrise and before sunset. NIGHT is any time
  between sunset and sunrise" (p. 290). Sunrise and sunset by the NOAA solar calculator
  equations as `astral` implements them (DN-005 section 3).
* Small and large spills: "A SMALL SPILL consists of a release of 208 liters (55 US
  gallons) or less" (p. 290).
* Several names under one ID number: "If you do not know the shipping name and Table 1
  lists more than one name for the same ID number, use the entry with the largest
  distances" (p. 290). The same rule is applied when the spill size or the Table 3
  container is unknown: the largest distances the material's rows give. That extension
  is this module's, recorded in HB-08's RESULT; the ERG states it for names only.
* Fire with a Table 1 material: "Use the appropriate Orange Guide for EVACUATION
  distances. Also protect in downwind direction according to Table 1 for residual
  material release" (p. 30).
* An unidentified load (HB-15): "USE THIS TABLE ONLY WHEN THE ID NUMBER OR PROPER
  SHIPPING NAME IS NOT AVAILABLE" (p. 9). A placard is resolved through the Table of
  Markings, Labels and Placards (pp. 10-11, `ErgData.placards`) to its circled guide, or
  the caller gives the guide number; either way the guide's EVACUATION distances apply,
  since Table 1 is read by ID number and name (p. 290).
* Wind bands: the km/h bounds of ERG Table 3 (p. 343) as the pack carries them: low
  below the low band's maximum, high above the high band's minimum, moderate between,
  bounds inclusive (packs/SCHEMA.md).
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from astral import Observer
from astral.sun import elevation, sunrise, sunset

from hazbrief import index_candidates
from hazbrief.models import (
    ErgData,
    ErgGuide,
    ErgIndexEntry,
    ErgMaterial,
    ErgPlacard,
    ErgUnnumbered,
    GuideDistance,
    KmDistance,
    MetricDistance,
    SpillSize,
    Table1Entry,
    Table3Row,
    WindBand,
)
from hazbrief.packs import PackSet

ERG = "ERG 2024"
ERG_DOC = "erg2024-en-pdf"
#: The ERG pages each rule above reads (PDF pages).
LOC_DAY_NIGHT = f"{ERG_DOC}#p290"
LOC_SPILL_SIZE = f"{ERG_DOC}#p290"
LOC_FIRE_WITH_TABLE1 = f"{ERG_DOC}#p30"
#: The source tag of the yellow section's Note 1 (p. 30): water-reactive materials in
#: Table 1. HB-15 (F-2): the note number goes in the tag, so a reason sentence carries
#: no untagged number (SB-NUM-01, SB-NUM-04).
NOTE_1 = f"{ERG} yellow section introduction, Note 1"
#: The Table of Markings, Labels and Placards' introduction (p. 9): use the table only
#: when the ID number and name are not available, and the placard's guide "for now".
LOC_PLACARD_TABLE_USE = f"{ERG_DOC}#p9"
PLACARD_TABLE = f"{ERG} Table of Markings, Labels and Placards"
#: How many nearest index names an unresolved material's hint lists, and how close a
#: name must be (difflib ratio) to be offered.
HINT_NAMES = 5
HINT_CUTOFF = 0.6

_ID = re.compile(r"^\s*(UN|NA)?\s*-?\s*(\d{4})\s*$", re.I)


class AssessmentError(ValueError):
    """An input the ERG cannot answer as given. `hint` says what would answer it."""

    def __init__(self, error: str, hint: str, **detail: Any):
        super().__init__(error)
        self.error, self.hint, self.detail = error, hint, detail

    def as_dict(self) -> dict:
        return {"error": self.error, "hint": self.hint, **self.detail}


class AmbiguousLoad(AssessmentError):
    """An input the ERG answers with several candidates (HB-18): a name under several ID
    numbers, an ID number whose names carry different guides, or a placard several rows
    of the placard table match. `materials` are the candidates as the tools draw them,
    in the order the yellow index or the placard table prints them. It is still the
    HB-15 error (`as_dict`, with the candidates) for a tool that answers one material;
    `protective_action_footprint` draws every candidate instead (DN-001 section 4: the
    ambiguity is reported, never resolved silently)."""

    def __init__(
        self, error: str, hint: str, materials: list, kind: str, **detail: Any
    ):
        super().__init__(error, hint, **detail)
        #: "id_number", "name" or "placard": what the input was ambiguous as
        self.materials, self.kind = materials, kind


def basis(supports: str, tag: str, locator: str | None) -> dict:
    """One basis entry: what it supports, its stylebook source tag, the pack locator."""
    return {"supports": supports, "tag": f"[{tag}]", "locator": locator}


def _norm_name(text: str) -> str:
    return " ".join(text.lower().split())


# ── Material ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Material:
    """What the incident's load resolved to. An identified material (`entry_point`
    "material") has its ID number and index entry. An unidentified load (HB-15;
    `entry_point` "placard" or "guide_number") has only a guide: `un`, `id_number`,
    `entry`, `material` and `matched_name` are None, and `coverage` is
    "unidentified". A yellow-index name with no ID number (HB-17; `entry_point`
    "index_name", the explosives) has its index row and the name it matched, no ID
    number, and `coverage` "unnumbered"; it takes the guide branch as an unidentified
    load does."""

    un: str | None
    id_number: str | None
    coverage: str  # "full", "erg", "index_only", "unidentified" or "unnumbered"
    entry: ErgIndexEntry | None
    material: ErgMaterial | None
    matched_name: str | None
    guide: str
    # "material", "placard", "guide_number" or "index_name"
    entry_point: str = "material"
    placard: ErgPlacard | None = None
    unnumbered: ErgUnnumbered | None = None
    alias: str | None = None
    #: HB-18: a candidate of an ambiguous input, the index names it stands for (one for
    #: a name under several ID numbers; every name of the guide for an ID number whose
    #: names carry different guides). Empty for a resolved input and a placard row.
    candidate_names: tuple[str, ...] = ()

    @property
    def identified(self) -> bool:
        return self.entry_point == "material"


#: The suffix the ERG's generic names carry ("not otherwise specified").
NOS = ", n.o.s."


def _named(key: str, erg: ErgData) -> tuple[list[str], list]:
    """The ID numbers whose index names match `key`, and the rows with no ID number
    (HB-17) whose name or an alias matches it, each with the alias matched or None."""
    rows = [
        (r, None if _norm_name(r.name) == key else a.alias)
        for r in erg.unnumbered
        for a in [None, *r.aliases]
        if _norm_name(a.alias if a else r.name) == key
    ]
    return list(erg.name_index.get(key) or []), rows


#: HB-18: the sentence every ambiguity error's hint ends with, so a client that reads
#: the error from assess_incident or material_response_guidance knows where the
#: candidates are drawn.
AMBIGUOUS_HINT = (
    "Meanwhile protective_action_footprint and build_ics_201 draw every candidate and "
    "print the largest distances."
)


def _id_candidates(un: str, id_number: str, entry: ErgIndexEntry, erg: ErgData) -> list:
    """The candidates of an ID number whose names carry different guides: one per guide,
    with the names under it, where Table 1 does not list the ID (the footprints then
    differ by guide only); one per name where it does (Table 1 has an entry per
    name)."""
    groups: dict = {}
    for n in entry.names:
        key = n.name if entry.in_table1 else n.guide
        groups.setdefault(key, []).append(n)
    return [
        Material(
            un,
            id_number,
            _coverage(un, erg),
            entry,
            erg.materials.get(un),
            names[0].name,
            names[0].guide,
            candidate_names=tuple(n.name for n in names),
        )
        for names in groups.values()
    ]


def _name_candidates(text: str, key: str, uns: list, rows: list, erg: ErgData) -> list:
    """The candidates of a name the yellow index prints under several ID numbers (and
    rows with no ID number): one per ID number, with the guide printed beside the name
    there. None when a candidate's guide cannot be read (the name is not under that ID
    number in the index, or its guide is unresolved): then no candidate is drawn."""
    out = []
    for un in uns:
        entry = erg.index[un]
        named = [n for n in entry.names if _norm_name(n.name) == key]
        if not named or named[0].guide is None:
            return None  # a candidate whose guide is not read: none is drawn
        out.append(
            Material(
                un,
                f"UN{un}",
                _coverage(un, erg),
                entry,
                erg.materials.get(un),
                named[0].name,
                named[0].guide,
                candidate_names=(named[0].name,),
            )
        )
    for row, alias in rows:
        out.append(
            Material(
                None, None, "unnumbered", None, None, row.name, row.guide,
                "index_name", None, row, alias, candidate_names=(row.name,),
            )
        )  # fmt: skip
    return out


def resolve_material(text: str, erg: ErgData) -> Material:
    """An ID number (`UN1017`, `NA1993`, `1017`) or a name as the yellow index prints it
    (case and spacing ignored), including (HB-17) the rows it prints with no ID number
    and their sourced aliases, and a generic name without its ", n.o.s.". Never a
    guess: an unknown or ambiguous input raises AssessmentError with the candidates."""
    m = _ID.match(text)
    if m:
        prefix, un = (m.group(1) or "UN").upper(), m.group(2)
        entry = erg.index.get(un)
        if entry is None:
            raise AssessmentError(
                f"ID number {prefix}{un} is not in the {ERG} yellow index.",
                "Check the number on the placard, orange panel or shipping paper, or "
                "give the material name as the shipping paper prints it.",
            )
        guides = sorted({n.guide for n in entry.names if n.guide is not None})
        if not guides:
            raise AssessmentError(
                f"{prefix}{un}: the pack's guide for this ID number is unresolved.",
                "Read the guide number from the ERG yellow index; the three keyings "
                "of the pack disagree (packs/build/UNRESOLVED.md).",
            )
        if len(guides) > 1:
            if any(n.guide is None for n in entry.names):
                # a candidate set with an unread guide is incomplete: not drawn
                raise AssessmentError(
                    f"{prefix}{un}: the pack's guide for one of its names is "
                    "unresolved.",
                    "Read the guide numbers from the ERG yellow index; the three "
                    "keyings of the pack disagree (packs/build/UNRESOLVED.md).",
                )
            raise AmbiguousLoad(
                f"{prefix}{un} is listed under {len(guides)} guides, one per name.",
                "Give the material name; the yellow index assigns the guide by name. "
                + AMBIGUOUS_HINT,
                _id_candidates(un, f"{prefix}{un}", entry, erg),
                "id_number",
                candidates=[f"{n.name} (Guide {n.guide})" for n in entry.names],
            )
        return Material(
            un,
            f"{prefix}{un}",
            _coverage(un, erg),
            entry,
            erg.materials.get(un),
            None,
            guides[0],
        )

    key = _norm_name(text)
    uns, rows = _named(key, erg)
    if not uns and not rows:
        # The ERG glossary: "n.o.s." marks a generic name ("Corrosive liquid, n.o.s.").
        # A name the index prints with it answers to the name without it; an exact
        # name is read first (HB-17).
        uns, rows = _named(f"{key}{NOS}", erg)
        key = f"{key}{NOS}" if uns or rows else key
    if len(uns) + len(rows) == 1 and rows:
        row, alias = rows[0]
        return Material(
            None,
            None,
            "unnumbered",
            None,
            None,
            row.name,
            row.guide,
            "index_name",
            None,
            row,
            alias,
        )
    if not uns and not rows:
        display = {
            _norm_name(n.name): n.name for e in erg.index.values() for n in e.names
        }
        near = difflib.get_close_matches(
            key, list(display), n=HINT_NAMES, cutoff=HINT_CUTOFF
        )
        # HB-207 item 7: not a bare refusal. The index rows the typed words point to
        # (`index_candidates`), each as the index prints it, for the client to choose
        # from and ask again by its ID number; the tool descriptions are unchanged
        # while the surface is frozen (DN-009 section 2), so the hint says so.
        raise AssessmentError(
            f"{text!r} is not a material name in the {ERG} yellow index.",
            "Give the ID number from the placard or shipping paper, or one of the "
            "nearest index names. index_candidates lists the yellow-index entries "
            "the typed words point to (ID number, name as printed, guide): choose "
            "one and ask again with its ID number; none is chosen here.",
            nearest_index_names=[display[k] for k in near],
            index_candidates=index_candidates.candidates(text, erg),
        )
    if len(uns) + len(rows) > 1:
        listed = (
            f"{len(uns)} ID numbers" if not rows else f"{len(uns) + len(rows)} entries"
        )
        error = f"{text!r} is listed under {listed} in the {ERG} yellow index."
        listed_as = [f"UN{u}" for u in uns] + [r.name for r, _ in rows]
        materials = _name_candidates(text, key, uns, rows, erg)
        if materials is None:
            raise AssessmentError(
                error,
                "Give the ID number from the placard or shipping paper.",
                candidates=listed_as,
            )
        raise AmbiguousLoad(
            error,
            "Give the ID number from the placard or shipping paper. " + AMBIGUOUS_HINT,
            materials,
            "name",
            candidates=listed_as,
        )
    un = uns[0]
    entry = erg.index[un]
    named = [n for n in entry.names if _norm_name(n.name) == key]
    if named[0].guide is None:
        raise AssessmentError(
            f"{text!r}: the pack's guide for this name is unresolved.",
            "Read the guide number from the ERG yellow index; the three keyings of the "
            "pack disagree (packs/build/UNRESOLVED.md).",
        )
    return Material(
        un,
        f"UN{un}",
        _coverage(un, erg),
        entry,
        erg.materials.get(un),
        named[0].name,
        named[0].guide,
    )


# ── The unidentified load (HB-15) ───────────────────────────────────────────

_PLACARD_PREFIX = re.compile(r"^(CLASS|DIVISION)\s+")
_GUIDE = re.compile(r"^\s*(?:guide\s*)?(\d{3})(p?)\s*$", re.I)


def _placard_key(text: str) -> str:
    """Case, hyphens, spacing and a leading "Class" or "Division" ignored."""
    t = " ".join(text.replace("-", " ").upper().split())
    return _PLACARD_PREFIX.sub("", t)


def placard_words(placard: str) -> str:
    """A placard row's key as a responder says it: "Class 2.3", "OXYGEN"."""
    return f"Class {placard}" if placard[0].isdigit() else placard


def _candidate(r: ErgPlacard) -> dict:
    return {"placard": r.placard, "guide": r.guide, "shows": r.shows}


def resolve_placard(text: str, erg: ErgData) -> Material:
    """A placard as the responder reads it: the class or division printed on it, a word
    printed on it, DANGEROUS, or none (no placard can be seen). Resolved through the
    Table of Markings, Labels and Placards to the one row it names; a value that names
    several rows (a bare class 2, 4, 5 or 6, whose divisions have their own guides;
    EXPLOSIVES; INHALATION HAZARD) raises AssessmentError with the rows, never a
    guess."""
    k = _placard_key(text)
    rows = [
        r
        for r in erg.placards
        if k == _placard_key(r.placard) or k in {_placard_key(w) for w in r.words}
    ]
    if not rows:
        rows = [
            r
            for r in erg.placards
            if r.hazard_class is not None and r.hazard_class.split(".")[0] == k
        ]
    if len(rows) == 1:
        r = rows[0]
        if r.unresolved:
            raise AssessmentError(
                f"Placard {text!r}: the pack's row is unresolved.",
                "Read the guide from the ERG's Table of Markings, Labels and Placards.",
            )
        return Material(
            None, None, "unidentified", None, None, None, r.guide, "placard", r
        )
    if rows:
        if any(r.unresolved for r in rows):
            raise AssessmentError(
                f"Placard {text!r}: a matching row of the pack is unresolved.",
                "Read the guides from the ERG's Table of Markings, Labels and "
                "Placards.",
                candidates=[_candidate(r) for r in rows],
            )
        raise AmbiguousLoad(
            f"Placard {text!r} matches {len(rows)} placards in the {PLACARD_TABLE}, "
            f"under {len({r.guide for r in rows})} guides.",
            "Give the division the placard shows, or the word printed on it; the ERG "
            "sends each to its own guide. " + AMBIGUOUS_HINT,
            [
                Material(None, None, "unidentified", None, None, None, r.guide,
                         "placard", r)
                for r in rows
            ],
            "placard",
            candidates=[_candidate(r) for r in rows],
        )  # fmt: skip
    accepted = sorted(
        {r.placard for r in erg.placards} | {w for r in erg.placards for w in r.words}
    )
    raise AssessmentError(
        f"{text!r} is not a placard in the {PLACARD_TABLE}.",
        "Give the class or division printed on the placard, a word printed on it, "
        "DANGEROUS, or none when no placard can be seen.",
        accepted=accepted,
    )


def resolve_guide(text: str, erg: ErgData) -> Material:
    """A guide number the responder gives (111 for an unidentified load; 112 or 114 for
    explosives by division; a P after the number is kept, as the yellow index prints
    it). Any guide the pack holds."""
    m = _GUIDE.match(text)
    if m is None or m.group(1) not in erg.guides:
        raise AssessmentError(
            f"{text!r} is not an orange guide the {ERG} prints guidance under.",
            "Give a guide number from 111 to 174; guides 121 and 167 print no "
            "guidance.",
            guides=sorted(erg.guides),
        )
    number = m.group(1) + m.group(2).upper()
    return Material(
        None, None, "unidentified", None, None, None, number, "guide_number", None
    )


def identify(
    erg: ErgData,
    material: str | None = None,
    guide_number: str | None = None,
    placard: str | None = None,
) -> Material:
    """The load, from exactly one of the three entry points `IncidentInput` takes."""
    given = [v is not None for v in (material, guide_number, placard)]
    if sum(given) != 1:
        raise ValueError("give exactly one of material, guide_number and placard")
    if material is not None:
        return resolve_material(material, erg)
    if guide_number is not None:
        return resolve_guide(guide_number, erg)
    return resolve_placard(placard, erg)


def identify_incident(incident, erg: ErgData) -> Material:
    """`identify` on an `IncidentInput`."""
    return identify(erg, incident.material, incident.guide_number, incident.placard)


def candidate_of(incident, erg: ErgData, index: int) -> Material:
    """Candidate `index` of an ambiguous incident (HB-18): the material the footprint
    marked governing, for the tools build_ics_201 runs on it."""
    try:
        identify_incident(incident, erg)
    except AmbiguousLoad as exc:
        return exc.materials[index]
    raise ValueError("the incident's load is not ambiguous")


def identified_by(mat: Material) -> dict | None:
    """How an unidentified load, or a name with no ID number (HB-17), reached its
    guide, for the tools' outputs; None for a material."""
    if mat.identified:
        return None
    if mat.entry_point == "guide_number":
        return {"entry_point": "guide_number", "guide": mat.guide, "locator": None}
    if mat.entry_point == "index_name":
        u = mat.unnumbered
        alias = next((a for a in u.aliases if a.alias == mat.alias), None)
        return {
            "entry_point": "index_name",
            "name": u.name,
            "alias": mat.alias,
            "alias_source": alias.model_dump() if alias else None,
            "guide": u.guide,
            "locator": u.locator,
            "note": u.note.model_dump(),
            "keyed_by": list(u.keyed_by),
        }
    r = mat.placard
    return {
        "entry_point": "placard",
        "placard": r.placard,
        "shows": r.shows,
        "hazard_class": r.hazard_class,
        "guide": r.guide,
        "locator": r.locator,
        "association": r.association,
        "prose": r.prose.model_dump() if r.prose else None,
        "keyed_by": list(r.keyed_by),
    }


def identity_basis(mat: Material) -> list[dict]:
    """The basis entries for how the load reached its guide: the yellow index for a
    material, the placard table (and the ERG sentence stating it) for a placard, the
    incident report for a guide number the caller gave."""
    if mat.identified:
        return [
            basis(
                "ID number, names and guide",
                f"{ERG} yellow index, {mat.id_number}",
                mat.entry.names[0].locator,
            )
        ]
    if mat.entry_point == "guide_number":
        return [basis("guide number", "incident report", None)]
    if mat.entry_point == "index_name":
        u = mat.unnumbered
        out = [basis("name and guide", f"{ERG} yellow index", u.locator)]
        out.append(basis("no ID number", f"{ERG} yellow index, Note 2", u.note.locator))
        alias = next((a for a in u.aliases if a.alias == mat.alias), None)
        if alias:
            section = alias.locator.split("#")[1]
            out.append(basis(f"{alias.alias} names {u.name}", f"49 CFR {section}",
                             alias.locator))  # fmt: skip
        return out
    r = mat.placard
    out = [basis("guide from the placard", PLACARD_TABLE, r.locator)]
    if r.prose:
        out.append(
            basis("the placard's guide, as the ERG states it", ERG, r.prose.locator)
        )
    return out


#: HB-17: a yellow-index name with no ID number (ERG 2024 p. 30, Note 2).
NO_ID_LIMIT = (
    f"The ERG lists explosives by division, not by ID number [{ERG} yellow index, "
    "Note 2]."
)


def unidentified_limits(mat: Material) -> list[str]:
    """`assess_incident`'s limits for an unidentified load, written to the stylebook
    (build_ics_201 prints them in Block 5). ERG p. 9 steps 3 and 5."""
    if mat.entry_point == "index_name":
        return [NO_ID_LIMIT]
    tag = f"[{PLACARD_TABLE}]"
    first = (
        "The guide is the placard's, not the material's."
        if mat.entry_point == "placard"
        else "The guide was given, not found from the material."
    )
    out = [
        f"{first} Use the material's own guide once its ID number is known {tag}.",
    ]
    if mat.entry_point == "placard":
        out.append(
            "With several placards, the ERG says to start with the guide needing the "
            f"most protective action {tag}."
        )
    return out


def guide_key(number: str) -> str:
    """The pack key of an orange guide. The yellow index prints a P after the guide
    number of a material that may polymerize ("128P"); the guide page is the same as
    the number's (ERG p. 347: "Those substances designated with a (P) may polymerize
    explosively when heated or involved in a fire"), and the pack keys it without the
    P."""
    return number.rstrip("P")


def _coverage(un: str, erg: ErgData) -> str:
    """ "full": a seed material, with every pack's rows; "erg": every other ID number,
    with the ERG's rows (Tables 1-3, guide) and no 49 CFR 172.101, CAMEO or hazard class
    rows (those packs hold the seeds); "index_only": an ID the ERG pack holds no rows
    for (none since schema version 3, kept for a pack built otherwise)."""
    if un not in erg.materials:
        return "index_only"
    return "full" if un in erg.seed_un_numbers else "erg"


# ── Day and night ─────────────────────────────────────────────────────────────


def day_or_night(latitude: float, longitude: float, when: datetime) -> dict:
    """`period` ("day" or "night") at the point and time, with the sunrise and sunset
    that bracket it: for day, the sunrise before and the sunset after; for night, the
    sunset before and the sunrise after. Times are returned in `when`'s offset."""
    obs = Observer(latitude=latitude, longitude=longitude)
    t = when.astimezone(timezone.utc)
    events: list[tuple[datetime, str]] = []
    for d in (t.date() - timedelta(days=1), t.date(), t.date() + timedelta(days=1)):
        events += _event(sunrise, obs, d, "sunrise") + _event(sunset, obs, d, "sunset")
    events = sorted(set(events))
    before = [e for e in events if e[0] <= t]
    after = [e for e in events if e[0] > t]
    loc = basis(
        "day or night",
        f"{ERG} Table 1 how to use, sunrise and sunset by the NOAA solar equations",
        LOC_DAY_NIGHT,
    )
    if not before or not after:
        # Polar day or night: no sunrise or sunset near the time. Decided by the sun's
        # apparent elevation, which is what sunrise and sunset are thresholds of.
        up = elevation(obs, t) > 0
        return {
            "period": "day" if up else "night",
            "sunrise": None,
            "sunset": None,
            "note": "The sun neither rises nor sets near this time at this point; "
            "decided by the sun's elevation.",
            "basis": [loc],
        }
    last, nxt = before[-1], after[0]
    period = "day" if last[1] == "sunrise" else "night"
    rise, set_ = (last, nxt) if period == "day" else (nxt, last)
    return {
        "period": period,
        "sunrise": rise[0].astimezone(when.tzinfo).isoformat(timespec="seconds"),
        "sunset": set_[0].astimezone(when.tzinfo).isoformat(timespec="seconds"),
        "basis": [loc],
    }


def _event(fn, obs: Observer, d: date, name: str) -> list[tuple[datetime, str]]:
    try:
        return [(fn(obs, d, tzinfo=timezone.utc), name)]
    except ValueError:  # the sun does not cross the horizon that day (polar)
        return []


def period_word(period: str) -> str:
    """The vocabulary's word for the period in a source tag."""
    return {"day": "daytime", "night": "nighttime"}[period]


# ── Wind ──────────────────────────────────────────────────────────────────────


def wind_band(speed_kmh: float, bands: list[WindBand]) -> WindBand:
    by = {b.band: b for b in bands}
    if set(by) != {"low", "moderate", "high"}:
        raise RuntimeError(f"ERG pack wind bands are {sorted(by)}")
    if speed_kmh < by["low"].kmh_max:
        return by["low"]
    if speed_kmh > by["high"].kmh_min:
        return by["high"]
    return by["moderate"]


# ── Containers and tables ─────────────────────────────────────────────────────


def container_kinds(erg: ErgData) -> list[str]:
    """Every Table 3 container kind the pack carries."""
    kinds = {
        r.container for m in erg.materials.values() if m.table3 for r in m.table3.rows
    }
    return sorted(kinds)


def resolve_container(text: str, erg: ErgData) -> str | None:
    """A pack container kind (case ignored; a unique prefix such as "highway tank truck"
    is accepted), or None for "unknown"."""
    key = _norm_name(text)
    if key == "unknown":
        return None
    kinds = container_kinds(erg)
    exact = [k for k in kinds if k.lower() == key]
    prefix = [k for k in kinds if k.lower().startswith(key)]
    if exact or len(prefix) == 1:
        return (exact or prefix)[0]
    raise AssessmentError(
        f"{text!r} is not an {ERG} Table 3 container kind.",
        "Give one of the container kinds, or unknown.",
        container_kinds=kinds + ["unknown"],
    )


def _cell_unit_notes(isolate, protect) -> dict:
    """The unit note (`UnitNote`, HB-03c; null when none) of the two cells a table row
    gives the footprint, by the distance each one is."""
    return {
        "initial_isolation_distance": isolate.unit_note,
        "protective_action_distance": protect.unit_note,
    }


def _protect(spill, period: str) -> KmDistance:
    return spill.protect_day if period == "day" else spill.protect_night


def _table1_entry(
    mat: Material, large: bool, period: str, surface: str = "land"
) -> Table1Entry:
    """The named entry when the name was given and Table 1 lists it, else the entry
    with the largest distances (ERG p. 290), among the entries for the spill's surface.
    """
    entries = _resolved(
        surface_entries(mat, surface), "Table 1 row", "large" if large else "small"
    )
    if mat.matched_name:
        named = [
            e for e in entries if _norm_name(e.name) == _norm_name(mat.matched_name)
        ]
        if named:
            return named[0]

    def size(e: Table1Entry):
        s = e.large if large else e.small
        return (_protect(s, period).km, s.isolate.m)

    return max(entries, key=size)


#: ERG p. 30 Note 1 (and p. 336 Note 2): Table 1 prints a water-reactive material "(when
#: spilled in water)"; a material that is also TIH has a second entry "(when spilled on
#: land)"; one that has only the water entry is, on land, answered by its orange guide.
LOC_SPILLED_IN_WATER = f"{ERG_DOC}#p30"


def surface_entries(mat: Material, surface: str) -> list[Table1Entry]:
    """The Table 1 entries that apply on `surface` ("land" or "water"): on land every
    entry not printed "(when spilled in water)"; in water the water entries where Table
    1 prints any, else the entries without a qualifier (a TIH gas that is not
    water-reactive keeps its distances on water)."""
    t1 = mat.material.table1 if mat.material else []
    if surface == "water":
        water = [e for e in t1 if e.spilled_in == "water"]
        return water or [e for e in t1 if e.spilled_in is None]
    return [e for e in t1 if e.spilled_in != "water"]


def _resolved(entries: list, what: str, cell: str | None = None) -> list:
    """`entries`, refused when any is unresolved or (with `cell`, the spill size a
    Table 1 entry is read at) when that cell is null: the ranking and the reading must
    read the same cell (review L2-10)."""
    bad = [e for e in entries if e.unresolved]
    if cell is not None and any(getattr(e, cell) is None for e in entries):
        raise AssessmentError(
            f"The pack's {what} {cell} spill cell is null.",
            "Read the row from the ERG 2024 printed table; a Table 1 entry prints a "
            "distance for each spill size it answers.",
        )
    if bad:
        raise AssessmentError(
            f"The pack's {what} is unresolved: its three keyings disagree "
            f"({', '.join(sorted(set(f for e in bad for f in e.unresolved_fields)))}).",
            "Read the row from the ERG 2024 printed table; packs/build/UNRESOLVED.md "
            "lists the three readings.",
        )
    return entries


@dataclass(frozen=True)
class TableChoice:
    """Which ERG table gives the distances, and why."""

    table: str  # "Table 1", "Table 3", "guide"
    spill_size_used: str
    container: str | None
    reason: str
    also_guide_fire_distances: bool
    surface: str = "land"


def choose_table(
    mat: Material,
    spill: SpillSize,
    container: str | None,
    fire: bool,
    surface: str = "land",
) -> TableChoice:
    """The table the ERG sends this incident to, for a spill on `surface` ("land" or
    "water"). Raises AssessmentError for a Table 3 container the material's Table 3 does
    not list."""
    large = spill != SpillSize.SMALL
    used = "large" if large else "small"
    unknown_note = (
        " The spill size is unknown, so the large spill distances apply (the ERG's "
        "largest-distances rule)."
        if spill == SpillSize.UNKNOWN
        else ""
    )
    if mat.entry_point == "index_name":
        return TableChoice(
            "guide",
            used,
            container,
            f"Guide {mat.guide} EVACUATION distances: the yellow index gives this name "
            "no ID number, so Table 1 does not list it.",
            False,
            surface,
        )
    if not mat.identified:
        return TableChoice(
            "guide",
            used,
            container,
            f"Guide {mat.guide} EVACUATION distances: Table 1 needs the material, and "
            "it is not identified.",
            False,
            surface,
        )
    if not mat.entry.in_table1:
        return TableChoice(
            "guide",
            used,
            container,
            f"Guide {mat.guide} EVACUATION distances: {ERG} Table 1 does not list "
            f"{mat.id_number}.",
            False,
        )
    if mat.material is None:  # index_only: Table 1 lists it, no rows in the packs
        return TableChoice(
            "Table 1",
            used,
            container,
            f"{ERG} Table 1 lists {mat.id_number}, perhaps only for a spill in water "
            f"[{NOTE_1}]. Confirm the name in Table 1.",
            fire,
        )
    t1 = surface_entries(mat, surface)
    if not t1:
        return TableChoice(
            "guide",
            used,
            container,
            f"Guide {mat.guide} EVACUATION distances: Table 1 lists {mat.id_number} "
            "only for a spill in water. On land, neither Table 1 nor Table 2 applies "
            f"[{NOTE_1}].",
            False,
            surface,
        )
    refers = large and any(e.large_refer_to_table3 for e in t1)
    fire_note = (
        f" Fire is involved: Guide {mat.guide} EVACUATION distances also apply."
        if fire
        else ""
    )
    if refers:
        rows = [r.container for r in mat.material.table3.rows]
        if container is not None and container not in rows:
            raise AssessmentError(
                f"{ERG} Table 3 lists no {container!r} row for {mat.id_number}.",
                "Give one of this material's Table 3 containers, or unknown.",
                container_kinds=rows + ["unknown"],
            )
        which = (
            f", the {container.lower()} row."
            if container
            else ". The container is unknown, so the row with the largest distances "
            "applies."
        )
        return TableChoice(
            "Table 3",
            used,
            container,
            f"Large spill of {mat.id_number}: Table 1 refers to Table 3{which}"
            + unknown_note
            + fire_note,
            fire,
            surface,
        )
    water_note = (
        " Spilled in water: the Table 1 entry printed (when spilled in water)."
        if surface == "water" and any(e.spilled_in == "water" for e in t1)
        else ""
    )
    return TableChoice(
        "Table 1",
        used,
        container,
        f"{used.capitalize()} spill of {mat.id_number}: {ERG} Table 1."
        + water_note
        + unknown_note
        + fire_note,
        fire,
        surface,
    )


# ── Distances ─────────────────────────────────────────────────────────────────


def metric_text(d: MetricDistance) -> dict:
    return {
        "metres": d.m,
        "erg_units": d.model_dump(),
        "text": f"{d.m:,} m ({d.ft:,} ft)",
    }


def km_text(d: KmDistance) -> dict:
    p = "+" if d.plus else ""
    return {
        "metres": round(d.km * 1000),
        "erg_units": d.model_dump(),
        "text": f"{d.km:.1f}{p} km ({d.mi:.1f}{p} mi)",
        "can_be_larger": d.plus,
    }


def guide_text(d: GuideDistance) -> dict:
    return {
        "metres": d.m,
        "erg_units": d.model_dump(),
        "text": f"{d.m:,} m ({d.imperial})",
    }


def guide_distances(guide: ErgGuide, fire: bool) -> dict:
    """The orange guide's EVACUATION distances that apply: the immediate precautionary
    measure always (and its solids distance where the guide prints one), the fire
    distances when fire is involved, and the large spill distance as the guide states
    it, downwind (a distance, not a zone shape) or in all directions. `basis` maps each
    returned key to its basis entry, so a caller cites only what it uses."""
    ev = guide.evacuation
    loc = guide.sections["public_safety"].locator
    tag = f"{ERG} Guide {guide.guide}"
    out: dict = {"basis": {}}
    pairs = [
        (
            "immediate_precautionary",
            ev.immediate_precautionary,
            True,
            "immediate precautionary measure",
        ),
        (
            "immediate_precautionary_solids",
            ev.immediate_precautionary_solids,
            True,
            "immediate precautionary measure for solids",
        ),
        (
            "large_spill_downwind",
            ev.large_spill_downwind,
            True,
            "large spill downwind distance",
        ),
        (
            "large_spill_all_directions",
            ev.large_spill_all_directions,
            True,
            "large spill, consider evacuation in all directions",
        ),
        (
            "fire_isolate",
            ev.fire_isolate,
            fire,
            "isolate in all directions, tank in fire",
        ),
        (
            "fire_evacuate",
            ev.fire_evacuate,
            fire,
            "consider evacuation in all directions, tank in fire",
        ),
    ]
    for key, d, applies, supports in pairs:
        if applies and d is not None:
            out[key] = guide_text(d)
            out["basis"][key] = basis(supports, tag, loc)
    return out


def table_distances(
    mat: Material, choice: TableChoice, period: str, band: WindBand | None
) -> dict:
    """The isolation and protective action distances of the chosen Table 1 or Table 3
    row, with the row as a receipt. `band` is required for Table 3."""
    m = mat.material
    if choice.table == "Table 3":
        if band is None:
            raise ValueError("Table 3 needs a wind band")
        rows = _resolved(m.table3.rows, "Table 3 row")

        def size(r: Table3Row):
            d = getattr(r, period)
            return (getattr(d, band.band).km, r.isolate.m)

        row = (
            next(r for r in rows if r.container == choice.container)
            if choice.container
            else max(rows, key=size)
        )
        protect = getattr(getattr(row, period), band.band)
        tag = (
            f"{ERG} Table 3, {mat.id_number}, {row.container.lower()}, "
            f"{period_word(period)}, {band.label.lower()}"
        )
        return {
            "table": "Table 3",
            "row": {
                "heading": m.table3.heading,
                "container": row.container,
                "period": period,
                "wind_band": band.band,
                "locator": m.table3.locator,
                # HB-94 (review L5-7): how the row was keyed, and the unit note of each
                # cell used, so a consumer reads both without opening the pack
                "keyed_by": list(row.keyed_by),
                "unit_note": _cell_unit_notes(row.isolate, protect),
            },
            "container_chosen_as_largest": choice.container is None,
            "initial_isolation_distance": metric_text(row.isolate),
            "protective_action_distance": km_text(protect),
            "basis": [
                basis("initial isolation distance", tag, m.table3.locator),
                basis("protective action distance", tag, m.table3.locator),
            ],
        }
    large = choice.spill_size_used == "large"
    entry = _table1_entry(mat, large, period, choice.surface)
    spill = entry.large if large else entry.small
    tag = f"{ERG} Table 1, {mat.id_number}, {choice.spill_size_used} spill, " + (
        period_word(period)
    )
    return {
        "table": "Table 1",
        "row": {
            "name": entry.name,
            "printed_name": entry.printed_name,
            "spill_size": choice.spill_size_used,
            "period": period,
            "locator": entry.locator,
            # HB-94 (review L5-7), as Table 3's row
            "keyed_by": list(entry.keyed_by),
            "unit_note": _cell_unit_notes(spill.isolate, _protect(spill, period)),
        },
        "initial_isolation_distance": metric_text(spill.isolate),
        "protective_action_distance": km_text(_protect(spill, period)),
        "basis": [
            basis("initial isolation distance", tag, entry.locator),
            basis("protective action distance", tag, entry.locator),
        ],
    }


# ── Assessment ────────────────────────────────────────────────────────────────


def assess(
    packs: PackSet,
    material: str,
    container: str,
    latitude: float,
    longitude: float,
    incident_time: datetime,
    fire_involved: bool,
    spill_size: SpillSize,
    where_spilled: str = "land",
    *,
    guide_number: str | None = None,
    placard: str | None = None,
    resolved: Material | None = None,
) -> dict:
    """The `assess_incident` result, for a spill on `where_spilled` ("land" or
    "water"), for a `material`, or for an unidentified load by `guide_number` or
    `placard` (exactly one of the three). `resolved` (HB-18) is one candidate of an
    ambiguous input, assessed as given instead of resolving the three again. Raises
    AssessmentError for an input the ERG cannot answer as given."""
    erg = packs.erg.data
    mat = resolved or identify(erg, material, guide_number, placard)
    kind = resolve_container(container, erg)
    choice = choose_table(mat, spill_size, kind, fire_involved, where_spilled)
    dn = day_or_night(latitude, longitude, incident_time)
    if not mat.identified:
        return _assess_unidentified(
            packs,
            mat,
            kind,
            choice,
            dn,
            latitude,
            longitude,
            incident_time,
            fire_involved,
            spill_size,
            where_spilled,
        )
    index_loc = mat.entry.names[0].locator
    out_basis = [
        basis(
            "ID number, names and guide",
            f"{ERG} yellow index, {mat.id_number}",
            index_loc,
        ),
    ]
    guide = erg.guides.get(guide_key(mat.guide))
    if mat.entry.in_table1:
        out_basis.append(
            basis(
                "listed in Table 1",
                f"{ERG} Table 1, {mat.id_number}",
                mat.entry.table1_locator,
            )
        )
    if choice.also_guide_fire_distances:
        out_basis.append(
            basis(
                "fire with a Table 1 material",
                f"{ERG} yellow section introduction",
                LOC_FIRE_WITH_TABLE1,
            )
        )
    if spill_size != SpillSize.UNKNOWN:
        out_basis.append(
            basis("spill size", f"{ERG} Table 1 how to use", LOC_SPILL_SIZE)
        )
    out_basis += dn["basis"]

    result: dict = {
        "coverage": mat.coverage,
        "material": {
            "un_number": mat.un,
            "id_number": mat.id_number,
            "names": [n.name for n in mat.entry.names],
            "matched_name": mat.matched_name,
        },
        "guide": {"number": mat.guide, "title": guide.title if guide else None},
        "tih": mat.entry.in_table1,
        "incident": {
            "container": kind or "unknown",
            "location": {"latitude": latitude, "longitude": longitude},
            "incident_time": incident_time.isoformat(),
            "fire_involved": fire_involved,
            "spill_size": spill_size.value,
            "where_spilled": where_spilled,
        },
        "erg_table": {
            "table": choice.table,
            "spill_size_used": choice.spill_size_used,
            "container": choice.container,
            "also_guide_fire_distances": choice.also_guide_fire_distances,
            "reason": choice.reason,
        },
        "day_night": {k: v for k, v in dn.items() if k != "basis"},
        "pack_versions": {
            "erg": packs.erg.version,
            "cfr172": packs.cfr172.version,
            "cameo": packs.cameo.version,
            "hazard_classes": packs.hazard_classes.version,
        },
    }
    if mat.coverage == "index_only":
        result["hint"] = (
            "The packs carry ERG names, guide and Table 1 membership for every ID "
            "number, and full rows (distances, 49 CFR 172.101, CAMEO, hazard class "
            f"rule set) for the seed materials only: "
            f"{', '.join('UN' + u for u in erg.seed_un_numbers)}."
        )
        result["tih_note"] = (
            f"{ERG} Table 1 lists this ID number. Table 1 also lists water-reactive "
            "materials only for a spill in water (yellow section introduction, Note 1)."
            if mat.entry.in_table1
            else None
        )
        result["basis"] = out_basis
        return result
    if mat.coverage == "erg":
        # Stylebook form (HB-11: build_ics_201 prints it in Block 5): sentences of
        # at most 20 words, the numbers inside the source tag.
        seeds = ", ".join("UN" + u for u in erg.seed_un_numbers)
        result["limits"] = [
            "The packs carry every ID number's ERG rows: its Table 1, Table 2 and "
            "Table 3 entries and its guide. The hazmat table, CAMEO and hazard class "
            "rule set rows cover the seed materials only [49 CFR 172.101 Hazardous "
            f"Materials Table; seeds {seeds}]."
        ]
    if mat.material is not None and mat.material.where_spilled_matters:
        result["water_reactive"] = {
            "table2": [
                {"name": e.name, "gases": e.gases, "locator": e.locator}
                for e in mat.material.table2 or []
            ],
            "note": f"{ERG} Table 2 lists this material: spilled in water, it produces "
            "toxic inhalation hazard gases, and Table 1's entry for a spill in water "
            "applies (yellow section introduction, Note 1).",
        }
        out_basis.append(
            basis(
                "water-reactive material",
                f"{ERG} Table 2, {mat.id_number}",
                (mat.material.table2 or [None])[0].locator
                if mat.material.table2
                else None,
            )
        )

    hc = next(
        (c for c in packs.hazard_classes.data.classes if mat.un in c.members), None
    )
    result["hazard_class"] = (
        {"class_id": hc.class_id, "title": hc.title, "rule_set_id": hc.rule_set_id}
        if hc
        else None
    )
    cfr = packs.cfr172.data.materials.get(mat.un)
    result["cfr172"] = [
        {
            "description": r.description,
            "hazard_class": r.hazard_class,
            "label_codes": r.label_codes,
            "packing_group": r.packing_group,
            "symbols": r.symbols,
            "locator": r.locator,
        }
        for r in (cfr.rows if cfr else [])
    ]
    if cfr:
        out_basis.append(
            basis(
                "hazard class and label codes",
                f"49 CFR 172.101 Hazardous Materials Table, {mat.id_number}",
                cfr.rows[0].locator,
            )
        )
    cameo = packs.cameo.data.materials.get(mat.un)
    result["cameo_datasheets"] = [
        {"title": d.title, "doc_id": d.doc_id, "locator": d.locator}
        for d in (cameo.datasheets if cameo else [])
    ]
    if guide:
        out_basis.append(
            basis(
                "guide title",
                f"{ERG} Guide {mat.guide}",
                guide.sections["potential_hazards"].locator,
            )
        )
    result["basis"] = out_basis
    return result


def _incident_echo(
    kind, latitude, longitude, incident_time, fire_involved, spill_size, where_spilled
) -> dict:
    return {
        "container": kind or "unknown",
        "location": {"latitude": latitude, "longitude": longitude},
        "incident_time": incident_time.isoformat(),
        "fire_involved": fire_involved,
        "spill_size": spill_size.value,
        "where_spilled": where_spilled,
    }


def _assess_unidentified(
    packs: PackSet,
    mat: Material,
    kind: str | None,
    choice: TableChoice,
    dn: dict,
    latitude: float,
    longitude: float,
    incident_time: datetime,
    fire_involved: bool,
    spill_size: SpillSize,
    where_spilled: str,
) -> dict:
    """The `assess_incident` result for a load known only by its placard or a guide
    number (HB-15): the guide and how it was reached, no material, no Table 1, and
    `tih` None: whether Table 1 lists the load is not known."""
    guide = packs.erg.data.guides[guide_key(mat.guide)]
    out_basis = identity_basis(mat)
    if spill_size != SpillSize.UNKNOWN:
        out_basis.append(
            basis("spill size", f"{ERG} Table 1 how to use", LOC_SPILL_SIZE)
        )
    out_basis += dn["basis"]
    out_basis.append(
        basis(
            "guide title",
            f"{ERG} Guide {mat.guide}",
            guide.sections["potential_hazards"].locator,
        )
    )
    return {
        "coverage": mat.coverage,
        "material": None,
        "identified_by": identified_by(mat),
        "guide": {"number": mat.guide, "title": guide.title},
        "tih": None,
        "incident": _incident_echo(
            kind,
            latitude,
            longitude,
            incident_time,
            fire_involved,
            spill_size,
            where_spilled,
        ),
        "erg_table": {
            "table": choice.table,
            "spill_size_used": choice.spill_size_used,
            "container": choice.container,
            "also_guide_fire_distances": choice.also_guide_fire_distances,
            "reason": choice.reason,
        },
        "day_night": {k: v for k, v in dn.items() if k != "basis"},
        "pack_versions": {
            "erg": packs.erg.version,
            "cfr172": packs.cfr172.version,
            "cameo": packs.cameo.version,
            "hazard_classes": packs.hazard_classes.version,
        },
        "limits": unidentified_limits(mat),
        "hazard_class": None,
        "cfr172": [],
        "cameo_datasheets": [],
        "basis": out_basis,
    }
