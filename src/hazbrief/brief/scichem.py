"""The dense-release engine's client: SCICHEM from what a brief holds to a held record
(HB-167 Part C; DN-028). It replaces HB-165's probe (`scichem_probe.py`): one
path remains.

Four steps, each its own function:

1. `build_request(problem, seed, ...)`: SCICHEM's namelist project from
   - the release, as the brief's SLAB problem holds it (`dense_gas.read_deck`): rate,
     duration, flashed fraction, boiling point, heat of vaporisation, liquid density,
     the flashed area AS, the air temperature and the roughness;
   - the held NWS gridpoint forecast (hourly wind, temperature, humidity, sky cover and,
     where `met.use_forecast_mixing_height`, the mixing height);
   - the site, the release time, the AEGL tiers at the brief's averaging time, and the
     points to measure (every roadblock and cordon the brief draws, the sited points
     and the named places; HB-167 ADDENDUM-01 item 1).

   The two-phase jet becomes a SCIPUFF continuous source by the technical
   documentation's method for its own two-phase trials (section 13.4, Desert Tortoise
   and Goldfish): "modeling the source jet as an expanding 7 degree cone until
   sufficient air has been entrained to evaporate the liquid aerosol. The SCIPUFF
   source is then initialized at this downstream location at the boiling temperature.
   The initial size is chosen to match the area implied by the expanding cone but with
   a horizontal spread that is twice the vertical." The air needed is an energy balance
   (the liquid's heat of vaporisation against the entrained air's sensible heat down to
   the boiling point); the jet's speed there is momentum conservation from SLAB's
   flashed source; the area is the mixture's volume flux over that speed; the sigmas
   are 0.75 of the radii, the documentation's rule for its pool sources.

   A wet forecast, a forecast that does not cover the run, or an input not held is a
   `Refusal` ("not modelled" with the reason; Part C item 13). Nothing is defaulted
   silently and the other engine is never run in its place.
2. `run_request(request, cfg)`: the models image runs `scichem_driver.py` on the
   request (`docker run --rm -i --network none --pull never`); `argv` replaces the
   command for a development build. The response is the engine's sensor file and the
   post-processor's contours.
3. `derive(request, response)`: the record HB-163 reads:
   - at every output step, one area per tier (the mean concentration's contour at the
     tier's level on the brief's plane) and the probability areas, P(C > tier) at
     each of `record.probability_percent`;
   - per tier, the area reached at any time (the union of the steps');
   - at every point, the breathing-height series of the mean and its variance, the
     peak, the highest tier reached, first arrival, minutes above and time clear per
     tier, the largest probability of exceeding each tier, and the dose integrated
     from the series (no time-integrated sensors: they crash both builds, HB-165);
   - the inputs used and the assumptions kept, by name.
4. `recorded(...)`: a replayed brief or test never starts the engine. It reads
   `<recordings_dir>/<sha256 of the request>.json`; with `record`, it runs the engine
   when no record is held and writes one.

The probability is the engine's clipped-normal distribution of the concentration from
its mean and variance (technical documentation section 12.2.1). As run here (no
large-scale variability, the README's practice for domains under about 150 km) it
covers turbulent fluctuation, not uncertainty in the forecast wind (DN-028 decision
4).
"""

from __future__ import annotations

import base64
import contextvars
import functools
import gzip
import hashlib
import json
import math
import re
import shutil
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from geographiclib.geodesic import Geodesic
from shapely import make_valid
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry import Point as ShPoint
from shapely.ops import unary_union

from hazbrief import geometry as G

ROOT = Path(__file__).resolve().parents[3]
CONFIG = Path(__file__).with_name("scichem.yaml")
_WGS84 = Geodesic.WGS84

FORECAST_LAYERS = (
    "temperature",
    "relativeHumidity",
    "windSpeed",
    "windDirection",
    "skyCover",
    "mixingHeight",
)
_DURATION = re.compile(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?)?")
#: SCICHEM's namelist scenario reader leaves the unit past end of file when the
#: namelist is the file's last record; patch 11 (patches/) adds
#: the BACKSPACE. EPRI's own namelist files all end with a trailing block, so the
#: project keeps one line after the namelist as they do (HB-165).
SCN_TRAILER = "#END"


class Refusal(RuntimeError):
    """The engine is not run, or did not finish: the message is the record's reason,
    beginning "not modelled:" (Part C item 13)."""


def load_config(path: Path = CONFIG) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


@functools.cache
def _record_config() -> dict:
    """The shipped config's `record` block, read once: `contour_shape` reads its edge
    rules at every tier of every step."""
    return load_config()["record"]


# ── inputs ───────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Tier:
    """An AEGL tier at the brief's averaging time: `ppm` and its mass concentration."""

    name: str
    ppm: float
    minutes: float
    kg_m3: float
    receipt: str

    def as_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass(frozen=True)
class Place:
    """A point the record measures: `kind` is roadblock, sited or named_place; `names`
    every label drawn there (two roads can meet at one point)."""

    id: str
    kind: str
    names: tuple[str, ...]
    lat: float
    lon: float
    layers: tuple[str, ...]

    def as_dict(self) -> dict:
        d = dict(self.__dict__)
        d["names"] = list(self.names)
        d["layers"] = list(self.layers)
        return d


def tiers_from_pack(
    mdata: dict, un: str, minutes: float, names: list[str], mw_kg_mol: float, cfg: dict
) -> list[Tier]:
    """The AEGL tiers the materials pack holds at `minutes` for `un`, lowest concern
    first (`dense_gas.bands.tiers`, the brief's own reading of the same cells)."""
    cells = ((mdata.get("materials") or {}).get(un) or {}).get("aegl_ppm") or {}
    vm = float(cfg["record"]["molar_volume_m3_mol"])
    out = []
    for name in names:
        cell = (cells.get(name) or {}).get(f"{minutes:g}") or {}
        if cell.get("status") != "held":
            continue
        ppm = float(cell["value"])
        rec = cell.get("receipt") or {}
        out.append(
            Tier(
                name=name,
                ppm=ppm,
                minutes=minutes,
                kg_m3=ppm * 1e-6 * mw_kg_mol / vm,
                receipt=f'{rec.get("locator")}: "{rec.get("quote")}"',
            )
        )
    if not out:
        raise Refusal(
            cfg["refusals"]["missing"].format(
                detail=f"an AEGL tier at {minutes:g} minutes for UN{un}"
            )
        )
    return out


def _popup_name(popup: str) -> str:
    m = re.search(r"<strong>(.*?)</strong>", popup or "")
    name = re.sub(r"<[^>]+>", "", m.group(1)) if m else ""
    return name.removeprefix("Candidate: ").strip() or "unnamed"


def places_from_map_data(map_data: dict, cfg: dict) -> list[Place]:
    """Every point feature of the brief's point layers (`record.point_layers`), merged
    where several share a position: a brief's map data in, the record's points out."""
    kinds = {
        lid: kind
        for kind, lids in cfg["record"]["point_layers"].items()
        for lid in lids
    }
    seen: dict[tuple[float, float, str], dict] = {}
    for layer in map_data.get("layers") or []:
        kind = kinds.get(layer.get("id"))
        if kind is None:
            continue
        for f in layer.get("features") or []:
            g = f.get("geometry") or {}
            if g.get("type") != "Point":
                continue
            lon, lat = (float(v) for v in g["coordinates"][:2])
            key = (round(lat, 6), round(lon, 6), kind)
            slot = seen.setdefault(key, {"names": [], "layers": []})
            nm = _popup_name((f.get("properties") or {}).get("popup", ""))
            if nm not in slot["names"]:
                slot["names"].append(nm)
            if layer["id"] not in slot["layers"]:
                slot["layers"].append(layer["id"])
    out = []
    for (lat, lon, kind), slot in sorted(seen.items()):
        pid = hashlib.sha256(f"{kind}:{lat:.6f}:{lon:.6f}".encode()).hexdigest()[:12]
        out.append(
            Place(
                id=pid,
                kind=kind,
                names=tuple(slot["names"]),
                lat=lat,
                lon=lon,
                layers=tuple(slot["layers"]),
            )
        )
    return out


