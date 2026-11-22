"""Pydantic models and enums for tool parameters and responses.

Typed parameters give MCP clients a precise schema, which helps the LLM call
your tools correctly. Prefer enums for closed sets of values and Pydantic
models for structured inputs/outputs.

The tool inputs (HB-08) come first; the knowledge pack models (HB-03) follow.
"""

from __future__ import annotations

import json
import re
from enum import Enum
from typing import Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    field_validator,
    model_validator,
)


class ResponseFormat(str, Enum):
    """How a tool should shape its return value.

    - JSON     → machine-readable dict/list (best for chaining tool calls)
    - MARKDOWN → human-readable text (best for direct display)
    """

    JSON = "json"
    MARKDOWN = "markdown"


class PaginationParams(BaseModel):
    """Reusable pagination inputs for list-style tools.

    Federal APIs almost always paginate. Expose these to the caller (or handle
    paging internally) and return `has_more` / `next_offset` in your response.
    """

    limit: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum number of items to return (1–100).",
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Number of items to skip from the start of the result set.",
    )


# ── Tool inputs (HB-08) ───────────────────────────────────────────────────────────────


#: HB-18 (A-1): the notice a tool output carries for an argument sent as a JSON string.
JSON_STRING_NOTICE = (
    "This argument arrived as a JSON string, not an object; it was parsed once. Send "
    "the object itself."
)


#: C0 control characters and DEL: a newline or carriage return would start a new
#: Markdown line in the ICS 201 (a fake heading or source tag), an escape a terminal
#: sequence (review L3-6).
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def plain_text(value: Any) -> Any:
    """A caller's free-text value, stripped, refused when it holds a control character.
    A `mode="before"` validator, not a schema `pattern`: the tool surface is frozen
    until the submission (DN-009 section 2), and the refusal is the same."""
    if not isinstance(value, str):
        return value
    if _CONTROL.search(value):
        raise ValueError(
            "must not contain a control character (a newline, tab or escape)"
        )
    return value.strip()


class ToolInput(BaseModel):
    """A tool's object argument. HB-18 (A-1): an agent may send the object as a JSON
    string (HB-16: Haiku and Sonnet did, LN-07 F3). A string that parses, whole, to one
    JSON object is accepted once, and `parsed_from_string` records it, so the tool's
    output can say so (`json_string_notices`). Any other string is rejected with where
    it stops being one object: malformed JSON is never repaired, and a string of a
    string is not parsed twice."""

    _parsed_from_string: bool = PrivateAttr(default=False)

    @model_validator(mode="wrap")
    @classmethod
    def _one_json_object(cls, data: Any, handler):
        if not isinstance(data, str):
            return handler(data)
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "a string was sent where an object is expected, and it is not one "
                f"JSON object ({exc.msg} at character {exc.pos}). Send the object "
                "itself."
            ) from None
        if not isinstance(parsed, dict):
            raise ValueError(
                "a string was sent where an object is expected, and it parses to a "
                f"JSON {type(parsed).__name__}, not an object. Send the object itself."
            )
        model = handler(parsed)
        model._parsed_from_string = True
        return model

    @property
    def parsed_from_string(self) -> bool:
        return self._parsed_from_string


def json_string_notices(**params: BaseModel | None) -> list[dict]:
    """A notice for every tool argument, or object inside one, that arrived as a JSON
    string (HB-18, A-1), named by its path ("request.incident")."""
    out: list[dict] = []

    def walk(m, path: str) -> None:
        if isinstance(m, ToolInput) and m.parsed_from_string:
            out.append({"notice": JSON_STRING_NOTICE, "parameter": path})
        if isinstance(m, BaseModel):
            for name in type(m).model_fields:
                walk(getattr(m, name), f"{path}.{name}")

    for name, m in params.items():
        walk(m, name)
    return out


def with_notices(result: dict, **params: BaseModel | None) -> dict:
    """`result` with `json_string_notices(**params)` added to its `errors` list."""
    notices = json_string_notices(**params)
    if notices:
        result = dict(result)
        result["errors"] = list(result.get("errors") or []) + notices
    return result


class SpillSize(str, Enum):
    """ERG spill size: "A SMALL SPILL consists of a release of 208 liters (55 US
    gallons) or less ... A LARGE SPILL consists of a release of more than 208 liters
    (55 US gallons)" (ERG 2024 PDF p. 290)."""

    SMALL = "small"
    LARGE = "large"
    UNKNOWN = "unknown"


class Location(ToolInput):
    """A point, WGS84 decimal degrees."""

    model_config = ConfigDict(extra="forbid")

    latitude: float = Field(ge=-90, le=90, description="Latitude, WGS84 degrees.")
    longitude: float = Field(ge=-180, le=180, description="Longitude, WGS84 degrees.")


