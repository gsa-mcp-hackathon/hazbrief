"""Which engine a release is modelled with: dense, passive or not determined (HB-163
ADDENDUM-02 item 1; DN-026 section 3).

The criterion is the one the held NOAA technical documentation states for choosing
between its heavy-gas and Gaussian calculations (NOAA Technical Memorandum NOS OR&R 43,
ALOHA 5.4.4 Technical Documentation, November 2013, section 4.4.1, pp. 46 to 47):

    "ALOHA uses the critical Richardson's Number (also called the friction Richardson's
    Number), Ric, as the criterion for distinguishing between passive or non-passive
    dispersion. When Ric is less than 1, ALOHA considers the gas to be passive"

    Ri_c = H * g_hat / U*^2,   g_hat = g (rho - rho_a) / rho_a

with H the characteristic dimension of the source:

- a continuous or semi-continuous source other than a puddle:
  H = sqrt(E pi / (4 rho U10));
- a puddle: H = E / (rho U10 D), D the puddle's diameter;
- an instantaneous release: H = V0 / A0, V0 the release's volume and A0 the source's
  area.

A release the source term floors to one minute (computed shorter than a minute,
`source_term._summary`) is ALOHA's "instantaneous" release: ALOHA models it as "a single
one-minute steady-state release" (section 4.3, printed p. 41) at its mass over that
minute. It is classed by the continuous form at that one-minute rate (HB-206, HBD-464;
docs/evidence/hb206/protocol.md section 2): no held page says which form ALOHA applies
to a tank's release its averaging has floored, the instantaneous form needs a source
area a jet does not have (a tank's source is a point source, section 4.4.3, printed
p. 48), and on the field trial HB-206 runs (docs/evidence/hb206/prepared.json) both
forms class the release dense unless the source were a layer under 0.1 mm over more
than 5 km2. The mass is unchanged; the class
records that the release was floored and its computed duration.

U* is the friction velocity from the surface-layer profile the same document states
(section 4.2, pp. 40 to 41): U(z) = (U*/k) [ln((z + z0)/z0) - psi(z/L)], k = 0.4, the
Obukhov length L from the Pasquill class and z0 (its table), and psi the
Businger-Paulson functions it prints. Two readings of the printed equation are stated
assumptions (DN-026 section 3.2): the profile's sign is the standard one (with the
printed "+" the friction velocity at a given wind would grow as the air grows more
stable), and the unstable branch's last term is pi/2 (the only value with psi(0) = 0,
which the same equation states).

The rule takes the release as computed: the source term's rate, the density of what is
released at its release temperature (a two-phase release by its liquid and vapour
fractions), the wind at 10 m, the roughness and the stability class. The material's
name alone never decides. A missing input is "not determined", with the input named.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

DENSE = "dense"
PASSIVE = "passive"
NOT_DETERMINED = "not_determined"


@dataclass(frozen=True)
class Release:
    """What the rule reads. `kind`: "continuous", "puddle" or "instantaneous" (a release
    floored to one minute, its rate the mass over that minute)."""

    kind: str | None
    rate_kg_s: float | None
    mw_kg_mol: float | None
    temperature_k: float | None
    liquid_fraction: float = 0.0
    liquid_density_kg_m3: float | None = None
    puddle_diameter_m: float | None = None
    air_temperature_k: float | None = None
    wind_10m_ms: float | None = None
    z0_m: float | None = None
    stability: str | None = None
    basis: str = ""
    sources: tuple[str, ...] = field(default_factory=tuple)
    # the source term's computed duration (s) of a release floored to one minute
    floored_from_s: float | None = None


def _missing(r: Release) -> list[str]:
    need = {
        "the release's rate": r.rate_kg_s,
        "the material's molecular weight": r.mw_kg_mol,
        "the release temperature": r.temperature_k,
        "the air temperature": r.air_temperature_k,
        "the wind at 10 m": r.wind_10m_ms,
        "the ground roughness": r.z0_m,
        "the stability class": r.stability,
    }
    out = [k for k, v in need.items() if v is None]
    if r.kind not in ("continuous", "puddle", "instantaneous"):
        out.append("the kind of source")
    if r.kind == "puddle" and not r.puddle_diameter_m:
        out.append("the puddle's diameter")
    if r.liquid_fraction and not r.liquid_density_kg_m3:
        out.append("the liquid's density")
    if r.wind_10m_ms is not None and r.wind_10m_ms <= 0:
        out.append("a wind above 0 m/s")
    return out


def gas_density(mw_kg_mol: float, t_k: float, p_pa: float, r_gas: float) -> float:
    """The ideal-gas density (kg/m3)."""
    return p_pa * mw_kg_mol / (r_gas * t_k)


def release_density(r: Release, cfg: dict) -> float:
    """The density of what is released at its release temperature: the vapour, or a
    two-phase mixture by mass fractions (its specific volume the fractions' sum)."""
    k = cfg["constants"]
    rho_v = gas_density(
        r.mw_kg_mol, r.temperature_k, k["ambient_pressure_pa"], k["gas_constant"]
    )
    x = float(r.liquid_fraction or 0.0)
    if x <= 0.0:
        return rho_v
    return 1.0 / ((1.0 - x) / rho_v + x / float(r.liquid_density_kg_m3))


def obukhov_length(stability: str, z0_m: float, table: dict) -> float:
    """L (m) from the class and z0, the held table (section 4.2, p. 40); infinite for
    class D."""
    row = table[stability]
    if row is None:
        return math.inf
    a, b = (float(v) for v in row)
    return a * z0_m**b


def psi(zeta: float, stable_coeff: float, unstable_coeff: float) -> float:
    """The stability function of the held profile (section 4.2, p. 41)."""
    if zeta > 0:
        return -stable_coeff * zeta
    if zeta == 0:
        return 0.0
    a = (1.0 - unstable_coeff * zeta) ** 0.25
    return (
        2.0 * math.log((1.0 + a) / 2.0)
        + math.log((1.0 + a * a) / 2.0)
        - 2.0 * math.atan(a)
        + math.pi / 2.0
    )


def friction_velocity(u_ms: float, z_m: float, z0_m: float, stability: str, cfg):
    """U* (m/s) from the wind at `z_m`, by the held profile."""
    p = cfg["profile"]
    big_l = obukhov_length(stability, z0_m, p["obukhov"])
    zeta = 0.0 if math.isinf(big_l) else z_m / big_l
    denom = math.log((z_m + z0_m) / z0_m) - psi(
        zeta, float(p["stable_coeff"]), float(p["unstable_coeff"])
    )
    return float(p["von_karman"]) * u_ms / denom, big_l


def classify(r: Release, cfg: dict) -> dict:
    """{class, ri_c, threshold, rho, rho_a, h_m, u_star, obukhov_m, missing, basis}:
    the release's class by the held criterion, with every number it rests on."""
    out = {
        "class": NOT_DETERMINED,
        "ri_c": None,
        "threshold": float(cfg["threshold"]),
        "rho_kg_m3": None,
        "rho_air_kg_m3": None,
        "h_m": None,
        "u_star_ms": None,
        "obukhov_m": None,
        "kind": r.kind,
        "rate_kg_s": r.rate_kg_s,
        "wind_10m_ms": r.wind_10m_ms,
        "stability_class": r.stability,
        "z0_m": r.z0_m,
        "basis": r.basis,
        "sources": list(r.sources),
        "missing": _missing(r),
    }
    if r.kind == "instantaneous":
        # HBD-464: a release floored to one minute takes the continuous form. Only such
        # a release carries these keys: the class's dict is part of the puff channel's
        # run record, whose hash every committed brief prints.
        out.update(form="continuous", floored=True, floored_from_s=r.floored_from_s)
    if out["missing"]:
        return out
    k = cfg["constants"]
    rho = release_density(r, cfg)
    rho_a = gas_density(
        float(k["air_molar_mass_kg_mol"]),
        float(r.air_temperature_k),
        float(k["ambient_pressure_pa"]),
        float(k["gas_constant"]),
    )
    u10 = float(r.wind_10m_ms)
    if r.kind == "puddle":
        h = r.rate_kg_s / (rho * u10 * float(r.puddle_diameter_m))
    else:
        h = math.sqrt(r.rate_kg_s * math.pi / (4.0 * rho * u10))
    g_hat = float(k["gravity_m_s2"]) * (rho - rho_a) / rho_a
    u_star, big_l = friction_velocity(
        u10, float(cfg["profile"]["wind_height_m"]), float(r.z0_m), r.stability, cfg
    )
    ri = h * g_hat / (u_star * u_star)
    out.update(
        ri_c=ri,
        rho_kg_m3=rho,
        rho_air_kg_m3=rho_a,
        h_m=h,
        u_star_ms=u_star,
        obukhov_m=None if math.isinf(big_l) else big_l,
        **{"class": PASSIVE if ri < out["threshold"] else DENSE},
    )
    return out
