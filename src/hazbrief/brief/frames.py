"""The moving cloud's frames: every 15 minutes of cloud time, a coarse mesh of mean
concentration over the cloud, with the three level outlines drawn from it (HB-192;
DN-024 ADDENDUM-01).

A frame is taken from what the engine already writes while it runs: SCICHEM saves its
whole puff state every `DT_SAVE` (300 s, `scichem.yaml` `project.dt_save_s`), and the
driver (`scichem_driver`) stages the project at each dump whose time is a frame's, as it
staged each whole hour for HB-189. In the staged project the post-processor (`scipp`)
writes the mean concentration on a uniform grid (its "Uniform Grid (UG)" extraction,
`Extract_fi.f90` EX_METHODS 1; one row per point, X and Y in project km, the mean and
the variance in kg/m3) over the box the frame's outermost level reaches at that time.
That grid is the frame's mesh.

This module, on the host (numpy and shapely, which the brief already uses):

- `read_grid`: scipp's uniform-grid text as a `Grid`;
- `encode` and `decode`: the mesh stored as one byte per point, the base-10 logarithm
  of the mean in steps of `1 / codes_per_decade` decade from a floor below the
  outermost level (0: below the floor). The variance is not stored (the page reads the
  mean; the uncertainty area is the record's, HBD-378);
- `outline`: the area at or above a level, drawn from the mesh by marching squares
  (linear interpolation along each cell edge; a saddle cell joined or split by its
  centre's value, Lorensen and Cline 1987 as the field resolves its ambiguity), so a
  lookup inside an outline reads at or above its level;
- `simplify`: the outline simplified by the stated tolerance (Douglas and Peucker 1973,
  GEOS's topology-preserving form), so what is stored is what the first view can show;
- `lookup`: the mesh's value at a point, by bilinear interpolation, and its level band.

No concentration is changed by a factor; a lookup is approximate and the page says by
how much (`docs/evidence/hb192/lookup_accuracy.tsv`); a named place's own times and
values stay the engine's sensor's, exact (`cloud.times`).
"""

from __future__ import annotations

import base64
import gzip
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml
from shapely import make_valid
from shapely.geometry import MultiPolygon, Polygon, box
from shapely.ops import unary_union

CONFIG = Path(__file__).with_name("scichem.yaml")


def load_config(path: Path = CONFIG) -> dict:
    """`scichem.yaml` `frames`: the interval, the mesh's spacing and margin, the
    floor, the codes and the outline tolerance, each with its reason."""
    return yaml.safe_load(path.read_text(encoding="utf-8"))["frames"]


@dataclass(frozen=True)
class Grid:
    """A uniform grid of mean concentration (kg/m3): `values[iy, ix]` at
    (x0 + ix * dx, y0 + iy * dy), project km."""

    x0: float
    y0: float
    dx: float
    dy: float
    values: np.ndarray

    @property
    def nx(self) -> int:
        return int(self.values.shape[1])

    @property
    def ny(self) -> int:
        return int(self.values.shape[0])


def read_grid(text: str) -> Grid:
    """scipp's uniform-grid output (a header ending in a row of `=` then a column
    header, then `X Y Mean Variance` per point, X outer and Y inner) as a `Grid`."""
    lines = text.splitlines()
    try:
        start = next(i for i, ln in enumerate(lines) if ln.startswith("====")) + 2
    except StopIteration as exc:
        raise ValueError("not a scipp grid: no header rule") from exc
    pts = np.array(
        [[float(v) for v in ln.split()[:3]] for ln in lines[start:] if ln.strip()],
        dtype=float,
    )
    if pts.size == 0:
        raise ValueError("a scipp grid with no points")
    xs, ys = np.unique(pts[:, 0]), np.unique(pts[:, 1])
    if xs.size * ys.size != pts.shape[0]:
        raise ValueError(
            f"a scipp grid of {pts.shape[0]} points is not {xs.size} by {ys.size}"
        )
    vals = np.zeros((ys.size, xs.size))
    ix = np.searchsorted(xs, pts[:, 0])
    iy = np.searchsorted(ys, pts[:, 1])
    vals[iy, ix] = pts[:, 2]
    dx = float((xs[-1] - xs[0]) / (xs.size - 1)) if xs.size > 1 else 0.0
    dy = float((ys[-1] - ys[0]) / (ys.size - 1)) if ys.size > 1 else 0.0
    return Grid(float(xs[0]), float(ys[0]), dx, dy, vals)


