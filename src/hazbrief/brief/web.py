"""The live page: the brief's blackboard served over Server-Sent Events (DN-022 sections
3, 8 and 9; HB-130R Part B).

    hazbrief brief SCENARIO.json --serve --replay --now 2026-10-26T12:00:00Z --no-google

A Starlette application bound to loopback (`orchestrator.yaml` `web.host` and
`web.port`; HB-89: the route has no authentication). HB-130R's three routes:

- `GET /`: the page shell. The static page's stylesheet, Leaflet's pinned assets and its
  map script, a progress strip in the header, the map's place, and below it the three
  columns of DN-022 section 4 (HB-131R): the alerts panel with the question box, the
  brief (every declared section as its pending fragment, in render order, then the
  commander's report), and the evidence log. `static/live.js` opens the stream.
- `GET /brief/<id>/events`: the run's events (`orchestrator.BriefEvent`), each as
  `event: <type>`, `id: <n>` and `data: <json>`. A reconnecting browser sends
  `Last-Event-ID` and is sent what follows it.
- `GET /brief/<id>/page`: the static render of the finished run, the bytes whose sha256
  `run_finished` carries, for the page's own check and for download.

and HB-131R's three:

- `GET /brief/<id>/record/<sha256>`: a record of the brief's record set as JSON, with
  the fields the evidence log prints (`record_json`); 404 for any other hash.
- `GET /brief/<id>/report`: the commander's report of the finished run, the ICS 201
  and its evidence appendix (`render.report_html`); the page's print view prints it
  and nothing else (`static/live.css`).
- `POST /brief/<id>/ask`: the question route (`model_author.ModelAuthor.ask`), read-only
  over the finished brief: an answer whose every sentence carries a record of the
  brief, or "not in this brief", or a structured error. Since HB-141 (HBD-271) the page
  has no question box and calls it never; it stays a server-side capability.

and HB-141's four (DN-019 ADDENDUM-02; HBD-217 to HBD-219, HBD-224):

- `POST /brief/<id>/check` and `/uncheck` with `{"item": <stream id>}`: the operator
  checklist's tick, appended to the stream as a `check` or `uncheck` event with the
  server's time, written first to the serve's checks file (`--checks`; `checklist.
  ChecksLog`), which a replay puts back at the same places. The only POSTs the page
  makes.
- `GET /brief/<id>/panels`: the guide panels (ERG guide, protective clothing, fire
  response, public safety), each the static page's slice of the guidance section.
- `GET /brief/<id>/recorded`: on a served replay, the dates its records were made, for
  the replay banner above the map; a live serve prints no banner.

and HB-154's two (DN-019 ADDENDUM-03), each read from the blackboard as it stands:

- `GET /brief/<id>/head`: the header line's facts (`render.head_facts`).
- `GET /brief/<id>/sources`: the Data sources view's table (`data_sources`), one row per
  channel with one of four outcomes; no call.

The layout (HB-154, `shell_html`): a fixed shell that never scrolls. The header (the
EXERCISE banner, one line, the replay banner on a replay); then the layers column, the
centre (the map, its view and overlay switches, the tabbed panel under it) and the
checklist column. The tabs hold the sections, the guide panels, the evidence log, the
Data sources view, the map section's side panel and the commander's report.

and HB-132R's entry form (DN-022 section 7), served when the server starts with no
scenario (`hazbrief brief --serve --entry`):

- `GET /` before a build: the form. A point clicked on the map or a typed location
  (an address, cross-streets, a milepost or a grade crossing), the situation line, and
  the weather source as a fourth field (HB-132R ADDENDUM-02 section 1).
- `POST /entry/locate`: a typed location resolved by DN-013's rules
  (`location.locate`), with its derivation, accuracy and label.
- `POST /entry/parse`: the situation line's three fields with their spans and route
  (`entry.Parser`), shown back as editable fields.
- `POST /entry/build`: the form's values, checked (the weather by HB-139's schema: a
  refused selection is a 422 naming the field or the acquisition), written as a
  fixture file (`entry.write_fixture`) before the build starts; the build then streams
  as HB-130R built it. A second build on the same server is a 409.

One server serves one brief, assembled once, on the first request that needs it. A
reload streams the same run again from its first event. A request whose Host is not
this server's, or whose Origin is present and foreign, is refused with 403 (DNS
rebinding; HB-89's rule, as `serve_review.py` applies it).

A run that raises sends `run_failed` with the error and ends the stream; `/page` then
answers 500 with the same error, and the traceback goes to stderr. Nothing is retried.

The application's code, not the server's: `.dockerignore` keeps `src/hazbrief/brief/`
(this module and `static/` with it) out of the container image.
"""

from __future__ import annotations

import asyncio
import html
import json
import socket
import sys
import traceback
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable
from urllib.parse import urlsplit

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    Response,
    StreamingResponse,
)
from starlette.routing import Route

from hazbrief.brief import (
    checklist,
    data_sources,
    entry,
    location,
    model_author,
    render,
    start,
    tevv,
    threat,
    weather_source,
)
from hazbrief.brief.author import NarrativeAuthor, NoAuthor
from hazbrief.brief.orchestrator import (
    RENDER_ORDER,
    Alert,
    AlertWithdrawn,
    AreaRadiusSet,
    Brief,
    BriefEvent,
    Check,
    SiteMoved,
    Uncheck,
)
from hazbrief.evidence import labels as L

STATIC = Path(__file__).with_name("static")
#: the hosts the route may bind (HB-89: loopback only)
LOOPBACK = ("127.0.0.1", "::1", "localhost")


class RunFailed(RuntimeError):
    """The brief's assembly raised; the message names the error."""


#: `start(on_event, on_brief)`: the assembly, `orchestrator.assemble` with the brief's
#: scenario and settings and these two hooks
Start = Callable[
    [Callable[[BriefEvent], None], Callable[[Brief], None]], Awaitable[Brief]
]


class NotRecorded(LookupError):
    """An Area radius step past the data in hand on a replay: its answer is not
    recorded, and a replay makes no call (HB-155 ADDENDUM-02 item 5)."""


