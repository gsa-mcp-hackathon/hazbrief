"""The `ics201_brief` prompt: an ICS 201 draft written to the commander stylebook.

It sequences the server's tools in DN-001 section 7 order and binds the agent to the
stylebook by carrying the stylebook's full text, so a client that never reads resources
still writes to it. The vocabulary is referenced by its resource URI rather than
inlined: the stylebook's rules point to it, and it is data for lookup, not instructions.

Data source: the incident as the caller reports it, and
`docs/stylebook/COMMANDER_STYLEBOOK.md`. Update cadence and as-of: the stylebook as
shipped with this server version.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from hazbrief.resources.attribution import ATTRIBUTION_URI
from hazbrief.resources.stylebook import STYLEBOOK_URI, VOCABULARY_URI
from hazbrief.stylebook_files import COMMANDER_STYLEBOOK, read_shipped

# DN-001 section 7, in order. These are the target tool names; a tool the server does
# not yet expose is reported as missing in the draft (see the instructions below), never
# filled from memory.
TOOL_SEQUENCE: tuple[tuple[str, str], ...] = (
    (
        "assess_incident",
        "resolve the material, its ERG guide and its hazard class rule set",
    ),
    (
        "protective_action_footprint",
        "the ERG zones as GeoJSON, oriented by the NWS wind",
    ),
    ("population_at_risk", "residents and daytime workers inside the footprint"),
    (
        "facilities_in_footprint",
        "schools, nursing homes, prisons and hospitals inside it",
    ),
    (
        "receiving_hospitals",
        "hospitals outside the footprint that can receive casualties",
    ),
    (
        "material_response_guidance",
        "the orange guide and response text for the material",
    ),
    (
        "build_ics_201",
        "the ICS 201 draft: it runs the tools above on the same incident and fills "
        "the blocks public data can fill, with Block 4's GeoJSON (the SVG sketch with "
        "`include_map_svg`) and Annex A",
    ),
)  # build_ics_201: HB-11, HB-11b

_INSTRUCTIONS = """\
Draft an ICS 201 Incident Briefing for this incident, for the Incident Commander to
review and sign.

Incident, as reported:
- Material: {material}
- Container: {container}
- Location: {location}
- Time: {incident_time}

Call the server's tools in this order, passing each result forward:
{sequence}

If a tool in this order is not available, write that it is missing in the block it would
fill and leave the block's content empty. Never fill a block from memory or from general
knowledge.

The server decides what is alarming: write only the flags its tools return, each with
its rule and source. Distances come from the ERG tables exactly as the tools return
them.

Write every sentence to the Commander Stylebook below ({stylebook_uri}). Use only the
terms in the controlled vocabulary ({vocabulary_uri}), and none of their forbidden
synonyms. Credit the sources as {attribution_uri} sets out.

---

{stylebook}"""


def render_ics201_brief(
    material: str, container: str, location: str, incident_time: str
) -> str:
    """The prompt text, apart from registration so tests and HB-05 can render it."""
    sequence = "\n".join(
        f"{i}. `{name}`: {purpose}"
        for i, (name, purpose) in enumerate(TOOL_SEQUENCE, start=1)
    )
    return _INSTRUCTIONS.format(
        material=material,
        container=container,
        location=location,
        incident_time=incident_time,
        sequence=sequence,
        stylebook_uri=STYLEBOOK_URI,
        vocabulary_uri=VOCABULARY_URI,
        attribution_uri=ATTRIBUTION_URI,
        stylebook=read_shipped(COMMANDER_STYLEBOOK),
    )


def register(mcp) -> None:
    # Read once now: a missing stylebook stops the server at startup
    # (stylebook_files.read_shipped).
    read_shipped(COMMANDER_STYLEBOOK)

    @mcp.prompt(
        name="ics201_brief",
        title="ICS 201 Incident Briefing",
        description=(
            "Draft an ICS 201 Incident Briefing for a transported-hazmat incident: "
            "calls the server's tools in order and writes to the commander stylebook."
        ),
    )
    def ics201_brief(
        material: Annotated[
            str,
            Field(
                min_length=1,
                description="Material name or UN/NA ID number, as reported.",
            ),
        ],
        container: Annotated[
            str,
            Field(
                min_length=1,
                description="Container, e.g. highway tank truck, rail tank car.",
            ),
        ],
        location: Annotated[
            str,
            Field(
                min_length=1,
                description="Where: road and mile marker, or latitude/longitude.",
            ),
        ],
        incident_time: Annotated[
            str,
            Field(
                min_length=1,
                description="When: month/day/year, 24-hour time and time zone.",
            ),
        ],
    ) -> str:
        return render_ics201_brief(material, container, location, incident_time)
