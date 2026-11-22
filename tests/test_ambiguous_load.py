"""HB-18: an ambiguous load, settled on the server (A-3; DN-001 section 4: an ambiguity
is reported, never resolved silently).

An input the ERG answers with several candidates (a name under two ID numbers, an ID
number whose names carry different guides, a placard several rows of the Table of
Markings, Labels and Placards match) was an error with the candidates in HB-15. HB-16's
agents, given that error, drew a footprint for every candidate and briefed the largest
(LN-07 F6). The ERG's own rule for the placard table is the same: "If multiple placards
point to more than one guide, initially use the most conservative guide (i.e., the
guide requiring the greatest degree of protective actions)" (ERG 2024 PDF p. 9), and
for Table 1, "use the entry with the largest distances" (p. 290). So the footprint tool
draws one footprint per candidate, marks the largest governing, and fires
`ambiguous_material` with every candidate as a receipt. Nothing is averaged and
nothing is picked by frequency: the envelope is the union, and the printed distances
are the governing candidate's.
"""

from __future__ import annotations

import pytest

from hazbrief.incident import AmbiguousLoad, AssessmentError, identify
from hazbrief.models import IncidentInput, WindObservation
from hazbrief.packs import default_packs
from hazbrief.tools.protective_action_footprint import footprint

