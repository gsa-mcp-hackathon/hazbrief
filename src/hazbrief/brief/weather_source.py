"""The brief's weather source: forecast, observed or stated (DN-019 ADDENDUM-01).

HB-139.

A brief has one wind record (HB-133, `hazbrief.brief.wind_record`), and that record has
one of three sources, chosen here and named on the first screen:

* **forecast** (the default): the NWS gridpoint forecast's cell at the as-given hour, as
  HB-133 resolves it;
* **observed**: an observation read from a held dataset. Since HB-143 the default
  dataset is the live NWS station observations (`nws:observations`, a row of the source
  catalog), read by `observed_wind` as one representative station with the others as a
  spread. A dataset with no client refuses: not a row, naming the acquisition; a corpus
  row (an archive for a past hour, DN-019 ADDENDUM-01), naming Issue 07c07030;
* **stated**: a wind given in full with a `basis` (a worked example, a drill's notional
  conditions, an exercise injection). Never the default, never inferred: a null field
  refuses, naming it.

The three follow the held manuals' weather inputs (HPAC: real-time data from
Meteorological Data Servers, and climatology or historical data when real data is not
available, `osd-ncbdp-specialized-radiological` PDF p. 1; ALOHA: entered manually or
from a portable SAM station, `epa-aloha-users-manual-2007` PDF p. 36); climatology is
left out on purpose (ADDENDUM-01 section 2).

**Where it is set, in order** (each overrides the one before, field by field):
`orchestrator.yaml` `weather` (`source`, `observed`, `stated`); the scenario file's
`weather:` block, which must carry a `basis` (a fixture never sets the source silently;
the brief prints the basis); the run's own fields (the CLI's flags, the `--serve` page's
query), named in `FIELDS` so every surface takes the same names and one schema
(`Weather`) validates them all.

The MCP server takes no part: it starts no brief (the brief application is its client,
CLAUDE), so the "MCP tool that starts a brief" of ADDENDUM-01 section 4 does not
exist, and the server's tool surface is frozen to the submission (DN-009 section 2). A
caller of the server already supplies a stated wind through the tools' `wind`
(`WindObservation`, with its `source`).
"""

from __future__ import annotations

from functools import cache
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from hazbrief.config import REPO_ROOT

SOURCES = ("forecast", "observed", "stated")
#: the five fields a stated wind is given in, in the order a refusal names the first
#: null one (ADDENDUM-01 section 4's block)
STATED_FIELDS = (
    "direction_from_deg",
    "speed_kmh",
    "stability_class",
    "mixing_height_m",
    "basis",
)

#: the run's own fields, one name per field on every surface (the CLI's
#: `--weather-source`, the `--serve` page's `?weather_source=`), and where each sits in
#: the block
FIELDS: dict[str, tuple[str, ...]] = {
    "weather_source": ("source",),
    "weather_basis": ("basis",),
    "observed_dataset": ("observed", "dataset"),
    "observed_tolerance_minutes": ("observed", "tolerance_minutes"),
    "observed_stations": ("observed", "stations"),
    "observed_min_stations": ("observed", "min_stations"),
    "stated_direction_from_deg": ("stated", "direction_from_deg"),
    "stated_speed_kmh": ("stated", "speed_kmh"),
    "stated_stability_class": ("stated", "stability_class"),
    "stated_mixing_height_m": ("stated", "mixing_height_m"),
    "stated_basis": ("stated", "basis"),
}


#: a query parameter with one of these prefixes is read as a weather field, so a
#: misspelt one is refused by name rather than ignored
FIELD_PREFIXES = ("weather_", "observed_", "stated_")

