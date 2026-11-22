"""The Block 4 sketch (HB-11b step 5): the form's GeoJSON drawn as an SVG over a
TIGERweb map image of the roads and railroads.

The ICS 201 instructions ask Block 4 for a sketch; the `geojson` output is the data,
this is the picture. Drawn: the spill, the initial isolation zone, the protective
action zone (or the guide's fire isolation circle), the wind arrow with its speed, the
facilities inside the footprint and the receiving hospitals inside the frame as
labelled points, the spill's county outline, a scale bar and a north arrow. Nothing
here computes a zone: every shape is a feature the footprint tool already drew.

Data source: TIGERweb `Transportation/MapServer`, its `export` operation (one call per
incident, through `utils.fetch_bytes`, so it records and replays like every other
exchange; ics201.yaml `map`). The service states no vintage, so the as-of is the
day the image was retrieved. The frame is the footprint, its facilities and the
nearest receiving hospital, padded and widened to the image's aspect ratio, in Web
Mercator (EPSG:3857), in which the export is asked for and the overlay is drawn, so the
two register and a circle draws round.

Determinism: the SVG is a function of its inputs and the recorded image's bytes. Every
coordinate is written at one decimal of a pixel, so a replayed scenario renders the
same bytes (the frozen sketches in fixtures/ics201/ hold it).

No PNG is rendered: cairosvg needs the system cairo library, which neither a plain
`uv sync` nor the container provides (HB-11b RESULT). Every Markdown renderer the brief
is read in displays SVG.
"""

from __future__ import annotations

import base64
import hashlib
import html
import math
from collections.abc import Callable

from hazbrief import ics201
from hazbrief.utils import UpstreamServiceError, fetch_bytes

#: EPSG:3857 is the spherical Mercator on the WGS84 semi-major axis.
EARTH_RADIUS_M = 6378137.0
#: Point features drawn as labelled facilities, by the GeoJSON layer `_map` gives them.
#: A grade crossing is drawn unlabelled: its name is an inventory number, which the
#: Block 5 sentences print.
FACILITY_LAYERS = (
    "school",
    "nursing_home",
    "emergency_service",
    "hospital_in_footprint",
)
CROSSING_LAYER = "grade_crossing"
#: Zone polygons, drawn largest first so the initial isolation zone lies on top.
ZONE_ORDER = ("protective_action_zone", "fire_isolation", "initial_isolation_zone")
ZONE_LABELS = {
    # HB-18 (A-4): the ERG's own square, the only downwind shape the sketch draws
    "protective_action_zone": "Protective action zone (ERG square)",
    "fire_isolation": "Fire isolation (guide)",
    "initial_isolation_zone": "Initial isolation zone",
}


def config() -> dict:
    return ics201.config()["map"]


def mercator(lon: float, lat: float) -> tuple[float, float]:
    """(x, y) in EPSG:3857 metres."""
    x = EARTH_RADIUS_M * math.radians(lon)
    y = EARTH_RADIUS_M * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
    return x, y


def frame(points: list[tuple[float, float]], cfg: dict) -> dict:
    """The sketch's frame around (lon, lat) points: padded by `pad_fraction` of its
    larger side, its height in pixels from its shape within the configured bounds, then
    widened in one direction so its aspect ratio is the image's exactly (an ArcGIS
    export otherwise widens the extent itself, and the overlay would not register)."""
    xs, ys = zip(*(mercator(lon, lat) for lon, lat in points), strict=True)
    dx, dy = max(xs) - min(xs), max(ys) - min(ys)
    pad = cfg["pad_fraction"] * max(dx, dy, 1000.0)
    x0, x1, y0, y1 = min(xs) - pad, max(xs) + pad, min(ys) - pad, max(ys) + pad
    width = int(cfg["width_px"])
    height = round(width * (y1 - y0) / (x1 - x0))
    height = max(int(cfg["min_height_px"]), min(int(cfg["max_height_px"]), height))
    ratio = width / height
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    w, h = x1 - x0, y1 - y0
    if w / h < ratio:
        w = h * ratio
    else:
        h = w / ratio
    return {
        "xmin": round(cx - w / 2, 2),
        "ymin": round(cy - h / 2, 2),
        "xmax": round(cx + w / 2, 2),
        "ymax": round(cy + h / 2, 2),
        "width": width,
        "height": height,
        "srid": 3857,
    }


