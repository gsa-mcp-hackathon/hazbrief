"""The source term from the container (DN-020 section 3.1; HB-110).

How much material enters the air, how fast and for how long, computed from the
container, the stated quantity, the material's properties and the weather by the
methods NOAA's ALOHA documents. Two release models:

- **two-phase flashing release** (`two_phase_release`): a gas liquefied under pressure
  leaves a hole as a superheated liquid that flashes. ALOHA Technical Documentation
  (`noaa-aloha-technical-documentation`, NOAA TM NOS OR&R 43, November 2013)
  section 3.4: the Homogeneous Nonequilibrium Model for the mass flux (3.4.5, printed
  p. 27), the tank's evaporative cooling (3.4.1, p. 22), a head-space gas release once
  the liquid is below the hole (3.4.6, pp. 28 to 30), the unvaporised liquid carried
  as an aerosol with no rain-out (p. 28) and the flashed fraction from the enthalpy
  balance (section 6.3.2, p. 68);
- **evaporating pool** (`pool_release`): a liquid at or below its boiling point
  spreads (Briscoe and Shaw, section 3.4.4.2, p. 26) and evaporates, by Brighton's
  mass transfer model below the boiling point (section 3.3.1, pp. 12 to 15) and by
  the energy balance at it (sections 3.3.2 and 3.3.3, pp. 16 to 21). A tank of
  non-boiling liquid feeding the pool through a hole is `liquid_tank_drain`
  (section 3.4.4.1, Bernoulli's equation, p. 25).

`source_term` routes a scenario by container class and material state (DN-020's
table; `docs/evidence/hb124/source_terms.tsv`) and returns `(result, None)` or
`(None, reason)`: the reason is DN-020 ADDENDUM-02 item 4's "not applicable" (the
chemistry) or "not available" (an input the pack or the scenario does not hold).

Every constant the methods use is read from `weather.source_term.constants` in
`orchestrator.yaml`, each beside its held quote and page (tests verify each quote on
its page); nothing here is a number from memory. Every output carries its inputs, each
material value with its pack tier (`source_tier`) and as-printed text, and the
method's pages. Pure functions: no I/O, no network, no clock.

What the methods here leave out of ALOHA, each said on the result's `omitted` lines:
the tank-wall heat flux (ALOHA states a wall of 2 cm steel and 10 cm foam but no
conductivity), the DIERS swelling test for a head-space hole (section 3.4.3), the
solar and longwave terms when the scenario gives no sky cover, solar altitude or
humidity, and the finite-difference ground model (the error-function solution the
documentation names for a constant puddle temperature is used instead).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

# ── inputs ────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AntoineRow:
    """One NIST Antoine row: log10(P / bar) = A - B / (T + C), T in K, valid on
    [t_min_k, t_max_k]."""

    t_min_k: float
    t_max_k: float
    a: float
    b: float
    c: float
    source: str


@dataclass(frozen=True)
class Value:
    """A material value as the source term uses it, with what the label prints."""

    name: str
    value: float
    unit: str
    tier: str | None
    as_printed: str | None
    source: str
    temperature_k: float | None = None


@dataclass(frozen=True)
class Material:
    """The properties a source term reads, SI per mole where the pack is per mole.

    `saturation` is either the pack's Antoine rows or, for a worked example that
    prints a vapour pressure at one temperature and the boiling point, the
    Clausius-Clapeyron form ALOHA prints (technical documentation p. 68) through those
    two points (`clausius`: (T_B, dH_v)). `vapour_cp_j_mol_k` is optional: only the
    head-space gas stage reads it."""

    name: str
    un: str | None
    mw_kg_mol: float
    tb_k: float
    hv_j_mol: float
    cpl_j_mol_k: float
    rhol_kg_m3: float
    antoine: tuple[AntoineRow, ...] = ()
    clausius: tuple[float, float] | None = None
    vapour_cp_j_mol_k: float | None = None
    tc_k: float | None = None
    values: tuple[Value, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def hv_j_kg(self) -> float:
        return self.hv_j_mol / self.mw_kg_mol

    @property
    def cpl_j_kg_k(self) -> float:
        return self.cpl_j_mol_k / self.mw_kg_mol


@dataclass(frozen=True)
class Tank:
    """The container's geometry when it is known (a worked example states it). A
    fixture states only a container class: `kind` None means the geometry is not
    stated, the hole is at the bottom and the liquid head is not added."""

    kind: str | None = None  # "horizontal_cylinder" | "vertical_cylinder" | None
    diameter_m: float | None = None
    length_m: float | None = None
    hole_bottom_m: float = 0.0
    label: str = "container geometry not stated"


@dataclass(frozen=True)
class Hole:
    area_m2: float
    kind: str  # "hole" | "short_pipe"
    width_m: float  # the diameter of a round hole, or sqrt(area) of a rectangular one
    height_m: float  # the hole's vertical extent
    label: str
    source: str


@dataclass(frozen=True)
class Storage:
    temperature_k: float
    source: str


@dataclass(frozen=True)
class Ambient:
    """The weather the source term reads. `cloud_tenths`, `solar_altitude_deg` and
    `rh_pct` are optional: a missing one leaves its flux out, and the result says so."""

    pressure_pa: float
    temperature_k: float
    wind_ms: float
    wind_height_m: float
    stability: str
    z0_m: float
    sources: tuple[str, ...] = ()
    cloud_tenths: float | None = None
    solar_altitude_deg: float | None = None
    rh_pct: float | None = None


@dataclass(frozen=True)
class Ground:
    kind: str  # a Table 9 key or "water"
    temperature_k: float
    source: str


class SourceTermError(ValueError):
    """An input the method cannot take (a programming error at the caller, not a
    scenario's missing data: those are the `(None, reason)` returns)."""


# ── the constants, from their quotes ──────────────────────────────────────────────────


def constants(spec: dict) -> dict[str, Any]:
    """`weather.source_term.constants` as name -> value. Each entry is
    {value, doc, page, quote}; a table entry carries `rows` instead of `value`."""
    out: dict[str, Any] = {}
    for name, entry in (spec.get("constants") or {}).items():
        if "rows" in entry:
            out[name] = entry["rows"]
        else:
            out[name] = entry["value"]
    return out


# ── thermodynamics ────────────────────────────────────────────────────────────────────


def antoine_row(material: Material, t_k: float) -> AntoineRow | None:
    """The Antoine row whose range holds `t_k`; of several, the narrowest. None when
    none does: a fit is never extrapolated."""
    inside = [r for r in material.antoine if r.t_min_k <= t_k <= r.t_max_k]
    if not inside:
        return None
    return min(inside, key=lambda r: (r.t_max_k - r.t_min_k, r.t_min_k))


def p_sat_pa(material: Material, t_k: float, k: dict) -> float | None:
    """Saturation pressure in Pa at `t_k`, or None outside every Antoine row."""
    if material.clausius is not None:
        tb, hv = material.clausius
        r = k["gas_constant_j_mol_k"]
        return k["clausius_p0_pa"] * math.exp(-(hv / r) * (1.0 / t_k - 1.0 / tb))
    row = antoine_row(material, t_k)
    if row is None:
        return None
    return 10.0 ** (row.a - row.b / (t_k + row.c)) * k["pa_per_bar"]


def gas_density(material: Material, p_pa: float, t_k: float, k: dict) -> float:
    """Ideal-gas vapour density, kg/m3."""
    return p_pa * material.mw_kg_mol / (k["gas_constant_j_mol_k"] * t_k)


def flashed_fraction(material: Material, t_k: float) -> float:
    """f = Cp (T - Tb) / dHv, the isenthalpic flash (technical documentation section
    6.3.2, p. 68), bounded to [0, 1]."""
    f = material.cpl_j_mol_k * (t_k - material.tb_k) / material.hv_j_mol
    return min(max(f, 0.0), 1.0)


# ── tank geometry ─────────────────────────────────────────────────────────────────────


def _segment_area(r: float, h: float) -> float:
    """The area of a circle of radius r below a chord at height h from its bottom."""
    h = min(max(h, 0.0), 2.0 * r)
    return r * r * math.acos((r - h) / r) - (r - h) * math.sqrt(
        max(2 * r * h - h * h, 0.0)
    )


def tank_volume_m3(tank: Tank) -> float | None:
    if tank.kind is None:
        return None
    r = tank.diameter_m / 2.0
    return math.pi * r * r * tank.length_m


def liquid_height_m(tank: Tank, volume_m3: float) -> float | None:
    """The liquid's depth for a liquid volume (bisection on the segment area for a
    horizontal cylinder)."""
    if tank.kind is None:
        return None
    r = tank.diameter_m / 2.0
    if tank.kind == "vertical_cylinder":
        return volume_m3 / (math.pi * r * r)
    if tank.kind != "horizontal_cylinder":
        raise SourceTermError(f"unknown tank kind {tank.kind!r}")
    target = volume_m3 / tank.length_m
    lo, hi = 0.0, 2.0 * r
    for _ in range(80):
        mid = (lo + hi) / 2.0
        if _segment_area(r, mid) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


# ── rates over time ───────────────────────────────────────────────────────────────────


def _summary(
    times: list[float], rates: list[float], dt: float, window_s: float
) -> dict:
    """The release's rates: initial, the largest average over any `window_s` (ALOHA
    averages its time steps into steps of at least one minute), and the mean over the
    duration. A release shorter than one minute is ALOHA's instantaneous release: "the
    shortest source duration allowed in ALOHA is one minute" (technical documentation
    p. 11), so its duration is one minute and its rates are its mass over that
    minute."""
    n = max(int(round(window_s / dt)), 1)
    best, run = 0.0, 0.0
    for i, q in enumerate(rates):
        run += q
        if i >= n:
            run -= rates[i - n]
        best = max(best, run / n)
    computed = times[-1] + dt if times else 0.0
    duration = max(computed, window_s) if times else 0.0
    total = sum(rates) * dt
    return {
        "initial_rate_kg_s": rates[0] if rates else 0.0,
        "max_average_rate_kg_s": best,
        "mean_rate_kg_s": total / duration if duration else 0.0,
        "released_kg": total,
        "duration_s": duration,
        "computed_duration_s": computed,
        "instantaneous": computed < window_s,
    }


# ── the two-phase flashing release (section 3.4.5) ────────────────────────────────────


def hne_mass_flux(
    material: Material,
    t_k: float,
    dp_pa: float,
    pipe_m: float,
    k: dict,
    p_tank_pa: float,
) -> float:
    """G, kg/(m2 s), by the Homogeneous Nonequilibrium Model (p. 27):

        G = Lc / (vg - vl) (N cP T)^-1/2,
        N = Lc^2 vl / (2 dP Cdis^2 (vg - vl)^2 T cP) + l / le.

    At l = 0 it is Bernoulli's G = Cdis (2 dP rho_l)^1/2 exactly. `p_tank_pa` gives
    the vapour's specific volume at the tank's pressure."""
    lc = material.hv_j_kg
    cp = material.cpl_j_kg_k
    vl = 1.0 / material.rhol_kg_m3
    vg = 1.0 / gas_density(material, p_tank_pa, t_k, k)
    cd = k["discharge_coefficient"]
    n = (
        lc * lc * vl / (2.0 * dp_pa * cd * cd * (vg - vl) ** 2 * t_k * cp)
        + pipe_m / k["hne_le_m"]
    )
    return lc / (vg - vl) / math.sqrt(n * cp * t_k)


def _pipe_flux(material, t_k, dp_pa, hole: Hole, k, p_tank_pa) -> tuple[float, str]:
    """The flux through the opening, with ALOHA's large-pipe rule (p. 28): over 1 m
    Bernoulli; between 0.1 and 1 m a straight-line interpolation in diameter between
    the HNE and Bernoulli."""
    bern = k["discharge_coefficient"] * math.sqrt(2.0 * dp_pa * material.rhol_kg_m3)
    if hole.kind == "hole":
        return bern, "a hole: the HNE with l = 0, which is Bernoulli's equation (p. 28)"
    length = k["short_pipe_m"]
    hne = hne_mass_flux(material, t_k, dp_pa, length, k, p_tank_pa)
    d = hole.width_m
    lo, hi = k["pipe_interpolation_m"]
    if d >= hi:
        return bern, f"a short pipe over {hi:g} m across: Bernoulli (p. 28)"
    if d > lo:
        w = (d - lo) / (hi - lo)
        return (1 - w) * hne + w * bern, (
            f"a short pipe {d:.2f} m across: interpolated between the HNE and "
            "Bernoulli (p. 28)"
        )
    return hne, f"a short pipe ({length:g} m): the HNE (p. 27)"


def _gas_flow(material, t_k, p_pa, hole: Hole, tank: Tank, k) -> tuple[float, str]:
    """Head-space gas through the hole (section 3.4.6, pp. 28 to 30): choked when
    Pa / PT <= Rc, the big-hole or small-hole critical ratio by the ratio of hole to
    tank diameter."""
    cpv = material.vapour_cp_j_mol_k
    r = k["gas_constant_j_mol_k"]
    gamma = cpv / (cpv - r)
    pa = k["_ambient_pa"]
    rho = gas_density(material, p_pa, t_k, k)
    beta = hole.width_m / tank.diameter_m
    if beta > k["big_hole_ratio"]:
        rc = (2.0 / (gamma + 1.0)) ** (gamma / (gamma - 1.0))
    else:
        # Rc^((1 - g)/g) + ((g - 1)/2) beta^4 Rc^(2/g) = (g + 1)/2, solved for Rc
        def f(x):
            return (
                x ** ((1 - gamma) / gamma)
                + (gamma - 1) / 2 * beta**4 * x ** (2 / gamma)
                - (gamma + 1) / 2
            )

        lo, hi = 1e-6, 1.0
        for _ in range(100):
            mid = (lo + hi) / 2
            if f(mid) > 0:
                lo = mid
            else:
                hi = mid
        rc = (lo + hi) / 2
    cd = k["discharge_coefficient"]
    rp = pa / p_pa
    if rp <= rc:
        q = (
            cd
            * hole.area_m2
            * math.sqrt(
                rho
                * p_pa
                * gamma
                * (2.0 / (gamma + 1.0)) ** ((gamma + 1.0) / (gamma - 1.0))
            )
        )
        return q, f"choked gas flow (p. 29), gamma {gamma:.3f}"
    q = (
        cd
        * hole.area_m2
        * math.sqrt(
            2.0
            * rho
            * p_pa
            * (gamma / (gamma - 1.0))
            * (rp ** (2.0 / gamma) - rp ** ((gamma + 1.0) / gamma))
        )
    )
    return q, f"unchoked gas flow (p. 30), gamma {gamma:.3f}"


def two_phase_release(
    material: Material,
    container: Tank,
    quantity_kg: float,
    ambient: Ambient,
    hole: Hole,
    storage: Storage,
    k: dict,
) -> dict:
    """A liquefied gas stored above its boiling point, released through `hole`.

    Each time step: the tank's liquid at temperature T drives a flux through the hole
    at dP = Psat(T) + rho_l g (liquid above the hole) - Pa (p. 25); the liquid that
    evaporates into the space the effluent leaves, Qe = QT / rho_X . rho_l rho_g /
    (rho_l - rho_g), cools the liquid by Qe Lc / (m cp) (section 3.4.1, p. 22). When
    the liquid falls below the hole the head-space gas leaves (section 3.4.6) and the
    liquid evaporates to replace it. The release ends when the tank is empty, when its
    pressure falls to ambient, or at ALOHA's one hour (p. 11)."""
    if quantity_kg <= 0:
        raise SourceTermError("quantity must be positive")
    k = {**k, "_ambient_pa": ambient.pressure_pa}
    pa = ambient.pressure_pa
    g = k["gravity_m_s2"]
    dt = float(k["dt_s"])
    t_max = float(k["max_duration_s"])
    t0 = storage.temperature_k
    p0 = p_sat_pa(material, t0, k)
    if p0 is None:
        return {"reason": _no_antoine(material, t0)}
    if p0 <= pa:
        return {
            "reason": (
                f"stored at {t0:.1f} K the {material.name} is not above its "
                f"boiling point ({material.tb_k:.2f} K), so it does not flash"
            )
        }
    vol0 = quantity_kg / material.rhol_kg_m3
    cap = tank_volume_m3(container)
    if cap is not None and vol0 > cap * (1 + 1e-9):
        raise SourceTermError(
            f"{quantity_kg} kg is {vol0:.3f} m3 of liquid, more than the tank's "
            f"{cap:.3f} m3"
        )
    m_liq, t_k, t = quantity_kg, t0, 0.0
    times, rates, stages = [], [], []
    how_liquid = how_gas = None
    end = "the hour the method allows a source (NOS OR&R 43, p. 11)"
    while t < t_max - 1e-9:
        p = p_sat_pa(material, t_k, k)
        if p is None:
            end = _no_antoine(material, t_k)
            break
        if p <= pa:
            end = f"the tank cooled to {t_k:.1f} K, where its pressure is ambient"
            break
        if m_liq <= 0:
            end = "the tank is empty"
            break
        h = liquid_height_m(container, m_liq / material.rhol_kg_m3)
        above = h is None or h > container.hole_bottom_m + hole.height_m / 2.0
        rho_g = gas_density(material, p, t_k, k)
        if above:
            head = (
                0.0
                if h is None
                else material.rhol_kg_m3
                * g
                * max(h - (container.hole_bottom_m + hole.height_m / 2.0), 0.0)
            )
            gflux, how_liquid = _pipe_flux(material, t_k, p + head - pa, hole, k, p)
            q = gflux * hole.area_m2
            # the effluent is liquid (rho_X = rho_l): it leaves the liquid, and the
            # liquid that evaporates into the space it leaves stays in the tank as
            # vapour
            released = min(q * dt, m_liq)
            evaporated = q * dt * rho_g / (material.rhol_kg_m3 - rho_g)
            stage = "two-phase"
        else:
            if material.vapour_cp_j_mol_k is None:
                end = (
                    "the liquid fell below the hole; the head-space gas release is not "
                    "computed: the vapour heat capacity is not held"
                )
                break
            q, how_gas = _gas_flow(material, t_k, p, hole, container, k)
            # the effluent is vapour (rho_X = rho_g): the liquid evaporates to refill
            # the head space, and that evaporation is what leaves the liquid
            released = q * dt
            evaporated = q * dt * material.rhol_kg_m3 / (material.rhol_kg_m3 - rho_g)
            stage = "gas"
        times.append(t)
        rates.append(released / dt)
        stages.append(stage)
        left = m_liq - (released if stage == "two-phase" else 0.0)
        evaporated = min(evaporated, max(left, 0.0))
        if left > 0:
            t_k -= evaporated * material.hv_j_kg / (left * material.cpl_j_kg_k)
        m_liq = left - evaporated if stage == "gas" else left
        t += dt
    summary = _summary(times, rates, dt, float(k["averaging_s"]))
    f = flashed_fraction(material, t0)
    two_phase_s = dt * sum(1 for s in stages if s == "two-phase")
    omitted = [
        "the tank wall's heat flux (the method states a wall of 2 cm steel and 10 cm "
        "foam and no conductivity, NOS OR&R 43 p. 22): the tank cools by evaporation "
        "alone"
    ]
    if container.kind is None:
        omitted.append(
            "the liquid's head above the hole: the container's dimensions are not "
            "stated, so the hole is at the bottom and the vapour pressure alone "
            "drives it"
        )
    return {
        "model": "two-phase flashing release",
        "method": (
            # HB-161 ADDENDUM-02 item 2: cited by its document, implemented by hazbrief
            "Homogeneous Nonequilibrium Model (section 3.4.5, p. 27), tank cooling "
            "(3.4.1, p. 22), head-space gas (3.4.6, pp. 28-30), flashed fraction "
            "(6.3.2, p. 68) of NOAA Technical Memorandum NOS OR&R 43, implemented by "
            "hazbrief"
        ),
        **summary,
        "two_phase_s": two_phase_s,
        "gas_s": dt * sum(1 for s in stages if s == "gas"),
        "remaining_kg": max(m_liq, 0.0),
        "end": end,
        "storage_temperature_k": t0,
        "storage_pressure_pa": p0,
        "final_temperature_k": t_k,
        "flashed_fraction": f,
        "aerosol_fraction": 1.0 - f,
        "source_temperature_k": material.tb_k,
        "hole_area_m2": hole.area_m2,
        "flux_how": how_liquid,
        "gas_how": how_gas,
        "omitted": omitted,
        "series": {"t_s": times, "rate_kg_s": rates, "stage": stages},
    }


# ── a tank of non-boiling liquid (section 3.4.4.1) ───────────────────────────────────


def _hole_fraction_below(level_m: float, hole: Hole, bottom_m: float) -> float:
    """The fraction of a round hole's area below the liquid level."""
    if level_m >= bottom_m + hole.height_m:
        return 1.0
    if level_m <= bottom_m:
        return 0.0
    r = hole.height_m / 2.0
    return _segment_area(r, level_m - bottom_m) / (math.pi * r * r)


def liquid_tank_drain(
    material: Material,
    container: Tank,
    quantity_kg: float,
    ambient: Ambient,
    hole: Hole,
    storage: Storage,
    k: dict,
) -> dict:
    """A liquid stored below its boiling point leaving a hole by Bernoulli's equation,
    QT = Cdis Af (2 (Ph - Pa) rho_l)^1/2 (p. 25): Ph is the vapour pressure plus the
    head above the hole, held at 1.01 Pa once it falls to it; Af the hole's area below
    the level; when the level intersects the hole, Ph is Pa plus the head above the
    hole's bottom. Flow stops when the level reaches the hole's bottom."""
    if container.kind is None:
        raise SourceTermError("a liquid tank drain needs the tank's geometry")
    pa = ambient.pressure_pa
    g = k["gravity_m_s2"]
    dt = float(k["dt_s"])
    pv = p_sat_pa(material, storage.temperature_k, k)
    if pv is None:
        return {"reason": _no_antoine(material, storage.temperature_k)}
    m, t = quantity_kg, 0.0
    times, rates = [], []
    while t < float(k["max_duration_s"]) - 1e-9:
        level = liquid_height_m(container, m / material.rhol_kg_m3)
        frac = _hole_fraction_below(level, hole, container.hole_bottom_m)
        if frac <= 0.0:
            break
        if frac >= 1.0:
            centre = container.hole_bottom_m + hole.height_m / 2.0
            ph = pv + material.rhol_kg_m3 * g * max(level - centre, 0.0)
            ph = max(ph, k["vented_pressure_factor"] * pa)
        else:
            ph = pa + material.rhol_kg_m3 * g * (level - container.hole_bottom_m)
        q = (
            k["discharge_coefficient"]
            * hole.area_m2
            * frac
            * math.sqrt(2.0 * max(ph - pa, 0.0) * material.rhol_kg_m3)
        )
        dm = min(q * dt, m)
        if dm <= 0:
            break
        times.append(t)
        rates.append(dm / dt)
        m -= dm
        t += dt
    return {"t_s": times, "rate_kg_s": rates, "left_in_tank_kg": m}


# ── the evaporating pool (sections 3.3 and 3.4.4) ─────────────────────────────────────


def _air(ambient: Ambient, k: dict) -> dict:
    """Air's density, kinematic viscosity and thermal diffusivity at the ambient
    temperature: density from the ideal gas with air's molecular weight (US Standard
    Atmosphere 1976 Table 3), viscosity by its equation (51) and conductivity by
    (53)."""
    t = ambient.temperature_k
    rho = (
        ambient.pressure_pa
        * k["air_molecular_weight_kg_mol"]
        / (k["gas_constant_j_mol_k"] * t)
    )
    mu = k["sutherland_beta"] * t**1.5 / (t + k["sutherland_s_k"])
    kt = (
        k["conductivity_coefficient"]
        * t**1.5
        / (t + k["conductivity_s_k"] * 10.0 ** (-12.0 / t))
    )
    return {
        "rho": rho,
        "nu": mu / rho,
        "thermal_diffusivity": kt / (rho * k["air_cp_j_kg_k"]),
    }


def _power_law_n(ambient: Ambient, k: dict) -> float:
    return float(k["power_law_n"][ambient.stability])


def friction_velocity(ambient: Ambient, k: dict) -> float:
    """Deacon's U* = 0.03 U (10 / z)^n (p. 13)."""
    n = _power_law_n(ambient, k)
    return (
        k["deacon_coefficient"]
        * ambient.wind_ms
        * (k["deacon_height_m"] / ambient.wind_height_m) ** n
    )


def mass_transfer_coefficient(
    material: Material, ambient: Ambient, diameter_m: float, k: dict
) -> dict:
    """Brighton's spatially averaged mass transfer coefficient j (pp. 14 and 15), with
    Brutsaert's Lambda and f(Sc), Graham's law diffusivity and Deacon's U*."""
    n = _power_law_n(ambient, k)
    vk, sct, ge = k["von_karman"], k["turbulent_schmidt"], k["euler_constant"]
    air = _air(ambient, k)
    us = friction_velocity(ambient, k)
    kappa = k["water_vapour_diffusivity_m2_s"] * math.sqrt(
        k["water_molecular_weight_kg_mol"] / material.mw_kg_mol
    )
    # Sc: p. 15 defines it in words as nu / kappa and typesets kappa / nu; the
    # constant `schmidt_form` chooses, and orchestrator.yaml says why (methods.md s4)
    form = k["schmidt_form"]
    if form == "typeset":
        sc = kappa / air["nu"]
    elif form == "worded":
        sc = air["nu"] / kappa
    else:
        raise SourceTermError(f"schmidt_form {form!r} is neither typeset nor worded")
    re0 = us * ambient.z0_m / air["nu"]
    lo, hi = k["roughness_reynolds"]

    def smooth():
        return (k["fsc_smooth_a"] * sc ** (1 / 3) - k["fsc_smooth_b"]) ** 2 + (
            sct / vk
        ) * math.log(k["fsc_smooth_c"] * sc)

    def rough(re):
        return k["fsc_rough_a"] * re**0.25 * math.sqrt(sc) - k["fsc_rough_b"] * sct

    if re0 < lo:
        fsc = smooth()
    elif re0 > hi:
        fsc = rough(re0)
    else:
        w = (re0 - lo) / (hi - lo)
        fsc = (1 - w) * smooth() + w * rough(hi)
    lam = 1 / n + 1 + 2 * math.log(1 + n) - 2 * ge + (vk / sct) * (1 + n) * fsc
    x1 = n * vk * vk * diameter_m / (sct * ambient.z0_m * math.exp(1 / n))
    y = lam + math.log(x1)
    pi = math.pi
    bracket = (
        0.5
        - math.atan(y / pi) / pi
        + (1 - ge) / (y * y + pi * pi)
        + (1 + (1 - ge) ** 2 + pi * pi / 6) * y / (y * y + pi * pi) ** 2
    )
    j = (vk / sct) * (1 + n) * bracket
    return {
        "j": j,
        "u_star": us,
        "sc": sc,
        "re0": re0,
        "f_sc": fsc,
        "lambda": lam,
        "x1": x1,
        "kappa": kappa,
        "air": air,
    }


def _brighton_flux(material, ambient, diameter_m, t_k, k) -> tuple[float, float, dict]:
    """(E, the correction factor, coefficients): E = Cs U* jc (p. 13), jc = -j Pa/Pv
    ln(1 - Pv/Pa)."""
    pv = p_sat_pa(material, t_k, k)
    pa = ambient.pressure_pa
    mt = mass_transfer_coefficient(material, ambient, diameter_m, k)
    if pv is None or pv >= pa:
        return float("inf"), float("inf"), mt
    corr = -(pa / pv) * math.log(1 - pv / pa)
    cs = gas_density(material, pv, t_k, k)
    return cs * mt["u_star"] * mt["j"] * corr, corr, mt


def _brighton_limit_t(material, ambient, k) -> float | None:
    """The puddle temperature at which the correction factor reaches its limit
    (footnote 3, p. 12): bisection on Pv between the lowest Antoine temperature and the
    boiling point."""
    target = k["brighton_correction_limit"]
    pa = ambient.pressure_pa
    lo = min((r.t_min_k for r in material.antoine), default=material.tb_k - 100.0)
    hi = material.tb_k
    for _ in range(80):
        mid = (lo + hi) / 2
        pv = p_sat_pa(material, mid, k)
        if pv is None:
            lo = mid
            continue
        x = min(pv / pa, 1 - 1e-12)
        if -(math.log(1 - x)) / x < target:
            lo = mid
        else:
            hi = mid
    return lo


def _fluxes(
    material, ambient, ground, diameter_m, tp_k, k, rings, t, dt, omitted
) -> dict:
    """The puddle's energy fluxes into it, W/m2 (section 3.3.3, pp. 16 to 21), averaged
    over the step. Ground: each ring of the puddle, wetted at its own time, takes the
    error-function solution for a constant surface temperature, integrated over the
    step (an infinite flux at wetting integrates to a finite energy)."""
    sigma = k["stefan_boltzmann"]
    ta = ambient.temperature_k
    out = {"solar": 0.0, "longwave_down": 0.0, "longwave_up": 0.0}
    if ambient.cloud_tenths is not None and ambient.solar_altitude_deg is not None:
        s = math.sin(math.radians(ambient.solar_altitude_deg))
        ci = ambient.cloud_tenths
        out["solar"] = (
            k["solar_constant"] * (1 - k["solar_cloud_factor"] * ci * ci) * (s - 0.1)
            if s > 0.1
            else 0.0
        )
    else:
        omitted.add("solar flux: the scenario gives no sky cover or solar altitude")
    if ambient.cloud_tenths is not None and ambient.rh_pct is not None:
        ci = int(round(ambient.cloud_tenths))
        a, b = k["radiation_factor"][ci]
        ew = k["ew_a"] * ambient.rh_pct / 100.0 * math.exp(k["ew_b"] - k["ew_c"] / ta)
        out["longwave_down"] = (
            (1 - k["longwave_reflectivity"]) * (a + b * ew) * sigma * ta**4
        )
        out["longwave_up"] = -k["emissivity"] * sigma * tp_k**4
    else:
        omitted.add(
            "longwave radiation, both ways: the scenario gives no relative humidity "
            "(the method's atmospheric factor needs it, NOS OR&R 43 p. 19)"
        )
    tg = ground.temperature_k
    area = math.pi * diameter_m**2 / 4.0
    if ground.kind == "water":
        fg = k["water_heat_transfer"] * (tg - tp_k) if tp_k < tg else 0.0
    else:
        alpha, kappa = k["ground"][ground.kind]
        energy = 0.0
        for t_wet, a_ring in rings:
            s0 = max(t - t_wet, 0.0)
            energy += a_ring * 2.0 * (math.sqrt(s0 + dt) - math.sqrt(s0))
        fg = alpha * (tg - tp_k) / math.sqrt(math.pi * kappa) * energy / (dt * area)
    out["ground"] = fg
    mt = mass_transfer_coefficient(material, ambient, diameter_m, k)
    pv = p_sat_pa(material, tp_k, k)
    pa = ambient.pressure_pa
    if pv is not None and pv < pa:
        jc = -mt["j"] * (pa / pv) * math.log(1 - pv / pa)
    else:
        jc = mt["j"] * k["brighton_correction_limit"]
    ch = jc * (mt["air"]["thermal_diffusivity"] / mt["kappa"]) ** (2.0 / 3.0)
    out["sensible"] = (
        mt["air"]["rho"] * k["air_cp_j_kg_k"] * ch * mt["u_star"] * (ta - tp_k)
    )
    return out


def pool_release(
    material: Material,
    quantity_kg: float,
    ambient: Ambient,
    ground: Ground,
    k: dict,
    *,
    initial_temperature_k: float | None = None,
    inflow: dict | None = None,
    isothermal: bool = False,
) -> dict:
    """A pool of `quantity_kg` (spilled at once) or fed by `inflow` (a tank's drain,
    {t_s, rate_kg_s}), spreading by Briscoe and Shaw's dr/dt = (2 g d)^1/2 (p. 26)
    until it is 5 mm deep or at ALOHA's 200 m (manual p. 56), its area never shrinking;
    evaporating by Brighton below its boiling point and by the energy balance at it,
    whichever is larger at Brighton's limit (p. 16). Below the boiling point the
    puddle's temperature follows dTp/dt = (sum of fluxes - Lc E) / (rho_l cpl d)
    (p. 17) unless `isothermal` (a worked example that prints no heat capacity)."""
    dt = float(k["dt_s"])
    g = k["gravity_m_s2"]
    t_max = float(k["max_duration_s"])
    rho = material.rhol_kg_m3
    tp = material.tb_k if initial_temperature_k is None else initial_temperature_k
    tp = min(tp, material.tb_k)
    t_limit = _brighton_limit_t(material, ambient, k)
    omitted: set[str] = set()
    mass = 0.0 if inflow else quantity_kg
    r2 = 0.0
    if not inflow:
        r2 = 2.0 * math.sqrt(2.0 * g * (mass / rho) / math.pi) * dt
    spreading = True
    rings: list[tuple[float, float]] = []
    if r2 > 0:
        rings.append((0.0, math.pi * r2))
    # the feed is a series on this function's own step (liquid_tank_drain's `dt_s`)
    feed = list(inflow["rate_kg_s"]) if inflow else []
    feed_t = inflow.get("temperature_k") if inflow else None
    fed_total = sum(feed) * dt if inflow else quantity_kg
    times, rates, branches = [], [], []
    t, step = 0.0, 0
    last_capacity = 0.0
    max_d = 0.0
    last_fluxes: dict = {}
    end = "the hour the method allows a source (NOS OR&R 43, p. 11)"
    while t < t_max - 1e-9:
        qin = feed[step] if step < len(feed) else 0.0
        mass += qin * dt
        if mass <= 0 and step >= len(feed):
            end = "the pool has evaporated"
            break
        if mass <= 0:
            times.append(t)
            rates.append(0.0)
            branches.append("none")
            t += dt
            step += 1
            continue
        if r2 <= 0:
            r2 = 2.0 * math.sqrt(2.0 * g * (mass / rho) / math.pi) * dt
            rings.append((t, math.pi * r2))
        area = math.pi * r2
        depth = mass / (rho * area)
        d = 2.0 * math.sqrt(r2)
        if spreading and depth > k["min_depth_m"] and d < k["max_diameter_m"]:
            new_r2 = r2 + 2.0 * math.sqrt(r2) * math.sqrt(2.0 * g * depth) * dt
            new_r2 = min(new_r2, (k["max_diameter_m"] / 2.0) ** 2)
            rings.append((t, math.pi * (new_r2 - r2)))
            r2 = new_r2
        elif spreading and (step >= len(feed) or qin * dt <= last_capacity):
            # spreading ends for good at the minimum depth or the largest diameter
            # (p. 26) once the tank no longer releases faster than the pool
            # evaporates ("When the tank release rate is greater than the computed
            # evaporation rate, ALOHA predicts that the puddle will spread", p. 26);
            # the area never shrinks
            spreading = False
        area = math.pi * r2
        d = 2.0 * math.sqrt(r2)
        max_d = max(max_d, d)
        fl = _fluxes(material, ambient, ground, d, tp, k, rings, t, dt, omitted)
        heat = sum(fl.values())
        lc = material.hv_j_kg
        boiling = tp >= t_limit - 1e-9
        e_limit, _, _ = _brighton_flux(material, ambient, d, t_limit, k)
        if boiling:
            e_boil = max(heat, 0.0) / lc
            e = max(e_boil, e_limit)
            branch = "boiling" if e_boil >= e_limit else "Brighton at its limit"
            tp = material.tb_k if e_boil >= e_limit else t_limit
        else:
            e, _, _ = _brighton_flux(material, ambient, d, tp, k)
            branch = "Brighton"
            if not isothermal:
                # FdM = QT cpl (TT - Tp) / (pi rp^2): the feed's heat (p. 26)
                fdm = (
                    qin * material.cpl_j_kg_k * (feed_t - tp) / area
                    if feed_t is not None
                    else 0.0
                )
                dtp = (heat - lc * e + fdm) / (
                    rho * material.cpl_j_kg_k * max(depth, 1e-6)
                )
                tp = min(tp + dtp * dt, t_limit)
        capacity = e * area * dt
        last_capacity = capacity
        dm = min(capacity, mass)
        mass -= dm
        times.append(t)
        rates.append(dm / dt)
        branches.append(branch)
        last_fluxes = {**fl, "evaporative": -lc * dm / dt / area}
        t += dt
        step += 1
        if mass <= 0.0 and not spreading:
            # The pool has evaporated. A tank still trickling through a hole its
            # level has nearly reached feeds less than the pool can evaporate, so it
            # evaporates as it arrives; it is reported, not timed as the release.
            end = "the pool has evaporated"
            break
    summary = _summary(times, rates, dt, float(k["averaging_s"]))
    if isothermal:
        omitted.add(
            "the puddle's temperature is held at its initial value: the inputs give no "
            "liquid heat capacity"
        )
    omitted.add(
        "ground conduction by the error-function solution for a constant puddle "
        "temperature, per ring of the spreading puddle; the method solves it by finite "
        "differences (NOS OR&R 43 p. 20)"
    )
    return {
        "model": "evaporating pool",
        "method": (
            "Briscoe and Shaw spreading (3.4.4.2, p. 26), Brighton's evaporation "
            "(3.3.1, pp. 12-15), the energy balance (3.3.2-3.3.3, pp. 16-21) of NOAA "
            "Technical Memorandum NOS OR&R 43, implemented by hazbrief"
        ),
        **summary,
        "fed_kg": fed_total,
        "trickle_after_kg": sum(feed[step:]) * dt if inflow else 0.0,
        "remaining_kg": max(mass, 0.0),
        "end": end,
        "max_diameter_m": max_d,
        "max_area_m2": math.pi * max_d**2 / 4.0,
        "pool_temperature_k": tp,
        "brighton_limit_k": t_limit,
        "branches": sorted(set(branches) - {"none"}),
        "last_fluxes_w_m2": last_fluxes,
        "omitted": sorted(omitted),
        "series": {"t_s": times, "rate_kg_s": rates},
    }


def _no_antoine(material: Material, t_k: float) -> str:
    spans = ", ".join(f"{r.t_min_k:g} to {r.t_max_k:g} K" for r in material.antoine)
    return (
        f"no saturation-pressure fit holds {t_k:.1f} K for {material.name} "
        f"(the pack's Antoine rows cover {spans}); a fit is not extrapolated"
    )


# ── the pack's material ───────────────────────────────────────────────────────────────

_REQUIRED = (
    "molecular_weight_g_mol",
    "heat_of_vaporization_j_mol",
    "liquid_heat_capacity_j_mol_k",
    "liquid_density_kg_m3",
    "normal_boiling_point_k",
)
_K = re.compile(r"(-?\d+(?:\.\d+)?)\s*K\b")
#: A fetched entry's missing fields in a responder's words (HB-119 ADDENDUM-01 section
#: 3: the dense-gas row names "vapour heat capacity"). The seed's line keeps the field
#: names it has always printed, so the committed briefs do not move.
_WORDS = {
    "molecular_weight_g_mol": "molecular weight",
    "normal_boiling_point_k": "normal boiling point",
    "heat_of_vaporization_j_mol": "heat of vaporisation",
    "liquid_heat_capacity_j_mol_k": "liquid heat capacity",
    "vapour_heat_capacity": "vapour heat capacity",
    "liquid_density_kg_m3": "liquid density",
    "saturation_pressure_antoine": "saturation-pressure (Antoine) constants",
}


def _value(
    block: dict,
    name: str,
    unit: str,
    source_label: str,
    labels: dict[str, str] | None = None,
) -> Value:
    """A pack value as the source term reads it. A value the materials resolver
    fetched (HB-119) prints its label, "properties fetched at <time> from <source>,
    not benchmark-validated", and the url it was read from, where a held value prints
    its document and page (DN-009 C1): `labels` is the entry's `provenance.labels`,
    keyed by the receipt's document id."""
    r = block.get("receipt") or {}
    fetched = (labels or {}).get(r.get("doc_id")) if r else None
    if fetched:
        where = f"{fetched} ({r.get('locator')})"
    else:
        where = f"{r.get('doc_id')} p. {r.get('page')}" if r else source_label
    return Value(
        name=name,
        value=float(block["value"]),
        unit=unit,
        tier=block.get("source_tier"),
        as_printed=block.get("as_printed"),
        source=where,
        temperature_k=block.get("temperature_k"),
    )


def material_from_pack(
    pack: dict, un: str, k: dict
) -> tuple[Material | None, str | None]:
    """The source term's material from `packs/materials_properties.json`'s data:
    `materials[un].thermodynamics` as HB-109 and HB-124 built it, through a proxy block
    where the pack marks one (DN-020 ADDENDUM-01 item 4; HB-110 ADDENDUM-02 section 2).
    A disputed boiling point is taken at the candidate where the pack's own Antoine row
    is nearest one atmosphere (ADDENDUM-02 section 3). `(None, why)` names what is not
    held."""
    mats = pack["materials"]
    entry = mats.get(un)
    if entry is None:
        return None, f"not available: UN{un} is not in the properties pack"
    thermo = entry.get("thermodynamics") or {}
    # HB-119: a fetched entry carries its labels; a seed entry has none.
    prov = entry.get("provenance") or {}
    labels = prov.get("labels") or {}
    holder = (
        f"the properties fetched from {' and '.join(prov.get('sources') or [])}"
        if prov
        else "the properties pack"
    )
    notes: list[str] = []
    proxy = thermo.get("proxy")
    if proxy:
        of = str(proxy["properties_of"]).removeprefix("UN")
        quote = (proxy.get("receipt") or {}).get("quote")
        doc = (proxy.get("receipt") or {}).get("doc_id")
        notes.append(
            f"{proxy['label']} (UN{of}); {doc}: “{quote}”" if quote else proxy["label"]
        )
        thermo = (mats[of].get("thermodynamics") or {}) | {"proxy": proxy}
    missing = [n for n in _REQUIRED if (thermo.get(n) or {}).get("value") is None]
    rows = (thermo.get("saturation_pressure_antoine") or {}).get("rows") or []
    if not rows:
        missing.append("saturation_pressure_antoine")
    if missing:
        listed = thermo.get("missing") or missing
        return None, (
            f"not available: {holder} do not hold "
            f"{', '.join(_WORDS.get(n, n) for n in listed)} for "
            f"{'UN' + un if un.isdigit() else un} {entry.get('name')}"
            if prov
            else f"not available: the properties pack does not hold "
            f"{', '.join(listed)} for UN{un} {entry.get('name')}"
        )
    antoine = tuple(
        AntoineRow(
            t_min_k=float(r["t_min_k"]),
            t_max_k=float(r["t_max_k"]),
            a=float(r["constants"]["A"]["value"]),
            b=float(r["constants"]["B"]["value"]),
            c=float(r["constants"]["C"]["value"]),
            source=f"{r['receipt']['doc_id']} p. {r['receipt']['page']}",
        )
        for r in rows
    )
    mw = float(thermo["molecular_weight_g_mol"]["value"]) / 1000.0
    tb_block = thermo["normal_boiling_point_k"]
    tb = float(tb_block["value"])
    base = Material(
        name=entry.get("name") or f"UN{un}",
        un=un,
        mw_kg_mol=mw,
        tb_k=tb,
        hv_j_mol=float(thermo["heat_of_vaporization_j_mol"]["value"]),
        cpl_j_mol_k=float(thermo["liquid_heat_capacity_j_mol_k"]["value"]),
        rhol_kg_m3=float(thermo["liquid_density_kg_m3"]["value"]),
        antoine=antoine,
    )
    tb_value = _value(tb_block, "normal boiling point", "K", "pack", labels)
    for check in thermo.get("cross_checks") or []:
        if check.get("field") == "normal boiling point (K)" and check.get("status") == (
            "disputed"
        ):
            cands = []
            for who, text in (check.get("values") or {}).items():
                m = _K.search(str(text))
                if m:
                    cands.append((who, float(m.group(1)), str(text)))
            scored = []
            for who, tbk, text in cands:
                p = p_sat_pa(base, tbk, k)
                if p is not None:
                    scored.append((abs(p - k["one_atmosphere_pa"]), who, tbk, text, p))
            if scored:
                scored.sort()
                _, who, tb, text, p = scored[0]
                listed = "; ".join(
                    f"{w}: {x} (Antoine {pp / k['one_atmosphere_pa']:.2f} atm)"
                    for _, w, _, x, pp in sorted(scored, key=lambda s: s[1])
                )
                notes.append(
                    f"boiling point disputed ({listed}); {tb:g} K taken, where the "
                    "pack's Antoine row is nearest 1 atm (HB-110 ADDENDUM-02 section 3)"
                )
                tb_value = Value(
                    name="normal boiling point",
                    value=tb,
                    unit="K",
                    tier=tb_block.get("source_tier"),
                    as_printed=text,
                    source=who,
                )
    vcp = (thermo.get("vapour_heat_capacity_j_mol_k") or {}).get("value")
    values = (
        _value(
            thermo["molecular_weight_g_mol"],
            "molecular weight",
            "g/mol",
            "pack",
            labels,
        ),
        tb_value,
        _value(
            thermo["heat_of_vaporization_j_mol"],
            "heat of vaporisation",
            "J/mol",
            "pack",
            labels,
        ),
        _value(
            thermo["liquid_heat_capacity_j_mol_k"],
            "liquid heat capacity",
            "J/mol/K",
            "pack",
            labels,
        ),
        _value(
            thermo["liquid_density_kg_m3"], "liquid density", "kg/m3", "pack", labels
        ),
        Value(
            name="saturation pressure (Antoine)",
            value=float(len(antoine)),
            unit="rows",
            tier=(thermo.get("saturation_pressure_antoine") or {}).get("source_tier")
            or (rows[0].get("source_tier") if rows else None)
            or "reference-table",
            as_printed="; ".join(
                f"{r.t_min_k:g} to {r.t_max_k:g} K: A {r.a:g}, B {r.b:g}, C {r.c:g}"
                for r in antoine
            ),
            source=", ".join(sorted({r.source for r in antoine})),
        ),
    )
    if vcp is not None:
        values += (
            _value(
                thermo["vapour_heat_capacity_j_mol_k"],
                "vapour heat capacity",
                "J/mol/K",
                "pack",
                labels,
            ),
        )
    return (
        Material(
            name=base.name,
            un=un,
            mw_kg_mol=mw,
            tb_k=tb,
            hv_j_mol=base.hv_j_mol,
            cpl_j_mol_k=base.cpl_j_mol_k,
            rhol_kg_m3=base.rhol_kg_m3,
            antoine=antoine,
            vapour_cp_j_mol_k=float(vcp) if vcp is not None else None,
            tc_k=(thermo.get("critical_temperature_k") or {}).get("value"),
            values=values,
            notes=tuple(notes),
        ),
        None,
    )


# ── the routing (DN-020 section 3.1's table) ──────────────────────────────────────────


@dataclass(frozen=True)
class Scenario:
    """What `source_term` routes on: the scenario's material, container, storage state
    and quantity, as `docs/evidence/hb124/source_terms.tsv` reads them."""

    un: str | None
    container: str | None
    storage_state: str | None
    quantity_kg: float | None
    where_spilled: str | None = "land"
    coverage: str | None = None
    unresolved_reason: str | None = None


@dataclass
class Met:
    ambient: Ambient
    ground: Ground


@dataclass
class Result:
    model: str
    result: dict
    material: Material
    assumptions: list[str] = field(default_factory=list)
    inputs: list[dict] = field(default_factory=list)


#: DN-001's hazard classes (the footprint's `hazard_class.class_id`) and the storage
#: state each is transported in: a toxic-by-inhalation or flammable gas in bulk is a
#: gas liquefied under its own pressure (the ERG's road trailer chart, erg2024-en-pdf
#: p. 15: MC331 "For liquefied compressed gases (e.g., LPG, ammonia)"); a flammable
#: liquid is a liquid at the air's temperature (p. 16: DOT406 "For flammable liquids
#: (e.g., gasoline, diesel)"); a cryogenic asphyxiant is a refrigerated liquid at its
#: boiling point (p. 15: MC338 "For refrigerated liquefied gases (cryogenic liquids)").
#: The route is by class, never by material (DN-020 ADDENDUM-02 item 1).
CLASS_STATES = {
    "tih_gas": "pressure_liquefied",
    "flammable_liquefied_gas": "pressure_liquefied",
    "flammable_liquid": "ambient_liquid",
    "cryogenic_asphyxiant": "refrigerated_liquid",
}


def route_state(
    class_id: str | None, names: list[str] | None
) -> tuple[str | None, str]:
    """(storage state, basis) for a resolved material: an ERG name that says
    "refrigerated liquid" first (the name is the shipping description), then the
    DN-001 class; (None, why) for a class no release model takes."""
    if any("REFRIGERATED LIQUID" in n.upper() for n in names or []):
        return "refrigerated_liquid", "ERG name: refrigerated liquid"
    state = CLASS_STATES.get(class_id or "")
    if state is None:
        return None, (
            f"the DN-001 class {class_id!r} routes to no release model"
            if class_id
            else "the material has no DN-001 hazard class that routes to a release "
            "model"
        )
    return state, f"DN-001 class {class_id}"


def source_term(
    scenario: Scenario, pack: dict, met: Met | None, spec: dict
) -> tuple[Result | None, str | None]:
    """Route one scenario to its release model and run it, or say in one line why not.

    Routing (DN-020 section 3.1): a known container holding a liquid under its vapour
    pressure (`pressure_liquefied`) takes the two-phase flashing release from the
    declared hole; a liquid at or below its boiling point (`refrigerated_liquid`,
    `ambient_liquid`) takes the evaporating pool on the stated quantity; an unknown
    container, an unstated quantity, or an unidentified or ambiguous material takes
    no source term."""
    k = constants(spec)
    lines = spec["lines"]
    if scenario.un is None:
        return None, lines["unidentified"].format(
            why=scenario.unresolved_reason or "the material is not identified"
        )
    if not scenario.container or scenario.container == "unknown":
        return None, lines["no_container"]
    if scenario.quantity_kg is None:
        return None, lines["no_quantity"]
    if scenario.storage_state not in (
        "pressure_liquefied",
        "refrigerated_liquid",
        "ambient_liquid",
    ):
        return None, lines["no_state"].format(
            un=scenario.un, why=scenario.unresolved_reason or "no storage state"
        )
    material, why = material_from_pack(pack, scenario.un, k)
    if material is None:
        return None, why
    if met is None:
        return None, lines["no_weather"]
    amb = met.ambient
    if (
        scenario.storage_state == "pressure_liquefied"
        and material.tc_k is not None
        and amb.temperature_k >= material.tc_k
    ):
        return None, lines["above_critical"].format(
            un=scenario.un, tc=material.tc_k, t=amb.temperature_k
        )
    inputs = [
        {
            "name": v.name,
            "value": v.value,
            "unit": v.unit,
            "tier": v.tier,
            "as_printed": v.as_printed,
            "source": v.source,
            "temperature_k": v.temperature_k,
        }
        for v in material.values
    ]
    if scenario.storage_state == "pressure_liquefied":
        hole_spec = spec["assumptions"]["hole"]
        hole = Hole(
            area_m2=float(hole_spec["area_m2"]),
            kind=hole_spec["kind"],
            width_m=float(hole_spec["width_m"]),
            height_m=float(hole_spec["height_m"]),
            label=hole_spec["label"],
            source=hole_spec["source"],
        )
        storage = Storage(amb.temperature_k, spec["assumptions"]["storage_ambient"])
        res = two_phase_release(
            material, Tank(), scenario.quantity_kg, amb, hole, storage, k
        )
        if "reason" in res:
            return None, lines["not_available"].format(why=res["reason"])
        assumptions = [hole.label, storage.source]
        return Result(
            "two-phase flashing release", res, material, assumptions, inputs
        ), None
    if scenario.storage_state == "refrigerated_liquid":
        t0 = material.tb_k
        assumptions = [spec["assumptions"]["storage_refrigerated"]]
    else:
        t0 = amb.temperature_k
        assumptions = [spec["assumptions"]["storage_ambient"]]
    assumptions.append(spec["assumptions"]["pool_spill"])
    res = pool_release(
        material, scenario.quantity_kg, amb, met.ground, k, initial_temperature_k=t0
    )
    if "reason" in res:
        return None, lines["not_available"].format(why=res["reason"])
    return Result("evaporating pool", res, material, assumptions, inputs), None


# ── the label ─────────────────────────────────────────────────────────────────────────


def _fmt(v: float) -> str:
    return f"{v:.6g}"


def values_text(material: Material, spec: dict) -> str:
    """Every value the source term read, each with its tier, its as-printed text and
    its page (HB-110 ADDENDUM-03 section 3), then each tier's note once."""
    env = spec["source_term_envelope"]
    parts = [
        env["value"].format(
            name=v.name,
            value=_fmt(v.value),
            unit=v.unit,
            tier=v.tier or "tier not stated",
            as_printed=v.as_printed or "not printed",
            source=v.source,
        )
        for v in material.values
    ]
    tiers = sorted({v.tier for v in material.values if v.tier})
    notes = [env["tier_notes"][t].rstrip(".") for t in tiers if t in env["tier_notes"]]
    return "; ".join(parts + notes)


def envelope_assumption(
    res: Result, quantity_kg: float, quantity_source: str, spec: dict
) -> str:
    """The puff envelope's `assumption` for a source term (HB-110 step 5): the release
    model, its rate and duration, its declared assumptions, every property with its
    tier, and the material's notes (a proxy, a disputed boiling point)."""
    env = spec["source_term_envelope"]
    r = res.result
    extra = list(res.material.notes)
    if r.get("instantaneous"):
        extra.insert(0, env["instantaneous"].format(seconds=r["computed_duration_s"]))
    for line in r.get("omitted") or []:
        extra.append(env["omitted"].format(what=line))
    notes = "; ".join(n.rstrip(".") for n in extra)
    common = {
        "mean": r["mean_rate_kg_s"],
        "minutes": r["duration_s"] / 60.0,
        "released": r["released_kg"],
        "quantity": quantity_kg,
        "quantity_source": quantity_source,
        "assumptions": "; ".join(res.assumptions),
        "values": values_text(res.material, spec),
        "notes": f"; {notes}" if notes else "",
    }
    if res.model == "two-phase flashing release":
        return env["two_phase"].format(
            flashed=r["flashed_fraction"],
            aerosol=r["aerosol_fraction"],
            ts=r["source_temperature_k"],
            **common,
        )
    return env["pool"].format(
        diameter=r["max_diameter_m"],
        tp=r["pool_temperature_k"],
        branches=", ".join(r["branches"]) or "no evaporation",
        **common,
    )
