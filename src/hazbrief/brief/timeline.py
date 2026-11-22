"""The modelled plume over time (HB-157; DN-024 sections 3.5 to 3.10).

The puff (`hazbrief.brief.puff`, the engine; its bytes are its version) is evaluated
at fixed steps from the as-given time, and every few minutes between them, on one grid:

- **Step outlines.** The level-of-concern isoline through the field at each step
  (`contours.level_set`), the outline the time control moves. A step whose field still
  reaches the grid's edge is open: it is drawn open and labelled, never closed by the
  grid (DN-024 section 3.1).
- **Arrival bands.** The first sampled time each grid node reaches the level, banded at
  the steps: band k is where the level is first reached after step k-1 and by step k.
  This is the HPAC fallout display's "arrival time" over the map (held,
  `osd-ncbdp-specialized-radiological` p. 6) for a chemical cloud, and ALOHA's
  Concentration at Point arrival ("would arrive at the location in about 7 minutes",
  `epa-aloha-users-manual-2007` p. 155) over every place at once.
- **The end.** The modelled time ends at the first step whose interval reaches no new
  place, or at the horizon (HB-157 ADDENDUM-01 item 3). The grid is sized for the
  candidate end (`derive.puff_grid`'s rule); a run still growing at a candidate end is
  run again to the next step on its grid.

The field is the engine's own: `puff.field` is called puff by puff on the grid window
`grid_sigma_multiple` sigma_y around each puff's centre (the held equation's spread is
sigma_y; past 4 sigma a Gaussian is exp(-8) of its peak, the grid's own rule), so the
equation is never re-typed here.

Also here, pure: the wind-direction uncertainty lines' angle and rotation (NOAA's ALOHA
technical documentation section 4.5.3, held; `docs/evidence/hb160/for_hb157.md`), the
forecast wind's range for the range of plume paths, and the wind-shift check.
"""

from __future__ import annotations

import dataclasses
import math
import time
from dataclasses import dataclass

import numpy as np
import shapely
from shapely import affinity
from shapely.ops import unary_union

from hazbrief.brief import contours as isolines
from hazbrief.brief import puff as engine


class TimelineError(RuntimeError):
    """A step run the inputs cannot make (no level, a bad configuration, the
    deadline)."""


def step_minutes(tspec: dict) -> list[int]:
    """The steps after the release time, in minutes: every `fine_step_min` to
    `fine_until_min`, then every `coarse_step_min` to the horizon (`horizon_h`, never
    past `ceiling_h`)."""
    horizon_h = float(tspec["horizon_h"])
    if horizon_h <= 0 or horizon_h > float(tspec["ceiling_h"]):
        raise TimelineError(
            f"horizon {horizon_h:g} h is outside (0, {tspec['ceiling_h']} h]"
        )
    end = int(round(horizon_h * 60))
    fine, until = int(tspec["fine_step_min"]), int(tspec["fine_until_min"])
    coarse = int(tspec["coarse_step_min"])
    out = list(range(fine, min(until, end) + 1, fine))
    m = out[-1] if out else 0
    while m + coarse <= end:
        m += coarse
        out.append(m)
    if not out or out[-1] != end:
        out.append(end)
    return out


def step_level(thresholds: list[dict]) -> dict:
    """The one level of concern for every step and the arrival bands (DN-024 section
    3.5): the class's first threshold at its longest held duration. For a toxic gas,
    AEGL-2 at 60 minutes (the ERG's own basis); else the class's one threshold."""
    if not thresholds:
        raise TimelineError("no threshold for the steps")
    first = thresholds[0]["threshold"].split(" (")[0]
    same = [t for t in thresholds if t["threshold"].split(" (")[0] == first]
    return max(same, key=lambda t: t["minute"])


@dataclass
class StepRun:
    """One run of the steps on one grid (plane metres around the spill)."""

    xg: np.ndarray
    yg: np.ndarray
    step_m: float
    half_width_m: float
    arrival_s: np.ndarray
    snapshots: dict[int, np.ndarray]
    edge: dict[int, bool]
    end_minute: int
    ended_by: str
    skipped_low_wind: int
    #: the running maximum of the field at each step: where it is at or above the
    #: level is where the level has been reached by then
    reached_fields: dict[int, np.ndarray]
    level: float
    #: DN-025 section 3 item 5: at every sample minute up to the end, each named
    #: level's outline (plane metres, or None) and whether the field at the spill's node
    #: is at or above it; empty when the run was given no levels
    samples: dict[int, dict[str, object]] = dataclasses.field(default_factory=dict)
    covers: dict[int, dict[str, bool]] = dataclasses.field(default_factory=dict)
    #: the running maximum at the run's end (the harm path's field)
    peak: np.ndarray | None = None