def encode(grid: Grid, floor: float, per_decade: int) -> dict:
    """The mesh as stored: its origin and spacing (km), its size, the floor (kg/m3)
    and the codes, one byte per point (row by row, south first), gzip and base64."""
    v = grid.values
    with np.errstate(divide="ignore"):
        lg = np.where(v > floor, np.log10(np.maximum(v, 1e-300) / floor), -1.0)
    codes = np.where(lg < 0, 0, np.clip(np.rint(lg * per_decade) + 1, 1, 255))
    raw = codes.astype(np.uint8).tobytes()
    return {
        "x0_km": round(grid.x0, 6),
        "y0_km": round(grid.y0, 6),
        "dx_km": round(grid.dx, 6),
        "dy_km": round(grid.dy, 6),
        "nx": grid.nx,
        "ny": grid.ny,
        "floor_kg_m3": floor,
        "per_decade": per_decade,
        "codes_gz_b64": base64.b64encode(gzip.compress(raw, mtime=0)).decode("ascii"),
    }


def decode(mesh: dict) -> Grid:
    """A stored mesh as a `Grid` of the values its codes stand for (0 where below the
    floor)."""
    raw = gzip.decompress(base64.b64decode(mesh["codes_gz_b64"]))
    codes = np.frombuffer(raw, dtype=np.uint8).reshape(mesh["ny"], mesh["nx"])
    pd = float(mesh["per_decade"])
    vals = np.where(
        codes == 0,
        0.0,
        float(mesh["floor_kg_m3"]) * 10.0 ** ((codes.astype(float) - 1.0) / pd),
    )
    return Grid(
        float(mesh["x0_km"]),
        float(mesh["y0_km"]),
        float(mesh["dx_km"]),
        float(mesh["dy_km"]),
        vals,
    )


def _cell_polys(grid: Grid, level: float) -> list[Polygon]:
    """Marching squares: per cell with corners on both sides of `level`, the part of
    the cell at or above it, edges interpolated linearly; whole cells above it merged
    into one rectangle per row run."""
    v = grid.values
    inside = v >= level
    out: list[Polygon] = []
    ny, nx = v.shape
    if ny < 2 or nx < 2:
        return out
    x0, y0, dx, dy = grid.x0, grid.y0, grid.dx, grid.dy
    c = inside[:-1, :-1] & inside[:-1, 1:] & inside[1:, 1:] & inside[1:, :-1]
    any_in = inside[:-1, :-1] | inside[:-1, 1:] | inside[1:, 1:] | inside[1:, :-1]
    for i in range(ny - 1):
        row = c[i]
        j = 0
        while j < nx - 1:
            if row[j]:
                k = j
                while k + 1 < nx - 1 and row[k + 1]:
                    k += 1
                out.append(
                    box(x0 + j * dx, y0 + i * dy, x0 + (k + 1) * dx, y0 + (i + 1) * dy)
                )
                j = k + 1
            else:
                j += 1
    mixed = np.argwhere(any_in & ~c)

    def cross(pa, pb, va, vb):
        t = (level - va) / (vb - va) if vb != va else 0.5
        return (pa[0] + t * (pb[0] - pa[0]), pa[1] + t * (pb[1] - pa[1]))

    for i, j in mixed:
        xa, ya = x0 + j * dx, y0 + i * dy
        corners = [(xa, ya), (xa + dx, ya), (xa + dx, ya + dy), (xa, ya + dy)]
        vals = [v[i, j], v[i, j + 1], v[i + 1, j + 1], v[i + 1, j]]
        ins = [val >= level for val in vals]
        saddle = ins == [True, False, True, False] or ins == [False, True, False, True]
        if saddle and sum(vals) / 4.0 < level:
            # split: each inside corner keeps its own triangle
            for k in range(4):
                if ins[k]:
                    p, q = (k - 1) % 4, (k + 1) % 4
                    out.append(
                        Polygon(
                            [
                                cross(corners[k], corners[p], vals[k], vals[p]),
                                corners[k],
                                cross(corners[k], corners[q], vals[k], vals[q]),
                            ]
                        )
                    )
            continue
        ring = []
        for k in range(4):
            n = (k + 1) % 4
            if ins[k]:
                ring.append(corners[k])
            if ins[k] != ins[n]:
                ring.append(cross(corners[k], corners[n], vals[k], vals[n]))
        if len(ring) >= 3:
            out.append(Polygon(ring))
    return out


def _polygonal(g):
    if isinstance(g, (Polygon, MultiPolygon)):
        return g
    parts = []
    for p in getattr(g, "geoms", []):
        if isinstance(p, Polygon):
            parts.append(p)
        elif isinstance(p, MultiPolygon):
            parts.extend(p.geoms)
    return unary_union(parts) if parts else Polygon()


