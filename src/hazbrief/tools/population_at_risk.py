"""`population_at_risk`: who is inside a footprint, with the uncertainty the sources
carry (HB-09; DN-001 sections 3, 4, 7; DN-005 section 2).

The method, stated because MARPLOT's is not (LN-01 section 1):

1. **Geography.** TIGERweb 2020 tabulation blocks, block groups and tracts whose area
   overlaps the footprint, each with the share of its area inside (`geo.area_share`).
2. **Nighttime residents.** 2020 DHC block counts (P1), each weighted by its share.
   Group quarters by type (P18) are listed with the block they sit in.
3. **Characteristics.** ACS 5-year cells at the finest geography the API publishes each
   table at, weighted by share, summed with a derived MOE (`census` module docstring).
4. **Daytime workforce.** LODES8 WAC jobs (C000) by block, weighted by share.
5. **Resilience.** CRE tract counts of people with three or more components of social
   vulnerability, weighted by tract share; no MOE (the API publishes none).
6. **Primary.** Both counts are always returned; `primary` names the one the ERG period
   makes first: day, the workforce; night, the residents.
"""

from __future__ import annotations

from datetime import date

from hazbrief import census, geo, lodes
from hazbrief.census import CensusKeyMissing, Unit
from hazbrief.geometry import GeometryError
from hazbrief.incident import basis, day_or_night
from hazbrief.models import PopulationInput, with_notices
from hazbrief.utils import PageCapExceeded, UpstreamServiceError

#: The `limits` sentences: what the method assumes and where the sources stop. Each is
#: checked against the stylebook (test_population_at_risk.py).
LIMITS = (
    "Blocks partly inside the footprint count by the share of their area inside it.",
    "Area weighting assumes people are spread evenly across each block, block group "
    "and tract.",
    "Derived margins of error assume no covariance between cells, so they are "
    "approximate.",
    "A partial area's margin of error is scaled by the same area share as its "
    "estimate.",
    "Census block counts carry disclosure avoidance noise, so a small block's count "
    "can be off.",
    "Daytime counts jobs located in the footprint; a worker with two jobs counts "
    "twice.",
    "Daytime does not add residents who stay home during the day.",
    "Disability, vehicle and group quarters estimates are tract estimates, the finest "
    "the survey publishes.",
    "The resilience count has no margin of error; the Census Data API publishes none.",
)
MOE_METHOD = (
    "derived: square root of the sum of squared component MOEs, zero covariance "
    "(ACS General Handbook 2020, chapter 8, formula 1); among zero-estimate cells "
    "only the largest MOE (OnTheMap for Emergency Management statistical "
    "methodology); a partial unit's estimate and MOE scaled by its area share; "
    "approximate"
)


