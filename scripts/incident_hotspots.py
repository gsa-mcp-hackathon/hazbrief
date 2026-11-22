"""The incident hotspot method (HB-136R Part B): an equal-area projection, a hexagonal
grid, Getis-Ord Gi* with a permutation test, and a Gaussian kernel density surface.

Each piece is a named method, implemented from its published form, not invented here:

- **Albers equal-area conic on the GRS 80 ellipsoid**, Snyder's equations (J. P. Snyder
  1987, Map Projections: A Working Manual, USGS Professional Paper 1395, pp. 98-103,
  equations 3-12, 14-3 to 14-6, 14-12 to 14-21), with the parameters of the
  conterminous-U.S. Albers grid (EPSG:5070: standard parallels 29.5 and 45.5 N, origin
  23 N 96 W). Equal area matters because a hexagon's count is compared with another's:
  every cell must cover the same ground.
- **Hexagonal grid in axial coordinates** with cube rounding of a point to its cell
  (pointy-top hexagons; the standard construction, e.g. Birch, Oom and Beecham 2007,
  "Rectangular and hexagonal grids used for observation, experiment and simulation in
  ecology", Ecological Modelling 206). A hexagon's six neighbours are all at the same
  distance, which a square's eight are not.
- **Getis-Ord Gi\\*** (Getis and Ord 1992, Geographical Analysis 24(3), DOI
  10.1111/j.1538-4632.1992.tb00261.x; Ord and Getis 1995, Geographical Analysis 27(4),
  DOI 10.1111/j.1538-4632.1995.tb00912.x), the standardised form of Ord and Getis 1995
  with binary weights that include the cell itself. Ord and Getis 1995 is about the
  statistic's distributional issues: with few neighbours and skewed counts the normal
  approximation is poor, so the p-value that classifies a cell is a permutation
  (randomisation) p-value, as PySAL's `esda.G_Local(star=True)` computes it, beside the
  normal one.
- **Kernel density** with a Gaussian kernel and a fixed bandwidth (Silverman 1986,
  Density Estimation for Statistics and Data Analysis, chapter 4), evaluated on a
  regular grid.

No step assigns points to groups: the question is density, not partition (HB-136R step
3). Both Getis-Ord papers are `not_held` rows in corpus/sources.yaml (HB-135; Issue
3f4efb5a), cited by row and DOI as DN-005 allows. The functions here are pure: no file,
no network.
"""

from __future__ import annotations

import math

import numpy as np

# ---- Albers equal-area conic, ellipsoidal (Snyder 1987)


class Albers:
    """Forward and inverse Albers equal-area conic on an ellipsoid (Snyder 1987, pp.
    98-103). Metres, from degrees.
    """

    def __init__(
        self,
        *,
        a: float,
        inv_f: float,
        lat1: float,
        lat2: float,
        lat0: float,
        lon0: float,
    ):
        f = 1.0 / inv_f
        self.a = a
        self.e2 = f * (2 - f)
        self.e = math.sqrt(self.e2)
        self.lon0 = math.radians(lon0)
        m1, m2 = self._m(math.radians(lat1)), self._m(math.radians(lat2))
        q0, q1, q2 = (self._q(math.radians(x)) for x in (lat0, lat1, lat2))
        self.n = (m1 * m1 - m2 * m2) / (q2 - q1)  # 14-14
        self.C = m1 * m1 + self.n * q1  # 14-13
        self.rho0 = a * math.sqrt(self.C - self.n * q0) / self.n  # 14-12a

    def _m(self, phi: float) -> float:  # 14-15
        s = math.sin(phi)
        return math.cos(phi) / math.sqrt(1 - self.e2 * s * s)

    def _q(self, phi):  # 3-12; scalar or array
        s = np.sin(phi)
        e = self.e
        return (1 - self.e2) * (
            s / (1 - self.e2 * s * s)
            - (1 / (2 * e)) * np.log((1 - e * s) / (1 + e * s))
        )

    def forward(self, lon, lat):
        """(x, y) metres for degrees; scalars or arrays."""
        lam = np.radians(np.asarray(lon, dtype=float))
        phi = np.radians(np.asarray(lat, dtype=float))
        rho = self.a * np.sqrt(self.C - self.n * self._q(phi)) / self.n  # 14-12
        theta = self.n * (lam - self.lon0)  # 14-4
        return rho * np.sin(theta), self.rho0 - rho * np.cos(theta)  # 14-1, 14-2

    def inverse(self, x, y):
        """(lon, lat) degrees for metres; scalars or arrays. Latitude by the iteration
        of equation 3-16 to 1e-12 radians.
        """
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        rho = np.hypot(x, self.rho0 - y)  # 14-10
        q = (self.C - (rho * self.n / self.a) ** 2) / self.n  # 14-19
        theta = np.arctan2(x, self.rho0 - y)  # 14-11 (n > 0)
        phi = np.arcsin(np.clip(q / 2, -1, 1))
        e, e2 = self.e, self.e2
        for _ in range(50):
            s = np.sin(phi)
            d = ((1 - e2 * s * s) ** 2 / (2 * np.cos(phi))) * (
                q / (1 - e2)
                - s / (1 - e2 * s * s)
                + (1 / (2 * e)) * np.log((1 - e * s) / (1 + e * s))
            )
            phi = phi + d
            if np.all(np.abs(d) < 1e-12):
                break
        return np.degrees(self.lon0 + theta / self.n), np.degrees(phi)


# ---- the hexagonal grid (pointy-top, axial coordinates)

_SQRT3 = math.sqrt(3.0)