class BriefRun:
    """One brief's assembly and the events it has sent so far. `start` is the assembly,
    started once, on the first request that needs it. `live` is its blackboard from
    before the first channel is called (`assemble`'s `on_brief`), which the record
    route reads as records land."""

    def __init__(
        self,
        brief_id: str,
        start: Start,
        checks: checklist.ChecksLog | None = None,
        clock: Callable[[], str] | None = None,
    ):
        self.brief_id = brief_id
        self._start = start
        self.events: list[BriefEvent] = []
        self.brief: Brief | None = None
        self.live: Brief | None = None
        self.error: str | None = None
        self.done = False
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()
        #: the weather fields the page's query gave before the run started (HB-139),
        #: passed to `start` as `weather_fields`; None: the run's own (the CLI's)
        self.weather_fields: dict | None = None
        #: where the operator's checks are written, and the recorded ones a replay
        #: puts back at their places in the stream (HB-141 item 2)
        self.checks = checks
        self._recorded = list(checks.recorded) if checks is not None else []
        self._clock = clock or (
            lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
        )
        #: HB-155: each moved point's standing Warning (its alert's stream id), and
        #: whether the review item has been raised
        self._site_warn: dict[str, int] = {}
        self._reviewed = False
        self._config: dict | None = None

    def _cfg(self) -> dict:
        if self._config is None:
            from hazbrief.brief.orchestrator import load_config

            self._config = load_config()
        return self._config

    @staticmethod
    def _wind_name(brief) -> str | None:
        """The brief's one wind record as a moved point names it (its source line)."""
        return ((getattr(brief, "wind_record", None) or {}) or {}).get("source")

    def _site_follow(self, ev: SiteMoved) -> None:
        """The checklist items a moved point raises (HB-155 item 8; ADDENDUM-04 items 1
        and 2): its Warning, naming the drawn layer it lies in and the modelled arrival
        there, the point's earlier Warning withdrawn; and the Verify item "review" when
        it was moved under another wind record than the brief's (ADDENDUM-04 item 3: a
        step of the time control is never one). Appended after the event, so a replay of
        the event regenerates them at the same places."""
        cfg = self._cfg()
        words = cfg["derive"]["siting"]["words"]
        title = cfg["derive"]["siting"]["points"][ev.point]["title"]
        receipt = words["moved_receipt"].format(time=ev.time)
        last = self._site_warn.pop(ev.point, None)
        if last is not None:
            self.events.append(
                AlertWithdrawn(
                    alert=last, kind="siting", receipt=receipt, section="map"
                )
            )
        parts = []
        if ev.inside:
            parts.append(
                words["moved_inside"].format(point=title, layer="; ".join(ev.inside))
            )
        if ev.arrival:
            parts.append(
                words["arrival_reached"].format(
                    point=title,
                    hplus=ev.arrival.get("hplus"),
                    clock=ev.arrival.get("clock"),
                )
            )
        if parts:
            self.events.append(Alert("siting", "; ".join(parts), receipt, "map"))
            self._site_warn[ev.point] = len(self.events) - 1
        brief = self.brief or self.live
        if (
            not self._reviewed
            and brief is not None
            and ev.wind != self._wind_name(brief)
        ):
            self._reviewed = True
            self.events.append(Alert("siting_review", words["review"], receipt, "map"))

    def site(self, point: Any, coordinates: Any) -> tuple[int, BriefEvent]:
        """HB-155 item 8: a suggested point moved to `coordinates` ([longitude,
        latitude]), or put back on its suggestion (`coordinates` None): the routes and
        the Warning recomputed by `siting.move`, the event written to the checks log at
        its place, then appended with the server's time. Raises ValueError for a point
        that is not one of the three, coordinates that are not a point, or a brief that
        suggested none."""
        from hazbrief.brief import siting

        brief = self.brief
        if brief is None:
            raise ValueError("a point is moved once the brief is presented")
        if point not in siting.POINTS:
            raise ValueError(f"{point!r} is not one of {', '.join(siting.POINTS)}")
        held = ((brief.derived or {}).get("siting") or {}).get("points") or {}
        if coordinates is None:
            if not held.get(point):
                raise ValueError(f"no {point} was suggested to go back to")
            coordinates = held[point]["suggested"]
        got = siting.move(brief.derived, point, coordinates, self._cfg())
        ev = SiteMoved(
            point=point,
            coordinates=got["coordinates"],
            time=self._clock(),
            suggestion=coordinates == (held.get(point) or {}).get("suggested"),
            where=got["where"],
            inside=got["inside"],
            arrival=got["arrival"],
            routes=got["routes"],
            wind=self._wind_name(brief),
        )
        at = len(self.events)
        if self.checks is not None:
            self.checks.append(at, ev)
        self.events.append(ev)
        self._site_follow(ev)
        self._notify()
        return at, ev

    async def area(self, radius_m: Any, *, live: bool) -> tuple[int, BriefEvent]:
        """HB-155 ADDENDUM-02 item 5: an Area radius step. A step whose data is in hand
        (at or inside the largest box read) is an event and nothing else; on a live
        serve a step past it reads that box (the stations and the travel roads) and
        sends the new facilities; on a replay it raises `NotRecorded`. A view filter:
        no record changes (HBD-371)."""
        from hazbrief.brief import derive, layers

        brief = self.brief
        if brief is None:
            raise ValueError("the area radius is set once the brief is presented")
        cfg = self._cfg()
        c = layers._Ctx(brief, cfg)
        area = layers.area_config(c)
        if area is None:
            raise ValueError("this brief has no services in the area to filter")
        steps = {float(x["m"]) for x in area["steps"]} | {0.0}
        if not isinstance(radius_m, (int, float)) or float(radius_m) not in steps:
            raise ValueError(
                f"the radius is one of the steps in metres: {sorted(steps)}"
            )
        r = float(radius_m)
        feats: list = []
        if r > area["held_m"] + 1:
            if not live:
                raise NotRecorded(cfg["web"]["shell"]["area_not_recorded"])
            fp = c.payload("protective_action_footprint")
            await derive.widen_area(c, brief, fp, brief.derived, cfg, r)
            feats = layers._nearby_layer(layers._Ctx(brief, cfg))["features"]
        ev = AreaRadiusSet(
            radius_m=r, time=self._clock(), held=not feats, features=feats
        )
        at = len(self.events)
        if self.checks is not None:
            self.checks.append(at, ev)
        self.events.append(ev)
        self._notify()
        return at, ev

    @property
    def started(self) -> bool:
        return self._task is not None

    def _put_back(self, upto: int | None) -> None:
        """Each recorded check whose place is at or before `upto` (None: all that
        remain), appended as it was: a replay's stream holds the checks where the
        recording held them, so a check names the same item id. A recorded check that
        names no checklist item sent before it fails the run (the file is not this
        brief's recording)."""
        while self._recorded and (upto is None or self._recorded[0]["at"] <= upto):
            row = self._recorded.pop(0)
            if row["type"] in checklist.RECORDED:
                self._put_back_other(row)
                continue
            if row["item"] not in checklist.item_ids(self.events):
                raise ValueError(
                    f"{self.checks.path}: the recorded {row['type']} at {row['at']} "
                    f"names item {row['item']}, which this run has not sent; the "
                    "file is not this brief's recording"
                )
            cls = Check if row["type"] == "check" else Uncheck
            self.events.append(cls(item=row["item"], time=row["time"]))

    def _put_back_other(self, row: dict) -> None:
        """A recorded moved point (with the items it raised, regenerated) or area
        radius step, appended as it was (HB-155)."""
        fields = {k: v for k, v in row.items() if k not in ("brief_id", "at", "type")}
        if row["type"] == "site_moved":
            ev = SiteMoved(**fields)
            self.events.append(ev)
            self._site_follow(ev)
        else:
            self.events.append(AreaRadiusSet(**fields))

    def _on_event(self, ev: BriefEvent) -> int:
        """Append the orchestrator's event after any recorded check due before it, and
        return its place in the stream, which is its id (`orchestrator.assemble`'s
        `emit`)."""
        self._put_back(len(self.events))
        self.events.append(ev)
        self._notify()
        return len(self.events) - 1

    def operator(self, action: str, item: Any) -> tuple[int, BriefEvent]:
        """A tick (`check`) or untick (`uncheck`) on checklist item `item` (a stream
        id): written to the checks log at its place, then appended to the stream with
        the server's time. Raises ValueError for anything that is not an item sent so
        far. Nothing else changes: the build, the report and the export run whether or
        not boxes are ticked (section 3 item 5)."""
        if action not in checklist.ACTIONS:
            raise ValueError(f"{action!r} is not check or uncheck")
        if not isinstance(item, int) or isinstance(item, bool):
            raise ValueError("item is a stream id, an integer")
        if item not in checklist.item_ids(self.events):
            raise ValueError(f"{item} is not a checklist item of this brief's stream")
        cls = Check if action == "check" else Uncheck
        ev = cls(item=item, time=self._clock())
        at = len(self.events)
        if self.checks is not None:
            self.checks.append(at, ev)
        self.events.append(ev)
        self._notify()
        return at, ev

    def _on_brief(self, brief: Brief) -> None:
        self.live = brief

    def _notify(self) -> None:
        wake, self._wake = self._wake, asyncio.Event()
        wake.set()

    def ensure_started(self) -> None:
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(self._run())

    async def _run(self) -> None:
        try:
            extra = (
                {}
                if self.weather_fields is None
                else {"weather_fields": self.weather_fields}
            )
            self.brief = await self._start(self._on_event, self._on_brief, **extra)
            # the recorded checks made after the run's last event
            self._put_back(None)
        except Exception as exc:  # surfaced on the stream, at /page and on stderr
            self.error = f"{type(exc).__name__}: {exc}"
            traceback.print_exc(file=sys.stderr)
        finally:
            self.done = True
            self._notify()

    async def follow(
        self, after: int = -1, keepalive_s: float | None = None
    ) -> AsyncIterator[tuple[int, BriefEvent] | None]:
        """Each event after index `after`, as `(index, event)`, as it arrives, until the
        run is done; None when `keepalive_s` passes with nothing new."""
        self.ensure_started()
        i = after + 1
        while True:
            while i < len(self.events):
                yield i, self.events[i]
                i += 1
            if self.done:
                return
            wake = self._wake
            try:
                await asyncio.wait_for(wake.wait(), keepalive_s)
            except TimeoutError:
                yield None

    async def finished(self) -> Brief:
        """The finished run's blackboard; raises `RunFailed` when the run raised."""
        self.ensure_started()
        await asyncio.shield(self._task)
        if self.error is not None:
            raise RunFailed(self.error)
        return self.brief

    async def page(self) -> str:
        """The finished run's static render; raises `RunFailed` when the run raised."""
        return (await self.finished()).html


def sse(index: int, ev: BriefEvent) -> str:
    """One event as SSE (WHATWG HTML section 9.2): JSON never holds a raw newline, so
    the data is one line."""
    data = json.dumps(ev.to_json(), sort_keys=True, ensure_ascii=False)
    return f"event: {ev.type}\nid: {index}\ndata: {data}\n\n"


def host_port(host: str, port: int) -> str:
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


def allowed_hosts(host: str, port: int) -> set[str]:
    """The Host values this server answers: its own address, and `localhost` with its
    port (HB-89; `serve_review.py`)."""
    return {host_port(host, port), f"localhost:{port}"}


class LoopbackOnly:
    """Refuses, with 403, a request whose Host is not one of `allowed`, or whose Origin
    is present and not one of them (DNS rebinding; HB-89). Starlette's
    `TrustedHostMiddleware` checks the Host without its port and no Origin, so the check
    is its own here, as the review page's is."""

    def __init__(self, app, allowed: set[str]):
        self.app = app
        self.allowed = allowed

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = {
                k.decode("latin-1"): v.decode("latin-1") for k, v in scope["headers"]
            }
            why = None
            if headers.get("host") not in self.allowed:
                why = "Host not allowed"
            else:
                origin = headers.get("origin")
                if origin is not None and (
                    urlsplit(origin).scheme != "http"
                    or urlsplit(origin).netloc not in self.allowed
                ):
                    why = "Origin not allowed"
            if why:
                await PlainTextResponse(why, status_code=403)(scope, receive, send)
                return
        await self.app(scope, receive, send)


def checklist_html(cfg: dict) -> str:
    """The operator checklist (DN-019 ADDENDUM-02 section 3; HB-141; HBD-217, HBD-218 as
    amended by HB-154), the right column's panel, empty until the stream fills it: the
    purpose sentence at its head (Issue 97736b94 item 3), then one collapsible group per
    `checklist.groups` entry, open, holding one list per kind in the group's order (the
    Verify group's first list is the reserved `wind` slot, HB-154 ADDENDUM-01 section
    2). No question box: questions are answered in the session that generated the
    brief (HBD-271)."""
    groups = "".join(
        f'<details class="group" id="group-{html.escape(g["id"])}"'
        f"{'' if g.get('open') is False else ' open'}>"
        f'<summary>{html.escape(g["title"])} <span class="n" '
        f'id="count-{html.escape(g["id"])}">0</span></summary>'
        + "".join(
            f'<ol class="items" id="items-{html.escape(k)}" '
            f'data-kind="{html.escape(k)}"></ol>'
            for k in g["kinds"]
        )
        + "</details>"
        for g in cfg["checklist"]["groups"]
    )
    sh = cfg["web"]["shell"]
    # HB-158 item 5: no Sited points block until the siting layer exists (G5); the
    # note on ticks opens under its own line (item 3)
    return (
        '<section class="panel" id="checklist" aria-live="polite">'
        "<h2>Operator checklist</h2>"
        f'<p class="purpose">{html.escape(sh["purpose"])}</p>'
        f'<details class="about"><summary>{html.escape(sh["ticks_about"])}</summary>'
        '<p class="panel-note">Tick an item once you have checked it. Each tick is '
        "recorded with the server's time and listed in the ICS 201's Operator checks "
        "annex; nothing waits on a tick. A line a later settle makes false is struck "
        "through, not removed.</p></details>"
        f'{groups}<p class="pending" id="checklist-empty">No item yet.</p>'
        "</section>"
    )