def _window(
    xg: np.ndarray, yg: np.ndarray, step: float, cx: float, cy: float, r: float
):
    """The index slices of the grid's nodes within `r` of (cx, cy), or None."""
    x0, y0 = xg[0, 0], yg[0, 0]
    n = xg.shape[0]
    i0 = max(0, int(math.floor((cy - r - y0) / step)))
    i1 = min(n, int(math.ceil((cy + r - y0) / step)) + 1)
    j0 = max(0, int(math.floor((cx - r - x0) / step)))
    j1 = min(n, int(math.ceil((cx + r - x0) / step)) + 1)
    if i0 >= i1 or j0 >= j1:
        return None
    return slice(i0, i1), slice(j0, j1)


def windowed_field(
    puffs: list,
    t_s: float,
    xg: np.ndarray,
    yg: np.ndarray,
    step: float,
    curves: dict,
    cls: str,
    spec: dict,
    lifetime_s: float,
    deadline: float | None,
) -> tuple[np.ndarray, int]:
    """The engine's Eq. (3) at `t_s`, each puff added on its own window of the grid."""
    c = np.zeros_like(xg, dtype=float)
    k = float(spec["grid_sigma_multiple"])
    skipped = 0
    for p in puffs:
        if deadline is not None and time.monotonic() > deadline:
            raise TimelineError("timed out")
        age = t_s - p.t_s
        if age <= 0 or age > lifetime_s:
            continue
        if p.speed_ms < float(spec["low_wind_ms"]):
            skipped += 1
            continue
        # the puff's centre on its path and the distance it travelled (DN-025)
        cx, cy, d = engine.centre(p, t_s)
        sy, _ = engine.sigmas(curves, cls, [d])
        if not (float(sy[0]) > 0):
            continue
        win = _window(xg, yg, step, cx, cy, k * float(sy[0]) + step)
        if win is None:
            continue
        part, _ = engine.field(
            [p],
            t_s,
            xg[win],
            yg[win],
            curves,
            cls,
            z_m=float(spec["receptor_height_m"]),
            z0_m=float(spec["release_height_m"]),
            lifetime_s=lifetime_s,
            low_wind_ms=float(spec["low_wind_ms"]),
        )
        c[win] += part
    return c, skipped


