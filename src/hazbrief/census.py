"""Census reads for `population_at_risk` (HB-09): TIGERweb geography, the 2020 DHC, the
ACS 5-year and the Community Resilience Estimates, through the one upstream client
(`utils.fetch_json`, DN-005 section 2). Every table, cell and vintage is in
`population_sources.yaml`.

**Derived margins of error.** A count summed over cells or geographies carries the MOE
of a sum, the square root of the sum of the squared component MOEs (ACS General
Handbook 2020, chapter 8, formula 1, PDF p. 65), with covariance taken as zero because
the ACS does not publish it (OnTheMap for Emergency Management, "Statistical Methodology
for ACS Data", OTMEM20250302, p. 1). Two OnTheMap EM conventions are adopted with it:
where several components estimate zero, only the largest of their MOEs enters; and a
suppressed or unavailable cell counts as zero and is flagged. A component allocated by
an area share is scaled by that share, estimate and MOE alike (the handbook's product
formula 9, PDF p. 72, with the share carrying no error). The result is approximate, and
the tool says so. The exact alternative, the variance replicate tables (handbook PDF
p. 64), covers selected tables only and is not used.

**Annotation values** (Census Bureau, "Notes on ACS Estimate and Annotation Values",
revised 2026-07-20): -666666666, -999999999, -888888888 for an estimate that cannot be
computed, displayed or applied; -222222222 and -333333333 for an MOE that cannot be
computed; -555555555 for an MOE "not appropriate because the corresponding estimate is
controlled", which this module reads as an exact estimate (MOE zero).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import yaml

from hazbrief import geo
from hazbrief.config import settings
from hazbrief.geometry import COORDINATE_DECIMALS
from hazbrief.utils import PageCapExceeded, UpstreamServiceError, fetch_json

SOURCES_FILE = Path(__file__).with_name("population_sources.yaml")
#: Every key `population_sources.yaml` must carry, by section.
REQUIRED = {
    "tigerweb": (
        "service",
        "vintage",
        "as_of",
        "layers",
        "out_fields",
        "page_size",
        "max_features_per_layer",
    ),
    "dhc": (
        "dataset",
        "label",
        "as_of",
        "total",
        "group_quarters_total",
        "group_quarters_types",
    ),
    # HB-94 (review L5-3): no `label`; it is derived from `dataset` (`acs_label`)
    "acs": ("dataset", "as_of", "characteristics"),
    "cre": ("dataset", "label", "as_of", "count", "rate", "universe", "moe_available"),
    "lodes": (
        "version",
        "year",
        "segment",
        "job_type",
        "column",
        "label",
        "as_of",
        "url_template",
    ),
}
CHARACTERISTIC_KEYS = ("table", "geography", "cells", "counts")
LEVELS = ("block", "block_group", "tract")
#: The Census Data API's limit: "You can include up to 50 variables in a single API
#: query" (census-api-query-limits).
MAX_VARIABLES = 50
#: -555555555: "A margin of error is not appropriate because the corresponding estimate
#: is controlled" (module docstring).
CONTROLLED = -555555555
KEY_SIGNUP_URL = "https://api.census.gov/data/key_signup.html"
#: Census Data API terms of service, the required notice (corpus/api_catalog.yaml).
API_NOTICE = (
    "This product uses the Census Bureau Data API but is not endorsed or certified by "
    "the Census Bureau."
)


class SourcesError(RuntimeError):
    """`population_sources.yaml` is missing or lacks a required key."""


#: An ACS dataset path of the Census Data API: `<vintage>/acs/acs<span>`.
_ACS_DATASET = re.compile(r"(\d{4})/acs/acs([15])")


def acs_label(dataset: str) -> str:
    """The ACS label from its dataset path (HB-94, review L5-3: the URL year and the
    label are one constant): `2024/acs/acs5` is "ACS 2020-2024 5-year", the five
    collection years the 2024 5-year estimates span; `2024/acs/acs1` is "ACS 2024
    1-year"."""
    m = _ACS_DATASET.fullmatch(dataset)
    if not m:
        raise SourcesError(f"acs.dataset {dataset!r} is not <year>/acs/acs1 or acs5")
    year, span = int(m.group(1)), int(m.group(2))
    years = f"{year - span + 1}-{year}" if span > 1 else str(year)
    return f"ACS {years} {span}-year"


