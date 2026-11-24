"""The brief as one HTML file (DN-011 D5; HB-41 step 6).

One file, inline CSS, the house style (HB-38 RESULT section 4: the Calibri stack, white,
black or grey text, one orange accent). The map is Leaflet, from pinned jsDelivr assets,
over the footprint's own GeoJSON and the TIGERweb roads image the ICS 201's Block 4 was
drawn over, embedded from the evidence store. The rest of the page is static, so it
opens from `file://`.

Every rendered section ends with its labels: each source, its as-of in the incident's
zone, and current or stale, with the record's hash prefix (DN-010 D4, read through
`hazbrief.evidence.labels`). A degraded section prints DN-011 D2's label in the accent.
A pending one says what it waits for (the first paint). The page holds no timing and no
wall clock, only the `now` the labels were read at, so a replay with `now` held fixed
gives the same bytes (D7 test d).
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import math
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from hazbrief.brief import checklist, data_sources, layers, location, tevv, threat
from hazbrief.config import REPO_ROOT
from hazbrief.evidence import labels as L
from hazbrief.evidence import store as S
from hazbrief.evidence.store import read_entity, record_by


def esc(text: Any) -> str:
    return html.escape(str(text), quote=False)


def attr(text: Any) -> str:
    return html.escape(str(text), quote=True)


# ── Markdown, the subset the ICS 201 and the authors write ────────────────────────────

_IMG = re.compile(r"^!\[([^\]]*)\]\(([^)]*)\)\s*$")
_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_URL = re.compile(r"(?<![\"'>=])(https?://[^\s<]+[^\s<.,;:)\]])")


def _inline(text: str) -> str:
    out = esc(text)
    out = _CODE.sub(lambda m: f"<code>{m.group(1)}</code>", out)
    out = _BOLD.sub(lambda m: f"<strong>{m.group(1)}</strong>", out)
    out = _LINK.sub(lambda m: f'<a href="{attr(m.group(2))}">{m.group(1)}</a>', out)
    return _URL.sub(lambda m: f'<a href="{attr(m.group(1))}">{m.group(1)}</a>', out)


def markdown_html(md: str, *, image_note: str = "") -> str:
    """Headings, bullets, tables, bold, code, links and paragraphs. An image line
    becomes a note, because the brief carries no image file (the map stands for the
    sketch)."""
    out: list[str] = []
    lines = md.split("\n")
    i = 0
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        if not s:
            i += 1
            continue
        m = re.match(r"^(#{1,6}) (.*)$", s)
        if m:
            level = min(len(m.group(1)) + 1, 6)
            out.append(f"<h{level}>{_inline(m.group(2))}</h{level}>")
            i += 1
            continue
        img = _IMG.match(s)
        if img:
            note = image_note or f"Image not included: {img.group(1)}"
            out.append(f'<p class="note">{esc(note)}</p>')
            i += 1
            continue
        if s.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(lines[i].strip())
                i += 1
            out.append(_table(rows))
            continue
        if s.startswith("- "):
            items = []
            while i < len(lines) and lines[i].strip().startswith("- "):
                items.append(f"<li>{_inline(lines[i].strip()[2:])}</li>")
                i += 1
            out.append("<ul>" + "".join(items) + "</ul>")
            continue
        para = []
        while (
            i < len(lines)
            and lines[i].strip()
            and not re.match(r"^(#{1,6} |- |\||!\[)", lines[i].strip())
        ):
            para.append(lines[i].strip())
            i += 1
        out.append(f"<p>{_inline(' '.join(para))}</p>")
    return "\n".join(out)


def _cells(row: str) -> list[str]:
    body = row.strip().strip("|")
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", body)]


def _table(rows: list[str]) -> str:
    head, *rest = rows
    if rest and re.fullmatch(r"\|?[\s:|-]+\|?", rest[0]):
        rest = rest[1:]
    th = "".join(f"<th>{_inline(c)}</th>" for c in _cells(head))
    body = "".join(
        "<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in _cells(r)) + "</tr>"
        for r in rest
    )
    return f"<table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>"


# ── labels
# ─────────────────────────────────────────────────────────────────────────────


def labels_html(labels: list[dict], tz: str) -> str:
    """The sources line a rendered section ends with."""
    n = L.config()["hash_prefix_chars"]
    parts = []
    for lab in labels:
        for s in lab["sources"]:
            if s["provenance_class"] == "caller_supplied":
                parts.append(f"{esc(s['parameter'])} as given by the requester")
                continue
            phrase = L.source_phrase(
                s, tz, esc=esc, stale='<span class="stale">{}</span>'
            )
            parts.append(f"{esc(s['name'])}, {phrase}")
        parts.append(f"record <code>{esc(lab['hash'][:n])}</code>")
    return f'<p class="sources">Sources: {"; ".join(parts)}.</p>'


# ── the sections ──────────────────────────────────────────────────────────────────────


def _payload(brief, channel: str) -> Any:
    return brief.channels[channel].get("payload")


def _kv(rows: list[tuple[str, Any]]) -> str:
    body = "".join(
        f"<tr><th>{esc(k)}</th><td>{_inline(str(v))}</td></tr>"
        for k, v in rows
        if v not in (None, "")
    )
    return f'<table class="kv"><tbody>{body}</tbody></table>'


def _roads(brief, page) -> dict | None:
    """The TIGERweb roads image build_ics_201 read (an entity its record `used`), as a
    data URI with its frame in latitude and longitude, or None before the ICS 201
    lands."""
    rec = brief.channels["build_ics_201"].get("record")
    if not rec:
        return None
    for sha in rec["used"]:
        for st in brief.stores:
            try:
                urec = record_by(st, sha, rec["activity"]["startedAtTime"])
            except FileNotFoundError:
                continue
            url = urec["activity"]["params"].get("url", "")
            if page["roads_export_path"] not in url:
                continue
            if urec["entity"]["encoding"] != "bytes":
                continue
            q = parse_qs(urlsplit(url).query)
            if q.get("bboxSR") != ["3857"]:
                raise ValueError(f"roads image {sha[:12]} is not in EPSG:3857: {url}")
            x0, y0, x1, y1 = (float(v) for v in q["bbox"][0].split(","))
            png = base64.b64encode(read_entity(st, sha)).decode("ascii")
            return {
                "sha": sha,
                "src": f"data:{urec['entity']['media_type']};base64,{png}",
                "bounds": [_lat_lon(x0, y0), _lat_lon(x1, y1)],
            }
    return None


def _lat_lon(x: float, y: float) -> list[float]:
    """Web Mercator (EPSG:3857) metres to [latitude, longitude], on the sphere of radius
    6,378,137 m the projection is defined on (EPSG Guidance Note 7-2, 1.3.3.2)."""
    r = 6378137.0
    lon = math.degrees(x / r)
    lat = math.degrees(2 * math.atan(math.exp(y / r)) - math.pi / 2)
    return [round(lat, 6), round(lon, 6)]


def _script_text(text: str) -> str:
    """JSON inside a <script> element: its text is not entity-decoded, so it is not
    HTML-escaped; only a closing tag inside it is broken (`<\\/`)."""
    return text.replace("</", "<\\/")


def _material_name(material: dict) -> str:
    names = material.get("names") or []
    return names[0] if names else ""


def _fire_row(guide: str | None, cfg) -> tuple[str, str | None]:
    """The ERG fire isolation row (HB-129 Part A step 2): the guide's distance, its tag
    and page, and its own fire paragraph quoted; empty (not printed) where the guide
    prints no fire isolation distance or the footprint names no guide."""
    from hazbrief.brief import erg_fire

    spec = cfg["sections"]["footprint"]
    got = erg_fire.fire_isolation(guide) if guide else None
    return (spec["fire_row"], spec["fire_line"].format(**got) if got else None)


def _brief_wind(brief) -> dict | None:
    """The wind every line and arrow on the page prints (HB-133): the brief's one
    record once resolved, else the footprint's own wind."""
    from hazbrief.brief import derive

    return derive.brief_wind(
        brief, _payload(brief, "protective_action_footprint") or {}
    )


def wind_source_label(brief, cfg, w: dict | None = None) -> str:
    """The wind's source as the first screen prints it (HB-139; DN-019 ADDENDUM-01
    section 1): the brief's one record in the addendum's form ("forecast, NWS cell ...",
    "observed, ...", "stated: notional, ..."), once resolved; else the wind's own source
    and as-of (a brief built by a test harness)."""
    from hazbrief.brief import wind_record

    tz = brief.time_zone
    rec = getattr(brief, "wind_record", None)
    if getattr(brief, "wind_resolved", False) and rec is not None:
        return wind_record.label(rec, cfg, lambda iso: L.when(iso, tz))
    w = w or {}
    return cfg["page"]["wind_unlabelled"].format(
        source=w.get("source"),
        as_of=L.when(w["as_of"], tz) if w.get("as_of") else "unknown",
    )


def _footprint(brief, cfg) -> str:
    fp = _payload(brief, "protective_action_footprint")
    zones = fp.get("zones") or {}
    iz = (zones.get("initial_isolation_zone") or {}).get("distance") or {}
    pz = zones.get("protective_action_zone") or {}
    wind = fp.get("wind") or {}
    mat = fp.get("material") or {}
    guide = fp.get("guide") or {}
    rows = [
        ("Material", f"{_material_name(mat)} ({mat.get('id_number', '')})"),
        ("ERG guide", f"{guide.get('number', '')} {guide.get('title', '')}".strip()),
        ("Initial isolation zone", iz.get("text")),
        ("Protective action zone", ((pz.get("distance") or {}).get("text"))),
        _fire_row(guide.get("number"), cfg),
        ("Shape", pz.get("shape")),
        ("Day or night", (fp.get("day_night") or {}).get("word")),
        (
            "Wind",
            f"{wind.get('speed_kmh')} km/h from the "
            f"{wind.get('direction_from_compass')}"
            f" ({wind.get('band_label')}), {wind.get('source')}"
            if wind
            else None,
        ),
        (
            "Table",
            pz.get("tag") or (zones.get("initial_isolation_zone") or {}).get("tag"),
        ),
    ]
    return _kv(rows)


def _flags(brief, cfg) -> str:
    """The flags the briefing prints (`flags.briefing.rule_ids`, at most ten, high
    first, hazbrief.flags.for_briefing), from `flags.all`; the count withheld beside
    them."""
    flags = _payload(brief, "protective_action_footprint").get("flags") or {}
    by_id = {f["rule_id"]: f for f in flags.get("all") or []}
    shown = [by_id[r] for r in (flags.get("briefing") or {}).get("rule_ids") or []]
    if not shown:
        return "<p>No flag holds for this incident.</p>"
    items = "".join(
        f'<li><span class="prio prio-{attr(f.get("priority"))}">'
        f"{esc(f.get('priority'))}</span> {_inline(f.get('sentence', ''))} "
        f"<code>{esc(f.get('rule_id'))}</code></li>"
        for f in shown
    )
    withheld = (flags.get("briefing") or {}).get("withheld") or 0
    more = (
        f'<p class="note">{withheld} more flags are withheld.</p>' if withheld else ""
    )
    return f"<ul>{items}</ul>{more}"


def _population(brief, cfg) -> str:
    p = _payload(brief, "population_at_risk")
    night = p.get("nighttime") or {}
    day = p.get("daytime") or {}
    rows = [
        ("Residents (nighttime)", f"{night.get('total')} [{night.get('vintage', '')}]"),
        ("Workers (daytime)", f"{day.get('workers')} [{day.get('vintage', '')}]"),
        ("Primary count", p.get("primary_count")),
    ]
    for key, c in (p.get("characteristics") or {}).items():
        moe = c.get("moe")
        val = f"{c.get('estimate')}" + (
            f" (margin of error {moe})" if moe is not None else ""
        )
        rows.append((key.replace("_", " ").capitalize(), val))
    res = p.get("resilience") or {}
    if res:
        rows.append(
            (
                "Three or more components of social vulnerability",
                f"{res.get('count')} of {res.get('universe')} "
                f"({res.get('rate')} percent)",
            )
        )
    note = f'<p class="note">{esc(p["notice"])}</p>' if p.get("notice") else ""
    # HB-157 item 7: the second figure, under the modelled area, beside the ERG's and
    # never merged with it; absent (no line) where no modelled layer is drawn
    fig = layers.modelled_figure(layers._Ctx(brief, cfg))
    modelled = f'<p class="note" id="modelled-population">{esc(fig)}</p>' if fig else ""
    return _kv(rows) + note + modelled


def _facilities(brief, cfg) -> str:
    """The counts by category; a category whose query failed prints "not available"
    with its source and the error's class, never a count (HB-114 step 5a.1)."""
    f = _payload(brief, "facilities_in_footprint")
    spec = cfg["sections"]["facilities"]
    counts = f.get("counts") or {}
    errors = f.get("errors") or []
    rows = []
    for k, v in counts.items():
        if v is None and errors:
            v = _not_available(k, errors, spec)
        rows.append((k.replace("_", " ").capitalize(), v))
    named = []
    for kind in ("schools", "hospitals", "nursing_homes", "emergency_services"):
        for it in f.get(kind) or []:
            named.append(
                f"<li>{esc(it.get('name'))}, {esc(it.get('type', kind))}, "
                f"{esc(str(it.get('zone')).replace('_', ' '))} zone</li>"
            )
    # HB-142R ADDENDUM-01 section 2: the inside list, headed as the places to warn,
    # then the nearest services outside, headed as the ones that respond
    lst = (
        f"<ul>{''.join(named)}</ul>" if named else f"<p>{esc(spec['inside_none'])}.</p>"
    )
    inside = f"<h3>{esc(spec['inside_heading'])}</h3>" + lst
    return (
        f'<p class="note">{esc(spec["why_line"])}</p>'
        + _kv(rows)
        + inside
        + _nearby_html(brief, cfg)
    )


def _nearby_row(cfg, cls: str, r: dict) -> str:
    """One service's table row; `data-area-m` is its distance, which the reader's Area
    radius steps filter by (HB-155 ADDENDUM-01 item 6)."""
    titles = cfg["derive"]["nearby"]["classes"]
    t = r.get("travel") or {}
    travel = (
        f"{t['minutes']:g} min"
        + (" (route crosses the footprint)" if t.get("crosses_footprint") else "")
        if t.get("minutes") is not None
        else ""
    )
    cells = (
        titles[cls]["title"],
        r.get("name"),
        f"{r['distance_m'] / 1000:,.1f} km",
        f"{r['bearing_deg']}° ({layers.compass(r['bearing_deg'])})",
        travel,
    )
    return (
        f'<tr data-cls="{esc(cls)}" data-area-m="{r["distance_m"]}">'
        + "".join(f"<td>{esc(x)}</td>" for x in cells)
        + "</tr>"
    )


def _nearby_html(brief, cfg) -> str:
    """The services in the area (HB-142R item 1; HB-155 ADDENDUM-01 item 5): per class,
    its count within the area radius, the nearest `listed_per_class` and a "Show all N"
    line that opens the rest (the kept and, beyond the radius, those in hand for the
    reader's wider steps), each with its distance, bearing and free-flow time; a class
    whose source is not held says why; then the routes to the suggested points."""
    spec = cfg["sections"]["facilities"]
    nspec = cfg["derive"]["nearby"]
    d = (brief.derived or {}).get("nearby")
    head = f"<h3>{esc(spec['outside_heading'])}</h3>"
    if d is None:
        return head + '<p class="degraded">Not derived.</p>'
    if d.get("reason"):
        why = spec["outside_not_derived"].format(why=d["reason"])
        return head + f'<p class="degraded">{esc(why)}</p>'
    titles = nspec["classes"]
    n = int(d.get("listed_per_class") or nspec["listed_per_class"])
    cols = ("Service", "Name", "Distance", "Bearing from the incident", "Travel time")
    th = "<tr>" + "".join(f"<th>{esc(x)}</th>" for x in cols) + "</tr>"
    km = f"{d['radius_m'] / 1000:,.1f} km"
    out = [head]
    any_rows = False
    for cls, items in (d.get("classes") or {}).items():
        rest = list(items[n:]) + list((d.get("beyond") or {}).get(cls) or [])
        if not items and not rest:
            continue
        any_rows = True
        count = nspec["count_line"].format(
            n=sum(1 for r in items if r["distance_m"] <= d["radius_m"]), radius=km
        )
        block = [
            f'<p class="nearby-class" data-cls="{esc(cls)}"><strong>'
            f"{esc(titles[cls]['title'])}</strong>: {esc(count)}</p>",
            f'<table class="derived" data-cls="{esc(cls)}">{th}'
            + "".join(_nearby_row(cfg, cls, r) for r in items[:n])
            + "</table>",
        ]
        if rest:
            block.append(
                f'<details class="show-all" data-cls="{esc(cls)}"><summary>'
                f"{esc(nspec['show_all'].format(n=len(items) + len(rest)))}</summary>"
                f'<table class="derived">{th}'
                + "".join(_nearby_row(cfg, cls, r) for r in rest)
                + "</table></details>"
            )
        out += block
    for w, why in (
        ("Fire, EMS and police", d.get("stations_reason")),
        ("Hospitals", d.get("hospitals_reason")),
        ("Travel time", d.get("travel_reason")),
    ):
        if why:
            out.append(f'<p class="degraded">{esc(w)}: not derived: {esc(why)}</p>')
    out += _widened_lines(d, cfg)
    if not any_rows and not (d.get("stations_reason") and d.get("hospitals_reason")):
        out.append("<p>None within the radius outside the footprint.</p>")
    # HB-157 item 14 (HB-155 ADDENDUM-04 item 2): the earliest modelled arrival at the
    # nearest listed service and at the suggested points
    arrival = layers.arrival_line(layers._Ctx(brief, cfg))
    if arrival:
        out.append(f'<p class="note" id="arrival-line">{esc(arrival)}</p>')
    line = d["label"]
    if any_rows:
        line += f"; travel: {d['travel_label']}"
    out.append(f'<p class="label">{esc(line)}</p>')
    out.append(_routes_html(brief, cfg))
    return "".join(out)


def _routes_html(brief, cfg) -> str:
    """HB-155 item 9 (ADDENDUM-05 item 5): the routes to the suggested points, one line
    each that opens (its connectors, its directions link built from the coordinates
    alone, its label); "free-flow, assumed speeds; no live traffic" is in each row's
    detail, never a paragraph at first open."""
    d = (brief.derived or {}).get("siting")
    spec = cfg["derive"]["siting"]["routes"]
    head = '<h3 id="siting-routes">Routes to the suggested points</h3>'
    if not d:
        return ""
    if d.get("reason") and not d.get("routes"):
        return head + f'<p class="degraded">{esc(d["reason"])}</p>'
    rows = []
    for r in d.get("routes") or []:
        detail = [
            f"<p>{esc(spec['label'])}.</p>",
            f"<p>{esc(spec['about'])}</p>",
        ]
        if r.get("minutes") is not None:
            detail.insert(0, f"<p>Connectors {r['connector_m']:,} m in all.</p>")
        detail.append(
            f'<p><a href="{esc(r["directions"])}" target="_blank" rel="noopener">'
            f"{esc(spec['directions'])}</a></p>"
        )
        rows.append(
            f'<details class="lrow route" data-from="{esc(r["from"])}" '
            f'data-to="{esc(r["to"])}"><summary>{esc(r["text"])}</summary>'
            + "".join(detail)
            + "</details>"
        )
    return head + "".join(rows)


def _widened_lines(d: dict, cfg) -> list[str]:
    """HB-155 ADDENDUM-01 item 3 (HB-151's pattern): a line per class with none inside
    the area radius, naming the distance it widened to, or the ceiling it reached with
    none. A class whose source is not held has its not-derived line instead."""
    spec = cfg["derive"]["nearby"]
    held = {
        cls: not (
            d.get("hospitals_reason") if cls == "hospital" else d.get("stations_reason")
        )
        for cls in spec["classes"]
    }
    km = "{:,.1f} km".format
    out = []
    for cls, s in (d.get("search") or {}).items():
        if not held.get(cls) or not s.get("widened"):
            continue
        title = spec["classes"][cls]["title"]
        if s.get("ceiling"):
            words = spec["ceiling_line"].format(
                title=title, ceiling=km(d["ceiling_m"] / 1000)
            )
        else:
            words = spec["widened_line"].format(
                title=title,
                radius=km(d["radius_m"] / 1000),
                widened=km(s["radius_m"] / 1000),
            )
        out.append(f"<p>{esc(words)}</p>")
    return out


