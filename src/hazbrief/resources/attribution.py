"""The attribution notices the server must carry, as an MCP resource (DN-003 section 2).

Data source: `docs/stylebook/ATTRIBUTION.md`, written from the terms catalogued in
`corpus/api_catalog.yaml` (HB-06): the Census Data API notice, the LODES citation form,
the USGS credit, and the NWS and CMS no-endorsement terms. Update cadence: changes only
with a commit, when a source's terms change. As-of: the file as shipped with this server
version.
"""

from __future__ import annotations

from hazbrief.stylebook_files import ATTRIBUTION, read_shipped

ATTRIBUTION_URI = "hazbrief://attribution"


def register(mcp) -> None:
    text = read_shipped(ATTRIBUTION)

    @mcp.resource(
        ATTRIBUTION_URI,
        name="attribution",
        title="Data Sources and Attribution",
        description=(
            "The notices each federal data source's terms require: Census, LODES, "
            "USGS, NWS, CMS and the ERG. No agency endorses this server."
        ),
        mime_type="text/markdown",
    )
    def attribution() -> str:
        return text