class IncidentInput(ToolInput):
    """A transported-hazmat incident as reported. The load is given by exactly one of
    `material`, `placard` and `guide_number`: the ERG's Table of Markings, Labels and
    Placards is for "when the ID number or proper shipping name is not available" (ERG
    2024 PDF p. 9)."""

    # HB-15 added `placard` and `guide_number`. HB-18 (A-5): a docstring here is the
    # schema's description an agent reads, so it names no internal task or note.

    model_config = ConfigDict(extra="forbid")

    material: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        description=(
            "The ID number from the placard or shipping paper (UN1017, NA1993 or "
            "1017), or the material name as the ERG yellow index prints it (Chlorine; "
            "a generic name may drop its ', n.o.s.'; an explosive the index lists by "
            "name, such as 'Blasting agent' or ANFO, resolves to its guide). Omit it "
            "when the material is not identified, and give `placard` or "
            "`guide_number`."
        ),
    )
    placard: str | None = Field(
        default=None,
        min_length=1,
        max_length=60,
        description=(
            "For a load with no ID number or name: the placard as read, which the "
            "ERG's Table of Markings, Labels and Placards sends to a guide. The class "
            "or division printed on it (2.3, 1.4, 8), a word printed on it (FLAMMABLE "
            "GAS, OXYGEN, GASOLINE), DANGEROUS, or none when hazardous materials are "
            "suspected and no placard can be seen. A class whose divisions have their "
            "own guides (2, 4, 5, 6) returns the candidates."
        ),
    )
    guide_number: str | None = Field(
        default=None,
        min_length=3,
        max_length=10,
        description=(
            "For a load with no ID number or name: an ERG orange guide number, such as "
            "111 (Mixed Load/Unidentified Cargo), 112 (explosives, Divisions 1.1, 1.2, "
            "1.3, 1.5) or 114 (Divisions 1.4, 1.6)."
        ),
    )
    container: str = Field(
        min_length=1,
        max_length=100,
        description=(
            "An ERG Table 3 container kind (Rail tank car; Highway tank truck or "
            "trailer; Agricultural nurse tank; Multiple ton cylinders; Multiple small "
            "cylinders; Multiple small cylinders or single ton cylinder), a unique "
            "start of one (highway tank truck), or unknown."
        ),
    )
    location: Location
    incident_time: AwareDatetime = Field(
        description=(
            "When, ISO 8601 with a UTC offset (2026-10-21T14:05:00-04:00). Decides day "
            "or night for the ERG tables."
        )
    )
    fire_involved: bool = Field(description="Whether fire is involved.")
    spill_size: SpillSize = Field(
        description=(
            "small: 208 liters (55 US gallons) or less; large: more than 208 liters "
            "(55 US gallons); unknown: the large spill distances apply."
        )
    )
    where_spilled: Literal["land", "water"] = Field(
        default="land",
        description=(
            "The surface the spill is on. It changes the answer only for a material "
            "ERG Table 2 lists (water-reactive): in water its Table 1 entry printed "
            '"(when spilled in water)" applies; on land a material Table 1 lists only '
            "for water is answered by its guide. land is the default, as in PHMSA's "
            "ERG app (whereSpilled)."
        ),
    )

    _plain = field_validator(
        "material", "placard", "guide_number", "container", mode="before"
    )(plain_text)

    @model_validator(mode="after")
    def _one_load(self) -> IncidentInput:
        given = [
            k
            for k in ("material", "placard", "guide_number")
            if getattr(self, k) is not None
        ]
        if len(given) != 1:
            raise ValueError(
                "give exactly one of material, placard and guide_number "
                f"(given: {', '.join(given) or 'none'})"
            )
        return self


class WindObservation(ToolInput):
    """A wind reading supplied by the caller instead of the NWS forecast."""

    model_config = ConfigDict(extra="forbid")

    speed_kmh: float = Field(ge=0, le=400, description="Wind speed, km/h.")
    direction_deg_from: float = Field(
        ge=0,
        le=360,
        description="Direction the wind blows FROM, degrees clockwise from true north.",
    )
    observed_at: AwareDatetime = Field(
        description="When the reading was taken, ISO 8601 with a UTC offset."
    )
    source: str = Field(
        min_length=1,
        max_length=200,
        description="Who or what measured it (on-scene anemometer, ASOS station KHGR).",
    )

    _plain = field_validator("source", mode="before")(plain_text)


class PopulationInput(ToolInput):
    """The area to count people in, and when."""

    # HB-09

    model_config = ConfigDict(extra="forbid")

    footprint: dict = Field(
        description=(
            "GeoJSON: the `footprint` FeatureCollection protective_action_footprint "
            "returns, a Feature, or a Polygon or MultiPolygon in WGS84 longitude and "
            "latitude. Points and lines are ignored; the polygons are counted as one "
            "area."
        )
    )
    incident_time: AwareDatetime = Field(
        description=(
            "When, ISO 8601 with a UTC offset. Decides day or night when `period` is "
            "not given."
        )
    )
    period: Literal["day", "night"] | None = Field(
        default=None,
        description=(
            "The ERG period, as protective_action_footprint's `day_night.period` "
            "gives it. Omitted: computed from `incident_time` at the footprint."
        ),
    )
    zones: list[str] | None = Field(
        default=None,
        description=(
            "Count only these footprint zones (`properties.zone`, such as "
            "protective_action_zone). Omitted: every polygon in the footprint."
        ),
    )


_FOOTPRINT_DESCRIPTION = (
    "GeoJSON: the `footprint` FeatureCollection protective_action_footprint returns "
    "(its zones are read from `properties.zone`), a Feature, or a Polygon or "
    "MultiPolygon in WGS84 longitude and latitude."
)


class FacilitiesInput(ToolInput):
    """The area to list facilities, waterways and rail in."""

    # HB-10

    model_config = ConfigDict(extra="forbid")

    footprint: dict = Field(description=_FOOTPRINT_DESCRIPTION)
    buffer_m: float = Field(
        default=0,
        ge=0,
        le=10_000,
        description=(
            "Grow the footprint by this many metres before listing. 0 by default: the "
            "ERG zones are the zones."
        ),
    )


class ReceivingInput(ToolInput):
    """The spill and its footprint, to find hospitals outside it."""

    # HB-10

    model_config = ConfigDict(extra="forbid")

    location: Location = Field(description="The spill point.")
    footprint: dict = Field(description=_FOOTPRINT_DESCRIPTION)
    max_km: float | None = Field(
        default=None,
        gt=0,
        le=200,
        description=(
            "Search radius in kilometres from the footprint's upwind edge. Omitted: "
            "50 km."
        ),
    )


class Ics201Input(ToolInput):
    """The incident to draft an ICS 201 for."""

    # HB-11

    model_config = ConfigDict(extra="forbid")

    incident: IncidentInput
    wind: WindObservation | None = Field(
        default=None,
        description=(
            "A wind reading to use instead of the NWS forecast grid, as for "
            "protective_action_footprint."
        ),
    )
    incident_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        description=(
            "Block 1, the name assigned to the incident. Omitted: '<material> release, "
            "<latitude>, <longitude>, <date>'."
        ),
    )
    _plain = field_validator("incident_name", mode="before")(plain_text)
    include_tool_outputs: bool = Field(
        default=False,
        description=(
            "Also return `tool_outputs`, every tool output the receipts point into "
            "(large: it carries the footprint, population and facility lists)."
        ),
    )
    response_format: Literal["concise", "detailed"] = Field(
        default="concise",
        description=(
            "concise (default): the Markdown form, every sentence with its source "
            "tag, the GeoJSON, errors and pack versions. detailed: also the blocks "
            "with each sentence's receipts, Annex A as structure, and the fired flags; "
            "with `block`, one of them at a time."
        ),
    )
    # HB-18 (A-6): the whole detailed form measured 61,392 to 97,392 characters over the
    # test scenarios (Block 5 at most 27,090, Annex A 23,844, the flags 7,706), above
    # Claude Code's default cap on a tool result; a page is one of them.
    block: Literal[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, "annex", "flags"] | None = Field(
        default=None,
        description=(
            "With response_format detailed, return only this part with its receipts: a "
            "block by its number (1 to 10), annex (Annex A) or flags (every fired "
            "flag). A part is at most about 28,000 characters. Omitted: the whole "
            "detailed form, 60,000 to 100,000 characters, above Claude Code's default "
            "cap on a tool result (25,000 tokens)."
        ),
    )
    include_map_svg: bool = Field(
        default=False,
        description=(
            "Also return `map_svg`, Block 4's sketch as SVG (large: 75,000 to 175,000 "
            "characters, above Claude Code's default cap on a tool result). `geojson` "
            "carries the same features for a client that draws."
        ),
    )


