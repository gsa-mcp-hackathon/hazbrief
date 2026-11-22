"""The workbench map's layers and its first-actions strip (DN-012 sections 2, 3; HB-45).

Every layer is drawn from records in the evidence store, never from the basemap: the
footprint's own GeoJSON, the points the tools return, and, for a layer whose tool
returns a feature without its geometry (a rail segment, a 3DHP reach, a Census block),
the geometry in the upstream exchange the tool's record `used`, matched by the id the
tool printed. That is the pattern HB-41 drew the roads image by (an entity a record
`used`). A layer that cannot be drawn says why, and the reason is shown beside the layer
list: what is missing is shown as plainly as what is present (DN-012 s2).

The layers are written once, as GeoJSON with a style and a popup per feature, and the
page binds them to whichever map object exists (Google or Leaflet; `render.MAP_JS`). A
popup carries the value's label from `labels.label_for`: each source, its provenance
class, its as-of, and current or stale, with the record's hash prefix.

The first-actions strip is the footprint's isolation and protective action distances and
the orange guide's public-safety lines as `material_response_guidance` returned them,
each with its page. Nothing in it is typed here or written by a model.
"""

from __future__ import annotations

import functools
import html
import json
import math
import re
from pathlib import Path
from typing import Any

from geographiclib.geodesic import Geodesic
from shapely import make_valid
from shapely.geometry import box, mapping, shape
from shapely.ops import unary_union

from hazbrief.brief import location
from hazbrief.config import REPO_ROOT
from hazbrief.evidence import labels as L
from hazbrief.evidence.store import read_entity, record_by

#: metres per degree of latitude on the WGS 84 mean sphere radius (6,371,008.8 m,
#: IUGG): only for drawing symbols (the wind arrow, the minimum extent), never a value.
_M_PER_DEG = math.pi * 6371008.8 / 180


def esc(text: Any) -> str:
    return html.escape(str(text), quote=True)


# ── labels ────────────────────────────────────────────────────────────────────────────


def label_text(label: dict, tz: str) -> str:
    """One line: each source with its class, as-of and state, then the record."""
    n = L.config()["hash_prefix_chars"]
    parts = []
    for s in label["sources"]:
        if s["provenance_class"] == "caller_supplied":
            parts.append(
                f"{s['parameter']} as given by the requester (caller_supplied)"
            )
            continue
        parts.append(f"{s['name']} ({s['provenance_class']}), {L.source_phrase(s, tz)}")
    return "; ".join(parts) + f"; record {label['hash'][:n]}"


def _popup(title: str, rows: list[tuple[str, Any]], labels: list[str]) -> dict:
    """A feature's popup: its title and rows as HTML, and its label lines, which the
    layer holds once and the feature names by index (`_layer`)."""
    body = "".join(
        f"<tr><th>{esc(k)}</th><td>{esc(v)}</td></tr>"
        for k, v in rows
        if v not in (None, "")
    )
    return {
        "html": f"<strong>{esc(title)}</strong><table>{body}</table>",
        "labs": labels,
    }


# ── reading the brief ─────────────────────────────────────────────────────────────────


class _Ctx:
    def __init__(self, brief, cfg):
        self.brief = brief
        self.cfg = cfg
        self.map = cfg["map"]
        self.tz = brief.time_zone
        self.now = brief.now

    def channel(self, name: str) -> dict:
        return self.brief.channels[name]

    def ok(self, name: str) -> bool:
        return self.channel(name)["state"] == "ok"

    def payload(self, name: str) -> Any:
        return self.channel(name).get("payload") if self.ok(name) else None

    def why_not(self, name: str) -> str:
        ch = self.channel(name)
        if ch["state"] == "pending":
            return f"waiting for {name.replace('_', ' ')}"
        return f"{name.replace('_', ' ')} is unavailable: {ch.get('reason')}"

    def label(self, name: str, only: list[str] | None = None) -> str:
        ch = self.channel(name)
        lab = L.label_for(ch["record"], self.now, ch["payload"], only=only)
        return label_text(lab, self.tz)

    def exchanges(self, name: str, source_id: str) -> list[tuple[dict, Any, str]]:
        """(record, body, label line) of each exchange of `source_id` that the tool's
        record `used`, from the brief's stores; a used hash no store holds is skipped.
        """
        out = []
        cite = self.channel(name)["record"]
        for sha in cite["used"]:
            for st in self.brief.stores:
                try:
                    rec = record_by(st, sha, cite["activity"]["startedAtTime"])
                except FileNotFoundError:
                    continue
                if rec["activity"]["type"] != "upstream_exchange":
                    break
                if rec["agent"]["source"][0]["id"] != source_id:
                    break
                body = read_entity(st, sha)
                lab = label_text(L.label_for(rec, self.now, body), self.tz)
                out.append((rec, body, f"geometry: {lab}"))
                break
        return out

    def round(self, geom: dict, simplify: bool = False) -> dict | None:
        """Round a GeoJSON geometry. With `simplify` (geometry read from an exchange):
        crop it to `clip_box`, then generalize it; None when nothing of it is left.
        Display only: every count and length stays the tool's."""
        places = self.map["coord_places"]
        if simplify:
            g = shape(geom)
            box = self.clip_box()
            if box is not None:
                g = g.intersection(box)
            if g.is_empty:
                return None
            geom = g.simplify(self.map["simplify_deg"]).__geo_interface__
        return {"type": geom["type"], "coordinates": _rnd(geom["coordinates"], places)}

    def clip_box(self):
        """The view's extent (`extent`, never narrower than `min_extent_m`) widened by
        `clip_margin_share` of its size on each side: a crop edge falls well outside
        the first view, so a cropped river never reads as a drawn shape."""
        ext = extent(self)
        if ext is None:
            return None
        (s, w), (n, e) = ext
        m = self.map["clip_margin_share"]
        dx, dy = (e - w) * m, (n - s) * m
        return box(w - dx, s - dy, e + dx, n + dy)


def _rnd(c: Any, places: int) -> Any:
    if isinstance(c, (int, float)):
        return round(float(c), places)
    return [_rnd(x, places) for x in c]


def _feature(geom: dict, popup: dict, **props) -> dict:
    return {
        "type": "Feature",
        "geometry": geom,
        "properties": {"popup": popup["html"], "_labs": popup["labs"], **props},
    }


def _layer(lid, title, kind, *, features=None, reason=None, style=None):
    """A layer. Each feature's label lines move to the layer's `labels`, escaped, and
    the feature keeps their indices (`labs`): a label repeated on a hundred reaches is
    written once. Its default (`on`) is set by `build` from `map.defaults`."""
    labels: list[str] = []
    for f in features or []:
        idx = []
        for text in f["properties"].pop("_labs"):
            html_text = esc(text)
            if html_text not in labels:
                labels.append(html_text)
            idx.append(labels.index(html_text))
        f["properties"]["labs"] = idx
    return {
        "id": lid,
        "title": title,
        "kind": kind,
        "on": None,
        "legend": None,
        "style": style or {},
        "labels": labels,
        "features": features or [],
        "reason": None if features else reason,
    }


@functools.lru_cache(maxsize=1)
def symbols() -> dict:
    """The marker symbol table (`symbols.yaml`; HB-152, HBD-315)."""
    import yaml

    path = Path(__file__).with_name("symbols.yaml")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=None)
def _symbol_file(cls: str) -> str:
    """A class's committed SVG (`scripts/build_symbols.py`). A class with no file is an
    error, never a dot: the build writes one for every class in the table."""
    path = REPO_ROOT / symbols()["standard"]["svg_dir"] / f"{cls}.svg"
    return path.read_text(encoding="utf-8").strip()


def _luminance(hex_color: str) -> float:
    """WCAG 2.1 relative luminance of an sRGB colour (`#rrggbb`), success criterion
    1.4.3's definition."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        raise ValueError(f"not a #rrggbb colour: {hex_color!r}")
    out = []
    for i in (0, 2, 4):
        c = int(h[i : i + 2], 16) / 255
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]


def ink_for(fill: str) -> str:
    """White or black, whichever has the higher WCAG 2.1 contrast ratio against `fill`
    (HB-152 item 4: the pictogram in white or black by contrast)."""
    lum = _luminance(fill)
    white = 1.05 / (lum + 0.05)
    black = (lum + 0.05) / 0.05
    return "#ffffff" if white >= black else "#000000"


def symbol_svg(cls: str, fill: str, px: int) -> str:
    """Class `cls`'s SVG with `fill` as its frame's fill, the contrasting ink, drawn at
    `px` pixels. Fails loud if the committed file is not the build's form."""
    std = symbols()["standard"]
    svg = _symbol_file(cls)
    swaps = [
        (
            f'data-hb="frame" fill="{std["frame_default"]}"',
            f'data-hb="frame" fill="{fill}"',
        ),
        (
            f'data-hb="ink" fill="{std["ink_default"]}"',
            f'data-hb="ink" fill="{ink_for(fill)}"',
        ),
        (
            f'width="{std["size_px"]}" height="{std["size_px"]}"',
            f'width="{px}" height="{px}"',
        ),
    ]
    for old, new in swaps:
        if old not in svg:
            raise ValueError(
                f"{cls}.svg: {old!r} not found; rebuild with scripts/build_symbols.py"
            )
        svg = svg.replace(old, new, 1)
    return svg


def symbol_own(cls: str) -> bool:
    """True where no FGDC glyph is named for the class and hazbrief draws its own."""
    return bool(symbols()["classes"][cls].get("own"))


def symbol_line(cls: str) -> str:
    """The Symbol row's text for a marker of class `cls`: the FGDC symbol's name,
    family, key stroke and reference page row, called a draft prototype as the fonts
    require; or, for an own-symbol class, that it is hazbrief's own. KeyError for a
    class the table does not map."""
    s = symbols()
    entry = s["classes"][cls]
    if entry.get("own"):
        return s["standard"]["own_line"].format(name=entry["name"])
    return s["standard"]["fgdc_line"].format(
        name=entry["name"], family=entry["family"], key=entry["key"], row=entry["row"]
    )


def symbol_legend(cls: str) -> str:
    """Class `cls`'s entry under its layer's toggle: the FGDC name, family and key
    stroke, or the own-symbol sentence."""
    s = symbols()
    entry = s["classes"][cls]
    if entry.get("own"):
        return s["standard"]["own_line"].format(name=entry["name"])
    return s["standard"]["legend_entry"].format(
        name=entry["name"], family=entry["family"], key=entry["key"]
    )


def _symbolize(lay: dict) -> None:
    """Every marker of a mapped class draws its class's SVG, and its popup names the
    symbol in a row (`symbol_line`; a row, not a label line: every label line names a
    record). A feature's class is its own `symbol` (the nearby services, the care
    layer's two kinds) or else the layer's id. The layer carries each of its classes'
    SVGs, coloured with its fill (`style.symbols`), once."""
    table = symbols()["classes"]
    if not lay["features"]:
        return
    classes: set[str] = set()
    for f in lay["features"]:
        p = f["properties"]
        cls = p.get("symbol") or (lay["id"] if lay["id"] in table else None)
        if cls is None:
            continue
        p["symbol"] = cls
        classes.add(cls)
        if "<th>Symbol</th>" not in p["popup"]:
            p["popup"] = p["popup"].replace("</table>", symbol_row(cls) + "</table>", 1)
    if classes:
        px = symbols()["standard"]["size_px"]
        fill = lay["style"]["fill"]
        lay["style"]["symbols"] = {c: symbol_svg(c, fill, px) for c in sorted(classes)}
        lay["style"]["symbol_px"] = px


ROADBLOCK_LAYERS = ("roadblock_candidates", "modelled_cordons", "rail_candidates")


def _reach_keys(c: _Ctx, lay: dict) -> None:
    """HB-163 ADDENDUM-04 item 1: on a brief whose cloud is drawn, each roadblock's own
    key shows the highest level the held record measured there, by that level's colour
    (`reach`, and the symbol in that colour, `style.reach_symbols`); nothing is
    written beside it. A roadblock the cloud does not reach keeps its own colour."""
    d = cloud_drawn(c)
    if d is None or lay["id"] not in ROADBLOCK_LAYERS or not lay["features"]:
        return
    levels = c.map["cloud"]["levels"]
    at = {
        (round(p["lat"], 6), round(p["lon"], 6)): p.get("highest_tier")
        for p in d.get("places") or []
        if p["kind"] == "roadblock"
    }
    px = symbols()["standard"]["size_px"]
    keys: dict[str, str] = {}
    for f in lay["features"]:
        lon, lat = f["geometry"]["coordinates"][:2]
        tier = at.get((round(float(lat), 6), round(float(lon), 6)))
        p = f["properties"]
        if not tier or tier not in levels:
            continue
        p["reach"] = tier
        cls = p.get("symbol")
        if cls:
            keys[f"{cls}|{tier}"] = symbol_svg(cls, levels[tier]["color"], px)
        else:
            p["fill"] = levels[tier]["color"]
    if keys:
        lay["style"]["reach_symbols"] = keys


def symbol_row(cls: str) -> str:
    """The popup row naming class `cls`'s symbol."""
    return f"<tr><th>Symbol</th><td>{esc(symbol_line(cls))}</td></tr>"


def _point_style(color: str, radius: int = 6) -> dict:
    return {
        "color": "#ffffff",
        "fill": color,
        "weight": 1.5,
        "fillOpacity": 0.95,
        "radius": radius,
    }


# ── the layers ────────────────────────────────────────────────────────────────────────


def _zone_features(fp: dict, zone: str) -> list[dict]:
    return [
        f
        for f in (fp.get("footprint") or {}).get("features") or []
        if f["properties"].get("zone") == zone and f["geometry"]["type"] == "Polygon"
    ]


ZONE_TITLES = {
    "initial_isolation_zone": "Initial isolation zone",
    "protective_action_zone": "Protective action zone",
    "fire_isolation": "Fire isolation zone",
}


def _footprint_layers(c: _Ctx) -> list[dict]:
    fp = c.payload("protective_action_footprint")
    col = c.map["colors"]
    if fp is None:
        why = c.why_not("protective_action_footprint")
        return [
            _layer("spill", "Spill point", "point", reason=why),
            *(_layer(z, t, "polygon", reason=why) for z, t in ZONE_TITLES.items()),
            _layer("wind", "Wind", "line", reason=why),
        ]
    lab = c.label("protective_action_footprint")
    # the spill point renders from its location record (DN-013 section 2; HB-48)
    rec = location.of_brief(c.brief, c.cfg)
    spills = [
        f for f in fp["footprint"]["features"] if f["properties"].get("zone") == "spill"
    ]
    if c.brief.location:
        # a derived location (HB-49): the spill symbol is the shape's representative
        # point, and every zone is the union over the shape, so each says so
        lon, lat = spills[0]["geometry"]["coordinates"] if spills else (None, None)
        where = fp.get("location_union", {}).get("label", rec["label"])
        rows = [
            (
                "Location",
                f"the source's own point ({rec['derivation']}), {lat}, {lon}"
                if rec.get("hint")
                else f"the middle of the {rec['shape']['type']}, {lat}, {lon}",
            ),
            ("How it was given", f"{rec['derivation']}: {rec['unit']}"),
            ("Accuracy", where),
        ]
        zone_rows = [("Location", where)]
    else:
        lon, lat = rec["shape"]["coordinates"]
        rows = [
            ("Location", f"{lat}, {lon}"),
            (
                "How it was given",
                f"a {rec['shape']['type'].lower()} from the {rec['source']} "
                f"({rec['derivation']})",
            ),
            ("Accuracy", rec["label"]),
        ]
        zone_rows = []
    spill_feats = [
        _feature(c.round(f["geometry"]), _popup("Spill point", rows, [lab]))
        for f in spills
    ]
    out = [
        _layer(
            "spill",
            "Spill point",
            "point",
            features=spill_feats,
            reason="the footprint carries no spill point",
            style=_point_style(col["spill"], 8),
        )
    ]
    for zone, title in ZONE_TITLES.items():
        feats = []
        for f in _zone_features(fp, zone):
            p = f["properties"]
            rows = [("Distance", p.get("text")), ("Table", p.get("tag"))]
            if p.get("downwind_bearing_deg") is not None:
                rows.append(
                    ("Downwind toward", f"{p['downwind_bearing_deg']:.0f} degrees")
                )
            rows += zone_rows
            # HB-133: the bearing the zone is oriented on, as data beside the popup, so
            # the one-wind check reads it from the page (test_hb133_one_wind.py)
            keep = (
                {"downwind_bearing_deg": p["downwind_bearing_deg"]}
                if p.get("downwind_bearing_deg") is not None
                else {}
            )
            feats.append(
                _feature(c.round(f["geometry"]), _popup(title, rows, [lab]), **keep)
            )
        z = (fp.get("zones") or {}).get(zone) or {}
        reason = z.get("note") or "the guide gives no such zone for this incident"
        out.append(
            _layer(
                zone,
                title,
                "polygon",
                features=feats,
                reason=reason,
                style={
                    "color": col[zone],
                    "fill": col[zone],
                    "weight": 2,
                    "fillOpacity": 0.22 if zone != "protective_action_zone" else 0.12,
                    "dash": "6 4" if zone == "fire_isolation" else None,
                },
            )
        )
    out.append(_wind_layer(c, fp, spills, lab))
    return out


