"""material_response_guidance (HB-11): the orange guide for the material, by section,
read only from `ErgGuide.sections` in packs/erg.json (DN-006 section 3.2), every line
with its locator, selected by the incident (fire first, small or large spill, water).

The cases are the task's step 2: UN1017 highway tank truck large day (guide 124), UN1075
with fire (guide 115, fire first, the 1,600 m sentence), UN1746 small in water (guide
144, the Table 2 note), UN1203 (guide 128, no (P) sentence) against UN2055 (128P, the
(P) sentence kept), and the "General First Aid" reference every ERG 2024 guide prints.
"""

from __future__ import annotations

import pytest
import yaml
from fastmcp import Client, FastMCP

from hazbrief import stylecheck
from hazbrief.models import IncidentInput
from hazbrief.packs import default_packs
from hazbrief.tools import register_tools
from hazbrief.tools.material_response_guidance import guidance

SECTIONS = ("potential_hazards", "public_safety", "emergency_response")
I81 = {"latitude": 39.722, "longitude": -77.724}
DAY = "2026-10-21T14:00:00-04:00"


def incident(material: str, **kw) -> IncidentInput:
    return IncidentInput.model_validate(
        {
            "material": material,
            "container": kw.pop("container", "unknown"),
            "location": I81,
            "incident_time": DAY,
            "fire_involved": kw.pop("fire_involved", False),
            "spill_size": kw.pop("spill_size", "large"),
            **kw,
        }
    )


def pack_items(guide: str, section: str) -> list:
    return default_packs().erg.data.guides[guide].sections[section].items


def texts(r: dict, section: str) -> list[str]:
    return [i["text"] for i in r[section]]


def test_chlorine_large_day_is_guide_124_in_printed_order():
    r = guidance(incident("UN1017", container="highway tank truck"))
    assert r["guide"]["number"] == "124"
    assert r["order"] == list(SECTIONS)
    for section in SECTIONS:
        items = r[section]
        assert items, section
        for i in items:
            assert set(i) >= {"text", "page", "kind", "locator", "quotation"}
            assert i["quotation"] is True
            assert i["locator"] == f"erg2024-en-pdf#p{i['page']}"
    # printed order: the guide's own sequence, sub-headings kept as headings
    printed = [i.text for i in pack_items("124", "potential_hazards")]
    assert texts(r, "potential_hazards") == printed
    assert r["potential_hazards"][0] == {
        "text": "HEALTH",
        "page": 180,
        "kind": "heading",
        "locator": "erg2024-en-pdf#p180",
        "quotation": True,
    }
    # no fire: the guide's fire evacuation is left out, and the omission is stated
    assert not any("involved in a fire" in t for t in texts(r, "public_safety"))
    assert any(
        o["section"] == "public_safety" and o["heading"] == "Fire"
        for o in r["selection"]["omitted"]
    )


def test_every_line_is_the_guide_line_as_printed():
    """Every item is a pack item of the material's guide, word for word, on its page."""
    for m, kw in [
        ("UN1017", {}),
        ("UN1075", {"fire_involved": True}),
        ("UN1746", {"spill_size": "small", "where_spilled": "water"}),
        ("UN1203", {}),
        ("UN2055", {"fire_involved": True}),
    ]:
        r = guidance(incident(m, **kw))
        g = r["guide"]["pack_key"]
        for section in SECTIONS:
            printed = {(i.text, i.kind) for i in pack_items(g, section)}
            for i in r[section]:
                assert (i["text"], i["kind"]) in printed, (m, i["text"])


def test_propane_with_fire_puts_fire_first_and_isolates_1600_m():
    r = guidance(incident("UN1075", fire_involved=True))
    assert r["guide"]["number"] == "115"
    assert r["potential_hazards"][0]["text"] == "FIRE OR EXPLOSION"
    assert r["emergency_response"][0]["text"] == "FIRE"
    fire = [t for t in texts(r, "public_safety") if "1600 meters (1 mile)" in t]
    assert len(fire) == 1 and fire[0].startswith("If tank, rail tank car")


def test_fire_moves_the_fire_subsection_ahead_of_health():
    """Guide 124 prints HEALTH first (its primary hazard); fire puts FIRE OR EXPLOSION
    first and keeps every line of both subsections."""
    plain = guidance(incident("UN1017"))
    fire = guidance(incident("UN1017", fire_involved=True))
    assert plain["potential_hazards"][0]["text"] == "HEALTH"
    assert fire["potential_hazards"][0]["text"] == "FIRE OR EXPLOSION"
    assert sorted(texts(plain, "potential_hazards")) == sorted(
        texts(fire, "potential_hazards")
    )