# ── Knowledge packs (HB-03; packs/SCHEMA.md)
# ────────────────────────────────────────────────── The typed form of every pack the
# server reads at runtime (DN-001 section 4 invariant 3). The JSON Schemas in
# packs/schema/ are generated from these models by `scripts/build_packs.py schema`, so
# the two never drift. Every model forbids unknown fields: a pack carrying a field this
# code does not know is a pack of a schema this code does not know.


class _PackModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PackSource(_PackModel):
    """One held document a pack was parsed from: its corpus doc_id, the sha256 of the
    held bytes, where in it the pack reads, and its licence as `corpus/sources.yaml`
    records it."""

    doc_id: str
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    locator: str
    licence: str


class AttributionCredit(_PackModel):
    doc_id: str
    title: str
    publisher: str
    edition: str | None
    url: str | None


class AttributionNotice(_PackModel):
    """A reuse or credit notice, verbatim from the held document at `locator`."""

    doc_id: str
    locator: str
    text: str


class PackAttribution(_PackModel):
    credits: list[AttributionCredit]
    notices: list[AttributionNotice]


class CrossCheck(_PackModel):
    """One field compared across sources (DN-003 section 5). `values` maps each source
    role to its value as that source prints it, or None where the source does not carry
    the field. `agree`: every carrying source agrees and at least two carry it;
    `disputed`: two carrying sources differ; `single_source`: only one source carries
    it."""

    field: str
    values: dict[str, str | None]
    status: Literal["agree", "disputed", "single_source"]


#: HB-03c (schema version 6): a cell whose printed US-unit value disagrees with its
#: metric value (no unrounded distance rounds up to both; lab/ LN-04).
#: `stale_secondary`: the metric value was revised from ERG 2020 and the US value was
#: not; `inconsistent_other`: neither edition explains it. The footprint uses the metric
#: value.
UnitNote = Literal["stale_secondary", "inconsistent_other"]


class MetricDistance(_PackModel):
    m: int
    ft: int
    unit_note: UnitNote | None = None


class KmDistance(_PackModel):
    """A downwind distance as ERG Table 1 or 3 prints it; `plus` is the table's "+"
    ("distance can be larger in certain atmospheric conditions")."""

    km: float
    mi: float
    plus: bool
    unit_note: UnitNote | None = None


class GuideDistance(_PackModel):
    """An orange-guide distance: metres, and the imperial phrase as printed ("1/2
    mile")."""

    m: int
    imperial: str


class Table1Spill(_PackModel):
    isolate: MetricDistance
    protect_day: KmDistance
    protect_night: KmDistance


#: The three keys of HB-03b's triple keying: A, the ERG 2024 PDF's text layer; B, a
#: vision read of the rendered page; C, PHMSA's ERG2020 data files.
KeyName = Literal["A", "B", "C"]


class _Keyed(_PackModel):
    """How a row was keyed (schema version 3, HB-03b). `keyed_by`: the keys whose
    reading equals the row's value on every field. `adjudicated`: A and B differed on a
    field and C decided it. `unresolved`: A, B and C all differ on `unresolved_fields`
    (or B did not read a page A and C disagree on); those fields are null, never guessed
    (packs/build/UNRESOLVED.md)."""

    keyed_by: list[KeyName]
    adjudicated: bool
    unresolved: bool
    unresolved_fields: list[str]


class Table1Entry(_Keyed):
    """One Table 1 name with its distances. `name` is the material name without the
    printed qualifier; `printed_name` is the cell as printed. ERG p. 30 Note 1: a
    water-reactive material that is also TIH has two entries, one "(when spilled on
    land)" and one "(when spilled in water)"; one that is only water-reactive has one
    entry "(when spilled in water)", and on land Tables 1 and 2 do not apply.
    `spilled_in` is that qualifier's surface (None: the entry has none), and
    `water_reactive_note` the qualifier as printed."""

    name: str
    printed_name: str
    guide: str | None
    spilled_in: Literal["land", "water"] | None
    water_reactive_note: str | None
    small: Table1Spill | None
    large: Table1Spill | None
    large_refer_to_table3: bool | None
    locator: str


class WindBandDistances(_PackModel):
    low: KmDistance
    moderate: KmDistance
    high: KmDistance


class Table3Row(_Keyed):
    container: str
    isolate: MetricDistance | None
    day: WindBandDistances | None
    night: WindBandDistances | None


class Table2Entry(_Keyed):
    """One Table 2 row (ERG pp. 337-341): a water-reactive material and the TIH gases it
    produces when spilled in water. The guide is the material's, as Table 2 prints it;
    the gases are symbols of `ErgData.table2_legend`. "The TIH gases indicated in Table
    2 are for information purposes only" (p. 336 Note 1)."""

    name: str
    guide: str | None
    gases: list[str] | None
    locator: str


class Table2Gas(_PackModel):
    """A gas symbol in Table 2's legend and its name, as printed."""

    symbol: str
    name: str
    locator: str


class Table3(_PackModel):
    heading: str
    locator: str
    rows: list[Table3Row]


class ErgName(_PackModel):
    name: str
    locator: str


class ErgMaterial(_PackModel):
    """Every ID number in the yellow index (schema version 3). `guide` is None when the
    index prints different guides under different names of the ID (the names carry
    theirs). `tih`: Table 1 lists the ID. `table2`: its Table 2 rows, or None.
    `where_spilled_matters`: Table 2 lists it, so a spill in water changes the answer
    (ERG pp. 30, 336). `cross_checks` are DN-003 section 5's, for the seed materials."""

    un: str
    names: list[ErgName]
    guide: str | None
    tih: bool
    table1: list[Table1Entry]
    table2: list[Table2Entry] | None
    where_spilled_matters: bool
    table3: Table3 | None
    cross_checks: list[CrossCheck]
    disputed: bool


