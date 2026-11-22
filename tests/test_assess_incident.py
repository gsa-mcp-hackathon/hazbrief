"""HB-08: `assess_incident` resolves materials, containers, tables and day or night.

All offline: the tool reads only the shipped packs and calculates sunrise and sunset.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from astral import Observer
from astral.sun import sunrise, sunset
from fastmcp import Client, FastMCP

from hazbrief.incident import day_or_night
from hazbrief.models import IncidentInput
from hazbrief.packs import default_packs
from hazbrief.tools import register_tools
from hazbrief.tools.assess_incident import run

ERG = default_packs().erg.data
SEEDS = ERG.seed_un_numbers
#: The I-81 scenario point (fixtures/scenario_points.yaml).
I81 = (39.722, -77.724)
DAY = "2026-10-21T14:00:00-04:00"


def incident(material: str, **kw) -> IncidentInput:
    lat, lon = kw.pop("location", I81)
    return IncidentInput.model_validate(
        {
            "material": material,
            "container": kw.pop("container", "unknown"),
            "location": {"latitude": lat, "longitude": lon},
            "incident_time": kw.pop("incident_time", DAY),
            "fire_involved": kw.pop("fire_involved", False),
            "spill_size": kw.pop("spill_size", "large"),
            **kw,
        }
    )


@pytest.mark.parametrize("un", SEEDS)
def test_every_seed_material_resolves_in_full(un):
    r = run(incident(f"UN{un}"))
    assert "error" not in r, r
    assert r["coverage"] == "full"
    assert r["material"]["un_number"] == un
    assert r["guide"]["number"] == ERG.materials[un].guide
    assert r["guide"]["title"] == ERG.guides[ERG.materials[un].guide].title
    assert r["tih"] is ERG.materials[un].tih
    assert r["hazard_class"]["rule_set_id"].startswith("rules.")
    assert r["cfr172"] and all(row["label_codes"] for row in r["cfr172"])
    assert r["cameo_datasheets"]
    assert all(b["tag"].startswith("[") and b["tag"].endswith("]") for b in r["basis"])


@pytest.mark.parametrize("un", SEEDS)
def test_un_and_name_forms_agree(un):
    by_un = run(incident(f"UN{un}"))
    for form in (un, f"un {un}", f"UN-{un}"):
        assert run(incident(form))["material"] == by_un["material"]
    keys = ("coverage", "guide", "tih", "hazard_class", "cfr172", "erg_table")
    for n in ERG.materials[un].names:
        if len(ERG.name_index[n.name.lower()]) > 1:
            continue  # an ambiguous name; see the propane test
        by_name = run(incident(n.name.upper()))
        assert by_name["material"]["matched_name"] == n.name
        assert {k: by_name[k] for k in keys} == {k: by_un[k] for k in keys}


def test_a_name_under_two_id_numbers_asks_for_the_id_number():
    """Propane is UN1075 and UN1978 in the yellow index: the ERG identifies by ID
    number, so the tool asks for it rather than choose."""
    r = run(incident("Propane"))
    assert "error" in r and r["candidates"] == ["UN1075", "UN1978"]
    assert "ID number" in r["hint"]


def test_an_unknown_name_returns_the_nearest_index_names():
    r = run(incident("chlorin"))
    assert "error" in r and "hint" in r
    assert r["nearest_index_names"][0] == "Chlorine"
    assert "coverage" not in r


def test_an_unknown_id_number_is_refused_with_a_hint():
    r = run(incident("UN9999"))
    assert "UN9999" in r["error"] and "placard" in r["hint"]


def test_an_id_under_several_guides_asks_for_the_name():
    un = next(u for u, e in ERG.index.items() if len({n.guide for n in e.names}) > 1)
    r = run(incident(un))
    assert "error" in r and len(r["candidates"]) == len(ERG.index[un].names)


def test_a_material_outside_the_seeds_resolves_with_its_erg_rows():
    """HB-03b: every ID number carries its ERG rows. UN1162 is listed in Table 1 only
    "(when spilled in water)", so on land its guide answers (ERG p. 30 Note 1); UN1993
    is not in Table 1. Neither is a seed, so no CFR, CAMEO or hazard class rows."""
    r = run(incident("UN1162"))
    assert r["coverage"] == "erg" and r["tih"] is True
    assert r["guide"]["number"] == "155" and r["guide"]["title"]
    assert r["erg_table"]["table"] == "guide"
    assert "only for a spill in water" in r["erg_table"]["reason"]
    assert r["water_reactive"]["table2"][0]["gases"] == ["HCl"]
    assert (
        r["hazard_class"] is None and r["cfr172"] == [] and r["cameo_datasheets"] == []
    )
    assert "seed materials only" in r["limits"][0]
    r = run(incident("1993"))
    assert r["coverage"] == "erg" and r["tih"] is False
    assert r["erg_table"]["table"] == "guide"


def test_a_non_seed_tih_material_answers_from_table1():
    r = run(incident("UN1076", spill_size="small"))  # Phosgene
    assert r["coverage"] == "erg" and r["erg_table"]["table"] == "Table 1"


def test_container_kinds_resolve_case_and_prefix():
    r = run(incident("UN1017", container="HIGHWAY TANK TRUCK"))
    assert r["incident"]["container"] == "Highway tank truck or trailer"
    r = run(incident("UN1017", container="tanker"))
    assert "error" in r and "unknown" in r["container_kinds"]


def test_a_container_the_materials_table3_lacks_is_refused():
    r = run(incident("UN1017", container="Agricultural nurse tank"))
    assert "error" in r and "Rail tank car" in r["container_kinds"]


@pytest.mark.parametrize(
    ("material", "spill", "fire", "table", "used", "also_fire"),
    [
        ("UN1017", "small", False, "Table 1", "small", False),
        ("UN1017", "large", False, "Table 3", "large", False),
        ("UN1017", "unknown", False, "Table 3", "large", False),
        ("UN1017", "large", True, "Table 3", "large", True),
        ("UN1203", "large", False, "guide", "large", False),
        ("UN1075", "small", True, "guide", "small", False),
    ],
)
def test_which_erg_table_applies(material, spill, fire, table, used, also_fire):
    r = run(incident(material, spill_size=spill, fire_involved=fire))
    t = r["erg_table"]
    assert (t["table"], t["spill_size_used"], t["also_guide_fire_distances"]) == (
        table,
        used,
        also_fire,
    )


def test_day_and_night_either_side_of_sunrise():
    """Within the hour of sunrise at the I-81 point, on both sides of it."""
    lat, lon = I81
    when = datetime.fromisoformat("2026-10-21T00:00:00-04:00")
    rise = sunrise(Observer(lat, lon), when.date(), tzinfo=when.tzinfo)
    before, after = rise - timedelta(minutes=20), rise + timedelta(minutes=20)
    assert day_or_night(lat, lon, before)["period"] == "night"
    assert day_or_night(lat, lon, after)["period"] == "day"
    for t in (before, after):
        r = run(incident("UN1017", incident_time=t.isoformat()))
        reported = datetime.fromisoformat(r["day_night"]["sunrise"])
        assert abs(reported - rise) < timedelta(seconds=1)


def test_day_and_night_either_side_of_sunset_and_across_utc_midnight():
    """A Pacific evening is after midnight UTC: the period is still the local one."""
    lat, lon = 34.05, -118.25
    when = datetime.fromisoformat("2026-10-21T12:00:00-07:00")
    set_ = sunset(Observer(lat, lon), when.date(), tzinfo=when.tzinfo)
    assert day_or_night(lat, lon, set_ - timedelta(minutes=10))["period"] == "day"
    assert day_or_night(lat, lon, set_ + timedelta(minutes=10))["period"] == "night"
    utc_next_day = (set_ - timedelta(minutes=10)).astimezone(timezone.utc)
    assert utc_next_day.date() > when.date()
    assert day_or_night(lat, lon, utc_next_day)["period"] == "day"


def test_polar_day_and_night_are_decided_by_the_sun():
    """Utqiagvik, Alaska: no sunrise or sunset at midsummer or midwinter."""
    summer = day_or_night(
        71.29, -156.79, datetime.fromisoformat("2026-06-21T00:00-08:00")
    )
    winter = day_or_night(
        71.29, -156.79, datetime.fromisoformat("2026-12-21T12:00-09:00")
    )
    assert (summer["period"], summer["sunrise"]) == ("day", None)
    assert (winter["period"], winter["sunset"]) == ("night", None)


def test_no_output_writes_plume():
    """DN-001 section 4 invariant 1."""
    for m in ["UN1017", "UN1203", "UN1162", "Propane", "chlorin"]:
        assert "plume" not in json.dumps(run(incident(m))).lower()


def test_an_input_without_a_utc_offset_is_rejected():
    with pytest.raises(ValueError):
        incident("UN1017", incident_time="2026-10-21T14:00:00")


async def test_registration_through_register_tools():
    mcp = FastMCP("test")
    register_tools(mcp)
    async with Client(mcp) as client:
        names = {t.name for t in await client.list_tools()}
        assert {"assess_incident", "protective_action_footprint"} <= names
        result = await client.call_tool(
            "assess_incident",
            {"incident": incident("UN1017").model_dump(mode="json")},
        )
    assert result.data["guide"]["number"] == "124"


def test_a_p_designated_guide_carries_its_guide_title():
    """HB-11 found: the pack keys orange guides without the P the yellow index prints
    (128P is guide 128's page, ERG p. 347), so a P material's guide title was null."""
    r = run(incident("UN2055"))
    assert r["guide"]["number"] == "128P"
    assert r["guide"]["title"] == "Flammable Liquids (Water-Immiscible)"


def test_every_limits_sentence_passes_the_stylebook():
    """HB-11: build_ics_201 prints every tool's `limits` in Block 5."""
    from hazbrief import stylecheck

    for m in ("UN1162", "1993"):
        for sentence in run(incident(m))["limits"]:
            assert stylecheck.check(sentence) == [], sentence


# ── HB-15 step 2 (F-2): the reason sentences are stylebook sentences ────────


def test_every_table_choice_reason_passes_the_stylebook():
    """`erg_table.reason` is not printed by build_ics_201, but a client narrates it, so
    it is written to the stylebook like every sentence the server drafts (HB-05 F-2).
    Every branch of choose_table, for every ID number, surface, spill size, fire and
    Table 3 container."""
    from hazbrief import stylecheck
    from hazbrief.incident import AssessmentError, choose_table, resolve_material
    from hazbrief.models import SpillSize

    reasons = set()
    for un, m in ERG.materials.items():
        try:
            mat = resolve_material(un, ERG)
        except AssessmentError:  # listed under several guides: the name is asked
            continue
        containers = [None] + ([r.container for r in m.table3.rows] if m.table3 else [])
        for size in SpillSize:
            for fire in (False, True):
                for surface in ("land", "water"):
                    for c in containers:
                        reasons.add(choose_table(mat, size, c, fire, surface).reason)
    bad = {r: [f.rule for f in stylecheck.check(r)] for r in reasons}
    assert not {r: f for r, f in bad.items() if f}
    assert len(reasons) > 2000  # every branch was reached, not a handful


@pytest.mark.parametrize("size", ["small", "large"])
def test_a_table_1_entry_with_a_null_cell_is_refused_not_read(size):
    """No shipped entry has a null cell its spill size reads (every `large: null`
    refers to Table 3), but the ranking fell back to the small cell where the large
    was null, and `table_distances` then read the null one (review L2-10). A null cell
    is refused like an unresolved row."""
    import dataclasses

    from hazbrief.incident import (
        AssessmentError,
        TableChoice,
        resolve_material,
        table_distances,
    )

    mat = resolve_material("UN1017", ERG)
    entries = [e.model_copy(update={size: None}) for e in mat.material.table1]
    mat = dataclasses.replace(
        mat, material=mat.material.model_copy(update={"table1": entries})
    )
    choice = TableChoice("Table 1", size, None, "test", False)
    with pytest.raises(AssessmentError, match=f"{size} spill cell is null"):
        table_distances(mat, choice, "day", None)


#: Values that would start a new Markdown line, or carry a terminal escape, in a form
#: whose preamble says no model wrote any sentence (review L3-6).
INJECTED = ["Chlorine\n# Fake heading", "Chlorine\r\n- [source]", "a\tb", "x\x1b[31m"]


@pytest.mark.parametrize("value", INJECTED)
@pytest.mark.parametrize("field", ["material", "container", "placard", "guide_number"])
def test_a_free_text_incident_field_refuses_control_characters(field, value):
    from pydantic import ValidationError

    kw = {field: value}
    if field in ("placard", "guide_number"):
        kw["material"] = None
    with pytest.raises(ValidationError, match="control character"):
        incident(kw.pop("material", "UN1017"), **kw)


@pytest.mark.parametrize("value", INJECTED)
def test_a_wind_source_refuses_control_characters(value):
    from pydantic import ValidationError

    from hazbrief.models import WindObservation

    with pytest.raises(ValidationError, match="control character"):
        WindObservation(
            speed_kmh=13,
            direction_deg_from=270,
            observed_at=DAY,
            source=value,
        )


def test_free_text_is_stripped_and_blank_after_stripping_is_refused():
    from pydantic import ValidationError

    assert incident("  UN1017  ", container=" unknown ").material == "UN1017"
    assert incident("UN1017", container=" unknown ").container == "unknown"
    with pytest.raises(ValidationError):
        incident("   ")
