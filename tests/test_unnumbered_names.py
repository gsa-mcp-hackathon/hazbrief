"""HB-17 residual 4: explosives by name. The ERG's yellow index prints four rows with
no ID number (ERG 2024 PDF p. 31): "Ammonium nitrate-fuel oil mixtures", "Blasting
agent, n.o.s." and "Explosives, division 1.1, 1.2, 1.3 or 1.5" under Guide 112, and
"Explosives, division 1.4 or 1.6" under Guide 114. Note 2 (p. 30): "Explosives are
not individually listed by their ID number". HB-15 premise 1 found the pack dropped
them; they now enter `material` resolution.

Two name rules, both sourced and neither a guess:

* an index name ending ", n.o.s." also answers to the name without it (the ERG
  glossary: the letters mark a generic name, "Corrosive liquid, n.o.s."); an exact
  name wins, and several matches are refused with the candidates, the resolver's
  ambiguity rule unchanged;
* "ANFO" is the term 49 CFR 173.59 prints for the ammonium nitrate-fuel oil mixture,
  and the pack carries that sentence with its locator; the build checks it against
  the held XML.
"""

from __future__ import annotations

import pytest

from hazbrief import stylecheck
from hazbrief.incident import AssessmentError, identify, resolve_material
from hazbrief.models import IncidentInput, WindObservation
from hazbrief.packs import default_packs
from hazbrief.tools import protective_action_footprint as paf
from hazbrief.tools.assess_incident import run
from hazbrief.tools.material_response_guidance import guidance

ERG = default_packs().erg.data
I81 = {"latitude": 39.722, "longitude": -77.724}
DAY = "2026-10-21T14:00:00-04:00"
WEST_13 = WindObservation.model_validate(
    {
        "direction_deg_from": 270,
        "speed_kmh": 13,
        "observed_at": "2026-10-20T13:40:00-04:00",
        "source": "worked example wind",
    }
)


def incident(material: str, **kw) -> IncidentInput:
    return IncidentInput.model_validate(
        {
            "material": material,
            "container": "unknown",
            "location": I81,
            "incident_time": DAY,
            "fire_involved": kw.pop("fire_involved", False),
            "spill_size": kw.pop("spill_size", "unknown"),
            **kw,
        }
    )


def test_the_pack_holds_the_four_rows_with_no_id_number():
    rows = {r.name: r for r in ERG.unnumbered}
    assert {n: r.guide for n, r in rows.items()} == {
        "Ammonium nitrate-fuel oil mixtures": "112",
        "Blasting agent, n.o.s.": "112",
        "Explosives, division 1.1, 1.2, 1.3 or 1.5": "112",
        "Explosives, division 1.4 or 1.6": "114",
    }
    for r in rows.values():
        assert r.locator == "erg2024-en-pdf#p31"
        assert r.keyed_by == ["A", "B", "C"]
        assert r.note.locator == "erg2024-en-pdf#p30"
        assert "Explosives are not individually listed" in r.note.quote
    (anfo,) = rows["Ammonium nitrate-fuel oil mixtures"].aliases
    assert anfo.alias == "ANFO"
    assert anfo.locator == "cfr49-govinfo-bulk#173.59"
    assert "(ANFO)" in anfo.quote


@pytest.mark.parametrize(
    "text, name, guide",
    [
        ("Blasting agent, n.o.s.", "Blasting agent, n.o.s.", "112"),
        ("blasting agent", "Blasting agent, n.o.s.", "112"),
        ("ANFO", "Ammonium nitrate-fuel oil mixtures", "112"),
        ("anfo", "Ammonium nitrate-fuel oil mixtures", "112"),
        (
            "Ammonium nitrate-fuel oil mixtures",
            "Ammonium nitrate-fuel oil mixtures",
            "112",
        ),
        ("Explosives, division 1.4 or 1.6", "Explosives, division 1.4 or 1.6", "114"),
    ],
)
def test_an_explosive_by_name_resolves_to_its_guide_with_the_page(text, name, guide):
    out = run(incident(text))
    assert "error" not in out, out
    assert out["guide"]["number"] == guide
    assert out["coverage"] == "unnumbered"
    assert out["material"] is None and out["tih"] is None
    ib = out["identified_by"]
    assert (ib["entry_point"], ib["name"], ib["guide"], ib["locator"]) == (
        "index_name",
        name,
        guide,
        "erg2024-en-pdf#p31",
    )
    assert ib["alias"] == ("ANFO" if text.lower() == "anfo" else None)
    assert out["basis"][0]["locator"] == "erg2024-en-pdf#p31"
    assert out["erg_table"]["table"] == "guide"
    for s in out["limits"] + [out["erg_table"]["reason"]]:
        assert stylecheck.check(s) == [], s