class GuideItem(_Keyed):
    kind: Literal["heading", "bullet", "text"]
    text: str | None


class GuideSection(_PackModel):
    heading: str
    locator: str
    items: list[GuideItem]


class GuideEvacuation(_PackModel):
    """The EVACUATION distances of an orange guide, parsed from its text. `None` where
    the guide states no such distance (a TIH guide refers its spill distance to Table
    1)."""

    immediate_precautionary: GuideDistance | None
    #: the solids distance where the guide prints one for liquids and one for solids
    #: (schema version 3); `immediate_precautionary` is then the liquids distance
    immediate_precautionary_solids: GuideDistance | None
    large_spill_downwind: GuideDistance | None
    #: "Consider initial evacuation for ... in all directions" for a large spill
    #: (version 3)
    large_spill_all_directions: GuideDistance | None
    fire_isolate: GuideDistance | None
    fire_evacuate: GuideDistance | None
    spill_refers_to_table1: bool


class ErgGuide(_PackModel):
    guide: str
    title: str | None
    title_keyed_by: list[KeyName]
    sections: dict[str, GuideSection]
    evacuation: GuideEvacuation
    cross_checks: list[CrossCheck]
    disputed: bool


class WindBand(_PackModel):
    """An ERG Table 3 wind category; an open end is None."""

    band: Literal["low", "moderate", "high"]
    label: str
    mph_min: int | None
    mph_max: int | None
    kmh_min: int | None
    kmh_max: int | None
    locator: str


class ErgIndexName(_Keyed):
    """One yellow-index row: a name and the guide printed beside it."""

    name: str
    guide: str | None
    locator: str


class ErgIndexEntry(_PackModel):
    """Every ID number in the yellow index, seed or not (schema version 2). `in_table1`:
    Table 1 lists the ID number, which covers both TIH materials and water-reactive
    materials listed "(when spilled in water)" (ERG 2024 PDF p. 30, printed p. 28, Note
    1); which names under the ID it lists is read only for the seeds
    (`ErgMaterial.table1`)."""

    un: str
    names: list[ErgIndexName]
    in_table1: bool
    table1_locator: str | None


class PlacardProse(_PackModel):
    """An ERG sentence, verbatim, by locator: the one that states a placard's guide, or
    (HB-17) the note that says why a row has no ID number."""

    quote: str
    locator: str


class ErgPlacard(_Keyed):
    """One input of the placard entry point (schema version 7, HB-15): a placard the
    ERG's Table of Markings, Labels and Placards and Initial Response Guide draws (PDF
    pp. 10-11, printed pp. 8-9), with the guide circled beside it. "USE THIS TABLE ONLY
    IF MATERIALS CANNOT BE SPECIFICALLY IDENTIFIED" (p. 10).

    `placard` is the row's key: the hazard class or division (for Classes 2, 4, 5 and
    6, the division ERG p. 8 names for the placard's printed word), a placard word
    where one placard of a class has its own guide (OXYGEN, GASOLINE, FUEL OIL, HOT),
    the lithium battery labels, DANGEROUS, or `none` (no placard can be seen). `words`
    are the other words printed on the row's placards, each also accepted;
    `hazard_class` the class number printed in the placard's lower corner, or None.
    `association`: `prose` when an ERG sentence (`prose`) states the guide as well as
    the drawing, `drawing` when only the drawing's grouping does. Keyed by A (the PDF
    text layer: the circled number, and the prose) and B (a reading of the rendered
    page); see packs/SCHEMA.md."""

    placard: str
    words: list[str]
    hazard_class: str | None
    shows: str
    guide: str
    locator: str
    association: Literal["prose", "drawing"]
    prose: PlacardProse | None


class ErgNameAlias(_PackModel):
    """Another name for a yellow-index row, printed by a source the pack cites (schema
    version 8, HB-17): the sentence that pairs the two, verbatim, by locator."""

    alias: str
    quote: str
    locator: str


class ErgUnnumbered(_Keyed):
    """A yellow-index row with no ID number (schema version 8, HB-17): ERG 2024 PDF
    p. 31 prints four, the explosives, which the index lists by name and division
    because "Explosives are not individually listed by their ID number" (`note`,
    p. 30). A
    `material` matching `name` or an alias resolves to `guide`. Keyed as every index
    row is (A, B, C)."""

    name: str
    guide: str
    locator: str
    note: PlacardProse
    aliases: list[ErgNameAlias]


class ErgData(_PackModel):
    seed_un_numbers: list[str]
    materials: dict[str, ErgMaterial]
    guides: dict[str, ErgGuide]
    #: every ID number in the yellow index -> its names, guides and Table 1 membership
    index: dict[str, ErgIndexEntry]
    #: lower-cased material name -> every UN number the yellow index lists it under
    name_index: dict[str, list[str]]
    table3_wind_bands: list[WindBand]
    table3_cross_checks: list[CrossCheck]
    #: Table 2's legend of gas symbols (schema version 3)
    table2_legend: list[Table2Gas]
    #: the Table of Markings, Labels and Placards, a row per accepted input (version 7)
    placards: list[ErgPlacard]
    #: the yellow-index rows with no ID number, the explosives (version 8)
    unnumbered: list[ErgUnnumbered]


class CfrRow(_PackModel):
    """One row of the 49 CFR 172.101 Hazardous Materials Table. `description` is column
    2 as printed; `roman_segments` are its Roman-type runs in order, italic words
    removed (172.101(c)(1): proper shipping names are limited to Roman type; (c)(2): an
    italic "or" marks alternatives). Which run is the proper shipping name is the
    regulation's reading, not this pack's; the runs are given as printed."""

    symbols: str
    description: str
    roman_segments: list[str]
    hazard_class: str
    identification_number: str
    packing_group: str | None
    label_codes: list[str]
    special_provisions: list[str]
    locator: str


class CfrMaterial(_PackModel):
    un: str
    rows: list[CfrRow]
    cross_checks: list[CrossCheck]
    disputed: bool