class CensusKeyMissing(RuntimeError):
    """CENSUS_API_KEY is not set: every Census data query requires one (May 2026)."""


def load_sources(path: Path = SOURCES_FILE) -> dict:
    if not path.is_file():
        raise SourcesError(f"population sources not found: {path}")
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for section, keys in REQUIRED.items():
        missing = [k for k in keys if k not in (doc.get(section) or {})]
        if missing:
            raise SourcesError(f"{path}: {section} lacks {', '.join(missing)}")
    for name, c in doc["acs"]["characteristics"].items():
        missing = [k for k in CHARACTERISTIC_KEYS if k not in c]
        if missing or c["geography"] not in ("block_group", "tract"):
            raise SourcesError(f"{path}: acs.characteristics.{name} is malformed")
    if "label" in doc["acs"]:
        raise SourcesError(f"{path}: acs.label is derived from acs.dataset; drop it")
    doc["acs"]["label"] = acs_label(doc["acs"]["dataset"])
    return doc


@lru_cache(maxsize=1)
def sources() -> dict:
    return load_sources()


def api_key() -> str:
    if not settings.census_api_key:
        raise CensusKeyMissing(
            "CENSUS_API_KEY is not set. The Census Data API requires a key on every "
            f"data query; request one at {KEY_SIGNUP_URL}."
        )
    return settings.census_api_key


# ── Estimates and margins of error ────────────────────────────────────────────


@dataclass(frozen=True)
class Cell:
    """One published estimate and its MOE (90 percent), or a scaled share of one."""

    estimate: float
    moe: float
    suppressed: bool = False

    def scaled(self, share: float) -> Cell:
        return Cell(self.estimate * share, self.moe * share, self.suppressed)


def _number(value) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def cell_from_api(estimate, moe) -> Cell:
    """A cell as the API returns it (strings, None, or annotation sentinels)."""
    e, m = _number(estimate), _number(moe)
    if e is None or e < 0:
        return Cell(0.0, 0.0, suppressed=True)
    if m is None:
        return Cell(e, 0.0, suppressed=True)
    if m == CONTROLLED:
        return Cell(e, 0.0)
    if m < 0:
        return Cell(e, 0.0, suppressed=True)
    return Cell(e, m)


def sum_with_moe(cells: Iterable[Cell]) -> tuple[float, float]:
    """`(estimate, moe)` of a sum: root sum of squares, zero covariance, and among
    zero-estimate cells only the largest MOE."""
    cells = list(cells)
    estimate = sum(c.estimate for c in cells)
    nonzero = [c.moe for c in cells if c.estimate != 0]
    zero = [c.moe for c in cells if c.estimate == 0]
    squares = [m * m for m in nonzero] + ([max(zero) ** 2] if zero else [])
    return estimate, math.sqrt(sum(squares))


# ── Geography (TIGERweb) ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class Unit:
    """A block, block group or tract and the share of its area inside the footprint."""

    level: str
    geoid: str
    share: float
    kind: str  # "whole" or "partial"
    state: str
    county: str
    tract: str


def envelope(footprint) -> str:
    """The footprint's bounding box, rounded outward to six decimals of a degree, so a
    query's URL (and its recorded exchange) is stable."""
    minx, miny, maxx, maxy = footprint.bounds
    lo = [math.floor(v * 1e6) / 1e6 for v in (minx, miny)]
    hi = [math.ceil(v * 1e6) / 1e6 for v in (maxx, maxy)]
    return ",".join(f"{v:.6f}" for v in (lo[0], lo[1], hi[0], hi[1]))


