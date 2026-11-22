"""HB-136R: the incident hotspot map, built from the held FRA Form 54 extract.

uv run python scripts/build_incident_map.py           # write every output uv run python
scripts/build_incident_map.py --check   # rebuild in memory, compare, exit 1 on a
difference

Reads `scripts/incident_map.yaml` and the held file it names (corpus/raw/, gitignored;
the sha256 is checked first). Writes:

- the released incidents of the period as committed GeoJSON points, each with its
  provenance (the FRA report keys, the manifest row, the file's sha256, the location
  method);
- Getis-Ord Gi* on an equal-area hexagonal grid: every cell's count, z, normal and
  permutation p-values and false-discovery-rate adjustment (TSV), and the hot cells at
  99 and 95 percent as GeoJSON polygons;
- a Gaussian kernel density grid (JSON) with its bandwidth;
- the counts per year beside HB-127's PHMSA rail rows (TSV), which do not reconcile, and
  why;
- the Mid-Atlantic deck figure and a national figure (SVG), drawn here: points by
  severity over the hot cells.

The method is `incident_hotspots.py`. No network, no model call: `calls_made` in the
summary is 0 by construction. Deterministic: the permutations are seeded, so `--check`
compares byte for byte.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import incident_hotspots as H  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "scripts" / "incident_map.yaml"


class HeldDataError(RuntimeError):
    """The held file is missing or is not the bytes HB-135 recorded."""


def load_config() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _num(v: str) -> float:
    return float(v) if v not in ("", None) else 0.0


# ---- Part A: the points


def read_incidents(cfg: dict, path: Path) -> list[dict]:
    """Every Form 54 incident of the period, one per `incidentkey`, with its reports."""
    first, last = cfg["period"]["first"], cfg["period"]["last"]
    by = defaultdict(list)
    with path.open(newline="", encoding="utf-8") as fh:
        for line, row in enumerate(csv.DictReader(fh), start=2):
            day = row["date"][:10]
            if first <= day <= last:
                row["_line"] = line
                by[row["incidentkey"]].append(row)
    return [{"key": k, "reports": rs} for k, rs in sorted(by.items())]


def _locate(rows: list[dict]) -> tuple[float, float] | None:
    for r in rows:
        lat, lon = _num(r["latitude"]), _num(r["longitude"])
        if lat != 0 and lon != 0:
            return lon, lat
    return None


def severity_of(cfg: dict, values: dict) -> dict:
    for s in cfg["severity"]:
        if s["field"] is None or values[s["field"]] > 0:
            return s
    raise AssertionError("the last severity class has no field and always applies")


def released_points(
    cfg: dict, incidents: list[dict], sha: str
) -> tuple[list[dict], list[dict]]:
    """(points, misses): each released incident located at the coordinates of the report
    that released (Form 54 Blocks 50 and 51); an incident with none is a miss."""
    field = cfg["release_field"]
    ds = cfg["dataset"]
    pts, misses = [], []
    for inc in incidents:
        rel = [r for r in inc["reports"] if _num(r[field]) > 0]
        if not rel:
            continue
        rel.sort(key=lambda r: (r["jointcd"], r["reportkey"]))
        where = _locate(rel) or _locate(inc["reports"])
        values = {
            "totalpersonskilled": max(
                _num(r["totalpersonskilled"]) for r in inc["reports"]
            ),
            "totalpersonsinjured": max(
                _num(r["totalpersonsinjured"]) for r in inc["reports"]
            ),
            "personsevacuated": max(
                _num(r["personsevacuated"]) for r in inc["reports"]
            ),
        }
        sev = severity_of(cfg, values)
        r0 = rel[0]
        props = {
            "incident_key": inc["key"],
            "report_keys": sorted(r["reportkey"] for r in inc["reports"]),
            "released_report_key": r0["reportkey"],
            "csv_lines": sorted(r["_line"] for r in inc["reports"]),
            "date": r0["date"][:10],
            "year": int(r0["date"][:4]),
            "mode": ds["mode"],
            "railroad": r0["reportingrailroadname"],
            "accident_type": r0["accidenttype"],
            "state": r0["stateabbr"],
            "county": r0["countyname"],
            "station": r0["station"],
            "hazmat_cars_released": int(sum(_num(r[field]) for r in inc["reports"])),
            "persons_evacuated": int(values["personsevacuated"]),
            "persons_killed": int(values["totalpersonskilled"]),
            "persons_injured": int(values["totalpersonsinjured"]),
            # HB-215: the accident's damage once, the reports' Blocks 36 and 37 summed;
            # `totaldamagecost` is the accident's total repeated on every report, so
            # summing it counted a two-railroad incident twice
            "damage_usd": int(
                sum(
                    _num(r["equipmentdamagecost"]) + _num(r["trackdamagecost"])
                    for r in inc["reports"]
                )
            ),
            "severity": sev["id"],
            "fra_report_url": r0["url"],
            "dataset_doc_id": ds["doc_id"],
            "dataset_sha256": sha,
            "location_method": "reported_coordinates",
        }
        if where is None:
            misses.append(props)
            continue
        pts.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [round(where[0], 6), round(where[1], 6)],
                },
                "properties": props,
            }
        )
    return pts, misses


# ---- Part B: the grid, Gi* and the density


def _in(box: dict, lon: float, lat: float) -> bool:
    return box["south"] <= lat <= box["north"] and box["west"] <= lon <= box["east"]


def hotspots(cfg: dict, incidents: list[dict], pts: list[dict]) -> dict:
    alb = H.Albers(**cfg["projection"])
    conus = cfg["conus"]
    bg = [w for w in (_locate(i["reports"]) for i in incidents) if w and _in(conus, *w)]
    rel = [
        f["geometry"]["coordinates"]
        for f in pts
        if _in(conus, *f["geometry"]["coordinates"])
    ]
    outside = [
        f["properties"]["incident_key"]
        for f in pts
        if not _in(conus, *f["geometry"]["coordinates"])
    ]
    bx, by = alb.forward([p[0] for p in bg], [p[1] for p in bg])
    rx, ry = alb.forward([p[0] for p in rel], [p[1] for p in rel])
    d = np.hypot(rx[:, None] - rx[None, :], ry[:, None] - ry[None, :])
    np.fill_diagonal(d, np.inf)
    nn_median_km = float(np.median(d.min(axis=1)) / 1000)
    hs = cfg["hotspots"]
    if hs["spacing_rule"] != "median_nearest_neighbour":
        raise ValueError(
            f"hotspots.spacing_rule {hs['spacing_rule']!r} is not implemented"
        )
    spacing_km = round(nn_median_km / hs["round_km"]) * hs["round_km"]
    size = spacing_km * 1000 / math.sqrt(3)
    bq, br = H.hex_of(bx, by, size)
    n_bg = defaultdict(int)
    for c in zip(bq.tolist(), br.tolist()):
        n_bg[c] += 1
    cells = sorted(n_bg)
    pos = {c: i for i, c in enumerate(cells)}
    x = np.zeros(len(cells))
    for c in zip(*(a.tolist() for a in H.hex_of(rx, ry, size))):
        x[pos[c]] += (
            1  # a released incident is a Form 54 accident, so its cell is in the domain
        )
    nb = H.neighbour_index(cells)
    g = H.gi_star(x, nb, permutations=hs["permutations"], seed=hs["seed"])
    fdr = H.benjamini_hochberg(g["p_sim"])
    cx, cy = H.hex_centre([c[0] for c in cells], [c[1] for c in cells], size)
    clon, clat = alb.inverse(cx, cy)
    rows = []
    for i, c in enumerate(cells):
        level = None
        if g["z"][i] > 0:
            for lv in hs["levels"]:
                if g["p_sim"][i] <= lv["p"]:
                    level = lv["label"]
                    break
        rows.append(
            {
                "q": c[0],
                "r": c[1],
                "lon": round(float(clon[i]), 5),
                "lat": round(float(clat[i]), 5),
                "form54_accidents": n_bg[c],
                "released": int(x[i]),
                "neighbours": int((nb[i] >= 0).sum() - 1),
                "z": round(float(g["z"][i]), 4),
                "p_norm": float(f"{g['p_norm'][i]:.4g}"),
                "p_sim": round(float(g["p_sim"][i]), 4),
                "p_fdr": round(float(fdr[i]), 4),
                "hot": level,
            }
        )
    # kernel density, national, on the projected plane
    kd = cfg["kde"]
    if kd["bandwidth_rule"] != "hex_spacing":
        raise ValueError(
            f"kde.bandwidth_rule {kd['bandwidth_rule']!r} is not implemented"
        )
    bw = spacing_km * 1000
    step = kd["step_km"] * 1000
    x0, y0 = math.floor(bx.min() / step) * step, math.floor(by.min() / step) * step
    nx = int(math.ceil((bx.max() - x0) / step)) + 1
    ny = int(math.ceil((by.max() - y0) / step)) + 1
    dens = H.kde_grid(rx, ry, bandwidth=bw, x0=x0, y0=y0, step=step, nx=nx, ny=ny)
    dens *= kd["per_km2"] * 1e6  # per square metre to per `per_km2` km2
    peaks = []
    flat = np.argsort(-dens, axis=None)
    for idx in flat:
        j, i = divmod(int(idx), nx)
        px, py = x0 + (i + 0.5) * step, y0 + (j + 0.5) * step
        if all(math.hypot(px - p["_x"], py - p["_y"]) > 3 * bw for p in peaks):
            lo, la = alb.inverse(px, py)
            peaks.append(
                {
                    "_x": px,
                    "_y": py,
                    "lon": round(float(lo), 3),
                    "lat": round(float(la), 3),
                    "density": round(float(dens[j, i]), 3),
                }
            )
        if len(peaks) == 5:
            break
    for p in peaks:
        del p["_x"], p["_y"]
    kde = {
        "kernel": "gaussian",
        "bandwidth_km": spacing_km,
        "projection": "Albers equal-area conic, GRS 80, EPSG:5070 parameters",
        "x0_m": x0,
        "y0_m": y0,
        "step_m": step,
        "nx": nx,
        "ny": ny,
        "unit": (
            f"released incidents per {kd['per_km2']:,} km2, {cfg['period']['label']}"
        ),
        "points": len(rel),
        "peaks": peaks,
        "values": [[round(float(v), 3) for v in row] for row in dens],
    }
    return {
        "alb": alb,
        "size": size,
        "spacing_km": spacing_km,
        "nn_median_km": round(nn_median_km, 2),
        "cells": cells,
        "rows": rows,
        "nb": nb,
        "kde": kde,
        "outside": outside,
        "background": bg,
        "released_in_conus": len(rel),
    }


def hot_cells_geojson(cfg: dict, hsr: dict) -> dict:
    feats = []
    for row in hsr["rows"]:
        if not row["hot"]:
            continue
        corners = H.hex_corners(row["q"], row["r"], hsr["size"])
        lon, lat = hsr["alb"].inverse([c[0] for c in corners], [c[1] for c in corners])
        ring = [[round(float(a), 5), round(float(b), 5)] for a, b in zip(lon, lat)]
        ring.append(ring[0])
        props = {
            k: row[k]
            for k in (
                "q",
                "r",
                "released",
                "form54_accidents",
                "neighbours",
                "z",
                "p_norm",
                "p_sim",
                "p_fdr",
                "hot",
            )
        }
        feats.append(
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [ring]},
                "properties": props,
            }
        )
    return {
        "type": "FeatureCollection",
        "properties": {
            "method": (
                "Getis-Ord Gi*, binary weights with the cell itself and its six "
                "hexagon neighbours"
            ),
            "hex_spacing_km": hsr["spacing_km"],
            "permutations": cfg["hotspots"]["permutations"],
            "seed": cfg["hotspots"]["seed"],
            "receipts": cfg["receipts"]["gi_star"],
        },
        "features": feats,
    }


# ---- the count reconciliation (HB-136R step 2)


def counts_table(cfg: dict, pts: list[dict]) -> list[dict]:
    tsv = REPO / cfg["reconcile"]["table"]
    with tsv.open(encoding="utf-8") as fh:
        table = list(csv.DictReader(fh, delimiter="\t"))
    want = {tuple(k) for k in cfg["reconcile"]["rows"]}
    phmsa = {
        (r["category"], r["mode"]): r
        for r in table
        if (r["category"], r["mode"]) in want
    }
    if set(phmsa) != want:
        raise ValueError(f"{tsv}: rows {sorted(want - set(phmsa))} not found")
    reg = cfg["region"]
    first, last = int(cfg["period"]["first"][:4]), int(cfg["period"]["last"][:4])
    out = []
    for y in range(first, last + 1):
        ys = [f for f in pts if f["properties"]["year"] == y]
        row = {
            "year": y,
            "mode": cfg["dataset"]["mode"],
            "fra_released_incidents": len(ys),
            "fra_released_incidents_region": sum(
                1 for f in ys if _in(reg, *f["geometry"]["coordinates"])
            ),
        }
        for (cat, mode), r in sorted(phmsa.items()):
            key = "phmsa_rail_" + (
                "overall" if mode == "Overall" else "accident_related"
            )
            row[key] = r.get(str(y), "") or "not in table"
        out.append(row)
    return out


# ---- the figures


def _svg_text(x, y, s, size, color, anchor="start", weight="normal"):
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{color}" '
        f'text-anchor="{anchor}" '
        f'font-weight="{weight}">{html.escape(s)}</text>'
    )


def _wrap(text: str, width_px: float, size: float, em: float) -> list[str]:
    """Greedy word wrap at an average glyph width of `em` x the font size."""
    per = max(10, int(width_px / (size * em)))
    lines, cur = [], ""
    for word in text.split():
        if cur and len(cur) + 1 + len(word) > per:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}" if cur else word
    return lines + ([cur] if cur else [])


def place_name(p: dict) -> str:
    """'HYNDMAN', 'PA' -> 'Hyndman, PA'; a closing two-letter word stays in capitals,
    and a station that already ends in its state ('WASHINGTON DC') is not given it
    twice.
    """
    raw = p["station"].split()
    words = [
        w if (i == len(raw) - 1 and len(w) == 2) else w.capitalize()
        for i, w in enumerate(raw)
    ]
    if words and words[-1] == p["state"]:
        return " ".join(words)
    return f"{' '.join(words)}, {p['state']}"


def figure_svg(
    cfg: dict,
    hsr: dict,
    pts: list[dict],
    marks: list[dict],
    *,
    region: dict | None,
    width_px: int,
    title: str,
    notes: list[str],
) -> str:
    """One map: the Form 54 accidents of the period as the grey background (where trains
    ran and had accidents), the hot cells under the released incidents by severity, the
    marked fixtures, then the legend and the notes (counts, period, datasets, method,
    each with its row).
    """
    fc = cfg["figure"]
    sz = fc["px"]
    alb = hsr["alb"]
    if region is None:
        fx, fy = alb.forward(
            [p[0] for p in hsr["background"]], [p[1] for p in hsr["background"]]
        )
    else:  # the region's corners and edge midpoints projected; Albers bends parallels
        lons = [region["west"], (region["west"] + region["east"]) / 2, region["east"]]
        lats = [region["south"], region["north"]]
        fx, fy = alb.forward(
            [lo for lo in lons for _ in lats], [la for _ in lons for la in lats]
        )
    xmin, xmax, ymin, ymax = (
        float(fx.min()),
        float(fx.max()),
        float(fy.min()),
        float(fy.max()),
    )
    m = fc["frame_margin_share"] * (xmax - xmin)
    xmin, xmax, ymin, ymax = xmin - m, xmax + m, ymin - m, ymax + m
    pad = fc["pad_px"]
    title_lines = _wrap(title, width_px - 2 * pad, sz["title"], fc["em"])
    head = int(len(title_lines) * sz["title"] * 1.25 + pad)
    map_w = width_px - 2 * pad
    scale = map_w / (xmax - xmin)
    map_h = (ymax - ymin) * scale
    note_lines = [
        ln for n in notes for ln in _wrap(n, width_px - 2 * pad, sz["note"], fc["em"])
    ]
    # the legend is two columns: severity under its heading, and the scale, the hot
    # cells and the background
    legend_rows = max(
        1 + len(cfg["severity"]),
        (1 if region is not None else 0) + len(cfg["hotspots"]["levels"]) + 1,
    )
    top = head + pad
    # the last note's baseline (as the drawing below advances y), then its descent and a
    # margin
    last = (
        top
        + map_h
        + pad
        + sz["legend"]
        + legend_rows * sz["legend"] * 1.45
        + pad
        + len(note_lines) * sz["note"] * 1.35
    )
    height = int(math.ceil(last + 0.35 * sz["note"] + pad))

    def px(lon, lat):
        x, y = alb.forward(lon, lat)
        return pad + (float(x) - xmin) * scale, top + (ymax - float(y)) * scale

    def inside(lon, lat):
        return region is None or _in(region, lon, lat)

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_px}" height="{height}" '
        f'viewBox="0 0 {width_px} {height}" font-family="{fc["font"]}">',
        f'<rect width="{width_px}" height="{height}" fill="#ffffff"/>',
    ]
    for i, line in enumerate(title_lines):
        out.append(
            _svg_text(
                pad,
                pad + sz["title"] * (1 + 1.25 * i),
                line,
                sz["title"],
                fc["text"],
                weight="bold",
            )
        )
    out += [
        f'<clipPath id="map"><rect x="{pad}" y="{top}" width="{map_w}" '
        f'height="{map_h:.1f}"/></clipPath>',
        '<g clip-path="url(#map)">',
    ]
    # hot cells, lightest level first so the darker sits on top
    for lv in reversed(cfg["hotspots"]["levels"]):
        for row in hsr["rows"]:
            if row["hot"] != lv["label"]:
                continue
            corners = H.hex_corners(row["q"], row["r"], hsr["size"])
            pts_s = " ".join(
                f"{pad + (cx - xmin) * scale:.1f},{top + (ymax - cy) * scale:.1f}"
                for cx, cy in corners
            )
            out.append(
                f'<polygon points="{pts_s}" fill="{lv["color"]}" stroke="none"/>'
            )
    # the background, every located Form 54 accident of the period, as one path of small
    # squares, one per occupied half-pixel: 20,000 circles would make a megabyte, and
    # two accidents in the same half-pixel are one mark on any screen
    r_bg = fc["background_r"]
    seen = sorted(
        {
            (round(x * 2) / 2, round(y * 2) / 2)
            for x, y in (
                px(lon, lat) for lon, lat in hsr["background"] if inside(lon, lat)
            )
        }
    )
    d = "".join(
        f"M{x - r_bg:g} {y - r_bg:g}h{2 * r_bg:g}v{2 * r_bg:g}h{-2 * r_bg:g}z"
        for x, y in seen
    )
    out.append(f'<path d="{d}" fill="{fc["background_dot"]}"/>')
    # released incidents, least severe first so the worst is on top
    order = {s["id"]: i for i, s in enumerate(cfg["severity"])}
    color = {s["id"]: s["color"] for s in cfg["severity"]}
    shown = [f for f in pts if inside(*f["geometry"]["coordinates"])]
    shown.sort(
        key=lambda f: (
            -order[f["properties"]["severity"]],
            f["properties"]["incident_key"],
        )
    )
    for f in shown:
        x, y = px(*f["geometry"]["coordinates"])
        out.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{fc["point_r"]}" '
            f'fill="{color[f["properties"]["severity"]]}" stroke="#000000" '
            'stroke-width="0.6"/>'
        )
        if (
            region is not None
        ):  # direct labels: the place and the year, the report's own
            p = f["properties"]
            out.append(
                _svg_text(
                    x + fc["point_r"] + 4,
                    y + sz["label"] * 0.35,
                    f"{place_name(p)} {p['year']}",
                    sz["label"],
                    fc["text"],
                )
            )
    for mk in marks:
        if not inside(mk["longitude"], mk["latitude"]):
            continue
        x, y = px(mk["longitude"], mk["latitude"])
        out.append(
            f'<path d="M{x - 7:.1f},{y:.1f}H{x + 7:.1f}'
            f'M{x:.1f},{y - 7:.1f}V{y + 7:.1f}" '
            f'stroke="{fc["mark_color"]}" stroke-width="2.4"/>'
        )
        if region is not None:
            out.append(
                _svg_text(
                    x - 10,
                    y + sz["label"] * 0.35,
                    mk["words"],
                    sz["label"],
                    fc["mark_color"],
                    anchor="end",
                    weight="bold",
                )
            )
    if region is None:
        reg = cfg["region"]
        corners = [
            (reg["west"], reg["south"]),
            (reg["east"], reg["south"]),
            (reg["east"], reg["north"]),
            (reg["west"], reg["north"]),
        ]
        pts_s = " ".join("{:.1f},{:.1f}".format(*px(a, b)) for a, b in corners)
        out.append(
            f'<polygon points="{pts_s}" fill="none" stroke="{fc["region_outline"]}" '
            'stroke-width="1"/>'
        )
    out.append("</g>")
    step = sz["legend"] * 1.45
    y0 = top + map_h + pad + sz["legend"]
    col2 = width_px / 2
    key = sz["legend"] * 1.5
    # column 1: the released incidents by severity, under a heading
    y = y0
    out.append(
        _svg_text(pad, y, "Hazmat released, by severity:", sz["legend"], fc["text"])
    )
    for s in cfg["severity"]:
        y += step
        out.append(
            f'<circle cx="{pad + 6}" cy="{y - sz["legend"] * 0.35:.1f}" '
            f'r="{fc["point_r"]}" '
            f'fill="{s["color"]}" stroke="#000000" stroke-width="0.6"/>'
        )
        out.append(_svg_text(pad + key, y, s["short"], sz["legend"], fc["text"]))
    # column 2: the scale (the region's), the hot cells and the background
    y = y0
    if region is not None:  # equal-area, so the scale varies a little with direction
        km = cfg["region"]["scale_bar_km"]
        bar = km * 1000 * scale
        out.append(
            f'<path d="M{col2},{y - 4:.1f}H{col2 + bar:.1f}" stroke="{fc["text"]}" '
            'stroke-width="2"/>'
        )
        out.append(_svg_text(col2 + bar + 6, y, f"{km} km", sz["legend"], fc["text"]))
        y += step
    for lv in cfg["hotspots"]["levels"]:
        out.append(
            f'<rect x="{col2}" y="{y - sz["legend"] * 0.85:.1f}" width="12" '
            f'height="12" fill="{lv["color"]}"/>'
        )
        out.append(
            _svg_text(
                col2 + key, y, f"Gi* hot cell, {lv['label']}", sz["legend"], fc["text"]
            )
        )
        y += step
    out.append(
        f'<rect x="{col2 + 4}" y="{y - sz["legend"] * 0.5:.1f}" width="3" height="3" '
        f'fill="{fc["background_dot"]}"/>'
    )
    out.append(
        _svg_text(col2 + key, y, "any Form 54 accident", sz["legend"], fc["muted"])
    )
    y = y0 + legend_rows * step
    y += pad + sz["note"] * 1.35
    for line in note_lines:
        out.append(_svg_text(pad, y, line, sz["note"], fc["muted"]))
        y += sz["note"] * 1.35
    out.append("</svg>")
    return "\n".join(out) + "\n"


def _md_table(header: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def alt_text(cfg: dict, in_region: list[dict], region_hot: int) -> str:
    """The deck figure's alt text, from the data (deck.yaml quotes it from the page)."""
    places = ", ".join(
        f"{place_name(f['properties'])} {f['properties']['year']}"
        for f in sorted(in_region, key=lambda f: f["properties"]["date"])
    )
    hot = (
        "no Gi* hot cell lies in the region"
        if region_hot == 0
        else f"{region_hot} Gi* hot cells lie in the region"
    )
    marks = " and ".join(
        cfg["region"]["mark_words"][m].replace(" (fixture)", "")
        for m in cfg["region"]["mark"]
    )
    return (
        f"Map of the {cfg['region']['label']} region, {cfg['period']['label']}: "
        f"{len(in_region)} rail hazmat "
        f"releases ({places}) coloured by severity over the grey trace of every rail "
        "equipment accident, with "
        f"the {marks} fixtures marked; {hot}"
    )