class Cfr172Data(_PackModel):
    edition: str
    #: pack field -> the table's own column heading
    columns: dict[str, str]
    materials: dict[str, CfrMaterial]


class CameoSection(_PackModel):
    heading: str
    paragraphs: list[str]


class CameoDatasheet(_PackModel):
    doc_id: str
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    title: str
    un_numbers: list[str]
    locator: str
    sections: list[CameoSection]


class CameoPageRef(_PackModel):
    doc_id: str
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    locator: str


class CameoMaterial(_PackModel):
    un: str
    unna_page: CameoPageRef
    datasheets: list[CameoDatasheet]


class CameoData(_PackModel):
    response_sections: list[str]
    materials: dict[str, CameoMaterial]


class HazardClass(_PackModel):
    class_id: str
    title: str
    rule_set_id: str
    criteria: dict[str, str | bool]
    members: list[str]
    basis: str


class HazardClassesData(_PackModel):
    classes: list[HazardClass]


class FlagInput(_PackModel):
    """A value a rule reads: `name` (its name in the predicate and template), the DN-001
    section 7 tool that produces it, the source dataset field, and the dataset."""

    name: str
    tool: str
    field: str
    dataset: str
    description: str


class FlagComparison(_PackModel):
    """`input` compared by `op` with a literal `value`, a rule param (`param`), or
    another input (`ref`). Exactly one of the three is set, except for the unary
    is_true/is_false."""

    input: str
    op: Literal["gt", "ge", "lt", "le", "eq", "ne", "in", "is_true", "is_false"]
    value: str | int | float | bool | list[str] | None = None
    param: str | None = None
    ref: str | None = None


class FlagPredicate(_PackModel):
    mode: Literal["all", "any"]
    terms: list[FlagComparison]


class FlagReceipt(_PackModel):
    """A held document, the page (PDF page, or form-feed block for a converted file, as
    Squiddy numbers them) and a verbatim quote the build verified there. `text_layer`
    (schema version 4) names the text the quote was verified against: `pdf_text` (the
    page text the corpus reader gives, HB-03's rule) or `keyA` (HB-03b's Key A text of
    an orange guide page, HB-12's admission test)."""

    doc_id: str
    page: int
    quote: str
    supports: str
    text_layer: Literal["pdf_text", "keyA"]


class FlagKind(_PackModel):
    """A rule kind (HB-12, `packs/src/flag_kinds.yaml`): `origin` authored (HB-03's
    hand-written rules), guide (an orange guide section), cross (a property several
    guides state) or table (a pack field)."""

    kind: str
    origin: Literal["authored", "guide", "cross", "table"]
    description: str


class FlagStatement(_PackModel):
    """One ERG sentence by locator: a flag's consequence or its response (DN-006 section
    3.1). `text_layer` as `FlagReceipt`'s."""

    doc_id: str
    page: int
    quote: str
    text_layer: Literal["pdf_text", "keyA"]


class FlagCause(_PackModel):
    """The cause of a rule consolidated into this flag (DN-006 section 3.4; ISA-18.2
    uniqueness): the flag fires when its own predicate holds or any merged cause does.
    """

    rule_id: str
    predicate: FlagPredicate


class FlagRule(_PackModel):
    """A flag rule. Schema version 4 (HB-12): `kind`; `source_kind` (authored: HB-03's
    hand-written rules; guide: mined from an orange guide and admitted by the substring
    test; table: binds a pack field, written by hand); `guides`, the orange guides whose
    materials the rule applies to (guide rules; empty otherwise); `dormant` and
    `dormant_inputs`, the inputs no registered tool supplies yet (the rule cannot fire
    until one does)."""

    rule_id: str
    title: str
    kind: str
    source_kind: Literal["authored", "guide", "table"]
    classes: list[str]
    guides: list[str]
    modes: list[Literal["highway", "rail"]]
    inputs: list[FlagInput]
    params: dict[str, int | float | str]
    predicate: FlagPredicate
    template: str
    receipts: list[FlagReceipt]
    basis: str
    gaps: list[str]
    dormant: bool
    dormant_inputs: list[str]
    #: Schema version 5 (HB-12b; DN-006): the rationalized alarm's attributes.
    #: `predicate` is its cause; `consequence` and `response` are ERG sentences by
    #: locator; `priority` is DN-006 section 3.5's rule (`flag_kinds.yaml` `priority`);
    #: `indication` is true when the ERG gives no response, and an indication is never
    #: printed; `merged` are the causes of the rules consolidated into this one.
    consequence: FlagStatement
    response: FlagStatement | None
    priority: Literal["high", "medium", "low"]
    indication: bool
    merged: list[FlagCause]


class FlagRulesData(_PackModel):
    rules: list[FlagRule]
    #: rule set id (one per hazard class) -> the rule ids that fire for that class
    rule_sets: dict[str, list[str]]
    #: orange guide number (without P) -> the rule ids mined from that guide (version 4)
    guide_rule_sets: dict[str, list[str]]
    #: the table rules, which apply to every material (version 4); HB-18: FR-AMB-01,
    #: the ambiguous load, the one that is not merged into a guide flag
    table_rule_set: list[str]
    #: the rule kinds (version 4)
    kinds: list[FlagKind]


class VocabularyReceipt(_PackModel):
    doc_id: str
    page: int
    locator: str


class VocabularyTerm(_PackModel):
    """A term pack-emitted text uses, with its definition read verbatim from the held
    page."""

    term: str
    definition: str
    authority: str
    receipt: VocabularyReceipt
    used_by: list[str]


class VocabularyData(_PackModel):
    terms: list[VocabularyTerm]


class PackEnvelope(_PackModel):
    """The fields every pack carries (packs/SCHEMA.md)."""

    schema_version: int
    pack_id: str
    version: str
    built_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sources: list[PackSource]
    attribution: PackAttribution


class ErgPack(PackEnvelope):
    kind: Literal["erg"]
    data: ErgData


class Cfr172Pack(PackEnvelope):
    kind: Literal["cfr172"]
    data: Cfr172Data


class CameoPack(PackEnvelope):
    kind: Literal["cameo"]
    data: CameoData


class HazardClassesPack(PackEnvelope):
    kind: Literal["hazard_classes"]
    data: HazardClassesData


class FlagRulesPack(PackEnvelope):
    kind: Literal["flag_rules"]
    data: FlagRulesData


