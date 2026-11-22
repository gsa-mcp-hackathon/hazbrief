"""The VSMOKE client: a fire's smoke from its inputs to a recorded run (DN-021 section
3; HB-128 step 4).

VSMOKE (Lavdas 1996, USDA Forest Service GTR SRS-6) is a steady-state Gaussian plume
model for one fire, with Briggs plume rise. It runs in the models image beside SLAB,
never in the server (DN-001 invariant 3; DN-020 section 2). This module follows the SLAB
client's pattern (`hazbrief.brief.dense_gas`, `slab_driver`):

1. `refusals(inputs, spec)`: every input the caller did not supply, or supplied without
   a source or out of range, is a one-line refusal that names it. Nothing is defaulted,
   as the SLAB client refuses on a missing CPS. The inputs are the fire's point, its
   PM2.5 emission rate and its heat release (each a `Sourced` value: the caller derives
   them from a fuel-consumption figure and says where it came from), the brief's
   Pasquill-Gifford class, the wind speed and the direction it blows from, and the
   mixing height.
2. `run(inputs, spec, recordings_dir=, record=, engine=)`: a recorded run of these
   inputs is replayed; with `record` and an engine, a run not recorded is made and
   recorded; otherwise the result is a refusal naming what is missing. The recording is
   keyed by the sha256 of the inputs' canonical JSON (`input_key`), as SLAB's runs are
   keyed by their deck (`fixtures/evidence/slab_runs`), and holds no time, so the same
   run recorded twice is the same bytes.
3. `label(source, spec)`: DN-021 section 3's label, verbatim, with the emission rate's
   source.

**State at HB-128.** The engine is not built: the Fortran source is distributed from
webcam.srs.fs.usda.gov, which has no address record, and the manual that defines
VSMOKE's input file and output tables is robots-disallowed at rung 1
(`docs/evidence/hb128/acquisition.md`). So there is no engine to pass (`engine=None`,
the default), every unrecorded run is the `engine_not_held` refusal, and the deck writer
and output reader are not written: their format is the manual's, and a format guessed
without it would be a guess, not VSMOKE. The task that holds the source and the manual
adds the image's VSMOKE entry, the deck writer and the output reader (distances, PM2.5
and plume rise), and passes the engine here.

**State at HB-150.** The manual is held; the source is not, anywhere reachable. The one
VSMOKE found (USFS AirFire's BlueSky repository, `bin/vsmoke`) is a prebuilt binary: it
reproduces the manual's worked example, but nothing is built from source, so under the
operator's decision of 2026-11-09 the smoke layer is a future use (`vsmoke.yaml`
`engine`; docs/evidence/hb150/smoke_candidates.tsv). Every run still refuses, in the
future-use words.

Words, hints and the label are in `vsmoke.yaml` beside this file (`load_spec`). Standard
library and PyYAML only.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

SPEC_PATH = Path(__file__).with_name("vsmoke.yaml")


def load_spec(path: str | Path = SPEC_PATH) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Sourced:
    """A value and where it came from (DN-020 ADDENDUM-02: every value labelled with
    its source)."""

    value: float
    source: str


@dataclass(frozen=True)
class Inputs:
    """One fire, in the units the names say. None is "not supplied"."""

    latitude: float | None = None
    longitude: float | None = None
    emission_rate_g_s: Sourced | None = None
    heat_release_w: Sourced | None = None
    stability: str | None = None
    wind_speed_ms: float | None = None
    wind_from_deg: float | None = None
    mixing_height_m: float | None = None


@dataclass
class Outcome:
    """A run's output, or `error` and `hint`, one line each."""

    output: str | None = None
    route: str | None = None
    engine_id: str | None = None
    label: str | None = None
    error: str | None = None
    hint: str | None = None
    refusals: list[str] = field(default_factory=list)


