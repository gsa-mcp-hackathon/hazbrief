"""The first-order passive Gaussian puff (DN-018 sections 4 and 5; HB-67).

**The equation.** Jia, Fish, Daniels, Sprinkle and Hammerling, "A fast and lightweight
implementation of the Gaussian puff model for near-field atmospheric transport of trace
gasses", Scientific Reports 15:18710 (2025), held as `jia2025-fast-gaussian-puff`,
section "The Gaussian puff model": a continuous release is a series of discrete puffs,
puff p carrying mass m_p and the wind at its creation, and the concentration of one
puff is their Eq. (2),

    c_p(x, y, z, t) = m_p / ((2 pi)^(3/2) sigma_y^2 sigma_z)
                      exp(-((x - u t)^2 + y^2) / (2 sigma_y^2))
                      [exp(-(z - z0)^2 / (2 sigma_z^2))
                       + exp(-(z + z0)^2 / (2 sigma_z^2))]

with x along the puff's own downwind direction, written out the same way in the held
implementation's README (`fastgaussianpuff-repo`, commit 56f84e77). The field is the sum
over the puffs alive at t, their Eq. (3).

**The wind a puff travels on (DN-025; HB-162R).** The paper holds the wind constant for
a single puff, "reasonable in practice, as each puff persists for only a few seconds to
minutes"; hazbrief's puffs live up to six hours, so here a puff takes the wind of its
creation and is then carried on the wind of every hour it travels, as SCIPUFF advances
each puff's centroid on the wind of each time step (SCICHEM 3.4 Technical
Documentation, sections 4.1 and 9.4). The wind is `HourlyWind`: piecewise on each
forecast hour, the NWS gridpoint value held over its interval. The centre is the sum of
each hour's wind vector times the time spent in it; the spread is read at the distance
travelled along that path (the paper: "use the location of the puff's center to compute
the dispersion parameters ... at each point in the puff's path"). On a constant wind
this is the paper's own rule: centre u t along the wind, spread at u t.

**Why NumPy and not the held C++ core** (HB-67 step 1; DN-018 section 4 item 3). The
core builds in the image's toolchain (HB-65 RESULT section 5), but it cannot be given
the stability class: `stabilityClassifier` (`src/CGaussianPuff.cpp`, line 426) assigns
its own from the wind speed and the clock hour, so HB-57's class by EPA's Turner key
could not reach it; and its emission runs at one rate for the whole simulation (line
120), so "the full quantity over ten minutes", observed for sixty, cannot be put to it.
This module computes the same equation on the same Pasquill-Gifford curves (ISC3 Volume
II Tables 1-1 and 1-2, the coefficients the core also uses), with the class given.
HB-68 checks it against the core on inputs where the core's own class is the one given.

**Sigma.** From `packs/sigma_curves.json` by class and the distance the puff's centre
has travelled (the paper: "use the location of the puff's center to compute the
dispersion parameters"), x in km: sigma_y = 465.11628 x tan(0.017453293 (c - d ln x)),
sigma_z = a x^b capped at 5,000 m. A puff that has not moved contributes nothing (the
core's `x <= 0` rule).

Pure: every function reads only its arguments.
"""

from __future__ import annotations

import bisect
import dataclasses
import math
import time
from dataclasses import dataclass

import numpy as np
import shapely
from shapely.geometry import box
from shapely.ops import unary_union

_TWO_PI_3_2 = (2.0 * math.pi) ** 1.5


class PuffError(RuntimeError):
    """An input the equation cannot take (a class the pack lacks, a bad grid)."""