class VocabularyPack(PackEnvelope):
    kind: Literal["vocabulary"]
    data: VocabularyData


#: pack kind -> its model; src/hazbrief/packs.py refuses a kind not listed here.
PACK_MODELS: dict[str, type[PackEnvelope]] = {
    "erg": ErgPack,
    "cfr172": Cfr172Pack,
    "cameo": CameoPack,
    "hazard_classes": HazardClassesPack,
    "flag_rules": FlagRulesPack,
    "vocabulary": VocabularyPack,
}


# ── The application's packs (HB-66; DN-018 sections 3 to 5) ─────────────────────────
# The workbench's first-order puff reads these; the server never loads them, so they
# stay out of PACK_MODELS and the tool surface does not move (DN-009 section 2). Every
# number sits in an object with a sibling `receipt`: the held document, its page and the
# text as printed there, which the build verifies on that page (packs/SCHEMA.md).

ValueStatus = Literal["held", "not_applicable", "not_held"]


class ValueReceipt(_PackModel):
    """Where a value is printed. `page` is the PDF page, or the form-feed block of a
    converted file (packs/SCHEMA.md, Locators); `quote` is the text as printed there.
    `read_by`: `text_layer` (verified on the page's text at build) or `rendered_page`
    (a page with no usable text layer, read from its image; the quote is the
    reading). `sha256` is the held file's raw sha256, so a receipt names the exact
    bytes it was read from (HB-109; DN-020 section 2 item 4). From a `reference-only`
    source the quote is the number and its unit only (the licence gate,
    packs/SCHEMA.md)."""

    doc_id: str
    page: int
    locator: str
    quote: str
    read_by: Literal["text_layer", "rendered_page"] = "text_layer"
    sha256: str


# ── The suggested actions to consider (HB-207 Part E; DN-029 ADDENDUM-00) ─────────────
# A server pack beside the flags, read by the `decision_support` prompt. Defined here,
# after `ValueReceipt`, and added to PACK_MODELS below it.


class GuideCell(_PackModel):
    """An action that is the ERG guide's own cell, as `material_response_guidance`
    returns it: its section and, where one is named, the heading it sits under."""

    tool: Literal["material_response_guidance"]
    section: Literal["potential_hazards", "public_safety", "emergency_response"]
    heading: str | None = None


class SuggestedAction(_PackModel):
    """One entry (DN-029 ADDENDUM-00 decision 2): the condition that brings it up, a
    test on values a tool result holds (`when`, with the fields it `reads`); the action,
    a quotation verified on its page (`action`, with the parsed `block` it is read in)
    or the guide's cell (`guide_cell`), never both; who acts, in the source's words,
    only where it says (`who`); the sources' order (`order`); and by when, a held range
    or the source's own words, verified on its page (`by_when`), never a clock time."""

    when: str
    reads: list[str]
    order: int
    action: ValueReceipt | None = None
    #: a table's column heading the quoted cell sits under, printed apart from it
    heading: ValueReceipt | None = None
    block: int | None = None
    guide_cell: GuideCell | None = None
    who: str | None = None
    by_when: ValueReceipt | None = None

    @model_validator(mode="after")
    def _one_action(self):
        if (self.action is None) == (self.guide_cell is None):
            raise ValueError("an entry is a quotation or a guide cell, exactly one")
        if self.action is not None and self.block is None:
            raise ValueError("a quotation names its parsed block")
        return self


class SuggestedActionsData(_PackModel):
    label: str
    demonstration: str
    decides: str
    no_entry: str
    #: conditions a tool result can hold that no entry answers (decision 5)
    uncovered: list[str]
    actions: dict[str, SuggestedAction]


class SuggestedActionsPack(PackEnvelope):
    kind: Literal["suggested_actions"]
    data: SuggestedActionsData


PACK_MODELS["suggested_actions"] = SuggestedActionsPack


class HeldValue(_PackModel):
    """One number with its unit and receipt, or none with the reason. `derived_from`
    names the values a computed one is made from (each held, with its own receipt)."""

    value: float | None
    unit: str
    status: ValueStatus
    reason: str | None = None
    receipt: ValueReceipt | None = None
    derived_from: list[str] = []

    @model_validator(mode="after")
    def _consistent(self):
        if self.status == "held":
            if self.value is None:
                raise ValueError("a held value has a value")
            if self.receipt is None and not self.derived_from:
                raise ValueError(
                    "a held value has a receipt or derives from held values"
                )
        elif self.value is not None or not self.reason:
            raise ValueError(f"a {self.status} value has no value and states why")
        return self


DispersionClass = Literal[
    "pressure_liquefied_toxic", "cryogenic_asphyxiant", "flammable"
]


class DispersionClassRule(_PackModel):
    """A DN-018 section 3 row: the threshold the puff draws to and its caveat."""

    thresholds: list[str]
    dense_gas_caveat: bool
    basis: str


#: What kind of page a held thermodynamic value comes from (HB-124 step 5; DN-020
#: ADDENDUM-02: every value is labelled with where it came from). `reference-table`: a
#: compiled property table (the NIST WebBook's species and Fluid Systems pages, CAMEO
#: Chemicals). `model-test-input`: a value a program's documentation prints as a
#: test-case input (the SLAB user's guide's chlorine case), which is not a
#: benchmark-validated property.
SourceTier = Literal["reference-table", "model-test-input"]


class ThermoValue(HeldValue):
    """A substance property with the temperature it is stated at (HB-109). `as_printed`
    is the value and unit as the page prints them where the pack converts the unit
    (`conversion` names the definition used); `value_range` is a range a mixture's page
    prints in place of one value (gasoline's boiling range), held with `value` None.
    `source_tier` says what kind of page a held value comes from (HB-124); a value not
    held has none."""

    temperature_k: float | None = None
    as_printed: str | None = None
    conversion: str | None = None
    value_range: list[float] | None = None
    source_tier: SourceTier | None = None

    @model_validator(mode="after")
    def _consistent(self):
        if self.status == "held":
            if self.value is None and not self.value_range:
                raise ValueError("a held value has a value or a printed range")
            if self.receipt is None and not self.derived_from:
                raise ValueError(
                    "a held value has a receipt or derives from held values"
                )
            if self.source_tier is None:
                raise ValueError("a held value names its source tier")
        elif (
            self.value is not None
            or self.value_range
            or not self.reason
            or self.source_tier is not None
        ):
            raise ValueError(
                f"a {self.status} value has no value and no tier, and states why"
            )
        return self