def map_data_of(brief_html: str) -> dict:
    """The `map-data` JSON a rendered brief embeds."""
    m = re.search(
        r'<script type="application/json" id="map-data"[^>]*>(.*?)</script>',
        brief_html,
        re.S,
    )
    if m is None:
        raise ValueError("the brief embeds no map-data")
    return json.loads(m.group(1))


def _interval(valid_time: str) -> tuple[datetime, datetime]:
    start_s, dur_s = valid_time.split("/")
    start = datetime.fromisoformat(start_s)
    m = _DURATION.fullmatch(dur_s)
    if m is None:
        raise ValueError(f"unparsed ISO 8601 duration {dur_s!r}")
    days, hours = (int(g) if g else 0 for g in m.groups())
    return start, start + timedelta(days=days, hours=hours)


def forecast_hours(seed: dict, start: datetime, n: int, cfg: dict) -> list[dict]:
    """The gridpoint forecast's layers at each hour from `start` (UTC), as held; a
    missing hour is a refusal naming it."""
    props = seed["properties"]
    rows = []
    for k in range(n):
        t = start + timedelta(hours=k)
        row: dict = {"time": t}
        for name in FORECAST_LAYERS:
            row[name] = None
            for v in (props.get(name) or {}).get("values") or []:
                a, b = _interval(v["validTime"])
                if a <= t < b:
                    row[name] = v["value"]
                    break
            if row[name] is None:
                raise Refusal(
                    cfg["refusals"]["forecast_short"].format(
                        detail=f"no {name} at {t.isoformat()}"
                    )
                )
        rows.append(row)
    return rows


def check_dry(seed: dict, start: datetime, end: datetime, cfg: dict) -> None:
    """A refusal unless every quantitativePrecipitation interval over [start, end) is
    zero (the record is dry only; Part C item 13)."""
    layer = (seed["properties"].get("quantitativePrecipitation") or {}).get("values")
    if not layer:
        raise Refusal(
            cfg["refusals"]["missing"].format(
                detail="the forecast's quantitativePrecipitation"
            )
        )
    seen = False
    for v in layer:
        a, b = _interval(v["validTime"])
        if a < end and b > start:
            seen = True
            if v["value"] is None or float(v["value"]) != 0.0:
                raise Refusal(
                    cfg["refusals"]["wet"].format(
                        detail=f"{v['value']!r} mm over {v['validTime']}"
                    )
                )
    if not seen:
        raise Refusal(
            cfg["refusals"]["forecast_short"].format(
                detail=f"no quantitativePrecipitation over {start.isoformat()}"
            )
        )


# ── the source ───────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class JetSource:
    rate_kg_s: float
    duration_s: float
    air_kg_s: float
    volume_flux_m3_s: float
    speed_m_s: float
    area_m2: float
    sigma_h_m: float
    sigma_z_m: float
    cone_length_m: float
    buoyancy_k_m3_s: float
    gas_density_kg_m3: float

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def jet_source(problem: dict, k: dict) -> JetSource:
    """The two-phase jet as a SCIPUFF continuous source (the module docstring's method;
    HB-165's probe, unchanged); `problem` is one SLAB problem (`read_deck`)."""
    if int(problem["idspl"]) != 2:
        raise Refusal(
            "not modelled: the release is not a two-phase jet (SLAB IDSPL "
            f"{problem['idspl']:.0f}); a pool source is not converted here"
        )
    r, p = k["gas_constant_j_mol_k"], k["ambient_pressure_pa"]
    m_air, cp_air = k["air_molar_mass_kg_mol"], k["air_cp_j_kg_k"]
    q, liq, hv = problem["qs"], problem["cmedo"], problem["dhe"]
    tb, ta, wms = problem["tbp"], problem["ta"], problem["wms"]
    if ta <= tb:
        raise Refusal(
            f"not modelled: air at {ta} K is not warmer than the boiling point {tb} K"
        )
    rho_v_b = p * wms / (r * tb)
    rho_air_b = p * m_air / (r * tb)
    air = liq * q * hv / (cp_air * (ta - tb))
    volume = q / rho_v_b + air / rho_air_b
    rho_m = 1.0 / ((1.0 - liq) / rho_v_b + liq / problem["rhosl"])
    u0 = q / (rho_m * problem["as"])
    speed = q * u0 / (q + air)
    area = volume / speed
    b = math.sqrt(area / (2.0 * math.pi))  # pi * a * b = area with a = 2 b
    a = 2.0 * b
    r0 = math.sqrt(problem["as"] / math.pi)
    cone = (math.sqrt(area / math.pi) - r0) / math.tan(
        math.radians(k["cone_half_angle_deg"])
    )
    frac = k["sigma_over_radius"]
    return JetSource(
        rate_kg_s=q,
        duration_s=problem["tsd"],
        air_kg_s=air,
        volume_flux_m3_s=volume,
        speed_m_s=speed,
        area_m2=area,
        sigma_h_m=frac * a,
        sigma_z_m=frac * b,
        cone_length_m=cone,
        buoyancy_k_m3_s=(tb - ta) * volume,
        gas_density_kg_m3=p * wms / (r * ta),
    )


# ── the project ──────────────────────────────────────────────────────────────────────


def _q(s: str) -> str:
    return "'" + s.replace("'", " ") + "'"


def at_name(name: str) -> str:
    """The MSC file's file reference, `@NNNname` (user's guide Figure 3)."""
    return f"@{len(name):03d}{name}"


def local_km(lat0: float, lon0: float, lat: float, lon: float) -> tuple[float, float]:
    """(east, north) km of a point in the azimuthal equidistant frame about the site
    (the frame `geometry.offset` writes back)."""
    g = _WGS84.Inverse(lat0, lon0, lat, lon)
    az = math.radians(g["azi1"])
    return g["s12"] * math.sin(az) / 1000.0, g["s12"] * math.cos(az) / 1000.0


def surface_file(series: list[dict], with_zi: bool, pgt: float | None = None) -> str:
    """A SCIPUFF SURFACE observation file (user's guide section 4.5.1): one station at
    the project origin, hour-ending UTC records; ZI (m) when `with_zi`; the stability
    class as PGT (A = 1 ... G = 7, footnote 5) when `pgt` is given (HB-169)."""
    cols = "ID      YYMMDD  HOUR    X       Y       WSPD    DIR     T       Q       FCC"
    units = (
        "NONE            HOURS   KM      KM      M/S             C       %       NONE"
    )
    n = 10
    if with_zi:
        cols += "     ZI"
        units += "    M"
        n += 1
    if pgt is not None:
        cols += "     PGT"
        units += "    NONE"
        n += 1
    lines = ["SURFACE", str(n), cols, units, "-999"]
    for rec in series:
        t = rec["time"]
        hour = t.hour if t.hour != 0 else 24
        day = t if t.hour != 0 else t - timedelta(days=1)
        ln = (
            f"99001 {day:%y%m%d} {hour:2d}    0.00    0.00 {rec['speed_m_s']:5.2f} "
            f"{rec['direction_deg']:5.0f}. {rec['temperature_c']:5.1f} "
            f"{rec['rh_pct']:5.1f} {rec['cloud_frac']:5.2f}"
        )
        if with_zi:
            ln += f" {rec['mixing_height_m']:7.1f}"
        if pgt is not None:
            ln += f" {pgt:7.2f}"
        lines.append(ln)
    return "\n".join(lines) + "\n"


