"""The application scenario's `stated_wind` block (HB-70 step 3).

A responder at the scene has an anemometer or a flag, and the puff should take what
they report, the way HB-69 made the release quantity an input (DN-018 ADDENDUM-00
section 3: an input is given, never defaulted). The block is an application field read
by `derive.puff` alone: a stated wind replaces the NWS forecast wind for every hour of
the puff's window; without it, the forecast drives the puff as before. The ERG
footprint does not read it: the ERG distance is a table lookup, not a wind product.

    "stated_wind": {
      "speed_m_s": 3.0,
      "direction_deg_from": 270,
      "source": "scene observation, hand anemometer, 21:10 EDT",
      "observed_at": "2026-10-28T21:10:00-04:00"     # optional
    }

**Why not `wind`.** HB-70's text names the block `wind`, but the scenario's `wind` has
been the server's `WindObservation` since HB-41 (km/h, `observed_at` required): it is
passed to `protective_action_footprint` and `build_ics_201` and orients the footprint,
and 18 fixtures carry it. A puff-only block under that key would either collide with it
or reach the footprint, which step 3 forbids. Same shape and refusals as `release`.

A speed or a direction without its source is refused: the value would print on every
contour with nothing to say where it came from. A direction without a speed is refused
(nothing to drive), and so is a moving wind without its direction. A speed of 0 needs
no direction: FMH-1 section 5.5.2 reports calm as calm, with no direction.
"""

from __future__ import annotations

import json

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)


class StatedWind(BaseModel):
    """The wind at the scene, as the scenario states it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    speed_m_s: float | None = Field(default=None, ge=0)
    direction_deg_from: float | None = Field(default=None, ge=0, le=360)
    source: str | None = Field(default=None, min_length=1)
    observed_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def _sources(self):
        given = self.speed_m_s is not None or self.direction_deg_from is not None
        if given and not (self.source or "").strip():
            what = "speed_m_s" if self.speed_m_s is not None else "direction_deg_from"
            raise ValueError(f"{what} is given without source")
        if self.direction_deg_from is not None and self.speed_m_s is None:
            raise ValueError("direction_deg_from is given without speed_m_s")
        if self.speed_m_s and self.direction_deg_from is None:
            raise ValueError("speed_m_s above 0 is given without direction_deg_from")
        return self


def parse(raw) -> tuple[StatedWind | None, str | None]:
    """(the block, None), (None, None) when the scenario has none, or (None, why) when
    it is refused. Never raises: a refused block is a line on the panel."""
    if raw is None:
        return None, None
    try:
        return StatedWind.model_validate(raw), None
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(x) for x in first.get("loc") or ())
        msg = first["msg"].removeprefix("Value error, ")
        return None, f"{where}: {msg}" if where else msg


def schema_text() -> str:
    """The block's JSON Schema (2020-12), `docs/schema/scenario_stated_wind.schema.json`
    (HB-70)."""
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        **StatedWind.model_json_schema(),
        # the model's validator, in the schema's own terms (JSON Schema 2020-12 s6.5.4
        # dependentRequired; s10.2.2 if/then for the moving wind's direction)
        "dependentRequired": {
            "speed_m_s": ["source"],
            "direction_deg_from": ["source", "speed_m_s"],
        },
        "if": {
            "properties": {"speed_m_s": {"type": "number", "exclusiveMinimum": 0}},
            "required": ["speed_m_s"],
        },
        "then": {"required": ["direction_deg_from"]},
    }
    return json.dumps(schema, sort_keys=True, indent=1, ensure_ascii=False) + "\n"