def _finite(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def refusals(inputs: Inputs, spec: dict) -> list[str]:
    """One line per input that is missing, unsourced or out of range, in
    `spec["inputs"]` order; [] when all hold."""
    words, r = spec["inputs"], spec["refusals"]
    out: list[str] = []

    def bad(key: str, value, why: str) -> None:
        out.append(r["out_of_range"].format(what=words[key], value=value, why=why))

    for key in words:
        v = getattr(inputs, key)
        if v is None:
            out.append(r["missing"].format(what=words[key]))
            continue
        if isinstance(v, Sourced):
            if not (v.source or "").strip():
                out.append(r["no_source"].format(what=words[key]))
            if not _finite(v.value) or v.value <= 0:
                bad(key, v.value, "it must be a positive number")
            continue
        if key == "stability":
            if v not in spec["stability_classes"]:
                bad(key, v, f"it must be one of {', '.join(spec['stability_classes'])}")
        elif not _finite(v):
            bad(key, v, "it must be a number")
        elif key == "latitude" and not -90 <= v <= 90:
            bad(key, v, "it must be between -90 and 90")
        elif key == "longitude" and not -180 <= v <= 180:
            bad(key, v, "it must be between -180 and 180")
        elif key == "wind_from_deg" and not 0 <= v < 360:
            bad(key, v, "it must be at least 0 and below 360")
        elif key in ("wind_speed_ms", "mixing_height_m") and v <= 0:
            bad(key, v, "it must be positive")
    return out


def canonical(inputs: Inputs) -> str:
    """The inputs as canonical JSON (sorted keys, no whitespace): what a recording
    is keyed by."""
    return json.dumps(asdict(inputs), sort_keys=True, separators=(",", ":"))


def input_key(inputs: Inputs) -> str:
    return hashlib.sha256(canonical(inputs).encode("utf-8")).hexdigest()


def label(source: str, spec: dict) -> str:
    """DN-021 section 3's label, with the emission rate's source."""
    return " ".join(spec["label"].split()).format(source=source)


def _recording_path(recordings_dir, inputs: Inputs) -> Path:
    return Path(recordings_dir) / f"{input_key(inputs)}.json"


def read_recording(recordings_dir, inputs: Inputs, spec: dict) -> dict | None:
    """The recorded run of `inputs`, or None. A recording whose inputs differ from the
    ones its name hashes is
    refused loudly: it is a corrupted file, not a different run."""
    path = _recording_path(recordings_dir, inputs)
    if not path.exists():
        return None
    rec = json.loads(path.read_text(encoding="utf-8"))
    if rec.get("inputs") != canonical(inputs):
        raise RuntimeError(spec["refusals"]["corrupt_recording"].format(path=path))
    return rec


def write_recording(
    recordings_dir, inputs: Inputs, output: str, route: str, engine_id: str
) -> dict:
    """Record one run: the inputs, VSMOKE's output, how it ran and with what. No
    time is written."""
    rec = {
        "inputs": canonical(inputs),
        "input_sha256": input_key(inputs),
        "output": output,
        "route": route,
        "engine_id": engine_id,
    }
    path = _recording_path(recordings_dir, inputs)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return rec


#: An engine: the inputs in, (VSMOKE's output, route, engine id) out. None: not built
#: (the state at HB-128).
Engine = Callable[[Inputs], tuple[str, str, str]]


def run(
    inputs: Inputs,
    spec: dict,
    *,
    recordings_dir: str | Path,
    record: bool = False,
    engine: Engine | None = None,
) -> Outcome:
    """VSMOKE's output for `inputs`: refused when an input is not held; replayed when
    recorded; run and recorded with `record` and an engine; otherwise refused with what
    is missing (the engine, or the recording)."""
    r, hints = spec["refusals"], spec["hints"]
    lines = refusals(inputs, spec)
    if lines:
        return Outcome(error=lines[0], hint=hints["missing"], refusals=lines)
    lab = label(inputs.emission_rate_g_s.source, spec)
    rec = read_recording(recordings_dir, inputs, spec)
    if rec is None and engine is None:
        return Outcome(
            error=" ".join(r["engine_not_held"].split()),
            hint=hints["engine_not_held"],
            label=lab,
        )
    if rec is None and record:
        output, route, engine_id = engine(inputs)
        rec = write_recording(recordings_dir, inputs, output, route, engine_id)
    if rec is None:
        return Outcome(
            error=r["not_recorded"].format(
                sha=input_key(inputs)[:12], dir=spec["recordings_dir"]
            ),
            hint=hints["not_recorded"],
            label=lab,
        )
    return Outcome(
        output=rec["output"],
        route=f"recorded {rec['route']}",
        engine_id=rec["engine_id"],
        label=lab,
    )