def scale_length(target_m: float) -> int:
    """The largest of 1, 2 or 5 times a power of ten metres not above `target_m`."""
    p = 10 ** math.floor(math.log10(target_m))
    return int(max(m * p for m in (1, 2, 5) if m * p <= target_m))


async def basemap(fr: dict, cfg: dict) -> tuple[dict, bytes | None]:
    """The TIGERweb export of the frame, and its record (url, vintage, layers, frame,
    tag, size and sha256 of the image; `error` instead when the call failed)."""
    layers = {int(k): v for k, v in cfg["layers"].items()}
    record = {
        "service": f"TIGERweb/{cfg['service']}",
        "description": cfg["description"],
        "layers": [layers[k] for k in sorted(layers)],
        "frame": fr,
    }
    try:
        ex = await fetch_bytes(
            "tigerweb",
            f"{cfg['service']}/export",
            params={
                "bbox": f"{fr['xmin']:.2f},{fr['ymin']:.2f},{fr['xmax']:.2f},"
                f"{fr['ymax']:.2f}",
                "bboxSR": "3857",
                "imageSR": "3857",
                "size": f"{fr['width']},{fr['height']}",
                "dpi": str(cfg["dpi"]),
                "format": cfg["image_format"],
                "transparent": "false",
                "layers": "show:" + ",".join(str(k) for k in sorted(layers)),
                "f": "image",
            },
        )
    except UpstreamServiceError as exc:
        return record | {"error": str(exc)}, None
    # the service states no vintage: its as-of is the day the image was retrieved
    day = ex.recorded_at[:10]
    return (
        record
        | {
            "url": ex.url,
            "retrieved": day,
            "tag": ics201.mdy(f"[TIGERweb Transportation, as of {day}]"),
            "content_type": ex.content_type,
            "bytes": len(ex.body),
            "sha256": hashlib.sha256(ex.body).hexdigest(),
        },
        ex.body,
    )


# ── SVG ──────────────────────────────────────────────────────────────────────


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


