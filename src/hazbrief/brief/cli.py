"""`hazbrief brief`: one labelled brief from the seven tools (DN-011 D5; HB-41 step 6).

To start the application and reach its start page (a prepared scenario's recorded run,
the scenario with today's conditions, or a new incident; HB-208):

    uv run hazbrief brief --serve

Every other form:

    hazbrief brief SCENARIO.json --out DIR             # live: spawns the server
    hazbrief brief SCENARIO.json --out DIR --replay    # from the stores; no call
    hazbrief brief SCENARIO.json --out DIR --no-google # the Leaflet fallback map
    hazbrief brief SCENARIO.json --serve --replay      # the live page (HB-130R)

SCENARIO.json is one scenario in `fixtures/scenarios.yaml`'s shape: `incident`, `wind`
(optional), `as_given`, and `id`; optionally `release` (HB-69) and `stated_wind`
(HB-70), the application fields the puff reads and the server never sees. A scenario
snapshot (`fixtures/scenarios/<id>.json`), which holds only an id, is resolved through
`fixtures/scenarios.yaml`.

Writes `brief.html` (rewritten as each section settles, so the first paint is the map),
`appendix.html` and `appendix.txt` (DN-010 D6), `tevv.html` (HB-161: one section per
thing the brief draws or states from a method), and prints one status line per section
with its timing. A live run writes its records into the evidence store
(`HAZBRIEF_EVIDENCE_STORE`, else `evidence/store/`). `--replay` reads the tool-call seed
and the exchange seed. `--now` holds the instant the labels are read at, for a
reproducible page; without it the labels are read at the wall clock.

The map's basemap is Google when the application setting `GOOGLE_MAPS_API_KEY` is set
(`hazbrief.brief.settings`; the key is written into the page, so restrict it by HTTP
referrer), else Leaflet over the USGS National Map. `--no-google` ignores the key: the
committed briefs are built so, and carry no key.

`--serve` writes no file: it serves the brief's live page on loopback
(`hazbrief.brief.web`; `orchestrator.yaml` `web.host` and `web.port`), assembles the
brief when the page asks for it, streams each section as it settles, and serves the
static page of the finished run beside it. `--replay`, `--now` and `--no-google` mean
what they mean for a written brief. `--no-open` prints the URL without opening a
browser. The page's question box asks the brief's model (`model_author`; HB-131R):
with `--replay` it answers only from recorded transcripts (`--transcripts DIR`), and
makes no call.

The weather source (DN-019 ADDENDUM-01; HB-139): `orchestrator.yaml` `weather.source`
(forecast by default), a scenario's `weather:` block (only with a `basis`, which the
brief prints), then this run's `--weather-source` and its fields (`--stated-*`,
`--observed-*`, `--weather-basis`; `weather_source.FIELDS`). One schema validates all
three; a refused selection prints its reason, naming the field or the acquisition, and
exits 3 before anything is called. The `--serve` page takes the same names as query
parameters (`/?weather_source=stated&stated_speed_kmh=...`) before its run starts.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Callable

import yaml

from hazbrief.brief import location, tevv, threat, weather_source
from hazbrief.brief.orchestrator import (
    RENDER_ORDER,
    Brief,
    BriefEvent,
    assemble,
    load_config,
)
from hazbrief.brief.settings import google_maps_api_key
from hazbrief.config import REPO_ROOT
from hazbrief.evidence import labels as L
from hazbrief.evidence import store as S

SCENARIOS = REPO_ROOT / "fixtures" / "scenarios.yaml"
#: the exit status of a run whose weather selection is refused (HB-139): distinct from
#: 2, a brief that was written with a section degraded
EXIT_WEATHER_REFUSED = 3


def replay_stores() -> list[Path]:
    """The stores `--replay` reads: the tool-call seed, the scenario-brief seed (the
    other fixture scenarios' calls, HB-45), and the exchange seed their `used` names."""
    return [
        S.repo_path("seed_calls_store_dir"),
        S.repo_path("seed_briefs_store_dir"),
        S.repo_path("seed_store_dir"),
    ]


def load_scenario(path: Path) -> dict:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if "incident" in doc:
        return doc
    sid = doc.get("scenario") or doc.get("id")
    for s in yaml.safe_load(SCENARIOS.read_text(encoding="utf-8"))["scenarios"]:
        if s["id"] == sid:
            return s
    raise SystemExit(
        f"FATAL: {path} has no incident, and {sid!r} is not in {SCENARIOS}"
    )


def _write(path: Path, text: str) -> None:
    """Atomic: a reader of a half-written page never sees one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    # mkstemp creates the file 0600; the brief is committed and read by anyone
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def replay_brief(
    scenario: dict, now, on_event: Callable[[BriefEvent], None] | None = None
) -> Brief:
    """A committed brief's replay, as `scripts/build_scenario_briefs.py` builds it
    (`--replay --no-google` at the given `now`), with its event stream (HB-130R)."""
    return asyncio.run(
        assemble(scenario, now=now, replay_stores=replay_stores(), on_event=on_event)
    )


def status_lines(brief: Brief) -> list[str]:
    """One line per section in the render order: its state and when it settled."""
    settled = {
        e["section"]: e["t"]
        for e in brief.events
        if e["event"] in ("render", "degrade")
    }
    out = []
    for name in RENDER_ORDER:
        sec = brief.sections[name]
        t = settled.get(name)
        when = f"{t:7.2f} s" if t is not None else "      - "
        tail = f"  {sec['reason']}" if sec["state"] == "degraded" else ""
        out.append(f"{name:<11} {sec['state']:<9} {when}{tail}")
    return out


def _with_puff_run(app: dict, brief: Brief) -> dict:
    """The first-order puff's run record after the cited records (DN-018 section 8,
    C2; HB-67): its sha256, then each input it read, with its source and, for a pack,
    the pack's sha256. A derivation, not a store record, so it is listed apart."""
    p = (brief.derived or {}).get("puff") or {}
    ev = p.get("evidence") or {}
    if not ev.get("sha256"):
        return app
    rows = [("First-order puff run record", ev["sha256"], "")]
    for i in p.get("inputs") or []:
        rows.append((f"  {i['name']}", str(i["value"]), i.get("sha256") or i["source"]))
    text = "\nDerived: the first-order puff\n" + "".join(
        f"{a}  {b}  {c}".rstrip() + "\n" for a, b, c in rows
    )
    import html as H

    body = "".join(
        f"<tr><td>{H.escape(a)}</td><td>{H.escape(b)}</td><td>{H.escape(c)}</td></tr>"
        for a, b, c in rows
    )
    return {
        **app,
        "text": app["text"] + text,
        "html": app["html"] + "<h2>Derived: the first-order puff</h2>"
        f'<table class="puff-run">{body}</table>',
    }


