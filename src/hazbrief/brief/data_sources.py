"""The Data sources view (HB-154 item 9; DN-019 ADDENDUM-03 section 3; Issue 97736b94
item 5): every MCP server and public source the brief contacted or reads from, with what
came back, in the operator's four plain outcomes.

One row per channel the brief holds, which is the evidence log's set of channels (each a
tool of the hazbrief MCP server; `orchestrator.yaml` `channels`): the public sources its
record's label names (DN-010 D4), or with no record the catalog rows the tool reads;
what the brief uses it for (the titles of the sections the channel feeds); the outcome;
and each source's as-of. Built from the channel states and records the brief already
holds, so it adds no call. The live page's fifth tab, the static page's foot and the
commander's report all print `table_html` over `rows`.

The outcome of a channel (`data_sources.by_state`, `error_by_reason`):

- `ok`: answered; but a record whose body is a structured error (DN-003's no-key Census
  case) was not configured, so not contacted;
- `error`: read by its reason: a replay with no recorded answer made no contact; an
  upstream that failed could not be reached; any other error is the tool's own answer
  that it holds nothing for this incident (reached, nothing available);
- `timeout`, `missing`: could not be reached; `not_run`, `skipped`: not contacted.

A source that could not be reached is a degraded section, whose DN-011 D2 label is the
checklist's Data gaps item (HB-141); the row's reason line is that label, word for word.
"""

from __future__ import annotations

import html
from typing import Any

from hazbrief.evidence import catalog
from hazbrief.evidence import labels as L

PENDING = "pending"


def _sections_of(tool: str, cfg: dict) -> list[str]:
    return [n for n, s in cfg["sections"].items() if tool in s["channels"]]


def _gives(tool: str, cfg: dict) -> str:
    return "; ".join(cfg["sections"][n]["title"] for n in _sections_of(tool, cfg))


def outcome(ch: dict, cfg: dict) -> str:
    """The outcome key (`data_sources.outcomes`) of one settled channel, or
    `pending`."""
    spec = cfg["data_sources"]
    state = ch.get("state")
    if state in (None, "pending"):
        return PENDING
    if state == "ok":
        body = ch.get("payload")
        if isinstance(body, dict) and body.get("error"):
            return spec["structured_error"]
        return spec["by_state"]["ok"]
    if state == "error":
        why = ch.get("reason") or ""
        for rule in spec["error_by_reason"]:
            if why.startswith(rule["starts"]):
                return rule["outcome"]
        return spec["error_default"]
    if state not in spec["by_state"]:
        raise ValueError(f"channel state {state!r} has no data_sources outcome")
    return spec["by_state"][state]


def _why(brief, tool: str, ch: dict, key: str, cfg: dict) -> str:
    """The reason line under an outcome other than answered: the degraded section's
    DN-011 D2 label when a section this channel feeds is degraded (the Data gaps item's
    own words), else the channel's reason."""
    if key in (PENDING, "answered"):
        return ""
    for name in _sections_of(tool, cfg):
        sec = brief.sections.get(name) or {}
        if sec.get("state") == "degraded" and sec.get("reason"):
            return sec["reason"]
    return ch.get("reason") or ""


def rows(brief, cfg: dict) -> list[dict[str, Any]]:
    """One row per channel of the brief, in `channels` order (the evidence log's set):
    `tool`, `server`, `sources` (each `{name, as_of}`; as-of None when nothing came
    back), `gives`, `outcome` (a key of `data_sources.outcomes`, or `pending`),
    `outcome_text` and `why`."""
    spec = cfg["data_sources"]
    out = []
    for tool in cfg["channels"]:
        ch = brief.channels.get(tool) or {}
        key = outcome(ch, cfg)
        rec = ch.get("record")
        sources: list[dict] = []
        if rec is not None:
            lab = L.label_for(rec, brief.now, ch.get("payload"))
            for s in lab["sources"]:
                if s.get("provenance_class") == "caller_supplied":
                    continue
                sources.append(
                    {"name": s["name"], "as_of": L.as_of_phrase(s, brief.time_zone)}
                )
        else:
            sources = [
                {"name": r["name"], "as_of": None} for r in catalog.rows_for_tool(tool)
            ]
        out.append(
            {
                "tool": tool,
                "server": spec["server"],
                "sources": sources,
                "gives": _gives(tool, cfg),
                "outcome": key,
                "outcome_text": spec["outcomes"].get(key, spec["pending"]),
                "why": _why(brief, tool, ch, key, cfg),
            }
        )
    mp = derivation_row(brief, cfg)
    if mp is not None:
        out.append(mp)
    out += area_stage_rows(brief, cfg)
    return out