def page_md(
    cfg: dict,
    summary: dict,
    counts: list[dict],
    pts: list[dict],
    in_region: list[dict],
    hsr: dict,
    src: dict,
) -> str:
    ds, hs, gs, reg = cfg["dataset"], cfg["hotspots"], summary["gi_star"], cfg["region"]
    period = cfg["period"]["label"]
    o = cfg["outputs"]
    sha = summary["dataset"]["sha256"]
    sev = {s["id"]: s for s in cfg["severity"]}
    # the released incidents in each hot cell's neighbourhood, by the report's own
    # station and state
    cell_of = {}
    for f in pts:
        x, y = hsr["alb"].forward(*f["geometry"]["coordinates"])
        q, r = H.hex_of(x, y, hsr["size"])
        cell_of.setdefault((int(q), int(r)), []).append(f["properties"])

    def near(row):
        out = []
        for dq, dr in ((0, 0), *H.NEIGHBOURS):
            out += cell_of.get((row["q"] + dq, row["r"] + dr), [])
        return out

    hot = sorted(
        (r for r in hsr["rows"] if r["hot"]), key=lambda r: (-r["z"], r["q"], r["r"])
    )
    hot_rows = [
        [
            f"{r['lat']:.2f}, {r['lon']:.2f}",
            r["released"],
            len(near(r)),
            f"{r['z']:.2f}",
            r["p_sim"],
            r["p_fdr"],
            r["hot"],
            "; ".join(sorted({place_name(p) for p in near(r)})) or "none",
        ]
        for r in hot
    ]
    reg_rows = [
        [
            p["date"],
            place_name(p),
            p["railroad"],
            p["accident_type"],
            p["hazmat_cars_released"],
            p["persons_evacuated"],
            p["persons_killed"],
            p["persons_injured"],
            f"{p['damage_usd']:,}",
            sev[p["severity"]]["words"],
            p["released_report_key"],
        ]
        for p in sorted((f["properties"] for f in in_region), key=lambda p: p["date"])
    ]
    by_sev = summary["by_severity"]
    years = [c for c in counts if c["phmsa_rail_overall"] != "not in table"]
    n_hot = summary["region"]["hot_cells"]
    region_hot_words = "none at 95%" if n_hot == 0 else str(n_hot)
    one = gs["cells_fdr_at_q"] == 1
    net = cfg["receipts"]["kde_network"]
    lines = [
        "# The incident hotspot map (HB-136R)",
        "",
        "Built by `scripts/build_incident_map.py` from `scripts/incident_map.yaml`; "
        "do not edit by hand "
        "(`--check` compares). No network and no model call: calls_made "
        f"{summary['calls_made']}.",
        "",
        f"## The {reg['label']} figure (the deck's)",
        "",
        f"![{alt_text(cfg, in_region, summary['region']['hot_cells'])}]"
        f"({Path(o['region_svg']).name})",
        "",
        "Alt text (the deck quotes it):",
        "",
        alt_text(cfg, in_region, summary["region"]["hot_cells"]) + ".",
        "",
        f"From {period[:4]} to {period[-4:]}, {summary['released_incidents']} rail "
        "incidents released hazmat in "
        f"the conterminous U.S.; {len(in_region)} of them in the {reg['label']} "
        "region the fixtures cover.",
        "",
        f"**Caption.** Rail hazmat releases, {reg['label']} ({reg['south']} to "
        f"{reg['north']} N, "
        f"{-reg['west']} to {-reg['east']} W), {period}: {len(in_region)} incidents, "
        "each where its report puts it. "
        f"Gi* hot cells in this region: {region_hot_words}. "
        "Data: FRA Form 6180.54, Rail Equipment Accident/Incident reports, row "
        f"`{ds['doc_id']}` "
        f"(sha256 `{sha}`; field list `{ds['fields_doc_id']}`), held by HB-135; one "
        "point per incident "
        "(`incidentkey`) with any car releasing hazmat (Block 10), at its reported "
        "coordinates (Blocks 50 and 51). "
        "PHMSA's 5800.1 incident reports are not held (row "
        f"`{cfg['phmsa']['doc_id']}`, rung 2; Issue "
        f"{cfg['phmsa']['issue']}), so highway, air and water releases are not on "
        "this map. Method: Getis-Ord Gi* "
        f"(rows "
        + ", ".join(f"`{d}`, DOI {src[d]['doi']}" for d in cfg["receipts"]["gi_star"])
        + "; neither held, Wiley refusing this client (HB-135; Issue 3f4efb5a), so "
        "cited by row and DOI as DN-005 "
        f"allows) on {gs['hex_spacing_km']} km hexagons ({gs['hex_area_km2']:,} km2, "
        "equal-area: Albers on GRS 80 "
        "with the EPSG:5070 parameters), each cell with its six neighbours, over the "
        f"{gs['domain_cells']:,} cells "
        "with any Form 54 accident of the period; one-sided p by "
        f"{hs['permutations']:,} permutations, seed "
        f"{hs['seed']}. The grey trace is every located Form 54 accident of the period "
        f"({summary['form54_incidents']:,} incidents nationally).",
        "",
        _md_table(
            [
                "Date",
                "Place",
                "Railroad",
                "Accident",
                "Cars released",
                "Evacuated",
                "Killed",
                "Injured",
                "Damage ($)",
                "Severity",
                "FRA report",
            ],
            reg_rows,
        ),
        "",
        "## Why these cells and this bandwidth",
        "",
        "- **Cell.** The hexagons' centre spacing is the median distance from a "
        "released incident to its nearest "
        f"released neighbour, {gs['nearest_neighbour_median_km']} km, rounded to "
        f"{gs['hex_spacing_km']} km. A typical "
        "incident's nearest released neighbour then falls inside its Gi* "
        "neighbourhood (the cell and its six "
        "neighbours), so the statistic compares neighbourhoods that hold more than "
        "one point. A smaller cell leaves "
        "most neighbourhoods empty; a larger one merges corridors hundreds of "
        "kilometres apart.",
        "- **Neighbourhood.** Binary weights, the cell itself included (Gi*, not "
        "Gi): a hexagon's six neighbours "
        "are all at one distance, which a square grid's eight are not. A neighbour "
        "outside the study area is left "
        "out of the sum, not counted as zero.",
        "- **Study area.** The cells holding at least one Form 54 rail equipment "
        "accident of any kind in the "
        "period: where trains ran and had accidents. A cell with no track is not a "
        "zero.",
        "- **p-values.** Ord and Getis 1995 is about Gi*'s distributional issues: "
        "with few neighbours and counts "
        "this sparse the normal approximation overstates significance (the TSV "
        "carries both). A cell is hot at 99% "
        "or 95% when z is above zero and its one-sided permutation p is at most 0.01 "
        "or 0.05. "
        f"{'No' if gs['cells_fdr_at_q'] == 0 else gs['cells_fdr_at_q']} cell"
        f"{'' if one else 's'} survive{'s' if one else ''} "
        "a "
        f"Benjamini-Hochberg false discovery rate of {gs['fdr_q']} over the "
        f"{gs['domain_cells']:,} tests, so the hot "
        f"cells are exploratory: where to look first, not a proven excess.",
        f"- **Kernel density.** Gaussian, bandwidth {summary['kde']['bandwidth_km']} "
        "km (the hexagon spacing, so the "
        f"surface and Gi* look at one scale), on a {cfg['kde']['step_km']} km grid, "
        f"in {summary['kde']['unit']} "
        f"(`{o['kde']}`). Planar, not along the track: network kernel density (row "
        f"`{net}`, DOI {src[net]['doi']}, "
        "not held) is the "
        f"method for points on a network and is not done here. Its five highest peaks: "
        + "; ".join(
            f"{p['lat']:.2f} N {-p['lon']:.2f} W ({p['density']})"
            for p in summary["kde"]["peaks"]
        )
        + ".",
        "- **No partition.** No step assigns incidents to groups; the question is "
        "density.",
        "",
        "## The national figure",
        "",
        f"![Rail hazmat releases, conterminous U.S., {period}]"
        f"({Path(o['national_svg']).name})",
        "",
        f"{summary['released_incidents']} released incidents: "
        + "; ".join(f"{by_sev[s['id']]} {s['words']}" for s in cfg["severity"])
        + f". Gi* hot cells: {gs['hot_cells']['99%']} at 99%, "
        f"{gs['hot_cells']['95%']} at 95% (`{o['cells_tsv']}` holds "
        f"every cell; `{o['hot_cells']}` the hot ones). The hot cells, by z, with the "
        "released incidents in each "
        f"neighbourhood named by their reports' own station and state:",
        "",
        _md_table(
            [
                "Centre (lat, lon)",
                "Released in cell",
                "In neighbourhood",
                "z",
                "p (perm.)",
                "p (FDR)",
                "Level",
                "Stations in the neighbourhood",
            ],
            hot_rows,
        ),
        "",
        "## Counts against HB-127's table (step 2): they do not reconcile",
        "",
        f"`{o['counts']}`. HB-127's rail rows are PHMSA's, from BTS TSAR 2024 Table "
        "5-5 (`bts-tsar-2024`, PDF "
        "p.161): hazardous materials incidents reported to PHMSA on Form 5800.1, "
        "which the same page says occur "
        "mostly in loading, unloading and storage, and the subset the table calls "
        "vehicular accident or "
        "derailment-related. This map counts FRA Form 54 incidents, rail equipment "
        'accidents "causing reportable '
        'damages greater than the reporting threshold" '
        "(`dot-fra-form54-85tf-25kj-metadata`), in which at least "
        "one car released hazmat. The definitions differ, so the counts differ, and "
        "neither is corrected to the "
        "other: the FRA count is below PHMSA's accident or derailment-related count "
        "in every year both cover.",
        "",
        _md_table(
            [
                "Year",
                "FRA, released (national)",
                "FRA, released (region)",
                "PHMSA rail, all",
                "PHMSA rail, accident or derailment-related",
            ],
            [
                [
                    c["year"],
                    c["fra_released_incidents"],
                    c["fra_released_incidents_region"],
                    c["phmsa_rail_overall"],
                    c["phmsa_rail_accident_related"],
                ]
                for c in counts
            ],
        ),
        "",
        f"In {years[0]['year']} to {years[-1]['year']}, the years both cover, FRA "
        "counts "
        f"{sum(c['fra_released_incidents'] for c in years)} released incidents and "
        "PHMSA "
        f"{sum(int(c['phmsa_rail_accident_related']) for c in years)} accident or "
        "derailment-related rail reports.",
        "",
        "## The planning reading",
        "",
        " ".join(cfg["planning_reading"].split()),
        "",
    ]
    return "\n".join(lines)