class HourlyWind:
    """A wind held piecewise over consecutive intervals: interval k starts at
    `starts_s[k]` seconds after the run's start and holds `speeds_ms[k]` from
    `froms_deg[k]` (the direction it blows from, degrees clockwise from north) until the
    next start; the first holds before it and the last after it. Called with a time it
    gives (speed, from), as a wind function does; `carry(t0, t1)` gives the
    displacement (east, north, metres) and the distance travelled along the path
    between the two times (DN-025 section 3 items 1 and 3)."""

    def __init__(self, starts_s, speeds_ms, froms_deg):
        starts = [float(s) for s in starts_s]
        if not starts or not (len(starts) == len(speeds_ms) == len(froms_deg)):
            raise PuffError("an hourly wind needs one speed and direction per start")
        if any(b <= a for a, b in zip(starts, starts[1:])):
            raise PuffError("an hourly wind's starts must increase")
        self.starts_s = starts
        self.speeds_ms = [float(v) for v in speeds_ms]
        self.froms_deg = [float(v) for v in froms_deg]
        # the velocity each interval carries a puff at (toward = from + 180 degrees)
        self._vx = [
            s * math.sin(math.radians(f + 180.0))
            for s, f in zip(self.speeds_ms, self.froms_deg)
        ]
        self._vy = [
            s * math.cos(math.radians(f + 180.0))
            for s, f in zip(self.speeds_ms, self.froms_deg)
        ]

    def _index(self, t_s: float) -> int:
        """The interval holding `t_s`: the last start at or before it, else the
        first."""
        return max(bisect.bisect_right(self.starts_s, t_s) - 1, 0)

    def __call__(self, t_s: float) -> tuple[float, float]:
        k = self._index(t_s)
        return self.speeds_ms[k], self.froms_deg[k]

    def carry(self, t0_s: float, t1_s: float) -> tuple[float, float, float]:
        """(east, north, along the path) metres travelled from `t0_s` to `t1_s`."""
        if t1_s <= t0_s:
            return 0.0, 0.0, 0.0
        x = y = d = 0.0
        k = self._index(t0_s)
        t = t0_s
        while t < t1_s:
            end = self.starts_s[k + 1] if k + 1 < len(self.starts_s) else math.inf
            dt = min(end, t1_s) - t
            x += self._vx[k] * dt
            y += self._vy[k] * dt
            d += self.speeds_ms[k] * dt
            t += dt
            k += 1
        return x, y, d


def steady(speed_ms: float, from_deg: float) -> HourlyWind:
    """One wind for every time (a stated or observed wind; HB-70 step 3)."""
    return HourlyWind([0.0], [speed_ms], [from_deg])


@dataclass(frozen=True)
class Puff:
    """One puff: released `t_s` seconds after the run starts, carrying `mass_kg` and
    the wind at its creation (`speed_ms`, and the direction it travels toward, degrees
    clockwise from north), then carried on `wind` (DN-025): the hourly wind every later
    hour moves it on. With no `wind` it keeps the wind of its creation."""

    t_s: float
    mass_kg: float
    speed_ms: float
    toward_deg: float
    wind: HourlyWind | None = dataclasses.field(default=None, compare=False, repr=False)


def centre(p: Puff, t_s: float) -> tuple[float, float, float]:
    """Puff `p`'s centre (east, north, metres from the spill) at `t_s`, and the distance
    it has travelled along its path, which its spread is read at (DN-025 section 3
    items 1 and 3)."""
    age = t_s - p.t_s
    if age <= 0:
        return 0.0, 0.0, 0.0
    if p.wind is None:
        d = p.speed_ms * age
        th = math.radians(p.toward_deg)
        return d * math.sin(th), d * math.cos(th), d
    return p.wind.carry(p.t_s, t_s)


def sigmas(curves: dict, cls: str, x_m) -> tuple[np.ndarray, np.ndarray]:
    """sigma_y and sigma_z (m) for class `cls` at travelled distances `x_m` (m), from
    the sigma_curves pack's `data`. A distance at or below zero gives NaN (no
    contribution)."""
    if cls not in curves["classes"]:
        raise PuffError(f"no sigma curves for stability class {cls!r}")
    c = curves["classes"][cls]
    x = np.asarray(x_m, dtype=float) / 1000.0
    pos = x > 0
    xs = np.where(pos, x, 1.0)
    sy_scale = curves["sigma_y_scale"]["value"]
    th_scale = curves["theta_scale"]["value"]
    theta = th_scale * (c["sigma_y"]["c"] - c["sigma_y"]["d"] * np.log(xs))
    sy = sy_scale * xs * np.tan(theta)
    sz = np.full_like(xs, np.nan)
    lower = 0.0
    for band in c["sigma_z"]:
        upper = band["x_max_km"]
        sel = (xs > lower) & (xs <= upper) if upper is not None else xs > lower
        if band["fixed_m"] is not None:
            sz = np.where(sel, band["fixed_m"], sz)
        else:
            sz = np.where(sel, band["a"] * xs ** band["b"], sz)
        if upper is not None:
            lower = upper
    sz = np.minimum(sz, curves["sigma_z_cap_m"]["value"])
    return np.where(pos, sy, np.nan), np.where(pos, sz, np.nan)