def _mdy(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%m/%d/%Y")


def _counts(units: list[Unit]) -> dict:
    whole = sum(1 for u in units if u.kind == "whole")
    return {"total": len(units), "whole": whole, "partial": len(units) - whole}


def _share(part: float, total: float) -> float | None:
    return round(part / total, 3) if total else None


def _nighttime(blocks: list[Unit], dhc: dict, src: dict) -> dict:
    total = partial = 0.0
    by_type: dict[str, float] = {t: 0.0 for t in src["group_quarters_types"]}
    facilities = []
    missing = []
    nulls = []
    for b in blocks:
        row = dhc.get(b.geoid)
        if row is None:
            missing.append(b.geoid)
            continue
        if row["null_cells"]:
            nulls.append({"block": b.geoid, "cells": row["null_cells"]})
        if row["total"] is None:
            continue  # named in `null_cells`, never counted as nobody (review L2-5)
        n = row["total"] * b.share
        total += n
        if b.kind == "partial":
            partial += n
        for t, count in row["group_quarters"].items():
            if count:
                by_type[t] += count * b.share
                facilities.append(
                    {
                        "block": b.geoid,
                        "type": t,
                        "count_in_block": int(count),
                        "block_share": round(b.share, 4),
                        "block_kind": b.kind,
                        "allocated": round(count * b.share, 1),
                    }
                )
    out = {
        "total": round(total),
        "from_partial_blocks": round(partial),
        "share_from_partial_blocks": _share(partial, total),
        "group_quarters": {
            "total": round(sum(by_type.values())),
            "by_type": {t: round(v) for t, v in by_type.items()},
            "facilities": facilities,
        },
        "source": f"{src['label']}, tables P1 and P18 (block)",
        "vintage": src["label"],
        "as_of": src["as_of"],
        "missing_blocks": missing,
    }
    # Present only when the API returned a null cell, as `day_night.note` is only for
    # polar time, so the recorded outputs (no null cell in any recorded DHC exchange)
    # are unchanged (HB-90).
    if nulls:
        out["null_cells"] = nulls
    return out


def _characteristics(bgs: list[Unit], tracts: list[Unit], cells: dict) -> dict:
    acs = census.sources()["acs"]
    units = {"block_group": bgs, "tract": tracts}
    out = {}
    for name, spec in acs["characteristics"].items():
        level = spec["geography"]
        parts, suppressed, missing = [], 0, []
        for u in units[level]:
            row = cells[level].get(u.geoid)
            if row is None:
                missing.append(u.geoid)
                continue
            for c in spec["cells"]:
                cell = row[c].scaled(u.share)
                suppressed += cell.suppressed
                parts.append(cell)
        est, moe = census.sum_with_moe(parts)
        out[name] = {
            "estimate": round(est),
            "moe": round(moe),
            "moe_method": MOE_METHOD,
            "counts": spec["counts"],
            "table": spec["table"],
            "cells": [f"{c}E" for c in spec["cells"]],
            "geography": level,
            "units": _counts(units[level]),
            "suppressed_cells": suppressed,
            "missing_units": missing,
            "source": f"{acs['label']}, table {spec['table']}",
            "vintage": acs["label"],
            "as_of": acs["as_of"],
        }
    return out


def _resilience(tracts: list[Unit], cre: dict, national: dict) -> dict:
    src = census.sources()["cre"]
    count = universe = 0.0
    missing = []
    for t in tracts:
        row = cre.get(t.geoid)
        if row is None or row["count"] is None or row["universe"] is None:
            missing.append(t.geoid)
            continue
        count += row["count"] * t.share
        universe += row["universe"] * t.share
    return {
        "count": round(count),
        "moe": None,
        "moe_note": "The Census Data API's CRE 2024 dataset publishes no margin of "
        "error; PRED3_M is in the tract CSV (cre-2024-tract), not held.",
        "universe": round(universe),
        "rate": round(100 * count / universe, 2) if universe else None,
        "national_rate": national["rate"],
        "counts": "people with three or more components of social vulnerability",
        "variable": src["count"],
        "units": _counts(tracts),
        "missing_tracts": missing,
        "source": f"{src['label']}, tract",
        "vintage": src["label"],
        "as_of": src["as_of"],
    }


def _basis(src: dict, characteristics: dict) -> list:
    tw, dhc, lo, cre = (src[k] for k in ("tigerweb", "dhc", "lodes", "cre"))
    out = [
        basis(
            "geography and area shares",
            f"TIGERweb {tw['vintage']}, {tw['as_of']}",
            None,
        ),
        basis(
            "nighttime residents",
            f"{dhc['label']}, table P1, as of {_mdy(dhc['as_of'])}",
            None,
        ),
        basis(
            "group quarters by type",
            f"{dhc['label']}, table P18, as of {_mdy(dhc['as_of'])}",
            None,
        ),
        basis(
            "daytime workforce",
            f"{lo['label']} {lo['year']}, as of {_mdy(lo['as_of'])}",
            None,
        ),
    ]
    for name, c in characteristics.items():
        out.append(basis(name, f"{c['source']}, as of {_mdy(c['as_of'])}", None))
    out.append(
        basis(
            "resilience",
            f"{cre['label']}, as of {_mdy(cre['as_of'])}",
            None,
        )
    )
    return out


def _flag_inputs(characteristics: dict, resilience: dict) -> dict:
    """The inputs packs/flag_rules.json names for this tool, by their rule names."""
    c = characteristics
    return {
        "gq_population": c["group_quarters_population"]["estimate"],
        "no_vehicle_households": c["no_vehicle_households"]["estimate"],
        "no_vehicle_households_moe": c["no_vehicle_households"]["moe"],
        "limited_english_households": c["limited_english_households"]["estimate"],
        "limited_english_households_moe": c["limited_english_households"]["moe"],
        "pred3_e": resilience["count"],
        "pred3_m": resilience["moe"],
        "pred3_pe": resilience["rate"],
        "national_pred3_pe": resilience["national_rate"],
    }


def _empty(period: str, query: dict, reason: str) -> dict:
    zero = {"total": 0, "whole": 0, "partial": 0}
    return {
        "geography": {
            "blocks": zero,
            "block_groups": zero,
            "tracts": zero,
            "query": query,
        },
        "nighttime": {"total": 0, "group_quarters": {"total": 0, "by_type": {}}},
        "daytime": {"workers": 0},
        "characteristics": {},
        "resilience": {"count": 0},
        "primary": period,
        "reason": reason,
        "limits": list(LIMITS),
    }


async def count(req: PopulationInput) -> dict:
    try:
        footprint = geo.footprint_shape(req.footprint, req.zones)
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
    if req.period:
        period, day_night = req.period, {"period": req.period, "given": True}
    else:
        p = footprint.representative_point()
        day_night = day_or_night(p.y, p.x, req.incident_time)
        period = day_night["period"]
    src = census.sources()
    try:
        census.api_key()
        blocks, block_query = await census.units_in("block", footprint)
        if not blocks:
            return _empty(
                period,
                block_query,
                "No 2020 tabulation block overlaps the footprint (open water or "
                "outside the United States): nobody is counted there.",
            )
        bgs, bg_query = await census.units_in("block_group", footprint)
        tracts, tract_query = await census.units_in("tract", footprint)
        dhc = await census.dhc_blocks(blocks)
        cells = {
            "block_group": await census.acs_cells(bgs, "block_group"),
            "tract": await census.acs_cells(tracts, "tract"),
        }
        cre, national = await census.cre_tracts(tracts)
    except CensusKeyMissing as exc:
        return {
            "error": str(exc),
            "hint": "Set CENSUS_API_KEY in the project .env or the master secrets "
            f"file (DN-004); signup: {census.KEY_SIGNUP_URL}",
        }
    except PageCapExceeded as exc:
        return {"error": str(exc), "hint": geo.TOO_LARGE_HINT}
    except UpstreamServiceError as exc:
        return {"error": str(exc), "hint": "Retry; the Census services may be slow."}

    nighttime = _nighttime(blocks, dhc, src["dhc"])
    work = lodes.jobs(blocks)
    lo = src["lodes"]
    daytime = {
        "workers": round(work["jobs"]),
        "counts": f"jobs located in the footprint (LODES {lo['column']}, total "
        "number of jobs)",
        "from_partial_blocks": round(work["from_partial_blocks"]),
        "share_from_partial_blocks": _share(work["from_partial_blocks"], work["jobs"]),
        "source": f"{lo['label']} {lo['year']} ({lo['segment']}, {lo['job_type']}), "
        f"LODES {lo['version']}",
        "vintage": f"LODES {lo['version']}, {lo['year']}",
        "as_of": lo["as_of"],
        "files": work["files"],
        "missing_states": work["missing_states"],
    }
    characteristics = _characteristics(bgs, tracts, cells)
    resilience = _resilience(tracts, cre, national)
    return {
        "geography": {
            "blocks": _counts(blocks),
            "block_groups": _counts(bgs),
            "tracts": _counts(tracts),
            "states": sorted({b.state for b in blocks}),
            "footprint_area_km2": round(geo.geodesic_area_m2(footprint) / 1e6, 3),
            "query": {
                "block": block_query,
                "block_group": bg_query,
                "tract": tract_query,
            },
        },
        "nighttime": nighttime,
        "daytime": daytime,
        "characteristics": characteristics,
        "resilience": resilience,
        "primary": period,
        "primary_count": "daytime" if period == "day" else "nighttime",
        "day_night": day_night,
        "flag_inputs": _flag_inputs(characteristics, resilience),
        "basis": _basis(src, characteristics),
        "limits": list(LIMITS),
        "notice": census.API_NOTICE,
    }


def register(mcp) -> None:
    census.sources()  # a missing or malformed sources file stops the server at startup

    @mcp.tool(
        name="population_at_risk",
        annotations={
            "title": "Population at Risk",
            "readOnlyHint": True,
            "openWorldHint": True,
        },
    )
    async def population_at_risk(area: PopulationInput) -> dict:
        """Who is inside a footprint: residents (night), jobs (day), group quarters by
        type, people 65 and over, people with a disability, households with no
        vehicle, limited English speaking households, and the Community Resilience
        Estimates count, each with its margin of error where the source has one.

        Pass `area.footprint`, the GeoJSON protective_action_footprint returns (or any
        polygon), the incident time, and optionally its `day_night.period`. Blocks
        partly inside count by the share of their area inside. Both day and night
        counts are always returned; `primary` says which the period makes first.

        Data sources: TIGERweb 2020 tabulation blocks, block groups and tracts; the
        2020 Census DHC (P1, P18) by block; the ACS 2020-2024 5-year by block group
        or tract; LEHD LODES8 workplace area characteristics 2023 (cached state
        files); Community Resilience Estimates 2024 by tract (api.census.gov).
        Update cadence: ACS and CRE annual, LODES annual, the 2020 counts fixed.
        As-of: each count's `as_of` and the `basis` source tags. Requires
        CENSUS_API_KEY; without it, returns `error` with the signup URL.
        """
        return with_notices(await count(area), area=area)
