"""Tools submodule — one tool per file.

Each tool module exposes a `register(mcp)` function that attaches its
`@mcp.tool`-decorated function to the server. This file aggregates them into a
single `register_tools(mcp)` that `app.py` calls.

To add a tool:
  1. Create `tools/<your_tool>.py` with a `register(mcp)` function.
  2. Import it below and call `<your_tool>.register(mcp)` inside register_tools.

Target tool set (DN-001 section 7): assess_incident, protective_action_footprint,
population_at_risk, facilities_in_footprint, receiving_hospitals,
material_response_guidance, build_ics_201. Registered: assess_incident and
protective_action_footprint (HB-08), population_at_risk (HB-09),
facilities_in_footprint and receiving_hospitals (HB-10), material_response_guidance and
build_ics_201 (HB-11): all seven.
"""

from __future__ import annotations

from hazbrief.request_shape import WrappedTwiceGuard
from hazbrief.tools import (
    assess_incident,
    build_ics_201,
    facilities_in_footprint,
    material_response_guidance,
    population_at_risk,
    protective_action_footprint,
    receiving_hospitals,
)


def register_tools(mcp) -> None:
    """Register all tools with the MCP server."""
    assess_incident.register(mcp)
    protective_action_footprint.register(mcp)
    population_at_risk.register(mcp)
    facilities_in_footprint.register(mcp)
    receiving_hospitals.register(mcp)
    material_response_guidance.register(mcp)
    build_ics_201.register(mcp)
    # HB-37 (A-11): every tool's object argument wrapped twice is refused with a hint;
    # installed here so every server built from these tools carries it.
    mcp.add_middleware(WrappedTwiceGuard(mcp))


__all__ = ["register_tools"]