def _not_available(category: str, errors: list[dict], spec: dict) -> str:
    """A failed category's line: the source the tool names for it (`category_source`)
    and each of that source's errors by class (`error_classes`: the message's opening
    words; an unlisted message is printed as the tool sanitized it)."""
    source = spec["category_source"][category]
    classes = []
    for e in errors:
        if e.get("source") != source:
            continue
        msg = str(e.get("error") or "")
        cls = next(
            (c["class"] for c in spec["error_classes"] if msg.startswith(c["starts"])),
            msg.rstrip("."),
        )
        if cls not in classes:
            classes.append(cls)
    return spec["not_available"].format(
        source=source, why="; ".join(classes) or spec["no_error_named"]
    )


def _hospitals(brief, cfg) -> str:
    r = _payload(brief, "receiving_hospitals")
    hs = (r.get("hospitals") or [])[: cfg["page"]["hospitals_shown"]]
    if not hs:
        return "<p>No receiving hospital within the search distance.</p>"
    head = (
        "<tr><th>Hospital</th><th>Distance</th><th>Direction</th><th>Beds</th>"
        "<th>Route crosses the footprint</th></tr>"
    )
    body = "".join(
        f"<tr><td>{esc(h.get('name'))}</td><td>{esc(h.get('distance_km'))} km</td>"
        f"<td>{esc(h.get('direction'))}</td><td>{esc(h.get('beds'))}</td>"
        f"<td>{'yes' if h.get('crosses_footprint') else 'no'}</td></tr>"
        for h in hs
    )
    return f"<table><thead>{head}</thead><tbody>{body}</tbody></table>"


def _narrative(brief, cfg, author, name: str) -> str:
    payloads = {c: _payload(brief, c) for c in cfg["sections"][name]["channels"]}
    # the records' labels, which a model-backed author reads beside the payloads
    # (HB-131R item 4); `NoAuthor` reads neither
    ctx: dict[str, Any] = {"labels": brief.sections[name]["labels"]}
    if name == "ics201":
        ctx["ics201_markdown"] = _ics201_labelled(brief, cfg)[0]
    md = author.write(name, payloads, **ctx)
    if md is None:
        return "<p>No text for this section.</p>"
    # the form's own title is the section's heading already
    first, _, rest = md.partition("\n")
    if first.strip() == f"# {cfg['sections'][name]['title']}":
        md = rest
    return markdown_html(md, image_note=ICS201_IMAGE_NOTE)


ICS201_IMAGE_NOTE = (
    "Block 4's sketch is not included here; the map at the top of this brief draws "
    "the same footprint."
)
APPENDIX_MARK = "\n## Evidence appendix"


def _ics201_labelled(brief, cfg) -> tuple[str, str]:
    """(the ICS 201 with each block's labels, its evidence appendix): `render_ics201`
    over the brief's channel records, a degraded tool's label in its place."""
    recs = [
        brief.channels[c]["record"]
        for c in cfg["channels"]
        if brief.channels[c].get("record")
    ]
    unavailable = {
        c: brief.sections[s]["reason"]
        for s, spec in cfg["sections"].items()
        for c in spec["channels"]
        if brief.sections[s]["state"] == "degraded"
        and not brief.channels[c].get("record")
    }
    md = L.render_ics201(
        _payload(brief, "build_ics_201"),
        recs,
        brief.now,
        stores=brief.stores,
        tz=brief.time_zone,
        unavailable=unavailable,
    )
    form, _, appendix = md.partition(APPENDIX_MARK)
    return form, appendix


def report_html(brief, cfg, author, checks: list[dict] | None = None) -> str:
    """The commander's report (DN-022 sections 2 and 4; HB-131R item 3): the ICS 201
    section as the page prints it, from the same blackboard and author, then its
    evidence appendix, in their own panel. The live page's print view prints this and
    nothing else. A degraded ICS 201 is its DN-011 D2 label.

    `checks` is the live page's checklist (`checklist.items` over the run's stream;
    HB-141): its first line counts the unticked Verify items, and the "Operator checks"
    annex lists every check and uncheck with its time. None: the static page's annex."""
    sec = brief.sections["ics201"]
    title = cfg["sections"]["ics201"]["title"]
    head = f'<h2 class="report-title">{esc(title)}</h2>'
    if checks is not None:
        unticked, total = checklist.unticked_verify(checks)
        first = cfg["checklist"]["report_first"].format(unticked=unticked, total=total)
        head = f'<p class="report-first">{esc(first)}</p>{head}'
    if sec["state"] == "pending":
        return head + '<p class="pending">The ICS 201 has not settled.</p>'
    if sec["state"] == "degraded" and not sec.get("partial"):
        return head + f'<p class="degraded">{esc(sec["reason"])}</p>'
    form = _narrative(brief, cfg, author, "ics201")
    # the load read's cuts to the ICS 201 section, made again here, so the report
    # prints what the section prints (HB-132R ADDENDUM-01 section 3)
    if getattr(brief, "load_read", None):
        from hazbrief.brief import load_read

        form = load_read.apply_cuts(form, brief.load_read["applied"], "ics201")
    form += siting_annex_html(brief, cfg)
    form += checklist.annex_html(cfg, checks, brief.time_zone)
    _, appendix = _ics201_labelled(brief, cfg)
    # HB-154 item 9: every MCP server and public source, with its outcome; after the
    # form, whose text stays the ICS 201 section's (HB-132R ADDENDUM-01 section 3)
    return (
        f'{head}<div class="report-form">{form}</div>'
        f"{labels_html(sec['labels'], brief.time_zone)}"
        f"{data_sources.annex_html(brief, cfg)}"
        '<div class="report-appendix"><h2>Evidence appendix</h2>'
        f"{markdown_html(appendix)}</div>"
    )


def siting_annex_html(brief, cfg) -> str:
    """HB-155 item 9: the ICS 201's map sketch and resources annex for the suggested
    points: each point, its place and its distance and bearing, named as suggested (the
    incident commander sets it); the routes to them with their drive times. The form is
    the server's (Block 4's sketch, the resources); this annex is the application's,
    after it. Empty where no point was suggested."""
    d = (brief.derived or {}).get("siting") or {}
    pts = [p for p in (d.get("points") or {}).values() if p]
    if not pts:
        return ""
    spec = cfg["derive"]["siting"]
    rows = "".join(
        f"<li>{esc(p['title'])}: {esc(p['name'])}, {esc(p['where'])}</li>" for p in pts
    )
    routes = "".join(f"<li>{esc(r['text'])}</li>" for r in d.get("routes") or [])
    return (
        '<div class="siting-annex"><h3>Map sketch and resources: the suggested '
        "points</h3>"
        f"<p>{esc(spec['words']['suggested'].capitalize())}. Each is a suggestion "
        "by the "
        "rules of DN-023, not on Block 4's sketch.</p>"
        f"<ul>{rows}</ul>"
        + (
            f"<p>Routes ({esc(spec['routes']['label'])}):</p><ul>{routes}</ul>"
            if routes
            else ""
        )
        + "</div>"
    )


SECTION_BODY = {
    "footprint": _footprint,
    "flags": _flags,
    "population": _population,
    "facilities": _facilities,
    "hospitals": _hospitals,
}


def section_state(brief, name: str) -> str:
    """rendered, degraded, pending, or stale (rendered, with a stale source)."""
    sec = brief.sections[name]
    if sec["state"] == "rendered" and any(lab["stale"] for lab in sec["labels"]):
        return "stale"
    return sec["state"]


def state_mark(
    cfg, key: str, *, time: str = "", date: str = "", glyph_only: bool = False
) -> str:
    """One of the three states (HB-158 ADDENDUM-01 item 2; `page.states`), as the page
    prints it: its shape, then its words (`glyph_only`: the words for a screen reader
    only, where the line beside the mark says the rest). `key` is retrieving,
    retrieved, recorded (a replay's retrieved) or failed; `data-state` carries the
    key, the class the shape's colour."""
    st = cfg["page"]["states"][key]
    words = st["words"].format(time=time, date=date).strip()
    cls = "retrieved" if key == "recorded" else key
    said = f'<span class="vh">{esc(words)}</span>' if glyph_only else esc(words)
    return (
        f'<span class="st st-{cls}" data-state="{attr(key)}">'
        f'<span class="mk" aria-hidden="true">{esc(st["glyph"])}</span> '
        f"{said}</span>"
    )


def _channel_ended(brief, channels) -> str | None:
    """The latest end time of the records of `channels` (the call's `endedAtTime`), or
    None when none has a record."""
    got = [
        ((brief.channels.get(c) or {}).get("record") or {})
        .get("activity", {})
        .get("endedAtTime")
        for c in channels
    ]
    got = [t for t in got if t]
    return max(got, key=S.parse_time) if got else None


def three_state(brief, cfg, channels, state: str) -> tuple[str, str, str]:
    """A section's or a channel's state as one of the three (`page.section_states`),
    with its time: (key, time, date). Retrieved takes the latest call end of
    `channels`, its date and time. The page is a function of the records (DN-011
    D7): a live build and its replay print the same bytes, so the fragment always
    reads "Retrieved <date time>"; a served replay's page relabels it "Recorded
    <date>" in the browser (`static/shell.js` `hbRecorded`)."""
    key = cfg["page"]["section_states"][state]
    if key != "retrieved":
        return key, "", ""
    ended = _channel_ended(brief, channels)
    stamp = L.when(ended, brief.time_zone) if ended else ""
    return "retrieved", stamp[:16], stamp[:10]


def section_mark(brief, cfg, name: str) -> str:
    """The state mark a section's summary and the static page's chip print."""
    key, t, d = three_state(
        brief, cfg, cfg["sections"][name]["channels"], section_state(brief, name)
    )
    return state_mark(cfg, key, time=t, date=d)


def pending_section_html(cfg, name: str) -> str:
    """A section below the map before it settles: what it waits for (the first paint,
    and the live page's empty section list, HB-130R step 4)."""
    spec = cfg["sections"][name]
    waits = ", ".join(c.replace("_", " ") for c in spec["channels"])
    return (
        f'<section class="pending" id="section-{attr(name)}">'
        f"<details><summary><h2>{esc(spec['title'])}</h2> "
        f"{state_mark(cfg, 'retrieving')}</summary>"
        f'<p class="pending">Waiting for {esc(waits)}.</p></details></section>'
    )


def section_html(brief, cfg, author, name: str) -> str:
    """A section below the map: collapsed (`<details>`, closed), unchanged inside. The
    map section is the workbench, the first screen."""
    if name == "map":
        return _workbench(brief, cfg)
    sec = brief.sections[name]
    spec = cfg["sections"][name]
    if sec["state"] == "pending":
        return pending_section_html(cfg, name)
    elif sec["state"] == "degraded" and sec.get("partial"):
        # answered in part (HB-114 step 5a.1): why first, then what did answer
        fn = SECTION_BODY.get(name)
        body = f'<p class="degraded">{esc(sec["reason"])}</p>'
        body += fn(brief, cfg) if fn else _narrative(brief, cfg, author, name)
        body += labels_html(sec["labels"], brief.time_zone)
    elif sec["state"] == "degraded":
        body = f'<p class="degraded">{esc(sec["reason"])}</p>'
    else:
        fn = SECTION_BODY.get(name)
        body = fn(brief, cfg) if fn else _narrative(brief, cfg, author, name)
        if name == "ics201":
            # HB-155 item 9: the suggested points beside the form's map sketch and
            # resources (the form is the server's; the annex is the application's)
            body += siting_annex_html(brief, cfg)
            # the "Operator checks" annex (HB-141; HBD-218): no check is recorded in
            # a render, so the static page's annex says where they are
            body += checklist.annex_html(cfg, None, brief.time_zone)
        body += labels_html(sec["labels"], brief.time_zone)
    return (
        f'<section class="{attr(sec["state"])}" id="section-{attr(name)}">'
        f"<details><summary><h2>{esc(spec['title'])}</h2> "
        f"{section_mark(brief, cfg, name)}</summary>"
        f"{body}</details></section>"
    )


# ── the workbench: the map and the first actions (HB-45) ──────────────────────────────


def _first_actions_html(brief, cfg, data: dict | None = None) -> str:
    fa = layers.first_actions(brief, cfg)
    out = ['<div id="first-actions"><h2>First actions</h2>']
    if fa.get("distances"):
        rows = "".join(
            f"<li><strong>{esc(head)}:</strong> {esc(text)}"
            + (f' <span class="q">{esc(note)}</span>' if note else "")
            + (f" <code>{esc(tag)}</code>" if tag else "")
            + "</li>"
            for head, text, note, tag in fa["distances"]
        )
        out.append(f'<ul class="dist">{rows}</ul>')
        # HB-133: the brief's one wind record, which the footprint is oriented on
        w = _brief_wind(brief) or {}
        if w.get("direction_deg_from") is not None:
            # the blackboard (DN-019 section 2 item 4; C1): the wind the footprint is
            # oriented on, with its source and as-of beside the value (HB-114 step 5),
            # the source in DN-019 ADDENDUM-01's form (HB-139)
            out.append(
                '<p class="fa-wind">'
                + esc(
                    cfg["page"]["footprint_wind_line"].format(
                        deg=w["direction_deg_from"],
                        kmh=w.get("speed_kmh"),
                        label=wind_source_label(brief, cfg, w),
                    )
                )
                + "</p>"
            )
            unused = (getattr(brief, "wind_record", None) or {}).get("unused")
            if unused:
                out.append(f'<p class="pl fa-wind-unused">{esc(unused)}</p>')
            # HB-143: under the observed source, every station read and, below the
            # minimum, why the forecast cell is the wind instead
            from hazbrief.brief import wind_record as _wr

            tz = getattr(brief, "time_zone", None)
            for css, text in _wr.observed_lines(
                getattr(brief, "wind_record", None), cfg, lambda iso: L.when(iso, tz)
            ):
                out.append(f'<p class="{css}">{esc(text)}</p>')
        # a scenario file that set the weather source says so, with its basis
        # (DN-019 ADDENDUM-01 section 1: never silently; HB-139 item 4)
        sel = getattr(brief, "weather", None) or {}
        if sel.get("set_by") == "scenario":
            line = cfg["wind_record"]["fixture_basis"].format(
                source=sel["source"], basis=sel.get("basis")
            )
            out.append(f'<p class="pl fa-wind-basis">{esc(line)}</p>')
        out.append(f'<p class="pl">{esc(fa["distances_label"])}</p>')
    if fa.get("distances_missing"):
        out.append(
            '<p class="degraded">Distances not held: '
            f"{esc(fa['distances_missing'])}</p>"
        )
    # the operator cue block sits under the distances and above the guide's lines, so
    # it is on the first screen (HB-115: placed after the guide's lines, it fell below
    # the fold of a 1440 x 900 window)
    if data is not None:
        out.append(_cue_block_html(brief, cfg, data))
    g = fa.get("guide")
    if g:
        out.append(
            f"<h3>Guide {esc(g.get('number'))}, {esc(g.get('title'))}: "
            "public safety</h3>"
        )
        items = []
        for kind, text, page in fa["lines"]:
            if kind == "heading":
                items.append(f'<li class="h">{esc(text)}</li>')
            else:
                items.append(
                    f'<li>{esc(text)} <span class="pg">p. {esc(page)}</span></li>'
                )
        if items:
            out.append(f'<ul class="guide">{"".join(items)}</ul>')
            out.append(f'<p class="pl">{esc(fa["guide_label"])}</p>')
    if fa.get("guide_missing"):
        out.append(
            f'<p class="degraded">Guide lines not held: {esc(fa["guide_missing"])}</p>'
        )
    out.append("</div>")
    return "".join(out)


def _cue_block_html(brief, cfg, data: dict) -> str:
    """The operator cue block (HB-115 ADDENDUM-01 section 2): "Before you act on this",
    at most six signal lines with their receipts, open when `map.defaults.cue_block`
    is on; nothing when no signal holds on this brief."""
    rows = layers.cue_lines(brief, cfg, data)
    if not rows:
        return ""
    spec = cfg["map"]["cue_block"]
    opened = " open" if layers.default_on(cfg, "cue_block") else ""
    # HB-161 ADDENDUM-02 item 1: a line whose document names a tool hazbrief does not
    # run cites it on the TEVV page; its receipt here is the section's number
    items = "".join(
        f'<li>{esc(r["text"])} <span class="pg">'
        + (tevv.link_html(cfg, r["tevv"]) if r.get("tevv") else esc(r["receipt"]))
        + "</span></li>"
        for r in rows
    )
    return (
        f'<details id="cue-block"{opened}><summary><h2>{esc(spec["heading"])}</h2>'
        f'</summary><ul class="cue">{items}</ul></details>'
    )


def _derived_tables_html(brief, cfg) -> str:
    """The roadblock candidates (roads, then rail) and the downstream path as tables
    (DN-015 sections 2 and 3; HB-54), after the first actions: the map's two layers as
    rows, each with its label line. A derivation with nothing to list says why."""
    d = brief.derived or {}
    out = ['<div id="derived">']
    roads, rail, down = d.get("roads"), d.get("rail"), d.get("downstream")
    out.append("<h2>Roadblock candidates</h2>")
    for name, part, cols in (
        (
            "road",
            roads,
            ("Road", "Class", "Zone boundary", "Bearing", "Lat, lon", "Offset"),
        ),
        (
            "rail",
            rail,
            ("Rail line", "FRA arc", "Zone boundary", "Bearing", "Lat, lon"),
        ),
    ):
        if part is None:
            out.append(f'<p class="degraded">Not derived: {name} crossings.</p>')
            continue
        rows = []
        for k in part.get("candidates") or []:
            first = (
                (k.get("road"), k.get("mtfcc"))
                if name == "road"
                else (
                    " ".join(x for x in (k.get("owner"), k.get("subdivision")) if x),
                    k.get("fra_arc"),
                )
            )
            bearing = f"{k['bearing_deg']}°" if k.get("bearing_deg") is not None else ""
            lon, lat = k["coordinates"]
            cells = (*first, layers._zone_text(k["zone"]), bearing, f"{lat}, {lon}")
            if name == "road":
                # HB-142R item 4: the candidate's offset from its crossing
                cells = (
                    *cells,
                    f"{k['offset_m']:,.0f} m ({k['offset_rule'].replace('_', ' ')})"
                    if "offset_rule" in k
                    else "at the crossing (not computed)",
                )
            rows.append("<tr>" + "".join(f"<td>{esc(x)}</td>" for x in cells) + "</tr>")
        if rows:
            head = "".join(f"<th>{esc(x)}</th>" for x in cols)
            out.append(f'<table class="derived"><tr>{head}</tr>{"".join(rows)}</table>')
        else:
            out.append(
                f'<p class="degraded">No {name} candidate: '
                f"{esc(part.get('reason'))}</p>"
            )
        if part.get("label"):
            line = f"{part['label']}; crossings within {part['merge_m']:g} m merged"
            if part.get("classes"):
                line += f"; classes {', '.join(part['classes'])}"
            out.append(f'<p class="pl">{esc(line)}</p>')
        if name == "road" and part.get("offset_reason"):
            # HB-142R: why these candidates sit at their crossings
            why = cfg["derive"]["roads"]["offset"]["not_computed"].format(
                why=part["offset_reason"]
            )
            out.append(f'<p class="degraded">Offset {esc(why)}</p>')
    out.append("<h2>Downstream path</h2>")
    if down is None or not down.get("path"):
        why = "the derivations have not run" if down is None else down.get("reason")
        out.append(f'<p class="degraded">Not drawn: {esc(why)}</p>')
    else:
        rows = "".join(
            "<tr>"
            + "".join(
                f"<td>{esc(x)}</td>"
                for x in (
                    i,
                    r.get("name") or "unnamed",
                    r.get("comid"),
                    r.get("id3dhp") or "",
                    f"{r['length_m']:,}",
                )
            )
            + "</tr>"
            for i, r in enumerate(down["reaches"], 1)
        )
        head = "".join(
            f"<th>{x}</th>"
            for x in ("#", "Name (3DHP)", "NHDPlus comid", "3DHP id", "Length (m)")
        )
        st = down.get("start") or {}
        km = f"{down['length_m'] / 1000:.1f}"
        out.append(
            f"<p>From {esc(st.get('name') or 'an unnamed flowline')} (3DHP "
            f"{esc(st.get('id3dhp'))}), {esc(st.get('distance_m'))} m from the spill; "
            f"{esc(km)} km drawn.</p>"
        )
        out.append(f'<table class="derived"><tr>{head}</tr>{rows}</table>')
        if down.get("reason_partial"):
            out.append(f'<p class="degraded">{esc(down["reason_partial"])}</p>')
    if down is not None and down.get("label"):
        out.append(f'<p class="pl">{esc(down["label"])}</p>')
    out.append(_terrain_html(d.get("terrain")))
    out.append(_establishments_html(d.get("establishments")))
    out.append("</div>")
    return "".join(out)