def guide_html(cfg: dict) -> str:
    """The ERG guide tab's own part (item 7; HB-141 item 6; HBD-224): a chip per guide
    panel, each hidden until the brief's guidance section holds its heading, and the one
    view they open, closable. The guidance section itself follows it in the tab."""
    chips = "".join(
        f'<button type="button" class="guide-chip" data-panel="{html.escape(p["id"])}"'
        f" hidden>{html.escape(p['title'])}</button>"
        for p in cfg["web"]["panels"]
    )
    return (
        f'<nav id="guide-chips" aria-label="Guide panels">{chips}</nav>'
        '<div id="panel-view" role="region" aria-labelledby="panel-title" hidden>'
        '<button type="button" id="panel-close" aria-label="Close">Close</button>'
        '<h2 id="panel-title"></h2><div id="panel-body"></div></div>'
    )


def replay_banner_html(cfg: dict) -> str:
    """The one banner a served replay prints, in the header under its line (F4;
    HBD-219; HB-154 item 4); its date is filled from the recorded route when the run
    finishes."""
    w = cfg["web"]
    pending = html.escape(w["replay_recorded_pending"])
    text = html.escape(w["replay_banner"]).replace(
        "{recorded}", f'<span id="replay-recorded">{pending}</span>'
    )
    return f'<div id="replay-banner" role="note">{text}</div>'


def evidence_html() -> str:
    """The evidence log (HB-131R item 2), the fourth tab's body."""
    return (
        '<section class="panel" id="evidence">'
        '<p class="panel-note">One row per call, in arrival order: what was asked of '
        "which source, what came back, and what the record says. A record opens as its "
        "stored JSON.</p>"
        '<label for="log-filter">Source</label> <select id="log-filter">'
        '<option value="">every source</option></select>'
        '<table id="log"><thead><tr><th>Source</th><th>Asked</th><th>State</th>'
        "<th>Record</th><th>As of</th><th>Validation</th></tr></thead>"
        "<tbody></tbody></table></section>"
    )


def report_html_slot() -> str:
    """The commander's report's place in the ICS 201 tab (HB-131R item 3), filled from
    the report route when the run finishes; the print view prints it alone."""
    return (
        '<section class="panel" id="report"><h2 class="report-wait">Commander\'s '
        'report</h2><p class="pending" id="report-wait">The ICS 201 and its appendix '
        "appear here when the run finishes.</p></section>"
    )


def tab_body_html(tab: dict, cfg: dict) -> str:
    """One tab's panel: its own body (`body`), then its sections, each pending until the
    stream swaps it in (`render.pending_section_html`)."""
    log_title = html.escape(cfg["data_sources"]["log_title"])
    bodies = {
        "guide": lambda: guide_html(cfg),
        # HB-158 item 8: the evidence log is the calls behind the sources table, so
        # it sits under the table in the one tab, behind its own line
        "sources": lambda: (
            '<div id="sources-table"><p class="pending">The sources appear as each '
            "channel settles.</p></div>"
            f'<details class="log-wrap" id="log-wrap"><summary>{log_title}</summary>'
            f"{evidence_html()}</details>"
        ),
        # HB-158 (ADDENDUM-01 item 6): the map's side panel opens under its own line,
        # so the Zones and models tab opens on its summary, not a wall of text
        "detail": lambda: (
            '<details class="tdetail" id="detail-wrap"><summary><h2>'
            f"{html.escape(cfg['web']['shell']['detail_title'])}</h2></summary>"
            '<div id="detail-slot"><p class="pending">The first actions, the weather '
            "and the modelled layers' notes appear when the footprint settles.</p>"
            "</div></details>"
        ),
        "report": report_html_slot,
    }
    sections = "".join(
        render.pending_section_html(cfg, n) for n in tab.get("sections", [])
    )
    own = bodies[tab["body"]]() if tab.get("body") else ""
    # the report follows the ICS 201 section; every other body leads its tab
    inner = sections + own if tab.get("body") == "report" else own + sections
    tid = html.escape(tab["id"])
    # ADDENDUM-01 item 6: the tab's first line is a summary read at a glance (its
    # figures, from the head route's `tabs`), the prose and tables under it
    return (
        f'<section class="tab-panel" id="tab-{tid}" role="tabpanel" '
        f'aria-labelledby="tab-btn-{tid}" hidden>'
        f'<p class="tab-sum" id="sum-{tid}"></p>{inner}</section>'
    )


def tabs_html(cfg: dict) -> str:
    """The under-map panel (item 7): the tab bar, always visible, each tab carrying its
    sections' state mark, then the progress count (HB-130R's strip, now the bar's
    tail); and the body, closed on first paint, opened to a fixed share of the window
    by a tab and closed by Hide."""
    tabs = cfg["web"]["shell"]["tabs"]
    placed = [n for t in tabs for n in t.get("sections", [])]
    want = list(RENDER_ORDER[1:])
    if sorted(placed) != sorted(want) or len(placed) != len(set(placed)):
        raise RuntimeError(
            "web.shell.tabs must place every section but the map in exactly one tab: "
            f"placed {placed}, sections {want}"
        )
    buttons = "".join(
        f'<button type="button" role="tab" class="tab" id="tab-btn-'
        f'{html.escape(t["id"])}" data-tab="{html.escape(t["id"])}" '
        f'aria-controls="tab-{html.escape(t["id"])}" aria-selected="false" '
        f'data-sections="{html.escape(" ".join(t.get("sections", [])))}">'
        f"{html.escape(t['title'])}"
        # HB-158 ADDENDUM-01 item 2: the tab's sections' state, its shape on the bar
        # and its words for a screen reader and the tooltip (live.js redraws it)
        + (
            render.state_mark(cfg, "retrieving", glyph_only=True)
            if t.get("sections")
            else ""
        )
        + "</button>"
        for t in tabs
    )
    return (
        '<div id="under"><div id="tabs" role="tablist" aria-label="Brief panels">'
        f"{buttons}"
        '<button type="button" id="tab-hide" aria-label="Hide the panel" hidden>'
        "Hide</button></div>"
        f'<div id="tab-body" hidden>{"".join(tab_body_html(t, cfg) for t in tabs)}'
        "</div></div>"
    )


def shell_css(cfg: dict) -> str:
    """The shell's sizes and its two breakpoints from `web.shell` (a media query
    cannot read a CSS variable, so these are written here, not in live.css)."""
    sh = cfg["web"]["shell"]
    stack = int(sh["stack_below_px"])
    return (
        f":root {{ --left: {int(sh['left_px'])}px; --right: {int(sh['right_px'])}px; "
        f"--strip: {int(sh['strip_px'])}px; "
        f"--panel: {float(sh['panel_share']) * 100:.0f}vh; "
        f"--stacked-map: {int(sh['stacked_map_px'])}px; }}\n"
        f"@media (max-width: {stack - 1}px) {{\n"
        "  body.shell { display: block; height: auto; overflow: visible; }\n"
        "  #shell { display: flex; flex-direction: column; }\n"
        "  #centre { display: contents; }\n"
        "  #map-region { order: 1; height: var(--stacked-map); flex: none; }\n"
        "  #col-checklist { order: 2; }\n"
        "  #col-layers { order: 3; }\n"
        "  #under { order: 4; }\n"
        "  #col-layers, #col-checklist, #col-layers[data-open='0'],\n"
        "  #col-checklist[data-open='0'] { width: auto; border: none;\n"
        "    border-top: 1px solid #cccccc; overflow: visible; }\n"
        "  #tab-body { height: auto; max-height: none; }\n"
        "  #top .bar { flex-wrap: wrap; }\n"
        "  #head-facts, .chip { white-space: normal; max-width: none; }\n"
        "  .col[data-open='0'] .col-toggle, .col[data-open='0'] .strip-count {\n"
        "    writing-mode: horizontal-tb; display: inline-block; margin: 6px 12px; }\n"
        "}\n"
    )