#: The dense-gas section's row names, which `the HB-112 evidence`
#: reads back from `appendix.txt` (HB-112 step 5): the table regenerates from the
#: committed briefs, never from a fresh run.
DENSE_GAS_ROWS = {
    "record": "Dense-gas run record",
    "class": "DN-001 class",
    "legend": "level of concern",
    "state": "state",
    # HB-120: the routing table's decision for the guide and the storage state
    "release_route": "release route",
    "engine": "engine",
    "deck": "SLAB deck sha256",
    "output": "SLAB output sha256",
    "erg": "ERG protective action distance (m)",
    "puff": "puff extent at the class's threshold (m)",
    "puff_at": "puff contour",
    "dense": "dense-gas downwind extent (m)",
    "ratios": "modelled over ERG",
}


def _with_dense_gas_run(app: dict, brief: Brief) -> dict:
    """The dense-gas run record after the puff's (HB-112 step 4; C2): its sha256, the
    engine and the hashes of SLAB's deck and output, the state, the comparison with the
    ERG and the puff, and each source-term input with its tier beside its doc_id and
    page in one cell (HB-112 ADDENDUM-01), then the material's model-test-input
    sentence. A derivation, not a store record, so it is listed apart."""
    import hashlib
    import html as H

    from hazbrief.brief.dense_gas import reach_text

    d = (brief.derived or {}).get("dense_gas") or {}
    ev = d.get("evidence") or {}
    if not ev.get("sha256"):
        return app
    spec = load_config()["weather"]["dense_gas"]
    rec = ev.get("record") or {}
    n = DENSE_GAS_ROWS
    cmp_ = d.get("comparison") or {}
    # HB-120: the three states of the modelled tier (DN-020 ADDENDUM-02 item 4)
    if d.get("footprint"):
        state = "drawn"
    elif d.get("state") == "not_applicable":
        state = f"not applicable: {d.get('reason')}"
    else:
        state = f"not drawn: {d.get('reason')}"
    rr = d.get("release_route") or {}
    release_route = (
        (
            f"{rr['route'].replace('_', ' ')}"
            + (f", level of concern {rr['loc_class']}" if rr.get("loc_class") else "")
        )
        if rr.get("route")
        else ""
    )
    route_basis = (
        f"Guide {rr['guide']}, {(rr.get('state') or 'any state').replace('_', ' ')}"
        f" ({rr['basis']['locator']})"
        if rr.get("basis")
        else ""
    )
    engine = (
        f"{d['engine_kind']} {d['engine_id']} ({d.get('route')})"
        if d.get("engine_id")
        else ""
    )
    out_sha = rec.get("output_sha256") or ""
    deck = rec.get("deck")
    deck_sha = hashlib.sha256(deck.encode("latin-1")).hexdigest() if deck else ""

    def num(x):
        return "" if x is None else f"{x:.0f}"

    dense, dense_note = "", ""
    if d.get("footprint"):
        dense = num(cmp_.get("dense_m"))
        if cmp_.get("dense_beyond_table"):
            # the level is still exceeded at SLAB's last row: a floor, never an end
            dense_note = reach_text(cmp_.get("dense_m"), True, spec)
    rows = [
        (n["record"], ev["sha256"], ""),
        (
            f"  {n['class']}",
            str(d.get("class") or ""),
            f"UN{d['un']}" if d.get("un") else "",
        ),
        (f"  {n['legend']}", d.get("legend") or "", ""),
        (f"  {n['state']}", state, d.get("hint") or ""),
        (f"  {n['release_route']}", release_route, route_basis),
        (f"  {n['engine']}", engine, ""),
        (f"  {n['deck']}", deck_sha, ""),
        (f"  {n['output']}", out_sha, ""),
        (f"  {n['erg']}", num(cmp_.get("erg_m")), cmp_.get("erg_zone") or ""),
        (f"  {n['puff']}", num(cmp_.get("puff_m")), ""),
        (f"  {n['puff_at']}", cmp_.get("puff_at") or "", ""),
        (f"  {n['dense']}", dense, dense_note),
        (
            f"  {n['ratios']}",
            (
                f"puff {cmp_.get('puff_ratio')}; dense gas {cmp_.get('dense_ratio')}"
                if cmp_
                else ""
            ),
            "",
        ),
    ]
    for r in d.get("tier_rows") or []:
        name = f"  input {r['name']}" + (f" ({r['slab']})" if r["slab"] else "")
        rows.append((name, r["value"], r["tier_source"]))
    if d.get("tier_sentence"):
        rows.append(("  tier note", d["tier_sentence"], ""))
    for i in d.get("inputs") or []:
        rows.append((f"  {i['name']}", str(i["value"]), i.get("sha256") or i["source"]))
    text = "\nDerived: the dense-gas footprint\n" + "".join(
        f"{a}  {b}  {c}".rstrip() + "\n" for a, b, c in rows
    )
    body = "".join(
        f"<tr><td>{H.escape(a)}</td><td>{H.escape(b)}</td><td>{H.escape(c)}</td></tr>"
        for a, b, c in rows
    )
    return {
        **app,
        "text": app["text"] + text,
        "html": app["html"] + "<h2>Derived: the dense-gas footprint</h2>"
        f'<table class="dense-gas-run">{body}</table>',
    }


