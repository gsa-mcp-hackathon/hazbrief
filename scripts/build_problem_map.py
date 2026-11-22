# ruff: noqa: E501  (the page, the source line and the alt text are prose strings, kept whole to read as printed)
"""The deck's problem slide: how often hazmat is released in transport and what it costs,
with a U.S. map of rail releases whose marks' areas are their damage (HB-215 Part C).

    uv run python scripts/build_problem_map.py           # write every output
    uv run python scripts/build_problem_map.py --check   # rebuild in memory, compare; exit 1 on a difference

Reads only committed records (`problem_map.yaml` `inputs`): HB-136R's 146 points, one per
FRA Form 54 incident 2016-2025 in which a car released hazmat, each at its reported
coordinates with its reported damage (Blocks 36 and 37, counted once per incident: HB-215
fixed HB-136R's double count); HB-136R's grid cells, drawn as the ground; and HB-127's
base-rate row for incidents reported to PHMSA in all modes (BTS TSAR 2024 Table 5-5).
No call and no held raw file, so it rebuilds on a clean clone.

The map follows the deck's house style and the display rules its config names: one mark
per place, its AREA proportional to the place's damage, one colour, no decoration, a
scale key, the source and years under it.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import sys
from collections import defaultdict
from html import escape
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import incident_hotspots as H  # noqa: E402

CONFIG = Path(__file__).with_name("problem_map.yaml")


def load_config(path: Path = CONFIG) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def phmsa_row(cfg: dict) -> dict:
    """HB-127's base-rate row the slide prints; refused if it is not held as a number."""
    i = cfg["inputs"]
    for row in csv.DictReader(io.StringIO(_read(i["base_rates"])), delimiter="\t"):
        if row["measure"] == i["phmsa_measure"] and row["period"] == i["phmsa_period"]:
            if row["value"] == "not_held":
                raise ValueError(
                    f"{i['phmsa_measure']} {i['phmsa_period']} is not held"
                )
            return row
    raise LookupError(f"no base-rate row {i['phmsa_measure']!r} {i['phmsa_period']!r}")


def places(cfg: dict, features: list[dict]) -> list[dict]:
    """One place per rounded coordinate pair: its incidents and their damage summed,
    largest damage first (so the map draws small marks over large ones)."""
    nd = cfg["place_decimals"]
    q = cfg["figure"]["quantity"]
    got: dict[tuple, dict] = {}
    for f in features:
        lon, lat = f["geometry"]["coordinates"]
        key = (round(lon, nd), round(lat, nd))
        p = got.setdefault(
            key, {"lon": lon, "lat": lat, "incidents": [], "damage_usd": 0}
        )
        p["incidents"].append(f["properties"]["incident_key"])
        p["damage_usd"] += int(f["properties"][q])
    return sorted(got.values(), key=lambda p: (-p["damage_usd"], p["incidents"][0]))


def numbers(cfg: dict) -> dict:
    """Every number the slide and the page print, from the records."""
    i = cfg["inputs"]
    pts = json.loads(_read(i["points"]))
    feats = pts["features"]
    summ = json.loads(_read(i["summary"]))
    by_year: dict[int, list] = defaultdict(lambda: [0, 0])
    for f in feats:
        p = f["properties"]
        by_year[p["year"]][0] += 1
        by_year[p["year"]][1] += int(p["damage_usd"])
    years = sorted(by_year)
    total = sum(v[1] for v in by_year.values())
    n = len(feats)
    pl = places(cfg, feats)
    ph = phmsa_row(cfg)
    if n != summ["released_incidents"]:
        raise ValueError(
            f"{n} points but HB-136R's summary says {summ['released_incidents']}"
        )
    return {
        "task": "HB-215",
        "calls_made": 0,
        "period": f"{years[0]}-{years[-1]}",
        "years": len(years),
        "rail": {
            "dataset_doc_id": pts["properties"]["dataset_doc_id"],
            "dataset_sha256": pts["properties"]["dataset_sha256"],
            "released_incidents": n,
            "places": len(pl),
            "per_year_mean": round(n / len(years), 1),
            "damage_usd": total,
            "damage_million_usd": round(total / 1e6, 1),
            "damage_million_usd_per_year_mean": round(total / 1e6 / len(years), 1),
            "largest_place_damage_million_usd": round(pl[0]["damage_usd"] / 1e6, 1),
            "zero_damage_places": sum(1 for p in pl if p["damage_usd"] == 0),
            "by_year": [
                {
                    "year": y,
                    "released_incidents": by_year[y][0],
                    "damage_usd": by_year[y][1],
                    "damage_million_usd": round(by_year[y][1] / 1e6, 1),
                }
                for y in years
            ],
        },
        "phmsa_all_modes": {
            "measure": ph["measure"],
            "value": int(ph["value"]),
            "period": ph["period"].split(" ")[0],
            "doc_id": ph["doc_id"],
            "page": ph["page"],
        },
    }