def _offset(lon: float, lat: float, bearing_deg: float, m: float) -> list[float]:
    """A point `m` metres from (lon, lat) toward `bearing_deg`, on a local flat
    approximation: for drawing a symbol a few kilometres long, not for a value."""
    b = math.radians(bearing_deg)
    dlat = m * math.cos(b) / _M_PER_DEG
    dlon = m * math.sin(b) / (_M_PER_DEG * math.cos(math.radians(lat)))
    return [lon + dlon, lat + dlat]


def _largest_radius_m(fp: dict) -> float:
    """The largest zone's reach from the spill, read from the zone polygons."""
    spill = next(
        f["geometry"]["coordinates"]
        for f in fp["footprint"]["features"]
        if f["properties"].get("zone") == "spill"
    )
    best = 0.0
    for f in fp["footprint"]["features"]:
        if f["geometry"]["type"] != "Polygon":
            continue
        for lon, lat in f["geometry"]["coordinates"][0]:
            dx = (lon - spill[0]) * _M_PER_DEG * math.cos(math.radians(spill[1]))
            dy = (lat - spill[1]) * _M_PER_DEG
            best = max(best, math.hypot(dx, dy))
    return best


def _wind_layer(c: _Ctx, fp: dict, spills: list[dict], lab: str) -> dict:
    wind = fp.get("wind")
    col = c.map["colors"]["wind"]
    if not wind or not spills:
        reason = fp.get("wind_error") or "the footprint carries no wind"
        return _layer("wind", "Wind", "line", reason=str(reason))
    lon, lat = spills[0]["geometry"]["coordinates"]
    length = max(c.map["arrow_min_m"], c.map["arrow_share"] * _largest_radius_m(fp))
    down = wind["downwind_bearing_deg"]
    # from the spill, downwind: the arrow lies inside the footprint it orients
    tip = _offset(lon, lat, down, length)
    head_len = length * 0.2
    left = _offset(tip[0], tip[1], down + 180 - 22, head_len)
    right = _offset(tip[0], tip[1], down + 180 + 22, head_len)
    given = (
        f"as given by the requester: {wind.get('source')}"
        if wind.get("origin") == "caller"
        else f"National Weather Service: {wind.get('source')}"
    )
    # HB-133: the brief resolved one wind record and asked the server to orient on it
    # (or the server read the same forecast cell); the popup names the record
    resolved = getattr(c.brief, "wind_resolved", False) and c.brief.wind_record
    if resolved and c.brief.wind_record["kind"] == "stated":
        given = f"as given by the requester: {c.brief.wind_record['source']}"
    elif resolved:
        given = c.map["wind_record_source"].format(source=c.brief.wind_record["source"])
    popup = _popup(
        "Wind",
        [
            (
                "Wind",
                f"{wind.get('speed_kmh')} km/h ({wind.get('speed_mph')} mph) from the "
                f"{wind.get('direction_from_compass')}, {wind.get('band_label')}",
            ),
            ("Source", given),
            (
                "As of" if resolved else "Observed",
                L.when(wind["as_of"], c.tz) if wind.get("as_of") else None,
            ),
            (
                "Arrow",
                "from the spill, pointing downwind; its length is a symbol, "
                "not a distance",
            ),
        ],
        [lab],
    )
    place = c.map["coord_places"]
    feats = [
        _feature(
            {"type": "LineString", "coordinates": _rnd([[lon, lat], tip], place)},
            popup,
        ),
        _feature(
            {
                "type": "Polygon",
                "coordinates": _rnd([[tip, left, right, tip]], place),
            },
            popup,
        ),
    ]
    return _layer(
        "wind",
        "Wind",
        "line",
        features=feats,
        style={"color": col, "fill": col, "weight": 3, "fillOpacity": 1},
    )


def _flags_layer(c: _Ctx) -> dict:
    fp = c.payload("protective_action_footprint")
    if fp is None:
        return _layer(
            "flags", "Flags", "point", reason=c.why_not("protective_action_footprint")
        )
    placed = [
        f
        for f in (fp.get("flags") or {}).get("all") or []
        if f.get("coordinates") or f.get("location")
    ]
    n = len((fp.get("flags") or {}).get("all") or [])
    # no flag rule carries a place today (packs/flag_rules.json); when one does, it is
    # drawn here as a point
    feats = [
        _feature(
            {"type": "Point", "coordinates": f.get("coordinates") or f["location"]},
            _popup(f["rule_id"], [("Flag", f.get("sentence"))], []),
        )
        for f in placed
    ]
    return _layer(
        "flags",
        "Flags with a location",
        "point",
        features=feats,
        reason=f"none of this incident's {n} flags carries a location"
        if n
        else "no flag holds for this incident",
    )


def _hospitals_layer(c: _Ctx) -> dict:
    rh = c.payload("receiving_hospitals")
    col = c.map["colors"]["receiving_hospitals"]
    if rh is None:
        return _layer(
            "receiving_hospitals",
            "Receiving hospitals",
            "point",
            reason=c.why_not("receiving_hospitals"),
        )
    lab = c.label("receiving_hospitals")
    shown = (rh.get("hospitals") or [])[: c.cfg["page"]["hospitals_shown"]]
    feats = [
        _feature(
            {"type": "Point", "coordinates": _rnd(h["coordinates"], 5)},
            _popup(
                h.get("name"),
                [
                    ("Type", h.get("type")),
                    ("Beds", h.get("beds")),
                    ("Distance", f"{h.get('distance_km')} km {h.get('direction')}"),
                    (
                        "Straight line crosses the footprint",
                        "yes" if h.get("crosses_footprint") else "no",
                    ),
                    ("Address", h.get("address")),
                ],
                [lab],
            ),
        )
        for h in shown
        if h.get("coordinates")
    ]
    return _layer(
        "receiving_hospitals",
        f"Receiving hospitals (nearest {len(feats)})",
        "point",
        features=feats,
        reason="no receiving hospital within the search distance",
        style=_point_style(col, 7),
    )


def _facility_points(c, fac, kinds, lid, title, only) -> dict:
    col = c.map["colors"][lid]
    lab = c.label("facilities_in_footprint", only=only)
    feats = []
    # HB-152: a layer of more than one kind draws each kind's own symbol (the care
    # layer's hospitals and nursing homes; `symbols.yaml` `feature_kinds`)
    by_kind = symbols().get("feature_kinds") or {}
    for kind in kinds:
        extra = {"symbol": by_kind[kind]} if kind in by_kind else {}
        for it in fac.get(kind) or []:
            if not it.get("coordinates"):
                continue
            feats.append(
                _feature(
                    {"type": "Point", "coordinates": _rnd(it["coordinates"], 5)},
                    _popup(
                        it.get("name"),
                        [
                            ("Type", it.get("type") or kind.replace("_", " ")),
                            ("Zone", str(it.get("zone")).replace("_", " ")),
                            ("Address", it.get("address")),
                            ("Beds", it.get("beds")),
                            ("Source", it.get("source")),
                            ("As of", it.get("as_of")),
                        ],
                        [lab],
                    ),
                    **extra,
                )
            )
    return _layer(
        lid,
        title,
        "point",
        features=feats,
        reason="none in the footprint in "
        + ", ".join(k.replace("_", " ") for k in kinds),
        style=_point_style(col),
    )


def _facility_layers(c: _Ctx) -> list[dict]:
    fac = c.payload("facilities_in_footprint")
    ids = [
        ("schools", "Schools"),
        ("care", "Hospitals and nursing homes in the footprint"),
        ("emergency_services", "Fire, EMS and police stations"),
        ("rail_lines", "Rail lines"),
        ("grade_crossings", "Grade crossings"),
        ("water", "Waterways and waterbodies"),
    ]
    if fac is None:
        why = c.why_not("facilities_in_footprint")
        return [
            _layer(
                i, t, "line" if i in ("rail_lines", "water") else "point", reason=why
            )
            for i, t in ids
        ]
    return [
        _facility_points(
            c, fac, ["schools"], "schools", ids[0][1], ["usgs_structures"]
        ),
        _facility_points(
            c,
            fac,
            ["hospitals", "nursing_homes"],
            "care",
            ids[1][1],
            ["usgs_structures", "cms:nursing_homes"],
        ),
        _facility_points(
            c,
            fac,
            ["emergency_services"],
            "emergency_services",
            ids[2][1],
            ["usgs_structures"],
        ),
        _rail_lines(c, fac),
        _crossings(c, fac),
        _water(c, fac),
    ]


@functools.lru_cache(maxsize=4)
def _incident_points(path: str) -> dict:
    """The committed released-incident points (HB-136R; scripts/build_incident_map.py),
    read once. A file without its dataset's row and sha256 is refused: every drawn point
    must trace to a held record (DN-010 D3)."""
    data = json.loads((REPO_ROOT / path).read_text(encoding="utf-8"))
    props = data.get("properties") or {}
    for key in ("dataset_doc_id", "dataset_sha256", "period"):
        if not props.get(key):
            raise ValueError(f"{path}: the collection has no {key!r}")
    for f in data["features"]:
        p = f["properties"]
        if not (p.get("released_report_key") and p.get("dataset_doc_id")):
            raise ValueError(f"{path}: a point without its report and row: {p}")
    return data


def _incidents_layer(c: _Ctx) -> dict:
    """HB-136R step 6: the committed released incidents inside the brief's zones (the
    isolation zone, the protective action zone and the fire isolation zone, wherever the
    footprint drew them), each with its year and severity, labelled with its dataset row
    and FRA report. Off by default (`map.defaults.incidents_nearby`); no sentence is
    written from it. A history of where releases were reported, not a value of this
    incident."""
    spec = c.map["incidents_nearby"]
    lid, title = "incidents_nearby", spec["title"]
    fp = c.payload("protective_action_footprint")
    if fp is None:
        return _layer(
            lid, title, "point", reason=c.why_not("protective_action_footprint")
        )
    zones = [shape(f["geometry"]) for z in ZONE_TITLES for f in _zone_features(fp, z)]
    data = _incident_points(spec["path"])
    props = data["properties"]
    n = L.config()["hash_prefix_chars"]
    lab = spec["label"].format(
        row=props["dataset_doc_id"],
        sha=props["dataset_sha256"][:n],
        period=props["period"],
        path=spec["path"],
    )
    words = {s["id"]: s["words"] for s in props["severity"]}
    area = unary_union(zones) if zones else None
    feats = []
    for f in data["features"]:
        if area is None or not area.covers(shape(f["geometry"])):
            continue
        p = f["properties"]
        feats.append(
            _feature(
                {"type": "Point", "coordinates": _rnd(f["geometry"]["coordinates"], 5)},
                _popup(
                    spec["popup_title"].format(year=p["year"]),
                    [
                        ("Date", p["date"]),
                        ("Severity", words[p["severity"]]),
                        ("Cars that released hazmat", p["hazmat_cars_released"]),
                        ("Persons evacuated", p["persons_evacuated"]),
                        ("Persons killed (any cause)", p["persons_killed"]),
                        ("Persons injured (any cause)", p["persons_injured"]),
                        ("Damage", f"${p['damage_usd']:,}"),
                        ("Railroad", p["railroad"]),
                        ("Place", f"{p['station']}, {p['county']}, {p['state']}"),
                        ("FRA report", p["released_report_key"]),
                        ("Dataset row", p["dataset_doc_id"]),
                        ("Located by", spec["location_words"][p["location_method"]]),
                    ],
                    [lab],
                ),
            )
        )
    return _layer(
        lid,
        title,
        "point",
        features=feats,
        reason=spec["none"].format(n=len(data["features"]), period=props["period"]),
        style=_point_style(c.map["colors"][lid]),
    )


def _exchange_features(c, tool, source_id, url_part=None):
    """Features of the exchanges of `source_id` the tool's record used, each with the
    exchange's label line."""
    out = []
    for rec, body, lab in c.exchanges(tool, source_id):
        if url_part and url_part not in rec["activity"]["params"]["url"]:
            continue
        for f in (body or {}).get("features") or [] if isinstance(body, dict) else []:
            out.append((f, lab))
    return out


#: HB-207 item 14 (Issue 8907cf6c): in a reader's words. Since HB-208 a served live
#: brief records its copies (`brief/live_exchanges.py`), so a layer says this only where
#: its record names none (the pre-run's fetch failed, and the server's call answered
#: alone); the counts are the tool's own and stand. No committed brief prints it.
NO_GEOMETRY = (
    "the shapes are drawn only from a recorded copy of the source's answer, and this "
    "brief's record holds none; the counts in the tool's section stand"
)


def _rail_lines(c: _Ctx, fac: dict) -> dict:
    col = c.map["colors"]["rail_lines"]
    segs = {s["source_id"]: s for s in (fac.get("rail") or {}).get("segments") or []}
    if not segs:
        return _layer(
            "rail_lines", "Rail lines", "line", reason="no rail line in the footprint"
        )
    lab = c.label("facilities_in_footprint", only=["bts_ntad"])
    feats, seen = [], set()
    for f, glab in _exchange_features(
        c, "facilities_in_footprint", "bts_ntad", "Rail_Network_Lines"
    ):
        sid = f["properties"].get("FRAARCID")
        if sid not in segs or sid in seen:
            continue
        seen.add(sid)
        s = segs[sid]
        geom = c.round(f["geometry"], simplify=True)
        if geom is None:
            continue
        feats.append(
            _feature(
                geom,
                _popup(
                    f"Rail line, {s.get('owner')}",
                    [
                        ("Subdivision", s.get("subdivision")),
                        ("Tracks", s.get("tracks")),
                        ("Yard", s.get("yard")),
                        ("Zone", str(s.get("zone")).replace("_", " ")),
                        (
                            "Length inside the footprint",
                            f"{s.get('length_inside_m')} m",
                        ),
                        ("FRA arc", sid),
                    ],
                    [lab, glab],
                ),
            )
        )
    return _layer(
        "rail_lines",
        f"Rail lines ({len(segs)} segments)",
        "line",
        features=feats,
        reason=NO_GEOMETRY,
        style={"color": col, "weight": 3, "dash": "8 3"},
    )


def _crossings(c: _Ctx, fac: dict) -> dict:
    col = c.map["colors"]["grade_crossings"]
    xs = (fac.get("rail") or {}).get("crossings") or []
    lab = c.label("facilities_in_footprint", only=["bts_ntad"])
    feats = [
        _feature(
            {"type": "Point", "coordinates": _rnd(x["coordinates"], 5)},
            _popup(
                f"Grade crossing {x.get('crossing_id')}",
                [
                    ("Railroad", x.get("railroad")),
                    ("Road", x.get("road")),
                    ("Type", x.get("type")),
                    ("Zone", str(x.get("zone")).replace("_", " ")),
                ],
                [lab],
            ),
        )
        for x in xs
        if x.get("coordinates")
    ]
    return _layer(
        "grade_crossings",
        "Grade crossings",
        "point",
        features=feats,
        reason="no grade crossing in the footprint",
        style=_point_style(col, 4),
    )


def _water(c: _Ctx, fac: dict) -> dict:
    col = c.map["colors"]["water"]
    w = fac.get("waterways") or {}
    want = {}
    for item in (w.get("flowlines") or []) + (w.get("waterbodies") or []):
        for sid in item.get("source_ids") or []:
            want[sid] = item
    if not want:
        return _layer(
            "water",
            "Waterways and waterbodies",
            "line",
            reason="no waterway in the footprint",
        )
    lab = c.label("facilities_in_footprint", only=["usgs_3dhp"])
    feats, seen = [], set()
    for f, glab in _exchange_features(c, "facilities_in_footprint", "usgs_3dhp"):
        sid = f["properties"].get("id3dhp")
        if sid not in want or sid in seen:
            continue
        seen.add(sid)
        it = want[sid]
        rows = [
            ("Kind", it.get("type") or it.get("kind")),
            ("In the isolation zone", "yes" if it.get("in_isolation_zone") else "no"),
        ]
        if it.get("length_inside_m") is not None:
            rows.append(
                (
                    "Length inside the footprint",
                    f"{it['length_inside_m']} m over {it.get('reaches')} reaches",
                )
            )
        if it.get("area_inside_m2") is not None:
            rows.append(("Area inside the footprint", f"{it['area_inside_m2']} m²"))
        rows.append(("Mainstem", it.get("mainstem")))
        rows.append(("3DHP id", sid))
        geom = c.round(f["geometry"], simplify=True)
        if geom is None:
            continue
        feats.append(
            _feature(
                geom,
                _popup(it.get("name") or "Unnamed", rows, [lab, glab]),
            )
        )
    return _layer(
        "water",
        f"Waterways and waterbodies ({w.get('count', len(want))})",
        "line",
        features=feats,
        reason=NO_GEOMETRY,
        style={"color": col, "fill": col, "weight": 1.5, "fillOpacity": 0.2},
    )


def _dhc(c: _Ctx) -> tuple[dict[str, int], list[str], set[str]]:
    """The DHC block counts the population tool's record used: {GEOID: residents}, the
    count label lines, and the counties (state + county FIPS) the blocks lie in."""
    counts: dict[str, int] = {}
    dhc_labs, counties = [], set()
    for rec, body, lab in c.exchanges("population_at_risk", "census:dhc2020"):
        if not isinstance(body, list) or "block" not in body[0]:
            continue
        head = body[0]
        i = {k: head.index(k) for k in ("P1_001N", "state", "county", "tract", "block")}
        for row in body[1:]:
            geoid = (
                row[i["state"]] + row[i["county"]] + row[i["tract"]] + row[i["block"]]
            )
            counts[geoid] = int(row[i["P1_001N"]])
            counties.add(row[i["state"]] + row[i["county"]])
        dhc_labs.append(lab.replace("geometry: ", "count: ", 1))
    return counts, dhc_labs, counties