def cone_end_km(src: JetSource, wind_from_deg: float) -> tuple[float, float]:
    """(east, north) km of the end of the source's cone, downwind of the breach along a
    wind from `wind_from_deg` (HB-177; technical documentation section 13.4: the source
    is initialised at the downstream location where the aerosol has evaporated)."""
    to = math.radians(wind_from_deg + 180.0)
    return (
        src.cone_length_m * math.sin(to) / 1000.0,
        src.cone_length_m * math.cos(to) / 1000.0,
    )


def run_hours(src: JetSource, wind_m_s: float, cfg: dict) -> int:
    """The release plus the transit to the domain's edge at the release hour's wind,
    in whole hours within the configured bounds."""
    p = cfg["project"]
    transit = p["half_width_km"] * 1000.0 / max(wind_m_s, 0.1)
    h = math.ceil((src.duration_s + transit) / 3600.0)
    return int(min(max(h, p["run_hours_min"]), p["run_hours_max"]))


def build_request(
    problem: dict,
    seed: dict,
    *,
    lat: float,
    lon: float,
    release: datetime,
    tiers: list[Tier],
    places: list[Place],
    cfg: dict,
    material: str,
    label: str,
    tzone: float,
    overrides: dict | None = None,
    turn: dict | None = None,
    lines: dict | None = None,
    extract: bool = True,
    vertical: dict | None = None,
) -> dict:
    """The request `scichem_driver` runs, with `meta`: every input used, the
    assumptions kept, the tiers, the points and the output times.

    `vertical` ({"vres_m", "zmax_m"}; HB-189, `project.stable_vertical` or its
    fallback) sets the vertical setting (VRES) and the domain top (ZMAX); absent, the
    request is byte-identical to one built before HB-189.

    `overrides` sets met values (`albedo`, `bowen`, `z0_m`, `bl_type`,
    `use_forecast_mixing_height`, `ensm_type`) and `source_at_cone_end` (HB-177) for
    a sensitivity run; `turn`
    ({"deg", "after_h"}) seeds a wind turn (a test, not a forecast); `lines`
    ({"distances_m", "points", "min_half_width_m", "half_width_frac",
    "column_heights_m", "height_m"}) adds crosswind lines and columns along the
    release hour's wind for the comparison with SLAB (HB-167 Part A)."""
    p, m, rc = cfg["project"], dict(cfg["met"]), cfg["record"]
    over = dict(overrides or {})
    for key in (
        "albedo",
        "bowen",
        "bl_type",
        "use_forecast_mixing_height",
        "stable_bl_from_class",
    ):
        if key in over:
            m[key] = over.pop(key)
    for key in ("ensm_type", "uu_ensm", "sl_ensm"):
        if key in over:
            m[key] = over.pop(key)
    z0 = float(over.pop("z0_m", problem["z0"]))
    static = bool(over.pop("static", p["static"]))
    at_cone_end = bool(over.pop("source_at_cone_end", p["source_at_cone_end"]))
    if over:
        raise ValueError(f"unknown overrides {sorted(over)}")
    release = release.astimezone(timezone.utc)
    src = jet_source(problem, cfg["constants"])
    first = forecast_hours(seed, release, 1, cfg)[0]
    hours = run_hours(src, float(first["windSpeed"]) / 3.6, cfg)
    # HB-177: the source at the cone's end (scichem.yaml project.source_at_cone_end);
    # off, the line is written as it always was, so the request is byte-identical
    xrel_line = " XREL = 0.0, YREL = 0.0,"
    offset = None
    if at_cone_end:
        offset = cone_end_km(src, float(first["windDirection"]))
        xrel_line = f" XREL = {offset[0]:.6f}, YREL = {offset[1]:.6f},"
    met_start = release - timedelta(hours=p["met_hours_before_release"])
    n_met = p["met_hours_before_release"] + hours + 2
    rows = forecast_hours(seed, met_start, n_met, cfg)
    end = release + timedelta(hours=hours)
    check_dry(seed, release, end, cfg)
    series = []
    for row in rows:
        wdir = float(row["windDirection"])
        if turn and row["time"] >= release + timedelta(hours=turn["after_h"]):
            wdir = (wdir + float(turn["deg"])) % 360.0
        series.append(
            {
                "time": row["time"],
                "speed_m_s": float(row["windSpeed"]) / 3.6,  # wmoUnit:km_h-1
                "direction_deg": wdir,
                "temperature_c": float(row["temperature"]),
                "rh_pct": float(row["relativeHumidity"]),
                "cloud_frac": float(row["skyCover"]) / 100.0,
                "mixing_height_m": float(row["mixingHeight"]),
            }
        )
    with_zi = bool(m["use_forecast_mixing_height"])
    # HB-169: a stable-class release takes the documented PGT boundary layer
    # (scichem.yaml met.stable_bl_from_class says why); the class is the SLAB deck's
    # STAB, the brief's own stability class
    stable = None
    if m.get("stable_bl_from_class"):
        stable = (m.get("stable_classes") or {}).get(int(round(float(problem["stab"]))))
    if stable is not None:
        if with_zi:
            raise ValueError(
                "the stability class's boundary layer (PGT, technical documentation "
                "Table 3) and the forecast mixing height (OPER) are two routes; a "
                "request takes one"
            )
        m["bl_type"] = "OBS"
    pgt = float(round(float(problem["stab"]))) if stable is not None else None
    name = p["name"]
    hw = float(p["half_width_km"])
    sensors: list[tuple[float, float, float, str]] = []
    for pl in places:
        x, y = local_km(lat, lon, pl.lat, pl.lon)
        sensors.append((x, y, float(rc["point_height_m"]), f"place:{pl.id}"))
    if lines:
        to = math.radians(float(first["windDirection"]) + 180.0)
        ux, uy = math.sin(to), math.cos(to)
        vx, vy = -uy, ux
        for d in lines["distances_m"]:
            half = max(lines["min_half_width_m"], lines["half_width_frac"] * d)
            n = int(lines["points"])
            for j in range(n):
                c = -half + 2.0 * half * j / (n - 1)
                sensors.append(
                    (
                        (d * ux + c * vx) / 1000.0,
                        (d * uy + c * vy) / 1000.0,
                        float(lines["height_m"]),
                        f"line:{d}:{j}",
                    )
                )
            for z in lines["column_heights_m"]:
                sensors.append(
                    (d * ux / 1000.0, d * uy / 1000.0, float(z), f"col:{d}:{z}")
                )
    # HB-189: the stable treatment's vertical setting, the namelist's VRES beside ZMAX
    zmax = p["zmax_m"] if vertical is None else float(vertical["zmax_m"])
    vres_line = "" if vertical is None else f" VRES = {float(vertical['vres_m'])},\n"
    sam = [f"SCIPUFF SENSOR OUTPUT {p['dt_smp_s']:g} SEC"]
    for x, y, z, _ in sensors:
        sam.append(f"{x:10.4f} {y:10.4f} {z:8.2f}  CONC {material}")
    inp = f""" &CTRL
 RESTART = F,
 /
 &TIME1
 YEAR_START = {release.year}, MONTH_START = {release.month}, DAY_START = {release.day},
 TSTART = {release.hour + release.minute / 60.0:.4f}, TZONE = {tzone:g}, LOCAL = F
 /
 &TIME2
 YEAR_END = {end.year}, MONTH_END = {end.month}, DAY_END = {end.day},
 TEND = {end.hour + end.minute / 60.0:.4f}, TEND_HR = {hours:.1f},
 DELT = {p["delt_s"]}, DT_SAVE = {p["dt_save_s"]}
 /
 &FLAGS
 TITLE = {_q(label)},
 CREATE = T,
 AUDIT_ANALYST = 'hazbrief',
 DYNAMIC = T,
 DENSE_GAS = T,
 STATIC = {"T" if static else "F"},
 HAZAREA = 'OFF',
 RUN_MODE = 0
 /
 &DOMAIN
 CMAP = 'CARTESIAN',
 XMIN = {-hw}, XMAX = {hw},
 YMIN = {-hw}, YMAX = {hw},
 ZMAX = {zmax},
{vres_line} XREF = 0.0, YREF = 0.0,
 LON0 = {lon:.6f}, LAT0 = {lat:.6f}
 /
 &OPTIONS
 SMPFILE = {_q(name + ".sam")},
 DT_SMP = {p["dt_smp_s"]}
 /
 &MATDEF
 CLASS = {_q(cfg["material"]["class"])},
 MNAME = {_q(material)},
 UNITS = 'kg',
 FILE_NAME = ' ',
 FILE_PATH = ' ',
 GROUP_DEPOSITION = F,
 GROUP_DOSE = T,
 MULTI_COMP = F,
 DENSITY = {src.gas_density_kg_m3:.4f},
 GAS_DEPOSITION = {cfg["material"]["gas_deposition"]}
 /
"""
    scn = f""" &SCN
 RELNAME = {_q(label[:32])},
 TREL = 0.0,
{xrel_line}
 ZREL = {p["release_height_m"]},
 CMASS = {src.rate_kg_s:.6f},
 TDUR = {src.duration_s / 3600.0:.6f},
 SIZE = 0.0,
 SIGY = {src.sigma_h_m:.4f},
 SIGZ = {src.sigma_z_m:.4f},
 WMOM = 0.0,
 BUOY = {src.buoyancy_k_m3_s:.3f},
 RELTYP = 'C',
 RELMAT = {_q(material)}
 /
{SCN_TRAILER}
"""
    ensm = str(m["ensm_type"])
    ensm_lines = ""
    if ensm == "INPUT":
        ensm_lines = f" UU_ENSM = {m['uu_ensm']},\n SL_ENSM = {m['sl_ensm']},\n"
    msc = f""" &MET
 MET_TYPE = {_q(m["met_type"])},
 BL_TYPE = {_q(m["bl_type"])},
 ENSM_TYPE = {_q(ensm)},
{ensm_lines} ZRUF = {z0},
 H_CNP = {m["canopy_height_m"]},
 ALBEDO = {m["albedo"]},
 BOWEN = {m["bowen"]},
 CLOUD_COVER = {series[p["met_hours_before_release"]]["cloud_frac"]},
 LOCAL_MET = F,
 LMC_UA = F,
 PR_TYPE = 'NONE',
 TBIN_MET = {m["tbin_met_s"]}
 /
   1 {at_name(name + ".sfc")}
"""
    dt_save = float(p["dt_save_s"])
    times_h = [k * dt_save / 3600.0 for k in range(1, int(hours * 3600 / dt_save) + 1)]
    ex = []
    if extract:
        levels = [t.kg_m3 for t in tiers]
        for k, th in enumerate(times_h):
            ex.append(
                {"name": f"m_{k:03d}", "kind": "mean", "time_h": th, "levels": levels}
            )
            for pct in rc["probability_percent"]:
                ex.append(
                    {
                        "name": f"x{int(round(pct * 10)):03d}_{k:03d}",
                        "kind": "exceedance",
                        "percent": float(pct),
                        "time_h": th,
                        "levels": levels,
                    }
                )
    assumptions = dict(cfg["assumptions"])
    if stable is not None:
        assumptions["boundary_layer"] = (
            f"BL_TYPE OBS with the brief's stability class {stable['class']} as PGT "
            f"{pgt:g} (technical documentation Table 3: L {stable['l_m']} m, zi "
            f"{stable['zi_m']} m), the class SLAB reads, so both engines read one "
            "stability; chosen over the calculated layer (CALC) on the published "
            "stable benchmark (DN-028 ADDENDUM-03)"
        )
    elif m["bl_type"] != "CALC" or with_zi:
        assumptions["boundary_layer"] = f"BL_TYPE {m['bl_type']}" + (
            ", ZI from the forecast's mixingHeight" if with_zi else ""
        )
    if ensm != "NONE":
        assumptions["large_scale"] = (
            f"ENSM_TYPE {ensm}, UU_ENSM {m['uu_ensm']} m2/s2, SL_ENSM {m['sl_ensm']} m"
        )
    if offset is not None:
        assumptions["source_position"] = (
            "the source starts at the end of its 7 degree cone, "
            f"{src.cone_length_m:.0f} m downwind of the breach along the release "
            "hour's wind (technical documentation section 13.4); nothing is computed "
            "inside the cone (HB-177)"
        )
    if m["albedo"] != cfg["met"]["albedo"]:
        assumptions["albedo"] = f"albedo {m['albedo']} (a sensitivity run)"
    if m["bowen"] != cfg["met"]["bowen"]:
        assumptions["bowen"] = f"Bowen ratio {m['bowen']} (a sensitivity run)"
    files = {
        name + ".inp": inp,
        name + ".scn": scn,
        name + ".msc": msc,
        name + ".sfc": surface_file(series, with_zi, pgt),
        name + ".sam": "\n".join(sam) + "\n",
    }
    return {
        "project": name,
        "files": files,
        "extract": ex,
        # HB-189 (DN-028 ADDENDUM-14 decision 4): the stable treatment's run is read
        # hour by hour (`scichem_driver`); absent otherwise, so a request built before
        # HB-189 is byte-identical
        **({"hourly": True} if vertical is not None else {}),
        "meta": {
            "label": label,
            "site": {"lat": lat, "lon": lon},
            "release_utc": release.isoformat(),
            "tzone": tzone,
            "run_hours": hours,
            "times_h": times_h,
            "dt_smp_s": p["dt_smp_s"],
            "plane_height_m": rc["plane_height_m"],
            "point_height_m": rc["point_height_m"],
            "probability_percent": list(rc["probability_percent"]),
            "tiers": [t.as_dict() for t in tiers],
            "places": [pl.as_dict() for pl in places],
            "sensors": [s[3] for s in sensors],
            "source": src.as_dict(),
            "slab_problem": {k: problem[k] for k in sorted(problem)},
            "met": [{**r, "time": r["time"].isoformat()} for r in series],
            "inputs": {
                "z0_m": z0,
                "albedo": m["albedo"],
                "bowen": m["bowen"],
                "bl_type": m["bl_type"],
                "use_forecast_mixing_height": with_zi,
                "ensm_type": ensm,
                "domain_half_width_km": hw,
                "material_class": cfg["material"]["class"],
                # HB-169: present only when the class's layer is used, so a request
                # built without it is byte-identical to one recorded before
                **(
                    {"stability_class": stable["class"], "pgt": pgt}
                    if stable is not None
                    else {}
                ),
                # HB-189: present only with a stated vertical setting
                **(
                    {
                        "vertical_setting_m": float(vertical["vres_m"]),
                        "domain_top_m": float(vertical["zmax_m"]),
                    }
                    if vertical is not None
                    else {}
                ),
                # HB-177: present only with the source at the cone's end
                **(
                    {"source_offset_km": [offset[0], offset[1]]}
                    if offset is not None
                    else {}
                ),
            },
            "assumptions": assumptions,
            "turn": turn,
        },
    }