class CorrelationRow(_PackModel):
    """One printed row of a correlation's constants and the temperature range the page
    states it for; each constant carries the row's receipt."""

    t_min_k: float
    t_max_k: float
    constants: dict[str, HeldValue]
    receipt: ValueReceipt


class Correlation(_PackModel):
    """A temperature correlation as the held page prints it: `form` states the equation
    and its units in the page's terms; `rows` are every printed row (Antoine) or the
    lowest-temperature column (Shomate), each with its range. A source term picks the
    row whose range covers its temperature; none is extrapolated here."""

    form: str
    status: ValueStatus
    reason: str | None = None
    rows: list[CorrelationRow] = []


class ThermoProxy(_PackModel):
    """DN-020 ADDENDUM-01 section 2 item 4: a mixture drawn with a pure substance's
    properties, so the label can say so. `receipt` is the mixture's own page stating
    its composition."""

    proxy_for: str
    properties_of: str
    label: str
    receipt: ValueReceipt


class Thermodynamics(_PackModel):
    """What a source term needs (DN-020 sections 2 item 4 and 3.1), each from a held
    page or absent with the reason; nothing is defaulted. CAMEO Chemicals is read first
    and the NIST WebBook second; `cross_checks` compare them where both print a value.
    `missing` names the source-term fields not held, for the label and the source-term
    table (`docs/evidence/hb109/source_terms.tsv`)."""

    proxy: ThermoProxy | None
    molecular_weight_g_mol: HeldValue
    normal_boiling_point_k: ThermoValue
    heat_of_vaporization_j_mol: ThermoValue
    liquid_heat_capacity_j_mol_k: ThermoValue
    vapour_heat_capacity_j_mol_k: ThermoValue
    vapour_heat_capacity_shomate: Correlation
    liquid_specific_gravity: ThermoValue
    liquid_density_kg_m3: ThermoValue
    vapour_pressure_as_printed: ThermoValue
    saturation_pressure_antoine: Correlation
    critical_temperature_k: ThermoValue
    critical_pressure_bar: ThermoValue
    cross_checks: list[CrossCheck]
    missing: list[str]


LevelOfConcernKind = Literal["aegl2", "lfl_fraction", "oxygen_deficiency"]


class LevelOfConcern(_PackModel):
    """A DN-001 class's level of concern (DN-020 ADDENDUM-01 section 2 item 2).
    `values` is keyed by averaging minutes for an AEGL ("10", "30", "60") and "any"
    otherwise; `components` are the held values a derived level is made from (the LFL
    and the fraction applied to it)."""

    kind: LevelOfConcernKind
    unit: str
    basis: str
    proxy_for: str | None = None
    values: dict[str, HeldValue]
    components: dict[str, HeldValue] = {}


class MaterialProperties(_PackModel):
    un: str
    name: str
    guide: str
    dispersion_class: DispersionClass
    dense_gas_caveat: bool
    molecular_weight_g_mol: HeldValue
    lfl_vol_pct: HeldValue
    #: The AEGL program's status for the values ("Final", "Proposed"), or None.
    aegl_status: str | None
    #: level ("AEGL-1"...) -> minutes ("10", "30", "60") -> ppm; None with
    #: `aegl_reason` where the class draws no AEGL or none is held.
    aegl_ppm: dict[str, dict[str, HeldValue]] | None
    aegl_reason: str | None
    oxygen_deficiency_threshold_vol_pct: HeldValue
    cross_checks: list[CrossCheck]
    #: HB-109: the source term's properties and the class's levels of concern.
    thermodynamics: Thermodynamics
    levels_of_concern: list[LevelOfConcern]


class AirBasis(_PackModel):
    """What turns a mass concentration into a volume fraction: the basis ppm and mg/m3
    are converted at (NIOSH: 25 C and 1 atm; EPA's RMP guidance: 25 C is 298 K) and the
    constants of the U.S. Standard Atmosphere, 1976 (1 atm is its sea-level P0; R* is
    its k times its N_A)."""

    conversion_temperature_c: HeldValue
    conversion_pressure_atm: HeldValue
    conversion_temperature_k: HeldValue
    boltzmann_constant_n_m_k: HeldValue
    avogadro_constant_per_kmol: HeldValue
    gas_constant_j_kmol_k: HeldValue
    standard_pressure_pa: HeldValue
    molar_volume_m3_kmol: HeldValue
    oxygen_volume_fraction: HeldValue
    #: The asphyxiant fraction at which oxygen falls below the threshold:
    #: 1 - threshold / (100 x oxygen_volume_fraction).
    asphyxiant_vol_pct_at_threshold: HeldValue


class MaterialsPropertiesData(_PackModel):
    classes: dict[DispersionClass, DispersionClassRule]
    air: AirBasis
    materials: dict[str, MaterialProperties]


class SigmaYCoefficients(_PackModel):
    c: float
    d: float
    receipt: ValueReceipt


class SigmaZBand(_PackModel):
    """One distance band of Table 1-2: sigma-z = a x^b for x up to `x_max_km` (None:
    the last band), or the fixed `fixed_m` where the table prints no a and b."""

    x_range_as_printed: str
    x_max_km: float | None
    a: float | None
    b: float | None
    fixed_m: float | None
    receipt: ValueReceipt


class SigmaClass(_PackModel):
    sigma_y: SigmaYCoefficients
    sigma_z: list[SigmaZBand]


class SigmaConstant(_PackModel):
    value: float
    unit: str
    receipt: ValueReceipt


class SigmaCurvesData(_PackModel):
    terrain: Literal["rural"]
    sigma_y_form: str
    sigma_z_form: str
    sigma_y_scale: SigmaConstant
    theta_scale: SigmaConstant
    sigma_z_cap_m: SigmaConstant
    band_rule: str
    classes: dict[Literal["A", "B", "C", "D", "E", "F"], SigmaClass]
    urban: dict[str, str]


class ReleaseDefinition(_PackModel):
    text: str
    receipt: ValueReceipt


class WorstCaseRule(_PackModel):
    definition: ReleaseDefinition
    duration_min: HeldValue


class AlternativeRule(_PackModel):
    method: ReleaseDefinition
    hole_size_cm: HeldValue
    duration_min: HeldValue