def population_blocks(c: _Ctx) -> list[dict]:
    """The blocks the population layer draws, in its order: each block the tool's
    record used that the footprint reaches, with its geometry, its geometry's label
    line, whether it is partly inside, and its residents (HB-45; shared with the
    workplace layer, HB-55)."""
    fp = c.payload("protective_action_footprint") or {}
    zones = [
        shape(f["geometry"])
        for f in (fp.get("footprint") or {}).get("features") or []
        if f["geometry"]["type"] == "Polygon"
    ]
    counts, _, _ = _dhc(c)
    out, seen = [], set()
    for f, glab in _exchange_features(
        c, "population_at_risk", "tigerweb:census2020", "/MapServer/10/"
    ):
        geoid = f["properties"].get("GEOID")
        if geoid in seen or geoid not in counts:
            continue
        g = shape(f["geometry"])
        if zones and not any(g.intersects(z) for z in zones):
            continue
        seen.add(geoid)
        out.append(
            {
                "geoid": geoid,
                "geometry": f["geometry"],
                "glab": glab,
                "partly": bool(zones and not any(z.contains(g) for z in zones)),
                "residents": counts[geoid],
            }
        )
    return out


def population_counties(c: _Ctx) -> list[str]:
    """The counties (state + county FIPS) of the blocks the population tool counted."""
    return sorted(_dhc(c)[2])


def _inside(partly: bool) -> str:
    return (
        "partly (the tool counts the share of its area inside)" if partly else "wholly"
    )


def _population_layer(c: _Ctx) -> dict:
    title = "Population by Census block (2020)"
    pop = c.payload("population_at_risk")
    if pop is None:
        return _layer(
            "population",
            title,
            "choropleth",
            reason=c.why_not("population_at_risk"),
        )
    _, dhc_labs, _ = _dhc(c)
    lab = c.label("population_at_risk", only=["census:dhc2020", "tigerweb:census2020"])
    breaks = c.map["population_breaks"]
    ramp = c.map["population_ramp"]
    feats = []
    for b in population_blocks(c):
        n = b["residents"]
        cls = sum(1 for x in breaks if n >= x)
        geom = c.round(b["geometry"], simplify=True)
        if geom is None:
            continue
        feats.append(
            _feature(
                geom,
                _popup(
                    f"Census block {b['geoid']}",
                    [
                        ("Residents, whole block (2020 Census)", n),
                        (
                            "Margin of error",
                            "none: 2020 Census counts are published without one; "
                            "they carry disclosure avoidance noise, so a small "
                            "block's count can be off",
                        ),
                        ("Inside the footprint", _inside(b["partly"])),
                    ],
                    [lab, b["glab"], *dhc_labs[:1]],
                ),
                fill=ramp[cls],
            )
        )
    return _layer(
        "population",
        title,
        "choropleth",
        features=feats,
        reason=NO_GEOMETRY,
        style={"color": "#ffffff", "weight": 0.6, "fillOpacity": 0.6},
    )


def _workplace_layer(c: _Ctx) -> dict:
    """LODES jobs per block (DN-015 section 4; HB-55), drawn exactly as the population
    choropleth is: the same blocks, ramp and breaks, off by default, whole-block counts,
    and the population tool's own note on jobs."""
    title = "Workplaces by Census block (LODES jobs)"
    d = _derived(c, "workplaces")
    if d is None:
        return _layer(
            "workplaces",
            title,
            "choropleth",
            reason="the derivations have not run",
        )
    if not d.get("jobs") or d.get("reason"):
        return _layer(
            "workplaces",
            title,
            "choropleth",
            reason=d.get("reason") or "no block",
        )
    lab = "; ".join(
        [
            f"{d['label']}; {', '.join(d['files'])}",
            c.label("population_at_risk", only=["lodes"]),
        ]
    )
    breaks = c.map["population_breaks"]
    ramp = c.map["population_ramp"]
    names = d["columns"]
    feats = []
    for b in population_blocks(c):
        row = d["jobs"].get(b["geoid"])
        if row is None:
            continue
        n = round(row.get("C000", 0))
        cls = sum(1 for x in breaks if n >= x)
        geom = c.round(b["geometry"], simplify=True)
        if geom is None:
            continue
        rows = [("Jobs located in the block, whole block (C000)", n)]
        rows += [
            (names[k], round(v)) for k, v in row.items() if k != "C000" and round(v) > 0
        ]
        rows += [("Note", d["note"]), ("Inside the footprint", _inside(b["partly"]))]
        feats.append(
            _feature(
                geom,
                _popup(
                    f"Census block {b['geoid']}: workplaces", rows, [lab, b["glab"]]
                ),
                fill=ramp[cls],
            )
        )
    return _layer(
        "workplaces",
        title,
        "choropleth",
        features=feats,
        reason=NO_GEOMETRY,
        style={"color": "#ffffff", "weight": 0.6, "fillOpacity": 0.6},
    )


def _location_layer(c: _Ctx) -> list[dict]:
    """The derived location's own shape (HB-49 step 5): the segment, the crossing
    point, the address range's segment or the intersection's disc the footprint was
    drawn over, under the spill symbol. None for the request's bare point, which the
    spill symbol already is. A location the sources could not resolve (HB-50) is a
    layer with nothing drawn and the reason beside it."""
    rec = c.brief.location
    if not rec:
        return []
    if rec["shape"] is None:
        return [_layer("location", "Location as given", "point", reason=rec["label"])]
    kind = {
        "LineString": "line",
        "MultiLineString": "line",
        "Polygon": "polygon",
        "MultiPolygon": "polygon",
    }.get(rec["shape"]["type"], "point")
    col = c.map["colors"]["location"]
    feat = _feature(
        c.round(rec["shape"]),
        _popup(
            "Location as given",
            [
                ("How it was given", f"{rec['derivation']}: {rec['unit']}"),
                ("Accuracy", rec["label"]),
                ("As of", L.when(rec["as_of"], c.tz)),
            ],
            [],
        ),
    )
    style = {
        "line": {"color": col, "weight": 5},
        "polygon": {"color": col, "fill": col, "weight": 2, "fillOpacity": 0.4},
    }.get(kind) or _point_style(col, c.map["location_point_radius"])
    return [
        _layer(
            "location",
            "Location as given",
            kind,
            features=[feat],
            reason="no location record",
            style=style,
        )
    ]


# ── the derivations (DN-015; HB-54) ─────────────────────────────────────────────────


def _derived(c: _Ctx, name: str) -> dict | None:
    """The brief's derivation `name` (`derive.run`), or None before it has run."""
    return (c.brief.derived or {}).get(name)


def _read_line(d: dict, tz: str) -> str:
    """What a derivation read: each upstream answer, when it was retrieved, and its
    recorded exchange (the record a popup's label names, as a tool's label names its
    call's)."""
    n = L.config()["hash_prefix_chars"]
    seen = []
    for s in d.get("sources") or []:
        when = L.when(s["retrieved"], tz) if s.get("retrieved") else "not stated"
        text = f"{s['api']} answer, retrieved {when}, record {s['key'][:n]}"
        if text not in seen:
            seen.append(text)
    return "; ".join(seen)


def _zone_text(zone: str) -> str:
    return ZONE_TITLES.get(zone, zone.replace("_", " ")).lower()


def _crossing_layer(c: _Ctx, name: str, lid: str, title: str) -> dict:
    d = _derived(c, name)
    if d is None:
        return _layer(lid, title, "point", reason="the derivations have not run")
    col = c.map["colors"][lid]
    rail = name == "rail"
    rule = (
        f"{d['label']}; crossings within {d['merge_m']:g} m on one "
        f"{'rail line' if rail else 'road'} merged"
        + ("" if rail else f"; classes {', '.join(d['classes'])}")
        if d.get("label")
        else ""
    )
    read = _read_line(d, c.tz)
    if rail and c.ok("facilities_in_footprint"):
        read = c.label("facilities_in_footprint", only=["bts_ntad"])
    labs = ["; ".join(t for t in (rule, read) if t)]
    # HB-178 (Issue 2c1d5f53): a candidate dropped because no point along its road
    # within the rule's distance is outside every zone is named, never drawn inside
    gone = d.get("dropped") or []
    if gone:
        spec = c.cfg["derive"]["roads"]["offset"]
        labs.append(
            spec["dropped_line"].format(
                n=len(gone),
                roads=", ".join(
                    f"{g['road']} at {g['crossing'][1]}, {g['crossing'][0]}"
                    for g in gone
                ),
                why=gone[0]["why"],
            )
        )
    feats = []
    fm = c.map["first_map_blocks"]
    for k in d.get("candidates") or []:
        # HB-192 (DN-024 ADDENDUM-01 decision 9): on the first map, a road block only
        # on a primary or secondary road or at the scene's isolation boundary; every
        # other candidate stays in the data and in the Timeline page's table
        if (
            not rail
            and not getattr(c.brief, "every_candidate", False)
            and not on_first_map(k, fm, c.cfg)
        ):
            continue
        rows = (
            [
                ("Owner", k.get("owner")),
                ("Subdivision", k.get("subdivision")),
                ("FRA arc", k.get("fra_arc")),
            ]
            if rail
            else [("Road", k.get("road")), ("Class (MTFCC)", k.get("mtfcc"))]
        )
        rows += [
            ("Zone boundary", _zone_text(k["zone"])),
            (
                "Bearing",
                f"{k['bearing_deg']}° / {(k['bearing_deg'] + 180) % 360}°"
                if k.get("bearing_deg") is not None
                else None,
            ),
            ("Crossings merged", k["crossings"] if k["crossings"] > 1 else None),
        ]
        if not rail:
            rows += _offset_rows(c, d, k)
        # HB-157 item 8: what the candidate guards, and the inner-cordon mark of a
        # candidate inside another drawn hazard layer (drawn muted, never hidden)
        rows += [("Guards", k.get("guards")), ("Inner cordon", k.get("inner"))]
        if not rail:
            # HB-192 (ADDENDUM-01 section 2; ADDENDUM-02 item 4): a candidate, which
            # may not be possible to staff; and inside the AEGL-1 outline, said so
            rows.append(("Candidate", fm["staff_words"]))
            if inside_aegl1(c, k):
                rows.append(("Inside AEGL-1", fm["inside_aegl1_words"]))
        head = k.get("road") if not rail else f"Rail line, {k.get('owner')}"
        extra = {"muted": True} if k.get("inner") else {}
        if lid == "modelled_cordons":
            extra["symbol"] = "roadblock_candidates"
        feats.append(
            _feature(
                {"type": "Point", "coordinates": k["coordinates"]},
                _popup(f"Candidate: {head}", rows, labs),
                **extra,
            )
        )
    # HB-192: candidates held but none on the first map: said so, and where they are
    off = 0 if rail else len(d.get("candidates") or []) - len(feats)
    reason = d.get("reason") or (
        fm["none_drawn"].format(n=off) if off and not feats else "no crossing"
    )
    return _layer(
        lid,
        title,
        "point",
        features=feats,
        reason=reason,
        style=_point_style(col, 6),
    )


def on_first_map(k: dict, fm: dict, cfg: dict) -> bool:
    """HB-192: whether a road candidate is drawn on the first map: its road's class is
    one the held road records mark primary or secondary (TIGER MTFCC,
    `derive.roads.classes`), or it stands on the scene's isolation boundary."""
    return k.get("zone") in fm["scene_zones"] or k.get("mtfcc") in set(
        cfg["derive"]["roads"]["classes"]
    )


def inside_aegl1(c: _Ctx, k: dict) -> bool:
    """HB-192 (ADDENDUM-02 item 4): whether a candidate stands inside the moving cloud's
    AEGL-1 outline reached at any time (a block guards the AEGL-2 planning area and may
    stand inside AEGL-1, decision 9 of DN-028 ADDENDUM-14)."""
    from shapely.geometry import Point

    d = cloud_drawn(c)
    g = ((d or {}).get("any_time") or {}).get("AEGL-1")
    if not g or not k.get("coordinates"):
        return False
    return make_valid(shape(g)).contains(Point(k["coordinates"]))


def _offset_rows(c: _Ctx, d: dict, k: dict) -> list[tuple[str, Any]]:
    """A road candidate's offset rows (HB-142R item 4): the offset, the rule that
    placed it, the crossing it stands for and the TIGER line; or why no offset was
    computed (the offset query not held)."""
    spec = c.cfg["derive"]["roads"]["offset"]
    if "offset_rule" not in k:
        why = d.get("offset_reason")
        if not why:
            return []
        return [("Offset", spec["not_computed"].format(why=why))]
    m = k["offset_m"]
    rule = spec["rules"][k["offset_rule"]].format(
        m=m, min=spec["min_m"], max=spec["max_m"], other=k.get("meets")
    )
    lon, lat = k["crossing"]
    return [
        ("Offset", f"{m:,.0f} m outward along the road from the boundary"),
        ("Rule", rule),
        ("Boundary crossing", f"{lat}, {lon}"),
        ("TIGER line", f"{k.get('tiger_oid')} ({k.get('mtfcc')})"),
    ]


def _nearby_layer(c: _Ctx) -> dict:
    """The services in the area (HB-142R item 1; HB-155 ADDENDUM-01): every fire, EMS
    and
    police station and hospital outside the footprint within the area radius, the
    nearest of a class with none inside it, and those in hand beyond it (stage two),
    each with its distance and bearing from the incident in the popup. Each feature
    carries `area_m` (its distance) and `nearest` (its class's nearest), so the reader's
    Area radius steps filter what is drawn on the page (`map-config` `area`); the first
    view draws the area radius's. A hospital with the CMS fields held (ADDENDUM-01
    section 3), every row with its free-flow travel time or the reason there is none."""
    lid = "nearby_services"
    d = _derived(c, "nearby")
    if d is None:
        return _layer(
            lid,
            "Nearest services outside the footprint",
            "point",
            reason="the derivations have not run",
        )
    # the full title stays HB-151's (every pre-task label stays, HB-158); the row's
    # short
    # name is "Services in the area" (ADDENDUM-05 item 2, `map.rows`)
    title = (
        "Nearest services outside the footprint "
        f"(within {d['radius_m'] / 1000:,.1f} km)"
        if d.get("radius_m")
        else "Nearest services outside the footprint"
    )
    spec = c.cfg["derive"]["nearby"]
    feats = []
    for cls, rows in (d.get("classes") or {}).items():
        sym = f"nearby_{cls}"
        line = symbol_line(sym)
        src = (
            c.label("receiving_hospitals")
            if cls == "hospital"
            else _read_line({"sources": d.get("sources") or []}, c.tz)
        )
        allrows = list(rows) + list((d.get("beyond") or {}).get(cls) or [])
        for i, r in enumerate(allrows):
            prow = [
                ("Service", spec["classes"][cls]["title"]),
                ("Type", r.get("type")),
                (
                    "Distance from the incident",
                    f"{r['distance_m'] / 1000:,.1f} km, bearing {r['bearing_deg']}° "
                    f"({compass(r['bearing_deg'])}), straight line",
                ),
                ("Address", r.get("address")),
            ]
            if cls == "hospital":
                prow += [
                    ("Beds", r.get("beds")),
                    ("Emergency department", r.get("emergency_department")),
                    ("Trauma level", spec["trauma_not_held"]),
                    ("Capability", spec["capability_not_held"]),
                ]
                # HB-151 item 3: a hospital's free-flow time too (the transport leg)
                prow += _travel_rows(d, r)
            else:
                prow += _travel_rows(d, r)
                prow.append(("As of", r.get("as_of")))
            feats.append(
                _feature(
                    {"type": "Point", "coordinates": _rnd(r["coordinates"], 5)},
                    _popup(
                        r.get("name"),
                        prow + [("Symbol", line)],
                        [f"{d['label']}; {src}"],
                    ),
                    symbol=sym,
                    service=cls,
                    area_m=r["distance_m"],
                    nearest=i == 0,
                )
            )
    ring = _area_ring(c)
    if ring is not None and feats:
        feats.append(ring)
    why = (
        "; ".join(
            f"{w}: {r}"
            for w, r in (
                ("fire, EMS and police", d.get("stations_reason")),
                ("hospitals", d.get("hospitals_reason")),
            )
            if r
        )
        or d.get("reason")
        or "none within the radius outside the footprint"
    )
    return _layer(
        lid,
        title,
        "point",
        features=feats,
        reason=why,
        style=_point_style(c.map["colors"][lid], 7),
    )


def area_config(c: _Ctx) -> dict | None:
    """The page's area (HB-155 ADDENDUM-01 item 6; ADDENDUM-02 items 5 and 6): the
    radius
    the first view draws, the reader's steps, which steps' data is in hand (the largest
    box read), and the ring's radius; None where the services were not derived."""
    d = _derived(c, "nearby")
    if not d or d.get("stations_reason") or d.get("reason"):
        return None
    a = c.cfg["derive"]["area"]
    mpm = float(a["metres_per_mile"])
    held = max(
        [
            float(x["box_m"])
            for x in d.get("stages") or []
            if x["outcome"] == "retrieved"
        ]
        or [float(d.get("box_m") or d["radius_m"])]
    )
    return {
        "radius_m": float(d["radius_m"]),
        "shown_m": float(d.get("area_m") or d["radius_m"]),
        "held_m": held,
        "steps": [
            {"mi": mi, "m": round(mi * mpm), "held": mi * mpm <= held + 1}
            for mi in a["steps_mi"]
        ],
    }