def shell_html(
    brief_id: str,
    cfg: dict,
    *,
    replay: bool = False,
    exercise: bool = True,
    notes: dict | None = None,
) -> str:
    """The live page before any event (HB-154; DN-019 ADDENDUM-03): a fixed shell that
    fills the window and never scrolls (below `web.shell.stack_below_px` it stacks and
    the document scrolls). The header: the EXERCISE banner (unless `exercise` is False,
    which only a form-built brief can ask for, HB-154 ADDENDUM-01), then one line (the
    material, the container, the place, the as-given time, the wind chip and Print the
    ICS 201), then the replay banner on a replay. Then one row: the layers and legend
    on the left, collapsible; the map in the centre with the view and overlay switches
    at its top right and the tabbed panel under it; the operator checklist on the
    right, collapsible. Then the footer banner and the scripts (Leaflet, the static
    page's map script as `window.hbMap`, and `static/live.js`)."""
    page = cfg["page"]
    sh = cfg["web"]["shell"]
    title = f"Live brief: {brief_id}"
    live_css = (STATIC / "live.css").read_text(encoding="utf-8")
    live_js = (STATIC / "live.js").read_text(encoding="utf-8")
    # HB-158 ADDENDUM-02 item 5: the status strip, the assembling view, the wind
    # chip's hour, the tab summaries and the rows' one-open rule, a script of its own
    shell_js = (STATIC / "shell.js").read_text(encoding="utf-8")
    # HB-155: the siting block and the Area radius steps, a sixth script of its own
    # (ADDENDUM-05 item 8: live.js has no room)
    siting_js = (STATIC / "siting.js").read_text(encoding="utf-8")
    banner = replay_banner_html(cfg) if replay else ""
    exercise_line = (
        f'<div class="banner">{html.escape(page["banner"])}</div>' if exercise else ""
    )
    footer = (
        f'<footer id="bottom" class="banner">{html.escape(page["banner"])}</footer>'
        if exercise
        else ""
    )
    data = html.escape(
        json.dumps(
            {
                # HB-207 item 13 and ADDENDUM-03 item 1: the words the page says while
                # it works and when no cloud is drawn, and a form-built brief's notes
                # (its start time, the levels line); `static/shell.js` prints them
                "working": cfg["entry"]["page"],
                "form_notes": notes or {},
                "collapse_left_below_px": int(sh["collapse_left_below_px"]),
                "stack_below_px": int(sh["stack_below_px"]),
                "overlays": sh["overlays"],
                "collapsed_count": sh["collapsed_count"],
                # HB-158: the words and shapes the page's scripts print
                "collapsed_updated": sh["collapsed_updated"],
                "updated": sh["updated"],
                "states": page["states"],
                "section_states": page["section_states"],
                "outcome_states": cfg["data_sources"]["outcome_states"],
                # HB-215: the Sources view's board words, for a replay's relabel
                "board_statuses": cfg["data_sources"]["board"]["statuses"],
                "strip_counts": sh["strip_counts"],
                "strip_title": sh["strip_title"],
                "progress": sh["progress"],
                "assembling_count": sh["assembling_count"],
                "cloud_hour": sh["cloud_hour"],
                # HB-192: the status line's words and each level's colour for the
                # frames a live page draws as they land (`static/shell.js`)
                "frames": {
                    **{
                        k: cfg["web"]["time_control"]["frames"][k]
                        for k in ("setting", "no_setting", "live")
                    },
                    "colors": {
                        name: lv["color"]
                        for name, lv in cfg["map"]["cloud"]["levels"].items()
                    },
                },
                "critical_stage": sh["critical_stage"],
                "wind_chip": sh["wind_chip"],
                "wind_hour": sh["wind_hour"],
                "pin": sh["pin"],
                "pinned": sh["pinned"],
                "channels": list(cfg["channels"]),
                "server": cfg["data_sources"]["server"],
                "tab_rows": sh["tab_rows"],
                # HB-171 item 11: the checklist item every timeline row's times rest
                # on points back to the Timeline page, where the brief draws one
                "timeline": {
                    "item": threat.config()["checklist_item"],
                    "href": threat.config()["file"],
                    "text": threat.config()["checklist_back"],
                },
                # HB-173: the two engines' item opens the measure's TEVV section;
                # DN-028 ADDENDUM-10: the stable-class line opens SCICHEM's
                # Conditions of use
                "engines": {
                    "links": {
                        k: {
                            "href": tevv.href(cfg, "agreement"),
                            "text": sh["engines_link"],
                        }
                        for k in ("engines", "engines_agree")
                    }
                    | {
                        "engines_stable": {
                            "href": tevv.href(cfg, "conditions_scichem"),
                            "text": sh["conditions_link"],
                        }
                    },
                },
            },
            sort_keys=True,
        )
    )
    left = (
        '<aside id="col-layers" class="col" data-open="1" aria-label="Layers and '
        'legend"><button type="button" class="col-toggle" id="toggle-layers" '
        'aria-expanded="true" aria-controls="layers-body" data-show="Layers" '
        'data-hide="Hide layers">Hide layers</button>'
        '<div class="col-body" id="layers-body"><div id="layers-slot">'
        '<p class="pending">The layers and their legend appear when the footprint '
        "settles.</p></div></div></aside>"
    )
    right = (
        '<aside id="col-checklist" class="col" data-open="1" aria-label="Operator '
        'checklist"><button type="button" class="col-toggle" id="toggle-checklist" '
        'aria-expanded="true" aria-controls="checklist-body" data-show="Checklist" '
        'data-hide="Hide checklist">Hide checklist</button>'
        '<span class="strip-count" id="checklist-count"></span>'
        f'<div class="col-body" id="checklist-body">{checklist_html(cfg)}</div></aside>'
    )
    # ADDENDUM-01 item 4: until the critical set is in, the map carries one assembling
    # view (the sources, each with its state, and a count) and the columns and tabs
    # wait; `static/shell.js` fills it and lifts it on `stage_reached`
    assembling = (
        '<div id="assembling" role="status" aria-live="polite">'
        f"<h2>{html.escape(sh['assembling_title'])}</h2>"
        '<p id="assembling-count"></p><ul id="assembling-list"></ul>'
        '<p id="assembling-cloud"></p>'
        f'<p class="pl">{html.escape(sh["assembling_note"])}</p></div>'
    )
    centre = (
        '<div id="centre"><div id="map-region">'
        '<section class="pending" id="section-map"><p class="pending" id="map-wait">'
        f"Waiting for the protective action footprint.</p></section>{assembling}"
        '<div id="map-switches"><div class="switch-group" id="view-switch" '
        'role="group" aria-label="Map view"></div><div class="switch-group" '
        'id="overlay-switch" role="group" aria-label="Live overlays"></div></div>'
        f"</div>{tabs_html(cfg)}</div>"
    )
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{html.escape(title)}</title>"
        f"<style>{render.vendored(cfg, 'css')}</style>"
        f"<style>{render.page_css(cfg)}</style><style>{live_css}</style>"
        f"<style>{shell_css(cfg)}</style></head>"
        f'<body class="shell" data-brief="{html.escape(brief_id)}" data-shell="{data}"'
        f"{' data-replay=' + chr(34) + '1' + chr(34) if replay else ''}>"
        f'<header id="top">{exercise_line}'
        f'<div class="bar"><h1 id="head-title">{html.escape(title)}</h1>'
        '<span class="meta" id="head-facts"><code>'
        f"{html.escape(brief_id)}</code></span>"
        # HB-158 item 6 (G2): the wind chip carries the record and the hour the one
        # clock is on, with the previous and next hour beside it (HBD-340)
        '<span class="chip" id="wind-chip" hidden><span id="wind-chip-text"></span>'
        '<button type="button" id="wind-prev" '
        f'aria-label="{html.escape(sh["wind_prev"])}"'
        ' hidden>&#9664;</button><span id="wind-chip-hour"></span>'
        '<button type="button" id="wind-next" '
        f'aria-label="{html.escape(sh["wind_next"])}"'
        " hidden>&#9654;</button></span>"
        # ADDENDUM-01 item 5: the status strip, always visible; a click opens the
        # Sources and MCP servers tab
        '<button type="button" id="status-strip" aria-controls="tab-sources">'
        '<span id="strip-marks"></span> <span id="strip-count"></span></button>'
        '<span class="status" id="progress" aria-live="polite"></span>'
        # HB-161 ADDENDUM-01 item 4: one link to the TEVV page, at its top
        f'<a id="tevv-link" href="{html.escape(cfg["tevv"]["file"])}" '
        'target="_blank" rel="noopener">'
        f"{html.escape(cfg['tevv']['link_text'])}</a>"
        # HB-171 item 9: the Timeline page's link, beside TEVV's
        f"{threat.link_html(cfg)}"
        '<button type="button" id="print-ics">Print the ICS 201</button></div>'
        f"{banner}</header>\n"
        f'<div id="shell">{left}{centre}{right}</div>\n'
        f"{footer}"
        f"<script>{render.vendored(cfg, 'js')}</script>"
        f"<script>{render.TIME_JS}</script>"
        # HB-210: the live shell always carries the Google branch's own script (one
        # load of Google's per page, however often the map section is swapped, and the
        # traffic switch); the map script reads the brief's key at run time and draws
        # Leaflet with no key
        f"<script>{render.GOOGLE_JS}</script>"
        f"<script>window.hbMap = function () {{{render.MAP_JS}}};</script>"
        f"<script>{shell_js}</script>"
        f"<script>{siting_js}</script>"
        f"<script>{live_js}</script></body></html>\n"
    )


def record_json(brief: Brief, sha: str, cfg: dict) -> dict | None:
    """The record route's body (HB-131R item 2): the stored record of entity `sha` this
    brief read, with the fields the evidence log prints, each read from the record or
    its DN-010 D4 label: its source, what it asked (`labels.asked`), its as-of, its
    validation (`web.log_validation`), and its hash. None when `sha` is not in the
    brief's record set."""
    got = model_author.record_view(brief, sha)
    if got is None:
        return None
    rec, body, lab = got
    w = cfg["web"]
    # an MCP error, or a structured error payload (DN-003's no-key Census case), is an
    # error, as the orchestrator reads it (`orchestrator._failed`)
    failed = rec["activity"].get("is_error") or (
        isinstance(body, dict) and bool(body.get("error"))
    )
    answered = w["log_errored"] if failed else w["log_answered"]
    return {
        "sha256": sha,
        "hash_prefix": sha[: L.config()["hash_prefix_chars"]],
        "tool": rec["activity"]["name"],
        "source": "; ".join(s["name"] for s in lab["sources"]),
        "asked": L.asked(rec),
        "as_of": L.when(lab["as_of"], brief.time_zone, lab["as_of_precision"]),
        "validation": w["log_validation"].format(
            answered=answered, state=L.state_cell(lab)
        ),
        "record": rec,
    }


