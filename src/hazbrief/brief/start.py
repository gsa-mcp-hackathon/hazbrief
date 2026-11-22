"""The start page (HB-208): what `hazbrief brief --serve` opens on.

    uv run hazbrief brief --serve

Two doors (the operator, 2026-11-19 13:49 EST: "a good start page of fire one up from
the demonstration or enter a new one"):

1. **The prepared scenarios** (`menu_rows`). One row per scenario held under
   `fixtures/scenarios/` that has a committed brief under `docs/briefs/<id>/`. No cell
   is written by hand: each is read from the scenario's own record, the tool record
   `fixtures/scenarios/<id>.json` the committed brief replays and the CLI input
   `docs/briefs/<id>/scenario.json` that built it:

   - the place: the ICS 201 tool's TIGERweb place and county
     (`build_ics_201.tool_outputs.tigerweb_place`), as block 5 prints it;
   - the material: the footprint tool's resolved ERG entry, its name (the name the
     index matched, else the first it prints) and ID number; where none resolved, the
     material as given and the guide the record took;
   - the container, and the time the run is for (`incident.incident_time`, in the zone
     NWS gave for the point, `build_ics_201.tool_outputs.nws_time_zone`);
   - day or night: the footprint tool's ERG Table 1 period.

   Sorted by material, then place, then time, so that different materials are easy
   to find (13:49 EST: "where it is, what chemical release it is").

   Each row opens its **recorded run**, the served replay `hazbrief brief
   docs/briefs/<id>/scenario.json --serve --replay --now <fixture_now> --no-google`
   makes, whose static page is the committed `brief.html` byte for byte (HB-130R), or
   is **run with today's conditions** (`template`): the entry form opens with the
   scenario's material (an ERG entry, so already confirmed), container, quantity,
   fire state and point copied in, now as the start time and the forecast as the
   weather (13:54 and 14:00 EST: "use it as a template ... adjust the location, or
   just say run with today's conditions"). Every field stays editable; nothing is
   built until the reader presses Build; no parse call is made.

2. **Enter a new incident**: the entry form as HB-207 left it.

The application's code, not the server's: `.dockerignore` keeps `src/hazbrief/brief/`
out of the container image.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from hazbrief.config import REPO_ROOT


class UnknownScenario(LookupError):
    """A scenario id that is not a prepared scenario with a recorded brief."""


def _dirs(cfg: dict) -> tuple[Path, Path]:
    s = cfg["start"]
    return REPO_ROOT / s["scenarios_dir"], REPO_ROOT / s["briefs_dir"]


def prepared_ids(cfg: dict) -> list[str]:
    """The ids of every scenario under `start.scenarios_dir` whose committed brief is
    held (`<briefs_dir>/<id>/brief.html` and its `scenario.json`)."""
    scen, briefs = _dirs(cfg)
    return sorted(
        p.stem
        for p in scen.glob("*.json")
        if (briefs / p.stem / "brief.html").is_file()
        and (briefs / p.stem / "scenario.json").is_file()
    )


def records(sid: str, cfg: dict) -> tuple[dict, dict]:
    """(the scenario's tool record, the CLI input that built its committed brief)."""
    if sid not in prepared_ids(cfg):
        raise UnknownScenario(cfg["start"]["unknown_scenario"].format(id=sid))
    scen, briefs = _dirs(cfg)
    tools = json.loads((scen / f"{sid}.json").read_text(encoding="utf-8"))["tools"]
    given = json.loads((briefs / sid / "scenario.json").read_text(encoding="utf-8"))
    return tools, given


def _place(tools: dict, cfg: dict) -> str:
    out = (tools.get("build_ics_201") or {}).get("tool_outputs") or {}
    tp = out.get("tigerweb_place") or {}
    county = tp.get("county") or {}
    parts = [
        (tp.get("place") or {}).get("name"),
        county.get("name"),
        county.get("state"),
    ]
    # the District of Columbia is its own county-equivalent: printed once
    seen: list[str] = []
    for p in parts:
        if p and p not in seen:
            seen.append(p)
    return ", ".join(seen) or cfg["start"]["not_given"]


def _time_zone(tools: dict) -> str | None:
    out = (tools.get("build_ics_201") or {}).get("tool_outputs") or {}
    return (out.get("nws_time_zone") or {}).get("time_zone")


def erg_entry(tools: dict) -> dict | None:
    """The ERG index row the footprint tool resolved (`{id_number, name, guide}`),
    checked against the held index byte for byte; None where none resolved."""
    from hazbrief import packs as P
    from hazbrief.index_candidates import in_index

    mat = (tools.get("protective_action_footprint") or {}).get("material") or {}
    idn = mat.get("id_number")
    if not idn:
        return None
    erg = P.default_packs().erg.data
    names = [mat["matched_name"]] if mat.get("matched_name") else []
    names += list(mat.get("names") or [])
    for name in names:
        row = in_index(idn, name, erg)
        if row is not None:
            return row
    return None


def _material(tools: dict, given: dict, cfg: dict) -> str:
    s = cfg["start"]
    row = erg_entry(tools)
    if row is not None:
        return f"{row['name']}, {row['id_number']}"
    inc = given.get("incident") or {}
    guide = ((tools.get("protective_action_footprint") or {}).get("guide") or {}).get(
        "number"
    )
    if inc.get("material"):
        what = s["material_unresolved"].format(given=inc["material"])
    elif inc.get("placard"):
        what = s["placard"].format(placard=inc["placard"])
    else:
        what = s["material_none"]
    return f"{what}; {s['guide'].format(number=guide)}" if guide else what


def _period(tools: dict, cfg: dict) -> str:
    dn = (tools.get("protective_action_footprint") or {}).get("day_night")
    if isinstance(dn, dict) and dn.get("period"):
        return dn["period"]
    return cfg["start"]["not_given"]


def _when(iso: str | None, tz: str | None, cfg: dict) -> str:
    from hazbrief.evidence import labels as L

    if not iso:
        return cfg["start"]["not_given"]
    return L.when(iso, tz) if tz else iso


def menu_rows(cfg: dict) -> list[dict[str, str]]:
    """One row per prepared scenario, every cell read from its record, sorted by
    material, then place, then time."""
    rows = []
    for sid in prepared_ids(cfg):
        tools, given = records(sid, cfg)
        inc = given.get("incident") or {}
        rows.append(
            {
                "id": sid,
                "place": _place(tools, cfg),
                "material": _material(tools, given, cfg),
                "container": inc.get("container") or cfg["start"]["not_given"],
                "when": _when(inc.get("incident_time"), _time_zone(tools), cfg),
                "incident_time": inc.get("incident_time") or "",
                "period": _period(tools, cfg),
            }
        )
    rows.sort(
        key=lambda r: (r["material"].lower(), r["place"], r["incident_time"], r["id"])
    )
    return rows


def template(sid: str, now: str, cfg: dict) -> dict[str, Any]:
    """The entry form's values for a prepared scenario run with today's conditions
    (item 3): its point, its fields with the confirmed ERG entry, and what the form
    proposes (`entry.assumptions`) at `now`, with the scenario's own quantity where it
    gives one and its guide takes a release model. The weather is the form's default,
    the forecast. Calls nothing."""
    from hazbrief.brief import entry

    s = cfg["start"]
    tools, given = records(sid, cfg)
    inc = given.get("incident") or {}
    row = erg_entry(tools)
    state = "burning" if inc.get("fire_involved") else "leaking"
    container = inc.get("container") or "unknown"
    if container not in cfg["entry"]["containers"]:
        container = "unknown"
    if row is not None:
        material = {"value": row["name"], "span": None}
        note = s["template_material"].format(
            entry=f"{row['id_number']}, {row['name']} (ERG Guide {row['guide']})"
        )
    elif inc.get("material"):
        material = {"value": str(inc["material"]), "span": None}
        note = s["template_material_unresolved"].format(given=inc["material"])
    elif inc.get("placard"):
        material = {"value": "unknown", "span": None}
        note = s["template_placard"].format(placard=inc["placard"])
    else:
        material = {"value": "unknown", "span": None}
        note = s["template_no_material"]
    fields = {
        "material": material,
        "container": {"value": container, "span": None},
        "state": {"value": state, "span": None},
    }
    assumed = entry.assumptions(fields, row, now, cfg)
    release = given.get("release") or {}
    q = assumed.get("quantity") or {}
    routed = (
        assumed.get("storage_state", {}).get("route", {}).get("status")
        != "not_applicable"
    )
    if row is not None and routed and release.get("quantity_kg"):
        kg = release["quantity_kg"]
        assumed["quantity"] = {
            **q,
            "kg": kg,
            "short": s["template_quantity"].format(
                kg=kg, source=release.get("quantity_source") or s["not_given"]
            ),
        }
    loc = inc.get("location") or {}
    tools_place = _place(tools, cfg)
    return {
        "scenario": sid,
        "point": (
            {"latitude": loc["latitude"], "longitude": loc["longitude"]}
            if "latitude" in loc
            else None
        ),
        "fields": fields,
        "confirmed": row,
        "material_note": note,
        "assumptions": assumed,
        "note": s["template_note"].format(id=sid, place=tools_place),
    }


def page_html(cfg: dict, rows: list[dict[str, str]]) -> str:
    """The start page: the exercise banner, the prepared scenarios as a table with the
    two buttons on each row, and the door to the entry form. `static/start.js` posts
    the recorded run's choice."""
    from hazbrief.brief import render
    from hazbrief.brief.web import STATIC

    s = cfg["start"]
    esc = html.escape
    banner = esc(cfg["page"]["banner"])
    head = "".join(f"<th>{esc(c)}</th>" for c in s["columns"])
    body = "".join(
        f'<tr data-scenario="{esc(r["id"])}">'
        f"<td>{esc(r['place'])}</td><td>{esc(r['material'])}</td>"
        f"<td>{esc(r['container'])}</td><td>{esc(r['when'])}</td>"
        f'<td>{esc(r["period"])}</td><td class="doors">'
        f'<button type="button" class="open-recorded" '
        f'data-scenario="{esc(r["id"])}">{esc(s["open_recorded"])}</button> '
        f'<a class="run-today" href="/entry?scenario={esc(r["id"])}">'
        f"{esc(s['run_today'])}</a></td></tr>"
        for r in rows
    )
    css = (STATIC / "start.css").read_text(encoding="utf-8")
    js = (STATIC / "start.js").read_text(encoding="utf-8")
    page = cfg["page"]
    # room under the fixed header and above the fixed footer (`page.header_px`,
    # `page.footer_px`), so the first door's heading is not under the header
    room = (
        f"#start {{ padding-top: {int(page['header_px']) + 12}px; "
        f"padding-bottom: {int(page['footer_px']) + 12}px; }}"
    )
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{esc(s['title'])}</title>"
        f"<style>{render.page_css(cfg)}</style><style>{css}{room}</style></head>"
        f'<body><header id="top"><div class="banner">{banner}</div>'
        f'<div class="bar"><h1>{esc(s["heading"])}</h1></div></header>'
        '<main id="start">'
        # door two first, in one line, so both doors are on the first screen
        f'<section id="door-two"><h2>{esc(s["door_two"])}</h2>'
        f'<p class="panel-note">{esc(s["door_two_note"])} '
        f'<a id="new-incident" href="/entry">{esc(s["door_two"])}</a></p>'
        "</section>"
        f'<section id="door-one"><h2>{esc(s["door_one"])}</h2>'
        f'<p class="panel-note">{esc(s["door_one_note"])}</p>'
        '<p id="start-error" class="degraded" role="alert"></p>'
        f'<table id="scenarios"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></section></main>"
        f'<footer id="bottom" class="banner">{banner}</footer>'
        f"<script>{js}</script></body></html>\n"
    )