# ---- the build


def source_rows(cfg: dict) -> dict[str, dict]:
    """The manifest rows the map cites (the dataset, its field list, the PHMSA row and
    the method rows), each with its plan and, where its edition prints one, its DOI. A
    cited row that the manifest lacks is refused.
    """
    rows = yaml.safe_load(
        (REPO / "corpus" / "sources.yaml").read_text(encoding="utf-8")
    )
    rows = rows["sources"] if isinstance(rows, dict) else rows
    by = {r["doc_id"]: r for r in rows}
    want = [
        cfg["dataset"]["doc_id"],
        cfg["dataset"]["fields_doc_id"],
        cfg["phmsa"]["doc_id"],
        *cfg["receipts"]["gi_star"],
        cfg["receipts"]["kde_network"],
    ]
    missing = [d for d in want if d not in by]
    if missing:
        raise ValueError(f"corpus/sources.yaml has no row for {missing}")
    out = {}
    for d in want:
        m = re.search(r"DOI (\S+?)[;,]?(?:\s|$)", str(by[d].get("edition", "")))
        out[d] = {"plan": by[d].get("plan"), "doi": m.group(1) if m else None}
    return out


def fixture_marks(cfg: dict) -> list[dict]:
    pts = yaml.safe_load(
        (REPO / "fixtures" / "scenario_points.yaml").read_text(encoding="utf-8")
    )["points"]
    by = {p["id"]: p for p in pts}
    reg = cfg["region"]
    return [
        {
            "id": i,
            "latitude": by[i]["latitude"],
            "longitude": by[i]["longitude"],
            "words": reg["mark_words"][i],
        }
        for i in reg["mark"]
    ]