def test_bromine_trifluoride_small_in_water_carries_the_table_2_note():
    r = guidance(incident("UN1746", spill_size="small", where_spilled="water"))
    assert r["guide"]["number"] == "144"
    note = r["table2_note"]
    assert note["locator"] == "erg2024-en-pdf#p338"
    assert "hydrogen fluoride" in note["text"].lower()
    assert "bromine" in note["text"].lower()
    assert stylecheck.check(note["text"]) == []
    er = texts(r, "emergency_response")
    assert "Small Spill" in er and "Large Spill" not in er
    assert any(t.startswith("Cover with DRY earth") for t in er)
    assert not any(t.startswith("DO NOT CLEAN-UP") for t in er)
    assert any(
        o["heading"] == "Large Spill" and o["reason"].startswith("spill_size")
        for o in r["selection"]["omitted"]
    )


def test_on_land_there_is_no_table_2_note():
    r = guidance(incident("UN1746", spill_size="small"))
    assert r["table2_note"] is None


def test_water_changes_nothing_for_a_material_table_2_does_not_list():
    r = guidance(incident("UN1203", where_spilled="water"))
    assert r["table2_note"] is None
    assert any("Table 2 does not list" in x for x in r["limits"])


def test_large_spill_drops_the_small_spill_lines():
    r = guidance(incident("UN1746", spill_size="large", where_spilled="water"))
    er = texts(r, "emergency_response")
    assert "Large Spill" in er and "Small Spill" not in er


def test_unknown_spill_size_keeps_both_and_says_so():
    r = guidance(incident("UN1746", spill_size="unknown"))
    er = texts(r, "emergency_response")
    assert "Small Spill" in er and "Large Spill" in er
    assert any("spill size is unknown" in x for x in r["limits"])


def test_gasoline_prints_no_p_sentence_and_styrene_does():
    """The (P) sentence holds only for a material whose guide number carries the P (ERG
    p. 347; HB-12b section 4)."""
    p = "Those substances designated with a (P)"
    gasoline = guidance(incident("UN1203"))
    styrene = guidance(incident("UN2055"))
    assert gasoline["guide"]["number"] == "128"
    assert styrene["guide"]["number"] == "128P"
    assert not any(p in t for t in texts(gasoline, "potential_hazards"))
    assert any(p in t for t in texts(styrene, "potential_hazards"))
    assert any(
        o["reason"].startswith("the guide number carries no P")
        for o in gasoline["selection"]["omitted"]
    )


def test_general_first_aid_is_referred_to_with_its_page():
    """ERG 2024 moved first aid to its General First Aid section (LN-02); each guide
    prints "Refer to the "General First Aid" section." (pp. 150-152)."""
    r = guidance(incident("UN1203"))
    assert r["general_first_aid"] == {
        "refer": True,
        "locator": "erg2024-en-pdf#p152",
        "title": "General First Aid",
    }
    assert any("General First Aid" in t for t in texts(r, "emergency_response"))


def test_the_app_link_is_not_here():
    """SB-STR-09: the verify_in_erg_app link goes with the map, in the ICS 201."""
    r = guidance(incident("UN1017"))
    assert "verify_in_erg_app" not in r


def test_basis_and_limits_are_in_stylebook_form():
    for m, kw in [
        ("UN1017", {}),
        ("UN1746", {"spill_size": "unknown", "where_spilled": "water"}),
        ("UN1203", {"where_spilled": "water"}),
    ]:
        r = guidance(incident(m, **kw))
        assert r["basis"] and all(b["tag"].startswith("[") for b in r["basis"])
        for sentence in r["limits"]:
            assert stylecheck.check(sentence) == [], sentence


def test_an_unknown_material_returns_the_hint():
    r = guidance(incident("chlorin"))
    assert "error" in r and "Chlorine" in r["nearest_index_names"]


def test_the_config_names_every_key_it_needs(tmp_path):
    from hazbrief import ics201

    cfg = yaml.safe_load(ics201.CONFIG_FILE.read_text(encoding="utf-8"))
    del cfg["guidance"]["general_first_aid"]
    bad = tmp_path / "ics201.yaml"
    bad.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    with pytest.raises(ics201.ConfigError, match="general_first_aid"):
        ics201.load_config(bad)


async def test_registration_through_register_tools():
    mcp = FastMCP("test")
    register_tools(mcp)
    async with Client(mcp) as client:
        names = {t.name for t in await client.list_tools()}
        assert "material_response_guidance" in names
        result = await client.call_tool(
            "material_response_guidance",
            {"incident": incident("UN1017").model_dump(mode="json")},
        )
    assert result.data["guide"]["number"] == "124"


def test_every_table2_note_passes_the_stylebook():
    """HB-05 F-2: the Table 2 note names the material when the sentence fits SB-SEN-01,
    else its ID number (UN3507's name alone is 16 words)."""
    erg = default_packs().erg.data
    notes = {}
    for un, m in erg.materials.items():
        if not m.table2:
            continue
        r = guidance(incident(f"UN{un}", where_spilled="water"))
        if "error" in r:
            continue
        notes[un] = r["table2_note"]["text"]
    assert len(notes) > 80
    assert {un: t for un, t in notes.items() if stylecheck.check(t)} == {}
    assert notes["3507"].startswith("UN3507 produces Hydrogen fluoride")
    assert notes["1340"].startswith("Phosphorus pentasulfide, free from yellow")
