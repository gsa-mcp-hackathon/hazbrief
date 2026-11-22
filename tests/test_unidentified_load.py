"""HB-15 step 1 (F-3): the unidentified load. A first-arriving unit often has a placard
and no ID number, or no paperwork at all; the ERG answers that with its Table of
Markings, Labels and Placards and Initial Response Guide (ERG 2024 PDF pp. 10-11,
printed pp. 8-9) and guides 111, 112 and 114, which no yellow-index ID number names.

`IncidentInput` takes, instead of `material`, a `guide_number` or a `placard` (the
class or division as printed, a placard word, DANGEROUS, or none). The known answers
below were read from the rendered pages and the ERG's own prose (pp. 3, 9) before the
code was written; the keying tests skip where the held PDF is absent, as HB-03b's do.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from hazbrief import stylecheck
from hazbrief.incident import AssessmentError, identify
from hazbrief.models import IncidentInput, WindObservation
from hazbrief.packs import default_packs
from hazbrief.tools.assess_incident import run
from hazbrief.tools.material_response_guidance import guidance
from hazbrief.tools.protective_action_footprint import footprint

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
PDF = REPO / "corpus" / "raw" / "erg2024-en-pdf.pdf"
KEY_B = REPO / "packs" / "src" / "erg_placards_keyB.yaml"
needs_pdf = pytest.mark.skipif(not PDF.is_file(), reason="corpus/raw/ ERG PDF absent")

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


def incident(**kw) -> IncidentInput:
    return IncidentInput.model_validate(
        {
            "container": kw.pop("container", "unknown"),
            "location": kw.pop("location", I81),
            "incident_time": DAY,
            "fire_involved": kw.pop("fire_involved", False),
            "spill_size": kw.pop("spill_size", "unknown"),
            **kw,
        }
    )


# ── The placard table: the pack and its keying ─────────────────────────────


#: Read by eye from the rendered spread and, where marked, stated in the ERG's prose.
KNOWN = {
    "DANGEROUS": "111",  # p. 9: "Use GUIDE 111 when the DANGER or DANGEROUS placard"
    "DANGER": "111",
    "none": "111",  # p. 9: "... but no placards can be seen."
    "1.1": "112",  # p. 3: "For Divisions 1.1, 1.2, 1.3, or 1.5 Use GUIDE 112"
    "1.5": "112",
    "BLASTING AGENTS": "112",
    "1.4": "114",  # p. 3: "For Divisions 1.4 or 1.6 Use GUIDE 114"
    "1.6": "114",
    "2.1": "118",
    "FLAMMABLE GAS": "118",
    "2.2": "120",
    "NON-FLAMMABLE GAS": "120",
    "2.3": "123",
    "OXYGEN": "122",
    "3": "127",  # p. 9: "Use GUIDE 127 for a FLAMMABLE (Class 3) placard"
    "COMBUSTIBLE": "127",
    "GASOLINE": "128",
    "FUEL OIL": "128",
    "4.1": "134",
    "4.2": "136",
    "4.3": "139",
    "DANGEROUS WHEN WET": "139",
    "5.1": "143",
    "5.2": "148",
    "6.1": "153",
    "POISON": "153",
    "6.2": "158",
    "7": "163",
    "8": "153",  # p. 9: "Use GUIDE 153 for a CORROSIVE (Class 8) placard"
    "CORROSIVE": "153",
    "9": "171",
    "LITHIUM ION BATTERIES": "147",
    "LITHIUM METAL BATTERIES": "138",
}


@pytest.mark.parametrize("placard,guide", sorted(KNOWN.items()))
def test_every_known_placard_resolves_to_its_guide(placard, guide):
    mat = identify(ERG, placard=placard)
    assert mat.guide == guide
    assert mat.un is None and mat.coverage == "unidentified"
    assert mat.placard.locator in ("erg2024-en-pdf#p10", "erg2024-en-pdf#p11")


def test_the_pack_rows_are_keyed_by_both_keys():
    rows = ERG.placards
    assert len(rows) == len(yaml.safe_load(KEY_B.read_text())["placards"])
    for r in rows:
        assert set(r.keyed_by) == {"A", "B"}, r.placard
        assert not r.unresolved and r.guide in ERG.guides
    prose = {r.placard for r in rows if r.association == "prose"}
    assert prose == {
        "DANGEROUS",
        "none",
        "1.1",
        "1.2",
        "1.3",
        "1.4",
        "1.5",
        "1.6",
        "3",
        "8",
    }


@pytest.mark.parametrize(
    "text,want",
    [
        ("class 2.3", "123"),
        ("Division 1.4", "114"),
        ("non flammable gas", "120"),
        ("  dangerous  ", "111"),
        ("NONE", "111"),
    ],
)
def test_placard_input_is_read_case_and_spacing_free(text, want):
    assert identify(ERG, placard=text).guide == want


@pytest.mark.parametrize(
    "text,guides",
    [
        ("2", {"118", "120", "122", "123"}),
        ("4", {"134", "136", "139"}),
        ("6", {"153", "158"}),
        ("1", {"112", "114"}),
        ("EXPLOSIVES", {"112", "114"}),
        ("INHALATION HAZARD", {"123", "153"}),
    ],
)
def test_a_placard_that_names_several_guides_is_refused_with_the_candidates(
    text, guides
):
    with pytest.raises(AssessmentError) as e:
        identify(ERG, placard=text)
    cands = e.value.detail["candidates"]
    assert {c["guide"] for c in cands} == guides
    assert all(c["placard"] and c["shows"] for c in cands)
    assert "division" in e.value.hint.lower() or "placard" in e.value.hint.lower()


def test_an_unknown_placard_is_refused_with_the_accepted_values():
    with pytest.raises(AssessmentError) as e:
        identify(ERG, placard="12")
    assert "2.3" in e.value.detail["accepted"] and "none" in e.value.detail["accepted"]


@pytest.mark.parametrize("g", ["111", "112", "114", "128P", "123"])
def test_any_packed_guide_number_is_an_entry_point(g):
    mat = identify(ERG, guide_number=g)
    assert mat.guide == g and mat.entry_point == "guide_number"


@pytest.mark.parametrize("g", ["121", "167", "999", "12a"])
def test_a_guide_the_pack_does_not_hold_is_refused(g):
    with pytest.raises(AssessmentError):
        identify(ERG, guide_number=g)


@needs_pdf
def test_key_a_reads_every_circle_key_b_reads_and_no_other():
    import erg_placards

    rows, report = erg_placards.key(PDF, yaml.safe_load(KEY_B.read_text()))
    assert report["circles_key_a"] == report["circles_key_b"] == 22
    assert report["unmatched"] == []
    assert all(set(r["keyed_by"]) == {"A", "B"} for r in rows)


@needs_pdf
def test_key_a_refuses_a_key_b_circle_with_the_wrong_number():
    import erg_placards

    kb = yaml.safe_load(KEY_B.read_text())
    kb["circles"][0]["guide"] = "117"  # p10-111 misread
    with pytest.raises(erg_placards.KeyingError, match="p10-111"):
        erg_placards.key(PDF, kb)


# ── The input ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "given",
    [
        {},
        {"material": "UN1017", "placard": "2.3"},
        {"material": "UN1017", "guide_number": "124"},
        {"placard": "2.3", "guide_number": "123"},
    ],
)
def test_exactly_one_of_material_guide_and_placard(given):
    with pytest.raises(ValidationError, match="exactly one"):
        incident(**given)


# ── The tools ───────────────────────────────────────────────────────────────


def test_assess_returns_the_guide_with_the_placard_table_as_basis():
    r = run(incident(placard="2.3"))
    assert "error" not in r, r
    assert r["coverage"] == "unidentified" and r["material"] is None
    assert r["guide"] == {"number": "123", "title": ERG.guides["123"].title}
    ib = r["identified_by"]
    assert ib["entry_point"] == "placard" and ib["placard"] == "2.3"
    assert ib["locator"] == "erg2024-en-pdf#p10"
    assert r["tih"] is None
    assert r["erg_table"]["table"] == "guide"
    tags = [b["tag"] for b in r["basis"]]
    assert any("Table of Markings, Labels and Placards" in t for t in tags)
    assert r["limits"] and all(not stylecheck.check(s) for s in r["limits"])


def test_assess_for_a_guide_number_names_the_incident_report():
    r = run(incident(guide_number="111"))
    assert r["identified_by"]["entry_point"] == "guide_number"
    assert r["guide"]["number"] == "111"
    assert r["guide"]["title"] == "Mixed Load/Unidentified Cargo"
    assert any(b["tag"] == "[incident report]" for b in r["basis"])


@pytest.mark.parametrize("entry", [{"guide_number": "111"}, {"placard": "1.1"}])
def test_guidance_runs_the_guide(entry):
    r = guidance(incident(fire_involved=True, **entry))
    assert "error" not in r, r
    g = "111" if "guide_number" in entry else "112"
    assert r["guide"]["number"] == g and r["material"] is None
    assert r["identified_by"]["entry_point"] in ("guide_number", "placard")
    want = [i.text for i in ERG.guides[g].sections["potential_hazards"].items]
    assert [i["text"] for i in r["potential_hazards"]] == want
    assert all(not stylecheck.check(s) for s in r["limits"])


async def test_the_footprint_is_the_guides_circles_and_says_why():
    r = await footprint(incident(placard="2.3", fire_involved=True), WEST_13)
    assert "error" not in r, r
    zones = r["zones"]
    assert set(zones) == {"initial_isolation_zone", "fire_isolation"}
    assert zones["initial_isolation_zone"]["distance"]["metres"] == 100
    assert zones["fire_isolation"]["distance"]["metres"] == 800
    assert r["table_row"] is None and r["verify_in_erg_app"] is None
    assert any("Table 1" in s for s in r["limits"])
    assert all(not stylecheck.check(s) for s in r["limits"])


async def test_guide_112_draws_its_explosive_distances():
    r = await footprint(
        incident(placard="1.1", fire_involved=True, spill_size="large"), WEST_13
    )
    zones = r["zones"]
    assert zones["initial_isolation_zone"]["distance"]["metres"] == 500
    assert zones["large_spill_evacuation"]["distance"]["metres"] == 800
    assert zones["fire_isolation"]["distance"]["metres"] == 1600


async def test_a_refused_placard_is_an_error_with_a_hint_in_every_tool():
    inc = incident(placard="2")
    assert "hint" in run(inc) and "hint" in guidance(inc)
    # HB-18: the footprint draws every candidate instead (tests/test_ambiguous_load.py)
    assert (await footprint(inc, WEST_13))["ambiguity"]["candidate_count"] == 4