def outline(grid: Grid, level: float):
    """The area at or above `level` drawn from the mesh (project km), one valid shape;
    empty where no point reaches it."""
    polys = [make_valid(p) for p in _cell_polys(grid, level)]
    polys = [p for p in (_polygonal(q) for q in polys) if not p.is_empty]
    if not polys:
        return Polygon()
    return _polygonal(unary_union(polys))


def simplify(shape, tolerance_km: float):
    """The outline simplified at `tolerance_km` (Douglas and Peucker, GEOS's
    topology-preserving form), its parts in one pass. A part whose area,
    before or after it is simplified, is under the tolerance's square is dropped: the
    first view cannot show it (`small_parts_dropped` is what is kept, unsimplified)."""
    keep = [s for _p, s in _kept_parts(shape, tolerance_km)]
    if not keep:
        return Polygon()
    # the parts as they are (no union: a union would repair what it is given)
    return keep[0] if len(keep) == 1 else MultiPolygon(keep)


def small_parts_dropped(shape, tolerance_km: float):
    """The parts of `shape` that `simplify` keeps, as they are before simplifying."""
    keep = [p for p, _s in _kept_parts(shape, tolerance_km)]
    return unary_union(keep) if keep else Polygon()


def _kept_parts(shape, tolerance_km: float) -> list[tuple]:
    """(part, its simplified form) for every part kept. The parts are simplified in
    one topology-preserving pass (GEOS `TopologyPreservingSimplifier`, Douglas and
    Peucker with the rings kept valid and apart), which keeps every part and its order,
    so each pairs with its own simplified form. The pass can move a point past its
    parameter; how far it does on these clouds is measured
    (`docs/evidence/hb192/outline_tolerance.tsv`) and stated as `drawn_within_m`. Plain
    Douglas and Peucker drops a collapsing hole and moved points up to 103 m
    (`outline_tolerance_plain_dp.tsv`), so it is not used."""
    shape = _polygonal(shape)
    parts = list(shape.geoms) if isinstance(shape, MultiPolygon) else [shape]
    parts = [p for p in parts if not p.is_empty and p.area >= tolerance_km**2]
    if not parts:
        return []
    joint = MultiPolygon(parts).simplify(tolerance_km, preserve_topology=True)
    simple = list(joint.geoms) if isinstance(joint, MultiPolygon) else [joint]
    if len(simple) != len(parts):
        raise ValueError(
            f"simplifying {len(parts)} parts gave {len(simple)}: the pass is not "
            "topology-preserving as assumed"
        )
    return [(p, q) for p, q in zip(parts, simple) if q.area >= tolerance_km**2]


def lookup(grid: Grid, x: float, y: float) -> float | None:
    """The mesh's mean at (x, y) project km by bilinear interpolation; None outside
    the mesh."""
    fx = (x - grid.x0) / grid.dx if grid.dx else 0.0
    fy = (y - grid.y0) / grid.dy if grid.dy else 0.0
    if fx < 0 or fy < 0 or fx > grid.nx - 1 or fy > grid.ny - 1:
        return None
    j, i = min(int(fx), grid.nx - 2), min(int(fy), grid.ny - 2)
    tx, ty = fx - j, fy - i
    v = grid.values
    return float(
        v[i, j] * (1 - tx) * (1 - ty)
        + v[i, j + 1] * tx * (1 - ty)
        + v[i + 1, j + 1] * tx * ty
        + v[i + 1, j] * (1 - tx) * ty
    )


def band(value: float | None, levels: list[tuple[str, float]]) -> str | None:
    """The highest level (name, kg/m3; any order) `value` reaches, or None."""
    if value is None:
        return None
    hit = [(kg, name) for name, kg in levels if value >= kg]
    return max(hit)[1] if hit else None


ROOT = Path(__file__).resolve().parents[3]