class _Canvas:
    """EPSG:3857 metres to SVG pixels for one frame."""

    def __init__(self, fr: dict):
        self.fr = fr
        self.sx = fr["width"] / (fr["xmax"] - fr["xmin"])
        self.sy = fr["height"] / (fr["ymax"] - fr["ymin"])

    def px(self, lon: float, lat: float) -> tuple[float, float]:
        x, y = mercator(lon, lat)
        return (x - self.fr["xmin"]) * self.sx, (self.fr["ymax"] - y) * self.sy

    def inside(self, lon: float, lat: float) -> bool:
        x, y = self.px(lon, lat)
        return 0 <= x <= self.fr["width"] and 0 <= y <= self.fr["height"]

    def path(self, rings: list) -> str:
        parts = []
        for ring in rings:
            pts = [self.px(lon, lat) for lon, lat in ring]
            parts.append("M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + " Z")
        return " ".join(parts)


def _rings(geometry: dict) -> list:
    if geometry["type"] == "Polygon":
        return geometry["coordinates"]
    if geometry["type"] == "MultiPolygon":
        return [ring for poly in geometry["coordinates"] for ring in poly]
    return []


Box = tuple[float, float, float, float]


def _overlaps(a: Box, b: Box) -> bool:
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


class _Labels:
    """Greedy, deterministic label placement: right, left, above, below the point, then
    the four diagonals; a label that overlaps something placed in all eight is left out
    (its point stays). `boxes` holds what no label may cover."""

    def __init__(self, size: int, width: int, height: int):
        self.size, self.w, self.h = size, width, height
        self.boxes: list[Box] = []

    def place(self, x: float, y: float, text: str) -> tuple[float, float, str] | None:
        tw, th = 0.58 * self.size * len(text), 1.2 * self.size
        for ax, ay, anchor in (
            (x + 8, y + 4, "start"),
            (x - 8, y + 4, "end"),
            (x, y - 10, "middle"),
            (x, y + 18, "middle"),
            (x + 6, y - 8, "start"),
            (x + 6, y + 16, "start"),
            (x - 6, y - 8, "end"),
            (x - 6, y + 16, "end"),
        ):
            left = {"start": ax, "end": ax - tw, "middle": ax - tw / 2}[anchor]
            box = (left, ay - th + 3, left + tw, ay + 3)
            if box[0] < 0 or box[2] > self.w or box[1] < 0 or box[3] > self.h:
                continue
            if any(_overlaps(box, b) for b in self.boxes):
                continue
            self.boxes.append(box)
            return ax, ay, anchor
        return None


def _text(
    x: float, y: float, text: str, st: dict, anchor: str = "start", size: str = ""
) -> str:
    """Text with a halo, so a label reads over the basemap."""
    font = f' font-size="{size}"' if size else ""
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}"{font} '
        f'fill="{st["fill"]}" stroke="{st["halo"]}" stroke-width="3" '
        f'paint-order="stroke">{_esc(text)}</text>'
    )