def refusal_html(brief_id: str, reason: str, cfg: dict) -> str:
    """The page a refused weather selection answers with (HB-139; DN-011 D2: a section
    that cannot be true is not drawn, and the reason is on its face), under the
    exercise banner like every screen (DN-012 section 7)."""
    banner = html.escape(cfg["page"]["banner"])
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        f"<title>{html.escape(brief_id)}: weather refused</title><style>body "
        f"{{ font-family: {cfg['page']['font_stack']}; margin: 24px 32px; }} "
        ".banner { font-weight: bold; } .degraded { color: #a00000; }</style></head>"
        f'<body><p class="banner">{banner}</p>'
        f"<h1>{html.escape(brief_id)}: no brief drawn</h1>"
        f'<p class="degraded">Weather refused: {html.escape(reason)}</p>'
        f'<p class="banner">{banner}</p></body></html>\n'
    )


def _error(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "detail": detail}}, status_code=status)


@dataclass
class EntryForm:
    """What the entry form's routes call (HB-132R Part B): the situation line's parser,
    the typed location's resolver (DN-013's `location.locate`), and `make_start`, which
    takes the scenario the build route wrote and returns the run's `Start`. Fixtures are
    written into `fixtures_root` (default `orchestrator.yaml` `entry.fixtures_dir`);
    `incident_time` is the time the form's incident is stated at (the run's `now`)."""

    parser: entry.Parser
    locate: Callable[[dict], Awaitable[dict]]
    make_start: Callable[[dict], Start]
    incident_time: str
    fixtures_root: Path | None = None
    #: the fixtures this server wrote, in order (one: one server, one brief)
    written: list[Path] = field(default_factory=list)
    #: HB-207 ADDENDUM-03 item 1: the start time the form proposes ("now" when the
    #: reader reads the line); None proposes `incident_time` (a replay's fixed now)
    clock: Callable[[], str] | None = None
    #: HB-207 item 11: whether today's forecast holds the start time, asked of NWS
    #: before a forecast build (a live server only; None skips the check)
    forecast_holds: Callable[[dict, str], Awaitable[bool | None]] | None = None


@dataclass
class StartMenu:
    """What the start page's routes call (HB-208): `make_recorded(id)` returns the
    `Start` of a prepared scenario's served replay, as `hazbrief brief
    docs/briefs/<id>/scenario.json --serve --replay --now <fixture_now> --no-google`
    makes it; `author` and `asker` are that replay's (a replay reads only recorded
    transcripts)."""

    make_recorded: Callable[[str], Start]
    author: NarrativeAuthor | None = None
    asker: model_author.ModelAuthor | None = None


def entry_html(cfg: dict, template: dict | None = None) -> str:
    """The entry form (DN-022 section 7): the map, the location, the situation line,
    the three parsed fields shown back with their spans, the weather source, and one
    button that builds. Under the exercise banner like every screen (DN-012 section
    7). `static/entry.js` drives it. With `template` (`start.template`, HB-208), the
    form opens filled with a prepared scenario's values, every one editable."""
    page = cfg["page"]
    e = cfg["entry"]
    banner = html.escape(page["banner"])
    containers = "".join(
        f'<option value="{html.escape(c)}">{html.escape(c)}</option>'
        for c in e["containers"]
    )
    states = "".join(
        f'<option value="{html.escape(s)}">{html.escape(s)}</option>'
        for s in e["states"]
    )
    wx = "".join(
        f'<label>{html.escape(name)} <input name="{html.escape(name)}" '
        f'data-weather="1" placeholder="{html.escape(help_text)}"></label>'
        for name, (help_text, _) in weather_source.FIELD_HELP.items()
        if name != "weather_source"
    )
    sources = "".join(
        f'<option value="{s}"{" selected" if s == "forecast" else ""}>{s}</option>'
        for s in weather_source.SOURCES
    )
    css = (STATIC / "entry.css").read_text(encoding="utf-8")
    js = (STATIC / "entry.js").read_text(encoding="utf-8")
    tiles = json.dumps(cfg["map"]["fallback_tiles"], sort_keys=True)
    # HB-208 item 3: a prepared scenario's values, read by entry.js on load; its note
    # is printed by the server, so the page says what it was filled from
    tmpl, tmpl_note = "", ""
    if template is not None:
        data = json.dumps(template, sort_keys=True).replace("</", "<\\/")
        tmpl = f'<script id="entry-template" type="application/json">{data}</script>'
        tmpl_note = f'<p id="entry-template-note">{html.escape(template["note"])}</p>'
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>New brief</title>"
        f"<style>{render.vendored(cfg, 'css')}</style>"
        f"<style>{render.page_css(cfg)}</style><style>{css}</style></head>"
        f'<body><header id="top"><div class="banner">{banner}</div>'
        '<div class="bar"><h1>New brief: a point and a situation</h1></div></header>'
        '<main id="entry"><div id="entry-map"></div>'
        '<form id="entry-form" autocomplete="off">'
        # HB-207 item 11: one plain message at the top (a past start time, say)
        '<p id="entry-top" class="degraded" role="alert"></p>'
        f"{tmpl_note}"
        "<h2>1. Where</h2>"
        '<p class="panel-note">Click the map, or type a location and resolve it. A '
        "typed location is resolved by DN-013's rules; its derivation and accuracy are "
        "printed below.</p>"
        '<label>Location <select id="loc-kind">'
        '<option value="point">a point on the map</option>'
        '<option value="address">an address</option>'
        '<option value="intersection">cross-streets</option>'
        '<option value="milepost">a milepost</option>'
        '<option value="crossing">a grade crossing</option></select></label>'
        '<div id="loc-fields"></div>'
        '<button type="button" id="loc-resolve">Resolve</button>'
        '<p id="loc-label" class="pl"></p>'
        "<h2>2. What</h2>"
        f'<label>Situation <input id="line" maxlength="{int(e["line_max_chars"])}" '
        'placeholder="chlorine leaking from a rail tank car"></label>'
        '<button type="button" id="parse">Read the line</button>'
        '<p id="line-shown" class="pl"></p>'
        '<fieldset id="fields"><legend>Read from the line: correct any field</legend>'
        '<label>Material <input id="f-material" value="unknown"></label>'
        '<span class="erg" id="f-material-erg"></span>'
        f'<label>Container <select id="f-container">{containers}</select></label>'
        f'<label>State <select id="f-state">{states}</select></label>'
        '<p id="route" class="pl"></p></fieldset>'
        # HB-207 item 5: the reader confirms one ERG entry before anything is built
        '<fieldset id="confirm"><legend>Confirm the material</legend>'
        '<p id="typed-shown" class="pl"></p><div id="candidates"></div>'
        '<p id="material-reason" class="degraded"></p>'
        '<label id="confirm-label" hidden><input type="checkbox" id="confirm-entry"> '
        "This is the material</label></fieldset>"
        # HB-207 item 9 and ADDENDUM-03 item 1: what is assumed, each with its source
        '<fieldset id="assumed"><legend>Assumed until you correct it</legend>'
        '<label>Start time <input id="a-time" type="datetime-local"></label>'
        '<button type="button" id="use-now">Use now</button>'
        '<p id="a-time-note" class="pl"></p>'
        '<label>Quantity released (kg) <input id="a-qty" type="number" min="0" '
        'step="any"></label><p id="a-qty-source" class="pl"></p>'
        '<p id="a-state" class="pl"></p><p id="a-worst" class="pl"></p></fieldset>'
        '<fieldset id="weather"><legend>Weather source</legend>'
        f'<label>weather_source <select name="weather_source" data-weather="1">'
        f"{sources}</select></label>{wx}</fieldset>"
        '<button type="submit" id="build">Build the brief</button>'
        '<p id="entry-error" class="degraded" role="alert"></p></form></main>'
        f'<footer id="bottom" class="banner">{banner}</footer>'
        f"<script>{render.vendored(cfg, 'js')}</script>"
        f'<script id="entry-tiles" type="application/json">{tiles}</script>'
        f"{tmpl}<script>{js}</script></body></html>\n"
    )