def area_stage_rows(brief, cfg: dict) -> list[dict[str, Any]]:
    """HB-155 ADDENDUM-02 item 4 and ADDENDUM-05 item 5: each stage of the services in
    the area (and a step the reader had read) is a fetch of the brief application, not
    an MCP call: one row each, `kind` "derivation", beside the population derivation
    and under the same heading, with no strip mark. A stage still being read is
    `pending` (the Retrieving state); a replay with no recorded answer reads "not
    contacted"."""
    spec = cfg["data_sources"]
    d = (getattr(brief, "derived", None) or {}).get("nearby")
    if not d:
        return []
    a = cfg["derive"]["area"]
    mpm = float(a["metres_per_mile"])
    srcs = d.get("sources") or []
    asof = (
        L.when(srcs[0]["retrieved"], brief.time_zone)
        if srcs and srcs[0].get("retrieved")
        else None
    )
    keys = {
        "retrieved": "answered",
        "failed": "unreachable",
        "not_contacted": "not_contacted",
    }
    stages = d.get("stages") or [
        {
            "n": 1,
            "box_m": None,
            "outcome": "not_contacted",
            "reason": d.get("stations_reason") or d.get("reason"),
        }
    ]
    out = []
    for st in stages:
        if d.get("stations_reason") and st["outcome"] == "retrieved":
            continue
        key = keys.get(st["outcome"], "pending")
        if (
            d.get("stations_reason")
            and key == "unreachable"
            and (d["stations_reason"] == spec["derivation"]["unrecorded"])
        ):
            key = "not_contacted"
        miles = (st["box_m"] or a["radius_m"]) / mpm
        names = list(spec["area_stage"]["sources"])
        if st["n"] == 1:
            names += spec["area_stage"]["siting_sources"]
        out.append(
            {
                "tool": f"area_stage_{st['n']}",
                "kind": "derivation",
                "server": a["stage_title"].format(n=st["n"], miles=round(miles)),
                "sources": [
                    {"name": n, "as_of": asof if key == "answered" else None}
                    for n in names
                ],
                "gives": a["stage_one_note"] if st["n"] == 1 else a["stage_two_note"],
                "outcome": key,
                "outcome_text": spec["outcomes"].get(key, spec["pending"]),
                "why": st.get("reason") or (d.get("stations_reason") or ""),
            }
        )
    return out


def derivation_row(brief, cfg: dict) -> dict[str, Any] | None:
    """HB-157 ADDENDUM-01 item 6: the population under the modelled area is a fetch of
    its own (TIGERweb blocks, DHC rows), made by the brief application, not an MCP
    tool: one row, `kind` "derivation", with its outcome. A replay with no recorded
    answer reads "not contacted"; no modelled layer drawn reads "not contacted" with
    that reason; None before the derivations have run."""
    spec = cfg["data_sources"]
    d = (getattr(brief, "derived", None) or {}).get("modelled_population")
    if d is None:
        return None
    dspec = spec["derivation"]
    why = d.get("reason") or ""
    if d.get("absent"):
        key = "not_contacted"
    elif not why:
        key = "answered"
    elif why == dspec["unrecorded"]:
        key = "not_contacted"
    else:
        key = "unreachable"
    asof = None
    srcs = d.get("sources") or []
    if srcs and srcs[0].get("retrieved"):
        asof = L.when(srcs[0]["retrieved"], brief.time_zone)
    return {
        "tool": "modelled_population",
        "kind": "derivation",
        "server": dspec["server"],
        "sources": [
            {"name": n, "as_of": asof if key == "answered" else None}
            for n in dspec["sources"]
        ],
        "gives": dspec["gives"],
        "outcome": key,
        "outcome_text": spec["outcomes"][key],
        "why": why,
    }