def render_svg(
    geojson: dict,
    fr: dict,
    png: bytes | None,
    outline: dict | None,
    cfg: dict,
    label: Callable[[str], str],
    attribution: str = "",
    county: str = "",
    notes: tuple[str, ...] = (),
) -> str:
    """The sketch as SVG text. `png` is the basemap image (None: no basemap, and the
    sketch says so); `outline` the county's GeoJSON geometry and `county` its name as
    the legend prints it; `label` writes a facility or hospital name as printed;
    `notes` are legend lines with no symbol (HB-18: what is not drawn, and why).

    HB-18: for an unresolved load the footprint holds every candidate's polygons, each
    marked `governing` or not. The governing candidate's zones are drawn as any
    footprint's; every other candidate's polygon is a dashed outline (style
    `candidate`), so the union is visible and the printed distances' shapes stand
    out."""
    st = cfg["style"]
    W, H = fr["width"], fr["height"]
    c = _Canvas(fr)
    txt = st["text"]
    labels = _Labels(int(txt["size"]), W, H)
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" font-family="Helvetica, Arial, sans-serif" '
        f'font-size="{txt["size"]}">',
        "<title>ICS 201 Block 4 sketch</title>",
        f'<rect width="{W}" height="{H}" fill="#ffffff"/>',
    ]
    if png is not None:
        data = base64.b64encode(png).decode("ascii")
        out.append(
            f'<image id="basemap" x="0" y="0" width="{W}" height="{H}" '
            f'preserveAspectRatio="none" href="data:image/png;base64,{data}"/>'
        )
    else:
        out.append(_text(12, H - 40, "Basemap not available", txt))
    if outline:
        out.append(
            f'<path id="county" d="{c.path(_rings(outline))}" fill="none" '
            f'stroke="{st["county"]["stroke"]}" stroke-width="1.5" '
            f'stroke-dasharray="{st["county"]["dash"]}"/>'
        )
    feats = geojson["features"]
    # the footprint's polygons only: a facility point carries its zone too, and since
    # HB-15 (F-5b) that can be a guide circle's name ("fire_isolation")
    zones = {
        f["properties"]["zone"]: f
        for f in feats
        if f["properties"].get("zone") in ZONE_ORDER
        and "layer" not in f["properties"]
        and f["properties"].get("governing", True)
    }
    others = [
        f
        for f in feats
        if f["properties"].get("governing") is False
        and f["geometry"]["type"] == "Polygon"
    ]
    for z in ZONE_ORDER:
        if z in zones:
            s = st[z]
            out.append(
                f'<path id="{z}" d="{c.path(_rings(zones[z]["geometry"]))}" '
                f'fill="{s["fill"]}" fill-opacity="{s["fill_opacity"]}" '
                f'stroke="{s["stroke"]}" stroke-width="2"/>'
            )
    cs = st["candidate"]
    for f in others:
        out.append(
            f'<path class="candidate" d="{c.path(_rings(f["geometry"]))}" fill="none" '
            f'stroke="{cs["stroke"]}" stroke-width="2" '
            f'stroke-dasharray="{cs["dash"]}"/>'
        )
    spill = next(f for f in feats if f["properties"].get("zone") == "spill")
    sx, sy = c.px(*spill["geometry"]["coordinates"])
    # Everything a label must not cover is known before any label is placed: the spill,
    # the wind arrow, every marker, then the legend, scale bar, north arrow and credit.
    content: list[Box] = [(sx - 8, sy - 8, sx + 8, sy + 8)]
    wind = next((f for f in feats if f["properties"].get("layer") == "wind"), None)
    if wind:
        (ulon, ulat), (slon, slat) = wind["geometry"]["coordinates"]
        x0, y0 = c.px(ulon, ulat)
        x1, y1 = c.px(slon, slat)
        content.append(
            (min(x0, x1) - 4, min(y0, y1) - 4, max(x0, x1) + 4, max(y0, y1) + 4)
        )
    points = []
    for f in feats:
        layer = f["properties"].get("layer")
        if layer not in FACILITY_LAYERS + ("receiving_hospital", CROSSING_LAYER):
            continue
        lon, lat = f["geometry"]["coordinates"]
        if not c.inside(lon, lat):
            continue
        x, y = c.px(lon, lat)
        points.append((layer, x, y, f["properties"]))
        content.append((x - 7, y - 7, x + 7, y + 7))
    zone_boxes = []
    for z in zones.values():
        xs, ys = zip(
            *(c.px(lon, lat) for ring in _rings(z["geometry"]) for lon, lat in ring),
            strict=True,
        )
        zone_boxes.append((min(xs), min(ys), max(xs), max(ys)))
    # the legend lists what this sketch draws, in drawing order
    drawn = [(st[z], ZONE_LABELS[z]) for z in reversed(ZONE_ORDER) if z in zones]
    if others:
        drawn.append((cs, "Other candidate (dashed)"))
    drawn += [(None, n) for n in notes]
    layers = {layer for layer, *_ in points}
    if layers & set(FACILITY_LAYERS):
        drawn.append((st["facility"], "Facility inside the footprint"))
    if CROSSING_LAYER in layers:
        drawn.append((st["crossing"], "Grade crossing"))
    if "receiving_hospital" in layers:
        drawn.append((st["hospital"], "Receiving hospital"))
    # the wind's speed is always printed: in the legend, and by the arrow where it fits
    wind_words = f"Wind {wind['properties']['text']}" if wind else ""
    furniture, reserved = _furniture(
        fr,
        c,
        cfg,
        attribution,
        county if outline else "",
        content + zone_boxes,
        drawn,
        wind_words,
    )
    labels.boxes = content + reserved
    if wind:
        col = st["wind"]["stroke"]
        ang = math.atan2(y1 - y0, x1 - x0)
        head = [
            (x1 - 14 * math.cos(ang - a), y1 - 14 * math.sin(ang - a))
            for a in (0.4, -0.4)
        ]
        out.append(
            f'<g id="wind"><line x1="{x0:.1f}" y1="{y0:.1f}" x2="{x1:.1f}" '
            f'y2="{y1:.1f}" stroke="{col}" stroke-width="3"/>'
            f'<path d="M{x1:.1f},{y1:.1f} L{head[0][0]:.1f},{head[0][1]:.1f} '
            f'L{head[1][0]:.1f},{head[1][1]:.1f} Z" fill="{col}"/></g>'
        )
        spot = labels.place(x0, y0, wind_words)
        if spot:
            out.append(_text(spot[0], spot[1], wind_words, txt, spot[2]))
    out.append(
        f'<g id="spill"><circle cx="{sx:.1f}" cy="{sy:.1f}" r="6" '
        f'fill="{st["spill"]["fill"]}" stroke="#ffffff" stroke-width="2"/></g>'
    )
    for layer, x, y, p in points:
        if layer == "receiving_hospital":
            col = st["hospital"]["fill"]
            out.append(
                f'<g class="receiving_hospital"><rect x="{x - 7:.1f}" '
                f'y="{y - 7:.1f}" width="14" height="14" fill="{col}" '
                f'stroke="#ffffff" stroke-width="1.5"/><path d="M{x:.1f},{y - 4:.1f} '
                f'V{y + 4:.1f} M{x - 4:.1f},{y:.1f} H{x + 4:.1f}" stroke="#ffffff" '
                f'stroke-width="2"/></g>'
            )
        elif layer == CROSSING_LAYER:
            out.append(
                f'<path class="{layer}" d="M{x:.1f},{y - 5:.1f} L{x + 5:.1f},{y:.1f} '
                f'L{x:.1f},{y + 5:.1f} L{x - 5:.1f},{y:.1f} Z" '
                f'fill="{st["crossing"]["fill"]}" stroke="#ffffff" stroke-width="1"/>'
            )
        else:
            col = st["facility"]["fill"]
            out.append(
                f'<rect class="{layer}" x="{x - 4:.1f}" y="{y - 4:.1f}" width="8" '
                f'height="8" fill="{col}" stroke="#ffffff" stroke-width="1"/>'
            )
    for layer, x, y, p in points:
        if layer == CROSSING_LAYER:
            continue
        text = (
            f"{label(p['name'])} ({p['distance_km']:g} km)"
            if layer == "receiving_hospital"
            else label(str(p["name"]))
        )
        spot = labels.place(x, y, text)
        if spot:
            out.append(_text(spot[0], spot[1], text, txt, spot[2]))
    out += furniture
    out.append("</svg>")
    return "\n".join(out) + "\n"