def run_steps(
    envelope: dict,
    level_kg_m3: float,
    wind,
    curves: dict,
    cls: str,
    grid_for,
    steps: list[int],
    spec: dict,
    tspec: dict,
    deadline: float | None = None,
    fixed_end: int | None = None,
    end_level: float | None = None,
    levels: list[tuple[str, float]] | None = None,
) -> StepRun:
    """The steps for one envelope. `grid_for(minutes)` gives the grid (`half_width_m`,
    `cells`) sized to a run of that many minutes (`derive.puff_grid`). Samples every
    `sample_min` and at every step; stops at the first step whose interval reaches no
    new node, or at the last step. `fixed_end`: run to exactly that step and stop (the
    range's runs end where the central run ended).

    DN-025 section 3 item 5: `end_level` (kg/m3) is the level the end rule reads, the
    outermost drawn level, so a lower level's harm path is not cut where `level`'s
    stops growing (default `level`); `levels` ((name, kg/m3), ...) are outlined at every
    sample (`StepRun.samples`), with whether each covers the spill (`covers`)."""
    sample = int(tspec["sample_min"])
    end_at = level_kg_m3 if end_level is None else float(end_level)
    coarse_from = [m for m in steps if m >= int(tspec["first_grid_min"])] or [steps[-1]]
    if fixed_end is not None:
        coarse_from = [fixed_end]
    for cand in coarse_from:
        g = grid_for(cand)
        xg, yg, step = engine.grid(g["half_width_m"], int(g["cells"]))
        half = g["half_width_m"]
        lifetime = cand * 60.0 + float(spec["puff_dt_s"])
        puffs = engine.release(
            envelope["mass_kg"], envelope["duration_s"], float(spec["puff_dt_s"]), wind
        )
        times = sorted(
            set(range(sample, cand + 1, sample)) | {m for m in steps if m <= cand}
        )
        arrival = np.full(xg.shape, np.inf)
        # where the end rule's level has been reached (`end_level`; `level` by default)
        reached_end = np.zeros(xg.shape, dtype=bool)
        cmax = np.zeros(xg.shape)
        peaks: dict[int, np.ndarray] = {}
        snaps: dict[int, np.ndarray] = {}
        edge: dict[int, bool] = {}
        reached_by: dict[int, int] = {}
        samples: dict[int, dict[str, object]] = {}
        covers: dict[int, dict[str, bool]] = {}
        # A level covers the spill when its outline reaches the spill's node or one of
        # its eight neighbours (sqrt 2 cells), widened by the outline's simplification:
        # nearer the spill than a cell the field is not resolved, and a class F puff a
        # few metres wide falls between the nodes while the release lasts (DN-025
        # section 3 item 5; csx night, docs/evidence/hb162r/source_cover.txt)
        at_spill = (math.sqrt(2.0) + float(spec["contour_simplify_cells"])) * step
        spill = shapely.Point(0.0, 0.0)
        skipped = 0
        for m in times:
            f, skipped = windowed_field(
                puffs, m * 60.0, xg, yg, step, curves, cls, spec, lifetime, deadline
            )
            above = f >= level_kg_m3
            arrival[above & np.isinf(arrival)] = m * 60.0
            reached_end |= f >= end_at
            np.maximum(cmax, f, out=cmax)
            if levels:
                samples[m] = {
                    name: outline_near(f, xg, yg, kg, step, spec) for name, kg in levels
                }
                covers[m] = {
                    name: g is not None and g.distance(spill) <= at_spill
                    for name, g in samples[m].items()
                }
            if m in steps:
                snaps[m] = f
                peaks[m] = cmax.copy()
                ring = np.concatenate(
                    (above[0, :], above[-1, :], above[:, 0], above[:, -1])
                )
                edge[m] = bool(ring.any())
                reached_by[m] = int(reached_end.sum())
        done = [m for m in steps if m <= cand]
        end, ended_by = done[-1], "horizon" if cand == steps[-1] else None
        if fixed_end is not None:
            ended_by = "fixed"
        for prev, m in zip([0] + done, done if fixed_end is None else []):
            if reached_by[m] == reached_by.get(prev, 0) and reached_by[m] > 0:
                end, ended_by = m, "no_new_place"
                break
            if reached_by[m] == 0 and m >= int(tspec["first_grid_min"]):
                end, ended_by = m, "never_reached"
                break
        if ended_by is not None:
            keep = {m: snaps[m] for m in steps if m <= end}
            return StepRun(
                xg,
                yg,
                step,
                half,
                arrival,
                keep,
                {m: edge[m] for m in keep},
                end,
                ended_by,
                skipped,
                {m: peaks[m] for m in keep},
                level_kg_m3,
                {m: s for m, s in samples.items() if m <= end},
                {m: s for m, s in covers.items() if m <= end},
                peaks[end],
            )
    raise TimelineError("the step run did not end")  # unreachable: the last step ends


def outline_near(f: np.ndarray, xg, yg, level: float, step: float, spec: dict):
    """`outline` read on the part of the grid where the field reaches `level`, with a
    node of margin: the same isoline, without contouring the empty grid around it
    (DN-025 section 3 item 5 outlines every level at every sample)."""
    rows, cols = np.nonzero(f >= level)
    if rows.size == 0:
        return None
    n0, n1 = f.shape
    r0, r1 = max(int(rows.min()) - 1, 0), min(int(rows.max()) + 2, n0)
    c0, c1 = max(int(cols.min()) - 1, 0), min(int(cols.max()) + 2, n1)
    return outline(
        f[r0:r1, c0:c1], xg[r0:r1, c0:c1], yg[r0:r1, c0:c1], level, step, spec
    )


def outline(f: np.ndarray, xg, yg, level: float, step: float, spec: dict):
    """The level set of `f` simplified as the puff's drawn contours are, or None."""
    g = isolines.level_set(f, xg, yg, level)
    if g is None:
        return None
    return g.simplify(
        step * float(spec["contour_simplify_cells"]), preserve_topology=True
    )


def reached(run: StepRun, minute: int, spec: dict):
    """Where the level has been reached by `minute` (plane metres), or None."""
    peak = run.reached_fields.get(minute)
    if peak is None or not np.any(peak >= run.level):
        return None
    # the isoline of the running maximum at the level: interpolated, as every
    # modelled outline is (contours.level_set), never the reached cells
    return outline(peak, run.xg, run.yg, run.level, run.step_m, spec)


def bands(run: StepRun, steps: list[int], spec: dict) -> list[tuple[int, object]]:
    """(minute, the band first reached in the interval ending at that step), in step
    order, for the steps up to the run's end. A band with no area is left out."""
    out, prev = [], None
    for m in [s for s in steps if s <= run.end_minute]:
        cur = reached(run, m, spec)
        if cur is None:
            continue
        band = cur if prev is None else shapely.make_valid(cur.difference(prev))
        if not band.is_empty and band.area > 0:
            out.append((m, band))
        prev = cur if prev is None else shapely.make_valid(unary_union([prev, cur]))
    return out