def place_pairs(
    request: dict,
    smp_text: str,
    stored_frames: list[dict],
    kinds: tuple[str, ...] = ("named_place", "sited", "roadblock"),
) -> list[dict]:
    """HB-192 (ADDENDUM-01 section 1): at every frame and every named place the cloud
    reaches there (its own sensor at or above the outermost level at the frame's
    time), the mesh's lookup beside the place's own series: the sensor's mean,
    linearly interpolated between its two samples about the frame's time (the record
    samples every `dt_smp_s`), and the highest level the sensor reads. The sensor is at
    `point_height_m` and the mesh on the receptor plane (`plane_height_m`); both are
    the record's, and the rows say so."""
    from hazbrief.brief import scichem as SC

    meta = request["meta"]
    smp = SC.read_smp(smp_text)
    levels = levels_of(request)
    site = meta["site"]
    places = {p["id"]: p for p in meta["places"]}
    out = []
    for i, sid in enumerate(meta["sensors"]):
        if not sid.startswith("place:"):
            continue
        pl = places.get(sid.split(":", 1)[1])
        if pl is None or pl.get("kind") not in kinds:
            continue
        col = smp.column(SC._col(smp, "C", i + 1))
        x, y = SC.local_km(site["lat"], site["lon"], pl["lat"], pl["lon"])
        for fr in stored_frames:
            if not fr.get("mesh"):
                continue
            t = fr["minute"] * 60.0
            k = next((j for j, tt in enumerate(smp.times) if tt >= t - 1e-6), None)
            if k is None:
                continue
            if k == 0 or abs(smp.times[k] - t) < 1e-6:
                sv = col[k]
            else:
                t0, t1 = smp.times[k - 1], smp.times[k]
                sv = col[k - 1] + (col[k] - col[k - 1]) * (t - t0) / (t1 - t0)
            if sv < levels[0][1]:
                continue
            mv = lookup(decode(fr["mesh"]), x, y)
            out.append(
                {
                    "place": pl["id"],
                    "kind": pl.get("kind"),
                    "minute": fr["minute"],
                    "sensor_kg_m3": sv,
                    "mesh_kg_m3": mv,
                    "band": band(sv, levels),
                    "innermost": band(sv, levels) == levels[-1][0],
                    "ratio": (mv / sv) if mv is not None and sv > 0 else None,
                }
            )
    return out


def accuracy(pairs: list[dict]) -> dict:
    """The median and the worst (farthest from 1 by its logarithm) ratio of the mesh's
    lookup to the place's own sensor, over every pair and over the innermost band's."""

    def summary(rs: list[float]) -> dict:
        rs = sorted(r for r in rs if r is not None and r > 0)
        if not rs:
            return {"n": 0, "median": None, "worst": None}
        n = len(rs)
        med = rs[n // 2] if n % 2 else math.sqrt(rs[n // 2 - 1] * rs[n // 2])
        worst = max(rs, key=lambda r: abs(math.log(r)))
        return {"n": n, "median": round(med, 3), "worst": round(worst, 3)}

    return {
        "all": summary([p["ratio"] for p in pairs]),
        "innermost": summary([p["ratio"] for p in pairs if p["innermost"]]),
    }


def spec(cfg: dict, horizon_h: float) -> dict:
    """What the driver is asked for (`scichem_driver` module docstring): a frame every
    `every_s` up to the brief's horizon, the mesh's spacing (km), margin and cap."""
    return {
        "every_s": float(cfg["every_s"]),
        "until_s": float(horizon_h) * 3600.0,
        "spacing_km": float(cfg["spacing_m"]) / 1000.0,
        "margin_cells": int(cfg["margin_cells"]),
        "max_points": int(cfg["max_points"]),
    }


def levels_of(request: dict) -> list[tuple[str, float]]:
    """The request's tiers as (name, kg/m3), outermost (lowest) first."""
    return sorted(
        ((t["name"], float(t["kg_m3"])) for t in request["meta"]["tiers"]),
        key=lambda x: x[1],
    )


def _rings(shape) -> list:
    from hazbrief.brief import scichem as SC

    return SC._rings(shape)


def stored(row: dict, request: dict, cfg: dict) -> dict:
    """A driver's frame row as the frames record keeps it: the minute, the walls, the
    mesh (one byte a point, `encode`) and each level's outline drawn from that stored
    mesh and simplified (`outline`, `simplify`), as km rings about the site."""
    out = {
        "minute": round(float(row["frame_s"]) / 60.0),
        "engine_wall_s": row.get("engine_wall_s"),
        "shown_wall_s": row.get("shown_wall_s"),
    }
    if row.get("error"):
        out["error"] = row["error"]
        return out
    levels = levels_of(request)
    if row.get("empty"):
        out["mesh"] = None
        out["outlines"] = {name: [] for name, _ in levels}
        return out
    raw = gzip.decompress(base64.b64decode(row["mean_f32_gz_b64"]))
    vals = np.frombuffer(raw, dtype="<f4").astype(float).reshape(row["ny"], row["nx"])
    g = Grid(
        float(row["x0_km"]),
        float(row["y0_km"]),
        float(row["dx_km"]),
        float(row["dy_km"]),
        vals,
    )
    floor = levels[0][1] / 10.0 ** float(cfg["floor_decades_below"])
    mesh = encode(g, floor, int(cfg["codes_per_decade"]))
    dg = decode(mesh)
    tol = float(cfg["tolerance_m"]) / 1000.0
    out["mesh"] = mesh
    out["outlines"] = {
        name: _rings(simplify(outline(dg, kg), tol)) for name, kg in levels
    }
    return out


def record_path(sha: str, root: Path = ROOT) -> Path:
    """Where the frames of the run of request `sha` are held."""
    from hazbrief.brief import live_records
    from hazbrief.brief import scichem as SC

    sc = SC.load_config()
    # HB-207: a served live brief writes a run no task recorded under its live root
    return live_records.resolve(root / sc["frames"]["recordings_dir"] / f"{sha}.json")


def write_record(
    sha: str,
    request: dict,
    rows: list[dict],
    fspec: dict,
    cfg: dict,
    *,
    engine_id: str | None,
    made: str,
    check: dict | None = None,
    smp_text: str | None = None,
    root: Path = ROOT,
) -> dict:
    """The frames record of request `sha`'s run: the spec asked, the engine, how it was
    made (`run`: by the brief's own run; `backfill`: by running a held request again,
    with `check`, the comparison of that run's contours with the held record's), and
    each frame as `stored` keeps it, in the order the frames landed."""
    rec = {
        "request_sha256": sha,
        "spec": fspec,
        "config": {
            k: cfg[k]
            for k in (
                "floor_decades_below",
                "codes_per_decade",
                "tolerance_m",
                "drawn_within_m",
            )
        },
        "engine_id": engine_id,
        "made": made,
        "check": check,
        "frames": [stored(r, request, cfg) for r in rows],
    }
    # HB-192 (ADDENDUM-01 section 1): the lookup's stated accuracy, from the run's own
    # sensors at the named places
    rec["accuracy"] = (
        accuracy(place_pairs(request, smp_text, rec["frames"])) if smp_text else None
    )
    path = record_path(sha, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec, sort_keys=True) + "\n", encoding="utf-8")
    return rec