def build(cfg: dict) -> dict[str, str]:
    """Every output's path (repository-relative) to its text."""
    ds = cfg["dataset"]
    path = REPO / ds["path"]
    if not path.exists():
        raise HeldDataError(
            f"{ds['path']} is not here: it is gitignored held data (HB-135); link "
            "corpus/raw from the primary checkout"
        )
    sha = sha256_of(path)
    if sha != ds["sha256"]:
        raise HeldDataError(
            f"{ds['path']} hashes to {sha}, not the held {ds['sha256']} (HB-135 "
            "datasets_held.tsv)"
        )
    incidents = read_incidents(cfg, path)
    pts, misses = released_points(cfg, incidents, sha)
    if misses:
        raise HeldDataError(
            f"{len(misses)} released incident(s) carry no coordinates: "
            + ", ".join(m["incident_key"] for m in misses)
            + "; Form 54 gives station and county, not an address, so the held "
            "geocoder cache cannot place them"
        )
    hsr = hotspots(cfg, incidents, pts)
    counts = counts_table(cfg, pts)
    reg = cfg["region"]
    in_region = [f for f in pts if _in(reg, *f["geometry"]["coordinates"])]
    hot = [r for r in hsr["rows"] if r["hot"]]
    hot_region = [r for r in hot if _in(reg, r["lon"], r["lat"])]
    period = cfg["period"]["label"]
    by_sev = {
        s["id"]: sum(1 for f in pts if f["properties"]["severity"] == s["id"])
        for s in cfg["severity"]
    }
    summary = {
        "task": "HB-136R",
        "calls_made": 0,
        "dataset": {"doc_id": ds["doc_id"], "sha256": sha, "path": ds["path"]},
        "phmsa": {
            "doc_id": cfg["phmsa"]["doc_id"],
            "held": False,
            "issue": cfg["phmsa"]["issue"],
        },
        "period": period,
        "form54_incidents": len(incidents),
        "released_incidents": len(pts),
        "by_location_method": {
            "reported_coordinates": len(pts),
            "geocoded_to_place": 0,
        },
        "geocode_misses": [m["incident_key"] for m in misses],
        "outside_conus": hsr["outside"],
        "by_severity": by_sev,
        "region": {
            "label": reg["label"],
            "released_incidents": len(in_region),
            "incident_keys": sorted(f["properties"]["incident_key"] for f in in_region),
            "hot_cells": len(hot_region),
        },
        "gi_star": {
            "domain_cells": len(hsr["rows"]),
            "hex_spacing_km": hsr["spacing_km"],
            "hex_area_km2": round(H.hex_area(hsr["size"]) / 1e6, 1),
            "nearest_neighbour_median_km": hsr["nn_median_km"],
            "permutations": cfg["hotspots"]["permutations"],
            "seed": cfg["hotspots"]["seed"],
            "hot_cells": {
                lv["label"]: sum(1 for r in hot if r["hot"] == lv["label"])
                for lv in cfg["hotspots"]["levels"]
            },
            "cells_fdr_at_q": sum(
                1 for r in hsr["rows"] if r["p_fdr"] <= cfg["hotspots"]["fdr_q"]
            ),
            "fdr_q": cfg["hotspots"]["fdr_q"],
            "top": sorted(hot, key=lambda r: (-r["z"], r["q"], r["r"]))[:10],
        },
        "kde": {k: hsr["kde"][k] for k in ("kernel", "bandwidth_km", "unit", "peaks")},
    }
    hs = cfg["hotspots"]
    gs = summary["gi_star"]
    rows_by_id = source_rows(cfg)
    dois = ", ".join(
        f"{d} (DOI {rows_by_id[d]['doi']})" for d in cfg["receipts"]["gi_star"]
    )
    fdr = (
        "no cell survives a Benjamini-Hochberg false discovery rate of "
        f"{hs['fdr_q']}, so the hot cells are exploratory"
        if gs["cells_fdr_at_q"] == 0
        else f"{gs['cells_fdr_at_q']} cells survive a Benjamini-Hochberg false "
        f"discovery rate of {hs['fdr_q']}"
    )
    data_note = (
        f"Data: FRA Form 6180.54 rail equipment accidents, row {ds['doc_id']} (sha256 "
        f"{sha[:12]}), {period}: one "
        "point per incident with any car releasing hazmat (Block 10), at its "
        "reported coordinates (Blocks 50-51). "
        f"PHMSA's 5800.1 incident reports are not held (row {cfg['phmsa']['doc_id']}; "
        f"Issue {cfg['phmsa']['issue']}), "
        f"so highway, air and water releases are not on this map."
    )
    method_note = (
        f"Method: Getis-Ord Gi*, rows {dois}, not held and cited by row and DOI; "
        f"{hsr['spacing_km']} km equal-area "
        "hexagons (Albers, EPSG:5070 parameters), each cell with its six neighbours, "
        f"over the {gs['domain_cells']:,} "
        f"cells with any Form 54 accident; one-sided p by {hs['permutations']:,} "
        f"seeded permutations; {fdr}."
    )
    sev_note = (
        "Severity: the report's own fields, the highest that applies; killed and "
        "injured are Form 55a's "
        "per-accident totals, from any cause."
    )
    region_hot = (
        "Gi* hot cells in this region: none at 95%."
        if summary["region"]["hot_cells"] == 0
        else f"Gi* hot cells in this region: {summary['region']['hot_cells']}."
    )
    nat_hot = (
        f"Gi* hot cells: {gs['hot_cells']['99%']} at 99%, {gs['hot_cells']['95%']} at "
        "95%."
    )
    sev_words = "; ".join(f"{by_sev[s['id']]} {s['words']}" for s in cfg["severity"])
    marks = fixture_marks(cfg)
    region_svg = figure_svg(
        cfg,
        hsr,
        pts,
        marks,
        region=reg,
        width_px=cfg["figure"]["width_px"],
        title=(
            f"Rail hazmat releases, {reg['label']}, {period}: {len(in_region)} "
            "incidents"
        ),
        # the deck shows this figure small: the full caption is the figure's page beside
        # it (docs/incidents/), and the figure carries the short form with the rows
        notes=[
            region_hot,
            f"FRA Form 54, row {ds['doc_id']}; PHMSA 5800.1 not held. Gi* (rows "
            f"{', '.join(cfg['receipts']['gi_star'])}), {hsr['spacing_km']} km "
            "hexagons.",
        ],
    )
    national_svg = figure_svg(
        cfg,
        hsr,
        pts,
        marks,
        region=None,
        width_px=cfg["figure"]["national_width_px"],
        title=(
            f"Rail hazmat releases, conterminous U.S., {period}: "
            f"{hsr['released_in_conus']} incidents"
        ),
        notes=[
            f"{nat_hot} By severity: {sev_words}. The box is the {reg['label']} "
            "figure's region.",
            data_note,
            method_note,
            sev_note,
        ],
    )
    o = cfg["outputs"]
    cols = list(hsr["rows"][0])
    cells_tsv = (
        "\t".join(cols)
        + "\n"
        + "".join(
            "\t".join("" if r[c] is None else str(r[c]) for c in cols) + "\n"
            for r in hsr["rows"]
        )
    )
    ccols = list(counts[0])
    counts_tsv = (
        "\t".join(ccols)
        + "\n"
        + "".join("\t".join(str(r[c]) for c in ccols) + "\n" for r in counts)
    )
    points = {
        "type": "FeatureCollection",
        "properties": {
            "dataset_doc_id": ds["doc_id"],
            "dataset_name": ds["name"],
            "dataset_sha256": sha,
            "fields_doc_id": ds["fields_doc_id"],
            "period": period,
            "unit": (
                "incident (incidentkey); a release when any report's "
                "hazmatreleasedcars > 0"
            ),
            "severity": [
                {k: s[k] for k in ("id", "field", "words")} for s in cfg["severity"]
            ],
            "built_by": "scripts/build_incident_map.py (HB-136R)",
        },
        "features": pts,
    }
    return {
        o["points"]: json.dumps(points, indent=1, sort_keys=False) + "\n",
        o["hot_cells"]: json.dumps(hot_cells_geojson(cfg, hsr), indent=1) + "\n",
        o["cells_tsv"]: cells_tsv,
        o["kde"]: json.dumps(hsr["kde"], separators=(",", ":")) + "\n",
        o["counts"]: counts_tsv,
        o["summary"]: json.dumps(summary, indent=1) + "\n",
        o["region_svg"]: region_svg,
        o["national_svg"]: national_svg,
        o["page"]: page_md(cfg, summary, counts, pts, in_region, hsr, rows_by_id),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--check",
        action="store_true",
        help="compare a fresh build with the committed files",
    )
    args = ap.parse_args(argv)
    files = build(load_config())
    if args.check:
        bad = [
            p
            for p, text in files.items()
            if not (REPO / p).exists() or (REPO / p).read_text(encoding="utf-8") != text
        ]
        for p in bad:
            print(f"DIFFERS: {p}")
        print(
            f"{len(files) - len(bad)} of {len(files)} outputs equal a fresh build; "
            "calls_made 0"
        )
        return 1 if bad else 0
    for p, text in files.items():
        dest = REPO / p
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        print(f"wrote {p} ({len(text.encode()):,} bytes)")
    print("calls_made 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