def create_app(
    run: BriefRun | None,
    cfg: dict,
    *,
    host: str,
    port: int,
    author: NarrativeAuthor | None = None,
    asker: model_author.ModelAuthor | None = None,
    weather_check: Callable[[dict], object] | None = None,
    entry_form: EntryForm | None = None,
    replay: bool = False,
    checks_for: Callable[[str], checklist.ChecksLog] | None = None,
    start_menu: StartMenu | None = None,
) -> Starlette:
    """The routes over one run, behind the Host and Origin check: the page, its
    events, the static page, a record, the commander's report, the checklist's ticks,
    the guide panels, the replay's recording dates, and the question route.
    `author` is the run's own (the report prints its text); `asker` answers questions
    (none: the route answers with a structured error; the page has no question box,
    HBD-271, so only a caller outside the page posts there). `weather_check(fields)`
    validates the page query's weather fields (HB-139) as the run will, raising
    `weather_source.WeatherRefused`; None: the page takes no weather fields. `replay`:
    the run answers from recorded exchanges, and the page says so (F4).
    `checks_for(brief_id)` opens the checks log of a run the entry form makes.

    With `entry_form` and no `run`, the server starts on the entry form (HB-132R): the
    build route writes the form's fixture and makes the run. With `start_menu` as well,
    it starts on the start page (HB-208): `GET /entry` is the form (`?scenario=<id>`
    fills it from a prepared scenario), and `POST /start/recorded` makes the run a
    prepared scenario's served replay, with the menu's replay author and asker."""
    keepalive = float(cfg["web"]["keepalive_s"])
    author = author or NoAuthor()
    views: dict[str, model_author.BriefView] = {}
    if run is None and entry_form is None:
        raise ValueError("a server with no run serves the entry form: give one")
    if start_menu is not None and entry_form is None:
        raise ValueError("the start page's second door is the entry form: give one")
    #: the one run this server serves: given, or made by the entry form's build or the
    #: start page's recorded run; `replay`, `author` and `asker` are that run's (HB-208:
    #: a start page's server makes a live brief or a recorded one)
    state: dict[str, Any] = {
        "run": run,
        "from_form": False,
        "replay": replay,
        "author": author,
        "asker": asker,
    }

    def known(request: Request) -> bool:
        cur = state["run"]
        return cur is not None and request.path_params["brief_id"] == cur.brief_id

    async def index(request: Request) -> Response:
        """`GET /`, optionally with the weather fields as query parameters
        (`weather_source.FIELD_HELP`'s names; HB-139 item 4): validated by the run's own
        schema before the run starts. A refused selection is a 422 page naming the
        field or the acquisition; a run already started under other fields is a 409
        (one brief, one weather source). Before the entry form's build, the form; its
        weather field carries the selection, so a query is refused there."""
        q = {
            k: v
            for k, v in request.query_params.items()
            if k.startswith(weather_source.FIELD_PREFIXES)
        }
        run = state["run"]
        if run is None:
            if q:
                return HTMLResponse(
                    refusal_html(
                        "new brief", cfg["entry"]["refusals"]["weather_query"], cfg
                    ),
                    status_code=422,
                )
            if start_menu is not None:
                return HTMLResponse(start.page_html(cfg, start.menu_rows(cfg)))
            return HTMLResponse(entry_html(cfg))
        replay = state["replay"]
        if q:
            try:
                if weather_check is None:
                    raise weather_source.WeatherRefused(
                        "this server takes no weather fields", "weather_source"
                    )
                fields = weather_source.from_text(q)
                weather_check(fields)
            except weather_source.WeatherRefused as exc:
                return HTMLResponse(
                    refusal_html(run.brief_id, str(exc), cfg), status_code=422
                )
            if run.started and run.weather_fields != fields:
                return HTMLResponse(
                    refusal_html(
                        run.brief_id,
                        cfg["web"]["weather_after_start"],
                        cfg,
                    ),
                    status_code=409,
                )
            run.weather_fields = fields
        # HB-154 ADDENDUM-01 section 1: a fixture or a replay is always marked; only a
        # brief the entry form built live may be unmarked, by `entry.exercise_marking`
        exercise = (
            replay or not state["from_form"] or bool(cfg["entry"]["exercise_marking"])
        )
        return HTMLResponse(
            shell_html(
                run.brief_id,
                cfg,
                replay=replay,
                exercise=exercise,
                notes=state.get("form_notes"),
            )
        )

    async def events(request: Request) -> Response:
        """The stream from its first event, or from after `Last-Event-ID` (a
        reconnecting browser) or the `after` query (the page reading a tick that came
        after `run_finished` closed its stream, HB-141)."""
        if not known(request):
            return PlainTextResponse("no such brief", status_code=404)
        run = state["run"]
        last = request.headers.get("last-event-id") or request.query_params.get("after")
        after = int(last) if last and last.isdigit() else -1

        async def body() -> AsyncIterator[str]:
            async for item in run.follow(after, keepalive):
                if item is None:
                    yield ": keepalive\n\n"
                else:
                    yield sse(*item)
            if run.error is not None:
                data = json.dumps({"type": "run_failed", "error": run.error})
                yield f"event: run_failed\ndata: {data}\n\n"

        return StreamingResponse(
            body(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    async def page(request: Request) -> Response:
        if not known(request):
            return PlainTextResponse("no such brief", status_code=404)
        run = state["run"]
        try:
            text = await run.page()
        except RunFailed as exc:
            return PlainTextResponse(str(exc), status_code=500)
        return Response(
            text.encode("utf-8"),
            media_type="text/html; charset=utf-8",
            headers={"Cache-Control": "no-store"},
        )

    async def record(request: Request) -> Response:
        """`GET /brief/<id>/record/<hash>`: a record of the brief's record set, as JSON,
        as soon as its channel has settled; 404 for any other hash."""
        if not known(request):
            return PlainTextResponse("no such brief", status_code=404)
        run = state["run"]
        sha = request.path_params["sha"]
        brief = run.brief or run.live
        body = record_json(brief, sha, cfg) if brief is not None else None
        if body is None:
            return _error(
                404, "not_in_record_set", f"{sha} is not a record of this brief"
            )
        return JSONResponse(body, headers={"Cache-Control": "no-store"})

    async def report(request: Request) -> Response:
        """`GET /brief/<id>/report`: the commander's report of the finished run."""
        if not known(request):
            return PlainTextResponse("no such brief", status_code=404)
        run = state["run"]
        try:
            brief = await run.finished()
        except RunFailed as exc:
            return PlainTextResponse(str(exc), status_code=500)
        return HTMLResponse(
            render.report_html(
                brief, cfg, state["author"], checks=checklist.items(run.events, cfg)
            ),
            headers={"Cache-Control": "no-store"},
        )

    async def operator(request: Request) -> Response:
        """`POST /brief/<id>/check` or `/uncheck` with `{"item": <stream id>}`: the
        operator's tick, appended to the stream as `check` or `uncheck` with the
        server's time (HB-141 item 2; HBD-218). 422 for anything that is not a
        checklist item of the stream so far. The answer is the event and its id; the
        page draws the box from the stream, not from this answer."""
        if not known(request):
            return PlainTextResponse("no such brief", status_code=404)
        body = await _body(request)
        if body is None or "item" not in body:
            return _error(400, "item", 'send {"item": <stream id>} as JSON')
        action = request.url.path.rsplit("/", 1)[1]
        try:
            at, ev = state["run"].operator(action, body["item"])
        except ValueError as exc:
            return _error(422, "not_a_checklist_item", str(exc))
        return JSONResponse({"id": at, **ev.to_json()})

    async def site_route(request: Request) -> Response:
        """`POST /brief/<id>/site` with `{"point": "command_post" | "triage" |
        "staging", "coordinates": [lon, lat]}`, or `{"point": ..., "suggestion": true}`:
        a moved point, or a point put back on its suggestion (HB-155 item 8), appended
        to
        the stream as `site_moved` with its routes and Warning recomputed. 422 for
        anything else; 409 before the brief is presented."""
        if not known(request):
            return PlainTextResponse("no such brief", status_code=404)
        body = await _body(request)
        if body is None or "point" not in body:
            return _error(
                400,
                "point",
                'send {"point": ..., "coordinates": [lon, lat]} or '
                '{"point": ..., "suggestion": true} as JSON',
            )
        coords = None if body.get("suggestion") is True else body.get("coordinates")
        if coords is None and body.get("suggestion") is not True:
            return _error(400, "coordinates", "send coordinates or suggestion: true")
        try:
            at, ev = state["run"].site(body["point"], coords)
        except ValueError as exc:
            return _error(422, "not_a_move", str(exc))
        return JSONResponse({"id": at, **ev.to_json()})

    async def area_route(request: Request) -> Response:
        """`POST /brief/<id>/area` with `{"radius_m": <a step in metres; 0 is widen to
        nearest>}` (HB-155 ADDENDUM-02 item 5): an `area_radius_set` event; on a live
        serve a step past the data in hand reads that box first. 409 on a replay for a
        step not recorded; 422 for a radius that is not a step."""
        if not known(request):
            return PlainTextResponse("no such brief", status_code=404)
        body = await _body(request)
        if body is None or "radius_m" not in body:
            return _error(400, "radius_m", 'send {"radius_m": <metres>} as JSON')
        try:
            at, ev = await state["run"].area(body["radius_m"], live=not state["replay"])
        except NotRecorded as exc:
            return _error(409, "not_recorded", str(exc))
        except ValueError as exc:
            return _error(422, "not_a_step", str(exc))
        return JSONResponse({"id": at, **ev.to_json()})

    async def panels(request: Request) -> Response:
        """`GET /brief/<id>/panels`: the guide panels the brief holds (item 6;
        HBD-224), each the slice of its section's last streamed fragment, which is the
        static page's (`checklist.panels`)."""
        if not known(request):
            return PlainTextResponse("no such brief", status_code=404)
        last: dict[str, str] = {}
        for ev in state["run"].events:
            if ev.type == "section_settled":
                last[ev.section] = ev.fragment
        return JSONResponse(
            checklist.panels(last, cfg), headers={"Cache-Control": "no-store"}
        )

    async def recorded(request: Request) -> Response:
        """`GET /brief/<id>/recorded`: on a served replay, the date (or the first and
        last) its records were made, for the replay banner (F4; HBD-219); on a live
        serve, `{"replay": false}`."""
        if not known(request):
            return PlainTextResponse("no such brief", status_code=404)
        if not state["replay"]:
            return JSONResponse({"replay": False})
        try:
            brief = await state["run"].finished()
        except RunFailed as exc:
            return _error(500, "run_failed", str(exc))
        return JSONResponse(
            {"replay": True, "recorded": checklist.recorded_dates(brief, cfg)}
        )

    async def head(request: Request) -> Response:
        """`GET /brief/<id>/head`: the header line's facts (HB-154 item 4) from the
        blackboard as it stands (`render.head_facts`); each fact None until known."""
        if not known(request):
            return PlainTextResponse("no such brief", status_code=404)
        run = state["run"]
        brief = run.brief or run.live
        if brief is None:
            return JSONResponse({}, headers={"Cache-Control": "no-store"})
        return JSONResponse(
            render.head_facts(brief, cfg), headers={"Cache-Control": "no-store"}
        )

    async def sources(request: Request) -> Response:
        """`GET /brief/<id>/sources`: the Data sources view's table (HB-154 item 9)
        over the blackboard as it stands: one row per channel, a channel not yet
        settled marked pending. Read from what the run holds; no call."""
        if not known(request):
            return PlainTextResponse("no such brief", status_code=404)
        run = state["run"]
        brief = run.brief or run.live
        if brief is None:
            return HTMLResponse('<p class="pending">No channel has started.</p>')
        # HB-158 item 7: the MCP table's call counts are the evidence log's
        calls = data_sources.calls_from_events(run.events)
        return HTMLResponse(
            data_sources.table_html(data_sources.rows(brief, cfg), cfg, brief, calls),
            headers={"Cache-Control": "no-store"},
        )

    async def tevv_page(request: Request) -> Response:
        """`GET /tevv.html` (HB-161 ADDENDUM-01 items 1 and 4): the brief's TEVV page,
        built from the run's brief as it stands (the finished brief once it is in),
        the bytes the static page writes beside `brief.html`; the shell's links are
        relative, so the same `tevv.html#t<n>` opens here and beside a written page."""
        run = state["run"]
        if run is None:
            return PlainTextResponse("no brief has started", status_code=404)
        brief = run.brief or run.live
        if brief is None:
            return PlainTextResponse("no channel has settled", status_code=404)
        return HTMLResponse(
            tevv.page_html(brief, cfg), headers={"Cache-Control": "no-store"}
        )

    async def frames_json(request: Request) -> Response:
        """`GET /frames.json` (HB-192, DN-024 ADDENDUM-01 decision 6): the moving
        cloud's mesh, frame by frame, read by the page only when Play or a lookup is
        first used; the bytes the static page writes beside `brief.html`."""
        from hazbrief.brief import frames as F

        run = state["run"]
        brief = (run.brief or run.live) if run is not None else None
        pub = F.published((brief.derived or {}).get("cloud")) if brief else None
        if pub is None:
            return PlainTextResponse("no frames are held", status_code=404)
        return JSONResponse(pub, headers={"Cache-Control": "no-store"})

    def _finished_brief():
        run = state["run"]
        if run is None:
            return None, PlainTextResponse("no brief has started", status_code=404)
        brief = run.brief or run.live
        if brief is None:
            return None, PlainTextResponse("no channel has settled", status_code=404)
        return brief, None

    async def timeline_page(request: Request) -> Response:
        """`GET /timeline.html` (HB-171 item 9): the brief's threat timeline, the
        bytes the static page writes beside `brief.html`."""
        brief, err = _finished_brief()
        if err is not None:
            return err
        return HTMLResponse(
            threat.page_html(brief, cfg), headers={"Cache-Control": "no-store"}
        )

    async def timeline_csv(request: Request) -> Response:
        """`GET /timeline.csv` (HB-171 item 12): the exercise events list."""
        brief, err = _finished_brief()
        if err is not None:
            return err
        return Response(
            threat.msel_csv(brief, cfg),
            media_type="text/csv; charset=utf-8",
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": "attachment; filename="
                + f'"{threat.config()["csv_file"]}"',
            },
        )

    async def ask(request: Request) -> Response:
        """`POST /brief/<id>/ask` with `{"question": ...}`: the checked answer, or a
        structured error (422 for an answer the check refused; 404 when a replay
        holds no record of the question; 503 with no model route). The route reads
        the finished brief and calls nothing but the model."""
        if not known(request):
            return PlainTextResponse("no such brief", status_code=404)
        run = state["run"]
        asker = state["asker"]
        if asker is None:
            return _error(503, "no_model_route", "this server has no question box")
        try:
            q = (await request.json()).get("question")
        except (ValueError, AttributeError):
            return _error(400, "question", 'send {"question": "..."} as JSON')
        if not isinstance(q, str):
            return _error(400, "question", 'send {"question": "..."} as JSON')
        try:
            brief = await run.finished()
        except RunFailed as exc:
            return _error(500, "run_failed", str(exc))
        if "view" not in views:
            parts = render.page_parts(brief, cfg, state["author"])
            views["view"] = model_author.of_brief(brief, cfg, parts)
        try:
            out = await asyncio.to_thread(asker.ask, q, views["view"])
        except model_author.NoRecordedCall as exc:
            return _error(404, "no_recorded_call", str(exc))
        except model_author.ModelRouteError as exc:
            return _error(503, "model_route", str(exc))
        status = 200
        if "error" in out:
            # the call itself failed (502), or its answer was refused by the check
            status = 502 if out["error"]["code"] == "call_failed" else 422
        return JSONResponse(out, status_code=status)

    # ── the entry form (HB-132R Part B) ──

    async def _body(request: Request) -> dict | None:
        try:
            body = await request.json()
        except ValueError:
            return None
        return body if isinstance(body, dict) else None

    async def entry_parse(request: Request) -> Response:
        """`POST /entry/parse` with `{"line": ...}`: the three fields with their spans,
        the material's ERG resolution and the route; a refusal is a structured error
        (422; 404 when a replay holds no record of the line; 503 with no route). Writes
        nothing but the parser's transcript."""
        if entry_form is None:
            return PlainTextResponse("no entry form", status_code=404)
        body = await _body(request)
        if body is None:
            return _error(400, "line", 'send {"line": "..."} as JSON')
        now = entry_form.clock() if entry_form.clock else entry_form.incident_time
        try:
            out = await asyncio.to_thread(
                entry_form.parser.parse, body.get("line"), now
            )
        except entry.EntryRefused as exc:
            status = {"no_recorded_call": 404, "model_route": 503}.get(exc.code, 422)
            if exc.code == "call_failed":
                status = 502
            return JSONResponse(exc.to_json(), status_code=status)
        return JSONResponse(out)

    async def entry_assume(request: Request) -> Response:
        """`POST /entry/assume` with `{"container": ..., "confirmed": {id_number,
        name}}`: what the form proposes for that ERG entry and container (HB-207 items 8
        and 9), when the reader picks another candidate or corrects the container. The
        entry is checked to be an index row byte for byte. Writes nothing."""
        if entry_form is None:
            return PlainTextResponse("no entry form", status_code=404)
        body = await _body(request) or {}
        try:
            row = entry.confirmed_row(body.get("confirmed"), cfg)
            container = str(body.get("container") or "unknown")
            if container not in cfg["entry"]["containers"]:
                raise entry.EntryRefused(
                    "container",
                    cfg["entry"]["refusals"]["container"].format(
                        value=container,
                        allowed=", ".join(cfg["entry"]["containers"]),
                    ),
                )
        except entry.EntryRefused as exc:
            return JSONResponse(exc.to_json(), status_code=422)
        now = entry_form.clock() if entry_form.clock else entry_form.incident_time
        fields = {"container": {"value": container, "span": None}}
        return JSONResponse(entry.assumptions(fields, row, now, cfg))

    async def entry_locate(request: Request) -> Response:
        """`POST /entry/locate` with `{"given": {...}}` (DN-013's location kinds): the
        location record, its derivation, accuracy and label; an unresolved record
        (no match, the geocoder unavailable) says why, and nothing is guessed."""
        if entry_form is None:
            return PlainTextResponse("no entry form", status_code=404)
        body = await _body(request)
        given = (body or {}).get("given")
        if not isinstance(given, dict) or not given.get("kind"):
            return _error(400, "given", 'send {"given": {"kind": ..., ...}} as JSON')
        try:
            rec = await entry_form.locate(given)
        except location.LocationError as exc:
            return _error(422, "location", str(exc))
        return JSONResponse(
            {
                "resolved": rec.get("shape") is not None,
                "derivation": rec.get("derivation"),
                "accuracy_m": rec.get("accuracy_m"),
                "basis": rec.get("basis"),
                "label": rec.get("label"),
                "shape": rec.get("shape"),
            }
        )

    async def entry_build(request: Request) -> Response:
        """`POST /entry/build` with the form's values (`point` or `given`, `line`,
        `parse`, `fields`, `weather`): checked, written as a fixture file before the
        build starts (HB-132R item 5), then the run is made and started. The weather
        selection is HB-139's: a refused one is a 422 naming the field or the
        acquisition; once a brief has started, another build is a 409."""
        if entry_form is None:
            return PlainTextResponse("no entry form", status_code=404)
        if state["run"] is not None:
            return _error(409, "one_brief", cfg["entry"]["refusals"]["one_brief"])
        body = await _body(request)
        if body is None:
            return _error(400, "build", "send the form's values as JSON")
        try:
            wx_fields = weather_source.from_text(body.get("weather") or {})
            # first as the run's own fields (HB-139: the field or the acquisition is
            # named, observed refuses until its client exists) ...
            weather_source.select(cfg, None, wx_fields)
            # ... then as the block the fixture will carry
            block = weather_source.from_fields(wx_fields)
            # the default (forecast, no basis typed) writes no weather block; any
            # other selection is the fixture's block, with the form's basis (HB-132R
            # ADDENDUM-02 section 2), checked as the run will read it
            if block == {"source": "forecast"} or not block:
                block = None
            weather_source.select(cfg, block, None)
        except weather_source.WeatherRefused as exc:
            return _error(422, "weather", str(exc))
        try:
            fields = entry.corrected(body.get("fields") or {}, cfg)
            point, given = body.get("point"), body.get("given")
            if given is not None:
                rec = await entry_form.locate(given)
                if rec.get("shape") is None:
                    raise entry.EntryRefused(
                        "location_unresolved",
                        cfg["entry"]["refusals"]["location_unresolved"].format(
                            label=rec.get("label")
                        ),
                    )
            assumed = body.get("assumptions") or {}
            when = entry.incident_time_of(
                assumed.get("incident_time"), entry_form.incident_time, cfg
            )
            release = entry.release_of(assumed, fields, cfg)
            scenario = entry.scenario_of(
                point=point,
                given=given,
                fields=fields,
                line=str(body.get("line") or ""),
                parse=body.get("parse"),
                incident_time=when,
                weather=block,
                cfg=cfg,
                release=release,
            )
            # HB-208 item 3: the prepared scenario the form was filled from, beside the
            # form's other inputs (the build does not read it; the id does not hash it)
            if body.get("template") is not None:
                if body["template"] not in start.prepared_ids(cfg):
                    raise entry.EntryRefused(
                        "template",
                        cfg["start"]["unknown_scenario"].format(
                            id=str(body["template"])[:80]
                        ),
                    )
                scenario["entry"]["template"] = body["template"]
            # HB-207 item 11: a forecast build whose start time today's forecast no
            # longer holds is one plain message on the form, not eleven failures on
            # the page; the stated wind, or now, is the reader's
            if (block or {}).get("source", "forecast") == "forecast" and (
                entry_form.forecast_holds is not None
            ):
                where = scenario["incident"].get("location") or point
                if where and await entry_form.forecast_holds(where, when) is False:
                    raise entry.EntryRefused(
                        "past_time",
                        cfg["entry"]["refusals"]["past_time"].format(when=when),
                    )
        except entry.EntryRefused as exc:
            return JSONResponse(exc.to_json(), status_code=422)
        except (location.LocationError, TypeError, ValueError, KeyError) as exc:
            return _error(422, "build", f"{type(exc).__name__}: {exc}")
        # the fixture first: every brief the form starts is a fixture that replays
        path = entry.write_fixture(scenario, cfg, entry_form.fixtures_root)
        entry_form.written.append(path)
        new = BriefRun(
            scenario["id"],
            entry_form.make_start(scenario),
            checks=checks_for(scenario["id"]) if checks_for is not None else None,
        )
        state["run"], state["from_form"] = new, True
        row = fields["material"].get("confirmed")
        state["form_notes"] = {
            "start_time": scenario["incident"]["incident_time"],
            "levels": entry.levels_note(row, cfg) if row else None,
        }
        new.ensure_started()
        return JSONResponse(
            {"brief_id": new.brief_id, "fixture": str(path), "url": "/"},
            status_code=201,
        )

    # ── the start page (HB-208) ──

    async def entry_page(request: Request) -> Response:
        """`GET /entry`: the entry form, the start page's second door; with
        `?scenario=<id>`, filled from that prepared scenario at now (`start.template`).
        Once this server's brief has started, a 409 (one server, one brief)."""
        if entry_form is None:
            return PlainTextResponse("no entry form", status_code=404)
        if state["run"] is not None:
            return HTMLResponse(
                refusal_html(
                    state["run"].brief_id, cfg["entry"]["refusals"]["one_brief"], cfg
                ),
                status_code=409,
            )
        sid = request.query_params.get("scenario")
        if not sid:
            return HTMLResponse(entry_html(cfg))
        now = entry_form.clock() if entry_form.clock else entry_form.incident_time
        try:
            tmpl = start.template(sid, now, cfg)
        except start.UnknownScenario as exc:
            return HTMLResponse(refusal_html(sid, str(exc), cfg), status_code=404)
        return HTMLResponse(entry_html(cfg, tmpl))

    async def start_recorded(request: Request) -> Response:
        """`POST /start/recorded` with `{"scenario": <id>}`: this server's brief becomes
        the prepared scenario's served replay, as committed, with its recorded
        weather; the page then opens at `/` under the replay banner. 404 for an id
        that is not a prepared scenario; 409 once a brief has started."""
        if start_menu is None:
            return PlainTextResponse("no start page", status_code=404)
        if state["run"] is not None:
            return _error(409, "one_brief", cfg["entry"]["refusals"]["one_brief"])
        body = await _body(request)
        sid = (body or {}).get("scenario")
        if not isinstance(sid, str) or sid not in start.prepared_ids(cfg):
            return _error(
                404,
                "scenario",
                cfg["start"]["unknown_scenario"].format(id=str(sid)[:80]),
            )
        new = BriefRun(
            sid,
            start_menu.make_recorded(sid),
            checks=checks_for(sid) if checks_for is not None else None,
        )
        state.update(
            run=new,
            replay=True,
            author=start_menu.author or NoAuthor(),
            asker=start_menu.asker,
        )
        new.ensure_started()
        return JSONResponse({"brief_id": sid, "url": "/"}, status_code=201)

    async def favicon(request: Request) -> Response:
        """The hazbrief cloud for the browser tab; browsers ask for it at the root."""
        icon = (STATIC / "favicon.ico").read_bytes()
        return Response(icon, media_type="image/x-icon")

    app = Starlette(
        routes=[
            Route("/", index),
            Route("/favicon.ico", favicon),
            Route("/brief/{brief_id}/events", events),
            Route("/brief/{brief_id}/page", page),
            Route("/brief/{brief_id}/record/{sha}", record),
            Route("/brief/{brief_id}/report", report),
            Route("/brief/{brief_id}/ask", ask, methods=["POST"]),
            Route("/brief/{brief_id}/check", operator, methods=["POST"]),
            Route("/brief/{brief_id}/uncheck", operator, methods=["POST"]),
            Route("/brief/{brief_id}/site", site_route, methods=["POST"]),
            Route("/brief/{brief_id}/area", area_route, methods=["POST"]),
            Route("/brief/{brief_id}/panels", panels),
            Route("/brief/{brief_id}/recorded", recorded),
            Route("/brief/{brief_id}/head", head),
            Route("/brief/{brief_id}/sources", sources),
            Route("/tevv.html", tevv_page),
            Route("/frames.json", frames_json),
            Route("/timeline.html", timeline_page),
            Route("/timeline.csv", timeline_csv),
            Route("/entry/parse", entry_parse, methods=["POST"]),
            Route("/entry/assume", entry_assume, methods=["POST"]),
            Route("/entry/locate", entry_locate, methods=["POST"]),
            Route("/entry/build", entry_build, methods=["POST"]),
            Route("/entry", entry_page),
            Route("/start/recorded", start_recorded, methods=["POST"]),
        ]
    )
    return LoopbackOnly(app, allowed_hosts(host, port))


def bind(host: str, port: int) -> socket.socket:
    """A listening socket on `host:port`, or SystemExit naming the port when anything
    already answers there or the bind fails (HB-115's first start took another tool's
    200 as its own). Bound before the server reports ready."""
    if host not in LOOPBACK:
        raise SystemExit(
            f"orchestrator.yaml web.host is {host!r}: the live page binds loopback "
            "only (HB-89: the route has no authentication)"
        )
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as probe:
        probe.settimeout(1.0)
        if probe.connect_ex((host, port)) == 0:
            raise SystemExit(
                f"port {port} on {host} is taken: something already answers there. "
                "Stop it, or set another port in orchestrator.yaml web.port."
            )
    sock = socket.socket(family, socket.SOCK_STREAM)
    # a port this server left in TIME_WAIT is reusable; a listener was refused above
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
    except OSError as exc:
        sock.close()
        raise SystemExit(f"port {port} on {host} is taken: {exc}") from exc
    sock.listen()
    return sock


def default_checks_path(cfg: dict, brief_id: str) -> Path:
    """A new checks file for one serve: `web.checks_dir`/<brief>_<UTC time>.jsonl,
    under the repository root (git ignores the directory)."""
    from hazbrief.config import REPO_ROOT

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return REPO_ROOT / cfg["web"]["checks_dir"] / f"{brief_id}_{stamp}.jsonl"


def serve(
    brief_id: str | None,
    start: Start | None,
    cfg: dict,
    *,
    open_browser: bool = True,
    author: NarrativeAuthor | None = None,
    asker: model_author.ModelAuthor | None = None,
    weather_check: Callable[[dict], object] | None = None,
    entry_form: EntryForm | None = None,
    start_menu: StartMenu | None = None,
    replay: bool = False,
    checks_file: Path | None = None,
) -> int:
    """Serve one brief until interrupted: bind, then report the URL, then serve. With
    `entry_form` and no brief, the server opens on the entry form (HB-132R); with
    `start_menu` as well, on the start page (HB-208).

    The operator's checks are written to `checks_file`, whose recorded checks a replay
    puts back first; by default a new file per serve under `web.checks_dir` (HB-141)."""
    import uvicorn

    host, port = cfg["web"]["host"], int(cfg["web"]["port"])
    sock = bind(host, port)

    def checks_for(bid: str) -> checklist.ChecksLog:
        path = checks_file or default_checks_path(cfg, bid)
        return checklist.ChecksLog.open(path, bid)

    run = (
        BriefRun(brief_id, start, checks=checks_for(brief_id))
        if start is not None
        else None
    )
    app = create_app(
        run,
        cfg,
        host=host,
        port=port,
        author=author,
        asker=asker,
        weather_check=weather_check,
        entry_form=entry_form,
        replay=replay,
        checks_for=checks_for,
        start_menu=start_menu,
    )
    url = f"http://{host_port(host, port)}/"
    what = (
        f"brief {brief_id}"
        if run is not None
        else "the start page"
        if start_menu is not None
        else "the entry form"
    )
    print(f"serving {what} at {url} (Ctrl-C stops)", flush=True)
    if run is not None:
        print(f"operator checks: {run.checks.path}", flush=True)
    if open_browser:
        webbrowser.open(url)
    server = uvicorn.Server(
        uvicorn.Config(app, log_level="warning", lifespan="off", access_log=False)
    )
    server.run(sockets=[sock])
    return 0
