"""The application scenario's `release` block (DN-018 ADDENDUM-00 section 3; HB-69).

The release quantity is an input, stated by whoever knows it (the shipping papers, the
train consist, the placarded capacity, the scenario author), never a default. The
block is an application field: `hazbrief brief`'s scenario carries it beside the
server's `incident`, which does not change (the tool surface stays `fded04ec6c0e`), and
`derive.puff` reads it.

    "release": {
      "quantity_kg": 80000,
      "quantity_source": "the train consist, car 4",
      "hole_diameter_m": 0.05,          # optional; the alternative release
      "hole_source": "the crew's report"
    }

A quantity without its source, or a hole without its, is refused: the value would print
on every contour with nothing to say where it came from. A hole without a quantity is
refused too: the alternative release runs until the stated quantity is gone.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class Release(BaseModel):
    """What was released, as the scenario states it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    quantity_kg: float | None = Field(default=None, gt=0)
    quantity_source: str | None = Field(default=None, min_length=1)
    hole_diameter_m: float | None = Field(default=None, gt=0)
    hole_source: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _sources(self):
        if self.quantity_kg is not None and not (self.quantity_source or "").strip():
            raise ValueError("quantity_kg is given without quantity_source")
        if self.hole_diameter_m is not None:
            if not (self.hole_source or "").strip():
                raise ValueError("hole_diameter_m is given without hole_source")
            if self.quantity_kg is None:
                raise ValueError("hole_diameter_m is given without quantity_kg")
        return self


def parse(raw) -> tuple[Release | None, str | None]:
    """(the block, None), (None, None) when the scenario has none, or (None, why) when
    it is refused. Never raises: a refused block is a line on the panel."""
    if raw is None:
        return None, None
    try:
        return Release.model_validate(raw), None
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(x) for x in first.get("loc") or ())
        msg = first["msg"].removeprefix("Value error, ")
        return None, f"{where}: {msg}" if where else msg


def schema_text() -> str:
    """The block's JSON Schema (2020-12), `docs/schema/scenario_release.schema.json`."""
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        **Release.model_json_schema(),
        # the model's validator, in the schema's own terms (JSON Schema 2020-12 s6.5.4)
        "dependentRequired": {
            "quantity_kg": ["quantity_source"],
            "hole_diameter_m": ["hole_source", "quantity_kg"],
        },
    }
    return json.dumps(schema, sort_keys=True, indent=1, ensure_ascii=False) + "\n"
