"""`facilities_in_footprint`: the schools, hospitals, nursing homes, emergency services,
waterways and rail inside a footprint (HB-10; DN-001 sections 2, 3, 6; DN-005 section
1 item 3).

Each list comes from one federal source (`facilities_sources.yaml`): the USGS National
Structures Dataset for schools, hospitals and emergency services; CMS Nursing Home
Provider Information for nursing homes; USGS 3DHP for waterways; the BTS NTAD rail
lines and FRA grade crossings for rail. A source that fails is reported in `errors`, its
section is null, its flag inputs are null (the flag evaluator reads null as not
supplied), and every other source still answers.

The tool supplies the inputs four flag rules read (FR-SCH-01, FR-HOSP-01, FR-WATER-01,
FR-RAIL-01); it fires no flag itself (DN-006).
"""

from __future__ import annotations

from hazbrief import facilities, geo
from hazbrief.facilities import CmsFileMissing
from hazbrief.geometry import GeometryError
from hazbrief.incident import basis
from hazbrief.models import FacilitiesInput, with_notices
from hazbrief.utils import PageCapExceeded, UpstreamServiceError

#: What each source omits or how the lists are made; each sentence carries its source
#: tag before its full stop, as the stylebook writes a tag.
LIMITS = (
    "The structures dataset holds selected facilities, so a school, hospital, fire "
    "station or police station it omits is not listed [USGS National Structures "
    "Dataset service description].",
    "Nursing homes are those certified by Medicare or Medicaid; assisted living "
    "facilities are not listed [CMS Nursing Home Provider Information].",
    "People in nursing facilities, correctional facilities, college housing and other "
    "group quarters are counted by population_at_risk, not here.",
    "A waterway counts once per named stream or 3DHP mainstem, and its reaches inside "
    "are summed [USGS 3D Hydrography Program].",
    # DN-002 section 4; HB-18 (A-5): the tag names the statute, not the design note
    "Drinking water intakes are not published, so waterways are listed, not intakes "
    "[Safe Drinking Water Act section 1433].",
    "Rail lines count by segment between network nodes, so one line can count more "
    "than once [NTAD North American Rail Network Lines].",
    "Grade crossings are the at-grade crossings of the FRA inventory, public and "
    "private; bridges and underpasses are not counted [NTAD Railroad Grade Crossings].",
    "A facility just outside the footprint is not listed unless buffer_m is set.",
)
GROUP_QUARTERS = (
    "Residents of nursing facilities, correctional facilities, college housing and "
    "other group quarters are counted by population_at_risk "
    "(nighttime.group_quarters), by census block. This tool names facilities and "
    "counts no people."
)
EMPTY_REASON = (
    "No school, hospital, nursing home, emergency service, waterway or rail feature in "
    "these sources lies inside the footprint."
)
SECTIONS = ("schools", "hospitals", "nursing_homes", "emergency_services")


def _error(source: str, exc: Exception, hint: str) -> dict:
    # A capped query is not a transient failure: the remedy is a smaller footprint.
    if isinstance(exc, PageCapExceeded):
        hint = geo.TOO_LARGE_HINT
    return {"source": source, "error": str(exc), "hint": hint}


def _basis(src: dict, homes_meta: dict | None) -> list:
    s, h, r = src["structures"], src["hydrography"], src["rail"]
    out = [
        basis(
            name,
            f"{s['label']}, {' and '.join(s['categories'][name].values())}, "
            f"{s['as_of']}",
            None,
        )
        for name in ("schools", "hospitals", "emergency_services")
    ]
    if homes_meta is not None:
        out.append(
            basis(
                "nursing_homes",
                f"{homes_meta['source']}, as of {homes_meta['as_of']}",
                None,
            )
        )
    out += [
        basis("waterways", f"{h['label']}, {h['as_of']}", None),
        basis(
            "rail lines",
            f"{r['lines']['label']}, updated {r['lines']['as_of']}",
            None,
        ),
        basis(
            "grade crossings",
            f"{r['crossings']['label']}, updated {r['crossings']['as_of']}",
            None,
        ),
    ]
    return out