def tzone_of(local: datetime) -> float:
    """SCICHEM's TZONE for a local time: its convention is the local midnight in UTC
    hours, as the TVA example writes CST (UTC-6) as 18 (HB-165); EDT (UTC-4) is 20."""
    off = (local.utcoffset() or timedelta()).total_seconds() / 3600.0
    return off % 24.0


def request_sha256(request: dict) -> str:
    return hashlib.sha256(
        json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


# ── the run ──────────────────────────────────────────────────────────────────────────


#: HB-189 (DN-028 ADDENDUM-14 decision 4): where each hour of an hourly run goes the
#: moment the driver has read it from the puff file (a live build's event stream sets
#: it; `None`, nothing is told). Called with the driver's row (`hour`,
#: `engine_wall_s`, `shown_wall_s`, `extracted`) from the thread reading the engine.
HOUR_SINK: contextvars.ContextVar[Callable[[dict], None] | None] = (
    contextvars.ContextVar("scichem_hour_sink", default=None)
)


#: HB-192 (DN-024 ADDENDUM-01): where each 15-minute frame of a run with frames goes the
#: moment the driver has written its mesh (a live build sets it; `None`, nothing is
#: told). Called with the driver's frame row (`frame_s`, the walls, the mesh) from the
#: thread reading the engine.
FRAME_SINK: contextvars.ContextVar[Callable[[dict], None] | None] = (
    contextvars.ContextVar("scichem_frame_sink", default=None)
)


def _call_streaming(
    argv: list[str],
    stdin: bytes,
    timeout_s: float,
    sink,
    frames: list[dict] | None = None,
) -> tuple[int | None, bytes, bytes]:
    """Run `argv` with `stdin`, handing each hourly line of its stdout (a JSON object
    with `hour` and no `runsci`) to `sink` as it is read; (exit code, the last stdout
    line, stderr). Past `timeout_s` the process is killed and the exit code is None,
    which the caller refuses with the engine's words.

    HB-192: each frame line (`frame_s`) is appended to `frames`, when given, and handed
    to `FRAME_SINK` as it is read."""
    fsink = FRAME_SINK.get()
    proc = subprocess.Popen(
        argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    err: list[bytes] = []
    reader = threading.Thread(
        target=lambda: err.append(proc.stderr.read()), daemon=True
    )
    reader.start()
    killed = threading.Event()

    def kill() -> None:
        killed.set()
        proc.kill()

    timer = threading.Timer(timeout_s, kill)
    timer.start()
    last = b""
    try:
        proc.stdin.write(stdin)
        proc.stdin.close()
        for raw in proc.stdout:
            line = raw.strip()
            if not line:
                continue
            last = line
            if line.startswith(b'{"') and b'"runsci"' not in line:
                row = json.loads(line)
                if "hour" in row and sink is not None:
                    sink(row)
                elif "frame_s" in row:
                    if frames is not None:
                        frames.append(row)
                    if fsink is not None:
                        fsink(row)
        rc = proc.wait()
    finally:
        timer.cancel()
    reader.join()
    if killed.is_set():
        return None, last, b"".join(err) + b"\nthe engine did not finish in time"
    return rc, last, b"".join(err)


def run_request(
    request: dict,
    cfg: dict,
    *,
    argv: list[str] | None = None,
    frames: dict | None = None,
    frame_rows: list[dict] | None = None,
) -> tuple[dict, str, str]:
    """(response, engine_kind, engine_id) from the models image, or from `argv` (a
    development command reading the request on stdin). A missing image or docker, or
    a driver refusal, is a `Refusal`.

    HB-189: a request with `hourly` (the stable treatment's, `stable_request`) is read
    hour by hour by the driver; each hour's line is handed to the hour sink
    (`HOUR_SINK`, set by a live build) the moment it is read, and the engine's call is
    bounded by `project.stable_vertical.timeout_s` instead of `timeout_s`.

    HB-192: `frames` (`frames.spec`) asks the driver for a frame every 15 minutes; it is
    sent beside the request, never in it, so the request and its record's name do not
    change. Each frame row is appended to `frame_rows` and handed to `FRAME_SINK`."""
    timeout = float(cfg["timeout_s"])
    body = {k: request[k] for k in ("project", "files", "extract")}
    if frames is not None:
        body["frames"] = frames
    env_args: list[str] = []
    if request.get("hourly"):
        body["hourly"] = True
        timeout = float(cfg["project"]["stable_vertical"]["timeout_s"])
        env_args = [
            "-e",
            f"SCICHEM_TIMEOUT_S={timeout:g}",
            "-e",
            f"SCICHEM_HOURLY_POLL_S={float(cfg['project']['hourly_poll_s']):g}",
        ]
    if argv is None:
        docker = shutil.which(cfg["docker"])
        if docker is None:
            raise Refusal(
                cfg["refusals"]["no_image"].format(
                    image=cfg["image"], detail=f"{cfg['docker']} is not installed"
                )
            )
        entry = list(cfg["entry"])
        argv = [
            docker,
            "run",
            "--rm",
            "-i",
            "--network",
            "none",
            "--pull",
            "never",
            *env_args,
            "--entrypoint",
            entry[0],
            cfg["image"],
            *entry[1:],
        ]
        kind = "image"
    else:
        kind = "command"
    rc, out, err = _call_streaming(
        argv,
        json.dumps(body).encode("utf-8"),
        timeout * 4,
        HOUR_SINK.get(),
        frame_rows,
    )
    if rc != 0:
        last = err.decode("latin-1").strip().splitlines()[-1:]
        detail = " ".join(last) or f"exit {rc}"
        if kind == "image" and rc == 125:
            raise Refusal(
                cfg["refusals"]["no_image"].format(image=cfg["image"], detail=detail)
            )
        raise Refusal(cfg["refusals"]["engine"].format(detail=detail))
    resp = json.loads(out)
    if kind == "image":
        ins = subprocess.run(
            [argv[0], "image", "inspect", "--format", "{{.Id}}", cfg["image"]],
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        engine_id = ins.stdout.decode().strip()
    else:
        engine_id = "command " + " ".join(argv)
    return resp, kind, engine_id


# ── the output ───────────────────────────────────────────────────────────────────────


@dataclass
class Smp:
    names: list[str]
    times: list[float]
    rows: list[list[float]]

    def column(self, name: str) -> list[float]:
        i = self.names.index(name)
        return [r[i] for r in self.rows]


def read_smp(text: str) -> Smp:
    """A sensor output file: '#' header lines, one column-name row, then one row per
    output time (time in seconds after the start, then C/V/T per sensor)."""
    body = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
    if not body:
        raise ValueError("the sensor file has no column row")
    names = body[0].split()
    rows = [[float(v) for v in ln.split()] for ln in body[1:]]
    return Smp(names, [r[0] for r in rows], rows)


def clipped_normal_from_moments(
    mean: float, var: float, iters: int = 200
) -> tuple[float, float]:
    """The Gaussian (mu, sigma) whose clipped normal has the given mean and variance
    (technical documentation section 12.2.1; Lewellen and Sykes 1986)."""
    if mean <= 0.0:
        return 0.0, 0.0
    if var <= 0.0:
        return mean, 0.0
    ratio = math.sqrt(var) / mean

    def moments(t: float) -> tuple[float, float]:
        phi = math.exp(-0.5 * t * t) / math.sqrt(2.0 * math.pi)
        big = 0.5 * math.erfc(-t / math.sqrt(2.0))
        m = t * big + phi
        m2 = (t * t + 1.0) * big + t * phi
        return m, m2 - m * m

    lo, hi = -30.0, 30.0
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        m, v = moments(mid)
        if m <= 0.0 or math.sqrt(max(v, 0.0)) / m > ratio:
            lo = mid
        else:
            hi = mid
    t = 0.5 * (lo + hi)
    m, _ = moments(t)
    sigma = mean / m
    return t * sigma, sigma


def exceedance(mean: float, var: float, level: float) -> float:
    """P(C > level) under the clipped normal of `mean` and `var`."""
    mu, sigma = clipped_normal_from_moments(mean, var)
    if sigma == 0.0:
        return 1.0 if mu > level else 0.0
    return 0.5 * math.erfc((level - mu) / (sigma * math.sqrt(2.0)))


def read_overlay(text: str) -> dict[float, list[list[tuple[float, float]]]]:
    """A SCIPUFF overlay (`.ovl`): per `#CONTOUR <level>` block, its `!LINE`
    polylines of (x, y) project km."""
    out: dict[float, list[list[tuple[float, float]]]] = {}
    level = None
    line: list[tuple[float, float]] | None = None
    for raw in text.splitlines():
        s = raw.strip()
        if s.startswith("#CONTOUR"):
            level = float(s.split()[1])
            out.setdefault(level, [])
            line = None
        elif s.startswith("!LINE"):
            if level is None:
                raise ValueError("an overlay line before any #CONTOUR")
            line = []
            out[level].append(line)
        elif s and not s.startswith(("#", "!")) and line is not None:
            x, y = s.split()[:2]
            line.append((float(x), float(y)))
    return out


def contour_shape(
    lines: list[list[tuple[float, float]]],
    box: float | None = None,
    max_box_fraction: float | None = None,
):
    """The area a contour's closed lines bound, holes by the even-odd rule. A line the
    post-processor writes twice (measured: csx day's AEGL-1 contour at 135 minutes)
    counts once, or the even-odd rule would cancel it. So does a piece of a line
    written again: where a contour leaves the domain the post-processor writes the open
    line more than once, as overlapping pieces, each shorter one a run of a longer
    one's points (measured: csx night's AEGL-1 at 250 minutes on the PGT layer, HB-172).

    An open line is closed by its chord, which is the grid's edge when both its ends
    lie on one edge. `box` is the grid's half-width (km): a line whose ends lie on two
    different edges is closed along them, through the corner, on its smaller side
    (`_edge_closed`; HB-172, measured at csx night's AEGL-1 at 300 minutes). The
    smaller side is the cloud's while the area above the level is under half the grid;
    a level that needed such a closure and comes out over `max_box_fraction` of the
    grid (scichem.yaml record.edge_closure_max_box_fraction) is refused."""
    shape = Polygon()
    seen: set[frozenset] = set()
    closed_at_edge = False
    edge = {}
    if box:
        rc = _record_config()
        edge["spacing"] = float(rc["edge_closure_vertex_spacing_km"])
        if max_box_fraction is None:
            max_box_fraction = float(rc["edge_closure_max_box_fraction"])
    for ln in _drop_retraced_pieces(lines):
        if len(ln) < 3:
            continue
        key = frozenset((round(x, 6), round(y, 6)) for x, y in ln)
        if key in seen:
            continue
        seen.add(key)
        got = _edge_closed(ln, box, edge["spacing"]) if box else None
        if got is None:
            poly = Polygon(ln).buffer(0)
        else:
            poly, chose = got
            closed_at_edge = closed_at_edge or chose
        if not poly.is_empty:
            shape = _polygonal(shape.symmetric_difference(poly))
    if closed_at_edge:
        if shape.area > max_box_fraction * (2 * box) ** 2:
            raise Refusal(
                "not modelled: a contour leaves the domain's edge and its area, "
                f"{shape.area:.0f} km2, is past {max_box_fraction:g} of the grid, so "
                "which side of the edge is the cloud's is not known"
            )
    return shape


def _edges(p: tuple[float, float], box: float) -> set[str]:
    """The grid edges (S, E, N, W) point `p` lies on, within a millimetre."""
    x, y = p
    tol = 1e-6
    out = set()
    if abs(y + box) <= tol:
        out.add("S")
    if abs(x - box) <= tol:
        out.add("E")
    if abs(y - box) <= tol:
        out.add("N")
    if abs(x + box) <= tol:
        out.add("W")
    return out


def _perimeter_t(p: tuple[float, float], box: float) -> float:
    """Where `p`, on the grid's edge, lies along its perimeter, counter-clockwise from
    the south-west corner (0 to 8 box)."""
    x, y = p
    e = _edges(p, box)
    if "S" in e:
        return x + box
    if "E" in e:
        return 2 * box + (y + box)
    if "N" in e:
        return 4 * box + (box - x)
    return 6 * box + (box - y)


def _edge_closed(
    ln: list[tuple[float, float]], box: float, spacing: float
) -> tuple[Polygon, bool] | None:
    """An open line whose two ends lie on the grid's edge, closed along that edge, and
    whether the closure chose a side: None for any other line (closed, or an end off
    the edge).

    - Both ends on one edge: closed along that edge between them, the side the chord
      bounds (as a chord closed it before HB-172).
    - Ends on two different edges: closed through the corners between them, on the side
      of smaller area. The overlay carries no orientation that says which side is above
      the level (every closed ring, holes included, is written counter-clockwise), so
      the smaller side is taken (`contour_shape` refuses a level past its bound).

    The walk along the edge carries a vertex at every `spacing` km of the perimeter,
    counted from the south-west corner (record.edge_closure_vertex_spacing_km), so every
    closure shares its edge vertices and the edge, mapped to longitude and latitude
    point by point, follows the grid's edge in every step and in their union."""
    a, b = ln[0], ln[-1]
    if a == b:
        return None
    ea, eb = _edges(a, box), _edges(b, box)
    if not ea or not eb:
        return None
    corners = [(-box, -box), (box, -box), (box, box), (-box, box)]
    per = 8 * box
    ta, tb = _perimeter_t(a, box), _perimeter_t(b, box)

    def at(t: float) -> tuple[float, float]:
        # the perimeter point at t, counter-clockwise from the south-west corner
        t %= per
        side, u = int(t // (2 * box)), t % (2 * box)
        x0, y0 = corners[side]
        dx, dy = ((1, 0), (0, 1), (-1, 0), (0, -1))[side]
        return (x0 + dx * u, y0 + dy * u)

    def walk(step: int) -> tuple[list[tuple[float, float]], int]:
        # from the line's end (b) to its start (a), along the perimeter: every corner
        # passed and every whole `spacing` of the perimeter between; and how many
        # corners it passes
        span = (ta - tb) % per if step > 0 else (tb - ta) % per
        cs = {
            (2 * box * k - tb) % per if step > 0 else (tb - 2 * box * k) % per
            for k in range(4)
        }
        cs = {d for d in cs if 0 < d < span}
        k0 = math.floor(tb / spacing)
        grid = set()
        k = k0 + (1 if step > 0 else 0)
        while True:
            d = (k * spacing - tb) * step
            if d >= span:
                break
            if d > 0:
                grid.add(d)
            k += step
        pts = [at(tb + step * d) for d in sorted(cs | grid)]
        return pts, len(cs)

    walks = [walk(s) for s in (1, -1)]
    if ea & eb:
        pts = next((w for w, n in walks if n == 0), None)
        if pts is None:
            return None
        return Polygon([*ln, *pts]).buffer(0), False
    sides = [Polygon([*ln, *w]).buffer(0) for w, _ in walks]
    return min(sides, key=lambda g: g.area), True


def _drop_retraced_pieces(
    lines: list[list[tuple[float, float]]],
) -> list[list[tuple[float, float]]]:
    """`lines` without each open line whose points (to the micrometre, either way
    round) are a contiguous run of a longer line's: the same line traced again in part.
    Equal lines are left to `contour_shape`'s own duplicate rule; a closed ring is
    never dropped here."""
    keys = [tuple((round(x, 6), round(y, 6)) for x, y in ln) for ln in lines]

    def _inside(short: tuple, long: tuple) -> bool:
        n = len(short)
        return any(
            long[i : i + n] == run
            for run in (short, short[::-1])
            for i in range(len(long) - n + 1)
        )

    out = []
    for i, ln in enumerate(lines):
        k = keys[i]
        closed = len(k) > 1 and k[0] == k[-1]
        if not closed and any(
            len(other) > len(k) and _inside(k, other)
            for j, other in enumerate(keys)
            if j != i
        ):
            continue
        out.append(ln)
    return out


def _polygonal(g):
    """The polygon parts of a geometry: a symmetric difference of touching contours can
    return a collection holding lines or points as well (measured: csx night without
    static puffs), which bound no area."""
    if isinstance(g, (Polygon, MultiPolygon)):
        return g
    parts = []
    for p in getattr(g, "geoms", []):
        if isinstance(p, Polygon):
            parts.append(p)
        elif isinstance(p, MultiPolygon):
            parts.extend(p.geoms)
    return unary_union(parts) if parts else Polygon()


def _level_lines(ov: dict, level: float) -> list[list[tuple[float, float]]]:
    for lev, lns in ov.items():
        if abs(lev - level) <= 1e-5 * max(abs(level), 1e-30):
            return lns
    return []


def _rings(shape) -> list[list[list[float]]]:
    """A shape as rings of [x, y] km, three decimals (one metre)."""
    shape = _polygonal(shape)
    polys = (
        list(shape.geoms)
        if isinstance(shape, MultiPolygon)
        else ([shape] if not shape.is_empty else [])
    )
    out = []
    for p in polys:
        rings = [p.exterior, *p.interiors]
        out.append([[[round(x, 3), round(y, 3)] for x, y in r.coords] for r in rings])
    return out


def _grid_half_width(ov: dict) -> float | None:
    """The post-processor's grid half-width (km) as an overlay shows it: the farthest
    coordinate any of its lines reaches, on the edge where an open line ends (the slice
    is the whole domain, `scichem_driver`; ±28.5 km at csx night, ±29.25 km by day on a
    30 km domain). None for an empty overlay."""
    pts = [abs(c) for lns in ov.values() for ln in lns for p in ln for c in p]
    return max(pts) if pts else None


def shape_of(rings: list) -> Polygon | MultiPolygon:
    """The shape `_rings` wrote, each polygon made valid before the union, as the
    brief's own reader does (`cloud._shape`). Rings rounded to the metre can cross
    themselves or collapse a sliver where a contour runs along the domain's edge
    (measured on the night clouds HB-172 re-recorded, and on a probability contour of
    csx day); the record keeps them as written, so a reader repairs them (GEOS
    MakeValid) rather than a union failing with a topology error."""
    polys = [_polygonal(make_valid(Polygon(r[0], r[1:]))) for r in rings if r and r[0]]
    polys = [p for p in polys if not p.is_empty]
    if not polys:
        return Polygon()
    return unary_union(polys)


def to_geojson(rings: list, lat: float, lon: float) -> dict | None:
    """A record's km rings as a GeoJSON geometry about the site."""
    if not rings:
        return None
    polys = [
        [[G.offset(lat, lon, x * 1000.0, y * 1000.0) for x, y in r] for r in poly]
        for poly in rings
    ]
    if len(polys) == 1:
        return {"type": "Polygon", "coordinates": polys[0]}
    return {"type": "MultiPolygon", "coordinates": polys}


def _sig(v: float) -> float:
    return float(f"{v:.4g}")


def derive(request: dict, response: dict) -> dict:
    """The record HB-163 reads, from a request and the engine's response (module
    docstring, step 3). A run that did not finish normally is a refusal."""
    meta = request["meta"]
    run = response.get("runsci") or {}
    if not run.get("normal") or response.get("smp") is None:
        tail = " ".join((run.get("log_tail") or [])[-2:]) or f"exit {run.get('exit')}"
        raise Refusal(f"not modelled: the engine did not finish ({tail})")
    tiers = meta["tiers"]
    pcts = meta["probability_percent"]
    # The engine stops early when every puff has left the domain ("No. Puffs = 0"); the
    # record ends at its last output time, never with steps it did not compute.
    end_h = float(meta["run_hours"])
    left = False
    for ln in run.get("log_tail") or []:
        m = re.search(r"Normal termination detected at Time =\s*([0-9.]+)", ln)
        if m:
            end_h = float(m.group(1))
        if re.search(r"No\. Puffs =\s*0\b", ln):
            left = True
    steps = []
    union: dict[str, list] = {t["name"]: [] for t in tiers}
    for k, th in enumerate(meta["times_h"]):
        if th > end_h + 1e-6:
            break
        step: dict = {"time_s": round(th * 3600.0, 3), "tiers": {}, "probability": {}}
        mean = response["overlays"].get(f"m_{k:03d}")
        if not isinstance(mean, str):
            raise Refusal(f"not modelled: the step {th:g} h has no contour ({mean})")
        ov = read_overlay(mean)
        for t in tiers:
            shape = contour_shape(_level_lines(ov, t["kg_m3"]), _grid_half_width(ov))
            union[t["name"]].append(shape)
            step["tiers"][t["name"]] = {
                "area_km2": round(shape.area, 6),
                "centroid_km": (
                    [round(shape.centroid.x, 4), round(shape.centroid.y, 4)]
                    if not shape.is_empty
                    else None
                ),
                "contains_source": bool(shape.contains(ShPoint(0.0, 0.0))),
                "rings_km": _rings(shape),
            }
        for pct in pcts:
            key = f"{pct:g}"
            xo = response["overlays"].get(f"x{int(round(pct * 10)):03d}_{k:03d}")
            if not isinstance(xo, str):
                raise Refusal(f"not modelled: no exceedance contour at {th:g} h ({xo})")
            xov = read_overlay(xo)
            step["probability"][key] = {}
            for t in tiers:
                shape = contour_shape(
                    _level_lines(xov, t["kg_m3"]), _grid_half_width(xov)
                )
                step["probability"][key][t["name"]] = {
                    "area_km2": round(shape.area, 6),
                    "rings_km": _rings(shape),
                }
        steps.append(step)
    any_time = {}
    for t in tiers:
        shape = unary_union([s for s in union[t["name"]] if not s.is_empty])
        any_time[t["name"]] = {
            "area_km2": round(shape.area, 6) if not shape.is_empty else 0.0,
            "rings_km": _rings(shape) if not shape.is_empty else [],
        }
    smp = read_smp(response["smp"])
    dt = float(meta["dt_smp_s"])
    sensor_ids = meta["sensors"]
    places_out = []
    for i, pl in enumerate(meta["places"]):
        if sensor_ids[i] != f"place:{pl['id']}":
            raise ValueError(f"sensor {i + 1} is {sensor_ids[i]}, not place {pl['id']}")
        c = smp.column(_col(smp, "C", i + 1))
        v = smp.column(_col(smp, "V", i + 1))
        places_out.append(place_record(pl, smp.times, c, v, dt, tiers, meta))
    return {
        "engine_end_s": round(end_h * 3600.0, 3),
        "cloud_left_domain": left,
        "times_s": [s["time_s"] for s in steps],
        "steps": steps,
        "any_time": any_time,
        "places": places_out,
    }


def _col(smp: Smp, prefix: str, i: int) -> str:
    """The column of sensor `i` (1-based): mean C, variance V or scale T. Columns come
    in that triple per sensor, in the sensor file's order, after the time. Their names
    are not a number to rebuild: the engine writes C001..C885 in decimal for 885
    sensors (HB-165) and C001..C3FC in hexadecimal for 1,020 (measured here)."""
    k = 1 + 3 * (i - 1) + "CVT".index(prefix)
    if k >= len(smp.names) or not smp.names[k].startswith(prefix):
        raise KeyError(f"no column {prefix} for sensor {i} in the sensor file")
    return smp.names[k]


def place_record(
    pl: dict,
    times: list[float],
    c: list[float],
    v: list[float],
    dt: float,
    tiers: list[dict],
    meta: dict,
) -> dict:
    """One point's measurement (ADDENDUM-01 item 1): series, peak, tiers, dose."""
    lat0, lon0 = meta["site"]["lat"], meta["site"]["lon"]
    x, y = local_km(lat0, lon0, pl["lat"], pl["lon"])
    peak = max(c) if c else 0.0
    i_peak = c.index(peak) if c else None
    reached = [t["name"] for t in tiers if peak > t["kg_m3"]]
    per = {}
    for t in tiers:
        over = [k for k, val in enumerate(c) if val > t["kg_m3"]]
        pmax = max(
            (exceedance(cm, vv, t["kg_m3"]) for cm, vv in zip(c, v) if cm > 0),
            default=0.0,
        )
        if over:
            per[t["name"]] = {
                "arrival_s": times[over[0]],
                "last_above_s": times[over[-1]],
                "minutes_above": round(len(over) * dt / 60.0, 3),
                "clear_s": times[over[-1]] + dt,
                "max_probability": round(pmax, 4),
            }
        else:
            per[t["name"]] = {
                "arrival_s": None,
                "last_above_s": None,
                "minutes_above": 0.0,
                "clear_s": None,
                "max_probability": round(pmax, 4),
            }
    dose = sum(c) * dt
    tier0 = tiers[0]
    ppm_per_kg = tier0["ppm"] / tier0["kg_m3"]
    return {
        **pl,
        "distance_m": round(math.hypot(x, y) * 1000.0, 1),
        "local_km": [round(x, 4), round(y, 4)],
        "peak_kg_m3": _sig(peak),
        "peak_ppm": _sig(peak * ppm_per_kg),
        "peak_time_s": times[i_peak] if peak > 0 else None,
        "highest_tier": reached[-1] if reached else None,
        "below_lowest_tier": not reached,
        "tiers": per,
        "dose_kg_s_m3": _sig(dose),
        "dose_ppm_min": _sig(dose * ppm_per_kg / 60.0),
        "reached": peak > 0.0,
        "series_mean_kg_m3": [_sig(val) for val in c],
        "series_variance": [_sig(val) for val in v],
    }


# ── the held record ──────────────────────────────────────────────────────────────────


def _pack(response: dict) -> str:
    raw = json.dumps(response, sort_keys=True).encode("utf-8")
    return base64.b64encode(gzip.compress(raw, mtime=0)).decode("ascii")


def unpack(record: dict) -> dict:
    return json.loads(gzip.decompress(base64.b64decode(record["response_gz_b64"])))


def recording_path(cfg: dict, request: dict, root: Path = ROOT) -> Path:
    from hazbrief.brief import live_records

    # HB-207: a served live brief writes a run no task recorded under its live root
    return live_records.resolve(
        root / cfg["recordings_dir"] / f"{request_sha256(request)}.json"
    )


def _for_sink(fr: dict, request: dict, frames: dict) -> dict:
    """HB-192: what a live page is handed for one frame: its minute and outlines (km
    rings), the site they are about, the frame count and the vertical setting; never
    its mesh (DN-024 ADDENDUM-01 decision 6)."""
    meta = request["meta"]
    every = float(frames["every_s"])
    return {
        "minute": fr["minute"],
        "outlines": fr.get("outlines") or {},
        "site": meta["site"],
        "n": int(float(frames["until_s"]) // every),
        "until_min": round(float(frames["until_s"]) / 60.0),
        "vertical_setting_m": (meta.get("inputs") or {}).get("vertical_setting_m"),
    }


def recorded(
    request: dict,
    cfg: dict,
    *,
    record: bool,
    argv: list[str] | None = None,
    root: Path = ROOT,
    frames: dict | None = None,
) -> dict:
    """The held record of `request`: read it, or with `record` run the engine and
    write it. Without `record`, a request not held is a refusal naming the record it
    lacks (the brief never runs the engine itself).

    HB-192: with `frames` (`frames.spec`), a run also writes the frames record
    (`frames.write_record`), each frame handed to `FRAME_SINK` as `frames.stored` keeps
    it the moment it lands; a held record's frames, where held, are handed to the sink
    in the order they landed, as its hours are."""
    path = recording_path(cfg, request, root)
    sha = request_sha256(request)
    if path.exists():
        rec = json.loads(path.read_text(encoding="utf-8"))
        if rec.get("request_sha256") != sha or rec.get("request") != request:
            raise RuntimeError(
                f"{path}: the recorded request is not the one its name hashes"
            )
        # HB-189: a replay hands the hours to the sink in the order they landed, so a
        # replayed live page shows the same hours as the run it replays
        sink = HOUR_SINK.get()
        if sink is not None:
            for row in rec.get("hours") or []:
                sink(row)
        fsink = FRAME_SINK.get()
        if fsink is not None and frames is not None:
            from hazbrief.brief import frames as F

            held = F.read_record(sha, root)
            for fr in (held or {}).get("frames") or []:
                fsink(_for_sink(fr, request, frames))
        return rec
    if not record:
        raise Refusal(
            cfg["refusals"]["not_recorded"].format(
                sha=sha[:12], dir=cfg["recordings_dir"]
            )
        )
    rows: list[dict] = []
    outer = FRAME_SINK.get()
    token = None
    if frames is not None:
        from hazbrief.brief import frames as F

        fcfg = cfg["frames"]

        def convert(row: dict) -> None:
            if outer is not None:
                outer(_for_sink(F.stored(row, request, fcfg), request, frames))

        token = FRAME_SINK.set(convert)
    try:
        response, kind, engine_id = run_request(
            request, cfg, argv=argv, frames=frames, frame_rows=rows
        )
    finally:
        if token is not None:
            FRAME_SINK.reset(token)
    response.pop("frames", None)
    rec = {
        "request_sha256": sha,
        "request": request,
        "engine_kind": kind,
        "engine_id": engine_id,
        "wall_s": response.get("wall_s"),
        "response_gz_b64": _pack(response),
    }
    if request.get("hourly"):
        # HB-189 (DN-028 ADDENDUM-14 decision 4): when each hour was whole on the puff
        # file and on the page, and the check that each staged hour equals the final
        # file's (the driver's `staged` and `staged_check`)
        rec["hours"] = response.get("staged") or []
        rec["hours_check"] = response.get("staged_check") or []
    try:
        rec["result"] = derive(request, response)
        rec["state"] = "modelled"
        rec["reason"] = None
    except Refusal as exc:
        rec["result"] = None
        rec["state"] = "not_modelled"
        rec["reason"] = str(exc)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    if frames is not None and rec["state"] == "modelled":
        from hazbrief.brief import frames as F

        F.write_record(
            sha,
            request,
            rows,
            frames,
            cfg["frames"],
            engine_id=engine_id,
            made="run",
            smp_text=response.get("smp"),
            root=root,
        )
    return rec