def _weather_html(brief, cfg) -> str:
    """The forecast over the response window (DN-016 section 3; HB-56): a wind strip,
    the wind the footprint is oriented on as hour 0 and each forecast hour after it,
    arrows pointing downwind; the veer/back flag; the full forecast table collapsed. The
    footprint is not re-oriented on any of it."""
    f = (brief.derived or {}).get("forecast")
    out = ["<h2>Weather over the response window</h2>"]
    if f is None:
        return out[0] + '<p class="degraded">Not derived.</p>'
    if not f.get("rows"):
        return out[0] + f'<p class="degraded">Not derived: {esc(f.get("reason"))}</p>'
    tz = brief.time_zone

    def hour(iso: str) -> str:
        return L.when(iso, tz)[11:16]

    def arrow(frm) -> str:
        if frm is None:
            return '<span class="wx-na">&ndash;</span>'
        turn = (frm + 180) % 360
        return (
            f'<span class="wx-arrow" style="transform:rotate({turn:.0f}deg)">'
            "&uarr;</span>"
        )

    obs = f.get("observed") or {}
    frm = obs.get("direction_deg_from")
    # the footprint's wind with its source and as-of in its own cell, beside the
    # value (HB-114 step 5; C1), the source in DN-019 ADDENDUM-01's form (HB-139)
    src = cfg["page"]["strip_source_line"].format(
        label=wind_source_label(brief, cfg, obs)
    )
    cells = [
        f'<td class="wx-obs">{arrow(frm)}<br>{esc(_num(obs.get("speed_kmh")))}<br>'
        f'{esc(_num(frm, 0))}&deg;<br><span class="wx-src">{esc(src)}</span></td>'
    ]
    heads = ['<th class="wx-obs">Footprint</th>']
    for r in f["rows"][1:]:
        mark = ' class="wx-erg"' if r["hour"] == math.ceil(f["erg_frame_h"]) else ""
        heads.append(f"<th{mark}>+{r['hour']} h<br>{esc(hour(r['time']))}</th>")
        cells.append(
            f"<td{mark}>{arrow(r['windDirection'])}<br>{esc(_num(r['windSpeed']))}<br>"
            f"{esc(_num(r['windDirection'], 0))}&deg;</td>"
        )
    out.append(
        f'<table class="wx-strip"><tr>{"".join(heads)}</tr>'
        f"<tr>{''.join(cells)}</tr></table>"
    )
    out.append(
        '<p class="pl">Arrows point downwind; speed in km/h; the direction is where '
        "the wind blows from. First column: the wind the footprint is oriented on "
        f"({esc(src)}). The "
        "ERG's distances were computed for exposures of at most "
        f"{f['erg_frame_h']:g} h (the marked column).</p>"
    )
    if f.get("flag"):
        out.append(f'<p class="degraded">{esc(f["flag"])}.</p>')
    else:
        out.append(
            "<p>No forecast hour turns more than "
            f"{f['veer_flag_deg']:g} degrees from the wind the footprint is oriented "
            "on.</p>"
        )
    if f.get("uncovered_hours"):
        out.append(
            f'<p class="degraded">{f["uncovered_hours"]} hour(s) of the window are '
            f"outside the forecast, valid {esc(L.when(f['valid_from'], tz))} to "
            f"{esc(L.when(f['valid_to'], tz))}; left blank.</p>"
        )
    if f.get("stale"):
        out.append(
            # HB-158 item 5: the fact the word "stale" stood for
            '<p class="stale">Past its valid time: the forecast is valid to '
            f"{esc(L.when(f['valid_to'], tz))}; it does not update by itself.</p>"
        )
    #: (heading, row key, decimals); time is printed as a time
    cols = (
        ("Hour", "hour", 0),
        ("Time", "time", None),
        ("Wind from (°)", "windDirection", 0),
        ("Speed (km/h)", "windSpeed", 1),
        ("Temperature (°C)", "temperature", 1),
        ("Sky cover (%)", "skyCover", 0),
        ("Precipitation chance (%)", "probabilityOfPrecipitation", 0),
    )
    head = "".join(f"<th>{esc(t)}</th>" for t, _, _ in cols)
    rows = "".join(
        "<tr>"
        + "".join(
            f"<td>{esc(L.when(r[k], tz) if d is None else _num(r[k], d))}</td>"
            for _, k, d in cols
        )
        + "</tr>"
        for r in f["rows"]
    )
    out.append(
        '<details class="derived"><summary>The forecast, hour by hour</summary>'
        f'<table class="derived"><tr>{head}</tr>{rows}</table></details>'
    )
    out.append(
        f'<p class="pl">{esc(f["label"])}; updated '
        f"{esc(L.when(f['update_time'], tz) if f.get('update_time') else 'unknown')}"
        + (
            f", generated {esc(L.when(f['generated_at'], tz))}"
            if f.get("generated_at")
            else ""
        )
        + f"; valid {esc(L.when(f['valid_from'], tz))} "
        f"to {esc(L.when(f['valid_to'], tz))}; "
        f"{esc(_read_counts(f.get('sources')))}</p>"
    )
    return "".join(out)


def _observation_html(brief) -> str:
    """The nearest station's latest observation (DN-016; HB-60): the station, its
    distance and elevation, the time observed as the as-of, and whether it is usable
    at the as-given time (DN-010's stale rule). Shown as data."""
    o = (brief.derived or {}).get("observation")
    out = ["<h3>Station observation</h3>"]
    if o is None:
        return out[0] + '<p class="degraded">Not derived.</p>'
    if not o.get("station"):
        return out[0] + f'<p class="degraded">Not derived: {esc(o.get("reason"))}</p>'
    tz = brief.time_zone
    when = L.when(o["observed_at"], tz)
    out.append(
        f"<p>{esc(o['station'])} ({esc(o.get('name'))}), {o['distance_km']:.1f} km "
        f"from the spill, station elevation {_num(o.get('station_elevation_m'), 0)} m; "
        f"observed {esc(when)}.</p>"
    )
    if not o["usable"]:
        out.append(
            f'<p class="degraded">Not used for the stability class: '
            f"{esc(o['stale_reason'])}.</p>"
        )
    layers = ", ".join(
        f"{x['amount']}"
        + (
            f" {round(x['base_m'] / 0.3048):,} ft"
            if x.get("base_m") is not None
            else ""
        )
        for x in o.get("cloud_layers") or []
    )
    ceiling = (
        f"{o['ceiling_ft']:,} ft"
        if o.get("ceiling_ft") is not None
        else o["ceiling_note"]
    )

    def shown(v, unit: str, places: int = 1) -> str:
        return "not reported" if v is None else f"{v:.{places}f} {unit}"

    rows = [
        ("Wind from", shown(o.get("wind_from_deg"), "degrees", 0)),
        ("Wind speed", f"{shown(o.get('wind_ms'), 'm/s')}, {o['wind_height']}"),
        ("Temperature", shown(o.get("temperature_c"), "°C")),
        ("Cloud layers", layers or "none reported"),
        ("Ceiling", ceiling),
    ]
    body = "".join(f"<tr><td>{esc(k)}</td><td>{esc(v)}</td></tr>" for k, v in rows)
    out.append(f'<table class="derived">{body}</table>')
    out.append(
        f'<p class="pl">{esc(o["label"])}; {esc(_read_counts(o.get("sources")))}</p>'
    )
    return "".join(out)


def _stability_html(brief, cfg=None) -> str:
    """The Pasquill-Gifford class and its inputs (DN-016 section 2; HB-57), in the
    weather section after the strip. This panel is the class's only reader: not on the
    map, not an input to any layer or table (DN-001 invariant 1; a test greps it)."""
    s = (brief.derived or {}).get("stability")
    out = ["<h3>Stability class (Pasquill-Gifford)</h3>"]
    if s is None:
        return out[0] + '<p class="degraded">Not derived.</p>'
    if cfg is not None and s.get("class"):
        out.append(method_ref(cfg, "stability_class"))
    tz = brief.time_zone
    if s.get("stated"):
        # HB-139: the weather source states the class; Turner's key on the held
        # inputs is printed beside it, so the reader sees both
        computed = (
            s.get("computed_class") or f"not determined ({s.get('computed_reason')})"
        )
        out.append(
            f"<p><strong>{esc(s['class'])}</strong> (stated by the weather source; "
            f"Turner's key on the inputs below gives {esc(computed)}).</p>"
        )
    elif s.get("class"):
        out.append(
            f"<p><strong>{esc(s['class'])}</strong> (net radiation index "
            f"{esc(s['net_radiation_index'])}, wind {esc(s['wind_knots'])} knots, "
            f"{esc(s['period'])} by Turner's rule: night runs from an hour before "
            "sunset to an hour after sunrise).</p>"
        )
    else:
        out.append(f'<p class="degraded">{esc(s.get("reason"))}.</p>')
    rows = []
    for i in [*(s.get("inputs") or []), *([s["ceiling"]] if s.get("ceiling") else [])]:
        v = i["value"]
        if v is None:
            shown = "not held"
        elif isinstance(v, str):  # a stated class (HB-139)
            shown = f"{v} ({i['unit']})"
        else:
            shown = f"{v:.1f} {i['unit']}"
        when = L.when(i["as_of"], tz) if i.get("as_of") else ""
        rows.append(
            "<tr>"
            + "".join(
                f"<td>{esc(x)}</td>" for x in (i["name"], shown, i["source"], when)
            )
            + "</tr>"
        )
    if rows:
        head = "".join(f"<th>{x}</th>" for x in ("Input", "Value", "Source", "As of"))
        out.append(f'<table class="derived"><tr>{head}</tr>{"".join(rows)}</table>')
    if s.get("table"):
        out.append(f'<p class="pl">{esc(s["table"])}; {esc(s["label"])}.</p>')
    return "".join(out)


def _dense_gas_html(brief, cfg) -> str:
    """The dense-gas footprint's panel (DN-020 section 3.3; HB-112), after the puff's:
    DN-020 section 3.3's label filled from the run, the client's label lines, the
    comparison with the ERG and the puff, the level of concern with its quote, and each
    source-term input with its tier beside its doc_id and page (HB-112 ADDENDUM-01);
    else the one line that says why it is not drawn. Not in the ICS 201, the export or
    the first actions."""
    spec = cfg["weather"]["dense_gas"]
    d = (brief.derived or {}).get("dense_gas")
    out = [f"<h3>{esc(spec['panel_title'])}</h3>"]
    if d is None:
        return out[0] + '<p class="degraded">Not derived.</p>'
    if d.get("label"):
        out.append(f'<p class="puff-label">{esc(d["label"])}</p>')
        if d.get("legend"):
            out.append(f"<p>{esc(d['legend'])}.</p>")
        for line in d.get("label_lines") or []:
            out.append(f'<p class="pl">{esc(line)}.</p>')
        cmp_ = d.get("comparison") or {}
        if cmp_.get("line"):
            out.append(f"<p>{esc(cmp_['line'])}.</p>")
        lvl = d.get("level") or {}
        if lvl.get("source"):
            out.append(f'<p class="pl">Level of concern from {esc(lvl["source"])}.</p>')
        w = d.get("wind") or {}
        if w:
            out.append(
                f'<p class="pl">Wind: {w["ms"]:.1f} m/s from {w["from_deg"]:.0f} '
                f"degrees, the puff's at hour 0 ({esc(w['label'])}).</p>"
            )
    elif d.get("state") == "not_applicable":
        # HB-120: the chemistry, not a degradation (DN-020 ADDENDUM-02 item 4); the
        # reason is the routing table's sentence and ends with its own full stop
        out.append(f"<p>{esc(spec['not_applicable'].format(reason=d['reason']))}</p>")
    else:
        what = d.get("reason") or "not drawn"
        out.append(
            f'<p class="degraded">{esc(spec["not_drawn"].format(what=what))}.</p>'
        )
        if d.get("hint"):
            out.append(f'<p class="pl">{esc(d["hint"])}.</p>')
    rows = d.get("tier_rows") or []
    if rows:
        head = "".join(
            f"<th>{x}</th>"
            for x in ("Source-term input", "SLAB", "Value", "Tier; source")
        )
        body = "".join(
            "<tr>"
            + "".join(
                f"<td>{esc(r[k])}</td>"
                for k in ("name", "slab", "value", "tier_source")
            )
            + "</tr>"
            for r in rows
        )
        out.append(f'<table class="derived"><tr>{head}</tr>{body}</table>')
    if d.get("tier_sentence"):
        out.append(f'<p class="pl">{esc(d["tier_sentence"])}.</p>')
    ev = d.get("evidence") or {}
    if ev.get("sha256"):
        # the sentence follows the channel's state (HB-114 step 5a.2; Issue 6367111e):
        # only a drawn footprint has a deck and SLAB's output hash in its record
        n = L.config()["hash_prefix_chars"]
        if d.get("label"):
            what = spec["run_record_drawn"]
        elif d.get("state") == "not_applicable":
            what = spec["run_record_state"].format(
                state=spec["not_applicable"].format(reason=d["reason"]).rstrip(".")
            )
        else:
            what = spec["run_record_state"].format(
                state=spec["not_drawn"].format(what=d.get("reason") or "not drawn")
            )
        out.append(
            f'<p class="pl">Run record <code>{esc(ev["sha256"][:n])}</code> '
            f"({esc(what)}).</p>"
        )
    return "".join(out)


def _smoke_html(brief, cfg) -> str:
    """The smoke layer's panel (DN-021; HB-129), on a fire brief only (a scenario with
    a `fire` block); empty on every other brief. While VSMOKE is not built it prints the
    client's refusal lines and hint (vsmoke.yaml's words), the fire block's own note,
    the one line that the overlay and the message block follow the bands, and the
    PLACES label once (HB-129 ADDENDUM-01 sections 2 and 3). No text of the renderer's
    own beyond the configured title and line."""
    from hazbrief.brief import places

    s = (brief.derived or {}).get("smoke")
    if s is None:
        return ""
    spec = cfg["weather"]["smoke"]
    out = [f"<h3>{esc(spec['panel_title'])}</h3>"]
    for line in s.get("lines") or []:
        out.append(f'<p class="degraded">{esc(line)}.</p>')
    if s.get("hint"):
        out.append(f'<p class="pl">{esc(s["hint"])}.</p>')
    if s.get("note"):
        out.append(
            f'<p class="pl">{esc(spec["note_line"].format(note=s["note"]))}.</p>'
        )
    if s.get("follows"):
        out.append(f"<p>{esc(s['follows'])}.</p>")
    out.append(f'<p class="pl">{esc(places.LABEL)}.</p>')
    return "".join(out)


def _puff_html(brief, cfg) -> str:
    """The first-order puff's panel (DN-018 section 9; HB-67), after the stability
    class: DN-018 section 9's label verbatim, the wind driving the puff and the grid it
    fits (HB-70), each envelope's assumption and farthest
    extents, the line naming any input not held, and the inputs table. On a material
    whose class carries the dense-gas caveat, the label's "not a dense-gas model" is in
    the accent. Not in the ICS 201, the export or the first actions."""
    spec = cfg["weather"]["puff"]
    p = (brief.derived or {}).get("puff")
    out = [f"<h3>{esc(spec['panel_title'])}</h3>"]
    if p is None:
        return out[0] + '<p class="degraded">Not derived.</p>'
    if tevv.source_term_of(brief) is not None:
        out.append(method_ref(cfg, "source_term"))
    if p.get("label"):
        label = esc(p["label"])
        clause = esc(spec["dense_gas_clause"])
        if p.get("dense_gas_caveat"):
            label = label.replace(clause, f'<span class="caveat">{clause}</span>', 1)
        out.append(f'<p class="puff-label">{label}</p>')
    # the wind driving the puff first, then the grid it fits (HB-70 steps 1 and 3)
    for line in p.get("assumptions") or []:
        out.append(f"<p>{esc(line)}.</p>")
    for env in p.get("envelopes") or []:
        if env.get("assumption"):
            ext = "; ".join(
                f"{k}: {v:,.0f} m" for k, v in (env.get("extents_m") or {}).items()
            )
            out.append(
                f"<p><strong>{esc(env['title'].capitalize())}.</strong> "
                f"{esc(env['assumption'])}. Farthest extent: {esc(ext or 'none')}.</p>"
            )
            if env.get("rate_how"):
                out.append(f'<p class="pl">{esc(env["rate_how"])}.</p>')
    for line in p.get("lines") or []:
        if p.get("state") == "not_applicable":
            # HB-120: a statement of the chemistry, with the ERG's own full stop
            out.append(f"<p>{esc(line)}</p>")
        else:
            out.append(f'<p class="degraded">{esc(line)}.</p>')
    rows = []
    for i in p.get("inputs") or []:
        when = L.when(i["as_of"], brief.time_zone) if i.get("as_of") else ""
        rows.append(
            "<tr>"
            + "".join(
                f"<td>{esc(x)}</td>"
                for x in (i["name"], i["value"], i.get("source") or "", when)
            )
            + "</tr>"
        )
    if rows:
        head = "".join(f"<th>{x}</th>" for x in ("Input", "Value", "Source", "As of"))
        out.append(f'<table class="derived"><tr>{head}</tr>{"".join(rows)}</table>')
    ev = p.get("evidence") or {}
    if ev.get("sha256"):
        n = L.config()["hash_prefix_chars"]
        out.append(
            f'<p class="pl">Run record <code>{esc(ev["sha256"][:n])}</code> '
            "(its inputs and their hashes are in the evidence appendix).</p>"
        )
    return "".join(out)


def _num(v, places: int = 1) -> str:
    """A number for the strip and table; a blank for an hour the grid does not cover."""
    if v is None:
        return ""
    return f"{v:.{places}f}"


def _read_counts(sources: list[dict]) -> str:
    """What a panel read, by service: how many answers and when (DN-015's labels)."""
    by: dict[str, list[str]] = {}
    for s in sources or []:
        by.setdefault(s["api"], []).append(s.get("retrieved") or "")
    parts = []
    for api, when in by.items():
        known = sorted(w for w in when if w)
        span = f", retrieved {known[0][:10]}" if known else ""
        parts.append(f"{api}: {len(when)} answer{'s' if len(when) != 1 else ''}{span}")
    return "; ".join(parts)


def _class_table(rows: list[dict], what: str) -> str:
    head = "".join(f"<th>{x}</th>" for x in ("Class", "Name", what))
    body = "".join(
        f"<tr><td>{esc(r['code'])}</td><td>{esc(r['name'] or '')}</td>"
        f"<td>{100 * r['share']:.1f}</td></tr>"
        for r in rows
    )
    return f'<table class="derived"><tr>{head}</tr>{body}</table>'


def _cover_html(cover: dict | None, reason: str | None) -> list[str]:
    """Land cover (HB-59 ADDENDUM-03): the class at the spill, the class mix over the
    footprint and the classes at the downstream path's vertices, from one read."""
    if cover is None:
        return [
            '<p class="degraded">Land cover: not answered'
            + (f": {esc(reason)}" if reason else "")
            + ".</p>"
        ]
    out = []
    pt = cover.get("point")
    out.append(
        f"<p>Land cover at the spill: {esc(pt['name'])} (Annual NLCD "
        f"{esc(cover['vintage'])}, class {esc(pt['code'])}).</p>"
        if pt
        else '<p class="degraded">Land cover at the spill: no data at that cell.</p>'
    )
    mix = cover.get("mix")
    if mix and mix["rows"]:
        top = mix["rows"][0]
        out.append(
            '<details class="derived"><summary>Land cover over the footprint, largest '
            f"share: {esc(top['name'])}, {100 * top['share']:.1f}% of "
            f"{mix['cells']:,} cells"
            + (f", {mix['no_data']:,} with no data" if mix["no_data"] else "")
            + "</summary>"
            + _class_table(mix["rows"], "Share (%)")
            + f'<p class="pl">{esc(cover["weighting"])}.</p></details>'
        )
    elif mix:
        out.append(
            '<p class="degraded">Land cover over the footprint: no cell answered.</p>'
        )
    along = cover.get("path")
    if along:
        out.append(
            '<details class="derived"><summary>Land cover along the downstream '
            f"path: {along['answered']} of {along['vertices']} vertices "
            "answered</summary>"
            + (_class_table(along["rows"], "Vertices (%)") if along["rows"] else "")
            + "</details>"
        )
    out.append(f'<p class="pl">{esc(cover["label"])}; {esc(cover["point_note"])}.</p>')
    return out