def siting_config(c: _Ctx) -> dict | None:
    """What the live page's siting block reads (HB-155 item 8; ADDENDUM-05 items 1 and
    2): each suggested point (its title, place, distance and bearing, why, rule sources
    and the coordinates it was suggested at), the surviving candidates a point can be
    moved to (one button each), the candidates rejected with why, and the block's
    words. None where no point was suggested: the block is then absent."""
    d = _derived(c, "siting")
    if not d or not any((d.get("points") or {}).values()):
        return None
    spec = c.cfg["derive"]["siting"]
    kinds = spec["candidates"]["kinds"]
    from hazbrief.brief import derive as D
    from hazbrief.brief import siting

    fp = c.payload("protective_action_footprint")
    inc = D.incident_point(c.brief, fp)
    points = {}
    for pid in siting.POINTS:
        p = (d.get("points") or {}).get(pid)
        points[pid] = (
            {
                "title": p["title"],
                "short": spec["points"][pid]["short"],
                "name": p["name"],
                "kind": kinds.get(p["kind"], p["kind"]),
                "where": p["where"],
                "why": f"{p['why']} (rule {p['rule']})",
                "sources": p["rule_sources"],
                "both": p.get("both"),
                "suggested": p["suggested"],
            }
            if p
            else {
                "title": spec["points"][pid]["title"],
                "short": spec["points"][pid]["short"],
                "none": spec["words"]["point_none"].format(
                    point=spec["points"][pid]["title"]
                ),
            }
        )
    return {
        "points": points,
        "candidates": [
            {
                "id": a["id"],
                "name": a["name"],
                "kind": kinds.get(a["kind"], a["kind"]),
                "xy": a["coordinates"],
                "where": siting.describe(inc, a["coordinates"], c.cfg)["text"],
            }
            for a in sorted(d.get("alive") or [], key=lambda a: a["distance_m"])
        ],
        "rejected": [
            {
                "name": r["name"],
                "kind": kinds.get(r["kind"], r["kind"]),
                "why": r["why"],
            }
            for r in d.get("rejected") or []
        ],
        "words": {
            k: v
            for k, v in c.cfg["web"]["shell"].items()
            if k.startswith(("siting_", "area_"))
        },
        "suggested": spec["words"]["suggested"],
    }


def siting_gaps(brief, cfg) -> list[str]:
    """HB-155 ADDENDUM-05 item 3: where the points layer is drawn but a point is not
    (no candidate survived for it), that point's own Data gaps line. With no point drawn
    the layer itself is the gap (`map.empty_rows`)."""
    d = (brief.derived or {}).get("siting") or {}
    pts = d.get("points") or {}
    if not any(pts.values()):
        return []
    spec = cfg["derive"]["siting"]
    return [
        spec["words"]["point_none"].format(point=spec["points"][pid]["title"])
        for pid in spec["points"]
        if not pts.get(pid)
    ]


def _area_ring(c: _Ctx) -> dict | None:
    """HB-155 ADDENDUM-02 item 6: a thin dotted ring at the edge of the area whose data
    is in hand (the largest box read), labelled with its radius, so an empty map past it
    reads as not fetched, not as nothing there. A mark of the services layer (`ring`),
    not a layer of its own, so it costs the full layer list no row (ADDENDUM-05 item 7);
    None where the services were not derived."""
    area = area_config(c)
    if area is None:
        return None
    import shapely as _sh

    from hazbrief.brief import derive as D

    fp = c.payload("protective_action_footprint")
    inc = D.incident_point(c.brief, fp)
    ring = D._unplane(_sh.Point(0.0, 0.0).buffer(area["held_m"], 64).exterior, inc)
    mi = area["held_m"] / float(c.cfg["derive"]["area"]["metres_per_mile"])
    d = _derived(c, "nearby") or {}
    words = (
        f"services and candidate places read within {mi:,.0f} miles of the incident; "
        "past this ring nothing was read; "
        + _read_line({"sources": d.get("sources") or []}, c.tz)
    )
    return _feature(
        {"type": "LineString", "coordinates": _rnd([list(p) for p in ring.coords], 5)},
        _popup(
            "Edge of the area read",
            [("Radius", f"{mi:,.0f} mi ({area['held_m'] / 1000:,.1f} km)")],
            [words],
        ),
        ring=True,
        dash="2 6",
    )


def _sited_layer(c: _Ctx) -> dict:
    """HB-155 item 8 (ADDENDUM-05 item 1): the suggested command post, triage and
    staging, each with the FGDC symbol (HB-152) and a popup: the reason, the rule
    sources, the distance and bearing, and "suggested; the incident commander sets
    it". Empty with "no candidate outside the hazard" where no candidate survived, or
    the reason the siting could not run."""
    lid = "sited_points"
    title = "Command post, triage and staging (suggested)"
    d = _derived(c, "siting")
    if d is None:
        return _layer(lid, title, "point", reason="the derivations have not run")
    words = c.cfg["derive"]["siting"]["words"]
    feats = []
    src = _read_line(d, c.tz)
    for pid, p in (d.get("points") or {}).items():
        if not p:
            continue
        kind = c.cfg["derive"]["siting"]["candidates"]["kinds"].get(
            p["kind"], p["kind"]
        )
        rows = [
            ("Place", f"{p['name']} ({kind})"),
            ("Why", f"{p['why']} (rule {p['rule']})"),
            ("Rule sources", p["rule_sources"]),
            ("Distance from the spill", p["where"]),
            ("Also", p.get("both")),
            ("Status", words["suggested"]),
        ]
        feats.append(
            _feature(
                {"type": "Point", "coordinates": _rnd(p["coordinates"], 5)},
                _popup(
                    p["title"], rows, ["; ".join(t for t in (d["label"], src) if t)]
                ),
                symbol=c.cfg["derive"]["siting"]["points"][pid]["symbol"],
                point=pid,
            )
        )
    return _layer(
        lid,
        title,
        "point",
        features=feats,
        reason=d.get("reason") or words["none"],
        style=_point_style(c.map["colors"][lid], 8),
    )


def _routes_layer(c: _Ctx) -> dict:
    """HB-155 item 9: the free-flow routes to the suggested points, avoiding the
    exclusion area: each nearest fire, EMS and police station to staging, triage to each
    hospital of the services in the area."""
    lid = "siting_routes"
    title = "Routes to the suggested points"
    d = _derived(c, "siting")
    if d is None:
        return _layer(lid, title, "line", reason="the derivations have not run")
    spec = c.cfg["derive"]["siting"]["routes"]
    tl = c.cfg["derive"]["nearby"]["travel"]
    # every label line names a record: the roads the routes were drawn over
    near = _derived(c, "nearby") or {}
    lab = (
        f"{spec['label']}; "
        + tl["label"].format(
            speeds=", ".join(f"{k} {v} km/h" for k, v in tl["speed_kmh"].items()),
            connector=tl["connector_kmh"],
        )
        + f"; {_read_line({'sources': near.get('sources') or []}, c.tz)}"
    )
    feats = []
    for r in d.get("routes") or []:
        if not r.get("geometry"):
            continue
        rows = [
            ("Route", r["text"]),
            ("Connectors", f"{r['connector_m']:,} m in all"),
            ("Directions", r["directions"]),
        ]
        feats.append(
            _feature(
                r["geometry"], _popup(r["text"], rows, [lab]), to=r["to"], src=r["from"]
            )
        )
    why = d.get("reason") or (
        spec["none"] if d.get("routes") else c.cfg["derive"]["siting"]["words"]["none"]
    )
    return _layer(
        lid,
        title,
        "line",
        features=feats,
        reason=why,
        style={"color": c.map["colors"][lid], "weight": 3, "dash": "6 4"},
    )


def _travel_rows(d: dict, r: dict) -> list[tuple[str, Any]]:
    """A station's travel-time rows: the minutes and the route's crossing of the
    footprint under the travel label, or why there is no time."""
    t = r.get("travel")
    if not t:
        why = d.get("travel_reason") or "not computed"
        return [("Travel time", f"not computed: {why}")]
    if t.get("minutes") is None:
        # HB-178: "no route in the held roads" is what is known, not a failure
        if t.get("no_route"):
            return [("Travel time", t["reason"])]
        return [("Travel time", f"not computed: {t.get('reason')}")]
    rows = [
        (
            "Travel time",
            f"{t['minutes']:g} min over {t['road_km']:g} km of road "
            f"and {t['connector_m']:,} m of connector ({d['travel_label']})",
        )
    ]
    if t.get("crosses_footprint"):
        rows.append(
            ("Route", "crosses the ERG footprint: the responder goes around it")
        )
    return rows


_COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def compass(deg: float) -> str:
    """The eight-point compass word of a bearing."""
    return _COMPASS[int(((deg % 360) + 22.5) // 45) % 8]


def block_area_km2(geom: dict) -> float:
    """A block's area, km², on the local plane around its centroid (the projection
    `facilities.buffer` and `derive._plane` use). A block is at most a few km across,
    where this is within 0.1 % of the WGS 84 geodesic area
    (`geodesic_area_km2`; test_hb142_nearby_roadblocks.py holds it on the pair's
    blocks) at a small share of the cost: Karney's polygon in pure Python took 20 s
    over csx day's blocks."""
    g = shape(geom)
    c = g.centroid
    kx = math.cos(math.radians(c.y)) * _M_PER_DEG
    return g.area * kx * _M_PER_DEG / 1e6


def geodesic_area_km2(geom: dict) -> float:
    """A polygon's geodesic area (WGS 84, Karney), km²: the reference the plane area
    is held to."""
    g = shape(geom)
    polys = list(g.geoms) if g.geom_type == "MultiPolygon" else [g]
    total = 0.0
    for p in polys:
        for ring, sign in [(p.exterior, 1)] + [(r, -1) for r in p.interiors]:
            poly = Geodesic.WGS84.Polygon()
            for x, y in list(ring.coords)[:-1]:
                poly.AddPoint(y, x)
            _, _, area = poly.Compute(False, True)
            total += sign * abs(area)
    return total / 1e6


def quantile_breaks(values: list[float], n: int) -> list[float]:
    """The n-1 inner breaks of `n` quantile bands of `values` (type 7, numpy's
    default linear interpolation), deduplicated: tied values give fewer bands."""
    import numpy as np

    if not values:
        return []
    qs = [float(np.quantile(values, i / n)) for i in range(1, n)]
    out: list[float] = []
    for q in qs:
        if not out or q > out[-1]:
            out.append(q)
    return out


def band_names(breaks: list[float]) -> list[str]:
    """The words of each quantile band, in the layer's class order (a value v is in
    band i when it exceeds i breaks): "0 to 26", "over 26 to 83", ..., "over 252";
    a first break of 0 makes the first band "0" (the blocks with no resident)."""
    if not breaks:
        return ["all blocks"]
    first = f"{breaks[0]:,.0f}" if breaks[0] == 0 else f"0 to {breaks[0]:,.0f}"
    mid = [f"over {lo:,.0f} to {hi:,.0f}" for lo, hi in zip(breaks, breaks[1:])]
    return [first, *mid, f"over {breaks[-1]:,.0f}"]


def _residential_layer(c: _Ctx) -> dict:
    """Residents per km² of each held block (HB-142R item 2; DN-019 ADDENDUM-02 F8):
    the population tool's own blocks and counts, no new call, classed in quantile
    bands of this brief's blocks; off by default, its legend naming the vintage."""
    spec = c.map["residential"]
    lid = "residential_density"
    pop = c.payload("population_at_risk")
    if pop is None:
        return _layer(
            lid, spec["title"], "choropleth", reason=c.why_not("population_at_risk")
        )
    blocks = population_blocks(c)
    areas = [block_area_km2(b["geometry"]) for b in blocks]
    dens = [b["residents"] / a if a > 0 else 0.0 for b, a in zip(blocks, areas)]
    breaks = quantile_breaks(dens, int(spec["bands"]))
    ramp = spec["ramp"]
    lab = spec["label"].format(n=spec["bands"], blocks=len(blocks))
    plab = c.label("population_at_risk", only=["census:dhc2020", "tigerweb:census2020"])
    feats = []
    for b, v, km2 in zip(blocks, dens, areas):
        cls = sum(1 for x in breaks if v > x)
        geom = c.round(b["geometry"], simplify=True)
        if geom is None:
            continue
        feats.append(
            _feature(
                geom,
                _popup(
                    f"Census block {b['geoid']}: residential density",
                    [
                        ("Residents per km²", f"{v:,.0f}"),
                        ("Residents, whole block (2020 Census)", b["residents"]),
                        ("Block area", f"{km2:,.3f} km²"),
                        ("Band", f"{cls + 1} of {len(breaks) + 1}"),
                        ("Inside the footprint", _inside(b["partly"])),
                    ],
                    [f"{lab}; {plab}", b["glab"]],
                ),
                fill=ramp[min(cls, len(ramp) - 1)],
                density_km2=round(v, 1),
            )
        )
    return _layer(
        lid,
        spec["title"],
        "choropleth",
        features=feats,
        reason=NO_GEOMETRY,
        style={
            "color": "#ffffff",
            "weight": 0.6,
            "fillOpacity": 0.6,
            "breaks": [round(x, 1) for x in breaks],
        },
    )


def _downstream_layer(c: _Ctx) -> dict:
    title = "Downstream path"
    d = _derived(c, "downstream")
    if d is None:
        return _layer(
            "downstream", title, "line", reason="the derivations have not run"
        )
    if not d.get("path"):
        return _layer("downstream", title, "line", reason=d.get("reason") or "no path")
    col = c.map["colors"]["downstream"]
    st = d.get("start") or {}
    names = []
    for r in d["reaches"]:
        n = r.get("name") or "unnamed"
        if not names or names[-1] != n:
            names.append(n)
    rows = [
        (
            "Starts at",
            f"{st.get('name') or 'an unnamed flowline'} (3DHP {st.get('id3dhp')}), "
            f"{st.get('distance_m')} m from the spill",
        ),
        ("Flows through", " → ".join(names)),
        (
            "Length drawn",
            f"{d['length_m'] / 1000:.1f} km over {len(d['reaches'])} NHDPlus reaches",
        ),
        ("Not drawn", d.get("reason_partial")),
    ]
    labs = ["; ".join(t for t in (d["label"], _read_line(d, c.tz)) if t)]
    feat = _feature(
        {"type": d["path"]["type"], "coordinates": d["path"]["coordinates"]},
        _popup(title, rows, [t for t in labs if t]),
    )
    return _layer(
        "downstream",
        title,
        "line",
        features=[feat],
        reason="no path",
        style={"color": col, "weight": 4, "dash": "2 6"},
    )


def _puff_layers(c: _Ctx) -> list[dict]:
    """The first-order puff's two envelopes (DN-018 section 9; HB-67), off by default
    until the operator's display review rules otherwise (DN-012 ADDENDUM-01 section 4),
    and drawn below the ERG footprint. Each contour carries its engine, version,
    envelope, threshold, minute, class, wind as-of, wind source (and the station and
    its observed time when an observation stood in; HB-75), sigma source, threshold
    source and assumption; a missing input leaves the layer empty with the line that
    names it."""
    spec = c.cfg["weather"]["puff"]
    p = _derived(c, "puff")
    out = []
    # the source term's envelope takes the worst case's place where it exists (HB-110)
    present = {e.get("name") for e in (p or {}).get("envelopes") or []}
    first = "source_term" if "source_term" in present else "worst_case"
    for name in (first, "alternative"):
        title = spec["layer_title"].format(envelope=spec["envelopes"][name]["title"])
        lid = f"puff_{name}"
        if p is None:
            out.append(
                _layer(
                    lid,
                    title,
                    "polygon",
                    reason="the derivations have not run",
                )
            )
            continue
        env = next((e for e in p.get("envelopes") or [] if e["name"] == name), None)
        if env is None or not env.get("contours"):
            # an envelope that ran and drew nothing says so; it does not borrow
            # another envelope's line (HB-110: the source term's 0 m contours read
            # "hole size not given", the alternative's line)
            ran = env is not None and not env.get("reason") and "extents_m" in env
            why = (
                (env or {}).get("reason")
                or (spec["no_contour"] if ran else None)
                or "; ".join(p.get("lines") or [])
                or "no contour"
            )
            out.append(_layer(lid, title, "polygon", reason=why))
            continue
        sources = {
            i["name"].removeprefix("threshold "): i["source"]
            for i in p.get("inputs") or []
            if i["name"].startswith("threshold ")
        }
        feats = []
        for ct in env["contours"]:
            props = {
                "engine": p["engine"],
                "version": p["version"],
                "envelope": name,
                "threshold": ct["threshold"],
                "minute": ct["minute"],
                "class": p["class"],
                "wind_as_of": p["wind_as_of"],
                # what drove the puff (HB-75 step 4), and which observation when a
                # station stood in for a calm forecast hour
                "wind_source": p["wind_source"],
                # HB-133: the wind the puff read at hour 0 (from, degrees)
                "wind_from_deg": (p.get("wind_read") or {}).get("from_deg"),
                **(p.get("wind_station") or {}),
                "sigma_source": p["sigma_source"],
                "threshold_source": sources.get(ct["threshold"]),
                "assumption": env["assumption"],
                "quantity_source": env.get("quantity_source"),
                "hole_source": env.get("hole_source"),
                "reaches_grid_edge": ct.get("reaches_grid_edge", False),
            }
            rows = [
                ("Threshold", ct["threshold"]),
                ("At", f"{ct['minute']} minutes after the release began"),
                ("Farthest extent", f"{ct['extent_m']:,.0f} m from the spill"),
                ("Source assumed", env["assumption"]),
                ("Quantity from", env.get("quantity_source")),
                ("Release rate", env.get("rate_how")),
            ]
            # the label names its record, as every popup's does: the run record (C2)
            n = L.config()["hash_prefix_chars"]
            sha = (p.get("evidence") or {}).get("sha256", "")
            lab = f"{p['label']}; record {sha[:n]}"
            feats.append(_feature(ct["geometry"], _popup(title, rows, [lab]), **props))
        col = c.map["colors"][lid]
        out.append(
            _layer(
                lid,
                title,
                "polygon",
                features=feats,
                reason="no contour",
                # HB-133 ADDENDUM-01: a translucent band with a thin outline
                style={
                    "color": col,
                    "fill": col,
                    "weight": c.map["band_weight"],
                    "fillOpacity": c.map["band_fill_opacity"],
                    "dash": "6 4",
                },
            )
        )
    return out


def _dense_gas_layer(c: _Ctx) -> dict:
    """The dense-gas footprint (DN-020 section 3.3; HB-112): one layer, one legend
    entry naming the class and its level of concern in a responder's words (DN-019
    section 2 items 1 and 2; HB-112 ADDENDUM-00), in its own colour and dotted pattern
    (item 3), on by default (DN-019 section 3, `map.defaults`), drawn beside
    the puff and under the ERG footprint. Its popup carries DN-020 section 3.3's label
    and names the run record; a layer that is not drawn carries its one line."""
    spec = c.cfg["weather"]["dense_gas"]
    d = _derived(c, "dense_gas")
    legend = (d or {}).get("legend")
    # HB-161 item 9: the title is the layer's name and its key (the class and its
    # level), at most eight words; the legend's caveats and a proxy's name are the
    # TEVV section's (`_move_docs` moves `title_full` there)
    key = re.sub(r"\s*\([^()]*\)$", "", legend.split("; ")[0]) if legend else None
    title = (
        spec["layer_title"].format(legend=key) if key else "Modelled, dense gas (SLAB)"
    )
    full = spec["layer_title"].format(legend=legend) if legend else title
    if d is None:
        return _layer(
            "dense_gas",
            title,
            "polygon",
            reason="the derivations have not run",
        )
    feat = d.get("footprint")
    if not feat:
        # HB-120: not applicable (the routing table's reason, no layer) or not drawn
        why = (
            spec["not_applicable"].format(reason=d.get("reason"))
            if d.get("state") == "not_applicable"
            else spec["not_drawn"].format(what=d.get("reason") or "not drawn")
        )
        return _layer("dense_gas", title, "polygon", reason=why)
    props = feat["properties"]
    cmp_ = d.get("comparison") or {}
    beyond = props.get("beyond_table")
    first = next((b for b in d.get("bands") or [] if b.get("primary")), None)
    rows = [
        # HB-161 item 5: the band as a key (its level, value and time), as every other
        # band's popup gives it; the level's words with their source are the TEVV's
        (
            "Band",
            f"{first['tier']} {first['ppm']:g} ppm at {first['minutes']:g} min"
            if first
            else None,
        ),
        ("Level of concern", d["level"]["words"]),
        (
            "Farthest downwind",
            dg_reach(props["downwind_m"], beyond, spec) + " from the spill",
        ),
        (
            "Widest half-width",
            dg_reach(props["max_half_width_m"], props.get("beyond_width"), spec),
        ),
        ("Beside", cmp_.get("line")),
        # HB-157 ADDENDUM-02 item 1 and DN-024 section 3.5: SLAB takes one wind and its
        # tables are a time average, so the layer says both at every step
        ("Time it stands for", spec["averaged"].format(s=d["level"]["minutes"] * 60)),
        # SLAB takes one wind, the release hour's (DN-024 section 3.5); HB-163: on a
        # dense release no puff timeline holds the words, so they are the timeline's
        # own words for the release hour
        (
            "Wind",
            (_timeline(c)[1] or {}).get("one_wind")
            or c.cfg["weather"]["puff"]["steps"]["one_wind"].format(clock=_clock0(c)),
        ),
    ]
    n = L.config()["hash_prefix_chars"]
    sha = (d.get("evidence") or {}).get("sha256", "")
    lab = f"{d['label']}; record {sha[:n]}"
    col = c.map["colors"]["dense_gas"]
    keep = {
        k: props.get(k)
        for k in (
            "downwind_m",
            "beyond_table",
            "max_half_width_m",
            "beyond_width",
            "toward_deg",
            "parts",
        )
    }
    bands = d.get("bands") or []
    primary = next((b for b in bands if b.get("primary")), None)
    fprops = dict(
        engine=d["engine"],
        engine_id=d.get("engine_id"),
        dn001_class=d.get("class"),
        level_of_concern=d["level"]["words"],
        record=sha,
        band=(primary or {}).get("tier", d["level"]["kind"]),
        **keep,
    )
    # HB-157 item 6: a band SLAB's table (or the modelled time) ended inside is drawn
    # open at that end with its label, never closed by the table's straight edge
    words = d.get("open_end_words") or ""
    pop = _popup(title, rows, [lab])
    if props.get("open_end"):
        feats = _open_features(
            feat["geometry"],
            props["open_end"],
            pop,
            words,
            c.map["open_key"],
            **fprops,
        )
    else:
        feats = [_feature(feat["geometry"], pop, **fprops)]
    # HB-133 ADDENDUM-01: the other held levels as nested bands through the same SLAB
    # output, the class level first (its numbers are the legend's and the cue's)
    for b in bands:
        if b.get("primary") or not b.get("geometry"):
            continue
        brows = [
            ("Band", f"{b['tier']} {b['ppm']:g} ppm at {b['minutes']:g} min"),
            (
                "Farthest downwind",
                dg_reach(b["downwind_m"], b["beyond_table"], spec) + " from the spill",
            ),
            ("Threshold from", b.get("receipt")),
        ]
        bprops = dict(
            engine=d["engine"],
            band=b["tier"],
            downwind_m=b["downwind_m"],
            beyond_table=b["beyond_table"],
            toward_deg=props.get("toward_deg"),
            record=sha,
        )
        bpop = _popup(title, brows, [lab])
        if b.get("open_end"):
            feats += _open_features(
                b["geometry"], b["open_end"], bpop, words, c.map["open_key"], **bprops
            )
        else:
            feats.append(_feature(b["geometry"], bpop, **bprops))
    lay = _layer(
        "dense_gas",
        title,
        "polygon",
        features=feats,
        reason="no footprint",
        style={
            "color": col,
            "fill": col,
            "weight": c.map["band_weight"],
            "fillOpacity": c.map["band_fill_opacity"],
            "dash": "1 6",
        },
    )
    if full != title:
        lay["title_full"] = full
    return lay


# ── HB-163: one modelled cloud, by health-effect level (DN-026; DN-028) ──────────────


def engine_class(c: _Ctx) -> str | None:
    """The release's class by the selection rule (`engine_rule`): "dense", "passive",
    "not_determined", or None where no release was computed (the guide routes none, or
    an input stopped the source term before the rule)."""
    return (_derived(c, "engine_rule") or {}).get("class")


def one_engine(c: _Ctx) -> bool:
    """A release the rule does not class passive: the modelled cloud is its only model,
    and nothing the puff derives is drawn (HB-163 ADDENDUM-02 item 2)."""
    return engine_class(c) in ("dense", "not_determined")


def cloud_drawn(c: _Ctx) -> dict | None:
    d = _derived(c, "cloud")
    return d if d and d.get("state") == "drawn" else None


def _cloud_lab(c: _Ctx, d: dict) -> str:
    """The cloud's label line, naming its held record (DN-010)."""
    n = L.config()["hash_prefix_chars"]
    spec = c.map["cloud"]
    # DN-025 section 3 item 5: a passive release's cloud names the puff, its run record
    key = "label_puff" if d.get("engine_key") == "puff" else "label"
    return (
        spec[key].format(
            engine=d["engine"],
            engine_id=d.get("engine_id") or "",
            release=d["release_minutes"],
        )
        + f"; record {d['record'][:n]}"
    )


def _clock0(c: _Ctx) -> str:
    """The release hour's clock time, as the puff's timeline names it."""
    from hazbrief.brief import derive as D

    return D._clock(c.brief, 0)


def _step_words(c: _Ctx, minute: int) -> str:
    from hazbrief.brief import derive as D

    return f"{D.hplus(minute)} ({D._clock(c.brief, minute)})"


def time_steps(d: dict) -> list[dict]:
    """HB-192: the cloud's steps the map and the time control show: its 15-minute
    frames where a frames record is held (DN-024 ADDENDUM-01), else every output
    step (a passive puff's samples, or a dense run held without frames)."""
    return d.get("frames") or d["steps"]


def cloud_level_ids(cfg) -> list[str]:
    """The level layers' ids, lowest concern first (the draw order: the innermost
    level is drawn on top)."""
    return [lv["id"] for lv in cfg["map"]["cloud"]["levels"].values()]


def _cloud_layers(c: _Ctx) -> list[dict]:
    """HB-163 items 4 and 5 (ADDENDA 01 and 03): the cloud as three nested filled areas,
    one per AEGL tier, each its own toggle, the innermost on top; each layer holds the
    area the level reaches at any time (the harm path, `view` "path", the default
    view) and its area at every output step (`view` "time", `step`), which the time
    control and Animate show. Where the rule classes the release dense or cannot class
    it and the cloud is not drawn, one row says why (ADDENDUM-02 item 2; ADDENDUM-06
    item 5)."""
    spec = c.map["cloud"]
    d = cloud_drawn(c)
    # HB-162R (DN-025 section 3 item 5): a passive release's cloud by level is the
    # puff's run, drawn here as SCICHEM's is; a passive release with none draws no row
    if not one_engine(c) and d is None:
        return []
    if d is None:
        why = (_derived(c, "cloud") or {}).get("reason") or spec["no_cloud"]
        return [
            _layer(
                spec["not_modelled_id"],
                spec["not_modelled_title"],
                "polygon",
                reason=why,
            )
        ]
    lab = _cloud_lab(c, d)
    out = []
    for t in d["tiers"]:
        lv = spec["levels"].get(t["name"])
        if lv is None:
            continue
        title = lv["title"]
        level = spec["level_row"].format(**t)
        feats = []
        g = d["any_time"].get(t["name"])
        if g:
            feats.append(
                _feature(
                    g,
                    _popup(
                        title, [("Level", level), ("View", spec["path_view"])], [lab]
                    ),
                    view="path",
                    band=t["name"],
                    record=d["record"],
                )
            )
        # HB-192 (DN-024 ADDENDUM-01 decision 5): the cloud at a time is its 15-minute
        # frames' outlines, drawn from the stored mesh, where a frames record is held
        for s in time_steps(d):
            gs = s["tiers"].get(t["name"])
            if not gs:
                continue
            feats.append(
                _feature(
                    gs,
                    _popup(
                        title,
                        [("Level", level), ("At", _step_words(c, s["minute"]))],
                        [lab],
                    ),
                    view="time",
                    step=s["minute"],
                    band=t["name"],
                    record=d["record"],
                )
            )
        # HB-178 (Issue 78ccbb4b; HBD-419): where the level's area meets the engine's
        # grid, the cut is drawn there as its own dashed line (a second cue beside
        # colour, NUREG-0700 r4 1.3.8-10), and the legend entry says so
        cut = (d.get("cut_edges") or {}).get(t["name"]) if g else None
        if cut:
            cs = spec["cut"]
            # HB-182: the edge this level's own area meets (one level can meet the
            # field's edge where it ends at 28.5 km and where it ends at 29.25 km)
            km = cs["km_join"].join(
                cs["km"].format(e) for e in (d.get("cut_edge_km") or {})[t["name"]]
            )
            words = cs["words"].format(km=km)
            feats.append(
                _feature(
                    cut,
                    _popup(
                        cs["title"].format(name=t["name"]),
                        [("Level", level), ("Cut", words), ("Shown so", cs["basis"])],
                        [lab],
                    ),
                    view="path",
                    band=t["name"],
                    record=d["record"],
                    color=cs["color"],
                    dash=cs["dash"],
                    weight=cs["weight"],
                    cut=True,
                )
            )
        lay = _layer(
            lv["id"],
            title,
            "polygon",
            features=feats,
            reason=spec["not_reached"],
            style={
                "color": lv["color"],
                "fill": lv["color"],
                "weight": spec["weight"],
                "fillOpacity": spec["fill_opacity"],
            },
        )
        lay["stepped"] = True
        lay["viewed"] = True
        lay["key"] = spec["key"].format(**t)
        if cut:
            lay["key"] += spec["cut"]["key"]
        # DN-028 ADDENDUM-14 decisions 1, 3 and 8: under the stable treatment the moving
        # cloud is the primary layer; the legend states its vertical setting as an
        # approximation, and a level outside the action levels (AEGL-1) is outlined,
        # its features unfilled (the page's style reads a feature's own `fill`)
        if slab_levels(c):
            sl = c.map["slab_levels"]
            vres = float(_derived(c, "agreement").get("vertical_setting_m") or 0.0)
            lay["key"] += sl["cloud_key"].format(vres=vres)
            # the row's figure never shrinks (render.py `li.lrow .n`), so the row
            # prints a short figure and the key stays the legend's
            lay["figure"] = sl["cloud_figure"].format(vres=vres)
            if lv["id"] in sl["outlined_levels"]:
                for f in lay["features"]:
                    if not f["properties"].get("cut"):
                        f["properties"]["fill"] = c.map["planning"]["check_fill"]
        out.append(lay)
    return out


def _cloud_extent_layer(c: _Ctx) -> list[dict]:
    """HB-163 ADDENDUM-06 item 2 (HBD-378, HBD-379): the uncertainty area, one outlined
    shape, off by default: per step the outermost tier's area with the area where the
    probability of exceeding it is at least 5 percent (`view` "time"), and on the harm
    path the union over all steps (`view` "path"). Its key says turbulence only."""
    spec = c.map["cloud"]["extent"]
    d = cloud_drawn(c)
    # DN-025 section 3 item 5: the puff gives no concentration variance, so no extent
    if d is None or d.get("engine_key") == "puff":
        return []
    lab = _cloud_lab(c, d)
    outer = d["tiers"][0]
    level = c.map["cloud"]["level_row"].format(**outer)
    feats = []
    if d.get("any_time_extent"):
        feats.append(
            _feature(
                d["any_time_extent"],
                _popup(spec["title"], [("Level", level)], [lab]),
                view="path",
                record=d["record"],
            )
        )
    at = {s["minute"] for s in time_steps(d)}
    for s in d["steps"]:
        if s.get("extent") and s["minute"] in at:
            feats.append(
                _feature(
                    s["extent"],
                    _popup(
                        spec["title"],
                        [("Level", level), ("At", _step_words(c, s["minute"]))],
                        [lab],
                    ),
                    view="time",
                    step=s["minute"],
                    record=d["record"],
                )
            )
    lay = _layer(
        spec["id"],
        spec["title"],
        "polygon",
        features=feats,
        reason=c.map["cloud"]["not_reached"],
        style={
            "color": spec["color"],
            "weight": spec["weight"],
            "fillOpacity": 0,
            "dash": spec["dash"],
        },
    )
    lay["stepped"] = True
    lay["viewed"] = True
    lay["key"] = spec["key"].format(**outer)
    return [lay]


def slab_levels(c: _Ctx) -> bool:
    """Whether the brief takes the stable treatment, its levels the planning areas
    (DN-028 ADDENDUM-14 decisions 2 and 6; `agreement.build` sets `levels`)."""
    ag = _derived(c, "agreement") or {}
    return ag.get("levels") == "planning" and bool(ag.get("planning"))


def _planning_layer(c: _Ctx) -> list[dict]:
    """HB-173 (HBD-390; DN-028 ADDENDUM-04 decision 6), as DN-028 ADDENDUM-14
    decisions 5 and 6 amend it: under the stable treatment each level's planning area
    is the moving cloud's area together with SLAB's extent check. The cloud's area is
    its own stepped levels, filled (`_cloud_layers`); this layer draws SLAB's part
    outside it, a dashed outline in the level's colour with no fill, told apart from
    the filled cloud without colour (`map.planning`). A level SLAB's band is cut inside
    (its table's end or the time bound) is drawn open at that end with its key. It is
    an area with no time, so it stands in both views. Where SLAB's reach lies past the
    release hour's wind's travel over the steps' horizon, the popup says how many hours
    that wind takes. A brief with none offers no row."""
    from hazbrief.brief import agreement as AG
    from hazbrief.brief import dense_gas as DG

    spec = c.map["planning"]
    ag = _derived(c, "agreement") or {}
    plan = ag.get("planning") or {}
    d = cloud_drawn(c)
    if not plan or d is None:
        return []
    w = AG.load_config()["words"]
    rows = {r["tier"]: r for r in ag.get("reaches") or []}
    lab = _cloud_lab(c, d)
    dense = _derived(c, "dense_gas") or {}
    sha = (dense.get("evidence") or {}).get("sha256", "")
    n = L.config()["hash_prefix_chars"]
    slab_lab = spec["label"].format(record=sha[:n])
    words = dense.get("open_end_words") or ""
    deck = ((dense.get("evidence") or {}).get("record") or {}).get("deck")
    ua = float(DG.read_deck(deck)[0]["ua"]) if deck else None
    horizon_h = float(c.cfg["weather"]["puff"]["steps"]["horizon_h"])
    feats = []
    drawn = []
    # the outermost level first, as the cloud's layers nest
    for t in d["tiers"]:
        p = plan.get(t["name"])
        lv = c.map["cloud"]["levels"].get(t["name"])
        if p is None or lv is None or not p.get("check"):
            continue
        drawn.append(t["name"])
        r = rows[t["name"]]
        head = [
            ("Level", c.map["cloud"]["level_row"].format(**t)),
            ("Area of", spec["engine"][p["engine"]]),
        ]
        tail = [
            (
                spec["reach_slab"],
                AG.reach_text(r["slab_m"], r["slab_cut"], "cut_time", w),
            ),
            (
                spec["reach_scichem"],
                AG.reach_text(r["scichem_m"], r["scichem_cut"], "cut_domain", w),
            ),
        ]
        if ua and r.get("slab_m"):
            hours = float(r["slab_m"]) / ua / 3600.0
            if hours > horizon_h:
                tail.append(
                    (
                        spec["travel"],
                        spec["travel_words"].format(h=hours, ms=ua, horizon=horizon_h),
                    )
                )
        tail.append(("Times", spec["times"]))
        # DN-028 ADDENDUM-14 decision 6: the moving cloud's part is its own stepped
        # levels, filled; this layer draws SLAB's extent check outside it, no fill and a
        # dash, told apart from the filled cloud without colour. The page's style reads
        # a feature's own `fill` (an SVG paint, so "none" paints no fill) and `dash`
        # (render.py, HB-173), so no script changes
        geom = p.get("check")
        if not geom:
            continue
        pop = _popup(
            spec["title"],
            [*head, ("Part", spec["part"]["check"]), *tail],
            [slab_lab, lab],
        )
        props = dict(
            band=t["name"],
            engine=p["engine"],
            part="check",
            color=lv["color"],
            record=sha,
            fill=spec["check_fill"],
            dash=spec["check_dash"],
        )
        if p.get("open_end") and p.get("slab_cut"):
            feats += _open_features(
                geom, p["open_end"], pop, words, c.map["open_key"], **props
            )
        else:
            feats.append(_feature(geom, pop, **props))
    if not feats:
        # SLAB's area lies inside the moving cloud's at every level: nothing to draw,
        # and no row (a brief with none offers no row)
        return []
    lay = _layer(
        spec["id"],
        spec["title"],
        "polygon",
        features=feats,
        reason=c.map["cloud"]["not_reached"],
        style={
            "color": c.map["cloud"]["levels"][d["tiers"][0]["name"]]["color"],
            "fill": c.map["cloud"]["levels"][d["tiers"][0]["name"]]["color"],
            "weight": spec["weight"],
            "fillOpacity": c.map["cloud"]["fill_opacity"],
        },
    )
    lay["key"] = spec["key"].format(levels=", ".join(reversed(drawn)))
    lay["figure"] = spec["figure"].format(n=len(drawn))
    return [lay]


def engine_alerts(brief, cfg) -> list[dict]:
    """HB-173 items 3 and 10 (DN-028 ADDENDUM-04 decision 7): the checklist's one item
    on the two engines of a dense release. Where the measure is outside the held factor,
    an alert (`engines`); where inside, the one line where the alert would be
    (`engines_agree`); where they were not compared, that line, as `engines_agree`.
    Each with its receipt: the held factor's source and the measure's TEVV section,
    which is the alert's pop-out."""
    from hazbrief.brief import agreement as AG
    from hazbrief.brief import tevv

    ag = (getattr(brief, "derived", None) or {}).get("agreement")
    cl = (getattr(brief, "derived", None) or {}).get("cloud") or {}
    if not ag or cl.get("state") != "drawn":
        return []
    acfg = AG.load_config()
    receipt = acfg["words"]["receipt"].format(
        factor_cite=acfg["measure"]["factor_source"]["cite"],
        link_text=cfg["tevv"]["link_text"],
        ref=tevv.ref(cfg, "agreement"),
    )
    if ag.get("levels") == "planning":
        # DN-028 ADDENDUM-10 decisions 2 and 4: under a stable class no two-methods
        # warning; one line says the levels are SLAB's and SCICHEM's forecast-following
        # cloud is unresolved under these conditions, with its Conditions of use
        ref = tevv.ref(cfg, "conditions_scichem")
        return [
            {
                "kind": "engines_stable",
                "text": AG.stable_line(ag, acfg, ref),
                "receipt": f"{cfg['tevv']['link_text']} {ref}",
            }
        ]
    kind = "engines" if ag.get("warning", ag.get("alert")) else "engines_agree"
    return [{"kind": kind, "text": AG.line(ag, acfg), "receipt": receipt}]


# ── the plume over time (HB-157; DN-024 sections 3.1 and 3.5 to 3.9) ─────────────────


def _open_features(
    geom: dict,
    ends: dict | list | None,
    popup: dict,
    words: str,
    key: str,
    **props,
):
    """A polygon whose edge is partly where the run stopped, not the cloud (DN-024
    section 3.1): the fill with no outline (`open`), its outline without the open part
    as a line, and a point at the open end that says so. `ends` is the open part (a
    GeoJSON geometry) or the two end points of a straight cut ([lon, lat] pairs)."""
    from shapely.geometry import LineString, shape

    poly = shape(geom)
    cut = LineString(ends) if isinstance(ends, list) else shape(ends)
    rest = poly.boundary.difference(cut.buffer(1e-6))
    mid = cut.interpolate(0.5, normalized=True)
    out = [_feature(geom, popup, open=True, **props)]
    keep = ("step", "wind_source", "wind_from_deg", "reaches_grid_edge")
    aux = {k: v for k, v in props.items() if k in keep}
    aux["open_of"] = props.get("band") or props.get("step")
    # HB-161 item 6: the open end is a key on the map ("continues beyond what is
    # drawn"); the sentence that says how the run ended goes to the TEVV section
    # (`tevv.moved_rows` "How the band ends")
    if not rest.is_empty:
        out.append(
            _feature(
                json.loads(json.dumps(mapping(rest))),
                {"html": popup["html"], "labs": list(popup["labs"])},
                outline_of_open=True,
                **aux,
            )
        )
    out.append(
        _feature(
            {"type": "Point", "coordinates": [round(mid.x, 6), round(mid.y, 6)]},
            {
                "html": popup["html"].replace(
                    "</table>",
                    _row_html("Open end", key)
                    + _row_html("How the band ends", words)
                    + "</table>",
                    1,
                ),
                "labs": list(popup["labs"]),
            },
            open_end=key,
            **aux,
        )
    )
    return out


def _row_html(k: str, v: str) -> str:
    return f"<tr><th>{esc(k)}</th><td>{esc(v)}</td></tr>"


def _timeline_lab(c: _Ctx, p: dict) -> str:
    """The puff's label naming its run record (every popup label line names one)."""
    n = L.config()["hash_prefix_chars"]
    sha = (p.get("evidence") or {}).get("sha256", "")
    return f"{p['label']}; record {sha[:n]}"


def _wind_props(p: dict, at_edge: bool = False) -> dict:
    """What drove the puff, on every one of its features (HB-75 step 4; HB-133), and
    whether the feature reaches the grid's edge (HB-69's `reaches_grid_edge`: only an
    open step outline does)."""
    return {
        "reaches_grid_edge": at_edge,
        "wind_source": p["wind_source"],
        "wind_from_deg": (p.get("wind_read") or {}).get("from_deg"),
        **(p.get("wind_station") or {}),
    }


def _timeline(c: _Ctx) -> tuple[dict | None, dict | None, str | None]:
    """(puff, its timeline, why there is none)."""
    p = _derived(c, "puff")
    if p is None:
        return None, None, "the derivations have not run"
    tl = p.get("timeline")
    if not tl:
        return p, None, "; ".join(p.get("lines") or []) or "the puff drew no envelope"
    if tl.get("reason"):
        return p, None, tl["reason"]
    return p, tl, None


def _arrival_layer(c: _Ctx) -> dict:
    """HB-157 item 11: the arrival bands, the first time the level is reached at each
    place, banded at the steps, darkest first; each band labelled with its time after
    release and its clock time. The default modelled view."""
    lid = "arrival_bands"
    p, tl, why = _timeline(c)
    title = (tl or {}).get("arrival_title") or "Modelled arrival, first order"
    if tl is None:
        return _layer(lid, title, "polygon", reason=why)
    ramp = c.map["arrival_ramp"]
    lab = _timeline_lab(c, p)
    shift = (tl.get("shift") or {}).get("minute")
    feats = []
    for i, b in enumerate(tl.get("bands") or []):
        if not b.get("geometry"):
            continue
        rows = [
            ("Reached", b["label"]),
            ("Level of concern", tl["level_line"]),
            ("Modelled time", tl["end_line"]),
            ("Wind", tl["one_wind"]),
            (
                "Wind shift",
                (tl.get("shift") or {}).get("item") if shift == b["minute"] else None,
            ),
        ]
        feats.append(
            _feature(
                b["geometry"],
                _popup(f"{title}: {b['hplus']}", rows, [lab]),
                fill=ramp[min(i, len(ramp) - 1)],
                minute=b["minute"],
                **_wind_props(p),
                shift=shift == b["minute"],
            )
        )
    col = c.map["colors"][lid]
    return _layer(
        lid,
        title,
        "polygon",
        features=feats,
        reason="the level is not reached anywhere",
        style={"color": col, "weight": 0.8, "fillOpacity": 0.35},
    )


def _step_layer(c: _Ctx) -> dict:
    """HB-157 item 12: the outline at each step, one shown at a time by the time
    control (`step`); a step outline still at the grid's edge is drawn open."""
    lid = "step_outline"
    p, tl, why = _timeline(c)
    title = (tl or {}).get("step_title") or "Modelled step outline, first order"
    if tl is None:
        return _layer(lid, title, "polygon", reason=why)
    lab = _timeline_lab(c, p)
    feats = []
    for s in tl.get("steps") or []:
        if not s.get("geometry"):
            continue
        wind = s.get("wind") or {}
        rows = [
            ("Step", f"{s['hplus']} ({s['clock']})"),
            ("Level of concern", tl["level_line"]),
            (
                "Wind at the step",
                f"from {wind['from_deg']} degrees, {wind['kmh']} km/h "
                f"({wind['source']})"
                if wind
                else None,
            ),
            (
                "Wind the outline was computed on",
                tl["one_wind"] if s["after_own_wind"] else None,
            ),
            ("Modelled time", tl["end_line"]),
        ]
        pop = _popup(f"{title}: {s['hplus']}", rows, [lab])
        if s.get("open") and s.get("open_ends"):
            feats += _open_features(
                s["geometry"],
                s["open_ends"],
                pop,
                s["open_end"],
                c.map["open_key"],
                step=s["minute"],
                **_wind_props(p, at_edge=True),
            )
        else:
            feats.append(
                _feature(s["geometry"], pop, step=s["minute"], **_wind_props(p))
            )
    col = c.map["colors"][lid]
    lay = _layer(
        lid,
        title,
        "polygon",
        features=feats,
        reason="the level is not reached at any step",
        style={"color": col, "fill": col, "weight": 2.5, "fillOpacity": 0.08},
    )
    lay["stepped"] = True
    return lay


def _uncertainty_layer(c: _Ctx) -> list[dict]:
    """The wind-direction uncertainty lines, hazbrief's calculation by the construction
    NOAA publishes (HB-157 ADDENDA 03 to 05): the outline rotated through the angle on
    either side of the wind, drawn as two lines with no fill. HB-163 ADDENDUM-01 item 3
    (and ADDENDUM-06 item 1): they bound the harm path, not each step, so no end-member
    outline moves with the time control; on a dense release they are drawn about the
    cloud's outermost level reached at any time, on a passive one about the area the
    puff's steps reached. None where no cloud is drawn on a dense release."""
    lid = "uncertainty_lines"
    spec = c.cfg["weather"]["puff"]["uncertainty"]
    title = spec["title"]
    col = c.map["colors"][lid]
    style = {"color": col, "weight": 1.5, "dash": "8 5"}
    # HB-162R (DN-025 section 3 item 4): a passive release whose cloud the puff draws by
    # level has its side lines about that cloud, on each step's own wind
    if one_engine(c) or cloud_drawn(c) is not None:
        d = cloud_drawn(c)
        if d is None:
            return []
        sl = d.get("side_lines") or {}
        if not sl.get("lines"):
            return [_layer(lid, title, "line", reason=sl.get("reason") or "no angle")]
        lab, around, credit = _cloud_lab(c, d), spec["around_cloud"], sl["credit"]
    else:
        p, tl, why = _timeline(c)
        if tl is None:
            return [_layer(lid, title, "line", reason=why)]
        sl = tl.get("side_lines") or {}
        if not sl.get("lines"):
            unc = tl.get("uncertainty") or {}
            return [
                _layer(lid, title, "line", reason=unc.get("reason") or sl.get("reason"))
            ]
        lab, around, credit = _timeline_lab(c, p), spec["around_reached"], sl["credit"]
    feats = [
        _feature(
            g,
            _popup(
                title,
                [
                    ("Around", around.format(tier=sl.get("tier") or "")),
                    ("Side", "rotated +alpha" if i == 0 else "rotated -alpha"),
                    ("Method", credit),
                ],
                [lab],
            ),
        )
        for i, g in enumerate(sl["lines"])
        if g
    ]
    return [
        _layer(
            lid,
            title,
            "line",
            features=feats,
            reason="no outline to draw them around",
            style=style,
        )
    ]


def _range_layer(c: _Ctx) -> dict:
    """ADDENDUM-02 item 3: the range of plume paths at each step, a faint band, off by
    default, never in the uncertainty lines' style; "not a probability"."""
    lid = "plume_range"
    p, tl, why = _timeline(c)
    title = c.cfg["weather"]["puff"]["range"]["title"]
    if tl is None:
        return _layer(lid, title, "polygon", reason=why)
    if tl.get("range_reason"):
        return _layer(lid, title, "polygon", reason=tl["range_reason"])
    lab = _timeline_lab(c, p)
    feats = [
        _feature(
            s["range"],
            _popup(
                title,
                [
                    ("Step", f"{s['hplus']} ({s['clock']})"),
                    ("Runs", tl.get("range_what")),
                ],
                [lab],
            ),
            step=s["minute"],
            **_wind_props(p),
        )
        for s in tl.get("steps") or []
        if s.get("range")
    ]
    col = c.map["colors"][lid]
    lay = _layer(
        lid,
        title,
        "polygon",
        features=feats,
        reason="no step outline to range around",
        style={"color": col, "fill": col, "weight": 0, "fillOpacity": 0.25},
    )
    lay["stepped"] = True
    return lay


def arrival_line(c: _Ctx) -> str | None:
    """HB-157 item 14: the earliest modelled arrival at the nearest listed service of
    each class (the Responders tab's list), from the arrival bands: the first step
    whose reached area holds it, or "not reached" by the run's end. None when no step
    ran or no service is listed. Evacuation order is not computed (DN-024 section
    3.11)."""
    spec = c.cfg["derive"]["modelled"]["arrival"]
    _, tl, _ = _timeline(c)
    near = _derived(c, "nearby") or {}
    if tl is None or not (
        near.get("classes") or ((_derived(c, "siting") or {}).get("points"))
    ):
        return None
    from shapely.geometry import Point

    titles = c.cfg["derive"]["nearby"]["classes"]
    reached = [
        (s, shape(s["reached"])) for s in tl.get("steps") or [] if s.get("reached")
    ]
    end = tl["steps"][-1]
    parts = []
    for cls, rows in near["classes"].items():
        if not rows:
            continue
        r = rows[0]
        pt = Point(r["coordinates"])
        hit = next((s for s, g in reached if g.covers(pt)), None)
        when = (
            spec["by"].format(hplus=hit["hplus"], clock=hit["clock"])
            if hit
            else spec["not_reached"].format(hplus=end["hplus"])
        )
        parts.append(
            spec["part"].format(
                service=titles[cls]["title"], name=r.get("name"), when=when
            )
        )
    # HB-155 ADDENDUM-04 item 2: the suggested points too (recomputed on a move by the
    # live page's server, `siting.move`)
    for pid, p in ((_derived(c, "siting") or {}).get("points") or {}).items():
        if not p:
            continue
        pt = Point(p["coordinates"])
        hit = next((s for s, g in reached if g.covers(pt)), None)
        when = (
            spec["by"].format(hplus=hit["hplus"], clock=hit["clock"])
            if hit
            else spec["not_reached"].format(hplus=end["hplus"])
        )
        parts.append(
            spec["part"].format(service=p["title"], name=p.get("name"), when=when)
        )
    if not parts:
        return None
    return spec["line"].format(level=tl["level"]["threshold"], parts="; ".join(parts))


def time_alerts(brief, cfg) -> list[dict]:
    """HB-157: the checklist's items from the modelled time (`kind`, `text`,
    `receipt`): the wind-shift Verify item (ADDENDUM-02 item 2) and the arrival line
    (item 14), in a group of its own (ADDENDUM-01 section 2 item 7)."""
    c = _Ctx(brief, cfg)
    spec = cfg["derive"]["modelled"]["arrival"]
    _, tl, _ = _timeline(c)
    out = []
    if tl and tl.get("shift"):
        out.append(
            {
                "kind": "shift",
                "text": tl["shift"]["item"],
                "receipt": spec["shift_receipt"],
            }
        )
    line = arrival_line(c)
    if line:
        out.append({"kind": "arrival", "text": line, "receipt": spec["receipt"]})
    return out


def modelled_figure(c: _Ctx) -> str | None:
    """HB-157 item 7: the second population figure, in `derive.modelled.figure`'s
    words beside the ERG figure; None where it is absent (no modelled layer drawn), and
    the reason where it was not read."""
    d = _derived(c, "modelled_population")
    spec = c.cfg["derive"]["modelled"]
    if not d or d.get("absent"):
        return None
    if d.get("reason"):
        return f"{spec['title']}: not read ({d['reason']})"
    erg = (
        spec["erg_words"].format(residents=d["erg_residents"], workers=d["erg_workers"])
        if d.get("erg_residents") is not None and d.get("erg_workers") is not None
        else spec["erg_absent"]
    )
    workers = (
        spec["figure_workers"].format(workers=d["workers"])
        if d.get("workers") is not None
        else ""
    )
    # HB-178 (Issue 78ccbb4b; HBD-419): an area the engine's grid or SLAB's table cuts
    # is a lower bound, and so is every count under it: "at least", with what cut it
    cuts = cut_levels(c)
    engines = [
        spec["cut_engine"].format(what=e, by=cuts[e]) if e in cuts else e
        for e in d["engines"]
    ]
    text = spec["figure"].format(
        residents=d["residents"],
        workers=workers,
        engines="; ".join(engines),
        area=d["area_km2"],
        blocks=d["blocks"]["total"],
        outside=d["blocks"]["outside_erg"],
        erg=erg,
    )
    if d.get("parts"):
        # DN-028 ADDENDUM-14 decisions 6 and 7: under the stable treatment the count of
        # the action levels' planning area with its parts
        text += spec["figure_parts"].format(**d["parts"])
    if any(e in cuts for e in d["engines"]):
        text = spec["at_least"] + text
    band = d.get("band")
    if band and band.get("levels"):
        # decision 8 (Desktop's assumption): the AEGL-1 band, counted separately
        names = c.cfg["derive"]["modelled"]["names"]
        cut = any(names["planning"].format(tier=t) in cuts for t in band["levels"])
        n = f"{band['residents']:,}"
        text += spec["figure_band"].format(
            residents=(spec["at_least"] + n) if cut else n,
            levels=" and ".join(band["levels"]),
        )
    return text


def cut_levels(c: _Ctx) -> dict[str, str]:
    """HB-178 (Issue 78ccbb4b; HBD-419): each drawn modelled layer's name, as the
    modelled population lists it (`derive.modelled.names`), whose area is cut, with
    what cut it: a cloud level whose area meets the engine's grid; a planning area
    (under a stable class SLAB's area together with SCICHEM's, DN-028 ADDENDUM-12
    decision 2) with a cut part: SLAB's band reaching the end of its table, or the
    forecast-turned part meeting SCICHEM's domain (`threat.cut_by`, the same rule)."""
    from hazbrief.brief import agreement as AG

    words = c.cfg["derive"]["modelled"]["names"]
    w = AG.load_config()["words"]
    out = {}
    d = cloud_drawn(c)
    if d is None:
        return out
    for t, is_cut in (d.get("reach_cut") or {}).items():
        if is_cut and (d.get("any_time") or {}).get(t):
            out[words["cloud"].format(tier=t)] = w["cut_domain"]
    ag = _derived(c, "agreement") or {}
    rows = {r["tier"]: r for r in ag.get("reaches") or []}
    for t, p in (ag.get("planning") or {}).items():
        by = []
        if p.get("slab_cut", (rows.get(t) or {}).get("slab_cut")):
            # HB-189 (DN-028 ADDENDUM-14 decision 5): under the stable treatment SLAB's
            # part is cut by the time bound, not by its table
            by.append(w["cut_time"])
        if p.get("scichem_cut"):
            by.append(w["cut_domain"])
        if by:
            out[words["planning"].format(tier=t)] = " and ".join(by)
    return out


def _modelled_population_layer(c: _Ctx) -> dict:
    """HB-157 item 7: the blocks under the modelled area, as the population layer draws
    its blocks, labelled with the figure beside the ERG's; absent, not zero, where no
    modelled layer is drawn."""
    lid = "modelled_population"
    spec = c.cfg["derive"]["modelled"]
    title = spec["title"]
    d = _derived(c, "modelled_population")
    if d is None:
        return _layer(lid, title, "choropleth", reason="the derivations have not run")
    if d.get("absent") or d.get("reason"):
        return _layer(
            lid, title, "choropleth", reason=d.get("reason") or spec["absent"]
        )
    breaks = c.map["population_breaks"]
    ramp = c.map["population_ramp"]
    lab = _read_line(d, c.tz)
    fig = modelled_figure(c)
    # HB-192 (DN-024 ADDENDUM-01 decision 9): drawn coarse, counted fine. The blocks
    # are dissolved by colour class, one shape per class; every count is still the
    # rows' (block by block), and nothing here changes one
    ds = c.map["population_dissolve"]
    by: dict[int, list] = {}
    for r in d.get("rows") or []:
        n = r["residents"]
        if n is None or not r.get("geometry"):
            continue
        by.setdefault(sum(1 for x in breaks if n >= x), []).append(r)
    feats = []
    for k in sorted(by):
        rs = by[k]
        geom = _dissolved([r["geometry"] for r in rs], float(ds["tolerance_deg"]))
        # rounded, not cropped: the modelled area runs past the view's clip box (F2)
        geom = c.round(geom) if geom is not None else None
        if geom is None:
            continue
        if k == 0:
            rng = ds["range_first"].format(hi=breaks[0])
        elif k == len(breaks):
            rng = ds["range_last"].format(lo=breaks[-1])
        else:
            rng = ds["range_mid"].format(lo=breaks[k - 1], hi_less=breaks[k] - 1)
        feats.append(
            _feature(
                geom,
                _popup(
                    ds["title"].format(range=rng),
                    [
                        (ds["blocks"], len(rs)),
                        (ds["residents"], sum(int(r["residents"]) for r in rs)),
                        (ds["counted"], ds["counted_words"]),
                        ("Figure", fig),
                    ],
                    [lab],
                ),
                fill=ramp[k],
            )
        )
    col = c.map["colors"][lid]
    return _layer(
        lid,
        title,
        "choropleth",
        features=feats,
        reason="no block under the modelled area",
        style={"color": col, "weight": 0.8, "fillOpacity": 0.5},
    )


def _dissolved(geoms: list[dict], tolerance_deg: float) -> dict | None:
    """HB-192: GeoJSON geometries unioned into one, simplified within `tolerance_deg`
    (topology kept); None where nothing is left."""
    from shapely.geometry import shape
    from shapely.ops import unary_union

    parts = [make_valid(shape(g)) for g in geoms]
    parts = [p for p in parts if not p.is_empty and p.area > 0]
    if not parts:
        return None
    u = unary_union(parts).simplify(tolerance_deg, preserve_topology=True)
    if u.is_empty:
        return None
    if u.geom_type == "GeometryCollection":
        polys = [g for g in u.geoms if g.geom_type in ("Polygon", "MultiPolygon")]
        if not polys:
            return None
        u = unary_union(polys)
    return mapping(u)


def dg_reach(x: float, beyond: bool | None, spec: dict) -> str:
    """A reach on the popup: "beyond <x> m" where SLAB's table ends first (HB-112)."""
    return spec["beyond_line" if beyond else "reach_line"].format(x=x)


def build(brief, cfg) -> dict:
    """{"layers": [...], "extent": [[south, west], [north, east]] or None}, in draw
    order (polygons under lines under points)."""
    from hazbrief.brief import tevv

    # HB-162R (DN-025): a passive release's cloud layers document the puff's sections
    cfg = tevv.brief_cfg(cfg, brief)
    c = _Ctx(brief, cfg)
    fpl = {lay["id"]: lay for lay in _footprint_layers(c)}
    fac = {lay["id"]: lay for lay in _facility_layers(c)}
    # HB-163 ADDENDUM-02 item 2 (DN-026): one engine per release. A release the rule
    # classes dense (or cannot class) draws the modelled cloud and nothing the puff
    # derives; SLAB, the second dense-gas method, is a layer only beside a drawn
    # cloud (ADDENDUM-03 item 2; never in its place, HBD-376). A passive release draws
    # the puff and no dense-gas layer. A brief whose release was never computed (a
    # guide that routes none, an input missing before the source term) keeps the
    # channels' own lines. The range of plume paths is not drawn (ADDENDUM-01 item 3:
    # its end-member runs are the TEVV page's).
    cls = engine_class(c)
    one = one_engine(c)
    # HB-162R (DN-025 section 3 item 5): a passive release whose cloud the puff draws by
    # level shows it over time by those levels; HB-157's single-level arrival bands
    # and step outline are the same run at one level and are not drawn beside them
    by_level = not one and cloud_drawn(c) is not None
    puffs = (
        [] if one else [*([] if by_level else [_arrival_layer(c)]), *_puff_layers(c)]
    )
    if cls is None or (cls == "dense" and cloud_drawn(c) is not None):
        slab = [_dense_gas_layer(c)]
    else:
        slab = []
    layers = [
        _population_layer(c),
        _modelled_population_layer(c),
        _residential_layer(c),
        _workplace_layer(c),
        *puffs,
        *slab,
        *_cloud_layers(c),
        *_planning_layer(c),
        *([] if one or by_level else [_step_layer(c)]),
        fpl["protective_action_zone"],
        fpl["fire_isolation"],
        fpl["initial_isolation_zone"],
        fac["water"],
        _downstream_layer(c),
        fac["rail_lines"],
        *_cloud_extent_layer(c),
        *_uncertainty_layer(c),
        fpl["wind"],
        _flags_layer(c),
        fac["grade_crossings"],
        fac["schools"],
        fac["care"],
        fac["emergency_services"],
        _incidents_layer(c),
        _hospitals_layer(c),
        _nearby_layer(c),
        _routes_layer(c),
        _crossing_layer(c, "roads", "roadblock_candidates", "Roadblock candidates"),
        _crossing_layer(
            c,
            "modelled_cordons",
            "modelled_cordons",
            # HB-189 (DN-028 ADDENDUM-14 decision 9): candidate blocks under the
            # stable treatment, on the AEGL-2 planning area's boundary
            c.cfg["derive"]["modelled"]["cordon_title_stable"]
            if slab_levels(c)
            else "Roadblock candidates on the modelled boundary",
        ),
        _crossing_layer(c, "rail", "rail_candidates", "Rail crossings of the boundary"),
        *_location_layer(c),
        _sited_layer(c),
        fpl["spill"],
    ]
    # DN-028 ADDENDUM-10 decision 2: where SLAB carries the levels, SCICHEM's cloud is
    # still drawn, a layer marked unresolved, off on the first view (`map.slab_levels`)
    stable_off = set(c.map["slab_levels"]["layers_off"]) if slab_levels(c) else set()
    for lay in layers:
        lay["on"] = default_on(cfg, lay["id"]) and lay["id"] not in stable_off
        # DN-019 section 2 item 3: each footprint layer's fill is a pattern as well as
        # a colour, so a greyscale print or a colour-blind reader tells them apart
        if lay["features"] and lay["id"] in c.map["patterns"]:
            lay["style"]["pattern"] = pattern_id(lay["id"])
        # HB-152: a mapped marker class draws its SVG symbol and names it in a popup row
        _symbolize(lay)
        _reach_keys(c, lay)
        lay["legend"] = _legend(c, lay)
        # HB-161: the documentation moves to the layer's TEVV section; the map keeps its
        # name, key and measurement and the section's number
        _move_docs(c, lay)
    return {"layers": layers, "extent": view_extent(c)}


# ── HB-161: the map carries names and keys only ──────────────────────────────────────

_RECORD = re.compile(r"record ([0-9a-f]{6,})")


def _record_clause(text: str) -> str:
    """A label line's record, the key the popup keeps ("record <hash>"); the line whole
    where it names none (every label line names one: DN-010, HB-142R)."""
    found = _RECORD.findall(text)
    return f"record {found[-1]}" if found else text


def _strip_row(popup_html: str, head: str) -> tuple[str, list[str]]:
    """The popup's HTML without its rows headed `head`, and their values (unescaped)."""
    pat = re.compile(rf"<tr><th>{re.escape(esc(head))}</th><td>(.*?)</td></tr>", re.S)
    values = [html.unescape(v) for v in pat.findall(popup_html)]
    return pat.sub("", popup_html), values


def _move_docs(c: _Ctx, lay: dict) -> None:
    """HB-161 items 2 to 6 (operator, 2026-11-11 06:38 EST): a moved layer's legend
    becomes its key (`map.key_legend`), its popup rows of method, check, limit and
    provenance (`tevv.moved_rows`) leave the popup, and each label line shortens to the
    record it names. What left is kept, word for word, in `lay["doc"]` for the layer's
    TEVV section (`tevv.sections`); `render` drops `doc` from the map data. Every drawn
    layer carries its section's number (`lay["tevv"]`), which the map script prints on
    each popup. A layer outside `tevv.moved_layers` keeps its rows and label lines (its
    DN-010 provenance; HB-163 takes the rest of the first view) and gets the number
    and a copy of its labels as the section's inputs."""
    from hazbrief.brief import tevv

    t = c.cfg["tevv"]
    if not lay["features"]:
        return
    labels = [html.unescape(x) for x in lay["labels"]]
    doc: dict = {"labels": labels, "legend": [], "rows": [], "records": []}
    lay["doc"] = doc
    doc["legend"] += lay.pop("legend_more", None) or []
    lay["tevv"] = tevv.layer_ref(c.cfg, lay["id"])
    if lay["id"] not in t["moved_layers"]:
        return
    if lay.get("legend"):
        doc["legend"] = [x for x in lay["legend"].split("; ") if x]
    full = lay.pop("title_full", None)
    if full:
        doc["legend"].insert(0, full)
    lay["legend"] = _key_legend(c, lay)
    # the label lines go to the section whole, word for word; the popup keeps the
    # record each names, and the section's run record lists those records
    for text in labels:
        rec = _record_clause(text)
        if rec != text:
            doc["records"].append(rec)
    lay["labels"] = [esc(_record_clause(x)) for x in labels]
    seen: set[tuple[str, str]] = set()
    for f in lay["features"]:
        pop = f["properties"]["popup"]
        for head, field in t["moved_rows"].items():
            pop, values = _strip_row(pop, head)
            for v in values:
                if field == "cut" or (head, v) in seen:
                    continue
                seen.add((head, v))
                doc["rows"].append((head, v, field))
        f["properties"]["popup"] = pop
    doc["records"] = list(dict.fromkeys(doc["records"]))


def _key_legend(c: _Ctx, lay: dict) -> str | None:
    """A moved layer's legend as its key alone (HB-161 item 3): the threshold with its
    value, unit and time, the distance the reader acts on; None where the layer had no
    legend entry."""
    spec = c.map["key_legend"]
    lid = lay["id"]
    if lid in ("arrival_bands", "step_outline", "plume_range"):
        _, tl, _ = _timeline(c)
        return spec["timeline"].format(
            threshold=tl["level"]["threshold"],
            as_printed=tl["level"]["as_printed"],
            end=tl["steps"][-1]["hplus"],
        )
    if lid.startswith("puff_"):
        levels = []
        for f in lay["features"]:
            th = f["properties"].get("threshold")
            if th and th not in levels:
                levels.append(th)
        return spec["puff"].format(levels=", ".join(levels))
    if lid == "dense_gas":
        d = _derived(c, "dense_gas") or {}
        props = lay["features"][0]["properties"]
        reach = spec["dense_beyond" if props.get("beyond_table") else "dense_reach"]
        bands = [b for b in d.get("bands") or [] if b.get("geometry")]
        if not bands:
            lv = d["level"]
            return reach.format(x=props["downwind_m"]) + f"; {lv['words']}"
        return spec["dense"].format(
            reach=reach.format(x=props["downwind_m"]),
            bands=", ".join(spec["dense_band"].format(**b) for b in bands),
        )
    return lay.get("legend")


def pattern_id(lid: str) -> str:
    """The SVG `<pattern>` id a layer's fill refers to (`render.pattern_defs`)."""
    return f"hb-pat-{lid}"


def _legend(c: _Ctx, lay: dict) -> str | None:
    """A footprint layer's one legend entry (DN-019 section 2 items 1 and 2; HB-114 step
    4): what it is, the time it stands for and the action, in `map.legend`'s words. The
    ERG zones name the ERG's action (the zone's own note where the guide gives the
    distance, else Table 1's column headings) and the distance; the modelled layers
    name their levels of concern and averaging times as drawn, each its own (HB-114
    ADDENDUM-01 section 2), and a dense-gas reach past SLAB's table as "beyond", never
    as an extent. None for a layer that is not a footprint or is not drawn."""
    if not lay["features"]:
        return None
    spec = c.map["legend"]
    lid = lay["id"]
    if lid in ZONE_TITLES:
        return _erg_legend(c, lay, spec)
    if lid in ("arrival_bands", "step_outline", "plume_range"):
        # HB-157: the time layers name their level, where the run ended and the one
        # wind they were computed on
        _, tl, _ = _timeline(c)
        return spec["timeline"].format(
            what=lay["title"],
            level=tl["level_line"],
            end=tl["end_line"],
            wind=tl["one_wind"],
        )
    if lid.startswith("puff_"):
        return _puff_legend(c, lay, spec)
    if lid == "dense_gas":
        return _dense_legend(c, lay, spec)
    if lid == "wind":
        return _wind_legend(c)
    if lid == "residential_density":
        # HB-142R item 2: the legend names the vintage and the bands
        r = c.map["residential"]
        names = band_names(lay["style"]["breaks"])
        return r["legend"].format(n=len(names), bands="; ".join(names))
    if lay.get("key"):
        # HB-163: a cloud level's key, its threshold value, unit and averaging time
        return lay["key"]
    return None


def _wind_legend(c: _Ctx) -> str | None:
    """The wind arrow's legend entry (HB-139; DN-019 ADDENDUM-01 section 1): the
    record every layer reads, with its source in the addendum's form. None when no
    record was resolved (a brief built by a test harness)."""
    from hazbrief.brief import wind_record

    rec = getattr(c.brief, "wind_record", None)
    if not (getattr(c.brief, "wind_resolved", False) and rec):
        return None
    text = wind_record.label(rec, c.cfg, lambda iso: L.when(iso, c.tz))
    return c.cfg["wind_record"]["legend"].format(
        deg=float(rec["direction_deg_from"]), kmh=float(rec["speed_kmh"]), label=text
    )


def _erg_legend(c: _Ctx, lay: dict, spec: dict) -> str:
    fp = c.payload("protective_action_footprint")
    z = (fp.get("zones") or {}).get(lay["id"]) or {}
    period = (fp.get("day_night") or {}).get("period")
    if z.get("note"):
        # HB-161 item 9: the guide's action is the key; a further sentence of the
        # guide's note (which distance the circle is) is the zone's TEVV section's
        first, *more = re.split(r"(?<=[a-z\]])\. (?=[A-Z])", z["note"].rstrip("."))
        action = first
        if more:
            lay["legend_more"] = [m.rstrip(".") for m in more]
    elif lay["id"] == "protective_action_zone":
        action = spec["erg_protect"].format(period=str(period).upper())
    else:
        action = spec["erg_isolate"]
    distance = (z.get("distance") or {}).get("text") or "distance not held"
    if z.get("downwind_bearing_deg") is not None:
        distance += spec["erg_toward"].format(deg=z["downwind_bearing_deg"])
    return spec["erg"].format(
        what=lay["title"],
        distance=distance,
        action=action,
        tag=(z.get("tag") or "").strip("[]"),
        period=(fp.get("day_night") or {}).get("word") or "period not held",
        when=L.when(c.brief.as_given, c.tz) if c.brief.as_given else "now",
    )


def _puff_legend(c: _Ctx, lay: dict, spec: dict) -> str:
    p = _derived(c, "puff") or {}
    levels = []
    for f in lay["features"]:
        t = f["properties"].get("threshold")
        if t and t not in levels:
            levels.append(t)
    cmp_ = ((_derived(c, "dense_gas") or {}).get("comparison")) or {}
    beside = (
        spec["puff_beside"].format(at=cmp_["puff_at"]) if cmp_.get("puff_at") else ""
    )
    return spec["puff"].format(
        what=lay["title"],
        levels=", ".join(levels),
        beside=beside,
        window=c.cfg["weather"]["puff"]["window_min"],
        when=L.when(c.brief.as_given, c.tz) if c.brief.as_given else "now",
        wind_as_of=L.when(p["wind_as_of"], c.tz) if p.get("wind_as_of") else "unknown",
    )


def _beyond_key(c: _Ctx) -> str:
    """The sentence for a SLAB band still above its level where it is drawn to: under
    the stable treatment the time bound cuts it (DN-028 ADDENDUM-14 decision 5); by day
    its table's end does (`map.legend.dense_beyond_time` and `dense_beyond`)."""
    return "dense_beyond_time" if slab_levels(c) else "dense_beyond"


def _dense_legend(c: _Ctx, lay: dict, spec: dict) -> str:
    d = _derived(c, "dense_gas") or {}
    props = lay["features"][0]["properties"]
    cmp_ = d.get("comparison") or {}
    reach = spec[_beyond_key(c) if props.get("beyond_table") else "dense_reach"].format(
        x=props["downwind_m"], ratio=cmp_.get("dense_ratio", "not computed")
    )
    p = _derived(c, "puff") or {}
    bands = d.get("bands") or []
    if len(bands) > 1:
        clause = spec["dense_bands"].format(
            bands="; ".join(
                spec["dense_band"].format(**b)
                if b.get("geometry")
                else spec["dense_band_absent"].format(tier=b["tier"])
                for b in bands
            ),
            opacity=c.map["band_fill_opacity"],
        )
    else:
        clause = spec["dense_one_level"]
    return (
        spec["dense"].format(
            what=lay["title"],
            level=d["level"]["words"],
            reach=reach,
            wind_as_of=L.when(p["wind_as_of"], c.tz)
            if p.get("wind_as_of")
            else "unknown",
        )
        + clause
    )


def cue_lines(brief, cfg, data: dict | None = None) -> list[dict]:
    """The operator cue block's lines (HB-115 ADDENDUM-01 section 2): each a signal the
    brief's own state makes true, what holds when it does, and its receipt (a held
    page, or None where the line is the brief's own number). In `map.cue_block`'s
    order, at most `max_lines`; a line whose signal is false is not printed. `data` is
    `build`'s output where the caller already holds it (the dense-gas reach is read
    from the drawn layer, so the number is the legend's own)."""
    c = _Ctx(brief, cfg)
    spec = c.map["cue_block"]
    rows = spec["lines"]
    data = data if data is not None else build(brief, cfg)
    drawn = {lay["id"]: lay for lay in data["layers"] if lay["features"]}
    dense = _derived(c, "dense_gas") or {}
    stab = _derived(c, "stability") or {}
    fp = c.payload("protective_action_footprint") or {}
    modelled = any(k.startswith("puff_") for k in drawn) or "dense_gas" in drawn
    out: list[dict] = []

    def add(key: str, signal: str, text: str) -> None:
        row = rows[key]
        # a held page, or (the dense-gas reach) the brief's own drawn layer
        receipt = (
            spec["receipt"].format(doc=row["doc"], page=row["page"])
            if row.get("doc")
            else row["receipt_text"]
        )
        if row.get("tevv"):
            # HB-161 ADDENDUM-02 item 1: the document is cited on the TEVV page; the
            # checklist item and the cue line carry the section's number
            from hazbrief.brief import tevv

            receipt = f"{cfg['tevv']['link_text']} {tevv.ref(cfg, row['tevv'])}"
        out.append(
            {
                "key": key,
                "text": spec["line"].format(signal=signal, text=text),
                "receipt": receipt,
                # HB-161 ADDENDUM-02 item 1: the TEVV section that cites the document
                "tevv": row.get("tevv"),
            }
        )

    r = rows["night_stable"]
    if stab.get("period") == "night" and stab.get("class") in r["when_classes"]:
        add(
            "night_stable",
            r["signal"].format(cls=stab["class"]),
            r["text"].format(quote=r["quote"]),
        )
    fire = (fp.get("zones") or {}).get("fire_isolation")
    if fire and "fire_isolation" in drawn:
        r = rows["tank_fire"]
        add(
            "tank_fire",
            r["signal"].format(
                distance=(fire.get("distance") or {}).get("text") or "not held"
            ),
            r["text"].format(quote=r["quote"]),
        )
    if modelled:
        r = rows["erg_floor"]
        add("erg_floor", r["signal"], r["text"].format(quote=r["quote"]))
    jet_sentence = cfg["weather"]["dense_gas"]["evaluation"]["jet"]
    # DN-028 ADDENDUM-10 decision 1: under a stable class SLAB carries the levels, so it
    # is not "the second method" there (`signal_slab_levels`)
    which = "signal_slab_levels" if slab_levels(c) else "signal"
    if "dense_gas" in drawn and jet_sentence in (dense.get("label") or ""):
        r = rows["jet"]
        add("jet", r[which], r["text"].format(sentence=jet_sentence))
    if modelled:
        r = rows["indoor"]
        add("indoor", r["signal"], r["text"].format(quote=r["quote"]))
    if "dense_gas" in drawn:
        props = drawn["dense_gas"]["features"][0]["properties"]
        if props.get("beyond_table"):
            r = rows["lower_bound"]
            reach = c.map["legend"][_beyond_key(c)].format(
                x=props["downwind_m"],
                ratio=(dense.get("comparison") or {}).get(
                    "dense_ratio", "not computed"
                ),
            )
            add("lower_bound", r[which], r["text"].format(reach=reach))
    return out[: spec["max_lines"]]


def empty_disposition(cfg, lid: str, reason: str) -> dict:
    """HB-158 item 4: what the layer list does with layer `lid`, which has nothing to
    draw for `reason` (`map.empty_rows`, first match wins): `as` none (a muted row in
    the `none` group), gap (under "N layers could not be drawn", and a Data gaps item)
    or unlisted (not on the brief); `say`, its one line; `rule`, the index of the rule
    that matched, or None when none did (a gap with `map.gap_default`)."""
    m = cfg["map"]
    why = reason or ""
    for i, r in enumerate(m["empty_rows"]):
        if "layer" in r and r["layer"] != lid:
            continue
        if "starts" in r and not why.startswith(r["starts"]):
            continue
        if "contains" in r and r["contains"] not in why:
            continue
        return {"as": r["as"], "say": r.get("say", ""), "rule": i}
    return {"as": "gap", "say": m["gap_default"], "rule": None}


def row_name(cfg, lid: str) -> str:
    """A layer row's short name (HB-158 item 3; `map.rows.layers`). A layer with no
    line there is refused, as `default_on` refuses one with no default."""
    spec = cfg["map"]["rows"]["layers"]
    if lid not in spec:
        raise KeyError(f"map.rows.layers in orchestrator.yaml has no line for {lid!r}")
    return spec[lid]["name"]


def _imperial(text: str) -> str:
    """The US-unit part of an ERG distance as the guide prints it, "1,000 m (3,000
    ft)" giving "3,000 ft"; the text whole when it holds no such part."""
    m = re.search(r"\(([\d.,]+ (?:ft|mi))\)", text or "")
    return m.group(1) if m else (text or "")


def row_figure(brief, cfg, lay: dict, n: int) -> str:
    """The one figure a layer row prints (HB-158 item 3; `map.rows`): a count with its
    unit, or a figure read from the layer's own held text (the ERG distance, the
    legend's farthest reach, the modelled time, the wind). No figure is computed
    here: each is a value the layer's label or the footprint already prints."""
    rows = cfg["map"]["rows"]
    spec = rows["layers"].get(lay["id"]) or {}
    # HB-184: a layer may carry its own short figure (the stable-class level rows)
    if lay.get("figure"):
        return lay["figure"]
    kind = spec.get("figure", "count")
    legend = lay.get("legend") or ""
    if kind == "none":
        return ""
    if kind == "legend":
        # HB-163: the layer's key as its figure (a cloud level's threshold and time)
        return legend
    if kind == "zone":
        fp = (brief.channels.get("protective_action_footprint") or {}).get(
            "payload"
        ) or {}
        z = (fp.get("zones") or {}).get(lay["id"]) or {}
        text = (z.get("distance") or {}).get("text")
        if text:
            return f"{_imperial(text)} {rows['zone_words'][lay['id']]}"
        return ""
    if kind == "farthest":
        m = re.search(r"farthest downwind ([\d,.]+ k?m)", legend)
        return f"to {m.group(1)}" if m else f"{n} {spec.get('unit', 'bands')}"
    if kind == "steps":
        # HB-161: the key legend says "steps to H+..."
        m = re.search(r"(?:Modelled to|steps to) (H\+\d+(?: h| min)?)", legend)
        return f"to {m.group(1)}" if m else ""
    if kind == "wind":
        m = re.search(r"from (\d+) degrees at ([\d.]+) km/h", legend)
        return f"from {m.group(1)}°, {m.group(2)} km/h" if m else ""
    return f"{n} {spec.get('unit', '')}".strip()


def default_on(cfg, lid: str) -> bool:
    """Whether layer `lid` is on before any click: its line in `map.defaults` (DN-019
    section 3; HB-114 step 3). A layer with no line there is refused, so a new layer
    cannot ship on or off by accident."""
    table = cfg["map"]["defaults"]
    if lid not in table:
        raise KeyError(
            f"map.defaults in orchestrator.yaml has no line for layer {lid!r}"
        )
    word = table[lid]
    if word not in ("on", "off"):
        raise ValueError(f'map.defaults.{lid} is {word!r}; it must be "on" or "off"')
    return word == "on"


def view_extent(c: _Ctx) -> list[list[float]] | None:
    """The map's first view (HB-155 ADDENDUM-02 item 6; HBD-366): `extent`, widened to
    hold the nearest facility of each class of the services in the area, so at least
    one of each class is on screen at first paint and a small zoom-out never empties
    the map. Only the view: the crop box and the snapshot request keep `extent`, which
    does not depend on the derivations (a recorded snapshot is keyed by its box)."""
    ext = extent(c)
    if ext is None:
        return None
    (s, w), (n, e) = ext
    near = _derived(c, "nearby") or {}
    for rows in (near.get("classes") or {}).values():
        if rows:
            lon, lat = rows[0]["coordinates"]
            w, e = min(w, lon), max(e, lon)
            s, n = min(s, lat), max(n, lat)
    return [[round(s, 6), round(w, 6)], [round(n, 6), round(e, 6)]]


def extent(c: _Ctx) -> list[list[float]] | None:
    """The footprint's bounds (every zone polygon: the protective action zone and the
    isolation circle around the spill, which sits on the zone's upwind edge), widened to
    `min_extent_m` across around their centre, as [[south, west], [north, east]]."""
    fp = c.payload("protective_action_footprint")
    if fp is None:
        return None
    feats = fp["footprint"]["features"]
    polys = [
        shape(f["geometry"])
        for f in feats
        if f["geometry"]["type"] in ("Polygon", "MultiPolygon")
    ]
    if polys:
        w = min(p.bounds[0] for p in polys)
        s = min(p.bounds[1] for p in polys)
        e = max(p.bounds[2] for p in polys)
        n = max(p.bounds[3] for p in polys)
    else:
        lon, lat = next(
            f["geometry"]["coordinates"]
            for f in feats
            if f["properties"].get("zone") == "spill"
        )
        w, s, e, n = lon, lat, lon, lat
    lat0 = (s + n) / 2
    half_lat = c.map["min_extent_m"] / 2 / _M_PER_DEG
    half_lon = half_lat / math.cos(math.radians(lat0))
    cx, cy = (w + e) / 2, (s + n) / 2
    w, e = min(w, cx - half_lon), max(e, cx + half_lon)
    s, n = min(s, cy - half_lat), max(n, cy + half_lat)
    return [[round(s, 6), round(w, 6)], [round(n, 6), round(e, 6)]]


# ── the first actions ─────────────────────────────────────────────────────────────────


def first_actions(brief, cfg) -> dict:
    """{"distances": [(heading, text, note, tag)], "distances_label",
    "distances_missing",
    "guide": {number, title}, "lines": [(kind, text, page)], "guide_label",
    "guide_missing"}: the footprint's distances and the orange guide's public-safety
    lines, as the tools returned them."""
    c = _Ctx(brief, cfg)
    out: dict[str, Any] = {"distances": [], "lines": []}
    fp = c.payload("protective_action_footprint")
    if fp is None:
        out["distances_missing"] = c.why_not("protective_action_footprint")
    else:
        zones = fp.get("zones") or {}
        # structural headings only; what to do is the tool's own `note` and the
        # guide's lines below, never wording typed here
        heads = {
            "initial_isolation_zone": "Initial isolation",
            "fire_isolation": "Fire isolation",
            "protective_action_zone": "Protective action",
            "large_spill_downwind": "Large spill, downwind",
        }
        for key, head in heads.items():
            z = zones.get(key)
            if not z:
                continue
            text = (z.get("distance") or {}).get("text")
            if key == "protective_action_zone" and z.get("shape"):
                text = f"{text}, {z['shape']}"
            out["distances"].append((head, text, z.get("note"), z.get("tag")))
        out["distances_label"] = c.label("protective_action_footprint")
        if not out["distances"]:
            out["distances_missing"] = (
                "the footprint holds no distance for this incident"
            )
    g = c.payload("material_response_guidance")
    if g is None:
        out["guide_missing"] = c.why_not("material_response_guidance")
    else:
        out["guide"] = g.get("guide") or {}
        out["lines"] = [
            (it.get("kind"), it.get("text"), it.get("page"))
            for it in g.get("public_safety") or []
        ]
        out["guide_label"] = c.label("material_response_guidance")
        if not out["lines"]:
            out["guide_missing"] = (
                "the guide holds no public safety line for this material"
            )
    return out
