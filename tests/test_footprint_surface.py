"""HB-08b: `where_spilled`, Table 2 flagging, and the `verify_in_erg_app` link.

The I-81 worked example is HB-01d's (`corpus/erg2020_datafiles.md` section 4): UN1017
Chlorine, highway tank truck or trailer, large spill, 2026-10-21 14:00 EDT, wind from
the recorded NWS exchange (from 0 degrees at 11.1 km/h, moderate band, daytime). The
link must equal it byte for byte.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from hazbrief.models import IncidentInput, WindObservation  # noqa: E402
from hazbrief.tools.protective_action_footprint import (  # noqa: E402
    erg_app_link,
    footprint,
)

POINTS = {
    p["id"]: p
    for p in yaml.safe_load(
        (REPO / "fixtures" / "scenario_points.yaml").read_text(encoding="utf-8")
    )["points"]
}
I81 = POINTS["i81-md-pa-line"]
DAY = "2026-10-21T14:00:00-04:00"
WEST_13 = WindObservation(
    speed_kmh=13,
    direction_deg_from=270,
    observed_at="2026-10-20T13:40:00-04:00",
    source="worked example wind",
)
HB01D_URL = (
    "https://www.phmsa.dot.gov/erg/material?materialName=Chlorine&materialUn=1017"
    "&lat=39.722&lon=-77.724&windDir=0&spillSize=large&timeOfDay=day&whereSpilled=land"
    "&containerType=Highway%20tank%20truck%20or%20trailer&windSpeed=moderate&showMap=true"
)


def incident(material: str, **kw) -> IncidentInput:
    return IncidentInput.model_validate(
        {
            "material": material,
            "container": kw.pop("container", "unknown"),
            "location": {"latitude": I81["latitude"], "longitude": I81["longitude"]},
            "incident_time": kw.pop("incident_time", DAY),
            "fire_involved": kw.pop("fire_involved", False),
            "spill_size": kw.pop("spill_size", "large"),
            **kw,
        }
    )


def test_the_link_encodes_as_the_page_says():
    url = erg_app_link(
        "Sulfur dioxide", "1079", 38.7934, -77.037, 359.6, "unknown", "night", "water",
        None, "high",
    )  # fmt: skip
    assert "materialName=Sulfur%20dioxide" in url and "windDir=0&" in url
    assert "spillSize=large" in url and "containerType" not in url
    assert url.endswith("whereSpilled=water&windSpeed=high&showMap=true")


def test_where_spilled_defaults_to_land_as_phmsa_does():
    assert incident("UN1017").where_spilled == "land"
    with pytest.raises(ValueError):
        incident("UN1017", where_spilled="river")


async def test_the_i81_link_equals_the_hb01d_worked_example_byte_for_byte():
    r = await footprint(
        incident("UN1017", container="Highway tank truck or trailer"), None
    )
    assert r["wind"]["direction_deg_from"] == 0 and r["wind"]["band"] == "moderate"
    assert r["verify_in_erg_app"] == HB01D_URL


async def test_an_unknown_container_omits_container_type_and_says_so():
    r = await footprint(incident("UN1017"), WEST_13)
    assert "containerType" not in r["verify_in_erg_app"]
    assert any("first container" in x for x in r["limits"])


async def test_the_link_caveat_names_the_editions():
    """HB-18 (A-5): the caveat no longer points a client at the repository's LN-02,
    which it cannot open; the code comment keeps the pointer."""
    r = await footprint(incident("UN1017"), WEST_13)
    text = " ".join(r["limits"])
    assert "ERG 2020" in text and "ERG 2024" in text and "LN-02" not in text


async def test_a_water_reactive_tih_material_in_water_uses_its_water_entry():
    """UN1746 Bromine trifluoride: Table 1 prints a land and a water entry (p. 30)."""
    land = await footprint(incident("UN1746", spill_size="small"), WEST_13)
    water = await footprint(
        incident("UN1746", spill_size="small", where_spilled="water"), WEST_13
    )
    assert "on land" in land["table_row"]["printed_name"]
    assert "in water" in water["table_row"]["printed_name"]
    assert "whereSpilled=water" in water["verify_in_erg_app"]
    # HB-12b: one water-reactive flag for guide 144, FR-T2-01 consolidated into it
    wr = [f for f in water["flags"]["all"] if f["kind"] == "water_reactive"]
    assert [f["rule_id"] for f in wr] == ["FR-G144-WATER_REACTIVE"]
    assert "FR-T2-01" in wr[0]["merged"]
    assert any(rc["page"] == 336 for rc in wr[0]["receipts"])
    assert wr[0]["priority"] == "high" and wr[0]["response"]
    assert all(f["receipts"] for f in water["flags"]["all"])


async def test_a_water_only_material_draws_table1_zones_only_in_water():
    land = await footprint(incident("UN1162"), WEST_13)
    water = await footprint(incident("UN1162", where_spilled="water"), WEST_13)
    assert land["erg_table"]["table"] == "guide"
    assert water["erg_table"]["table"] == "Table 1"
    assert "protective_action_zone" in water["zones"]


async def test_water_changes_nothing_for_a_material_table2_does_not_list():
    land = await footprint(incident("UN1017"), WEST_13)
    water = await footprint(incident("UN1017", where_spilled="water"), WEST_13)
    assert land["zones"] == water["zones"]
    assert any("changes nothing" in x for x in water["limits"])