# ── HB-215 Part B: every source the brief called, one row each, by kind ─────────────


class UnmappedSource(LookupError):
    """A source the brief's records name that `data_sources.board.sources` does not:
    refused, so the view never drops a source silently."""


def _index(spec: dict) -> dict[tuple[str, str], str]:
    """(kind, name) -> source id over `board.sources`; a name two rows claim is
    refused."""
    out: dict[tuple[str, str], str] = {}
    for s in spec["sources"]:
        for kind in ("labels", "apis", "location"):
            for name in s.get(kind, []):
                key = (kind, name)
                if key in out:
                    raise ValueError(
                        f"board: {key} is claimed by {out[key]} and {s['id']}"
                    )
                out[key] = s["id"]
        if "derived" in s:
            out[("derived", s["derived"])] = s["id"]
    return out


def _exchanges(obj, out: list[dict]) -> None:
    """Every exchange descriptor (a dict with a string `api`) under `obj`."""
    if isinstance(obj, dict):
        if isinstance(obj.get("api"), str):
            out.append(obj)
        for v in obj.values():
            _exchanges(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _exchanges(v, out)


def _latest(times: list[str | None]) -> str | None:
    """The newest of ISO-8601 UTC stamps of one form (`...Z`), which sort as text."""
    got = [t for t in times if t]
    return max(got) if got else None


def _contributions(
    brief, cfg: dict, got: list[dict]
) -> list[tuple[str, str, str | None]]:
    """(source id, status, as-of words) for each thing in the brief's records that
    names a source: the channel and derivation rows' label sources, the derivations'
    exchanges (or, with none, their reasons), the location record and the engines."""
    spec = cfg["data_sources"]["board"]
    idx = _index(spec)
    tz = brief.time_zone
    out: list[tuple[str, str, str | None]] = []

    def sid(kind: str, name: str) -> str:
        if (kind, name) not in idx:
            raise UnmappedSource(
                f"the brief names {kind[:-1] if kind != 'location' else kind} "
                f"{name!r}, which data_sources.board.sources does not"
            )
        return idx[(kind, name)]

    for r in got:
        status = spec["from_outcome"][r["outcome"]]
        for s in r["sources"]:
            out.append((sid("labels", s["name"]), status, s["as_of"]))
    derived = getattr(brief, "derived", None) or {}
    for key, d in derived.items():
        if not isinstance(d, dict) or key in {
            s["derived"] for s in spec["sources"] if "derived" in s
        }:
            continue
        exs: list[dict] = []
        _exchanges(d, exs)
        for ex in exs:
            when = L.when(ex["retrieved"], tz) if ex.get("retrieved") else None
            out.append((sid("apis", ex["api"]), "answered", when))
        if not exs and key in spec["derived_apis"] and d.get("reason"):
            why = str(d["reason"])
            status = (
                "failed"
                if any(m in why for m in spec["failed_markers"])
                else "not_called"
            )
            for api in spec["derived_apis"][key]:
                out.append((sid("apis", api), status, None))
    loc = getattr(brief, "location", None)
    if loc and loc.get("source") and loc["source"] != "request":
        out.append(
            (
                sid("location", loc["source"]),
                "answered",
                L.when(loc["as_of"], tz) if loc.get("as_of") else None,
            )
        )
    fc = (derived.get("forecast") or {}).get("sources") or []
    wind_at = _latest([x.get("retrieved") for x in fc])
    for s in spec["sources"]:
        d = derived.get(s.get("derived", "")) if "derived" in s else None
        if not isinstance(d, dict) or not d.get("state"):
            continue
        status = spec["model_states"].get(d["state"])
        if status is None:
            raise UnmappedSource(f"engine state {d['state']!r} has no board status")
        if status == "not_called" and d.get("record") and d.get("reason"):
            status = "failed"
        asof = L.when(wind_at, tz) if wind_at and status == "answered" else None
        out.append((s["id"], status, asof))
    return out


def board(brief, cfg: dict, got: list[dict] | None = None) -> list[dict[str, Any]]:
    """The view's first table (HB-215 Part B item 8): one row per source the brief's
    records name, in `board.sources` order, each `{id, group, name, gives, status,
    as_of}`; a status is the first of `board.precedence` among the source's
    contributions. The basemap rows (the browser's call) are "not called" until the
    page's map script marks them. Built from the records; no call."""
    spec = cfg["data_sources"]["board"]
    got = rows(brief, cfg) if got is None else got
    seen: dict[str, list[tuple[str, str | None]]] = {}
    for source_id, status, asof in _contributions(brief, cfg, got):
        seen.setdefault(source_id, []).append((status, asof))
    tiles = cfg["map"]["fallback_tiles"]
    keyed = bool(getattr(brief, "google_key", ""))
    out = []
    for s in spec["sources"]:
        if s["group"] == "basemap":
            if ("google" in s) != keyed:
                continue
            name = s.get("name") or tiles[s["tile"]]["name"]
            out.append(
                {
                    "id": s["id"],
                    "group": "basemap",
                    "name": name,
                    "gives": s["gives"],
                    "status": "not_called",
                    "as_of": spec["basemap_as_of"],
                    "tile": s.get("tile"),
                }
            )
            continue
        got_s = seen.get(s["id"])
        if not got_s:
            continue
        status = next(p for p in spec["precedence"] if any(g[0] == p for g in got_s))
        asof = next((a for st, a in got_s if st == status and a), None)
        out.append(
            {
                "id": s["id"],
                "group": s["group"],
                "name": s["name"],
                "gives": s["gives"],
                "status": status,
                "as_of": asof,
            }
        )
    return out


def board_mark(cfg: dict, status: str) -> str:
    """A status as the board prints it: its shape, then its word (the shape is
    aria-hidden, the word is read); `data-status` carries the key, the class its
    colour."""
    st = cfg["data_sources"]["board"]["statuses"][status]
    return (
        f'<span class="bst bst-{status}" data-status="{status}">'
        f'<span class="mk" aria-hidden="true">{html.escape(st["glyph"])}</span> '
        f"{html.escape(st['words'])}</span>"
    )


#: the states the page's map script may give a basemap row (`render.MAP_JS` baseMark)
BROWSER_STATUSES = ("not_called", "answered", "failed")


def _marks(cfg: dict, r: dict) -> str:
    """A row's mark. A basemap row (the browser's call) prints its three possible
    marks, all but its status hidden, so the map script switches one on as tiles load
    or fail without printing words of its own."""
    if r["group"] != "basemap":
        return board_mark(cfg, r["status"])
    out = []
    for k in BROWSER_STATUSES:
        m = board_mark(cfg, k)
        out.append(m if k == r["status"] else m.replace("<span ", "<span hidden ", 1))
    return "".join(out)


def board_counts(rows_: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows_:
        if r["group"] != "basemap":
            out[r["status"]] = out.get(r["status"], 0) + 1
    return out


def board_html(brief, cfg: dict, got: list[dict]) -> str:
    """The board: under each heading of `board.groups`, one line per source with its
    mark (shape and word), its name, what it gave the brief and its as-of. A heading
    with no source prints its `none` line where it has one, else is left out."""
    spec = cfg["data_sources"]["board"]
    e = html.escape
    rows_ = board(brief, cfg, got)
    no_asof = cfg["data_sources"]["no_as_of"]
    head = "".join(f"<th>{e(c)}</th>" for c in spec["columns"])
    out = [
        f'<div class="board"><h3>{e(spec["title"])}</h3>'
        f'<p class="pl">{e(spec["note"])}</p>'
    ]
    for g in spec["groups"]:
        mine = [r for r in rows_ if r["group"] == g["id"]]
        if not mine and not g.get("none"):
            continue
        out.append(f'<h4 data-group="{e(g["id"])}">{e(g["title"])}</h4>')
        if not mine:
            out.append(f'<p class="pl none">{e(g["none"])}</p>')
            continue
        body = "".join(
            f'<tr data-source="{e(r["id"])}" data-status="{e(r["status"])}"'
            + (' data-browser="1"' if r["group"] == "basemap" else "")
            + f"><td>{_marks(cfg, r)}</td><td>{e(r['name'])}</td>"
            f"<td>{e(r['gives'])}</td>"
            f'<td class="asof">{e(r["as_of"] or no_asof)}</td></tr>'
            for r in mine
        )
        out.append(
            f'<table class="board-rows"><thead><tr>{head}</tr></thead>'
            f"<tbody>{body}</tbody></table>"
        )
    out.append("</div>")
    return "".join(out)


def calls_from_brief(brief, cfg: dict) -> dict[str, int]:
    """The calls each tool of the hazbrief server answered for, as the brief holds
    them: one per channel that holds a record, plus the footprint's further samples
    (`Brief.samples`, HB-49). The live page counts the evidence log's
    `channel_started` events instead (`calls_from_events`); the two agree on every
    committed brief (test_hb158_less_at_once.py)."""
    out = {}
    for tool in cfg["channels"]:
        ch = brief.channels.get(tool) or {}
        n = 1 if ch.get("state") not in (None, "pending", "not_run", "skipped") else 0
        if tool == "protective_action_footprint":
            n += len(getattr(brief, "samples", None) or [])
        out[tool] = n
    return out


def calls_from_events(events: list) -> dict[str, int]:
    """The evidence log's calls per tool: its `channel_started` events (each a call
    asked of the hazbrief server; HB-131R item 2)."""
    out: dict[str, int] = {}
    for ev in events:
        d = ev.to_json() if hasattr(ev, "to_json") else dict(ev)
        if d.get("type") == "channel_started":
            out[d["tool"]] = out.get(d["tool"], 0) + 1
    return out


def _mark(brief, cfg: dict, key: str, tools: list[str]) -> str:
    """An outcome key as its state mark (`data_sources.outcome_states`, then
    `render.three_state`'s time or date)."""
    from hazbrief.brief import render

    state = cfg["data_sources"]["outcome_states"][key]
    if state != "retrieved":
        return render.state_mark(cfg, state)
    k, t, d = render.three_state(brief, cfg, tools, "rendered")
    return render.state_mark(cfg, k, time=t, date=d)


def _server_row(brief, got: list[dict], cfg: dict, calls: dict[str, int]) -> str:
    """The MCP servers table's one row: the hazbrief server, each of its seven tools
    by name with its call count ("not called" for none), the server's state (any
    channel retrieving: retrieving; every channel failed: could not retrieve; else
    retrieved, or recorded on a replay) and its as-of (the latest call's end)."""
    spec = cfg["data_sources"]
    e = html.escape
    mcp = [r for r in got if r.get("kind") != "derivation"]
    keys = [cfg["data_sources"]["outcome_states"][r["outcome"]] for r in mcp]
    if "retrieving" in keys:
        key = "pending"
    elif keys and all(k == "failed" for k in keys):
        key = "unreachable"
    else:
        key = "answered"
    tools = "".join(
        f'<li data-tool="{e(t)}" data-calls="{calls.get(t, 0)}">'
        f"{e(t.replace('_', ' '))} "
        f'<span class="n">{calls[t] if calls.get(t) else e(spec["not_called"])}'
        "</span></li>"
        for t in spec["server_tools"]
    )
    head = "".join(f"<th>{e(c)}</th>" for c in spec["servers_columns"])
    from hazbrief.brief import render

    _, t, d = render.three_state(brief, cfg, list(cfg["channels"]), "rendered")
    return (
        f"<h3>{e(spec['servers_title'])}</h3>"
        f'<table class="mcp-servers"><thead><tr>{head}</tr></thead><tbody>'
        f'<tr data-server="hazbrief"><td>{e(spec["server"])}</td>'
        f'<td><ul class="tools">{tools}</ul></td>'
        f"<td>{_mark(brief, cfg, key, list(cfg['channels']))}</td>"
        f"<td>{e(d or t)}</td></tr></tbody></table>"
    )


def _refs_html(cfg: dict, tool: str, present: list[str]) -> str:
    """HB-161 ADDENDUM-01 item 4: the numbers of the TEVV sections this brief has
    that read the row's channel or derivation (`tevv.sections` `tools`), as links."""
    from hazbrief.brief import tevv

    reg = tevv.registry(cfg)
    links = [
        tevv.link_html(cfg, sid) for sid in present if tool in reg[sid].get("tools", [])
    ]
    if not links:
        return ""
    return f'<p class="tref-line">{cfg["tevv"]["link_text"]}: {" ".join(links)}</p>'


def _rows_html(
    brief, rows_: list[dict], cfg: dict, present: list[str] | None = None
) -> str:
    """One line per source row (item 3; ADDENDUM-01 item 6: marks, names and times,
    not sentences): its state mark, its tool and public sources, its as-of; what it
    gives, the outcome in the HB-154 words and the reason open under the line."""
    spec = cfg["data_sources"]
    e = html.escape
    body = []
    for r in rows_:
        names = "; ".join(s["name"] for s in r["sources"])
        asof = "".join(
            f"<li>{e(s['name'])}: {e(s['as_of'] or spec['no_as_of'])}</li>"
            for s in r["sources"]
        )
        first = next((s["as_of"] for s in r["sources"] if s["as_of"]), None)
        why = f'<span class="why">{e(r["why"])}</span>' if r["why"] else ""
        tools = [r["tool"]] if r.get("kind") != "derivation" else []
        body.append(
            f'<tr data-tool="{e(r["tool"])}" data-outcome="{e(r["outcome"])}">'
            f"<td>{_mark(brief, cfg, r['outcome'], tools)}</td>"
            f'<td><details class="trow"><summary><span class="tool">'
            f"{e(r['tool'].replace('_', ' '))}</span> "
            f'<span class="srcs">{e(names)}</span></summary>'
            f'<p class="pl">{e(r["server"])}; gives: {e(r["gives"])}</p>'
            f'<p class="pl"><span class="outcome">{e(r["outcome_text"])}</span>'
            f"{why}</p><ul>{asof}</ul>"
            f"{_refs_html(cfg, r['tool'], present or [])}</details></td>"
            f"<td>{e(first or spec['no_as_of'])}</td></tr>"
        )
    return (
        '<table class="data-sources"><thead><tr><th>State</th><th>Source</th>'
        f"<th>As of</th></tr></thead><tbody>{''.join(body)}</tbody></table>"
    )


def table_html(
    got: list[dict], cfg: dict, brief=None, calls: dict[str, int] | None = None
) -> str:
    """The view (HB-158 item 7): the MCP servers table first, then one line per
    channel (the public sources behind each tool), then the brief application's own
    derivation under its own heading. `calls` is the evidence log's count per tool
    (`calls_from_events`), else the brief's (`calls_from_brief`)."""
    spec = cfg["data_sources"]
    e = html.escape
    if brief is None:
        raise ValueError("table_html needs the brief its rows were read from")
    calls = calls if calls is not None else calls_from_brief(brief, cfg)
    mcp = [r for r in got if r.get("kind") != "derivation"]
    own = [r for r in got if r.get("kind") == "derivation"]
    out = _server_row(brief, got, cfg, calls)
    # HB-161: each row carries the numbers of the TEVV sections it feeds
    from hazbrief.brief import tevv

    # a blackboard with no derivations yet (or a stand-in) has no sections to name
    present = tevv.present(brief, cfg) if hasattr(brief, "derived") else []
    # HB-215 Part B: after the server, every source the brief called, by kind
    out += board_html(brief, cfg, got)
    out += f"<h3>{e(spec['sources_title'])}</h3>{_rows_html(brief, mcp, cfg, present)}"
    if own:
        out += (
            f"<h3>{e(spec['derivation_title'])}</h3>"
            f"{_rows_html(brief, own, cfg, present)}"
        )
    return (
        f'<details class="about"><summary>About this view</summary>'
        f'<p class="note">{e(spec["note"])}</p></details>{out}'
    )


def annex_html(brief, cfg: dict) -> str:
    """The Data sources annex of the static page and of the commander's report."""
    spec = cfg["data_sources"]
    return (
        f'<div class="data-sources-annex"><h3>{html.escape(spec["title"])}</h3>'
        f"{table_html(rows(brief, cfg), cfg, brief)}</div>"
    )