#: each field's help line and the type its text is read as (the CLI and the page's
#: query both give text; `from_text` reads it, so both refuse alike)
FIELD_HELP: dict[str, tuple[str, type]] = {
    "weather_source": ("forecast, observed or stated", str),
    "weather_basis": ("why this source, printed on the brief", str),
    "observed_dataset": ("the observed dataset's corpus row (doc_id)", str),
    "observed_tolerance_minutes": ("minutes from the hour an observation covers", int),
    "observed_stations": ("observed: the nearest NWS stations read (HB-143)", int),
    "observed_min_stations": ("observed: fresh stations needed, else forecast", int),
    "stated_direction_from_deg": ("stated: degrees the wind blows from", float),
    "stated_speed_kmh": ("stated: wind speed, km/h", float),
    "stated_stability_class": ("stated: Pasquill-Gifford class A to F", str),
    "stated_mixing_height_m": ("stated: mixing height, m", float),
    "stated_basis": ("stated: the basis (drill plan, worked example)", str),
}


def from_text(values: dict) -> dict:
    """The run's fields as text (the CLI's flags, the page's query) read by
    `FIELD_HELP`'s types; an empty or absent value is not given. An unknown name or a
    value that does not read as its type is refused, naming the field."""
    out: dict = {}
    for name, v in values.items():
        if name not in FIELD_HELP:
            raise WeatherRefused(
                f"{name} is not a weather field (one of {', '.join(FIELD_HELP)})", name
            )
        if v is None or v == "":
            continue
        kind = FIELD_HELP[name][1]
        try:
            out[name] = kind(v)
        except ValueError:
            raise WeatherRefused(
                f"{name}: {v!r} is not {'an integer' if kind is int else 'a number'}",
                name,
            ) from None
    return out


class WeatherRefused(ValueError):
    """The weather selection is refused; the message names the field or the
    acquisition, and `field` is the block path it concerns."""

    def __init__(self, message: str, field: str):
        super().__init__(message)
        self.field = field


class Observed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset: str | None = Field(default=None, min_length=1)
    tolerance_minutes: int = Field(gt=0)
    # HB-143: the nearest stations read and the fresh ones the method needs (one
    # representative station; docs/evidence/hb143/prior_art.md)
    stations: int = Field(gt=0)
    min_stations: int = Field(gt=0)


class Stated(BaseModel):
    model_config = ConfigDict(extra="forbid")

    direction_from_deg: float | None = Field(default=None, ge=0, le=360)
    speed_kmh: float | None = Field(default=None, ge=0, le=400)
    # Pasquill-Gifford A to F, the classes the stability key yields (DN-016 ADDENDUM-00)
    stability_class: Literal["A", "B", "C", "D", "E", "F"] | None = None
    mixing_height_m: float | None = Field(default=None, gt=0)
    basis: str | None = Field(default=None, min_length=1)


class Weather(BaseModel):
    """The `weather` block's source keys (ADDENDUM-01 section 4), validated."""

    model_config = ConfigDict(extra="forbid")

    source: Literal["forecast", "observed", "stated"]
    observed: Observed
    stated: Stated
    #: why this source: required of a scenario file's block, optional elsewhere
    basis: str | None = Field(default=None, min_length=1)


def _schema(cfg: dict) -> dict:
    return cfg["weather"]["source_schema"]


def _refusal(cfg: dict, key: str, where: str, **kw) -> WeatherRefused:
    return WeatherRefused(_schema(cfg)["refusals"][key].format(**kw), where)


def configured(cfg: dict) -> dict:
    """The source keys of `orchestrator.yaml` `weather`, as a plain block."""
    w = cfg["weather"]
    return {
        "source": w["source"],
        "observed": dict(w["observed"]),
        "stated": dict(w["stated"]),
    }


def _merge(base: dict, over: dict) -> dict:
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in base.items()}
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = {**out[k], **v}
        else:
            out[k] = v
    return out