async def _tigerweb_features(level: str, bbox: str) -> tuple[list, list]:
    """Every feature of `level` intersecting `bbox`, paged in GEOID order; and the
    exchanges' urls."""
    tw = sources()["tigerweb"]
    path = f"{tw['service']}/{tw['layers'][level]}/query"
    page, offset, features, urls = int(tw["page_size"]), 0, [], []
    max_pages = math.ceil(int(tw["max_features_per_layer"]) / page)
    while True:
        if len(urls) >= max_pages:
            raise PageCapExceeded(
                f"TIGERweb {level} query reached its cap of {max_pages} pages of "
                f"{page}; the footprint's bounding box holds too many {level}s."
            )
        ex = await fetch_json(
            "tigerweb",
            path,
            params={
                "geometry": bbox,
                "geometryType": "esriGeometryEnvelope",
                "inSR": "4326",
                "spatialRel": "esriSpatialRelIntersects",
                "outFields": tw["out_fields"][level],
                "returnGeometry": "true",
                "outSR": "4326",
                # Six decimals of a degree, about 10 cm (RFC 7946 section 11.2), as
                # geometry.COORDINATE_DECIMALS writes the footprint itself.
                "geometryPrecision": str(COORDINATE_DECIMALS),
                "orderByFields": "GEOID",
                "resultOffset": str(offset),
                "resultRecordCount": str(page),
                "f": "geojson",
            },
        )
        urls.append(ex.url)
        body = ex.body if isinstance(ex.body, dict) else {}
        if "error" in body or "features" not in body:
            # TIGERweb answers an error object with HTTP 200 (corpus/api_catalog.yaml).
            raise UpstreamServiceError("TIGERweb returned an error object.")
        features += body["features"]
        # A server whose maxRecordCount is below `page` answers a short page with
        # exceededTransferLimit (top level, or under `properties` in GeoJSON), so a
        # short page is the last only without it (review L2-11; as arcgis_features).
        more = body.get("exceededTransferLimit") or (body.get("properties") or {}).get(
            "exceededTransferLimit"
        )
        if (not more and len(body["features"]) < page) or not body["features"]:
            return features, urls
        offset += len(body["features"])


async def units_in(level: str, footprint) -> tuple[list[Unit], dict]:
    """The units of `level` whose area overlaps the footprint, with their shares; and
    the query record (layer, vintage, envelope, urls)."""
    tw = sources()["tigerweb"]
    bbox = envelope(footprint)
    features, urls = await _tigerweb_features(level, bbox)
    out = []
    for f in features:
        props = f.get("properties") or {}
        geometry = f.get("geometry")
        if not geometry:
            continue
        share, kind = geo.area_share(geo.shape(geometry), footprint)
        if kind is None:
            continue
        out.append(
            Unit(
                level=level,
                geoid=str(props["GEOID"]),
                share=share,
                kind=kind,
                state=str(props["STATE"]),
                county=str(props["COUNTY"]),
                tract=str(props["TRACT"]),
            )
        )
    query = {
        "service": f"TIGERweb/{tw['service']}",
        "layer": tw["layers"][level],
        "vintage": tw["vintage"],
        "envelope": bbox,
        "spatial_relation": "esriSpatialRelIntersects, then the area share by GEOS",
        "candidates": len(features),
        "urls": urls,
    }
    return out, query


# ── Census Data API ───────────────────────────────────────────────────────────


async def table_rows(dataset: str, variables: list[str], geo_for: str, geo_in: str):
    """Rows of `dataset` as dicts, the variables read in chunks under the API's limit
    and joined on the geography columns."""
    key = api_key()
    rows: dict[tuple, dict] = {}
    for i in range(0, len(variables), MAX_VARIABLES):
        chunk = variables[i : i + MAX_VARIABLES]
        params = {"get": ",".join(chunk), "for": geo_for, "key": key}
        if geo_in:
            params["in"] = geo_in
        ex = await fetch_json("census", dataset, params=params)
        body = ex.body
        if not isinstance(body, list) or not body or not isinstance(body[0], list):
            raise UpstreamServiceError("Census Data API returned no table.")
        header = body[0]
        geo_cols = [h for h in header if h not in chunk]
        for r in body[1:]:
            row = dict(zip(header, r))
            rows.setdefault(tuple(row[c] for c in geo_cols), {}).update(row)
    return list(rows.values())