def _terrain_html(t: dict | None) -> str:
    """The terrain panel (DN-015 section 5; HB-55): numbers, not a surface, with the
    section's label verbatim."""
    out = ["<h2>Terrain</h2>"]
    if t is None:
        return out[0] + '<p class="degraded">Not derived.</p>'
    if t.get("reason") and not t.get("zones"):
        return out[0] + f'<p class="degraded">Not derived: {esc(t["reason"])}</p>'
    ref = t.get("vertical_reference", "")
    spill = t.get("spill_m")
    out.append(
        "<p>Elevation at the spill: "
        + (f"{spill:.1f} m" if spill is not None else "not answered")
        + f" ({esc(ref)}).</p>"
    )
    rows = "".join(
        "<tr>"
        + "".join(
            f"<td>{esc(x)}</td>"
            for x in (
                z,
                f"{v['answered']} of {v['samples']}",
                "" if v["min_m"] is None else f"{v['min_m']:.1f}",
                "" if v["max_m"] is None else f"{v['max_m']:.1f}",
            )
        )
        + "</tr>"
        for z, v in [
            *((layers._zone_text(z), v) for z, v in (t.get("zones") or {}).items()),
            *([("Downstream path (its vertices)", t["path"])] if t.get("path") else []),
        ]
    )
    if rows:
        head = "".join(
            f"<th>{x}</th>"
            for x in ("Sampled along", "Points answered", "Lowest (m)", "Highest (m)")
        )
        out.append(f'<table class="derived"><tr>{head}</tr>{rows}</table>')
        out.append(
            f'<p class="pl">Points every {t["spacing_m"]:.0f} m along each boundary '
            "(the union's sample spacing, HB-49).</p>"
        )
    if t.get("elevation_fallback"):
        out.append(
            '<p class="degraded">Elevation read point by point from EPQS: 3DEP '
            f"getSamples was not read for {esc(t['elevation_fallback'])}.</p>"
        )
    out += _cover_html(t.get("cover"), t.get("cover_reason"))
    out.append(
        f'<p class="pl">{esc(t["label"])}; {esc(_read_counts(t.get("sources")))}</p>'
    )
    return "".join(out)


def _establishments_html(e: dict | None) -> str:
    """The county's establishments by two-digit NAICS (DN-015 section 4; HB-55): every
    sector, sortable by any column, no selection."""
    out = ["<h2>Establishments in the county</h2>"]
    if e is None:
        return out[0] + '<p class="degraded">Not derived.</p>'
    if not e.get("rows"):
        return out[0] + f'<p class="degraded">Not derived: {esc(e.get("reason"))}</p>'
    rows = "".join(
        "<tr>"
        + "".join(
            f"<td>{esc(x)}</td>"
            for x in (r["county"], r["naics"], r["sector"], r["establishments"])
        )
        + "</tr>"
        for r in e["rows"]
    )
    head = "".join(
        f"<th>{x}</th>" for x in ("County (FIPS)", "NAICS", "Sector", "Establishments")
    )
    out.append(
        '<details class="derived"><summary>Every two-digit sector, by county '
        "(click a heading to "
        f'sort)</summary><table class="derived sortable"><tr>{head}</tr>{rows}'
        "</table></details>"
    )
    out.append(
        f'<p class="pl">{esc(e["label"])}; {esc(_read_counts(e.get("sources")))}</p>'
    )
    return "".join(out)


def _pattern_body(spec: dict, color: str, opacity: float) -> str:
    """The marks of one `map.patterns` entry inside a `gap_px` tile: lines (`hatch`),
    two sets at right angles (`cross`) or a dot (`dots`), in `color`."""
    g, w = spec["gap_px"], spec["width_px"]
    mark = f'stroke="{attr(color)}" stroke-width="{w}" stroke-opacity="{opacity}"'
    if spec["kind"] == "dots":
        return (
            f'<circle cx="{g / 2:g}" cy="{g / 2:g}" r="{w:g}" fill="{attr(color)}" '
            f'fill-opacity="{opacity}"/>'
        )
    out = f'<line x1="0" y1="{g / 2:g}" x2="{g}" y2="{g / 2:g}" {mark}/>'
    if spec["kind"] == "cross":
        out += f'<line x1="{g / 2:g}" y1="0" x2="{g / 2:g}" y2="{g}" {mark}/>'
    elif spec["kind"] != "hatch":
        raise ValueError(
            f"map.patterns kind {spec['kind']!r} is not hatch, cross or dots"
        )
    return out


def pattern_defs(data: dict, cfg) -> str:
    """One hidden SVG holding a `<pattern>` per patterned layer drawn (DN-019 section 2
    item 3; HB-114 step 4): a tint in the layer's colour at its fill opacity, under the
    pattern's marks. The map's fills and the legend's swatches refer to them by id, so
    both draw the same pattern."""
    m = cfg["map"]
    pats = []
    for lay in data["layers"]:
        pid = lay["style"].get("pattern")
        if not pid:
            continue
        spec = m["patterns"][lay["id"]]
        st = lay["style"]
        color = st.get("fill") or st.get("color")
        tint = st.get("fillOpacity", 0.2)
        g = spec["gap_px"]
        pats.append(
            f'<pattern id="{attr(pid)}" patternUnits="userSpaceOnUse" width="{g}" '
            f'height="{g}" patternTransform="rotate({spec["angle"]})">'
            f'<rect width="{g}" height="{g}" fill="{attr(color)}" '
            f'fill-opacity="{tint}"/>'
            f"{_pattern_body(spec, color, m['pattern_opacity'])}</pattern>"
        )
    if not pats:
        return ""
    return (
        '<svg id="hb-patterns" width="0" height="0" aria-hidden="true" '
        f'style="position:absolute"><defs>{"".join(pats)}</defs></svg>'
    )


def _swatch(layer: dict) -> str:
    st = layer["style"]
    if st.get("pattern"):
        # the layer's own pattern, outlined in its colour (DN-019 section 2 item 3)
        return (
            '<svg class="sw sw-pat" width="22" height="14" aria-hidden="true">'
            f'<rect x="0.5" y="0.5" width="21" height="13" '
            f'fill="url(#{attr(st["pattern"])})" stroke="{attr(st.get("color"))}" '
            'stroke-width="1"/></svg>'
        )
    if st.get("symbols"):
        # HB-152 item 5: the layer's symbol beside its toggle; a layer of several
        # classes (the nearby services, the care layer) shows each
        px = layers.symbols()["standard"]["legend_px"]
        return "".join(
            f'<span class="sw sw-sym" aria-hidden="true">'
            f"{layers.symbol_svg(cls, st['fill'], px)}</span>"
            for cls in st["symbols"]
        )
    color = st.get("fill") or st.get("color") or "#000000"
    shape = (
        "dot"
        if layer["kind"] == "point"
        else ("bar" if layer["kind"] == "line" else "box")
    )
    return f'<span class="sw sw-{shape}" style="background:{attr(color)}"></span>'


def method_ref(cfg, sid: str) -> str:
    """HB-161: the number of a method's TEVV section, on its own line under the
    method's heading in the Zones and models tab."""
    return f'<p class="tref-line">{tevv.link_html(cfg, sid)}</p>'


def map_data(data: dict) -> dict:
    """The map data as the page carries it: each layer without `doc`, the documentation
    `layers.build` moved off the map for the TEVV page (HB-161)."""
    return {
        **data,
        "layers": [
            {k: v for k, v in lay.items() if k != "doc"} for lay in data["layers"]
        ],
    }


def _layer_row(
    cfg,
    lid: str,
    on: bool | None,
    swatch: str,
    title: str,
    figure: str,
    body: str,
    *,
    muted: bool = False,
) -> str:
    """One layer row (HB-158 item 3; G4, G10, G11): one line (its box, its swatch, a
    short name and the one figure that matters) that opens on a click or Enter onto
    the layer's full title, legend, label line and source (a native `<details>`).
    The box sits in its own label so a click on it toggles the layer, not the row; a
    muted row (`none`, nothing there) has no box. Nothing the old row printed is
    dropped: the full title opens first when the short name differs from it."""
    name = layers.row_name(cfg, lid)
    box = ""
    if on is not None:
        box = (
            f'<label class="lbox"><input type="checkbox" data-layer="{attr(lid)}"'
            f'{" checked" if on else ""}><span class="vh">Show {esc(name)}</span>'
            "</label> "
        )
    full = f'<p class="lt">{esc(title)}</p>' if title != name else ""
    cls = "lrow lnone" if muted else "lrow"
    # HB-161 ADDENDUM-01 items 2 and 4: the opened row keeps its key and measurement
    # and ends with its TEVV section's number; a muted row draws nothing, so none
    if not muted:
        ref = tevv.link_html(cfg, lid)
        if ref:
            body += f'<p class="tref-line">{ref}</p>'
    return (
        f'<li class="{cls}" data-row="{attr(lid)}"><details><summary>{box}{swatch}'
        f'<span class="ln">{esc(name)}</span> <span class="n">{esc(figure)}</span>'
        f'</summary><div class="lx">{full}{body}</div></details></li>'
    )


WIND_FIELD_TITLE = "Wind field (NWS gridpoint forecast)"


def _wind_field_entry(wf: dict | None, cfg, missing: list, tz: str) -> str:
    """The wind field's layer row (HB-103 Part B): its checkbox, on by default (DN-019
    section 3; `map.defaults`), and the hour stepper over the forecast window's rows
    (hours 0 to N), in its expansion (the live page's header carries the hour and its
    previous and next buttons, HB-158 item 6); else a missing entry with why."""
    head = WIND_FIELD_TITLE
    if not wf or not wf.get("cells"):
        why = (wf or {}).get("reason") or "the derivations have not run"
        missing.append(("wind_field", head, why))
        return ""
    spec = cfg["weather"]["wind_field"]
    on = layers.default_on(cfg, "wind_field")
    n = len(wf["hours"]) - 1
    # the stepper's opening hour (DN-019 section 3, "at hour 0"; `map.defaults`)
    h0 = min(int(cfg["map"]["defaults"]["hour_stepper"]), n)
    first = _wind_hours(wf, tz)[h0]
    body = (
        '<p class="pl"><label>Hour <input type="range" id="wind-hour" min="0" '
        f'max="{n}" value="{h0}" step="1"></label> '
        f'<output id="wind-hour-label">{esc(first)}</output></p>'
        f'<p class="pl" id="wind-hour-note">{esc(_wind_notes(wf, cfg, tz)[h0])}</p>'
        f'<p class="lg">{esc(spec["legend"])}.</p>'
        f'<p class="pl">{esc(wf["label"])}</p>'
    )
    swatch = f'<span class="sw sw-bar" style="background:{attr(spec["color"])}"></span>'
    figure = layers.row_figure(
        None, cfg, {"id": "wind_field", "legend": ""}, len(wf["cells"])
    )
    return _layer_row(cfg, "wind_field", on, swatch, head, figure, body)


def _wind_hours(wf: dict, tz: str) -> list[str]:
    """The stepper's label for each hour: "+h h, HH:MM" in the brief's zone, the same
    hours as the forecast window's rows."""
    return [f"+{h} h, {L.when(t, tz)[11:16]}" for h, t in enumerate(wf["hours"])]


def _wind_notes(wf: dict, cfg, tz: str) -> list[str]:
    """Each hour's line under the stepper: how many cells hold no forecast for it (the
    mismatch between a cell's grid and the hour, as the window counts uncovered hours),
    and the cells not drawn at all, with why."""
    spec = cfg["weather"]["wind_field"]
    cells = wf["cells"]
    out = []
    gone = wf.get("missing") or []
    tail = ""
    if gone:
        whys = sorted({m[2] for m in gone})
        tail = " " + spec["missing_line"].format(n=len(gone), why="; ".join(whys)) + "."
    for i, t in enumerate(wf["hours"]):
        near = [c for c in cells if c["rows"][i] is not None and len(c["rows"][i]) > 2]
        blank = [c for c in cells if c["rows"][i] is None]
        lines = []
        if near:
            ups = sorted({c["update_time"] for c in near if c.get("update_time")})
            starts = sorted({c["valid_from"] for c in near})
            reads = sorted({c["rows"][i][2] for c in near})
            lines.append(
                spec["uncovered_line"].format(
                    n=len(near),
                    cells=len(cells),
                    when=L.when(t, tz),
                    updated=", ".join(L.when(u, tz) for u in ups) or "unknown",
                    valid_from=", ".join(L.when(s, tz) for s in starts),
                    read_at=", ".join(L.when(r, tz) for r in reads),
                )
            )
        if blank:
            lines.append(
                spec["blank_line"].format(
                    n=len(blank), cells=len(cells), when=L.when(t, tz)
                )
            )
        if not lines:
            lines.append(f"Every cell holds a forecast for {L.when(t, tz)}")
        out.append(". ".join(lines) + "." + tail)
    return out


def _wind_field_config(
    wf: dict | None, fp_wind: dict | None, cfg, tz: str, grid: str | None = None
):
    """The wind field as the map script draws it: each cell's centre, title (its grid
    and as-of) and its (direction from, km/h) per hour, or null for an hour its grid
    does not cover; the hour labels and notes; and the footprint's own wind at the
    spill. `grid` is the brief's wind record's cell (HB-133) when the record is a
    forecast cell: that cell is `own`, drawn full, and every other cell muted (HB-141
    F1). None when the field is not drawn."""
    if not wf or not wf.get("cells"):
        return None
    spec = cfg["weather"]["wind_field"]
    speeds = [r[1] for c in wf["cells"] for r in c["rows"] if r is not None]
    foot = None
    if fp_wind and fp_wind.get("direction_deg_from") is not None and wf.get("spill"):
        as_of = fp_wind.get("as_of")
        foot = {
            "lat": wf["spill"][0],
            "lon": wf["spill"][1],
            "dir": fp_wind["direction_deg_from"],
            "speed": fp_wind.get("speed_kmh"),
            "title": spec["footprint_label"].format(
                source=fp_wind.get("source"),
                as_of=L.when(as_of, tz) if as_of else "unknown",
            ),
        }

    def row(r, t):
        # a row read at its grid's nearest covered hour carries that hour's title
        if r is None or len(r) < 3:
            return r
        return [
            r[0],
            r[1],
            spec["read_at_title"].format(read_at=L.when(r[2], tz), when=L.when(t, tz)),
        ]

    return {
        "cells": [
            {
                "lat": c["lat"],
                "lon": c["lon"],
                "rows": [row(r, t) for r, t in zip(c["rows"], wf["hours"])],
                "title": spec["title"].format(
                    grid=c["grid"],
                    updated=L.when(c["update_time"], tz)
                    if c.get("update_time")
                    else "unknown",
                ),
                "own": grid is not None and c["grid"] == grid,
            }
            for c in wf["cells"]
        ],
        "muted_opacity": spec["muted_opacity"],
        "own_title": spec["own_title"],
        "hours": _wind_hours(wf, tz),
        "notes": _wind_notes(wf, cfg, tz),
        "max_speed": max(speeds, default=0),
        "arrow_px": spec["arrow_px"],
        "footprint_px": spec["footprint_px"],
        "color": spec["color"],
        "accent": cfg["page"]["accent"],
        "footprint": foot,
    }


def _snapshots_config(derived: dict) -> dict:
    """Each stored snapshot as the map draws it: a data URI of the stored image and its
    frame in latitude and longitude (the EPSG:3857 box it was asked for)."""
    out = {}
    for name, s in (derived.get("snapshots") or {}).items():
        if not s.get("held"):
            continue
        png = base64.b64encode(read_entity(Path(s["store"]), s["sha"])).decode("ascii")
        x0, y0, x1, y1 = (float(v) for v in s["bbox"].split(","))
        out[name] = {
            "src": f"data:{s['media_type']};base64,{png}",
            "bounds": [_lat_lon(x0, y0), _lat_lon(x1, y1)],
            "time": s["time"],
        }
    return out


def _snapshot_html(brief, cfg) -> str:
    """The weather section's citation of its snapshots (DN-009 C2): each stored image
    by record hash, with its request url, scan time and fetch time; else why there is
    none."""
    snaps = (brief.derived or {}).get("snapshots")
    if snaps is None:
        return ""
    out = ["<h3>Radar and satellite snapshots</h3>"]
    for name, head in (("radar", "Radar"), ("satellite", "Satellite")):
        s = snaps.get(name)
        if s and s.get("held"):
            out.append(
                f'<p class="pl">{esc(s["label"])}; asked as '
                f"<code>{esc(s['url'])}</code>.</p>"
            )
        else:
            why = (s or {}).get("reason") or "not derived"
            out.append(f'<p class="pl">{head}: {esc(why)}.</p>')
    return "".join(out)


def _missing_layers(data: dict, radar, derived: dict, cfg, tz: str) -> list[tuple]:
    """Every layer the list can offer that has nothing to draw, as (id, title, reason,
    swatch): the built layers without features, then the weather layers the page
    draws from the derivations (radar, satellite, the wind field, the snapshots).
    `_layer_list_html` and the Data gaps items (`layer_gaps`) read the same list."""
    out = []
    for lay in reversed(data["layers"]):
        if not lay["features"]:
            out.append((lay["id"], lay["title"], lay["reason"] or "", _swatch(lay)))
    box = '<span class="sw sw-box" style="background:{}"></span>'
    if not (radar and radar.get("held")):
        why = radar.get("reason") if radar else "the derivations have not run"
        out.append(("radar", RADAR_TITLE, why or "", box.format("#3cb44b")))
    sat = derived.get("satellite")
    if not (sat and sat.get("held")):
        why = sat.get("reason") if sat else "the derivations have not run"
        out.append(("satellite", SATELLITE_TITLE, why or "", box.format("#9e9e9e")))
    wf = derived.get("wind_field")
    if not wf or not wf.get("cells"):
        color = cfg["weather"]["wind_field"]["color"]
        why = (wf or {}).get("reason") or "the derivations have not run"
        out.append(
            (
                "wind_field",
                WIND_FIELD_TITLE,
                why,
                f'<span class="sw sw-bar" style="background:{attr(color)}"></span>',
            )
        )
    for name, head in SNAPSHOTS:
        s = (derived.get("snapshots") or {}).get(name)
        if not (s and s.get("held")):
            why = s.get("reason") if s else "the derivations have not run"
            out.append((f"{name}_snapshot", head, why or "", box.format("#5c6bc0")))
    return out


RADAR_TITLE = "Radar now (NOAA nowCOAST base reflectivity)"
SATELLITE_TITLE = "Satellite now (NOAA nowCOAST)"
SNAPSHOTS = (("radar", "Radar snapshot"), ("satellite", "Satellite snapshot"))


def layer_gaps(brief, cfg) -> list[dict]:
    """HB-158 item 4: the layers the reader would expect that could not be drawn (a
    source not reached or not recorded, a model not run; `map.empty_rows`, `as: gap`),
    each with its short name, its line and its reason, in the layer list's order:
    what "N layers could not be drawn" lists and what the checklist's Data gaps items
    say, worded the same (`map.layer_gap_line`)."""
    derived = brief.derived or {}
    data = layers.build(brief, cfg)
    out = []
    for lid, title, why, _ in _missing_layers(
        data, derived.get("radar"), derived, cfg, brief.time_zone
    ):
        d = layers.empty_disposition(cfg, lid, why)
        if d["as"] != "gap":
            continue
        name = layers.row_name(cfg, lid)
        out.append(
            {
                "layer": lid,
                "name": name,
                "title": title,
                "say": d["say"],
                "reason": why,
                "text": cfg["map"]["layer_gap_line"].format(name=name, say=d["say"]),
            }
        )
    return out