def read_record(sha: str, root: Path = ROOT) -> dict | None:
    """The held frames record of request `sha`'s run, or None where none is held."""
    path = record_path(sha, root)
    if not path.exists():
        return None
    rec = json.loads(path.read_text(encoding="utf-8"))
    if rec.get("request_sha256") != sha:
        raise RuntimeError(f"{path}: the frames record is not the one its name holds")
    return rec


#: the file beside `brief.html` that holds the frames' mesh (decision 6)
PUBLISHED = "frames.json"


def published(cloud: dict | None) -> dict | None:
    """HB-192 (DN-024 ADDENDUM-01 decisions 3 and 6): what the page reads for a point
    lookup, from request A's frames record: the site, the levels (kg/m3 and ppm), the
    stated accuracy and, per frame, its minute and stored mesh (the codes as held; no
    mesh is decoded here). None where the drawn cloud has no frames."""
    if not cloud or not cloud.get("frames_run"):
        return None
    run = cloud["frames_run"]
    held = read_record(run["record"])
    if held is None:
        return None
    tiers = cloud["tiers"]
    req_tiers = {t["name"]: t for t in tiers}
    meta_levels = [
        {"name": t["name"], "ppm": float(req_tiers[t["name"]]["ppm"])} for t in tiers
    ]
    return {
        "record": run["record"],
        "site": cloud["site"],
        "levels": meta_levels,
        "spacing_m": run["spacing_m"],
        "accuracy": held.get("accuracy"),
        "frames": [
            {"minute": fr["minute"], "mesh": fr.get("mesh")}
            for fr in held.get("frames") or []
            if not fr.get("error")
        ],
    }


def frame_box(
    rings_km: list, spacing_km: float, margin_cells: int
) -> tuple[float, float, float, float] | None:
    """The box a frame's mesh covers: the outermost level's area at that time, out by
    `margin_cells` cells, its corners on the mesh's spacing (so frames share points).
    None where the level covers nothing."""
    pts = [xy for poly in rings_km for ring in poly[:1] for xy in ring]
    if not pts:
        return None
    m = margin_cells * spacing_km
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]

    def lo(v: float) -> float:
        return math.floor((v - m) / spacing_km) * spacing_km

    def hi(v: float) -> float:
        return math.ceil((v + m) / spacing_km) * spacing_km

    return lo(min(xs)), hi(max(xs)), lo(min(ys)), hi(max(ys))