def _with_load_read(app: dict, brief: Brief) -> dict:
    """The load read's rows after the derivations' (HB-132R item 2; DN-022 section 6):
    the rule file's sha256, each section's words before and after the read, and the
    cuts applied and proposed. A render step, not a store record, so it is listed
    apart, under a "Derived:" heading as the puff's and the dense gas's are: the
    appendix's readers take the records table to end at the first one."""
    import html as H

    from hazbrief.brief import load_read

    rep = brief.load_read
    if not rep:
        return app
    rows = load_read.summary_lines(rep, list(RENDER_ORDER))
    text = "\nDerived: the load read\n" + "".join(
        f"{a}  {b}  {c}".rstrip() + "\n" for a, b, c in rows
    )
    body = "".join(
        f"<tr><td>{H.escape(a)}</td><td>{H.escape(b)}</td><td>{H.escape(c)}</td></tr>"
        for a, b, c in rows
    )
    return {
        **app,
        "text": app["text"] + text,
        "html": app["html"] + "<h2>Derived: the load read</h2>"
        f'<table class="load-read">{body}</table>',
    }


def write_outputs(brief: Brief, out: Path) -> None:
    _write(out / "brief.html", brief.html)
    # each cited hash prints the record this brief read, not the newest record of its
    # body, which can be another scenario's call (HB-99)
    cited = {r["entity"]["sha256"]: r for r in brief.records()}
    shas = list(cited)
    # the spill point's location record, beside the footprint request's values (HB-48)
    loc = location.of_brief(brief, load_config())
    fp = brief.channels.get(location.FOOTPRINT, {}).get("record")
    # a location not resolved (HB-50) made no call, so no record carries it; the page
    # carries the record itself (render's location-record)
    locs = {fp["entity"]["sha256"]: loc} if loc and fp else None
    app = L.appendix(shas, brief.now, brief.stores, brief.time_zone, locs, cited)
    app = _with_puff_run(app, brief)
    app = _with_dense_gas_run(app, brief)
    app = _with_load_read(app, brief)
    title = f"Evidence appendix: {brief.scenario_id}"
    page = (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        f"<title>{title}</title><style>body {{ font-family: "
        f"{load_config()['page']['font_stack']}; margin: 24px 32px; }} "
        "table { border-collapse: collapse; } th, td { text-align: left; "
        "padding: 3px 10px 3px 0; border-bottom: 1px solid #eeeeee; font-size: 13px; } "
        "tr.used td:first-child { padding-left: 18px; color: #595959; }</style></head>"
        f"<body><h1>{title}</h1>{app['html']}</body></html>\n"
    )
    _write(out / "appendix.html", page)
    _write(out / "appendix.txt", app["text"])
    # HB-161 ADDENDUM-01 item 1: the TEVV page beside the brief, from the same state
    _write(out / load_config()["tevv"]["file"], tevv.page_html(brief, load_config()))
    # HB-192 (DN-024 ADDENDUM-01 decision 6): the moving cloud's mesh beside the page,
    # read only when Play or a lookup is first used; none where no frames are held
    from hazbrief.brief import frames as F

    pub = F.published((brief.derived or {}).get("cloud"))
    if pub is not None:
        _write(out / F.PUBLISHED, json.dumps(pub, sort_keys=True) + "\n")
    # HB-171 items 9 and 12: the threat timeline and its exercise events list
    tc = threat.config()
    _write(out / tc["file"], threat.page_html(brief, load_config()))
    _write(out / tc["csv_file"], threat.msel_csv(brief, load_config()))