def _furniture(
    fr: dict,
    c: _Canvas,
    cfg: dict,
    attribution: str,
    county: str,
    content: list,
    rows: list[tuple[dict, str]],
    wind: str,
) -> tuple[list[str], list[Box]]:
    """Scale bar, north arrow, legend (`rows`, the spill, the wind and the county
    line) and credit line, and the boxes they cover. The legend takes the first of
    three corners (top left, bottom left, top right) that covers the least of `content`
    (markers, the wind arrow, the zones)."""
    st = cfg["style"]
    W, H = fr["width"], fr["height"]
    txt = st["text"]
    size = int(txt["size"])
    # ground metres per pixel at the frame's centre (Mercator scale is sec(latitude))
    ymid = (fr["ymin"] + fr["ymax"]) / 2
    lat = math.degrees(2 * math.atan(math.exp(ymid / EARTH_RADIUS_M)) - math.pi / 2)
    mpp = math.cos(math.radians(lat)) / c.sx
    length = scale_length(W * cfg["scale_bar_fraction"] * mpp)
    bar = length / mpp
    x0, y0 = W - 24 - bar, H - 28
    words = f"{length // 1000:g} km" if length >= 1000 else f"{length} m"
    out = [
        f'<g id="scale_bar"><rect x="{x0 - 8:.1f}" y="{y0 - 22:.1f}" '
        f'width="{bar + 16:.1f}" height="34" fill="#ffffff" fill-opacity="0.8"/>'
        f'<path d="M{x0:.1f},{y0 - 6:.1f} V{y0:.1f} H{x0 + bar:.1f} V{y0 - 6:.1f}" '
        f'fill="none" stroke="#111111" stroke-width="2"/>'
        + _text(x0 + bar / 2, y0 - 10, words, txt, "middle")
        + "</g>",
        f'<g id="north_arrow"><path d="M{W - 30},20 L{W - 40},48 L{W - 30},42 '
        f'L{W - 20},48 Z" fill="#111111"/>'
        + _text(W - 30, 64, "N", txt, "middle")
        + "</g>",
    ]
    reserved: list[Box] = [
        (x0 - 8, y0 - 22, x0 + bar + 8, y0 + 12),
        (W - 44, 16, W - 16, 68),
    ]
    # every legend line's words (HB-18: the row labels grew, and a note has no swatch)
    longest = max(
        len(f"Boundary of {county}"),
        len(wind),
        *(len(n) + (0 if s is None else 4) for s, n in rows),
    )
    lw = max(236, 60 + int(0.58 * size * longest))
    lh = 22 * len(rows) + 30 + (22 if county else 0) + (22 if wind else 0)
    corners = [(10, 10), (10, H - lh - 26), (W - lw - 56, 10)]
    lx, ly = min(
        corners,
        key=lambda xy: (
            sum(_overlaps((xy[0], xy[1], xy[0] + lw, xy[1] + lh), b) for b in content),
            corners.index(xy),
        ),
    )
    reserved.append((lx, ly, lx + lw, ly + lh))
    lg = [
        f'<g id="legend" transform="translate({lx},{ly})"><rect x="0" y="0" '
        f'width="{lw}" height="{lh}" fill="#ffffff" fill-opacity="0.85" '
        f'stroke="#999999"/>'
    ]
    for i, (s, name) in enumerate(rows):
        y = 14 + 22 * i
        if s is None:  # a note: words only
            lg.append(f'<text x="10" y="{y + 12}">{_esc(name)}</text>')
            continue
        if "dash" in s:  # an outline
            lg.append(
                f'<rect x="10" y="{y}" width="14" height="14" fill="none" '
                f'stroke="{s["stroke"]}" stroke-width="2" '
                f'stroke-dasharray="{s["dash"]}"/>'
                f'<text x="32" y="{y + 12}">{_esc(name)}</text>'
            )
            continue
        op = s.get("fill_opacity", 1)
        lg.append(
            f'<rect x="10" y="{y}" width="14" height="14" fill="{s["fill"]}" '
            f'fill-opacity="{op}" stroke="{s.get("stroke", "#ffffff")}"/>'
            f'<text x="32" y="{y + 12}">{_esc(name)}</text>'
        )
    y = 14 + 22 * len(rows)
    lg.append(
        f'<circle cx="17" cy="{y + 7}" r="5" fill="{st["spill"]["fill"]}"/>'
        f'<text x="32" y="{y + 12}">Spill</text>'
    )
    if wind:
        y += 22
        col = st["wind"]["stroke"]
        lg.append(
            f'<path d="M6,{y + 7} H22" stroke="{col}" stroke-width="3"/>'
            f'<path d="M28,{y + 7} L20,{y + 2} L20,{y + 12} Z" fill="{col}"/>'
            f'<text x="32" y="{y + 12}">{_esc(wind)}</text>'
        )
    if county:
        y += 22
        lg.append(
            f'<path d="M8,{y + 7} H26" stroke="{st["county"]["stroke"]}" '
            f'stroke-width="1.5" stroke-dasharray="{st["county"]["dash"]}"/>'
            f'<text x="32" y="{y + 12}">{_esc(f"Boundary of {county}")}</text>'
        )
    lg.append("</g>")
    out += lg
    if attribution:
        out.append(_text(10, H - 8, attribution, txt, size="11"))
        reserved.append((8, H - 20, 10 + 0.58 * 11 * len(attribution), H))
    return out, reserved