def _layer_list_html(
    data: dict,
    cfg,
    radar: dict | None = None,
    derived: dict | None = None,
    tz: str = "UTC",
    brief=None,
) -> str:
    """The layer list (HB-154 item 5; HB-158 items 3 and 4): one row per drawn layer
    under its group's heading, each one line that opens onto its full title, legend,
    label line and source; the layers with nothing there, muted, in the `none` group;
    the layers that could not be drawn behind one line, "N layers could not be
    drawn", each with its line and its reason (the `ul.missing` list the load read
    protects); a layer `map.empty_rows` marks unlisted is not printed."""
    derived = derived or {}
    # HB-162R (DN-025): a passive release's cloud rows carry the puff's sections
    if brief is not None:
        cfg = tevv.brief_cfg(cfg, brief)
    shown = []
    for lay in reversed(data["layers"]):
        if not lay["features"]:
            continue
        # HB-155: the area ring is a mark of the services layer, not one of its places
        n = sum(1 for f in lay["features"] if not f["properties"].get("ring"))
        if lay["id"] == "wind":
            n = 1
        extra = ""
        if lay["kind"] == "choropleth":
            m = cfg["map"]
            b = m["population_breaks"]
            names = (
                [f"{b[0] - 1}"]
                + [f"{lo}–{hi - 1}" for lo, hi in zip(b, b[1:])]
                + [f"{b[-1]}+"]
            )
            ramp = m["population_ramp"]
            if "breaks" in lay["style"]:
                # HB-142R item 2: a quantile layer's swatches are its own bands
                names = layers.band_names(lay["style"]["breaks"])
                ramp = m["residential"]["ramp"]
            extra = (
                '<ul class="ramp">'
                + "".join(
                    '<li><span class="sw sw-box" '
                    f'style="background:{attr(col)}"></span>{esc(t)}</li>'
                    for col, t in zip(ramp, names)
                )
                + "</ul>"
            )
        if lay.get("legend"):
            # the footprint layer's legend entry: what, when, the action (HB-114)
            extra += f'<p class="lg">{esc(lay["legend"])}.</p>'
        if lay["style"].get("symbols"):
            # HB-152 item 5: each class's symbol named, FGDC or hazbrief's own
            px = layers.symbols()["standard"]["legend_px"]
            extra += (
                '<ul class="syms">'
                + "".join(
                    f'<li><span class="sw sw-sym" aria-hidden="true">'
                    f"{layers.symbol_svg(cls, lay['style']['fill'], px)}</span>"
                    f"{esc(layers.symbol_legend(cls))}</li>"
                    for cls in lay["style"]["symbols"]
                )
                + "</ul>"
            )
        if any(f["properties"].get("open") for f in lay["features"]):
            # HB-161 item 6: an open band's key, one symbol, a box with no edge at
            # its open end; how the run ended is the layer's TEVV section
            col = attr(lay["style"].get("color") or "#000000")
            extra += (
                '<p class="lg"><svg class="open-key" width="22" height="12" '
                f'aria-hidden="true"><path d="M22 1 H1 V11 H22" fill="none" '
                f'stroke="{col}" stroke-width="1.5"/></svg>'
                f"{esc(cfg['map']['open_key'])}</p>"
            )
        extra += f'<p class="pl">{n} drawn</p>'
        figure = layers.row_figure(brief, cfg, lay, n) if brief is not None else str(n)
        shown.append(
            (
                lay["id"],
                _layer_row(
                    cfg, lay["id"], lay["on"], _swatch(lay), lay["title"], figure, extra
                ),
            )
        )
    shown.append(
        (
            "roads",
            _layer_row(
                cfg,
                "roads",
                layers.default_on(cfg, "roads"),
                '<span class="sw sw-bar" style="background:#999999"></span>',
                "Roads image (TIGERweb, as Block 4 drew it)",
                "",
                "",
            ),
        )
    )
    box = '<span class="sw sw-box" style="background:{}"></span>'
    if radar and radar.get("held"):
        shown.append(
            (
                "radar",
                _layer_row(
                    cfg,
                    "radar",
                    layers.default_on(cfg, "radar"),
                    box.format("#3cb44b"),
                    RADAR_TITLE,
                    f"scan {radar['time']}",
                    f'<p class="pl">{esc(radar["label"])}</p>',
                ),
            )
        )
    sat = derived.get("satellite")
    if sat and sat.get("held"):
        shown.append(
            (
                "satellite",
                _layer_row(
                    cfg,
                    "satellite",
                    layers.default_on(cfg, "satellite"),
                    box.format("#9e9e9e"),
                    f"Satellite now (NOAA nowCOAST, {sat['band']})",
                    f"scan {sat['time']}",
                    f'<p class="pl">{esc(sat["label"])}</p>',
                ),
            )
        )
    # HB-210: the traffic row exists only on a page that carries a Google key
    if brief is not None and brief.google_key:
        shown.append(("traffic", _traffic_row(cfg)))
    wf_row = _wind_field_entry(derived.get("wind_field"), cfg, [], tz)
    if wf_row:
        shown.append(("wind_field", wf_row))
    for name, head in SNAPSHOTS:
        s = (derived.get("snapshots") or {}).get(name)
        if s and s.get("held"):
            shown.append(
                (
                    f"{name}_snapshot",
                    _layer_row(
                        cfg,
                        f"{name}_snapshot",
                        layers.default_on(cfg, f"{name}_snapshot"),
                        box.format("#5c6bc0"),
                        f"{head} (stored)",
                        f"scan {s['time']}",
                        f'<p class="pl">{esc(s["label"])}</p>',
                    ),
                )
            )
    # HB-171 item 10: the next rows of the threat timeline, above the Hazard group's
    # rows (`map.layer_groups` places `threat_next` first)
    nxt = threat.first_view_html(brief, cfg, data) if brief is not None else ""
    if nxt:
        shown.append(("threat_next", nxt))
    # HB-163 item 6 (ADDENDUM-04): the cloud's measured times, one row under the levels
    times = _cloud_times_html(brief, cfg) if brief is not None else ""
    if times:
        shown.append(("cloud_times", times))
    none_rows, gaps = [], []
    for lid, title, why, swatch in _missing_layers(data, radar, derived, cfg, tz):
        d = layers.empty_disposition(cfg, lid, why)
        if d["as"] == "unlisted":
            continue
        if d["as"] == "none":
            # the full title opens first (`_layer_row`), then the layer's own reason
            body = f'<p class="pl">{esc(why)}</p>'
            none_rows.append(
                _layer_row(cfg, lid, None, swatch, title, d["say"], body, muted=True)
            )
            continue
        # worded as its Data gaps item (`layer_gaps`), the old "Not drawn" line under it
        # HB-163 ADDENDUM-02 item 2: the cloud not modelled carries the selection
        # rule's number (its section is on every brief that classed a release)
        gref = (
            tevv.link_html(cfg, lid)
            if lid == cfg["map"]["cloud"]["not_modelled_id"]
            else ""
        )
        gaps.append(
            f'<li data-row="{attr(lid)}">{state_mark(cfg, "failed", glyph_only=True)} '
            f"<strong>{esc(layers.row_name(cfg, lid))}:</strong> "
            f'<span class="gsay">{esc(d["say"])}</span>'
            f'<span class="why">{esc(title)}: {esc(why)}</span>'
            f"{' ' + gref if gref else ''}</li>"
        )
    out = (
        f'{_basemaps_html(cfg)}{pattern_defs(data, cfg)}<ul id="layer-list">'
        f"{_grouped_rows(shown, cfg, none_rows)}"
        # HB-152 item 5: the fonts' own terms require a product to call the symbols a
        # draft prototype (docs/evidence/hb150/glyph_notes.md); the list's last entry,
        # so the load read protects it with the legend (load_read_rules ids.layer-list)
        f'<li class="pl" id="symbols-note">'
        f"{esc(layers.symbols()['standard']['legend_line'])}</li></ul>"
    )
    if gaps:
        m = cfg["map"]
        line = (
            m["gaps_line_one"] if len(gaps) == 1 else m["gaps_line"].format(n=len(gaps))
        )
        out += (
            f'<details id="layer-gaps"><summary>{esc(line)}</summary>'
            f'<ul class="missing">{"".join(gaps)}</ul></details>'
        )
    return out


def _grouped_rows(rows: list[tuple[str, str]], cfg, none_rows=()) -> str:
    """The layer rows under their plain headings (HB-154 item 5; `map.layer_groups`),
    in the groups' order, each group's rows in its `layers` order (HB-158: the zones
    before the models). The group marked `holds: none` holds `none_rows`, the muted
    rows of layers with nothing there. A group with no row prints nothing. A row whose
    layer no group lists raises: a new layer is placed in a group when it is added,
    never dropped from the list."""
    groups = cfg["map"]["layer_groups"]
    where = {lid: g["id"] for g in groups for lid in g["layers"]}
    stray = sorted({lid for lid, _ in rows if lid not in where})
    if stray:
        raise RuntimeError(
            f"layer rows {stray} are in no map.layer_groups entry (orchestrator.yaml)"
        )
    out = []
    for g in groups:
        if g.get("holds") == "none":
            mine = list(none_rows)
        else:
            rank = {lid: i for i, lid in enumerate(g["layers"])}
            mine = [
                h
                for lid, h in sorted(
                    (r for r in rows if where[r[0]] == g["id"]),
                    key=lambda r: rank[r[0]],
                )
            ]
        if not mine:
            continue
        count = f' <span class="n">{len(mine)}</span>' if g.get("holds") else ""
        out.append(
            f'<li class="lgroup" data-group="{attr(g["id"])}">'
            f"<h3>{esc(g['title'])}{count}</h3></li>"
        )
        out += mine
    return "".join(out)


def _basemaps_html(cfg) -> str:
    """The basemap switch at the head of the layer control (HB-141 F7; HBD-222): one
    radio per `map.fallback_tiles` entry, the first (the street map) checked. The map
    script moves the check when a page opened from a file opens on another (the tile
    policy's Referer; `map.file_basemap_note`)."""
    radios = "".join(
        f'<label><input type="radio" name="basemap" value="{i}"'
        f"{' checked' if i == 0 else ''}> {esc(t['label'])} "
        f'<span class="n">{esc(t["name"])}</span></label>'
        for i, t in enumerate(cfg["map"]["fallback_tiles"])
    )
    return (
        f'<fieldset id="basemaps"><legend>Basemap</legend>{radios}'
        '<p class="pl" id="basemap-note" hidden></p></fieldset>'
    )


def _layer_control_html(inner: str) -> str:
    """The layer control docked to the map's right edge (HB-141 F2; HBD-216): a
    `<details>` open on first paint, closed and reopened by its summary. The list
    inside keeps `#layer-list` and `ul.missing`, the load read's protected places
    (`load_read_rules.yaml` `protected`)."""
    return (
        '<details id="layer-control" open><summary><h2>Layers</h2></summary>'
        f'<div class="lc-body">{inner}</div></details>'
    )


def _location_record(brief, cfg) -> str:
    """The spill point's location record (DN-013 section 2; HB-48), as data on the page,
    so the label a popup prints is read from the record a reader can inspect."""
    rec = location.of_brief(brief, cfg)
    if rec is None:
        return ""
    return (
        '<script type="application/json" id="location-record">'
        f"{_script_text(json.dumps(rec, sort_keys=True))}</script>"
    )


def _google_config(brief, cfg) -> dict:
    """The map configuration only a page with a Google key carries (HB-210): the map
    notes `static/google.js` writes and the traffic row's words, its label read at the
    time the page is opened, in the brief's zone. A page with no key carries none of
    it, so the committed briefs (built with `--no-google`) are unchanged."""
    if not brief.google_key:
        return {}
    g = cfg["map"]["google"]
    t = cfg["map"]["traffic"]
    return {
        "google_note_refused": g["note_refused"],
        "google_note_blocked": g["note_blocked"],
        "google_note_timeout": g["note_timeout"],
        "traffic": {
            "name": layers.row_name(cfg, "traffic"),
            "figure": t["figure"],
            "label": t["label"],
            "time_zone": brief.time_zone,
        },
    }


def _traffic_row(cfg) -> str:
    """The traffic row on a page with a Google key (HB-210): built as its Leaflet
    fallback, the line "not available" and no switch; `static/google.js` makes it the
    layer's switch, off, with its legend and live label, once the Google map draws."""
    t = cfg["map"]["traffic"]
    legend = "".join(
        f'<li><span class="sw sw-bar" style="background:{attr(k["color"])}"></span>'
        f"{esc(k['label'])}</li>"
        for k in t["legend"]
    )
    body = (
        f'<p class="pl traffic-na">{esc(t["not_available"])}</p>'
        f'<ul class="ramp traffic-legend" hidden>{legend}</ul>'
        '<p class="pl traffic-label"></p>'
        f'<p class="pl">{esc(t["drawn_by"])}</p>'
    )
    return _layer_row(
        cfg,
        "traffic",
        None,
        '<span class="sw sw-bar" style="background:#9e9e9e"></span>',
        t["title"],
        t["not_available_figure"],
        body,
        muted=True,
    )


def _workbench(brief, cfg) -> str:
    sec = brief.sections["map"]
    page = cfg["page"]
    data = layers.build(brief, cfg)
    roads = _roads(brief, page)
    derived = brief.derived or {}
    radar = derived.get("radar")
    sat = derived.get("satellite")
    fp_wind = _brief_wind(brief)
    if sec["state"] == "pending":
        note = "Waiting for the protective action footprint."
    elif sec["state"] == "degraded":
        note = sec["reason"]
    else:
        note = ""
    mcfg = cfg["map"]
    cfg_js = json.dumps(
        {
            **_google_config(brief, cfg),
            "google_key": brief.google_key or "",
            "google_js": mcfg["google_js"],
            "google_timeout_ms": int(mcfg["google_timeout_s"] * 1000),
            "tiles": mcfg["fallback_tiles"],
            "file_basemap_note": mcfg["file_basemap_note"],
            "padding": mcfg["fit_padding_px"],
            "roads": roads and {"src": roads["src"], "bounds": roads["bounds"]},
            "roads_attribution": page["roads_attribution"],
            "radar": (
                {k: radar[k] for k in ("url", "layer", "time", "opacity", "label")}
                if radar and radar.get("held")
                else None
            ),
            "satellite": (
                {k: sat[k] for k in ("url", "layer", "time", "opacity", "label")}
                if sat and sat.get("held")
                else None
            ),
            "wind_field": _wind_field_config(
                derived.get("wind_field"),
                fp_wind,
                cfg,
                brief.time_zone,
                (getattr(brief, "wind_record", None) or {}).get("grid"),
            ),
            "snapshots": _snapshots_config(derived),
            # HB-157 item 12: the time control's steps (None: no modelled time)
            "time": _time_config(brief, cfg),
            # HB-155 ADDENDUM-01 item 6: the area the first view draws and the reader's
            # steps (None: the services were not derived)
            "area": layers.area_config(layers._Ctx(brief, cfg)),
            # HB-155 item 8: the siting block's data (None: no point was suggested)
            "siting": layers.siting_config(layers._Ctx(brief, cfg)),
            "muted_opacity": mcfg["muted_opacity"],
            # the weather layers whose switch the session remembers (HB-103 step 6)
            "remember": ["radar", "satellite", "wind_field"],
        },
        sort_keys=True,
    )
    labels = (
        labels_html(sec["labels"], brief.time_zone)
        if sec["state"] == "rendered"
        else ""
    )
    n = L.config()["hash_prefix_chars"]
    roads_note = (
        '<p class="pl">Roads image: TIGERweb, record '
        f"<code>{esc(roads['sha'][:n])}</code>.</p>"
        if roads
        else ""
    )
    return (
        f'<section class="{attr(sec["state"])}" id="section-map">'
        '<div id="workbench"><div id="map-wrap">'
        f'<div id="map" data-state="{attr(sec["state"])}"></div>'
        f"{_time_control_html(brief, cfg)}"
        f'<div id="map-note"{"" if note else " hidden"}>{esc(note)}</div>'
        + _layer_control_html(
            _layer_list_html(data, cfg, radar, derived, brief.time_zone, brief)
        )
        + "</div>"
        f'<aside id="panel">{_first_actions_html(brief, cfg, data)}'
        f"{_weather_html(brief, cfg)}{_snapshot_html(brief, cfg)}"
        f"{_observation_html(brief)}{_stability_html(brief, cfg)}"
        f"{_puff_html(brief, cfg)}{_dense_gas_html(brief, cfg)}"
        f"{_smoke_html(brief, cfg)}"
        f"{_derived_tables_html(brief, cfg)}"
        f"{roads_note}{labels}</aside></div>"
        f'<script type="application/json" id="map-data">'
        f"{_script_text(json.dumps(map_data(data), sort_keys=True))}</script>"
        f"{_location_record(brief, cfg)}"
        '<script type="application/json" id="map-config">'
        f"{_script_text(cfg_js)}</script></section>"
    )


def _live_build(brief) -> bool:
    """A brief whose tool calls were made in this run (not replayed from a store)."""
    return any(ch.get("origin") == "call" for ch in brief.channels.values())