def entry_start(scenario: dict, **kw) -> Callable:
    """The run the entry form's build starts for the scenario it wrote: the same
    `assemble` a written brief or `--serve` runs, over the fixture's own values."""

    def start(on_event, on_brief, weather_fields=None):
        return assemble(
            scenario,
            on_event=on_event,
            on_brief=on_brief,
            weather_fields=weather_fields,
            **kw,
        )

    return start


def _live_kw(cfg: dict, args) -> dict:
    """What a served live run's `assemble` takes so its map draws its geometry (HB-208,
    Issue 8907cf6c; `live_exchanges`): a new exchanges directory for this run, the
    server in record mode on it, and each call's reads named in its record's `used`.
    Nothing for a replay, which reads its recorded stores."""
    if args.replay:
        return {}
    from hazbrief.brief.live_exchanges import LiveExchanges

    return LiveExchanges.from_config(cfg, S.default_store_dir()).assemble_kw()


def _now_to_the_minute() -> str:
    """Now, UTC, to the minute: the start time the live form proposes (HB-207
    ADDENDUM-03 item 1); the reader sees it in local time and may change it."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(second=0, microsecond=0).isoformat()


def recorded_start(scenario: dict, author) -> Callable:
    """A prepared scenario's served replay (HB-208 "Open the recorded run"), exactly
    as `hazbrief brief docs/briefs/<id>/scenario.json --serve --replay --now
    <fixture_now> --no-google` starts it: the stores `--replay` reads, the fixture's
    now, no key. Its static page is the committed `brief.html` (HB-130R)."""
    now = S.parse_time(L.config()["fixture_now"])
    flags = weather_source.from_text({n: None for n in weather_source.FIELD_HELP})

    def start(on_event, on_brief, weather_fields=None):
        return assemble(
            scenario,
            on_event=on_event,
            on_brief=on_brief,
            weather_fields={**flags, **(weather_fields or {})},
            now=now,
            google_key="",
            author=author,
            replay_stores=replay_stores(),
        )

    return start


def _serve_entry(args, *, start_page: bool = False) -> int:
    """`--serve --entry`: the live page opens on the entry form (HB-132R Part B). The
    form's typed locations are resolved by DN-013's rules (from recorded exchanges with
    `--replay`); its situation line is parsed by the entry route's model (only from
    recorded transcripts with `--replay`).

    `--serve` alone (`start_page`): the live page opens on the start page (HB-208),
    whose second door is the same entry form and whose first opens a prepared
    scenario's recorded run (`recorded_start`) or fills the form from it."""
    from hazbrief.brief import entry, live_records, model_author, start, web
    from hazbrief.brief.orchestrator import author_from_config

    cfg = load_config()
    # HB-207 item 1: a served run's new engine records stay out of the tree
    live_records.set_root(REPO_ROOT / cfg["entry"]["records_dir"])
    now = S.parse_time(args.now) if args.now else S.parse_time(S.utc_now())
    key = "" if args.no_google else google_maps_api_key()
    author = author_from_config(cfg, replay=args.replay)
    kw: dict = {"now": now, "google_key": key, "author": author}
    if args.replay:
        kw["replay_stores"] = replay_stores()
    else:
        kw["store"] = S.default_store_dir()

    async def locate(given: dict) -> dict:
        return await location.locate(given, cfg, replay=args.replay)

    async def forecast_holds(point: dict, when: str) -> bool | None:
        """HB-207 item 11: whether NWS's forecast grid holds a wind at the point for
        `when` (the grid's layers begin at its `validTimes` start, hours before now:
        12:00Z for a 19:37Z read on 2026-11-19, docs/evidence/hb207/resume.md). None
        when NWS cannot be asked: the build goes on and the page says what failed."""
        from hazbrief import nws
        from hazbrief.utils import UpstreamServiceError

        try:
            await nws.wind_at(
                float(point["latitude"]), float(point["longitude"]), S.parse_time(when)
            )
        except nws.WindUnavailable:
            return False
        except UpstreamServiceError:
            return None
        return True

    form = web.EntryForm(
        parser=entry.parser_from_config(cfg, replay=args.replay),
        locate=locate,
        make_start=lambda scenario: entry_start(scenario, **kw, **_live_kw(cfg, args)),
        incident_time=now.isoformat(),
        # live: the form proposes the time it reads the line at; a replay keeps --now
        clock=None if args.replay else _now_to_the_minute,
        forecast_holds=None if args.replay else forecast_holds,
    )
    menu = None
    if start_page:
        # the recorded run reads only recorded transcripts, whatever this server is
        rauthor = author_from_config(cfg, replay=True)
        menu = web.StartMenu(
            make_recorded=lambda sid: recorded_start(
                start.records(sid, cfg)[1], rauthor
            ),
            author=rauthor,
            asker=model_author.from_config(
                cfg, replay=True, transcripts=args.transcripts
            ),
        )
    return web.serve(
        None,
        None,
        cfg,
        open_browser=not args.no_open,
        author=author,
        asker=model_author.from_config(
            cfg, replay=args.replay, transcripts=args.transcripts
        ),
        entry_form=form,
        replay=args.replay,
        checks_file=args.checks,
        start_menu=menu,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="hazbrief brief",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("scenario", type=Path, nargs="?")
    ap.add_argument("--out", type=Path, help="the brief's directory (not with --serve)")
    ap.add_argument(
        "--entry",
        action="store_true",
        help="with --serve and no SCENARIO: open on the entry form, a point and a "
        "situation line (HB-132R); the build writes its fixture into "
        "orchestrator.yaml entry.fixtures_dir first",
    )
    ap.add_argument(
        "--serve",
        action="store_true",
        help="serve the live page on loopback instead of writing files (HB-130R)",
    )
    ap.add_argument(
        "--no-open", action="store_true", help="with --serve: do not open a browser"
    )
    ap.add_argument(
        "--transcripts",
        type=Path,
        help="with --serve: the question box's model transcripts (default "
        "orchestrator.yaml model.transcripts_dir); with --replay it answers only "
        "the questions they hold (HB-131R: the HB-131 evidence)",
    )
    ap.add_argument(
        "--checks",
        type=Path,
        help="with --serve: the operator checks file; its recorded checks are put "
        "back at their places in the stream and new ones are appended (HB-141; "
        "default a new file per serve under orchestrator.yaml web.checks_dir)",
    )
    ap.add_argument("--replay", action="store_true")
    ap.add_argument("--now", help="ISO 8601 instant the labels are read at")
    ap.add_argument(
        "--no-google",
        action="store_true",
        help="ignore GOOGLE_MAPS_API_KEY: the Leaflet fallback map, no key in the page",
    )
    wx = ap.add_argument_group(
        "weather source (DN-019 ADDENDUM-01; HB-139)",
        "Override orchestrator.yaml weather for this run; the --serve page takes the "
        "same names as query parameters. Under stated every stated field is given.",
    )
    for name, (help_text, _) in weather_source.FIELD_HELP.items():
        wx.add_argument("--" + name.replace("_", "-"), dest=name, help=help_text)
    args = ap.parse_args(argv)
    if args.serve == (args.out is not None):
        ap.error("give exactly one of --out DIR and --serve")
    if args.entry:
        if not args.serve or args.scenario is not None:
            ap.error("--entry takes --serve and no SCENARIO")
        return _serve_entry(args)
    if args.scenario is None:
        if args.serve:
            # HB-208: the start page, a prepared scenario or a new incident
            return _serve_entry(args, start_page=True)
        ap.error("give SCENARIO, --serve for the start page, or --serve --entry")
    scenario = load_scenario(args.scenario)
    try:
        fields = weather_source.from_text(
            {n: getattr(args, n) for n in weather_source.FIELD_HELP}
        )
        # checked before anything starts, by the schema assemble checks it with
        weather_source.select(load_config(), scenario.get("weather"), fields)
    except weather_source.WeatherRefused as exc:
        print(f"hazbrief brief: weather refused: {exc}", file=sys.stderr)
        return EXIT_WEATHER_REFUSED
    now = S.parse_time(args.now) if args.now else S.parse_time(S.utc_now())
    key = "" if args.no_google else google_maps_api_key()
    if args.serve:
        from hazbrief.brief import live_records, model_author, web
        from hazbrief.brief.orchestrator import author_from_config

        cfg = load_config()
        # HB-207 item 1: a served run's new engine records stay out of the tree
        live_records.set_root(REPO_ROOT / cfg["entry"]["records_dir"])
        # one author for the run and its report (`orchestrator.yaml` `author`); the
        # question box replays only its transcripts when the brief replays (HB-131R)
        author = author_from_config(cfg, replay=args.replay)
        kw: dict = {"now": now, "google_key": key, "author": author}
        if args.replay:
            kw["replay_stores"] = replay_stores()
        else:
            kw["store"] = S.default_store_dir()

        def start(on_event, on_brief, weather_fields=None):
            # the page's query, when it gives weather fields, over the flags' (HB-139)
            return assemble(
                scenario,
                on_event=on_event,
                on_brief=on_brief,
                weather_fields={**fields, **(weather_fields or {})},
                **kw,
                **_live_kw(cfg, args),
            )

        return web.serve(
            scenario.get("id", "scenario"),
            start,
            cfg,
            open_browser=not args.no_open,
            author=author,
            asker=model_author.from_config(
                cfg, replay=args.replay, transcripts=args.transcripts
            ),
            # the page's query fields over the flags', checked by the run's schema
            replay=args.replay,
            checks_file=args.checks,
            weather_check=lambda f: weather_source.select(
                cfg, scenario.get("weather"), {**fields, **f}
            ),
        )
    out = args.out

    def first_paint(brief: Brief) -> None:
        _write(out / "brief.html", brief.html)

    kw = {
        "now": now,
        "on_render": first_paint,
        "google_key": key,
        "weather_fields": fields,
    }
    if args.replay:
        kw["replay_stores"] = replay_stores()
    else:
        kw["store"] = S.default_store_dir()
    brief = asyncio.run(assemble(scenario, **kw))
    write_outputs(brief, out)
    print(f"brief {brief.scenario_id} ({'replay' if args.replay else 'live'}):")
    for line in status_lines(brief):
        print("  " + line)
    print(
        f"wrote {out / 'brief.html'}, appendix.html, appendix.txt, tevv.html, "
        "timeline.html, timeline.csv"
    )
    degraded = [n for n, s in brief.sections.items() if s["state"] != "rendered"]
    return 0 if not degraded else 2


if __name__ == "__main__":
    sys.exit(main())