def open_ends(geom, half_width: float, step: float):
    """The parts of `geom`'s boundary on the grid's edge (where the run stopped, not the
    cloud): a MultiLineString to leave undrawn, or None when the outline closes."""
    if geom is None:
        return None
    frame = shapely.box(-half_width, -half_width, half_width, half_width).exterior
    cut = geom.boundary.intersection(frame.buffer(step * 0.75))
    return None if cut.is_empty or cut.length == 0 else cut


# ── the wind-direction uncertainty lines (ADDENDA 03 to 05; for_hb157.md section 2) ──


def u3_from_u10(
    u10_ms: float, cls: str, power_n: dict, ref_h: float, to_h: float
) -> float:
    """The wind at `to_h` (3 m) from the wind at `ref_h` (10 m) by ALOHA's power law,
    U(z) = U(ref) (z / ref)^n with n by stability class (`noaa-aloha-technical-
    documentation` p. 49, "ALOHA uses a power function (Brutsaert 1982)"; n from the
    class table the source term already holds, p. 22)."""
    if cls not in power_n:
        raise TimelineError(f"no power-law exponent for class {cls!r}")
    return float(u10_ms) * (float(to_h) / float(ref_h)) ** float(power_n[cls])


def confidence_angle(u3_ms: float, cls: str, coeffs: dict, seconds: float) -> dict:
    """alpha = arctan(2 sigma_y(x5) / x5), x5 = `seconds` x U3 (300 s: "a distance 5
    minutes downwind of the source"), sigma_y(x) = s_y1 x / sqrt(1 + s_y2 x) with Table
    13's rural coefficients (Tech. Doc. section 4.5.3, p. 57; section 4.3.1, pp. 43 to
    45). That sigma_y is read at x5 is HB-160's reading of the sentence and its
    denominator."""
    if cls not in coeffs:
        raise TimelineError(f"no Table 13 coefficients for class {cls!r}")
    if u3_ms <= 0:
        raise TimelineError("the uncertainty lines need a wind above 0")
    s1, s2 = (float(v) for v in coeffs[cls])
    x5 = float(seconds) * float(u3_ms)
    sy = s1 * x5 / math.sqrt(1.0 + s2 * x5)
    return {
        "alpha_deg": math.degrees(math.atan(2.0 * sy / x5)),
        "x5_m": x5,
        "sigma_y_m": sy,
        "u3_ms": float(u3_ms),
        "class": cls,
    }


def rotated(geom, alpha_deg: float) -> tuple:
    """The outline rotated about the source (the plane's origin) by +alpha and -alpha:
    "The axis of the threat zone is rotated through an angle on either side of the
    nominal wind direction and the contour of the rotated threat zone is drawn"."""
    return (
        affinity.rotate(geom, alpha_deg, origin=(0.0, 0.0)),
        affinity.rotate(geom, -alpha_deg, origin=(0.0, 0.0)),
    )


# ── the forecast wind's range and its shift (ADDENDUM-02 items 2 and 3) ──────────────


def _delta(d: float, d0: float) -> float:
    return (float(d) - float(d0) + 180.0) % 360.0 - 180.0


def wind_range(rows: list[dict], hours: list[int]) -> dict | None:
    """The low and high ends of the forecast direction (unwrapped about hour 0's) and
    speed (km/h) over `hours`, or None when fewer than one row is held."""
    use = [r for r in rows if int(r["hour"]) in hours]
    if not use:
        return None
    d0 = float(use[0]["windDirection"])
    deltas = [_delta(r["windDirection"], d0) for r in use]
    kmh = [float(r["windSpeed"]) for r in use]
    return {
        "from_lo": (d0 + min(deltas)) % 360.0,
        "from_hi": (d0 + max(deltas)) % 360.0,
        "width_deg": max(deltas) - min(deltas),
        "kmh_lo": min(kmh),
        "kmh_hi": max(kmh),
        "hours": [int(r["hour"]) for r in use],
    }


def wind_shift(rows: list[dict], hours: list[int], limit_deg: float) -> dict | None:
    """The first hour whose forecast direction is more than `limit_deg` from hour 0's,
    or None."""
    use = sorted(
        (r for r in rows if int(r["hour"]) in hours), key=lambda r: int(r["hour"])
    )
    if not use:
        return None
    d0 = float(use[0]["windDirection"])
    for r in use[1:]:
        dd = _delta(r["windDirection"], d0)
        if abs(dd) > float(limit_deg):
            return {
                "from_deg": d0,
                "to_deg": float(r["windDirection"]),
                "hour": int(r["hour"]),
                "turn_deg": abs(dd),
            }
    return None