ERG = default_packs().erg.data
I81 = {"latitude": 39.722, "longitude": -77.724}
I83 = {"latitude": 39.722, "longitude": -76.661}
DAY = "2026-10-21T14:00:00-04:00"
WEST_13 = WindObservation.model_validate(
    {
        "direction_deg_from": 270,
        "speed_kmh": 13,
        "observed_at": "2026-10-21T14:00:00-04:00",
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


#: The four HB-16 ambiguity prompts' loads, and the candidates the ERG gives each: the
#: guide of each, in the order the yellow index or the placard table prints them.
AMBIGUOUS = {
    "a-name-several-ids": (
        {"material": "propane", "spill_size": "large"},
        [("UN1075", "115"), ("UN1978", "115")],
    ),
    "a-id-several-guides": (
        {"material": "UN1057", "spill_size": "large", "fire_involved": True,
         "location": I83},
        [("UN1057", "115"), ("UN1057", "128")],
    ),
    "a-inhalation-hazard": (
        {"placard": "INHALATION HAZARD"},
        [("2.3", "123"), ("6.1", "153")],
    ),
    "a-bare-class-2": (
        {"placard": "2"},
        [("2.1", "118"), ("2.2", "120"), ("2.3", "123"), ("OXYGEN", "122")],
    ),
}  # fmt: skip
#: The governing candidate of each, by the largest distance its guide gives: propane's
#: two IDs share Guide 115 (a tie, so the first); UN1057 in fire, Guide 115's 1,600 m
#: against 128's 800 m; INHALATION HAZARD, 123's 100 m against 153's 50 m; a bare class
#: 2, OXYGEN's 500 m downwind.
GOVERNING = {
    "a-name-several-ids": 0,
    "a-id-several-guides": 0,
    "a-inhalation-hazard": 0,
    "a-bare-class-2": 3,
}


def _key(c: dict) -> tuple[str, str]:
    return (c["id_number"] or c["placard"], c["guide"])


# ── Resolution ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("pid", sorted(AMBIGUOUS))
def test_an_ambiguous_input_raises_with_its_candidates_as_materials(pid):
    load, expected = AMBIGUOUS[pid]
    load = {k: v for k, v in load.items() if k in ("material", "placard")}
    with pytest.raises(AmbiguousLoad) as e:
        identify(ERG, **load)
    got = [(m.id_number or m.placard.placard, m.guide) for m in e.value.materials]
    assert got == expected
    # still the HB-15 error, for the tools that answer an ambiguity with it
    assert isinstance(e.value, AssessmentError)
    assert e.value.as_dict()["candidates"]


def test_an_id_under_several_guides_is_one_candidate_per_guide_with_its_names():
    """UN1057's three names carry two guides: the footprints differ by guide only, since
    Table 1 does not list UN1057, so the candidates are the guides, each with its names.
    """
    with pytest.raises(AmbiguousLoad) as e:
        identify(ERG, material="UN1057")
    names = [m.candidate_names for m in e.value.materials]
    assert names == [
        (
            "Lighter refills containing flammable gas",
            "Lighters containing flammable gas",
        ),
        ("Lighters, non-pressurized, containing flammable liquid",),
    ]


def test_an_unambiguous_input_still_resolves_to_one_material():
    assert identify(ERG, material="UN1017").un == "1017"
    assert identify(ERG, placard="2.3").guide == "123"


# ── The footprint ───────────────────────────────────────────────────────────


async def _fp(pid: str) -> dict:
    load, _ = AMBIGUOUS[pid]
    return await footprint(incident(**load), WEST_13)


@pytest.mark.parametrize("pid", sorted(AMBIGUOUS))
async def test_the_footprint_draws_one_footprint_per_candidate(pid):
    r = await _fp(pid)
    amb = r["ambiguity"]
    _, expected = AMBIGUOUS[pid]
    assert amb["candidate_count"] == len(expected)
    assert [_key(c) for c in amb["candidates"]] == expected
    for c in amb["candidates"]:
        assert "error" not in c
        assert c["zones"]["initial_isolation_zone"]["distance"]["metres"] > 0
        # each with its own locators
        assert c["basis"] and all(b["tag"] for b in c["basis"])
    assert [c["governing"] for c in amb["candidates"]].count(True) == 1


@pytest.mark.parametrize("pid", sorted(AMBIGUOUS))
async def test_the_governing_candidate_has_the_largest_distances(pid):
    r = await _fp(pid)
    cands = r["ambiguity"]["candidates"]
    g = GOVERNING[pid]
    assert cands[g]["governing"] and r["ambiguity"]["governing"] == g
    reach = [c["reach_m"] for c in cands]
    assert reach[g] == max(reach)
    # the printed distances are the governing candidate's, never an average
    assert r["zones"] == cands[g]["zones"]
    assert r["guide"]["number"] == cands[g]["guide"]


@pytest.mark.parametrize("pid", sorted(AMBIGUOUS))
async def test_the_envelope_is_the_union_of_every_candidates_polygons(pid):
    r = await _fp(pid)
    polys = [
        f for f in r["footprint"]["features"] if f["geometry"]["type"] == "Polygon"
    ]
    for i, c in enumerate(r["ambiguity"]["candidates"]):
        mine = [f for f in polys if f["properties"]["candidate"] == i]
        drawn = {f["properties"]["zone"] for f in mine}
        assert drawn == {z for z in c["zones"] if z != "large_spill_downwind"}
        for f in mine:
            assert f["properties"]["governing"] is c["governing"]
            radius = f["properties"].get("radius_m")
            if radius is not None:
                assert (
                    radius == c["zones"][f["properties"]["zone"]]["distance"]["metres"]
                )
    spills = [f for f in r["footprint"]["features"] if f["geometry"]["type"] == "Point"]
    assert len(spills) == 1


@pytest.mark.parametrize("pid", sorted(AMBIGUOUS))
async def test_the_ambiguous_material_flag_fires_with_the_candidates_as_receipts(pid):
    r = await _fp(pid)
    fired = [
        f for f in r["flags"]["all"] if f["kind"] == "identification.ambiguous_material"
    ]
    assert len(fired) == 1
    f = fired[0]
    assert f["priority"] == "high" and not f["indication"]
    n = r["ambiguity"]["candidate_count"]
    assert f"{n} candidates" in f["sentence"]
    assert r["ambiguity"]["candidates"][GOVERNING[pid]]["label"] in f["sentence"]
    # cause: the candidate count; consequence: the ERG's most-conservative-guide rule;
    # response: the ERG's identify-the-material sentence, by page
    assert f["consequence"]["page"] == 9
    assert "most conservative guide" in f["consequence"]["quote"]
    assert f["response"]["page"] == 9
    assert "ID number or proper shipping name" in f["response"]["quote"]
    assert f["rule_id"] in r["flags"]["briefing"]["rule_ids"]
    got = [(c["id_number"] or c["placard"], c["guide"]) for c in f["candidates"]]
    assert got == AMBIGUOUS[pid][1]
    for c in f["candidates"]:
        assert c["names"] or c["placard"]


async def test_every_candidates_limits_travel_with_the_union():
    """A bare class 2: Guides 118 and 123 send a spill to Table 1, which needs the
    material, so their real distances are unknown; the governing OXYGEN row cannot say
    so, its candidates' limits do."""
    r = await _fp("a-bare-class-2")
    for guide in ("118", "123"):
        assert any(
            f"Guide {guide} sends a spill to Table 1" in t for t in r["limits"]
        ), guide


async def test_an_identified_material_has_no_ambiguity():
    r = await footprint(incident(material="UN1017", spill_size="large"), WEST_13)
    assert "ambiguity" not in r
    assert not any(
        f["kind"] == "identification.ambiguous_material" for f in r["flags"]["all"]
    )


async def test_the_same_ambiguous_input_gives_the_same_answer():
    assert await _fp("a-bare-class-2") == await _fp("a-bare-class-2")


async def test_an_input_no_candidate_can_answer_is_still_an_error():
    r = await footprint(incident(placard="2", container="no such container"), WEST_13)
    assert "error" in r and "ambiguity" not in r