def release(
    mass_kg: float,
    duration_s: float,
    puff_dt_s: float,
    wind,
    *,
    start_s: float = 0.0,
) -> list[Puff]:
    """A constant-rate release of `mass_kg` over `duration_s`, one puff every
    `puff_dt_s`, each with `wind(t)`'s (speed m/s, direction from, degrees) at its
    creation; t in seconds from the window's start, the release starting at
    `start_s`. A `HourlyWind` then carries every puff on each later hour's wind
    (DN-025); any other wind function is held at each puff's creation (a wind given as
    a function of time alone has no hours to carry a puff through)."""
    if duration_s <= 0 or puff_dt_s <= 0:
        raise PuffError("a release needs a positive duration and puff interval")
    n = max(1, int(round(duration_s / puff_dt_s)))
    m = mass_kg / n
    carry = wind if isinstance(wind, HourlyWind) else None
    out = []
    for i in range(n):
        t = start_s + i * puff_dt_s
        speed, frm = wind(t)
        out.append(Puff(t, m, float(speed), (float(frm) + 180.0) % 360.0, carry))
    return out


def field(
    puffs: list[Puff],
    t_s: float,
    xg: np.ndarray,
    yg: np.ndarray,
    curves: dict,
    cls: str,
    *,
    z_m: float,
    z0_m: float,
    lifetime_s: float,
    low_wind_ms: float,
    deadline: float | None = None,
) -> tuple[np.ndarray, int]:
    """Eq. (3): the concentration (kg/m3) at time `t_s` on the grid `xg`, `yg` (metres
    east and north of the spill, at height `z_m`), summed over the puffs released before
    `t_s` and alive (`lifetime_s`). A puff whose wind is below `low_wind_ms` is not
    emitted, as the held implementation's `skip_low_wind` does ("the model is unreliable
    in low wind speeds (< 0.5m/s) and doesn't run if there is a wind speed of 0 m/s",
    its README). `deadline`: a `time.monotonic()` instant past which it stops with
    PuffError (the channel's own timeout, DN-018 section 8, C3). Returns the field and
    the number of puffs skipped for low wind."""
    c = np.zeros_like(xg, dtype=float)
    skipped = 0
    for p in puffs:
        if deadline is not None and time.monotonic() > deadline:
            raise PuffError("timed out")
        age = t_s - p.t_s
        if age <= 0 or age > lifetime_s:
            continue
        if p.speed_ms < low_wind_ms:
            skipped += 1
            continue
        cx, cy, d = centre(p, t_s)
        sy, sz = sigmas(curves, cls, [d])
        sy, sz = float(sy[0]), float(sz[0])
        if not (sy > 0 and sz > 0):
            continue
        r2 = (xg - cx) ** 2 + (yg - cy) ** 2
        vert = math.exp(-((z_m - z0_m) ** 2) / (2 * sz * sz)) + math.exp(
            -((z_m + z0_m) ** 2) / (2 * sz * sz)
        )
        c += (
            p.mass_kg
            / (_TWO_PI_3_2 * sy * sy * sz)
            * np.exp(-r2 / (2 * sy * sy))
            * vert
        )
    return c, skipped


def grid(half_width_m: float, cells: int) -> tuple[np.ndarray, np.ndarray, float]:
    """A square grid of `cells` x `cells` cell centres centred on the spill."""
    if half_width_m <= 0 or cells < 3:
        raise PuffError("a grid needs a positive extent and at least 3 cells a side")
    step = 2.0 * half_width_m / cells
    axis = -half_width_m + step * (np.arange(cells) + 0.5)
    xg, yg = np.meshgrid(axis, axis)
    return xg, yg, step


def contour(c: np.ndarray, xg: np.ndarray, yg: np.ndarray, step: float, level: float):
    """The cells at or above `level` as one (Multi)Polygon in plane metres, or None."""
    rows, cols = np.nonzero(c >= level)
    if rows.size == 0:
        return None
    h = step / 2.0
    cells = [
        box(xg[r, k] - h, yg[r, k] - h, xg[r, k] + h, yg[r, k] + h)
        for r, k in zip(rows, cols)
    ]
    return shapely.make_valid(unary_union(cells))


def extent_m(poly) -> float:
    """The farthest point of a contour from the spill (m)."""
    if poly is None or poly.is_empty:
        return 0.0
    pts = shapely.get_coordinates(poly.boundary)
    return float(np.max(np.hypot(pts[:, 0], pts[:, 1])))


def kg_m3(
    volume_fraction: float, mw_g_mol: float, molar_volume_m3_kmol: float
) -> float:
    """A volume fraction as a mass concentration: fraction x MW / molar volume (MW in
    kg/kmol equals g/mol)."""
    return volume_fraction * mw_g_mol / molar_volume_m3_kmol