def render_tsv(nums: dict) -> str:
    r = nums["rail"]
    out = io.StringIO()
    w = csv.writer(out, delimiter="\t", lineterminator="\n")
    w.writerow(["measure", "period", "value", "unit", "source"])
    ph = nums["phmsa_all_modes"]
    w.writerow(
        [
            ph["measure"],
            ph["period"],
            f"{ph['value']:,}",
            "incidents",
            f"{ph['doc_id']}, {ph['page']}",
        ]
    )
    src = f"{r['dataset_doc_id']} via fixtures/incidents (HB-136R)"
    for y in r["by_year"]:
        w.writerow(
            [
                "Rail accidents in which a car released hazmat",
                y["year"],
                y["released_incidents"],
                "incidents",
                src,
            ]
        )
        w.writerow(
            [
                "Their reported damage, equipment and track",
                y["year"],
                y["damage_million_usd"],
                "million dollars",
                src,
            ]
        )
    w.writerow(
        [
            "Rail accidents in which a car released hazmat",
            nums["period"],
            r["released_incidents"],
            "incidents",
            src,
        ]
    )
    w.writerow(
        [
            "Rail accidents in which a car released hazmat, a year on average",
            nums["period"],
            r["per_year_mean"],
            "incidents a year",
            src,
        ]
    )
    w.writerow(
        [
            "Their reported damage, equipment and track",
            nums["period"],
            r["damage_million_usd"],
            "million dollars",
            src,
        ]
    )
    w.writerow(
        [
            "Their reported damage, a year on average",
            nums["period"],
            r["damage_million_usd_per_year_mean"],
            "million dollars a year",
            src,
        ]
    )
    return out.getvalue()


def _wrap(text: str, chars: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        if cur and len(cur) + 1 + len(word) > chars:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    return lines + ([cur] if cur else [])


def source_line(cfg: dict, nums: dict) -> str:
    r = nums["rail"]
    return (
        f"Source: FRA Form 6180.54 rail equipment accidents ({r['dataset_doc_id']}), "
        f"{nums['period']}: the {r['released_incidents']} accidents in which a car released "
        "hazmat, at their reported coordinates. Mark area: reported damage to equipment "
        "and track (Blocks 36 and 37), dollars as reported. Grey: 71 km cells with any "
        "rail equipment accident. Highway, air and water releases (PHMSA 5800.1) are not held."
    )


def render_svg(cfg: dict, nums: dict) -> str:
    fc = cfg["figure"]
    i = cfg["inputs"]
    im = yaml.safe_load(_read(i["incident_map"]))
    alb = H.Albers(**im["projection"])
    summ = json.loads(_read(i["summary"]))
    size = summ["gi_star"]["hex_spacing_km"] * 1000 / math.sqrt(3)
    cells = list(csv.DictReader(io.StringIO(_read(i["cells"])), delimiter="\t"))
    polys = [H.hex_corners(int(c["q"]), int(c["r"]), size) for c in cells]
    xs = [x for p in polys for x, _ in p]
    ys = [y for p in polys for _, y in p]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    m = (x1 - x0) * fc["margin"]
    x0, x1, y0, y1 = x0 - m, x1 + m, y0 - m, y1 + m
    pad = fc["pad_px"]
    w = fc["width_px"]
    scale = (w - 2 * pad) / (x1 - x0)
    map_h = (y1 - y0) * scale

    def px(x, y):
        return pad + (x - x0) * scale, pad + (y1 - y) * scale

    out = []
    for p in polys:
        pts = " ".join(f"{a:.1f},{b:.1f}" for a, b in (px(x, y) for x, y in p))
        out.append(f'<polygon points="{pts}" fill="{fc["cell_color"]}"/>')
    pts = json.loads(_read(i["points"]))["features"]
    pl = places(cfg, pts)
    dmax = pl[0]["damage_usd"]
    rmax, rmin = fc["max_radius_px"], fc["min_radius_px"]

    def radius(d: float) -> float:
        return max(rmin, rmax * math.sqrt(d / dmax))

    col, op, sw = fc["mark_color"], fc["mark_fill_opacity"], fc["mark_stroke_px"]
    for p in pl:
        x, y = alb.forward(p["lon"], p["lat"])
        cx, cy = px(float(x), float(y))
        out.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{radius(p["damage_usd"]):.2f}" '
            f'fill="{col}" fill-opacity="{op}" stroke="{col}" stroke-width="{sw}"/>'
        )
    # the scale key: its circles side by side on one baseline, each labelled at its
    # right, drawn as the marks are, beneath the map
    fs, tc, font = fc["font_px"], fc["text_color"], fc["font"]
    ky = pad + map_h + 12
    base = ky + 2 * rmax
    kx = float(pad)
    key = []
    for usd in sorted(fc["key_usd"]):
        r = radius(usd)
        label = f"${usd / 1e6:g} million"
        key.append(
            f'<circle cx="{kx + r:.1f}" cy="{base - r:.1f}" r="{r:.2f}" fill="{col}" '
            f'fill-opacity="{op}" stroke="{col}" stroke-width="{sw}"/>'
            f'<text x="{kx + 2 * r + 6:.1f}" y="{base - 2:.1f}" font-size="{fs}" '
            f'fill="{tc}">{label}</text>'
        )
        kx += 2 * r + 6 + len(label) * fs * 0.5 + 24
    small = math.ceil(dmax * (rmin / rmax) ** 2 / 1000) * 1000
    key.append(
        f'<text x="{kx:.1f}" y="{base - 2:.1f}" font-size="{fs}" '
        f'fill="{tc}">Area: reported damage. Under ${small:,}: the smallest '
        "size.</text>"
    )
    lines = _wrap(source_line(cfg, nums), int((w - 2 * pad) / (fs * 0.5)))
    ty = base + 10
    for k, line in enumerate(lines):
        key.append(
            f'<text x="{pad}" y="{ty + (k + 1) * fs * 1.35:.1f}" font-size="{fs}" '
            f'fill="{tc}">{escape(line)}</text>'
        )
    h = ty + (len(lines) + 1) * fs * 1.35
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h:.0f}" '
        f'viewBox="0 0 {w} {h:.0f}" font-family="{font}">\n'
        f'<rect width="{w}" height="{h:.0f}" fill="#FFFFFF"/>\n'
        + "\n".join(out + key)
        + "\n</svg>\n"
    )