def _time_config(brief, cfg) -> dict | None:
    """HB-157 item 12 (DN-024 section 3.7): the time control's steps, each with its
    clock time, the wind stepper's hour, the step's wind chip and the residents under
    the area it has reached; the step the page opens at (the last modelled step for a
    replay; for a live build the last step at or before its now after the as-given
    time). None when the puff ran no steps.

    HB-163 (ADDENDA 01 and 03): on a release whose modelled cloud is drawn the steps
    are the cloud's output steps, each with the forecast wind of the hour it falls in;
    the page opens on the harm path, and the control opens at the release."""
    cl = _cloud_time_config(brief, cfg)
    if cl is not None:
        return cl
    tl = ((brief.derived or {}).get("puff") or {}).get("timeline") or {}
    steps = tl.get("steps") or []
    if tl.get("reason") or not steps:
        return None
    tc = cfg["web"]["time_control"]
    mspec = cfg["derive"]["modelled"]
    by_step = ((brief.derived or {}).get("modelled_population") or {}).get(
        "by_step"
    ) or {}
    wf = (brief.derived or {}).get("wind_field") or {}
    last_hour = max(len(wf.get("hours") or []) - 1, 0)
    rows = []
    for s in steps:
        w = s.get("wind") or {}
        n = by_step.get(str(s["minute"]))
        rows.append(
            {
                "minute": s["minute"],
                "hplus": s["hplus"],
                "clock": s["clock"],
                "hour": min(s["minute"] // 60, last_hour) if wf.get("hours") else None,
                "wind_text": tc["wind"].format(
                    deg=w["from_deg"], kmh=w["kmh"], source=w["source"]
                )
                if w
                else tc["no_wind"],
                "pop_n": n,
                "pop_text": mspec["step_figure"].format(n=n, hplus=s["hplus"])
                if n is not None
                else tc["no_pop"],
            }
        )
    open_index = len(rows) - 1
    if _live_build(brief) and brief.as_given:
        from hazbrief.evidence import store as S

        since = (brief.now - S.parse_time(brief.as_given)).total_seconds() / 60.0
        at = [i for i, r in enumerate(rows) if r["minute"] <= since]
        open_index = at[-1] if at else 0
    return {
        "steps": rows,
        "open_index": open_index,
        "play_ms": int(tc["play_ms"]),
        "words": {k: tc[k] for k in ("play", "pause", "past")},
    }


def _hm(brief, minutes: int) -> str:
    """The clock time `minutes` after the as-given time, hours and minutes in the
    brief's zone (the date is the header's)."""
    from datetime import timedelta
    from zoneinfo import ZoneInfo

    from hazbrief.evidence import store as S

    t = S.parse_time(brief.as_given) + timedelta(minutes=int(minutes))
    tz = getattr(brief, "time_zone", None)
    return (t.astimezone(ZoneInfo(tz)) if tz else t).strftime("%H:%M")


def _cloud_times_html(brief, cfg) -> str:
    """HB-163 item 6 and ADDENDUM-04 items 1 and 2: one row under the cloud's levels.
    Closed, it is the headline: the time the last level leaves the scene, and how many
    drawn roadblocks the cloud reaches with the earliest arrival. Open, one line per
    place the cloud reaches (first arrival, the highest level and minutes above it,
    clear) and per roadblock (the same, or "not reached"). Measurements of the held
    record, with their sections' numbers; no advice."""
    from hazbrief.brief import cloud as CL
    from hazbrief.brief import derive as D

    cl = (brief.derived or {}).get("cloud") or {}
    if cl.get("state") != "drawn":
        return ""
    # HB-162R (DN-025): a passive release's lines are the puff's sections
    cfg = tevv.brief_cfg(cfg, brief)
    w = cfg["map"]["cloud"]["times"]
    t = CL.times(cl)

    def at(m: float | None) -> str:
        if m is None:
            return w["never"]
        k = int(round(m))
        return w["at"].format(clock=_hm(brief, k), hplus=D.hplus(k))

    last = (cl.get("steps") or [{}])[-1].get("minute", 0)
    scene = t["scene_clear_min"]
    head = (
        w["headline"].format(clock=_hm(brief, int(round(scene))))
        if scene is not None
        else w["headline_open"].format(clock=_hm(brief, int(last)))
    )
    first = t["first_roadblock_min"]
    blocks_line = (
        w["roadblocks"].format(
            n=t["roadblocks_reached"], clock=_hm(brief, int(round(first)))
        )
        if t["roadblocks_reached"]
        else w["roadblocks_none"]
    )
    # the closed row's words, in full, open first in its expansion
    full = [
        w["headline_full"].format(at=at(scene))
        if scene is not None
        else w["headline_open_full"].format(at=at(last)),
        w["roadblocks_full"].format(n=t["roadblocks_reached"], at=at(first))
        if t["roadblocks_reached"]
        else w["roadblocks_none"],
    ]
    names = lambda r: "; ".join(r["names"]) or w["unnamed"]  # noqa: E731
    places = "".join(
        f'<li data-place="{attr(r["id"])}">'
        + esc(
            w["place"].format(
                name=names(r),
                arr=at(r["arrival_min"]),
                tier=r["highest"],
                mins=r["minutes_above"],
                clear=at(r["clear_min"]),
            )
        )
        + "</li>"
        for r in t["places"]
    )
    blocks = "".join(
        f'<li data-place="{attr(r["id"])}">'
        + esc(
            w["block"].format(
                name=names(r),
                tier=r["highest"],
                arr=at(r["arrival_min"]),
                mins=r["minutes_above"],
                clear=at(r["clear_min"]),
            )
            if r["highest"]
            else w["block_not"].format(name=names(r))
        )
        + "</li>"
        for r in t["roadblocks"]
    )
    # the sections these lines and the cloud rest on, as `tevv.present` lists them
    kinds = {p["kind"] for p in cl.get("places") or []}
    refs = " ".join(
        x
        for x in (
            tevv.link_html(cfg, "arrival_lines")
            if kinds & {"named_place", "sited"}
            else "",
            tevv.link_html(cfg, "roadblock_lines") if "roadblock" in kinds else "",
            tevv.link_html(cfg, "engine_rule"),
        )
        if x
    )
    body = (
        "".join(f'<p class="lt">{esc(x)}</p>' for x in full)
        + (
            f'<p class="lt">{esc(w["places_head"])}</p><ul class="ctimes">{places}</ul>'
            if places
            else ""
        )
        + (
            f'<p class="lt">{esc(w["blocks_head"])}</p><ul class="ctimes">{blocks}</ul>'
            if blocks
            else ""
        )
        + (f'<p class="tref-line">{refs}</p>' if refs else "")
    )
    # HB-173 (HBD-390; DN-028 ADDENDUM-04 decision 5; Issue 54dfacf4), as DN-028
    # ADDENDUM-14 decision 10 amends it: under the stable treatment the times above
    # are the moving cloud's, from its run at the stated vertical setting, and a place
    # inside SLAB's extent check only has none, and says why
    from hazbrief.brief import agreement as AG

    ag = (brief.derived or {}).get("agreement") or {}
    if ag.get("planning"):
        untimed = AG.untimed_places(cl, ag)
        vres = float(ag.get("vertical_setting_m") or 0.0)
        head = (
            w["headline_slab"].format(head=head, n=len(untimed), vres=vres)
            if untimed
            else w["headline_slab_none"].format(head=head, vres=vres)
        )
        ps = cfg["map"]["planning"]
        body = (
            f'<p class="lt">{esc(w["slab_full"].format(vres=vres))} '
            f"{tevv.link_html(cfg, 'planning_shape')} "
            f"{tevv.link_html(cfg, 'conditions_scichem')}</p>"
            + (
                f'<p class="lt">{esc(w["slab_head"])}</p><ul class="ctimes">'
                + "".join(
                    # its own attribute: the place's measured line (data-place)
                    # is the cloud's, and this one has no time
                    f'<li data-untimed="{attr(u["id"])}">'
                    + esc(
                        w["planning_place"].format(
                            name=u["name"] or w["unnamed"],
                            tier=u["tier"],
                            engine=ps["engine"][u["engine"]],
                        )
                    )
                    + "</li>"
                    for u in untimed
                )
                + "</ul>"
                if untimed
                else ""
            )
            + body
        )
    return (
        f'<li class="lrow" data-row="cloud_times" id="cloud-times"><details><summary>'
        f'<span class="ln" id="cloud-clear">{esc(head)}</span> '
        f'<span class="n" id="cloud-roadblocks">{esc(blocks_line)}</span>'
        f'</summary><div class="lx">{body}</div></details></li>'
    )


def _cloud_time_config(brief, cfg) -> dict | None:
    """The time control's steps from the modelled cloud (HB-163), or None where no
    cloud is drawn."""
    from datetime import timedelta

    from hazbrief.brief import derive as D
    from hazbrief.evidence import store as S

    d = (brief.derived or {}).get("cloud") or {}
    if d.get("state") != "drawn" or not d.get("steps"):
        return None
    tc = cfg["web"]["time_control"]
    wf = (brief.derived or {}).get("wind_field") or {}
    last_hour = max(len(wf.get("hours") or []) - 1, 0)
    release = S.parse_time(d["release_utc"])
    met = sorted(
        ((S.parse_time(m["time"]), m) for m in d.get("met") or []),
        key=lambda x: x[0],
    )
    rows = []
    # HB-192 (DN-024 ADDENDUM-01 decision 5): the steps are the frames where held
    for s in layers.time_steps(d):
        m = int(s["minute"])
        at = release + timedelta(minutes=m)
        held = [x for t, x in met if t <= at]
        w = held[-1] if held else None
        rows.append(
            {
                "minute": m,
                "hplus": D.hplus(m),
                "clock": D._clock(brief, m),
                "hour": min(m // 60, last_hour) if wf.get("hours") else None,
                "wind_text": tc["wind"].format(
                    deg=round(float(w["direction_deg"])),
                    kmh=round(float(w["speed_m_s"]) * 3.6, 1),
                    source="forecast",
                )
                if w
                else tc["no_wind"],
                "pop_n": None,
                "pop_text": tc["cloud_pop"],
            }
        )
    return {
        "steps": rows,
        "open_index": 0,
        "play_ms": int(tc["play_ms"]),
        "words": {k: tc[k] for k in ("play", "pause", "past", "animate", "stop")},
        "cloud": True,
        # HB-192: the status line's words for a live page's frames as they land
        "frames": _frames_status(d, tc) if d.get("frames_run") else None,
        "keep": list(tc["animate_keep"]),
        # HB-222 item 1: left as the reader had them (the roads image), never switched
        "leave": list(tc["animate_leave"]),
        "viewed": layers.cloud_level_ids(cfg) + [cfg["map"]["cloud"]["extent"]["id"]],
    }


def _frames_status(d: dict, tc: dict) -> dict:
    """HB-192 (DN-024 ADDENDUM-01 decision 4): the status line under the time control:
    how far the run has computed and at what setting. On the built page the run is
    whole ("done"); a live page rewrites it as each frame lands (`shell.js`,
    `cloud_frame`), from `live` with {to}, {of}, {k}, {n} and {setting}."""
    from hazbrief.brief import derive as D

    fr = d["frames_run"]
    fs = tc["frames"]
    setting = (
        fs["setting"].format(m=f"{float(fr['vertical_setting_m']):g}")
        if fr.get("vertical_setting_m") is not None
        else fs["no_setting"]
    )
    last = fr.get("last_min")
    title = fs["title"].format(
        n=fr["count"],
        every=fr["every_min"],
        to=D.hplus(last) if last is not None else D.hplus(0),
        setting=setting,
        first_s=f"{float(fr['first_s']):.0f}" if fr.get("first_s") is not None else "?",
        last_s=f"{float(fr['last_s']):.0f}" if fr.get("last_s") is not None else "?",
        made=fs["made"].get(fr.get("made") or "", fs["made"]["run"]),
    )
    done = fs["done"].format(
        n=fr["count"],
        every=fr["every_min"],
        to=D.hplus(last) if last is not None else D.hplus(0),
        setting=setting,
    )
    return {
        "done": done,
        "title": title,
        "live": fs["live"],
        "setting": setting,
        "of": D.hplus(int(fr["until_min"])),
        "n": fr["count"],
        "lookup": fs["lookup"],
        "kg": fr["levels_kg"],
        "below_levels": fs["below_levels"],
    }


def _time_control_html(brief, cfg) -> str:
    """HB-157 item 12: the control along the map's lower edge (inside the map region,
    above the tab bar; ADDENDUM-01 section 3): play, the range of steps and one button
    per step, the step's "H+" and clock time, its wind chip and the residents under the
    area reached; the run's level, end and one-wind note. Built from buttons and a
    range input only (HBD-328). Where no step ran, one line says why."""
    # HB-162R (DN-025): a passive release's cloud at a time is the puff's section
    cfg = tevv.brief_cfg(cfg, brief)
    tc = cfg["web"]["time_control"]
    t = _time_config(brief, cfg)
    tl = ((brief.derived or {}).get("puff") or {}).get("timeline") or {}
    if t is None:
        why = tl.get("reason") or tc["none"]
        return (
            f'<p class="pl" id="time-none">{esc(tc["none_line"].format(why=why))}</p>'
        )
    i = t["open_index"]
    s = t["steps"][i]
    cloud = bool(t.get("cloud"))
    # HB-163: the cloud's steps are every 5 minutes for hours; a button marks every
    # `button_every_min` minutes and the slider holds every step
    every = int(tc["button_every_min"]) if cloud else 1
    btns = "".join(
        f'<button type="button" data-step="{k}" aria-current='
        f'"{"step" if k == i else "false"}">{esc(r["hplus"])}</button>'
        for k, r in enumerate(t["steps"])
        if not cloud or int(r["minute"]) % every == 0
    )
    play = (
        f'<button type="button" id="time-play" aria-pressed="false" '
        f'aria-label="{attr(tc["animate_aria"])}" data-animate="1">'
        f"{esc(tc['animate'])}</button>"
        if cloud
        else f'<button type="button" id="time-play" aria-pressed="false">'
        f"{esc(tc['play'])}</button>"
    )
    note = "cloud_at_time" if cloud else "time_steps"
    return (
        f'<div id="time-control" role="group" aria-label="{attr(tc["aria"])}">'
        f"{play}"
        f'<input type="range" id="time-step" min="0" max="{len(t["steps"]) - 1}" '
        f'value="{i}" step="1" aria-label="{attr(tc["range_aria"])}">'
        f'<span id="time-steps">{btns}</span>'
        f'<output id="time-now">{esc(s["hplus"])} &middot; {esc(s["clock"])}</output>'
        # HB-192 (DN-024 ADDENDUM-01 decision 4): how far the run has computed and at
        # what setting, beside the step's time (the full sentence as its title); a live
        # page rewrites it as each frame lands
        + (
            f' <output class="pl" id="frames-status" role="status" '
            f'title="{attr(t["frames"]["title"])}">{esc(t["frames"]["done"])}</output>'
            if t.get("frames")
            else ""
        )
        # two rows: the controls, then the step's wind chip, figure and the run's note
        + '<span class="tc-break"></span>'
        f'<span class="chip" id="time-wind">{esc(s["wind_text"])}</span>'
        f'<span id="time-pop">{esc(s["pop_text"])}</span>'
        # HB-161: the run's end and its one wind are the time steps' TEVV section
        # (T44); the note under the control is that section's number, and a wind
        # shift is its Verify item in the checklist
        f'<p class="pl" id="time-note">{tevv.link_html(cfg, note)}</p></div>'
    )


def _header(brief, cfg, title: str) -> str:
    page = cfg["page"]
    given = (
        f" &middot; as given {esc(L.when(brief.as_given, brief.time_zone))}"
        if brief.as_given
        else ""
    )
    return (
        f'<header id="top"><div class="banner">{esc(page["banner"])}</div>'
        f'<div class="bar"><h1>{esc(title)}</h1><span class="meta">Scenario '
        f"<code>{esc(brief.scenario_id)}</code>{given}</span>"
        # HB-161 ADDENDUM-01 item 4: one link to the TEVV page, at its top
        f'<a id="tevv-link" href="{attr(cfg["tevv"]["file"])}" target="_blank" '
        f'rel="noopener">{esc(cfg["tevv"]["link_text"])}</a>'
        # HB-171 item 9: the Timeline page's link, beside TEVV's
        f"{threat.link_html(cfg)}"
        # HB-215 Part B item 8: one control from the page's top to the Sources view
        f"{sources_link(brief, cfg)}</div></header>"
    )


def sources_link(brief, cfg) -> str:
    """The static page's one control to its Sources and MCP servers view (HB-215 Part
    B item 8): a link to the annex, which the page's script opens (`openHash`), with
    the board's counts in words (`data_sources.board.link`)."""
    spec = cfg["data_sources"]["board"]
    counts = data_sources.board_counts(data_sources.board(brief, cfg))
    said = ", ".join(
        f"{counts[k]} {spec['statuses'][k]['words']}"
        for k in spec["precedence"]
        if counts.get(k)
    )
    return (
        f'<a id="sources-link" href="#data-sources">'
        f"{esc(spec['link'].format(counts=said))}</a>"
    )


def _chips(brief, cfg) -> str:
    """The section status chips, one per section in render order with its state, each
    a link to its section: a row below the map, not above it (HB-141 F10; HBD-224)."""
    from hazbrief.brief.orchestrator import RENDER_ORDER

    # HB-158 ADDENDUM-01 item 2: each chip names its section and its one of three states
    chips = "".join(
        f'<a class="chip-link" href="#section-{attr(n)}">'
        f"{esc(cfg['sections'][n]['title'])}: {section_mark(brief, cfg, n)}</a>"
        for n in RENDER_ORDER
    )
    return f'<nav class="status" id="status">{chips}</nav>'


CSS = """
:root {{ --accent: {accent}; --grey: {grey}; --text: {text}; }}
body {{ font-family: {font}; color: {text}; background: #ffffff; margin: 0; }}
#top {{ position: fixed; top: 0; left: 0; right: 0; height: {header}px; z-index: 2000;
        background: #ffffff; border-bottom: 1px solid #cccccc; overflow: hidden; }}
.banner {{ background: {accent}; color: #ffffff; font-weight: bold; text-align: center;
          letter-spacing: 0.2em; font-size: 14px; line-height: 24px; height: 24px; }}
#bottom {{ position: fixed; bottom: 0; left: 0; right: 0; height: {footer}px;
          line-height: {footer}px; z-index: 2000; }}
.bar {{ padding: 4px 16px; display: flex; flex-wrap: wrap; align-items: baseline;
        gap: 4px 16px; }}
.bar h1 {{ font-size: 20px; margin: 0; }}
.meta {{ color: {grey}; font-size: 13px; }}
.status {{ display: flex; flex-wrap: wrap; gap: 4px; padding: 8px 16px;
           border-bottom: 1px solid #cccccc; }}
.status a {{ font-size: 12px; text-decoration: none; padding: 1px 6px;
            border-radius: 3px;
            border: 1px solid #dddddd; color: {text}; }}
.st {{ white-space: nowrap; }}
.st .mk {{ font-size: 1.05em; }}
.st-failed {{ color: {accent} !important; font-weight: bold;
             border-color: {accent} !important; }}
.st-retrieving {{ color: {grey} !important; }}
.st-retrieved {{ color: #166534 !important; }}
#section-map {{ margin-top: {header}px; }}
#workbench {{ display: flex; height: calc(100vh - {header}px - {footer}px); }}
#map-wrap {{ position: relative; flex: 1 1 auto; min-width: 0; }}
#map {{ position: absolute; inset: 0; background: #f2f2f2; }}
#map-wrap:has(#time-control) #map {{ bottom: 64px; }}
#map-wrap:has(#time-control) #layer-control {{ max-height: calc(100% - 104px); }}
#time-control {{ position: absolute; left: 0; right: 0; bottom: 0; height: 64px;
                box-sizing: border-box; padding: 4px 8px; background: #ffffff;
                border-top: 1px solid #999999; font-size: 13px; display: flex;
                flex-wrap: wrap; align-items: center; gap: 4px 8px; overflow: hidden; }}
#time-control #time-steps {{ display: inline-flex; gap: 2px; overflow-x: auto;
                            max-width: 55%; flex-wrap: nowrap; }}
#time-control button {{ font-size: 12px; padding: 1px 6px; white-space: nowrap; }}
#time-control button[aria-current="step"] {{ background: {text}; color: #ffffff; }}
#time-control #time-now {{ font-weight: bold; white-space: nowrap; }}
#time-control .tc-break {{ flex-basis: 100%; height: 0; }}
#time-control #time-wind, #time-control #time-pop {{ white-space: nowrap; }}
#time-control #time-note {{ flex: 1 1 0; min-width: 0; margin: 0; color: {grey};
                           white-space: nowrap; overflow: hidden;
                           text-overflow: ellipsis; }}
#map-note {{ position: absolute; left: 50px; right: 12px; top: 10px; z-index: 1000;
            background: #ffffff; border: 1px solid {accent}; color: {accent};
            padding: 6px 10px; font-size: 14px; font-weight: bold; }}
#map-note[hidden] {{ display: none; }}
#layer-control {{ position: absolute; top: 10px; right: 10px; z-index: 1001;
                 max-height: calc(100% - 40px); width: 320px; overflow-y: auto;
                 background: #ffffff; border: 1px solid #999999;
                 box-shadow: 0 1px 4px rgba(0, 0, 0, 0.3); padding: 4px 10px;
                 font-size: 14px; }}
#layer-control:not([open]) {{ width: auto; }}
#map-wrap:has(#layer-control[open]) #map-note {{ right: 344px; }}
#layer-control h2 {{ font-size: 15px; margin: 2px 0; }}
#layer-control h3 {{ font-size: 13px; margin: 8px 0 4px; }}
#layer-control ul {{ margin: 4px 0; padding-left: 18px; }}
#layer-control li {{ font-size: 13px; line-height: 1.3; margin: 2px 0; }}
#basemaps {{ border: none; padding: 0; margin: 4px 0 6px; }}
#basemaps legend {{ font-weight: bold; font-size: 13px; padding: 0; }}
#basemaps label {{ display: block; font-size: 13px; }}
#panel {{ flex: 0 0 380px; overflow-y: auto; padding: 8px 16px 16px;
          border-left: 1px solid #cccccc; font-size: 14px; }}
#panel h2 {{ font-size: 17px; margin: 10px 0 6px; border-bottom: 2px solid {accent};
            padding-bottom: 2px; }}
#panel h3 {{ font-size: 14px; margin: 10px 0 4px; }}
#panel ul {{ margin: 4px 0; padding-left: 18px; }}
#panel li {{ font-size: 14px; line-height: 1.35; margin: 2px 0; }}
#panel li.h {{ list-style: none; margin-left: -18px; font-weight: bold;
               margin-top: 6px; }}
ul.dist li {{ margin-bottom: 4px; }}
#layer-list, ul.ramp {{ list-style: none; padding-left: 0 !important; }}
ul.ramp {{ display: flex; flex-wrap: wrap; gap: 2px 10px;
           margin-left: 24px !important; }}
ul.ramp li {{ font-size: 12px !important; }}
.n {{ color: {grey}; font-size: 12px; }}
.sw {{ display: inline-block; vertical-align: middle; margin-right: 4px; }}
.sw-dot {{ width: 11px; height: 11px; border-radius: 50%; }}
.hb-sym {{ background: none; border: 0; }}
.hb-sym svg, .sw-sym svg {{ display: block; }}
ul.syms {{ list-style: none; margin: 2px 0 4px 24px !important;
           padding-left: 0 !important; }}
ul.syms li {{ font-size: 12px !important; display: flex; align-items: center;
              gap: 4px; }}
.sw-bar {{ width: 16px; height: 4px; }}
.sw-box {{ width: 14px; height: 11px; opacity: 0.8; }}
.sw-pat {{ width: 22px; height: 14px; }}
.lg {{ font-size: 12px; margin: 2px 0 6px 24px; }}
.q, .pg, .pl {{ color: {grey}; }}
.pg {{ font-size: 12px; white-space: nowrap; }}
.pl {{ font-size: 12px; margin: 4px 0; overflow-wrap: anywhere; }}
.tref-line {{ font-size: 11px; margin: 2px 0; }}
a.tref {{ font-size: 11px; color: {grey}; font-variant-numeric: tabular-nums; }}
.open-key {{ vertical-align: middle; margin-right: 4px; }}
ul.missing li {{ color: {grey}; font-size: 13px; }}
ul.missing .why {{ display: block; font-size: 12px; margin-left: 18px; }}
li.lgroup h3 {{ font-size: 13px; margin: 2px 0 1px; padding-bottom: 1px;
               border-bottom: 1px solid #dddddd; white-space: nowrap;
               overflow: hidden; text-overflow: ellipsis; }}
/* HB-158 item 3: a layer row is one line; its detail opens under it */
li.lrow {{ margin: 0 !important; }}
li.lrow > details > summary {{ list-style: none; display: flex; align-items: center;
                               gap: 2px; white-space: nowrap; line-height: 19px;
                               min-height: 19px; }}
li.lrow > details > summary::-webkit-details-marker {{ display: none; }}
li.lrow > details > summary::after {{ content: "\\25B8"; color: {grey};
                                      font-size: 9px; margin-left: 1px; }}
li.lrow > details[open] > summary::after {{ content: "\\25BE"; }}
li.lrow .ln {{ overflow: hidden; text-overflow: ellipsis; min-width: 0;
              flex: 1 1 auto; }}
li.lrow .sw {{ margin-right: 1px; }}
li.lrow .n {{ margin-left: auto; padding-left: 4px; flex: none; }}
li.lrow .lx {{ padding: 0 0 4px 22px; }}
li.lrow .lt {{ font-size: 12px; font-weight: bold; margin: 2px 0; }}
li.lrow.lnone summary {{ color: {grey}; }}
li.lrow.lnone .sw {{ opacity: 0.45; }}
/* HB-171 item 10: the threat timeline's next rows, one line each, above the Hazard
   rows; a row moves the time control, its number opens the row on the Timeline page */
li.tnext {{ margin: 0 !important; }}
li.tnext ul.tn-rows {{ list-style: none; margin: 0; padding: 0; }}
li.tnext li {{ display: flex; align-items: center; white-space: nowrap;
              line-height: 19px; min-height: 19px; margin: 0 !important; }}
li.tnext button.tn-go {{ flex: 1 1 auto; min-width: 0; overflow: hidden;
                        text-overflow: ellipsis; text-align: left; border: 0;
                        background: none; padding: 0; font: inherit; cursor: pointer;
                        white-space: nowrap; }}
li.tnext button.tn-go .clock {{ font-weight: bold;
                             font-variant-numeric: tabular-nums; }}
li.tnext svg.sw {{ vertical-align: middle; margin: 0 3px; }}
li.tnext a.tn-ref {{ flex: none; font-size: 11px; color: {grey}; padding-left: 4px; }}
li.tnext li.tn-more a {{ font-size: 12px; color: {grey}; }}
.lbox {{ display: inline-flex; }}
.vh {{ position: absolute; width: 1px; height: 1px; overflow: hidden;
      clip: rect(0 0 0 0); white-space: nowrap; }}
#layer-gaps > summary {{ font-size: 13px; color: {grey}; margin-top: 6px; }}
table.data-sources td ul {{ margin: 0; padding-left: 16px; }}
table.data-sources .tool {{ font-weight: bold; }}
table.data-sources .why {{ display: block; color: {grey}; font-size: 12px; }}
.board h4 {{ margin: 10px 0 2px; font-size: 14px; }}
.board .none {{ color: {grey}; }}
table.board-rows td {{ font-size: 13px; padding: 2px 10px 2px 0; vertical-align: top; }}
table.board-rows td.asof {{ color: {grey}; }}
.bst {{ font-weight: bold; white-space: nowrap; }}
.bst-answered, .bst-recorded {{ color: #166534; }}
.bst-failed {{ color: {accent}; }}
.bst-not_called, .bst-pending {{ color: {grey}; }}
table.derived th, table.derived td {{ font-size: 12px; padding: 2px 6px 2px 0; }}
table.wx-strip {{ margin: 4px 0; }}
table.wx-strip th, table.wx-strip td {{ font-size: 11px; text-align: center;
                                       padding: 2px 3px; }}
.wx-obs {{ border-right: 2px solid {grey}; }}
.wx-erg {{ border-right: 2px dashed {accent}; }}
.wx-arrow {{ display: inline-block; font-size: 16px; line-height: 16px; }}
.wx-na {{ color: {grey}; }}
.wx-src {{ color: {grey}; font-size: 10px; }}
.fa-wind {{ margin: 4px 0; }}
main {{ max-width: 1080px; margin: 0 auto; padding: 16px 32px {main_bottom}px; }}
details summary {{ cursor: pointer; }}
details summary h2 {{ display: inline; }}
summary .st {{ font-size: 13px; margin-left: 8px; color: {grey}; }}
section > details {{ margin-top: 18px; border-bottom: 2px solid {accent};
                    padding-bottom: 6px; }}
h3, h4 {{ font-size: 16px; margin: 18px 0 6px; }}
main p, main li, main td, main th {{ font-size: 15px; line-height: 1.4;
                                     overflow-wrap: anywhere; }}
.lede, .note, .sources, .pending {{ color: {grey}; }}
.sources {{ font-size: 13px; border-top: 1px solid #dddddd; padding-top: 6px; }}
.degraded, .stale {{ color: {accent}; font-weight: bold; }}
.caveat {{ color: {accent}; font-weight: bold; }}
table {{ border-collapse: collapse; margin: 8px 0; }}
th, td {{ text-align: left; vertical-align: top; padding: 4px 10px 4px 0;
         border-bottom: 1px solid #eeeeee; }}
table.kv th {{ color: {grey}; font-weight: normal; width: 260px; }}
code {{ font-size: 12px; color: {grey}; }}
.prio {{ display: inline-block; min-width: 56px; color: {grey}; }}
.prio-high {{ color: {accent}; font-weight: bold; }}
a {{ color: {accent}; }}
.hb-pop {{ font-size: 13px; max-width: 320px; }}
.hb-pop th {{ color: {grey}; font-weight: normal; padding: 1px 8px 1px 0; }}
.hb-pop td {{ padding: 1px 0; }}
.hb-pop .pl {{ font-size: 11px; }}
@media (max-width: 820px) {{
  #top {{ position: static; height: auto; }}
  #section-map {{ margin-top: 0; }}
  #workbench {{ flex-direction: column; height: auto; }}
  #map-wrap {{ height: 70vh; }}
  #layer-control {{ width: 240px; }}
  #panel {{ flex: none; border-left: none; }}
  main {{ padding: 16px 16px {main_bottom}px; }}
}}
"""

# The map, bound to Google when a key is set and its script loads, else to Leaflet
# (inlined, so it draws offline). The layers are the same GeoJSON either way; the layer
# list in the panel is the one control for both. `#map[data-drawn]` records what was
# drawn (engine, features per layer, each zone's bounds), for the headless-browser test.
#: HB-157 item 12: the time-step control's script, in its own file (ADDENDUM-01 item 5:
#: live.js keeps its 700-line bound), inlined before the map script on the static page
#: and the live shell; the map script calls `window.hbTime` once its layers are drawn.
TIME_JS = (Path(__file__).parent / "static" / "time.js").read_text(encoding="utf-8")
MAP_JS = """
(function () {
  var D = JSON.parse(document.getElementById('map-data').textContent);
  var C = JSON.parse(document.getElementById('map-config').textContent);
  var el = document.getElementById('map');
  var noteEl = document.getElementById('map-note');
  var started = false;
  function note(text) { noteEl.textContent = text; noteEl.hidden = false; }
  function openHash() {
    var t = document.getElementById(location.hash.slice(1));
    var d = t && t.querySelector('details');
    if (d) { d.open = true; }
  }
  window.addEventListener('hashchange', openHash); openHash();
  // HB-215 Part B: the Sources view's basemap rows are the browser's call, not the
  // brief's: a tile that loads marks its row answered, a basemap that fails marks it
  // failed (each row prints all its marks, one shown); a view loaded later (the
  // shell's tab) is marked by `hbBaseApply` when it lands
  window.hbBase = window.hbBase || {};
  window.hbBaseApply = function (root) {
    Object.keys(window.hbBase).forEach(function (k) {
      var tr = root && root.querySelector('tr[data-source="' + k + '"]');
      if (!tr) { return; }
      var b = window.hbBase[k];
      tr.dataset.status = b.status;
      tr.querySelectorAll('.bst').forEach(function (m) {
        m.hidden = m.dataset.status !== b.status;
      });
      tr.querySelector('td.asof').textContent = b.at;
    });
  };
  function baseMark(key, status) {
    var was = window.hbBase[key];
    if (was && was.status === 'answered') { return; }
    window.hbBase[key] = {status: status, at: new Date().toLocaleString()};
    window.hbBaseApply(document);
  }
  // a table with class "sortable" sorts by the clicked heading, numbers as numbers
  var sortable = document.querySelectorAll('table.sortable');
  Array.prototype.forEach.call(sortable, function (t) {
    Array.prototype.forEach.call(t.rows[0].cells, function (th, i) {
      th.style.cursor = 'pointer';
      th.addEventListener('click', function () {
        var rows = Array.prototype.slice.call(t.rows, 1);
        var asc = th.dataset.dir !== 'asc';
        th.dataset.dir = asc ? 'asc' : 'desc';
        rows.sort(function (a, b) {
          var x = a.cells[i].textContent, y = b.cells[i].textContent;
          var num = /^-?[0-9.,]+$/;
          var c = (num.test(x) && num.test(y))
            ? parseFloat(x.replace(/,/g, '')) - parseFloat(y.replace(/,/g, ''))
            : x.localeCompare(y);
          return asc ? c : -c;
        });
        rows.forEach(function (r) { t.tBodies[0].appendChild(r); });
      });
    });
  });
  if (el.dataset.state !== 'rendered') { return; }
  var byId = {};
  D.layers.forEach(function (l) { byId[l.id] = l; });
  var boxes = Array.prototype.slice.call(
    document.querySelectorAll('#layer-list input[data-layer]'));
  function drawn(engine, counts, bounds) {
    el.dataset.drawn = JSON.stringify({engine: engine, layers: counts, bounds: bounds});
  }
  function fc(l) { return {type: 'FeatureCollection', features: l.features}; }
  // the popup HTML and the label lines are escaped when the page is built
  // HB-161 item 5: the measurement, then the layer's TEVV section number, a link that
  // opens the section in a new tab (one `tevv` entry per layer, not per feature)
  function popup(l, html, labs) {
    var ref = l.tevv ? '<p class="tref-line"><a class="tref" target="_blank" ' +
      'rel="noopener" href=' + JSON.stringify(l.tevv.href) + '>' + l.tevv.ref +
      '</a></p>' : '';
    return '<div class="hb-pop">' + html + (labs || []).map(function (i) {
      return '<p class="pl">' + l.labels[i] + '</p>';
    }).join('') + ref + '</div>';
  }
  // HB-103 step 6: the weather layers' switches are remembered for the session. Storage
  // can be refused (a sandboxed frame); the page then keeps each switch's default.
  function recall(id) {
    if (C.remember.indexOf(id) < 0) { return null; }
    try { return window.sessionStorage.getItem('hazbrief.layer.' + id); }
    catch (e) { return null; }
  }
  function keep(id, on) {
    if (C.remember.indexOf(id) < 0) { return; }
    try { window.sessionStorage.setItem('hazbrief.layer.' + id, on ? '1' : '0'); }
    catch (e) { return; }
  }
  boxes.forEach(function (b) {
    var r = recall(b.dataset.layer);
    if (r !== null) { b.checked = r === '1'; }
  });
  function wire(setOn) {
    boxes.forEach(function (b) {
      setOn(b.dataset.layer, b.checked);
      b.addEventListener('change', function () {
        keep(b.dataset.layer, b.checked); setOn(b.dataset.layer, b.checked);
      });
    });
  }
  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  // The wind field (HB-103 Part B): one arrow per gridpoint cell, an SVG drawn here, a
  // circle where the cell's grid holds no forecast for the hour; the hour stepper reads
  // the forecast window's rows. `put(lat, lon, svg, px)` places one symbol.
  var W = C.wind_field;
  function arrowSvg(from, kmh, px, color, title, full, opacity) {
    var len = W.max_speed > 0 ? Math.max(px * kmh / W.max_speed, 6) : 6;
    if (full) { len = px; }
    var h = len / 2, to = (from + 180) % 360;
    return '<svg xmlns="http://www.w3.org/2000/svg" width="' + px + '" height="' + px +
      '" viewBox="' + (-px / 2) + ' ' + (-px / 2) + ' ' + px + ' ' + px + '">' +
      '<title>' + esc(title) + '</title><g transform="rotate(' + to + ')" stroke="' +
      color + '" stroke-width="' + (full ? 3 : 2) + '" fill="none" ' +
      'opacity="' + opacity + '" ' +
      'stroke-linecap="round"><path d="M0,' + h + ' L0,' + (-h) + ' M-4,' +
      (-h + 6) + ' L0,' + (-h) + ' L4,' + (-h + 6) + '"/></g></svg>';
  }
  function blankSvg(px, color, title, calm, opacity) {
    return '<svg xmlns="http://www.w3.org/2000/svg" width="' + px + '" height="' + px +
      '" viewBox="-6 -6 12 12"><title>' + esc(title) + '</title><circle r="4" ' +
      'stroke="' + color + '" stroke-width="1.5" fill="' + (calm ? color : 'none') +
      '" opacity="' + opacity + '"/></svg>';
  }
  function windField(put, clear) {
    if (!W) { return; }
    var slider = document.getElementById('wind-hour');
    var label = document.getElementById('wind-hour-label');
    var noteP = document.getElementById('wind-hour-note');
    function at(h) {
      clear();
      var arrows = 0, circles = 0, own = 0;
      // HB-141 F1: an arrow is the wind at the stepped hour, and nothing else is an
      // arrow. A cell whose grid holds no forecast for the hour (read at its nearest
      // covered hour, a third value) is an open circle with what it holds in its
      // title, never an arrow from another hour. The footprint's own cell is drawn
      // full; every other cell is muted.
      W.cells.forEach(function (c) {
        var r = c.rows[h], t = c.title + '; ' + W.hours[h];
        var o = c.own ? 1 : W.muted_opacity;
        if (c.own) { own += 1; }
        if (r === null) {
          put(c.lat, c.lon,
              blankSvg(12, W.color, t + ': no forecast for this hour', false, o), 12);
          circles += 1;
        } else if (r.length > 2) {
          put(c.lat, c.lon, blankSvg(12, W.color, t + ': no forecast for this hour; ' +
            r[2] + ' it reads from ' + r[0] + ' degrees, ' + r[1] + ' km/h', false, o),
            12);
          circles += 1;
        } else if (r[1] === 0) {
          put(c.lat, c.lon, blankSvg(12, W.color, t + ': calm', true, o), 12);
          circles += 1;
        } else {
          put(c.lat, c.lon, arrowSvg(r[0], r[1], W.arrow_px, W.color,
            t + ': from ' + r[0] + ' degrees, ' + r[1] + ' km/h' +
            (c.own ? '; ' + W.own_title : ''), c.own, o), W.arrow_px);
          arrows += 1;
        }
      });
      if (W.footprint) {
        var f = W.footprint;
        put(f.lat, f.lon, arrowSvg(f.dir, f.speed, W.footprint_px, W.accent,
          f.title + ': from ' + f.dir + ' degrees, ' + f.speed + ' km/h', true, 1),
          W.footprint_px);
      }
      if (label) { label.textContent = W.hours[h]; }
      if (noteP) { noteP.textContent = W.notes[h]; }
      el.dataset.windField = JSON.stringify({hour: h, arrows: arrows, circles: circles,
                                             own: own, cells: W.cells.length,
                                             footprint: !!W.footprint});
    }
    if (slider) {
      slider.addEventListener('input', function () { at(parseInt(slider.value, 10)); });
    }
    at(slider ? parseInt(slider.value, 10) : 0);
  }

  // HB-157 item 12: the time control's step. A feature carrying a `step` shows only at
  // the control's current step (`window.hbStep`, set from `map-config`'s `time` at
  // its opening step); `static/time.js` moves it and calls the branch's restyle.
  function stepStart() {
    window.hbStep = C.time ? C.time.steps[C.time.open_index].minute : null;
    // HB-163 item 5: a cloud feature carries its `view`, "path" (the area its level
    // reaches at any time, the default) or "time" (its area at its step); the page
    // opens on the harm path and Animate or the step control shows the cloud at a time
    window.hbView = 'path';
  }
  function stepOk(f) {
    var p = f.properties ? f.properties.step : f.getProperty('step');
    var v = f.properties ? f.properties.view : f.getProperty('view');
    if (v !== undefined && v !== null && v !== window.hbView) { return false; }
    return p === undefined || p === null || p === window.hbStep;
  }
  // HB-155 ADDENDUM-01 item 6: a feature with `area_m` (the services in the area) shows
  // within the reader's radius (`window.hbArea`, metres; 0 is "widen to nearest"), and
  // its
  // class's nearest shows when none of its class is inside; set from `map-config`
  // `area`
  window.hbArea = C.area ? C.area.radius_m : null;
  function prop(f, k) { return f.properties ? f.properties[k] : f.getProperty(k); }
  function areaOk(f, l) {
    var a = prop(f, 'area_m');
    if (a === undefined || a === null || window.hbArea === null) { return true; }
    if (a <= window.hbArea) { return true; }
    if (!prop(f, 'nearest')) { return false; }
    var cls = prop(f, 'service');
    return !l.features.some(function (g) {
      return g.properties.service === cls && g.properties.area_m <= window.hbArea;
    });
  }
  function stepWire(restyle, setOn) {
    if (C.time && window.hbTime) { window.hbTime(C.time, restyle, setOn); }
  }

  function leaflet(why) {
    if (started) { return; } started = true;
    if (why) { note(why); }
    var map = L.map(el, {zoomSnap: 0.25});
    var panes = {choropleth: 405, polygon: 410, line: 420, point: 430};
    Object.keys(panes).forEach(function (k) {
      map.createPane('hb-' + k).style.zIndex = panes[k];
    });
    // the basemaps, switched by the layer control's radios (HB-141 F7): the first
    // (the street map) opens, except on a page opened from a file, which opens on the
    // first tile whose policy needs no Referer and says so (`map.file_basemap_note`)
    var bases = [], first = null, failed = 0, loaded = 0;
    var fromFile = window.location.protocol === 'file:';
    C.tiles.forEach(function (t, i) {
      var tl = L.tileLayer(t.url, {attribution: t.attribution, maxZoom: t.max_zoom,
                                   maxNativeZoom: t.max_zoom});
      tl.on('tileerror', function () { failed += 1; check(); });
      tl.on('tileload', function () {
        loaded += 1; baseMark('tile_' + i, 'answered');
      });
      bases.push(tl);
      if (first === null && !(fromFile && t.needs_referer)) { first = i; }
    });
    if (first === null) { first = 0; }
    var radios = Array.prototype.slice.call(
      document.querySelectorAll('#basemaps input[name="basemap"]'));
    radios.forEach(function (r) {
      r.checked = parseInt(r.value, 10) === first;
      r.addEventListener('change', function () {
        if (!r.checked) { return; }
        bases.forEach(function (b) { map.removeLayer(b); });
        bases[parseInt(r.value, 10)].addTo(map);
      });
    });
    if (first !== 0) {
      var bn = document.getElementById('basemap-note');
      if (bn) {
        bn.textContent = C.file_basemap_note.replace('{name}', C.tiles[first].name);
        bn.hidden = false;
      }
    }
    var roads = C.roads ? L.imageOverlay(
      C.roads.src, C.roads.bounds, {attribution: C.roads_attribution, opacity: 0.85}
    ) : null;
    function check() {
      if (failed >= 4 && loaded === 0 && !check.done) {
        check.done = true;
        baseMark('tile_' + first, 'failed');
        // HB-161 item 9: over the map, a status key, not a sentence; every layer is
        // drawn from the evidence store whatever the basemap does
        note('Basemap tiles did not load' + (roads ? '; roads image shown' : ''));
        if (roads) { setOn('roads', true); }
      }
    }
    bases[first].addTo(map);
    L.control.scale({imperial: true, metric: true}).addTo(map);
    var objs = {}, counts = {}, bounds = {};
    stepStart();
    D.layers.forEach(function (l) {
      if (!l.features.length) { return; }
      var s = l.style, pane = 'hb-' + l.kind;
      objs[l.id] = L.geoJSON(fc(l), {
        pane: pane,
        // HB-157 item 12: a feature of one step shows only at the control's step;
        // HB-155: a service only within the reader's area radius
        filter: function (f) { return stepOk(f) && areaOk(f, l); },
        style: function (f) {
          // a patterned layer fills with its SVG pattern, which carries its own
          // tint and marks (HB-114; DN-019 section 2 item 3)
          // HB-178: a feature may carry its own weight (the grid's cut line)
          var w = f.properties.open ? 0 : (f.properties.weight || s.weight || 1);
          if (s.pattern) {
            return {color: s.color || s.fill, weight: w,
                    fillColor: 'url(#' + s.pattern + ')', fillOpacity: 1,
                    dashArray: s.dash || null};
          }
          // HB-173: a feature may carry its own outline colour (the planning shape
          // draws each level in the level's colour)
          return {color: f.properties.color || s.color || s.fill, weight: w,
                  fillColor: f.properties.fill || s.fill || s.color,
                  fillOpacity: s.fillOpacity === undefined ? 0.2 : s.fillOpacity,
                  opacity: f.properties.muted ? C.muted_opacity : 1,
                  dashArray: f.properties.dash || s.dash || null};
        },
        pointToLayer: function (f, ll) {
          // HB-152: a mapped marker class draws its FGDC (or hazbrief's own) SVG
          // symbol, coloured with the layer's fill (layers.symbol_svg); HB-157 item 8:
          // an inner-cordon candidate is drawn muted, never hidden
          var o = f.properties.muted ? C.muted_opacity : 1;
          // HB-163 ADDENDUM-04 item 1: a roadblock the cloud reaches draws its symbol
          // in the colour of the highest level reached there
          var rk = f.properties.reach && s.reach_symbols &&
            s.reach_symbols[f.properties.symbol + '|' + f.properties.reach];
          var sym = rk ||
            (f.properties.symbol && s.symbols && s.symbols[f.properties.symbol]);
          if (sym) {
            var px = s.symbol_px;
            return L.marker(ll, {pane: pane, keyboard: false, opacity: o,
              icon: L.divIcon({className: 'hb-sym', iconSize: [px, px],
                iconAnchor: [px / 2, px / 2], html: sym})});
          }
          return L.circleMarker(ll, {pane: pane, radius: s.radius || 6, color: s.color,
                                     weight: s.weight || 1,
                                     fillColor: f.properties.fill || s.fill,
                                     fillOpacity: s.fillOpacity * o, opacity: o});
        },
        onEachFeature: function (f, lay) {
          lay.bindPopup(popup(l, f.properties.popup, f.properties.labs),
                        {maxWidth: 340});
        }
      });
      counts[l.id] = l.features.length;
      // a stepped layer may hold no feature at the opening step (no bounds then)
      if (l.kind === 'polygon' && objs[l.id].getLayers().length) {
        var b = objs[l.id].getBounds();
        bounds[l.id] = [[b.getSouth(), b.getWest()], [b.getNorth(), b.getEast()]];
      }
    });
    if (roads) { objs.roads = roads; }
    ['radar', 'satellite'].forEach(function (id) {
      var r = C[id]; if (!r) { return; }
      objs[id] = L.tileLayer.wms(r.url, {
        layers: r.layer, format: 'image/png', transparent: true,
        version: '1.3.0', time: r.time, opacity: r.opacity,
        attribution: 'NOAA nowCOAST'});
    });
    Object.keys(C.snapshots).forEach(function (id) {
      var s = C.snapshots[id];
      objs[id + '_snapshot'] = L.imageOverlay(s.src, s.bounds,
        {opacity: 0.6, attribution: 'NOAA nowCOAST (stored snapshot)'});
    });
    if (W) {
      var wind = L.layerGroup();
      objs.wind_field = wind;
      windField(function (lat, lon, svg, px) {
        // interactive, so the pointer reaches the SVG's title (Leaflet sets
        // pointer-events: none on a non-interactive icon)
        wind.addLayer(L.marker([lat, lon], {interactive: true, keyboard: false,
          icon: L.divIcon({className: 'hb-wind', html: svg, iconSize: [px, px],
                           iconAnchor: [px / 2, px / 2]})}));
      }, function () { wind.clearLayers(); });
    }
    function setOn(id, on) {
      var o = objs[id]; if (!o) { return; }
      if (on) { o.addTo(map); } else { map.removeLayer(o); }
      boxes.forEach(function (b) { if (b.dataset.layer === id) { b.checked = on; } });
    }
    wire(setOn);
    if (D.extent) { map.fitBounds(D.extent, {padding: [C.padding, C.padding]}); }
    drawn('leaflet', counts, bounds);
    // HB-155: the hook the siting script (`static/siting.js`) moves points and redraws
    // layers through: a layer's features are redrawn from `byId` after a change
    window.hbMapApi = {
      map: map, layers: byId, objs: objs, setOn: setOn,
      redraw: function (id) {
        var l = byId[id], o = objs[id];
        if (!l) { return; }
        if (!o) {
          o = objs[id] = L.geoJSON(fc(l), {pane: 'hb-' + l.kind,
            style: function () { var s = l.style; return {color: s.color, weight:
            s.weight || 3,
              dashArray: s.dash || null}; },
            onEachFeature: function (f, lay) {
              lay.bindPopup(popup(l, f.properties.popup, f.properties.labs), {maxWidth:
              340});
            }});
          var b = document.querySelector('#layer-list input[data-layer="' + id + '"]');
          if (!b || b.checked) { o.addTo(map); }
          return;
        }
        o.clearLayers(); o.addData(fc(l));
      }
    };
    if (window.hbSiting) { window.hbSiting(window.hbMapApi); }
    stepWire(function () {
      D.layers.forEach(function (l) {
        if (l.stepped && objs[l.id]) {
          objs[l.id].clearLayers(); objs[l.id].addData(fc(l));
        }
      });
    }, setOn);
  }

  function google() {
    if (started) { return; } started = true;
    var g = window.google.maps;
    // Google's own map-type control switches its base (roadmap, the street map,
    // first); the layer control's fallback radios do not apply (HB-141 F7)
    var bm = document.getElementById('basemaps');
    if (bm) { bm.hidden = true; }
    var map = new g.Map(el, {
      mapTypeId: 'roadmap', mapTypeControl: true, scaleControl: true,
      streetViewControl: false,
      mapTypeControlOptions: {mapTypeIds: ['roadmap', 'satellite']}
    });
    g.event.addListenerOnce(map, 'tilesloaded', function () {
      baseMark('google', 'answered');
    });
    var info = new g.InfoWindow();
    var z = {choropleth: 1, polygon: 2, line: 3, point: 4};
    var objs = {}, counts = {}, bounds = {};
    stepStart();
    D.layers.forEach(function (l) {
      if (!l.features.length) { return; }
      var s = l.style, d = new g.Data();
      d.addGeoJson(fc(l));
      d.setStyle(function (f) {
        var fill = f.getProperty('fill') || s.fill || s.color;
        var m = f.getProperty('muted') ? C.muted_opacity : 1;
        var o = {strokeColor: f.getProperty('color') || s.color || s.fill,
                 strokeWeight: f.getProperty('open') ? 0 :
                   (f.getProperty('weight') || s.weight || 1),
                 strokeOpacity: m, fillColor: fill,
                 fillOpacity: (s.fillOpacity === undefined ? 0.2 : s.fillOpacity) * m,
                 visible: stepOk(f) && areaOk(f, l), zIndex: z[l.kind]};
        if (l.kind === 'point') {
          o.icon = {path: g.SymbolPath.CIRCLE, scale: s.radius || 6, fillColor: s.fill,
                    fillOpacity: s.fillOpacity, strokeColor: s.color,
                    strokeWeight: s.weight || 1};
          // HB-152: the same SVG symbol as the Leaflet branch, as a data URL image
          var cls = f.getProperty('symbol');
          var rk = f.getProperty('reach') && s.reach_symbols &&
            s.reach_symbols[cls + '|' + f.getProperty('reach')];
          var sym = rk || (cls && s.symbols && s.symbols[cls]);
          if (sym) {
            var px = s.symbol_px;
            o.icon = {url: 'data:image/svg+xml;charset=UTF-8,' +
                           encodeURIComponent(sym),
                      scaledSize: new g.Size(px, px),
                      anchor: new g.Point(px / 2, px / 2)};
          }
        }
        return o;
      });
      d.addListener('click', function (e) {
        info.setContent(popup(l, e.feature.getProperty('popup'),
                              e.feature.getProperty('labs')));
        info.setPosition(e.latLng); info.open({map: map});
      });
      objs[l.id] = d; counts[l.id] = l.features.length;
    });
    if (C.roads) {
      var rb = C.roads.bounds;
      objs.roads = new g.GroundOverlay(C.roads.src,
        {south: rb[0][0], west: rb[0][1], north: rb[1][0], east: rb[1][1]},
        {opacity: 0.85});
    }
    // a WMS GetMap per 256 px tile, its box in EPSG:3857 metres (radar, satellite)
    var half = 20037508.342789244;
    ['radar', 'satellite'].forEach(function (id) {
      var r = C[id]; if (!r) { return; }
      var mt = new g.ImageMapType({tileSize: new g.Size(256, 256),
        opacity: r.opacity, name: id,
        getTileUrl: function (c, zoom) {
          var size = 2 * half / Math.pow(2, zoom);
          var x0 = -half + c.x * size, y1 = half - c.y * size;
          return r.url + '?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&STYLES=' +
            '&LAYERS=' + encodeURIComponent(r.layer) + '&CRS=EPSG:3857' +
            '&BBOX=' + [x0, y1 - size, x0 + size, y1].join(',') +
            '&WIDTH=256&HEIGHT=256&FORMAT=image/png&TRANSPARENT=true' +
            '&TIME=' + encodeURIComponent(r.time);
        }});
      objs[id] = {setMap: function (m) {
        var i = map.overlayMapTypes.getArray().indexOf(mt);
        if (m && i < 0) { map.overlayMapTypes.push(mt); }
        if (!m && i >= 0) { map.overlayMapTypes.removeAt(i); }
      }};
    });
    Object.keys(C.snapshots).forEach(function (id) {
      var s = C.snapshots[id], sb = s.bounds;
      objs[id + '_snapshot'] = new g.GroundOverlay(s.src,
        {south: sb[0][0], west: sb[0][1], north: sb[1][0], east: sb[1][1]},
        {opacity: 0.6});
    });
    if (W) {
      var marks = [], windOn = false;
      windField(function (lat, lon, svg, px) {
        var m = new g.Marker({position: {lat: lat, lng: lon}, clickable: false,
          title: svg.split('<title>')[1].split('</title>')[0],
          icon: {url: 'data:image/svg+xml;charset=UTF-8,' + encodeURIComponent(svg),
                 anchor: new g.Point(px / 2, px / 2)}});
        if (windOn) { m.setMap(map); }
        marks.push(m);
      }, function () {
        marks.forEach(function (m) { m.setMap(null); }); marks = [];
      });
      objs.wind_field = {setMap: function (m) {
        windOn = !!m; marks.forEach(function (k) { k.setMap(m); });
      }};
    }
    // HB-210: Google's traffic layer, drawn by Google in the browser, off
    objs.traffic = new g.TrafficLayer(); window.hbTraffic(C, boxes);
    function setOn(id, on) {
      var o = objs[id]; if (o) { o.setMap(on ? map : null); }
    }
    wire(setOn);
    if (D.extent) {
      var e = D.extent;
      map.fitBounds({south: e[0][0], west: e[0][1], north: e[1][0], east: e[1][1]},
                    C.padding);
    }
    drawn('google', counts, bounds);
    stepWire(function () {
      D.layers.forEach(function (l) {
        var d = objs[l.id];
        if (l.stepped && d && d.setStyle) { d.setStyle(d.getStyle()); }
      });
    }, setOn);
  }

  function fallback(why) {
    if (typeof L === 'undefined') { note('The map library did not load.'); return; }
    leaflet(why);
  }
  if (!C.google_key) { fallback(''); return; }
  // HB-210: Google's script is loaded once per page by static/google.js
  window.hbGoogleLoad(C, el, function () { if (!started) { google(); } },
                      fallback, note);
})();
"""


#: HB-210: the Google branch's own script (one load of Google's script per page, and the
#: traffic switch), inlined before the map script on every page; it runs only where the
#: page carries a key (Issue 9e5dd74c folded HB-210's two replacements into MAP_JS
#: when the committed briefs were next re-rendered, HB-215).
GOOGLE_JS = (Path(__file__).parent / "static" / "google.js").read_text(encoding="utf-8")


def google_scripts() -> str:
    """The map's scripts after TIME_JS: the Google branch's own script, then the map
    script (HB-210; one map script for every page since HB-215)."""
    return f"<script>{GOOGLE_JS}</script><script>{MAP_JS}</script>"


def _vendored(cfg, name: str) -> str:
    """Leaflet's script or stylesheet, vendored, checked against its pinned hash."""
    page = cfg["page"]
    path = REPO_ROOT / page["leaflet_dir"] / f"leaflet.{name}"
    data = path.read_bytes()
    want = page[f"leaflet_{name}_sha256"]
    got = hashlib.sha256(data).hexdigest()
    if got != want:
        raise RuntimeError(f"{path} sha256 {got} is not the pinned {want}")
    return data.decode("utf-8")


def page_css(cfg) -> str:
    """The page's own stylesheet in the house style (the static page's and the live
    page's, HB-130R)."""
    page = cfg["page"]
    return CSS.format(
        font=page["font_stack"],
        text=page["text"],
        grey=page["grey"],
        accent=page["accent"],
        header=page["header_px"],
        footer=page["footer_px"],
        main_bottom=page["footer_px"] + 32,
    )


def vendored(cfg, name: str) -> str:
    """Leaflet's `js` or `css`, checked against its pinned hash (the live page reads
    the same assets as the static one, DN-022 section 8)."""
    return _vendored(cfg, name)


def page_parts(brief, cfg, author) -> dict[str, str]:
    """Each section's HTML fragment, by name, in the render order: the one function the
    static page (`page_html`) and the event stream's `section_settled` (HB-130R Part A
    step 1) both read, so a streamed fragment is the static page's byte for byte."""
    from hazbrief.brief.orchestrator import RENDER_ORDER

    if RENDER_ORDER[0] != "map":
        raise RuntimeError(
            "the map is the first screen: render_order must start with it"
        )
    parts = {n: section_html(brief, cfg, author, n) for n in RENDER_ORDER}
    # the load read (HB-132R Part A): each fragment is read here, before the stream
    # sends it and before the static page is assembled from it, so both carry the
    # same text; the read's report stays on the blackboard for the appendix
    reader = getattr(brief, "reader", None)
    if reader is not None:
        read = reader.apply(parts)
        parts, brief.load_read = read.parts, read.report
    return parts


def brief_html(brief, cfg, author) -> str:
    return page_html(brief, cfg, author, page_parts(brief, cfg, author))


def _sources_annex(brief, cfg) -> str:
    """The static page's Data sources annex (HB-154 item 9), after the sections and
    collapsed like them; not a streamed section, so the live page shows the same table
    in its fifth tab from the sources route."""
    title = cfg["data_sources"]["title"]
    return (
        '<section class="rendered" id="data-sources"><details><summary>'
        f"<h2>{esc(title)}</h2></summary>"
        f"{data_sources.table_html(data_sources.rows(brief, cfg), cfg, brief)}"
        "</details></section>"
    )


def head_facts(brief, cfg) -> dict[str, str | None]:
    """The live shell's header line (HB-154 item 4), read from the blackboard as it
    stands: the material and its UN number, the container, the place, the as-given
    time and the wind record's label. A fact not yet known is None; the page prints
    what it has and fetches again as sections settle."""
    fp = brief.channels.get("protective_action_footprint") or {}
    payload = fp.get("payload") or {}
    mat = payload.get("material") or {}
    rec = fp.get("record") or {}
    incident = ((rec.get("activity") or {}).get("params") or {}).get("incident") or {}
    loc = location.of_brief(brief, cfg) if rec else None
    place = None
    if loc and (loc.get("shape") or {}).get("type") == "Point":
        lon, lat = loc["shape"]["coordinates"]
        place = cfg["page"]["head_place"].format(
            lat=abs(lat),
            ns="N" if lat >= 0 else "S",
            lon=abs(lon),
            ew="E" if lon >= 0 else "W",
        )
        if loc.get("derivation") and loc["derivation"] != "caller_supplied":
            place += cfg["page"]["head_derived"].format(how=loc["derivation"])
    un = mat.get("id_number")
    return {
        "material": _material_name(mat) or None,
        "un": f"UN{un}" if un and str(un).isdigit() else (un or None),
        "container": incident.get("container"),
        "place": place,
        "as_given": L.when(brief.as_given, brief.time_zone) if brief.as_given else None,
        "wind": wind_source_label(brief, cfg) if payload else None,
        # HB-158 item 6: the chip's short form, the record's direction, speed and
        # source kind (the label's first word); the full label is its tooltip
        "wind_short": _wind_short(brief, cfg) if payload else None,
    }


def _wind_short(brief, cfg) -> str | None:
    """The header chip's wind (HB-158 item 6): "from 10° at 11.1 km/h, forecast", read
    from the brief's one wind record (HB-133) and its label's source kind."""
    w = _brief_wind(brief) or {}
    if w.get("direction_deg_from") is None:
        return None
    kind = (wind_source_label(brief, cfg, w) or "").split(",")[0].strip()
    speed = w.get("speed_kmh")
    at = f" at {float(speed):g} km/h" if speed is not None else ""
    return f"from {float(w['direction_deg_from']):.0f}°{at}" + (
        f", {kind}" if kind else ""
    )


def page_html(brief, cfg, author, parts: dict[str, str]) -> str:
    """The static page from the blackboard and its sections' fragments (`page_parts`
    of the same blackboard)."""
    page = cfg["page"]
    css = page_css(cfg)
    fp = brief.channels["protective_action_footprint"].get("payload") or {}
    mat = _material_name(fp.get("material") or {}) or "Hazardous material"
    title = f"{mat} release: incident workbench"
    from hazbrief.brief.orchestrator import RENDER_ORDER

    first = parts["map"]
    rest = "\n".join(parts[n] for n in RENDER_ORDER[1:])
    read_at = L.when(L._iso(brief.now), brief.time_zone)
    # a model-backed author (HB-131R item 4) says so; NoAuthor's page is unchanged
    wrote = (
        "no model wrote any sentence"
        if author.name == "NoAuthor"
        else cfg["model"]["lede_author"]
    )
    lede = (
        "Draft for the Incident Commander, assembled from the hazbrief server's seven "
        f"tools. Labels read at {read_at}. Narrative author: {author.name}; {wrote}. "
        "Each section below opens on a click. "
        '<a href="appendix.html">Evidence appendix</a> '
        '(<a href="appendix.txt">text</a>).'
    )
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{esc(title)}</title>"
        f"<style>{_vendored(cfg, 'css')}</style>"
        f"<style>{css}</style></head><body>"
        f"{_header(brief, cfg, title)}\n{first}\n{_chips(brief, cfg)}\n"
        f'<main><p class="lede">{lede}</p>\n{rest}\n{_sources_annex(brief, cfg)}\n'
        "</main>"
        f'<footer id="bottom" class="banner">{esc(page["banner"])}</footer>'
        f"<script>{_vendored(cfg, 'js')}</script>"
        f"<script>{TIME_JS}</script>"
        f"{google_scripts()}</body></html>\n"
    )