async def list_facilities(req: FacilitiesInput) -> dict:
    try:
        a = facilities.area(req.footprint, req.buffer_m)
    except geo.FootprintTooLarge as exc:
        return {
            "error": f"The footprint is too large: {exc}.",
            "hint": geo.TOO_LARGE_HINT,
        }
    except GeometryError as exc:
        return {
            "error": f"The footprint cannot be read: {exc}.",
            "hint": "Pass the `footprint` GeoJSON protective_action_footprint returns, "
            "or a GeoJSON Polygon in WGS84 longitude and latitude.",
        }
    src = facilities.sources()
    out: dict = {}
    queries: dict = {}
    errors: list = []
    retry = "Retry; the other sources answered."
    for name in ("schools", "hospitals", "emergency_services"):
        try:
            out[name], queries[name] = await facilities.structures(name, a)
        except UpstreamServiceError as exc:
            out[name] = None
            errors.append(_error(src["structures"]["label"], exc, retry))
    homes_meta = None
    try:
        out["nursing_homes"], homes_meta = facilities.nursing_homes(a)
    except CmsFileMissing as exc:
        out["nursing_homes"] = None
        errors.append(
            _error(
                src["cms"]["nursing_homes"]["label"], exc, "Run scripts/fetch_cms.py."
            )
        )
    try:
        out["waterways"], queries["waterways"] = await facilities.waterways(a)
    except UpstreamServiceError as exc:
        out["waterways"] = None
        errors.append(_error(src["hydrography"]["label"], exc, retry))
    try:
        out["rail"], queries["rail"] = await facilities.rail(a)
    except UpstreamServiceError as exc:
        out["rail"] = None
        errors.append(_error("NTAD rail", exc, retry))

    def count(section: str, key: str | None = None) -> int | None:
        """How many listed; None when the section's source failed."""
        v = out[section]
        if v is None:
            return None
        return len(v if key is None else v[key])

    water = out["waterways"]
    flag_inputs = {
        "schools_in_footprint": count("schools"),
        "hospitals_in_footprint": count("hospitals"),
        "waterways_in_footprint": None if water is None else water["count"],
        "rail_features_in_footprint": count("rail", "segments"),
        "grade_crossings": count("rail", "crossings"),
    }
    result = {
        **{k: out[k] for k in SECTIONS},
        "waterways": out["waterways"],
        "rail": out["rail"],
        "counts": {
            "schools": count("schools"),
            "hospitals": count("hospitals"),
            "nursing_homes": count("nursing_homes"),
            "emergency_services": count("emergency_services"),
            "waterways": flag_inputs["waterways_in_footprint"],
            "rail_segments": flag_inputs["rail_features_in_footprint"],
            "grade_crossings": flag_inputs["grade_crossings"],
        },
        "zones": sorted(a.zones) or ["footprint"],
        "buffer_m": req.buffer_m,
        "group_quarters": GROUP_QUARTERS,
        "flag_inputs": flag_inputs,
        "basis": _basis(src, homes_meta),
        "limits": list(LIMITS),
        "query": queries,
    }
    if errors:
        result["errors"] = errors
    if not errors and not any(result["counts"].values()):
        result["reason"] = EMPTY_REASON
    return result


def register(mcp) -> None:
    facilities.sources()  # a missing or malformed sources file stops the server here

    @mcp.tool(
        name="facilities_in_footprint",
        annotations={
            "title": "Facilities in Footprint",
            "readOnlyHint": True,
            "openWorldHint": True,
        },
    )
    async def facilities_in_footprint(area: FacilitiesInput) -> dict:
        """The schools, hospitals, nursing homes, emergency services (fire, EMS,
        ambulance, police), waterways and rail lines and grade crossings inside a
        footprint, each with its zone (isolation or protective_action; else the guide
        circle it is in: large_spill_evacuation, fire_isolation or fire_evacuation),
        source id and as-of.

        Pass `area.footprint`, the GeoJSON protective_action_footprint returns (or any
        polygon), and optionally `buffer_m`. Group quarters residents are counted by
        population_at_risk, not here. `flag_inputs` carries the counts the facility
        flag rules read; this tool fires no flag.

        Data sources: USGS National Structures Dataset (carto.nationalmap.gov; schools,
        colleges, hospitals, fire and EMS stations, ambulance services, police
        stations); CMS Nursing Home Provider Information (cached file); USGS 3D
        Hydrography Program flowlines and waterbodies (hydro.nationalmap.gov); BTS NTAD
        North American Rail Network Lines and FRA Railroad Grade Crossings
        (services.arcgis.com). Update cadence: Structures and 3DHP refreshed by USGS
        (3DHP quarterly), NTAD as FRA updates, CMS quarterly. As-of: each facility's
        `as_of` (its load date) and the `basis` source tags. A source that fails is
        listed in `errors` and the others still answer.
        """
        return with_notices(await list_facilities(area), area=area)