def block_geoid(row: dict) -> str:
    return row["state"] + row["county"] + row["tract"] + row["block"]


def block_group_geoid(row: dict) -> str:
    return row["state"] + row["county"] + row["tract"] + row["block group"]


def tract_geoid(row: dict) -> str:
    return row["state"] + row["county"] + row["tract"]


async def dhc_blocks(blocks: list[Unit]) -> dict[str, dict]:
    """Block GEOID -> {total, group_quarters_total, group_quarters: {type: count},
    null_cells}, read tract by tract (the API takes blocks within a tract). A cell the
    API returns null is None in `total` and `group_quarters_total`, left out of a type's
    sum, and named in `null_cells`: not a zero (review L2-5; the ACS path's
    `cell_from_api` reports the same case as suppressed)."""
    d = sources()["dhc"]
    types = d["group_quarters_types"]
    variables = [d["total"], d["group_quarters_total"]] + [
        v for cells in types.values() for v in cells
    ]
    wanted = {b.geoid for b in blocks}
    out: dict[str, dict] = {}
    for st, co, tr in sorted({(b.state, b.county, b.tract) for b in blocks}):
        for row in await table_rows(
            d["dataset"], variables, "block:*", f"state:{st} county:{co} tract:{tr}"
        ):
            g = block_geoid(row)
            if g not in wanted:
                continue
            out[g] = {
                "total": _number(row[d["total"]]),
                "group_quarters_total": _number(row[d["group_quarters_total"]]),
                "group_quarters": {
                    t: sum(n for v in cells if (n := _number(row[v])) is not None)
                    for t, cells in types.items()
                },
                "null_cells": [v for v in variables if _number(row[v]) is None],
            }
    return out


def _acs_variables(level: str) -> list[str]:
    chars = sources()["acs"]["characteristics"]
    cells = [
        c for ch in chars.values() if ch["geography"] == level for c in ch["cells"]
    ]
    return [f"{c}{suffix}" for c in cells for suffix in ("E", "M")]


async def acs_cells(units: list[Unit], level: str) -> dict[str, dict]:
    """GEOID -> {cell: Cell} for every ACS characteristic published at `level`."""
    acs = sources()["acs"]
    variables = _acs_variables(level)
    if not variables or not units:
        return {}
    wanted = {u.geoid for u in units}
    out: dict[str, dict] = {}
    if level == "block_group":
        scopes = sorted({(u.state, u.county, u.tract) for u in units})
        queries = [
            ("block group:*", f"state:{s} county:{c} tract:{t}") for s, c, t in scopes
        ]
        geoid = block_group_geoid
    else:
        scopes = sorted({(u.state, u.county) for u in units})
        queries = [("tract:*", f"state:{s} county:{c}") for s, c in scopes]
        geoid = tract_geoid
    for geo_for, geo_in in queries:
        for row in await table_rows(acs["dataset"], variables, geo_for, geo_in):
            g = geoid(row)
            if g in wanted:
                out[g] = {
                    v[:-1]: cell_from_api(row[v], row[v[:-1] + "M"])
                    for v in variables
                    if v.endswith("E")
                }
    return out


async def cre_tracts(tracts: list[Unit]) -> tuple[dict[str, dict], dict]:
    """Tract GEOID -> {count, universe, rate}; and the national row."""
    c = sources()["cre"]
    variables = [c["count"], c["universe"], c["rate"]]
    wanted = {t.geoid for t in tracts}
    out: dict[str, dict] = {}
    for st, co in sorted({(t.state, t.county) for t in tracts}):
        for row in await table_rows(
            c["dataset"], variables, "tract:*", f"state:{st} county:{co}"
        ):
            g = tract_geoid(row)
            if g in wanted:
                out[g] = {
                    "count": _number(row[c["count"]]),
                    "universe": _number(row[c["universe"]]),
                    "rate": _number(row[c["rate"]]),
                }
    [us] = await table_rows(c["dataset"], variables, "us:1", "")
    national = {
        "count": _number(us[c["count"]]),
        "universe": _number(us[c["universe"]]),
        "rate": _number(us[c["rate"]]),
    }
    return out, national