def alt_text(nums: dict) -> str:
    r = nums["rail"]
    return (
        f"Map of the conterminous United States, {nums['period']}: one circle for each of the "
        f"{r['released_incidents']} rail accidents in which a car released hazmat, its area "
        f"its reported damage (largest ${r['largest_place_damage_million_usd']} million), "
        "over grey cells where any rail equipment accident happened."
    )


def render_md(cfg: dict, nums: dict) -> str:
    r = nums["rail"]
    ph = nums["phmsa_all_modes"]
    rows = "\n".join(
        f"| {y['year']} | {y['released_incidents']} | {y['damage_million_usd']} |"
        for y in r["by_year"]
    )
    o = cfg["outputs"]
    return f"""<!-- Generated by scripts/build_problem_map.py from scripts/problem_map.yaml (HB-215 Part C); do not edit. -->
# The problem slide's numbers and map

{alt_text(nums)}

## How often, and what it costs

- **All modes:** {ph["value"]:,} hazmat transportation incidents were reported to PHMSA in {ph["period"]}
  (`{ph["doc_id"]}`, {ph["page"]}; `docs/evidence/hb127/base_rates.tsv`). Their damage in dollars is not held:
  BTS NTS table 2-6 and the Table 5-5 workbook were refused to the fetcher (HB-127, rung 2).
- **Rail, where a car released hazmat:** {r["released_incidents"]} accidents in {nums["period"]}, {r["per_year_mean"]} a
  year on average, with ${r["damage_million_usd"]} million of reported damage to equipment and track
  (${r["damage_million_usd_per_year_mean"]} million a year on average; dollars as reported, not adjusted for
  inflation; FRA Form 54 Blocks 36 and 37, each accident counted once).

| Year | Rail accidents releasing hazmat | Reported damage, million dollars |
|---|---|---|
{rows}

## The map

`{o["svg"]}`: one mark per place ({r["places"]} places), its area proportional to the place's reported damage, one
colour, a scale key, and the source and years beneath. The ground is HB-136R's 71 km cells holding any Form 54
accident; the United States' outline is not held. {r["zero_damage_places"]} accident reported no damage and is drawn
at the smallest size. The line under the map:

{source_line(cfg, nums)}

Built by `scripts/build_problem_map.py` from `scripts/problem_map.yaml` (no call; `--check` rebuilds and compares),
with HB-136R's projection from `scripts/incident_map.yaml` and `scripts/incident_hotspots.py`; summary
`{cfg["inputs"]["summary"]}`. Records: `{o["tsv"]}`, `{o["json"]}`; inputs `{cfg["inputs"]["points"]}`, `{cfg["inputs"]["cells"]}`,
`{cfg["inputs"]["base_rates"]}`.
"""


def build(cfg: dict) -> dict[str, str]:
    nums = numbers(cfg)
    o = cfg["outputs"]
    return {
        o["json"]: json.dumps(nums, indent=1) + "\n",
        o["tsv"]: render_tsv(nums),
        o["svg"]: render_svg(cfg, nums),
        o["md"]: render_md(cfg, nums),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="compare, write nothing")
    args = ap.parse_args(argv)
    cfg = load_config()
    files = build(cfg)
    if args.check:
        stale = [
            rel
            for rel, text in files.items()
            if not (REPO / rel).is_file()
            or (REPO / rel).read_text(encoding="utf-8") != text
        ]
        if stale:
            print(
                f"stale: {', '.join(stale)}; run scripts/build_problem_map.py",
                file=sys.stderr,
            )
            return 1
        print(f"{len(files)} of {len(files)} equal a fresh build")
        return 0
    for rel, text in files.items():
        (REPO / rel).write_text(text, encoding="utf-8")
        print(f"wrote {rel} ({len(text.encode()):,} bytes)")
    print("calls_made 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
