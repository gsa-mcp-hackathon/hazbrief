"""The level set of a gridded field as a polygon: marching squares (HB-133 ADDENDUM-01).

A modelled footprint draws as the contour of its level of concern through the engine's
field, not as the grid cells above it (Issue 90ac45af, the operator's display review:
cells read as a defect). This is the isoline method every contouring package
implements: marching squares, the two-dimensional case of Lorensen and Cline's
marching cubes (SIGGRAPH 1987), with each crossing interpolated linearly along its
grid edge and the two saddle cases resolved by the cell's centre value (the mean of
its four corners), as matplotlib's and contourpy's "mpl2005" algorithm does. The
filled region is then the faces of the isolines' arrangement whose interior is at or
above the level (`shapely.ops.polygonize`), so holes and separate lobes come out as
the field has them.

The field is padded with one ring of nodes below the level, one cell outside the grid,
so every isoline closes; the result is clipped to the grid's own extent, where a level
still exceeded at the edge is cut by the grid (the caller says so: `reaches_grid_edge`).

The engine is not touched: `hazbrief.brief.puff` (whose bytes are the engine's
version, DN-018 section 8) keeps its cell contour for the extents it records; this
module only draws.
"""

from __future__ import annotations

import numpy as np
import shapely
from shapely.geometry import LineString, MultiLineString, box
from shapely.ops import polygonize, unary_union

#: Segments per marching-squares case: corner bits bottom-left 1, bottom-right 2,
#: top-right 4, top-left 8; edges B(ottom), R(ight), T(op), L(eft). The saddles (5, 10)
#: are resolved in `_segments` by the cell centre.
_CASES: dict[int, tuple[tuple[str, str], ...]] = {
    1: (("L", "B"),),
    2: (("B", "R"),),
    3: (("L", "R"),),
    4: (("R", "T"),),
    6: (("B", "T"),),
    7: (("L", "T"),),
    8: (("L", "T"),),
    9: (("B", "T"),),
    11: (("R", "T"),),
    12: (("L", "R"),),
    13: (("B", "R"),),
    14: (("L", "B"),),
}


def _cross(v0: np.ndarray, v1: np.ndarray, level: float) -> np.ndarray:
    """Where the level falls between two node values, as a fraction of the edge."""
    # a near-flat edge overflows to +-inf, which the clip bounds to the edge's end
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        t = (level - v0) / (v1 - v0)
    return np.clip(np.nan_to_num(t, nan=0.5), 0.0, 1.0)


def _bilinear(f: np.ndarray, xs: np.ndarray, ys: np.ndarray, x: float, y: float):
    j = int(np.clip(np.searchsorted(xs, x) - 1, 0, len(xs) - 2))
    i = int(np.clip(np.searchsorted(ys, y) - 1, 0, len(ys) - 2))
    tx = (x - xs[j]) / (xs[j + 1] - xs[j])
    ty = (y - ys[i]) / (ys[i + 1] - ys[i])
    return (
        f[i, j] * (1 - tx) * (1 - ty)
        + f[i, j + 1] * tx * (1 - ty)
        + f[i + 1, j] * (1 - tx) * ty
        + f[i + 1, j + 1] * tx * ty
    )


def level_set(field: np.ndarray, xg: np.ndarray, yg: np.ndarray, level: float):
    """The region of the regular grid (`xg`, `yg`: node coordinates, `meshgrid`'s
    order, increasing) where `field` is at or above `level`, as a shapely
    (Multi)Polygon bounded by the interpolated isoline; None when no node reaches it."""
    if not np.any(field >= level):
        return None
    xs0, ys0 = xg[0, :].astype(float), yg[:, 0].astype(float)
    dx, dy = xs0[1] - xs0[0], ys0[1] - ys0[0]
    xs = np.concatenate(([xs0[0] - dx], xs0, [xs0[-1] + dx]))
    ys = np.concatenate(([ys0[0] - dy], ys0, [ys0[-1] + dy]))
    below = min(float(np.min(field)), float(level)) - abs(float(level)) - 1.0
    f = np.full((len(ys), len(xs)), below)
    f[1:-1, 1:-1] = field
    up = f >= level
    # the crossing on every horizontal edge (i, j)-(i, j+1) and vertical edge
    # (i, j)-(i+1, j), computed once so two cells sharing an edge share its point
    hx = xs[:-1][None, :] + _cross(f[:, :-1], f[:, 1:], level) * dx
    vy = ys[:-1][:, None] + _cross(f[:-1, :], f[1:, :], level) * dy
    code = (
        up[:-1, :-1] * 1 + up[:-1, 1:] * 2 + up[1:, 1:] * 4 + up[1:, :-1] * 8
    ).astype(int)
    mixed = np.argwhere((code > 0) & (code < 15))
    segs = []
    for i, j in mixed:
        pts = {
            "B": (hx[i, j], ys[i]),
            "T": (hx[i + 1, j], ys[i + 1]),
            "L": (xs[j], vy[i, j]),
            "R": (xs[j + 1], vy[i, j + 1]),
        }
        k = int(code[i, j])
        if k in (5, 10):
            centre = (f[i, j] + f[i, j + 1] + f[i + 1, j + 1] + f[i + 1, j]) / 4.0
            joined = centre >= level
            if k == 5:
                pairs = (("L", "T"), ("B", "R")) if joined else (("L", "B"), ("R", "T"))
            else:
                pairs = (("L", "B"), ("R", "T")) if joined else (("B", "R"), ("L", "T"))
        else:
            pairs = _CASES[k]
        for a, b in pairs:
            if pts[a] != pts[b]:
                segs.append(LineString([pts[a], pts[b]]))
    faces = list(polygonize(unary_union(MultiLineString(segs)))) if segs else []
    keep = [
        p
        for p in faces
        if _bilinear(f, xs, ys, *p.representative_point().coords[0]) >= level
    ]
    if not keep:
        return None
    grid = box(xs0[0], ys0[0], xs0[-1], ys0[-1])
    out = shapely.make_valid(unary_union(keep).intersection(grid))
    return None if out.is_empty else out