def test_the_alias_basis_cites_49_cfr():
    out = run(incident("ANFO"))
    cfr = [b for b in out["basis"] if b["locator"] == "cfr49-govinfo-bulk#173.59"]
    assert cfr, out["basis"]


def test_every_nos_name_answers_without_its_suffix():
    """ERG 2024 prints 392 names ending ", n.o.s."; the name without it is printed
    under no other ID, so each resolves to its own ID number."""
    nos = [k for k in ERG.name_index if k.endswith(", n.o.s.")]
    assert len(nos) >= 300
    for key in nos:
        mat = resolve_material(key[: -len(", n.o.s.")], ERG)
        assert [mat.un] == ERG.name_index[key], key


def test_an_exact_name_wins_over_the_nos_rule_and_several_are_refused():
    exact = ERG.model_copy(
        update={"name_index": ERG.name_index | {"ammonia, anhydrous, n.o.s.": ["3511"]}}
    )
    assert resolve_material("Ammonia, anhydrous", exact).un == "1005"
    several = ERG.model_copy(
        update={
            "name_index": ERG.name_index | {"adsorbed gas, n.o.s.": ["3510", "3511"]}
        }
    )
    with pytest.raises(AssessmentError) as e:
        resolve_material("Adsorbed gas", several)
    assert e.value.detail["candidates"] == ["UN3510", "UN3511"]


def test_an_unknown_name_is_still_refused():
    with pytest.raises(AssessmentError):
        identify(ERG, material="dynamite")


async def test_the_footprint_draws_guide_112_and_says_why_there_is_no_table_1():
    out = await paf.footprint(incident("ANFO", spill_size="large"), WEST_13)
    assert "error" not in out, out
    assert out["erg_table"]["table"] == "guide"
    assert out["zones"]["initial_isolation_zone"]["distance"]["metres"] == 500
    assert out["zones"]["large_spill_evacuation"]["distance"]["metres"] == 800
    assert out["verify_in_erg_app"] is None
    assert paf.NO_ID_TABLE1_LIMIT in out["limits"]
    assert paf.LINK_NO_ID_LIMIT in out["limits"]
    assert paf.UNIDENTIFIED_TABLE1_LIMIT not in out["limits"]
    assert out["identified_by"]["entry_point"] == "index_name"
    for s in out["limits"]:
        assert stylecheck.check(s) == [], s


def test_the_guidance_is_guide_112s():
    out = guidance(incident("blasting agent", where_spilled="water"))
    assert out["guide"]["number"] == "112"
    assert out["material"] is None
    assert out["identified_by"]["name"] == "Blasting agent, n.o.s."
    assert not any("not identified" in s for s in out["limits"])
    for s in out["limits"]:
        assert stylecheck.check(s) == [], s


async def test_the_briefing_names_the_explosive_and_why_its_guide_applies():
    """Block 1 names the row, Block 5 says how the name reached Guide 112 (the yellow
    index page, the 49 CFR term for the alias, the ERG's note), and Block 4 says why
    there is no ERG app link. Population and facilities are not recorded for this
    footprint; their tools' errors are the form's business, not this test's."""
    from hazbrief.models import Ics201Input
    from hazbrief.tools.build_ics_201 import assemble

    r = await assemble(
        Ics201Input.model_validate(
            {
                "incident": {
                    "material": "ANFO",
                    "container": "unknown",
                    "location": I81,
                    "incident_time": DAY,
                    "fire_involved": False,
                    "spill_size": "unknown",
                },
                "wind": WEST_13.model_dump(mode="json"),
            }
        )
    )
    blocks = {b["number"]: b for b in r["blocks"]}
    assert blocks[1]["sections"][0]["sentences"][0]["text"].startswith(
        "Ammonium nitrate-fuel oil mixtures release, "
    )
    five = [s["text"] for sec in blocks[5]["sections"] for s in sec["sentences"]]
    assert (
        "The material is Ammonium nitrate-fuel oil mixtures, ERG 2024 Guide 112 "
        "[ERG 2024 yellow index, PDF p. 31]." in five
    )
    assert "ANFO, as reported, is this mixture's abbreviation [49 CFR 173.59]." in five
    assert (
        "The ERG lists explosives by division, not by ID number, so Guide 112's "
        "distances apply [ERG 2024 yellow index, Note 2, PDF p. 30]." in five
    )
    assert not any("not identified" in t for t in five)
    four = [s["text"] for sec in blocks[4]["sections"] for s in sec["sentences"]]
    assert (
        "No ERG app link: the app draws a material by ID number, and this one has none."
        in four
    )
    for t in five + four:
        assert stylecheck.check(t) == [], t
