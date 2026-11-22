"""The `assess_incident` tool: resolve the material and decide which ERG table applies.

Data source: the shipped knowledge packs (`packs/erg.json`, `cfr172.json`,
`hazard_classes.json`, `cameo.json`): ERG 2024 (with its Table of Markings, Labels and
Placards for a load known only by its placard), 49 CFR 172.101 (edition of October 1,
2025), CAMEO Chemicals datasheets. Sunrise and sunset are calculated (NOAA solar
equations), not fetched. Update cadence: the packs change only with a server release.
As-of: `pack_versions` in the result names the edition and build of each pack. No
network call.

A material name the yellow index does not print ("ammonia", "liquid nitrogen") is not
refused bare (HB-207 item 7): the error carries `index_candidates`, the index rows the
typed words point to, each its ID number, its name as printed and its guide
(`hazbrief.index_candidates`), for the client to choose from and ask again by ID number.
None is chosen for it. The tool description says nothing of it while the tool surface is
frozen (DN-009 section 2, to 2026-11-20); the error's own `hint` does.
"""

from __future__ import annotations

from hazbrief.incident import AssessmentError, assess
from hazbrief.models import IncidentInput, with_notices
from hazbrief.packs import default_packs


def run(incident: IncidentInput) -> dict:
    """The tool body, apart from registration so tests can call it directly."""
    try:
        return assess(
            default_packs(),
            incident.material,
            incident.container,
            incident.location.latitude,
            incident.location.longitude,
            incident.incident_time,
            incident.fire_involved,
            incident.spill_size,
            incident.where_spilled,
            guide_number=incident.guide_number,
            placard=incident.placard,
        )
    except AssessmentError as exc:
        return exc.as_dict()


def register(mcp) -> None:
    default_packs()  # a missing or altered pack stops the server at startup

    @mcp.tool(
        name="assess_incident",
        annotations={
            "title": "Assess a Hazmat Incident",
            "readOnlyHint": True,
            "openWorldHint": False,
        },
    )
    def assess_incident(incident: IncidentInput) -> dict:
        """Resolve a transported-hazmat incident against the ERG 2024.

        Returns the ID number, names, ERG guide number and title, whether ERG Table 1
        lists the material (TIH), its hazard class rule set, its 49 CFR 172.101 hazard
        class and label codes, its CAMEO datasheets, which ERG table gives its distances
        (Table 1, Table 3, or the guide's EVACUATION distances), and whether the
        incident time is day or night at the point, with the sunrise and sunset. Each
        value has a `basis` entry: a source tag and the page it reads.

        Data source: ERG 2024, 49 CFR 172.101 and CAMEO, from the server's packs.
        Update cadence: changes only with a server release. As-of: `pack_versions`.
        Every ERG ID number resolves; full rows (distances, CFR, CAMEO, hazard class)
        exist for the seed materials, and any other ID returns `coverage: erg`.

        A load with no ID number or name (`placard` or `guide_number` instead of
        `material`) returns `coverage: unidentified`: the guide the ERG's Table of
        Markings, Labels and Placards circles beside the placard (or the guide given),
        `identified_by` saying how, no material, and `tih` null. An explosive the
        yellow index names with no ID number ("Blasting agent", "ANFO") returns
        `coverage: unnumbered` the same way, with the index page. An input the ERG
        cannot answer returns `error` and a `hint`, never a guess.
        """
        return with_notices(run(incident), incident=incident)
