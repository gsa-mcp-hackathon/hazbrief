"""HB-18 (A-1): a tool argument sent as a JSON string.

HB-16's Haiku and Sonnet sent `request` (or `incident`) as a JSON string in 14 scenario
episodes (LN-07 F3, A-1). Every one of those 22 strings was malformed: one object, then
extra text (`..., "response_format": "detailed"}`). The decision: a string that parses,
whole, to one JSON object is accepted once, and the parse is recorded in the output's
`errors` as a notice; anything else is rejected as before, and the rejection now says
where the text stops being one object. Malformed JSON is never repaired.
"""

from __future__ import annotations

import json

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from hazbrief.config import settings
from hazbrief.tools import register_tools

I81 = {"latitude": 39.722, "longitude": -77.724}
INCIDENT = {
    "material": "UN1017",
    "container": "unknown",
    "location": I81,
    "incident_time": "2026-10-21T14:00:00-04:00",
    "fire_involved": False,
    "spill_size": "large",
}
WIND = {
    "direction_deg_from": 270,
    "speed_kmh": 13,
    "observed_at": "2026-10-21T14:00:00-04:00",
    "source": "worked example wind",
}


@pytest.fixture(autouse=True)
def a_key(monkeypatch):
    if not settings.census_api_key:
        monkeypatch.setattr(settings, "census_api_key", "replay-placeholder")


def _server() -> FastMCP:
    mcp = FastMCP("test")
    register_tools(mcp)
    return mcp


def _notices(data: dict) -> list[dict]:
    return [e for e in data.get("errors") or [] if "notice" in e]


async def test_an_object_sent_as_a_json_string_is_parsed_once_with_a_notice():
    async with Client(_server()) as c:
        as_object = await c.call_tool("assess_incident", {"incident": INCIDENT})
        as_string = await c.call_tool(
            "assess_incident", {"incident": json.dumps(INCIDENT)}
        )
    assert not _notices(as_object.data)
    got = {k: v for k, v in as_string.data.items() if k != "errors"}
    assert got == {k: v for k, v in as_object.data.items() if k != "errors"}
    (n,) = _notices(as_string.data)
    assert n["parameter"] == "incident"
    assert "JSON string" in n["notice"]


async def test_a_nested_object_sent_as_a_string_is_named_by_its_path():
    req = {"incident": json.dumps(INCIDENT), "wind": WIND}
    async with Client(_server()) as c:
        r = await c.call_tool("build_ics_201", {"request": req})
    assert [n["parameter"] for n in _notices(r.data)] == ["request.incident"]


async def test_every_tool_that_takes_an_object_accepts_one_string():
    async with Client(_server()) as c:
        fp = await c.call_tool(
            "protective_action_footprint",
            {"incident": json.dumps(INCIDENT), "wind": json.dumps(WIND)},
        )
        area = {
            "footprint": fp.data["footprint"],
            "incident_time": INCIDENT["incident_time"],
        }
        calls = {
            "protective_action_footprint": fp,
            "material_response_guidance": await c.call_tool(
                "material_response_guidance", {"incident": json.dumps(INCIDENT)}
            ),
            "population_at_risk": await c.call_tool(
                "population_at_risk", {"area": json.dumps(area)}
            ),
            "facilities_in_footprint": await c.call_tool(
                "facilities_in_footprint",
                {"area": json.dumps({"footprint": fp.data["footprint"]})},
            ),
            "receiving_hospitals": await c.call_tool(
                "receiving_hospitals",
                {
                    "incident": json.dumps(
                        {"location": I81, "footprint": fp.data["footprint"]}
                    )
                },
            ),
        }
    assert [n["parameter"] for n in _notices(fp.data)] == ["incident", "wind"]
    for name, r in calls.items():
        assert _notices(r.data), name


#: The shape every one of HB-16's stringified requests had: one object, then extra text.
TRAILING = json.dumps(INCIDENT) + ', "response_format": "detailed"}'


@pytest.mark.parametrize(
    "bad, words",
    [
        (TRAILING, "not one JSON object"),
        ("{'material': 'UN1017'}", "not one JSON object"),
        (json.dumps(json.dumps(INCIDENT)), "not an object"),
        (json.dumps([INCIDENT]), "not an object"),
    ],
)
async def test_anything_else_is_rejected_and_never_repaired(bad, words):
    async with Client(_server()) as c:
        with pytest.raises(ToolError) as e:
            await c.call_tool("assess_incident", {"incident": bad})
    assert words in str(e.value)