def hex_of(x, y, size: float):
    """The axial (q, r) of the pointy-top hexagon of circumradius `size` holding each
    (x, y); cube rounding. Arrays in, integer arrays out.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    qf = (_SQRT3 / 3 * x - y / 3) / size
    rf = (2 / 3 * y) / size
    sf = -qf - rf
    q, r, s = np.round(qf), np.round(rf), np.round(sf)
    dq, dr, ds = np.abs(q - qf), np.abs(r - rf), np.abs(s - sf)
    fix_q = (dq > dr) & (dq > ds)
    fix_r = ~fix_q & (dr > ds)
    q = np.where(fix_q, -r - s, q)
    r = np.where(fix_r, -q - s, r)
    return q.astype(int), r.astype(int)


def hex_centre(q, r, size: float):
    q = np.asarray(q, dtype=float)
    r = np.asarray(r, dtype=float)
    return size * _SQRT3 * (q + r / 2), size * 1.5 * r


def hex_corners(q: int, r: int, size: float) -> list[tuple[float, float]]:
    """The six corners, anticlockwise from the east-north-east one."""
    cx, cy = hex_centre(q, r, size)
    return [
        (
            float(cx + size * math.cos(math.radians(60 * i - 30))),
            float(cy + size * math.sin(math.radians(60 * i - 30))),
        )
        for i in range(6)
    ]


#: the six axial neighbours of a hexagon
NEIGHBOURS = ((1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1))


def hex_area(size: float) -> float:
    return 1.5 * _SQRT3 * size * size


# ---- Getis-Ord Gi*


def neighbour_index(cells: list[tuple[int, int]]) -> np.ndarray:
    """For each cell, the indices of itself and its domain neighbours, padded with -1:
    the binary Gi* weights, self included (w_ii = 1). A neighbour outside the domain is
    not a zero; it is not in the sum.
    """
    pos = {c: i for i, c in enumerate(cells)}
    out = np.full((len(cells), 7), -1, dtype=int)
    for i, (q, r) in enumerate(cells):
        out[i, 0] = i
        k = 1
        for dq, dr in NEIGHBOURS:
            j = pos.get((q + dq, r + dr))
            if j is not None:
                out[i, k] = j
                k += 1
    return out


def _gi_star_z(x: np.ndarray, nb: np.ndarray) -> np.ndarray:
    """Ord and Getis 1995's standardised Gi*: (sum_j w_ij x_j - xbar W_i) /
    (S sqrt((n S1_i - W_i^2) / (n - 1))), binary weights, self included. `x` may be a
    (k, n) stack of permuted fields."""
    n = x.shape[-1]
    mask = nb >= 0
    w = mask.sum(axis=1).astype(float)  # W_i = S1_i for binary weights
    xpad = np.concatenate([x, np.zeros(x.shape[:-1] + (1,))], axis=-1)
    local = xpad[..., np.where(mask, nb, n)].sum(axis=-1)
    xbar = x.mean(axis=-1, keepdims=True)
    s = np.sqrt((x * x).mean(axis=-1, keepdims=True) - xbar * xbar)
    den = s * np.sqrt((n * w - w * w) / (n - 1))
    with np.errstate(divide="ignore", invalid="ignore"):
        return (local - xbar * w) / den


def gi_star(x, nb: np.ndarray, *, permutations: int, seed: int) -> dict:
    """z (Ord and Getis 1995), the two-sided normal p-value of z, and the one-sided
    upper permutation p-value (p_sim = (1 + #{z_perm >= z}) / (1 + permutations)), the
    field permuted across the domain's cells with a seeded generator. Returned as
    arrays.
    """
    x = np.asarray(x, dtype=float)
    z = _gi_star_z(x, nb)
    rng = np.random.default_rng(seed)
    ge = np.zeros(len(x), dtype=int)
    batch = 100
    done = 0
    while done < permutations:
        k = min(batch, permutations - done)
        perm = np.stack([rng.permutation(x) for _ in range(k)])
        ge += (_gi_star_z(perm, nb) >= z[None, :] - 1e-12).sum(axis=0)
        done += k
    p_norm = np.array([math.erfc(abs(v) / math.sqrt(2)) for v in z])
    return {"z": z, "p_norm": p_norm, "p_sim": (1 + ge) / (1 + permutations)}


def benjamini_hochberg(p: np.ndarray) -> np.ndarray:
    """Benjamini and Hochberg 1995 adjusted p-values (the step-up false discovery
    rate)."""
    p = np.asarray(p, dtype=float)
    n = len(p)
    order = np.argsort(p)
    adj = np.empty(n)
    run = 1.0
    for rank in range(n, 0, -1):
        i = order[rank - 1]
        run = min(run, p[i] * n / rank)
        adj[i] = run
    return adj


# ---- kernel density


def kde_grid(
    px, py, *, bandwidth: float, x0: float, y0: float, step: float, nx: int, ny: int
) -> np.ndarray:
    """A Gaussian kernel density on an (ny, nx) grid of cell centres x0 + (i + 0.5)
    step, y0 + (j + 0.5) step: points per square metre (each kernel integrates to one
    point).
    """
    xs = x0 + (np.arange(nx) + 0.5) * step
    ys = y0 + (np.arange(ny) + 0.5) * step
    out = np.zeros((ny, nx))
    norm = 1.0 / (2 * math.pi * bandwidth * bandwidth)
    for x, y in zip(np.asarray(px, float), np.asarray(py, float)):
        gx = np.exp(-((xs - x) ** 2) / (2 * bandwidth * bandwidth))
        gy = np.exp(-((ys - y) ** 2) / (2 * bandwidth * bandwidth))
        out += norm * np.outer(gy, gx)
    return out