class ContainerScenarios(_PackModel):
    """A container string the fixtures use. `covered`: the guidance states the inputs
    both envelopes need for it; when false, `reason` names the first one missing."""

    container: str
    covered: bool
    reason: str | None
    worst_case_quantity_kg: HeldValue
    alternative_hole_size_cm: HeldValue
    alternative_duration_min: HeldValue


class ReleaseScenariosData(_PackModel):
    authority: str
    worst_case: WorstCaseRule
    alternative: AlternativeRule
    containers: dict[str, ContainerScenarios]
    not_adopted: list[dict[str, str]]


#: HB-120 (DN-020 ADDENDUM-02 section 2 item 3): the release models a routed guide
#: takes, and "no dispersion model applies".
ReleaseRoute = Literal[
    "two_phase_jet", "evaporating_pool", "instantaneous", "not_applicable"
]
#: The level-of-concern classes: `toxic` is AEGL-2, else the NIOSH IDLH (HB-119
#: ADDENDUM-00), as the dense-gas channel's `tih_gas` class reads it.
LocClass = Literal["toxic", "flammable_lfl", "oxygen_deficiency"]
#: The storage states a row is keyed on: source_term's three, a solid, or `any` (the
#: guide routes every state alike).
RoutingState = Literal[
    "pressure_liquefied", "refrigerated_liquid", "ambient_liquid", "solid", "any"
]


class RoutingRow(_PackModel):
    """One guide's route for one storage state. A routed row names its level-of-concern
    class and no reason; a `not_applicable` row names its reason, in a responder's
    words, and no class. Every row's `basis` is the guide's own POTENTIAL HAZARDS text
    on its page, verified at build."""

    state: RoutingState
    route: ReleaseRoute
    loc_class: LocClass | None = None
    reason: str | None = None
    basis: ValueReceipt

    @model_validator(mode="after")
    def _consistent(self):
        if self.route == "not_applicable":
            if not self.reason or self.loc_class is not None:
                raise ValueError("a not_applicable row states its reason and no class")
        elif self.loc_class is None or self.reason is not None:
            raise ValueError("a routed row names its loc_class and no reason")
        return self


class GuideRouting(_PackModel):
    """One ERG orange guide: its title, the 49 CFR 172.101 hazard classes and divisions
    of the index entries it serves (and, for a guide with no numbered entry, the ERG
    placard table's) and its rows. It holds no number without a receipt."""

    guide: str = Field(pattern=r"^\d{3}$")
    title: str
    hazard_classes: list[str]
    placard_classes: list[str]
    rows: list[RoutingRow] = Field(min_length=1)

    @model_validator(mode="after")
    def _states(self):
        states = [r.state for r in self.rows]
        if len(set(states)) != len(states):
            raise ValueError(f"guide {self.guide}: a state has more than one row")
        if "any" in states and len(states) != 1:
            raise ValueError(f"guide {self.guide}: an `any` row stands alone")
        return self


class RoutingRule(_PackModel):
    text: str
    receipt: ValueReceipt


class ReleaseRoutingData(_PackModel):
    rules: dict[str, RoutingRule]
    guides: dict[str, GuideRouting]


class OperatorStatement(_PackModel):
    """A rule the operator stated (HB-155): its register record and the line of
    docs/evidence/hb155/operator_statements.md it was registered from."""

    record: str = Field(pattern=r"^hazbrief-mcp:HBD-\d{3}$")
    statement: str = Field(pattern=r"^S\d+$")


class MaterialSources(_PackModel):
    """HB-178: a rule's sources for one material: the receipt that keys the document to
    the material (its UN number on its page) and the quotes that support the rule."""

    key: ValueReceipt
    sources: list[ValueReceipt] = Field(min_length=1)


class SourceNote(_PackModel):
    """HB-178: what a general source was drawn from (one incident, one material), with
    the held words that say so, printed beside the source wherever it is cited."""

    note: str
    receipt: ValueReceipt


class SitingRule(_PackModel):
    """One rule of the siting layer (HB-155; DN-023 section 4): where it applies, its
    words, and its held quotes (each verified on its page at build) or the operator's
    record, never neither. HB-178: a source about one material is keyed by the material
    (`material_sources`, by UN number), with the words printed where the brief's
    material has none (`material_none`); a general source drawn from one material's
    incident says so (`source_notes`, by doc_id)."""

    applies: Literal["exclude", "choose", "label", "candidates"]
    point: Literal["command_post", "triage", "staging"] | None = None
    words: str
    sources: list[ValueReceipt] = Field(default_factory=list)
    operator_stated: OperatorStatement | None = None
    material_sources: dict[str, MaterialSources] = Field(default_factory=dict)
    material_none: str | None = None
    source_notes: dict[str, SourceNote] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _grounded(self):
        if not self.sources and self.operator_stated is None:
            raise ValueError("a siting rule has a held quote or an operator record")
        if (self.applies == "choose") != (self.point is not None):
            raise ValueError("a `choose` rule names its point, and only it does")
        if bool(self.material_sources) != (self.material_none is not None):
            raise ValueError("material sources and the words for none come together")
        return self


class SitingRulesData(_PackModel):
    rules: dict[str, SitingRule]


class SitingRulesPack(PackEnvelope):
    kind: Literal["siting_rules"]
    data: SitingRulesData


class MaterialsPropertiesPack(PackEnvelope):
    kind: Literal["materials_properties"]
    data: MaterialsPropertiesData


class SigmaCurvesPack(PackEnvelope):
    kind: Literal["sigma_curves"]
    data: SigmaCurvesData


class ReleaseScenariosPack(PackEnvelope):
    kind: Literal["release_scenarios"]
    data: ReleaseScenariosData


class ReleaseRoutingPack(PackEnvelope):
    kind: Literal["release_routing"]
    data: ReleaseRoutingData


#: The application's pack kinds: read by the brief (`hazbrief.packs.load_app_pack`),
#: never by the server's `load_packs`.
APP_PACK_MODELS: dict[str, type[PackEnvelope]] = {
    "materials_properties": MaterialsPropertiesPack,
    "sigma_curves": SigmaCurvesPack,
    "release_scenarios": ReleaseScenariosPack,
    "release_routing": ReleaseRoutingPack,
    "siting_rules": SitingRulesPack,
}