def from_fields(values: dict) -> dict:
    """The run's flat fields (`FIELDS`' names; None or absent: not given) as a partial
    block. An unknown name is refused, so a misspelt flag never passes silently."""
    out: dict = {}
    for name, v in values.items():
        if name not in FIELDS:
            raise WeatherRefused(
                f"{name} is not a weather field (one of {', '.join(FIELDS)})", name
            )
        if v is None or v == "":
            continue
        path = FIELDS[name]
        d = out
        for p in path[:-1]:
            d = d.setdefault(p, {})
        d[path[-1]] = v
    return out


@cache
def _source_rows() -> frozenset[str]:
    doc = yaml.safe_load((REPO_ROOT / "corpus" / "sources.yaml").read_text("utf-8"))
    return frozenset(r["doc_id"] for r in doc.get("sources") or [] if "doc_id" in r)


@cache
def _catalog_rows() -> frozenset[str]:
    """The source catalog's row ids (DN-010 section 3.2: `docs/sources/catalog.yaml`),
    the registry a live dataset is read through (HB-143)."""
    from hazbrief.evidence import catalog

    return frozenset(r["id"] for r in catalog.rows())


def _validate(block: dict, cfg: dict) -> Weather:
    try:
        w = Weather.model_validate(block)
    except ValidationError as exc:
        first = exc.errors()[0]
        field = ".".join(str(x) for x in first.get("loc") or ())
        raise _refusal(cfg, "invalid", field, field=field, why=first["msg"]) from None
    limit = int(_schema(cfg)["basis_max_chars"])
    for field, text in (("basis", w.basis), ("stated.basis", w.stated.basis)):
        if text is not None and len(text) > limit:
            raise _refusal(
                cfg,
                "invalid",
                field,
                field=field,
                why=f"at most {limit} characters (the server's wind source holds 200)",
            )
    return w


def select(
    cfg: dict,
    scenario_block: dict | None = None,
    run_fields: dict | None = None,
) -> dict:
    """The brief's weather selection: the configuration, then the scenario file's block
    (which must carry a basis), then the run's fields; validated by one schema and
    refused, naming the field or the acquisition, when it cannot be read. Returns the
    validated block with `set_by` (configuration, scenario or run) and, for a scenario
    block, its `basis`."""
    block = configured(cfg)
    set_by = "configuration"
    if scenario_block is not None:
        if not isinstance(scenario_block, dict):
            raise _refusal(
                cfg, "invalid", "weather", field="weather", why="must be a mapping"
            )
        stated = scenario_block.get("stated") or {}
        if not (scenario_block.get("basis") or stated.get("basis")):
            raise _refusal(cfg, "fixture_no_basis", "weather.basis")
        block = _merge(block, scenario_block)
        set_by = "scenario"
    given = from_fields(run_fields or {})
    if given:
        block = _merge(block, given)
        set_by = "run"
    w = _validate(block, cfg)
    if w.source == "stated":
        for f in STATED_FIELDS:
            if getattr(w.stated, f) is None:
                raise _refusal(cfg, "stated_null", f"stated.{f}", field=f)
    elif w.source == "observed":
        ds = w.observed.dataset
        if ds is None:
            raise _refusal(cfg, "observed_no_dataset", "observed.dataset")
        # HB-143: a dataset with a client (the live NWS station observations) is read
        # through its source-catalog row and needs that row; a corpus row with no client
        # (an archive, Issue 07c07030) still refuses, naming the client's Issue
        if ds in cfg["weather"]["observed_client"]["clients"]:
            if ds not in _catalog_rows():
                raise _refusal(
                    cfg, "observed_client_row_missing", "observed.dataset", dataset=ds
                )
        elif ds not in _source_rows():
            raise _refusal(cfg, "observed_not_a_row", "observed.dataset", dataset=ds)
        else:
            raise _refusal(
                cfg,
                "observed_no_client",
                "observed.dataset",
                dataset=ds,
                issue=_schema(cfg)["observed_client_issue"],
            )
    out = w.model_dump()
    out["set_by"] = set_by
    if set_by == "scenario":
        out["basis"] = (scenario_block or {}).get("basis") or w.stated.basis
    return out
