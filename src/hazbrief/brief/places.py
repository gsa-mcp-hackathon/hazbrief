"""CDC PLACES census-tract prevalence of the smoke-sensitive conditions (DN-021 section
5; HB-128 step 6).

Reads the PLACES 2025 release's census-tract file in GIS-friendly format (data.cdc.gov
`yjkw-uj5s`; corpus row `cdc-places-tract-gis-2025`), as a slice for some states that
`the HB-128 evidence` fetched into `corpus/raw/`. Three
measures, each the crude prevalence among adults and its 95 percent interval, as the
file prints them:

- current asthma (`CASTHMA`), chronic obstructive pulmonary disease (`COPD`) and
  coronary heart disease (`CHD`): the conditions the EPA's wildfire-smoke guide and AQI
  document name for the sensitive groups (people with heart or lung disease;
  `packs/src/aqi_pm25_breakpoints.json`, `method.sensitive_groups`).

What a value is: a model-based estimate, not a count. The dataset's own description
begins "This dataset contains model-based census tract level estimates"
(`cdc-places-tract-gis-2025-metadata`), and the methodology page says PLACES uses "a
multilevel regression and poststratification (MRP) method" on BRFSS, ACS and census
counts (`cdc-places-methodology`). Every caller labels the values with `LABEL`.

A tract the release does not estimate is `None` for that measure, never 0. The 2025
release prints no estimate of these three measures for 4,707 of its 83,522 tracts, every
Pennsylvania tract among them (3,408 of 3,408; the metadata's null counts and the held
slice, HB-128 RESULT). Why is not held.

`hazbrief.brief.smoke.places_rows` reads it per AQI band (HB-129); no fire brief
prints band rows until VSMOKE is built (Issue 69cc2af7), so the brief prints `LABEL`
alone. Standard library only.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

#: The measures read, by the file's column prefix, with the definitions' own names
#: (`cdc-places-measure-definitions-health-outcomes`).
MEASURES = {
    "casthma": "Current asthma among adults",
    "copd": "Chronic obstructive pulmonary disease among adults",
    "chd": "Coronary heart disease among adults",
}
#: The columns every row must carry, besides each measure's `_crudeprev` and
#: `_crude95ci`.
ID_COLUMNS = (
    "stateabbr",
    "countyname",
    "countyfips",
    "tractfips",
    "totalpopulation",
    "totalpop18plus",
)
#: The cap `fetch_places_slice.py` puts on the query (`$limit`): a slice with exactly
#: this many rows may be truncated.
ROW_CAP = 50000
#: The label every value carries, from the dataset's description and the methodology
#: page (held pages above).
LABEL = (
    "CDC PLACES 2025 release, census tract: model-based estimates of crude "
    "prevalence among adults (multilevel regression and poststratification of "
    "BRFSS 2023 with Census 2020 and ACS), not counts"
)
_CI = re.compile(r"^\(\s*([0-9.]+),\s*([0-9.]+)\)$")


class PlacesError(ValueError):
    """The file is not the PLACES tract file this module reads. The message is one
    line."""


@dataclass(frozen=True)
class Estimate:
    """Crude prevalence among adults, percent, and its 95 percent interval."""

    percent: float
    ci95: tuple[float, float]


@dataclass(frozen=True)
class Tract:
    tractfips: str
    state: str
    county: str
    population: int
    adults: int
    #: measure key (`MEASURES`) to its estimate, or None where the release prints none
    measures: dict[str, Estimate | None]

    def adults_with(self, measure: str) -> float | None:
        """The estimated number of adults with the condition: prevalence times adults
        (Census 2020), or None."""
        e = self.measures[measure]
        return None if e is None else e.percent / 100.0 * self.adults


def _estimate(row: dict, key: str, where: str) -> Estimate | None:
    prev, ci = row[f"{key}_crudeprev"].strip(), row[f"{key}_crude95ci"].strip()
    if not prev and not ci:
        return None
    m = _CI.match(ci)
    if not prev or m is None:
        raise PlacesError(
            f"{where}: {key} prints {prev!r} with interval {ci!r}; "
            "want a percent and '(lo, hi)'"
        )
    return Estimate(float(prev), (float(m.group(1)), float(m.group(2))))


def load(path: str | Path) -> dict[str, Tract]:
    """Every tract in the file, by its 11-digit FIPS code. Refuses a file without the
    columns, with a duplicate
    tract, a malformed value, or exactly ROW_CAP rows (a possibly truncated query)."""
    p = Path(path)
    if not p.is_file():
        raise PlacesError(
            f"{p} is not held: fetch it with "
            "the HB-128 evidence (corpus row "
            "cdc-places-tract-gis-2025)"
        )
    with p.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        need = set(ID_COLUMNS) | {
            f"{k}_{s}" for k in MEASURES for s in ("crudeprev", "crude95ci")
        }
        missing = sorted(need - set(reader.fieldnames or ()))
        if missing:
            raise PlacesError(
                f"{p}: not the PLACES tract file; missing columns {missing}"
            )
        out: dict[str, Tract] = {}
        for n, row in enumerate(reader, start=2):
            fips = row["tractfips"].strip()
            where = f"{p.name} line {n} (tract {fips})"
            if not re.fullmatch(r"\d{11}", fips):
                raise PlacesError(f"{where}: tractfips is not 11 digits")
            if fips in out:
                raise PlacesError(f"{where}: tract printed twice")
            out[fips] = Tract(
                tractfips=fips,
                state=row["stateabbr"].strip(),
                county=row["countyname"].strip(),
                population=int(row["totalpopulation"]),
                adults=int(row["totalpop18plus"]),
                measures={k: _estimate(row, k, where) for k in MEASURES},
            )
    if len(out) == ROW_CAP:
        raise PlacesError(
            f"{p}: exactly {ROW_CAP} rows, the query's cap; the slice may be truncated"
        )
    return out
