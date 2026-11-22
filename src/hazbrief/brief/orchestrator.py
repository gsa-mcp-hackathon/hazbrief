"""The orchestrator (DN-011 D1 to D6; HB-41): seven channels, eight sections, one brief.

**Channels** (`orchestrator.yaml`). One asyncio task per tool, each through DN-010's
`RecordingClient`, so every call writes its record (D6). A channel's result is the
record's entity hash; the payload is read back from the store. The three tools that take
the footprint as input start when it lands; the rest start at once (D3's scatter). A
channel past its `timeout_s` is cancelled and marked, not waited for. A structured error
(a payload with `error`, such as the no-key Census case, DN-003) or an MCP error marks
it too. Nothing retries inside an assembly (D2).

**Replay** (`replay_stores`). Each channel is resolved from the stores by `records_for`
on the same tool, parameters (`params_for`, which `scripts/record_tool_call_seed.py`
also uses) and, for a tool that reads the footprint, the footprint it used (HB-99), and
no server is spawned. A channel with no record degrades.

**The blackboard** (D2). Each section is `pending`, `rendered` or `degraded`. It settles
when its channels and its `after` sections have. If a channel is not good, the section
degrades with `degraded_label`: "unavailable: <source>, <reason>, attempted at <time>".
Sections render as they become ready, in the render order (D3), so the map comes first.
`on_render` receives the brief after each section settles: the CLI's first paint.

The page is rebuilt from the blackboard at each settle (`hazbrief.brief.render`), so
labels print in the incident's zone once it is known, and the final page is a function
of the records and `now` alone (D7 test d).
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from functools import cache
from pathlib import Path
from typing import Any, Awaitable, Callable, ClassVar

import yaml

from hazbrief.brief.author import NarrativeAuthor, NoAuthor
from hazbrief.evidence import catalog
from hazbrief.evidence import labels as L
from hazbrief.evidence.store import read_entity, records_for, repo_path, utc_now

CONFIG_FILE = Path(__file__).with_name("orchestrator.yaml")


@cache
def _raw_config() -> dict:
    cfg = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8"))
    for key in (
        "channels",
        "sections",
        "render_order",
        "degraded_label",
        "not_run_label",
        "page",
        "location",
        "derive",
        "wind_record",
        "stream",
        "web",
        "author",
        "model",
        "load_read",
        "entry",
    ):
        if key not in cfg:
            raise RuntimeError(f"{CONFIG_FILE} is missing {key!r}")
    if set(cfg["render_order"]) != set(cfg["sections"]):
        raise RuntimeError(f"{CONFIG_FILE}: render_order and sections differ")
    for name, sec in cfg["sections"].items():
        unknown = set(sec["channels"]) - set(cfg["channels"])
        if unknown:
            raise RuntimeError(f"{CONFIG_FILE}: section {name} reads unknown {unknown}")
    if cfg["author"] not in ("none", "model"):
        raise RuntimeError(
            f"{CONFIG_FILE}: author is none or model, not {cfg['author']!r}"
        )
    return cfg


def author_from_config(cfg: dict, *, replay: bool) -> NarrativeAuthor:
    """The author `orchestrator.yaml` `author` names (HB-131R item 4): `none` is
    NoAuthor; `model` the model-backed author, reading only its transcripts in a
    replay."""
    if cfg["author"] == "none":
        return NoAuthor()
    from hazbrief.brief import model_author

    return model_author.from_config(cfg, replay=replay)


def load_config() -> dict:
    """A fresh copy of `orchestrator.yaml`, checked (a test may change its copy)."""
    return copy.deepcopy(_raw_config())


RENDER_ORDER: tuple[str, ...] = tuple(_raw_config()["render_order"])


def params_for(tool: str, scenario: dict, fp: dict | None) -> dict:
    """A tool's MCP arguments for a scenario (`fixtures/scenarios.yaml`'s shape), given
    the footprint's payload when the tool takes the footprint. The ICS 201 is asked for
    in its detailed form, the blocks and Annex A the labels read (HB-41 ADDENDUM-00
    point 2)."""
    if tool in ("assess_incident", "material_response_guidance"):
        return {"incident": scenario["incident"]}
    if tool == "protective_action_footprint":
        p = {"incident": scenario["incident"]}
        if scenario.get("wind"):
            p["wind"] = scenario["wind"]
        return p
    if tool == "population_at_risk":
        area = {"footprint": fp["footprint"], "incident_time": scenario["as_given"]}
        area["period"] = fp["day_night"]["period"]
        return {"area": area}
    if tool == "facilities_in_footprint":
        return {"area": {"footprint": fp["footprint"]}}
    if tool == "receiving_hospitals":
        loc = scenario["incident"]["location"]
        return {"incident": {"location": loc, "footprint": fp["footprint"]}}
    if tool == "build_ics_201":
        req = {"incident": scenario["incident"]}
        if scenario.get("wind"):
            req["wind"] = scenario["wind"]
        return {"request": req, "response_format": "detailed"}
    raise KeyError(f"no parameters for the tool {tool!r}")


@dataclass
class Brief:
    scenario_id: str
    now: datetime
    channels: dict[str, dict] = field(default_factory=dict)
    sections: dict[str, dict] = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)
    html: str = ""
    time_zone: str = "UTC"
    #: the stores the brief's records are read from: the run's own, then the seeds,
    #: whose exchange records a tool call's `used` names
    stores: list[Path] = field(default_factory=list)
    #: the scenario's as-given time, printed in the header (HB-45)
    as_given: str | None = None
    #: the Google Maps key the page's basemap loads with (an application setting,
    #: hazbrief.brief.settings); empty is the Leaflet fallback. Never recorded.
    google_key: str = ""
    #: the derived location record (DN-013 section 2; HB-49) when the scenario gave a
    #: milepost or a crossing; None for the request's bare point (`location.of_brief`)
    location: dict | None = None
    #: the footprint's sample calls after the first (HB-49 step 4): their records
    samples: list[dict] = field(default_factory=list)
    #: the derivations over held data (DN-015; HB-54, `derive.run`): roadblock and rail
    #: candidates and the downstream path, each with what it read or why it is absent
    derived: dict = field(default_factory=dict)
    #: the scenario's `release` block as given (DN-018 ADDENDUM-00 section 3; HB-69):
    #: an application field the server never sees; `derive.puff` validates and reads it
    release: dict | None = None
    #: the scenario's `stated_wind` block as given (HB-70 step 3; `stated_wind`): the
    #: wind at the scene, which replaces the forecast wind for the puff alone
    stated_wind: dict | None = None
    #: the scenario's `fire` block as given (DN-021 section 3; HB-129): the smoke
    #: client's emission rate and heat release, an application field the server never
    #: sees; `smoke.derive` reads it. None: not a fire fixture, so no smoke layer
    fire: dict | None = None
    #: the incident's point as given (latitude, longitude), for a derivation that
    #: needs the point when no footprint was drawn (the brush fire; HB-129)
    point: tuple[float, float] | None = None
    #: the scenario's `wind` as given (the request's), for the same derivation
    given_wind: dict | None = None
    #: the brief's one wind record (HB-133; `wind_record`), resolved before any
    #: channel is called; None when neither a forecast nor a stated wind is held
    wind_record: dict | None = None
    #: True once `assemble` has resolved the record: every consumer then reads it. A
    #: brief built by a test harness without it keeps the engines' own wind choice
    #: (the stated wind of HB-72, the calm stand-in of HB-75)
    wind_resolved: bool = False
    #: the forecast the record was read from (`wind_record.Held`), which the
    #: derivations read instead of fetching it again
    wind_held: Any = None
    #: the brief's weather selection (DN-019 ADDENDUM-01; HB-139;
    #: `weather_source.select`): forecast, observed or stated, who set it
    #: (configuration, scenario or run) and, from a scenario file, its basis
    weather: dict | None = None
    #: the load read (HB-132R Part A; `load_read.Reader`), which `render.page_parts`
    #: runs on every fragment before it is streamed or assembled; None: no read (a
    #: test harness's brief)
    reader: Any = None
    #: the last read's report (`load_read.Read.report`): the cuts applied and
    #: proposed and the words per section, which the appendix prints
    load_read: dict | None = None

    def records(self) -> list[dict]:
        own = [c["record"] for c in self.channels.values() if c.get("record")]
        # the weather snapshots the brief draws (HB-103 Part C; DN-009 C2): cited by
        # hash from the weather section, so listed in the evidence appendix too
        snaps = [
            s["record"]
            for s in ((self.derived or {}).get("snapshots") or {}).values()
            if s.get("held")
        ]
        return own + list(self.samples) + snaps


# ── the event stream (DN-022 section 3; HB-130R Part A) ──────────────────────────────
#
# `assemble(on_event=...)` receives one typed event at a time, in DN-022 section 3's
# set, in the shape AG-UI standardises for agent-to-interface streams (run started, tool
# call started with its arguments, tool call result, state delta, text message, run
# finished; arXiv 2604.08224) without adopting that library. Events carry no wall clock
# (counts, not a clock, DN-022 section 2): a replayed brief gives the same sequence.


@dataclass(frozen=True)
class BriefEvent:
    """One event of the stream. `type` names it on the wire (SSE's `event:` field)."""

    type: ClassVar[str] = ""

    def to_json(self) -> dict:
        return {"type": self.type, **asdict(self)}


@dataclass(frozen=True)
class RunStarted(BriefEvent):
    """After the brief's one wind record is resolved (HB-133) and before any channel is
    called: the brief, the zone its labels print in, and the sections declared in
    `orchestrator.yaml`, in render order."""

    type: ClassVar[str] = "run_started"
    brief_id: str
    time_zone: str
    #: where the zone was read: NWS `points` for the spill (the forecast the wind record
    #: read), else the labels' default zone, which the footprint's zone replaces
    time_zone_from: str
    sections: list[dict]


@dataclass(frozen=True)
class ChannelStarted(BriefEvent):
    """One tool call asked, with its parameters as sent. A footprint over a located
    shape is one call per sample (`sample`, from 0); every other call has none."""

    type: ClassVar[str] = "channel_started"
    tool: str
    parameters: dict
    sample: int | None = None


@dataclass(frozen=True)
class ChannelSettled(BriefEvent):
    """A channel's end: its state (ok, error, missing, timeout, skipped, not_run), the
    record hash it resolved to, why it is not ok, and the as-of of each source its label
    names (DN-010 D4; ok channels only)."""

    type: ClassVar[str] = "channel_settled"
    tool: str
    state: str
    record_sha256: str | None
    reason: str | None
    as_of: list[dict] | None
    #: a footprint sampled over a located shape (HB-49): each sample call's record
    #: hash, in `channel_started`'s sample order (the first is `record_sha256`), so
    #: the evidence log has one hash per call (HB-131R item 2). None for every other
    #: call, and then absent from the JSON, so an unsampled call's line is unchanged
    samples: list[str] | None = None

    def to_json(self) -> dict:
        row = super().to_json()
        if row["samples"] is None:
            del row["samples"]
        return row


@dataclass(frozen=True)
class SectionSettled(BriefEvent):
    """A section's state and its fragment, the static page's own (`render.page_parts`).
    A section whose state or fragment changes after it settled settles again (HB-130R
    ADDENDUM-02 section 2); the last one per section is the static page's."""

    type: ClassVar[str] = "section_settled"
    section: str
    #: pending, rendered or degraded (DN-011 D2); `shown` adds stale
    #: (`render.section_state`)
    state: str
    shown: str
    fragment: str
    labels: list[dict]


@dataclass(frozen=True)
class Alert(BriefEvent):
    """A cue line (HB-115 ADDENDUM-01 section 2), a flag the briefing prints, a
    degraded section's DN-011 D2 label, or one of the checklist's standing integrity
    items (`integrity`; HB-141), each with its receipt. Its id is its place in
    the run's event stream, the `id:` SSE sends it with (from 0), which an
    `alert_withdrawn` names."""

    type: ClassVar[str] = "alert"
    kind: str
    text: str
    receipt: str
    section: str


@dataclass(frozen=True)
class AlertWithdrawn(BriefEvent):
    """An alert a later settle made false (HB-131R ADDENDUM-01 section 1; Issue
    5aa6b127): `alert` is the withdrawn alert's id (its place in the stream), and
    `receipt` the DN-010 D4 line of the record whose settle made it false. A cue line
    is withdrawn when a map settle no longer prints it; a flag when a flags settle
    no longer prints it; a degraded label only when its section settles rendered."""

    type: ClassVar[str] = "alert_withdrawn"
    alert: int
    kind: str
    receipt: str
    section: str


@dataclass(frozen=True)
class Check(BriefEvent):
    """An operator ticked a checklist item (DN-019 ADDENDUM-02 section 3 item 3;
    HB-141; HBD-218): `item` is the item's stream id (an `alert`'s or a
    `channel_started`'s place in the stream) and `time` the server's time, UTC, and
    nothing else. Sent by the live page's server, never by the orchestrator, so a
    committed brief's stream holds none."""

    type: ClassVar[str] = "check"
    item: int
    time: str


@dataclass(frozen=True)
class Uncheck(BriefEvent):
    """An operator unticked a checklist item; the fields are `Check`'s."""

    type: ClassVar[str] = "uncheck"
    item: int
    time: str


@dataclass(frozen=True)
class SiteMoved(BriefEvent):
    """HB-155 item 8 (DN-023 section 4.5): the operator moved a suggested point, or put
    it back on its suggestion (`suggestion`). `point` is command_post, triage or
    staging;
    `coordinates` [longitude, latitude]; `time` the server's time, UTC; and what the
    server recomputed for it (`siting.move`): its distance and bearing (`where`), the
    exclusion parts it lies in (`inside`, each a Warning), the modelled arrival there
    and
    the routes to it. `wind` names the wind record it was moved under, so a replay under
    another record marks the points for review. Sent by the live page's server, written
    first to the serve's checks file and replayed at its place, as a tick is
    (HB-141)."""

    type: ClassVar[str] = "site_moved"
    point: str
    coordinates: list
    time: str
    suggestion: bool
    where: str
    inside: list
    arrival: dict | None
    routes: list
    wind: str | None


@dataclass(frozen=True)
class AreaRadiusSet(BriefEvent):
    """HB-155 ADDENDUM-01 item 6 and ADDENDUM-02 item 5 (DN-023 section 5.5): the reader
    chose an Area radius step (`radius_m`; 0 is "widen to nearest"). A view filter, not
    configuration (HBD-328, HBD-371): it changes what is drawn and listed, never a
    record. `held` says whether the step's data was in hand; a live serve reads a step
    not in hand and sends its facilities (`features`, the services layer's GeoJSON)."""

    type: ClassVar[str] = "area_radius_set"
    radius_m: float
    time: str
    held: bool
    features: list


@dataclass(frozen=True)
class Narrative(BriefEvent):
    """The author's own text for a section; never from `NoAuthor`, which writes no word
    of its own (author.py), so a brief built without a model has none."""

    type: ClassVar[str] = "narrative"
    section: str
    text: str


@dataclass(frozen=True)
class StageReached(BriefEvent):
    """HB-158 ADDENDUM-01 item 4 (the operator: "let all the information come in and
    ... only present the finished thing"): the critical set is in, so the live page
    shows its checklist, layer list and tabs; a later change to a checklist item is
    marked as an update. In this build the derivations wait for every channel (the
    `derive.run` after the channels' gather), so stage one is everything up to the
    derivations' map, the suggested points included; HB-155 ADDENDUM-02's stage two
    (`derive.stage_two`) follows it."""

    type: ClassVar[str] = "stage_reached"
    stage: str


@dataclass(frozen=True)
class CloudHour(BriefEvent):
    """HB-189 (DN-028 ADDENDUM-14 decision 4): one simulated hour of the moving cloud,
    the moment the engine's driver has read it from the puff file and extracted its
    levels, while the run carries on; a replay sends the record's hours in the order
    they landed. It carries the hour and how many of its level extractions were made,
    no wall clock (DN-022 section 2: counts, not a clock); the record holds the engine's
    wall time to each hour."""

    type: ClassVar[str] = "cloud_hour"
    hour: int
    extracted: int


@dataclass(frozen=True)
class CloudFrame(BriefEvent):
    """HB-192 (DN-024 ADDENDUM-01 decision 4): one 15-minute frame of the moving cloud,
    the moment the engine's driver has written its mesh, while the run carries on; a
    replay sends the frames record's frames in the order they landed. It carries the
    frame's minute, its place in the run (`k` of `n`, to the horizon's minute), the
    vertical setting, and each level's outline as GeoJSON (drawn from the mesh and
    simplified); never the mesh, and no wall clock (DN-022 section 2)."""

    type: ClassVar[str] = "cloud_frame"
    minute: int
    k: int
    n: int
    until_min: int
    vertical_setting_m: float | None
    outlines: dict


@dataclass(frozen=True)
class RunFinished(BriefEvent):
    """The final page's sha256, which equals the static render's of the same records
    and `now` (DN-022 section 3), the distinct sections settled over those declared, and
    the tool calls this assembly made (0 when it replays)."""

    type: ClassVar[str] = "run_finished"
    sha256: str
    settled: int
    declared: int
    calls_made: int


def evidence_line(ev: BriefEvent) -> dict:
    """An event as the committed evidence holds it (`the HB-130 evidence`): a fragment
    is its sha256 and length, not its bytes (a map fragment is up to 2.3 MB; the test
    compares the bytes with a fresh static render instead)."""
    row = ev.to_json()
    if isinstance(ev, SectionSettled):
        raw = row.pop("fragment").encode("utf-8")
        row["fragment_sha256"] = hashlib.sha256(raw).hexdigest()
        row["fragment_bytes"] = len(raw)
    return row


class _TapAuthor:
    """An author whose every answer is also kept, by section, for `narrative` events."""

    def __init__(self, inner: NarrativeAuthor):
        self.inner = inner
        self.name = inner.name
        self.written: dict[str, str] = {}

    def write(self, section: str, payloads: dict, **context) -> str | None:
        md = self.inner.write(section, payloads, **context)
        if md is not None:
            self.written[section] = md
        return md


def _zone_held(held: Any) -> str | None:
    """The zone NWS `points` names for the forecast the wind record read, or None."""
    body = getattr(getattr(held, "points", None), "body", None)
    zone = ((body or {}).get("properties") or {}).get("timeZone")
    return zone if isinstance(zone, str) else None


def _point_of(scenario: dict) -> tuple[float, float] | None:
    """The incident's (latitude, longitude) as given, or None when it gives none."""
    loc = (scenario.get("incident") or {}).get("location") or {}
    if "latitude" in loc and "longitude" in loc:
        return (float(loc["latitude"]), float(loc["longitude"]))
    return None


def _good(ch: dict) -> bool:
    return ch["state"] == "ok"


def _source_names(cfg: dict, channel: str, payload: Any = None) -> str:
    """The sources a degraded label names: the channel's live and file sources, or every
    source when it reads only packs and code. A structured error the channel's own
    reading of its input returned (a payload with `error` and no `assessment`, where the
    channel names `input_error_sources`) names those sources instead: the failure is
    theirs, not the live services' (HB-207 item 12)."""
    spec = cfg["channels"][channel]
    if (
        spec.get("input_error_sources")
        and isinstance(payload, dict)
        and payload.get("error")
        and "assessment" not in payload
    ):
        return "; ".join(catalog.row(i)["name"] for i in spec["input_error_sources"])
    rows = [catalog.row(i) for i in spec["sources"]]
    outside = [r for r in rows if r["kind"] in ("api", "file")]
    return "; ".join(r["name"] for r in (outside or rows))


def incident_time_zone(brief: Brief, default: str) -> str:
    """The zone the brief prints in: the one NWS gives for the spill point. It is read
    from the footprint's wind when NWS gave the wind, else from the ICS 201's Block 3,
    else the default."""
    fp = brief.channels.get("protective_action_footprint", {}).get("payload") or {}
    tz = (fp.get("wind") or {}).get("time_zone")
    if tz:
        return tz
    ics = brief.channels.get("build_ics_201", {}).get("payload") or {}
    md = ics.get("markdown") or ""
    marker = "Local times are in "
    if marker in md:
        return md.split(marker, 1)[1].split(",", 1)[0].split()[0]
    return default


async def assemble(
    scenario: dict,
    *,
    now: datetime,
    store: Path | None = None,
    replay_stores: list[Path] | None = None,
    config: dict | None = None,
    server_entry: Path | None = None,
    env: dict[str, str] | None = None,
    author: NarrativeAuthor | None = None,
    on_render: Callable[[Brief], None] | None = None,
    on_event: Callable[[BriefEvent], None] | None = None,
    on_brief: Callable[[Brief], None] | None = None,
    google_key: str = "",
    reuse_held: bool = False,
    used_for: Callable[[str, dict], Awaitable[list[str]]] | None = None,
    derive_replay: bool | None = None,
    weather_fields: dict | None = None,
    reader: Any = None,
) -> Brief:
    """Assemble one brief. Live (through the recording client into `store`) unless
    `replay_stores` is given, which reads the records and calls nothing. With
    `reuse_held`, a live assembly reads a call `store` already holds (same tool, same
    parameters, the same footprint used; HB-99) instead of making it again, so
    recording a scenario's brief is its own resume (HB-49: the location scenarios'
    seed). `used_for(tool, params)`, when given,
    names the evidence a live call read beyond the footprint (the upstream exchange
    records), so its record's `used` holds them as the seeded records' do.

    A scenario that gives its location as a milepost or a crossing (`given`, HB-49) is
    located first (`location.locate`, from the recorded exchanges when replaying). The
    footprint is then the union over samples along the shape (`union`), and every other
    tool is asked about the shape's representative point and the union. A channel the
    scenario declares `not_run` is not called; its sections say why.

    When every channel has settled, the derivations run (`derive.run`, DN-015; HB-54)
    and the page is drawn once more with them. They read recorded exchanges when the
    brief replays, unless `derive_replay` is False (`scripts/record_derivations.py`
    records them that way).

    `on_event`, when given, receives the stream of DN-022 section 3 (`BriefEvent`): the
    run's start once the wind record is resolved, each call asked and each channel
    settled, each section settled with its fragment (again when its fragment changes,
    as the derived pass can), the alerts and their withdrawals (HB-131R ADDENDUM-01),
    the author's own text, and the run's end with the final page's sha256 (HB-130R).

    `on_brief`, when given, receives the blackboard once, before any channel is
    called, so a live view can read the records it points to as they land (the live
    page's record route and report, HB-131R). It must not change it.

    `weather_fields` are the run's weather fields (`weather_source.FIELDS`: the CLI's
    flags, the `--serve` page's query), over `orchestrator.yaml` `weather` and the
    scenario's `weather:` block (HB-139). A selection that cannot be read raises
    `weather_source.WeatherRefused`, naming the field or the acquisition, before any
    call is made.

    `reader` is the load read (`load_read.Reader`, HB-132R Part A), run on every
    fragment before it is streamed or assembled; by default `orchestrator.yaml`
    `load_read`'s, whose model verdicts a replay reads from their transcripts."""
    from hazbrief.brief import (
        derive,
        layers,
        load_read,
        location,
        render,
        union,
        wind_record,
    )

    cfg = config or load_config()
    author = author or author_from_config(cfg, replay=replay_stores is not None)
    brief = Brief(
        scenario_id=scenario.get("id", "scenario"),
        now=now,
        as_given=scenario.get("as_given"),
        google_key=google_key,
        release=scenario.get("release"),
        stated_wind=scenario.get("stated_wind"),
        fire=scenario.get("fire"),
        point=_point_of(scenario),
        given_wind=scenario.get("wind"),
        reader=reader
        or load_read.reader_from_config(cfg, replay=replay_stores is not None),
    )
    # The weather source (DN-019 ADDENDUM-01; HB-139), checked before anything is
    # located or called: a refused selection stops the run here, naming the field
    from hazbrief.brief import weather_source

    brief.weather = weather_source.select(cfg, scenario.get("weather"), weather_fields)
    seeds = [repo_path("seed_calls_store_dir"), repo_path("seed_store_dir")]
    not_run = dict(scenario.get("not_run") or {})
    if scenario.get("given"):
        brief.location = await location.locate(
            scenario["given"], cfg, replay=replay_stores is not None
        )
        if brief.location["shape"] is None:
            # nothing to ask any tool about: every tool takes the incident's location
            # (HB-50: no match, no crossing, the geocoder unavailable); nothing is
            # guessed, and every section says why
            not_run.update({name: brief.location["label"] for name in cfg["channels"]})
        else:
            lon, lat = union.representative(brief.location)
            scenario = {
                **scenario,
                "incident": {
                    **scenario["incident"],
                    "location": {"latitude": lat, "longitude": lon},
                },
            }
    # One brief, one wind (HB-133): the record is resolved here, once, before any
    # channel is called, from the forecast at the point the derivations read it (the
    # located shape's forecast point, else the incident's), and the request the server
    # orients the footprint on carries it (`wind_record.request_scenario`)
    replay = replay_stores is not None if derive_replay is None else derive_replay
    if brief.location and brief.location.get("shape"):
        from shapely.geometry import shape as _shape

        wx_point = derive.forecast_point(_shape(brief.location["shape"]))
    else:
        wx_point = _point_of(scenario)
    brief.wind_record, brief.wind_held = await wind_record.resolve(
        scenario, wx_point, cfg, now=now, replay=replay, weather=brief.weather
    )
    brief.wind_resolved = True
    scenario = wind_record.request_scenario(scenario, brief.wind_record)
    if replay_stores is not None:
        brief.stores = list(replay_stores)
    elif store is not None:
        brief.stores = [Path(store)] + seeds
    brief.channels = {
        name: {"state": "pending", "tool": name} for name in cfg["channels"]
    }
    brief.sections = {
        name: {"state": "pending", "reason": None, "labels": [], "title": sec["title"]}
        for name, sec in cfg["sections"].items()
    }
    settled = {name: asyncio.Event() for name in cfg["channels"]}
    t0 = time.monotonic()
    default_tz = L.config()["default_time_zone"]
    if on_event is not None and not isinstance(author, NoAuthor):
        author = _TapAuthor(author)
    stream = cfg["stream"]
    #: per section, the (state, fragment) last streamed; the alerts and narratives sent
    streamed: dict[str, tuple[str, str]] = {}
    #: the alerts on the panel now (sent and not withdrawn): key -> the alert's id,
    #: its place in the stream (HB-131R ADDENDUM-01 section 1)
    live_alerts: dict[tuple, int] = {}
    narrated: dict[str, str] = {}
    calls_made = [0]
    #: the events sent so far: the next event's id
    sent = [0]
    #: the DN-010 D4 line of the record whose settle is being drawn: what an
    #: `alert_withdrawn` names as the record that made the alert false
    cause = [stream["withdrawn_before_any_record"]]
    emit = None
    if on_event is not None:

        def emit(ev: BriefEvent) -> int:
            """Send one event; its id is its place in the stream, from 0. A consumer
            whose stream also carries events the orchestrator did not send (the live
            page's operator checks, HB-141) returns the place it gave the event, and
            that is its id; otherwise the id is the count of events sent."""
            place = on_event(ev)
            sent[0] += 1
            if isinstance(place, int) and not isinstance(place, bool):
                return place
            return sent[0] - 1

    if on_brief is not None:
        on_brief(brief)

    ck = cfg["checklist"]

    def old_lines(name: str) -> list[str]:
        """HB-158 ADDENDUM-01 item 3: one line per source of section `name` past its
        horizon, answering the operator's three questions: how old it is (its as-of,
        its age and its limit, `labels.old_phrase`), whether it updates by itself (no:
        the brief reads each channel once), and what the reader does (`old_action`:
        on a replay nothing, this is a recording; else by the source's provenance)."""
        out: list[str] = []
        tz = brief.time_zone
        for lab in brief.sections[name]["labels"]:
            for s in lab["sources"]:
                if not s.get("stale"):
                    continue
                kind = "replay" if replay_stores is not None else s["provenance_class"]
                acts = ck["old_action"]
                text = ck["old_line"].format(
                    source=s["name"],
                    as_of=L.as_of_phrase(s, tz),
                    old=L.old_phrase(s),
                    update=ck["old_update"],
                    action=acts.get(kind, acts["live_call"]),
                )
                if text not in out:
                    out.append(text)
        return out

    def alert_changes(name: str) -> list[tuple[tuple | None, BriefEvent]]:
        """What a section's settle does to the alerts panel. Withdrawals first: on the
        map, each cue line it no longer prints; on the flags (rendered), each flag the
        briefing no longer prints; on any section that settles rendered, its degraded
        labels. Then the new alerts, each once while it stands: its DN-011 D2 label
        when degraded; on the map, the cue block's lines (HB-130R ADDENDUM-01 section 2,
        in `cue_lines` order); on the flags, the flags the briefing prints, in its
        order (high, medium, low, then by id: `flags.for_briefing`)."""
        sec = brief.sections[name]
        now_true: list[tuple[tuple, Alert]] = []
        scopes: list[str] = []
        if sec["state"] == "degraded":
            receipt = stream["degraded_receipt"].format(title=sec["title"])
            now_true.append(
                (
                    ("degraded", name, sec["reason"]),
                    Alert("degraded", sec["reason"], receipt, name),
                )
            )
        if sec["state"] == "rendered":
            scopes.append("degraded")
        if sec["state"] != "pending":
            # HB-158 ADDENDUM-01 item 3: each source of the section past its horizon
            # is a Data gaps item saying how old it is, whether it updates by itself
            # and what to do; the section's own settle withdraws it
            scopes.append("old")
            for text in old_lines(name):
                receipt = ck["old_receipt"].format(title=sec["title"])
                # keyed by its text: the ICS 201 reprints the other sections'
                # sources, and one old source is one item
                now_true.append((("old", text), Alert("old", text, receipt, name)))
        if name == "map" and brief.derived:
            # HB-158 item 4: each layer that could not be drawn is a Data gaps item
            # worded as its layer list line, once the derivations have run (before
            # them every weather layer reads "not run")
            scopes.append("layer_gap")
            for g in render.layer_gaps(brief, cfg):
                receipt = cfg["map"]["layer_gap_receipt"].format(reason=g["reason"])
                now_true.append(
                    (
                        ("layer_gap", g["layer"], g["text"]),
                        Alert("layer_gap", g["text"], receipt, name),
                    )
                )
            # HB-155 ADDENDUM-05 item 3: a point missing beside drawn ones is its own
            # Data gaps item
            for text in layers.siting_gaps(brief, cfg):
                receipt = cfg["map"]["layer_gap_receipt"].format(reason=text)
                now_true.append(
                    (
                        ("layer_gap", "sited_points", text),
                        Alert("layer_gap", text, receipt, name),
                    )
                )
        if name == "map":
            scopes.append("cue")
            for row in layers.cue_lines(brief, cfg):
                now_true.append(
                    (
                        ("cue", row["text"], row["receipt"]),
                        Alert("cue", row["text"], row["receipt"], name),
                    )
                )
            # HB-157: the wind-shift Verify item and the arrival line, from the
            # modelled time, withdrawn like a cue line when a later settle drops them
            scopes += ["shift", "arrival"]
            for row in layers.time_alerts(brief, cfg):
                now_true.append(
                    (
                        (row["kind"], row["text"], row["receipt"]),
                        Alert(row["kind"], row["text"], row["receipt"], name),
                    )
                )
            # HB-173 (DN-028 ADDENDUM-04 decision 7): the two engines of a dense
            # release, one item: a disagreement's alert, or the one line where it
            # would be; withdrawn like a cue line when a later settle drops it
            # DN-028 ADDENDUM-10 decision 4: under a stable class, its one line
            scopes += ["engines", "engines_agree", "engines_stable"]
            for row in layers.engine_alerts(brief, cfg):
                now_true.append(
                    (
                        (row["kind"], row["text"], row["receipt"]),
                        Alert(row["kind"], row["text"], row["receipt"], name),
                    )
                )
        if name == "flags" and sec["state"] == "rendered":
            scopes.append("flag")
            fp_ch = brief.channels["protective_action_footprint"]
            flags = (fp_ch.get("payload") or {}).get("flags") or {}
            by_id = {f["rule_id"]: f for f in flags.get("all") or []}
            # the record the flag was evaluated in, as its DN-010 D4 label line
            # (HB-131R item 1: each panel line prints its receipt in that form)
            fp_line = settle_receipt("protective_action_footprint", fp_ch)
            for rid in (flags.get("briefing") or {}).get("rule_ids") or []:
                f = by_id[rid]
                receipt = stream["flag_receipt"].format(
                    rule_id=rid, priority=f.get("priority"), record=fp_line
                )
                now_true.append(
                    (("flag", rid), Alert("flag", f.get("sentence", ""), receipt, name))
                )
        keys = {k for k, _ in now_true}
        out: list[tuple[tuple | None, BriefEvent]] = []
        for key, aid in list(live_alerts.items()):
            # a degraded label is the section's own: only its section withdraws it
            mine = key[0] != "degraded" or key[1] == name
            if key[0] == "old":
                # an old source stands while any settled section still prints it
                mine = key[1] not in {
                    t
                    for n, s in brief.sections.items()
                    if s["state"] != "pending"
                    for t in old_lines(n)
                }
            if key[0] in scopes and mine and key not in keys:
                del live_alerts[key]
                gone = AlertWithdrawn(
                    alert=aid, kind=key[0], receipt=cause[0], section=name
                )
                out.append((None, gone))
        fresh: set[tuple] = set()
        for key, a in now_true:
            if key not in live_alerts and key not in fresh:
                fresh.add(key)
                out.append((key, a))
        return out

    def publish(parts: dict[str, str]) -> None:
        """Stream every settled section whose state or fragment differs from what was
        last streamed for it, in render order, each followed by its alerts and its
        author's own text."""
        for name in RENDER_ORDER:
            sec = brief.sections[name]
            if sec["state"] == "pending":
                continue
            key = (sec["state"], parts[name])
            if streamed.get(name) == key:
                continue
            streamed[name] = key
            emit(
                SectionSettled(
                    section=name,
                    state=sec["state"],
                    shown=render.section_state(brief, name),
                    fragment=parts[name],
                    labels=copy.deepcopy(sec["labels"]),
                )
            )
            for key, ev in alert_changes(name):
                aid = emit(ev)
                if key is not None:
                    live_alerts[key] = aid
            text = getattr(author, "written", {}).get(name)
            if text is not None and brief.load_read:
                # the author's text as the section prints it: the read's cuts made
                # on it too (HB-132R item 2)
                from hazbrief.brief import load_read

                text = load_read.apply_text(text, brief.load_read["applied"], name)
            if text is not None and narrated.get(name) != text:
                narrated[name] = text
                emit(Narrative(section=name, text=text))

    def draw() -> None:
        """The page from the blackboard, in the incident's zone once known; the first
        paint (`on_render`) and the stream (`on_event`) read the same render."""
        brief.time_zone = incident_time_zone(brief, default_tz)
        parts = render.page_parts(brief, cfg, author)
        brief.html = render.page_html(brief, cfg, author, parts)
        if emit is not None:
            publish(parts)
        if on_render:
            on_render(brief)

    def asked(name: str, params: dict, sample: int | None = None) -> None:
        if emit is not None:
            emit(
                ChannelStarted(
                    tool=name, parameters=copy.deepcopy(params), sample=sample
                )
            )

    def event(kind: str, **kw):
        brief.events.append({"t": round(time.monotonic() - t0, 3), "event": kind, **kw})

    def degrade_two_winds(derived: dict | None) -> bool:
        """The map degraded, naming both records, when a consumer read a wind other
        than the brief's record (HB-133 item 3; `wind_record.check`)."""
        fp = brief.channels["protective_action_footprint"].get("payload")
        try:
            wind_record.check(brief.wind_record, fp, derived, cfg)
        except wind_record.WindRecordsDisagree as exc:
            sec = brief.sections["map"]
            sec["state"] = "degraded"
            sec["reason"] = str(exc)
            sec["two_winds"] = True
            event("degrade", section="map")
            return True
        return False

    def settle_sections():
        changed = True
        while changed:
            changed = False
            for name in RENDER_ORDER:
                sec, spec = brief.sections[name], cfg["sections"][name]
                if sec["state"] != "pending":
                    continue
                chans = [brief.channels[c] for c in spec["channels"]]
                if any(c["state"] == "pending" for c in chans):
                    continue
                if any(
                    brief.sections[a]["state"] == "pending"
                    for a in spec.get("after", [])
                ):
                    continue
                bad = next(
                    (c for c, ch in zip(spec["channels"], chans) if not _good(ch)), None
                )
                if bad is None:
                    sec["state"] = "rendered"
                    sec["labels"] = [
                        L.label_for(ch["record"], now, ch["payload"]) for ch in chans
                    ]
                    # HB-114 step 5a.1 (Issue 0a7ff478): a payload that answered in
                    # part (its `errors` name the queries that failed) degrades its
                    # section, which still prints what did answer
                    failed = [
                        e
                        for ch in chans
                        if spec.get("partial_label")
                        for e in (ch["payload"] or {}).get("errors") or []
                    ]
                    if failed:
                        sec["state"] = "degraded"
                        sec["partial"] = True
                        sec["reason"] = spec["partial_label"].format(
                            n=len(failed),
                            sources=", ".join(
                                sorted({str(e.get("source")) for e in failed})
                            ),
                        )
                    # HB-133: a footprint oriented on another wind than the brief's
                    # one record is never drawn beside it (DN-011 D2)
                    if name == "map" and brief.wind_resolved:
                        degrade_two_winds(None)
                    event("render", section=name)
                elif brief.channels[bad]["state"] == "not_run":
                    sec["state"] = "degraded"
                    sec["reason"] = cfg["not_run_label"].format(
                        source=_source_names(cfg, bad),
                        reason=brief.channels[bad]["reason"],
                    )
                    event("degrade", section=name)
                else:
                    ch = brief.channels[bad]
                    sec["state"] = "degraded"
                    sec["reason"] = cfg["degraded_label"].format(
                        source=_source_names(cfg, bad, ch.get("payload")),
                        reason=ch["reason"],
                        attempted=L.when(ch["started"], default_tz),
                    )
                    event("degrade", section=name)
                changed = True
                draw()

    def settle_receipt(name: str, ch: dict) -> str:
        """The DN-010 D4 line of a settled channel's record (its label line, as the
        ICS 201's block sources print it), or, for a channel with no record, what it
        settled as. A sampled footprint's payload is the union, not the record's
        entity, so its body is read back from the stores."""
        rec = ch.get("record")
        if not rec:
            return stream["withdrawn_by_no_record"].format(
                tool=name.replace("_", " "), state=ch["state"], reason=ch.get("reason")
            )
        body = ch["payload"]
        if ch.get("samples"):
            _, body = L.latest(brief.stores, rec["entity"]["sha256"])
        lab = L.label_for(rec, now, body)
        return L.label_line(name, rec, lab, brief.time_zone).removeprefix("- ")

    def finish(name: str, **result):
        ch = brief.channels[name]
        ch.update(result)
        ch["seconds"] = round(time.monotonic() - t0, 3)
        event("channel", channel=name, state=ch["state"])
        if ch.get("origin") == "call":
            calls_made[0] += 1
        if emit is not None:
            cause[0] = settle_receipt(name, ch)
            as_of = None
            if ch["state"] == "ok":
                lab = L.label_for(ch["record"], now, ch["payload"])
                as_of = [
                    {"source": s["id"], "as_of": s["as_of"]} for s in lab["sources"]
                ]
            emit(
                ChannelSettled(
                    tool=name,
                    state=ch["state"],
                    record_sha256=ch.get("sha"),
                    reason=ch.get("reason"),
                    as_of=as_of,
                    samples=list(ch["samples"]) if ch.get("samples") else None,
                )
            )
        settled[name].set()
        settle_sections()

    async def resolve(name: str, call):
        spec = cfg["channels"][name]
        fp_payload, used = None, None
        if name in not_run:
            finish(name, state="not_run", started=None, reason=not_run[name])
            return
        if name == location.FOOTPRINT and brief.location:
            await resolve_over_shape(name, call)
            return
        if spec.get("needs"):
            dep = spec["needs"]
            await settled[dep].wait()
            if not _good(brief.channels[dep]):
                title = dep.replace("_", " ")
                finish(
                    name,
                    state="skipped",
                    started=utc_now(),
                    reason=f"needs the {title}, which is unavailable",
                    origin=brief.channels[dep].get("origin"),
                )
                return
            fp_payload = brief.channels[dep]["payload"]
            used = brief.channels[dep].get("samples") or [brief.channels[dep]["sha"]]
        params = params_for(name, scenario, fp_payload)
        started = utc_now()
        asked(name, params)
        try:
            result = await asyncio.wait_for(call(name, params, used), spec["timeout_s"])
        except TimeoutError:
            finish(
                name,
                state="timeout",
                started=started,
                reason=f"timed out after {spec['timeout_s']} s",
            )
            return
        sha, payload, record, origin = result
        if record is None:
            finish(
                name,
                state="missing",
                started=started,
                origin=origin,
                reason="no record in the store",
            )
            return
        reason = None
        if record["activity"].get("is_error"):
            reason = "error: " + _error_text(payload)
        elif isinstance(payload, dict) and payload.get("error"):
            reason = f"error: {payload['error']}"
        finish(
            name,
            state="error" if reason else "ok",
            # the attempt is the recorded call: its own start, so a replayed degraded
            # label prints when the call was made, not when it was read (HB-45)
            started=record["activity"]["startedAtTime"],
            reason=reason,
            sha=sha,
            payload=payload,
            record=record,
            origin=origin,
        )

    async def resolve_over_shape(name: str, call):
        """The footprint over the derived location (`union`): the first sample's call
        sets the spacing, the rest follow, and the channel's payload is the union. Any
        sample that fails fails the channel, so no union is drawn from part of the
        shape."""
        spec = cfg["channels"][name]

        def params_at(lon: float, lat: float) -> dict:
            inc = {
                **scenario["incident"],
                "location": {"latitude": lat, "longitude": lon},
            }
            return params_for(name, {**scenario, "incident": inc}, None)

        async def one(lon, lat, i):
            params = params_at(lon, lat)
            asked(name, params, i)
            try:
                return await asyncio.wait_for(
                    call(name, params, None), spec["timeout_s"]
                )
            except TimeoutError:
                return None

        first = union.samples(brief.location, float("inf"), cfg)[0]
        started = utc_now()
        results = [await one(*first, 0)]
        if results[0] is None or results[0][2] is None:
            finish(name, state="missing", started=started, reason="no first sample")
            return
        spacing = union.spacing_m(results[0][1], cfg)
        for i, (lon, lat) in enumerate(
            union.samples(brief.location, spacing, cfg)[1:], start=1
        ):
            results.append(await one(lon, lat, i))
        for r in results:
            why = None
            if r is None:
                why = f"a sample timed out after {spec['timeout_s']} s"
            elif r[2] is None:
                why = "a sample has no record in the store"
            elif r[2]["activity"].get("is_error") or (
                isinstance(r[1], dict) and r[1].get("error")
            ):
                why = "error: " + (
                    r[1]["error"] if isinstance(r[1], dict) else _error_text(r[1])
                )
            if why:
                finish(name, state="error", started=started, reason=why)
                return
        sha, payload0, record, origin = results[0]
        brief.samples = [r[2] for r in results[1:]]
        finish(
            name,
            state="ok",
            started=record["activity"]["startedAtTime"],
            reason=None,
            sha=sha,
            payload=union.union([r[1] for r in results], brief.location, spacing, cfg),
            record=record,
            origin=origin,
            samples=[r[0] for r in results],
        )

    if emit is not None:
        held_zone = _zone_held(brief.wind_held)
        emit(
            RunStarted(
                brief_id=brief.scenario_id,
                time_zone=held_zone or default_tz,
                time_zone_from=stream["zone_from"]["held" if held_zone else "default"],
                sections=[
                    {"name": n, "title": cfg["sections"][n]["title"]}
                    for n in RENDER_ORDER
                ],
            )
        )
        # the checklist's standing integrity items (DN-019 ADDENDUM-02 section 3 item
        # 1; HB-141; HBD-218), one alert each, before any channel: they are true of
        # every brief, so no settle withdraws them
        for row in cfg["checklist"]["integrity"]:
            emit(Alert("integrity", row["text"], row["receipt"], row["section"]))
    if replay_stores is not None:

        async def from_store(name, params, used):
            # keyed by what the call used as well (HB-99): a reader whose parameters
            # another scenario shares reads the record made on this scenario's
            # footprint, not the other's
            for st in replay_stores:
                held = records_for(st, name, params, used)
                if held:
                    rec = held[-1]
                    sha = rec["entity"]["sha256"]
                    return sha, read_entity(st, sha), rec, "store"
            return None, None, None, "store"

        await asyncio.gather(*(resolve(n, from_store) for n in cfg["channels"]))
    else:
        from hazbrief.evidence.client import RecordingClient

        if store is None:
            raise ValueError("a live assembly needs the store its records go into")
        async with RecordingClient(store, env=env, server_entry=server_entry) as rc:

            async def live(name, params, used):
                held = records_for(store, name, params, used) if reuse_held else []
                # a held call is reused only when it succeeded; a failed one is a row
                # in the store, and the next recording run calls again (standards
                # section 15, rule 7), whose record replay then reads (the latest)
                if held and not _failed(
                    held[-1], read_entity(store, held[-1]["entity"]["sha256"])
                ):
                    rec = held[-1]
                    sha = rec["entity"]["sha256"]
                    return sha, read_entity(store, sha), rec, "store"
                if used_for is not None:
                    used = sorted(set(used or []) | set(await used_for(name, params)))
                sha, _ = await rc.call(name, params, used=used or None)
                (rec,) = [
                    r
                    for r in records_for(store, name, params, used)
                    if r["entity"]["sha256"] == sha
                ][-1:]
                # the payload as its record holds it, as a replay reads it: the page
                # is a function of the records (DN-011 D7), so a live brief and its
                # replay print the same bytes. The client's own copy keeps the tool's
                # key order, which the record's canonical JSON does not (HB-132R:
                # facilities' and population's rows reordered between the two)
                return sha, read_entity(store, sha), rec, "call"

            await asyncio.gather(*(resolve(n, live) for n in cfg["channels"]))
    # HB-189 (DN-028 ADDENDUM-14 decision 4): each hour of the moving cloud is sent the
    # moment the engine's driver hands it over; the engine runs on a worker thread
    # (`derive.run`), so the event is put on this loop from there
    sink_token = None
    if emit is not None:
        from hazbrief.brief import scichem as SC

        loop = asyncio.get_running_loop()

        def hour_sink(row: dict) -> None:
            ev = CloudHour(hour=int(row["hour"]), extracted=int(row["extracted"]))
            loop.call_soon_threadsafe(emit, ev)

        sink_token = SC.HOUR_SINK.set(hour_sink)
        landed = [0]

        def frame_sink(fr: dict) -> None:
            # HB-192: each frame's outlines as GeoJSON about the run's site
            landed[0] += 1
            site = fr["site"]
            ev = CloudFrame(
                minute=int(fr["minute"]),
                k=landed[0],
                n=int(fr["n"]),
                until_min=int(fr["until_min"]),
                vertical_setting_m=fr.get("vertical_setting_m"),
                outlines={
                    t: SC.to_geojson(r, site["lat"], site["lon"])
                    for t, r in (fr.get("outlines") or {}).items()
                    if r
                },
            )
            loop.call_soon_threadsafe(emit, ev)

        frame_token = SC.FRAME_SINK.set(frame_sink)
    try:
        brief.derived = await derive.run(brief, cfg, replay=replay)
    finally:
        if sink_token is not None:
            SC.HOUR_SINK.reset(sink_token)
            SC.FRAME_SINK.reset(frame_token)
        # the hours put on the loop from the engine's thread are sent before the
        # derivations' own events
        await asyncio.sleep(0)
    event("derived")
    cause[0] = stream["withdrawn_by_derivations"]
    if brief.sections["map"]["state"] == "rendered":
        degrade_two_winds(brief.derived)
    draw()
    if emit is not None:
        emit(StageReached(stage=cfg["web"]["shell"]["critical_stage"]))
    # HB-155 ADDENDUM-02 item 4 (ADDENDUM-05 item 6): stage two of the services in the
    # area, after the brief is presented; the sited points are stage one's and do not
    # move. A static build runs it too, so the static page is the live page's last state
    with derive._replaying(replay):
        if await derive.stage_two_run(brief, cfg):
            event("stage_two")
            draw()
    if emit is not None:
        emit(
            RunFinished(
                sha256=hashlib.sha256(brief.html.encode("utf-8")).hexdigest(),
                settled=sum(s["state"] != "pending" for s in brief.sections.values()),
                declared=len(brief.sections),
                calls_made=calls_made[0],
            )
        )
    return brief


def _failed(record: dict, payload: Any) -> bool:
    """A recorded call that failed: an MCP error, or a structured error payload."""
    return bool(record["activity"].get("is_error")) or (
        isinstance(payload, dict) and bool(payload.get("error"))
    )


def _error_text(payload: Any) -> str:
    """An MCP error result's text, as the client returned its content blocks."""
    if isinstance(payload, list):
        texts = [b.get("text", "") for b in payload if isinstance(b, dict)]
        return " ".join(t for t in texts if t)[:300] or "the tool returned an error"
    return str(payload)[:300]
