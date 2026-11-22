"""The smoke layer: VSMOKE's downwind PM2.5 as AQI bands, who is sensitive in each band,
and the message each band must hear (DN-021 sections 3 to 6; HB-129 Part B).

Four parts, each a function the tests drive directly:

1. **The banding** (`category`, `aqi`, `bands`). The PM2.5 AQI table is
   `packs/src/aqi_pm25_breakpoints.json` (HB-128 step 6): the 2024 breakpoints of the
   EPA AQI technical assistance document's Table 6, which implements 40 CFR part 58
   Appendix G. Only its `categories` are read, never `guide_printed_pm25`, the
   wildfire-smoke guide's pre-2024 ranges, kept there to show the drift and labelled not
   a breakpoint (HB-128 finding 2). A concentration is truncated to one decimal place,
   as the table's method says ("PM2.5 (ug/m3) - truncate to 1 decimal place", p. 13),
   then placed in the category whose range holds it; the index is the table's equation,
   rounded to the nearest integer ("Round the index to the nearest integer", p. 13).
   Above the top breakpoint (325.4 ug/m3, AQI 500) the category is still Hazardous
   (Table 6 prints "225.5+") but there is no index value: the index ends at 500. `bands`
   turns a concentration-at-distance profile, PM2.5 at DN-021 section 3's 31 downwind
   distances, into runs of one category, each from its first to its last distance.
   Nothing is interpolated between VSMOKE's distances: a band's edges are the distances
   VSMOKE reports.

2. **The overlay** (`overlay`): for one band, the population tool's answer over the
   band's area (ACS adults 65 and over; the day or night count by the period, the LODES
   switch the brief already has), the CDC PLACES estimated adults with asthma, COPD and
   coronary heart disease (prevalence among adults times the tract's adults times the
   tract's area share in the band, the arithmetic printed), and, in the worst bands, the
   schools, nursing homes and hospitals the facilities tool names. A tract PLACES does
   not estimate prints "not estimated", never 0 (every Pennsylvania tract in the 2025
   release; Issue 3ae8fa9b). Children are not counted: the population tool carries no
   under-18 count, and the overlay says so rather than derive one.

3. **The message block** (`messages`): for each band, the EPA wildfire-smoke guide's
   cautionary statement for its category, quoted with its page (the table's
   `guide_cautionary`, quote-checked against the held page by HB-128's builder), the
   named places and roads inside it, and when the smoke reaches its near edge at the
   brief's wind speed. The renderer writes nothing in the block but place names and
   times.

4. **The derivation** (`derive`): the inputs VSMOKE takes, from the brief (the fire's
   point; the emission rate and heat release from the scenario's `fire` block; the
   stability class, wind and mixing height from the brief's weather), run through
   `vsmoke_driver`. **State at HB-129:** VSMOKE is not built (HB-128; Issue 69cc2af7),
   so no run exists, and the derivation returns the client's refusal lines and its
   `engine_not_held` error and hint. No band is drawn from any other engine's
   concentration (the puff, SLAB or a hand profile): that would be the reconciliation
   between engines DN-020 section 3.4 forbids. **State at HB-150:** the smoke layer is a
   future use (`vsmoke.yaml` `engine`): no held open engine builds and reproduces the
   manual's example, so the refusal says so.

**The seam.** When the task that builds VSMOKE adds the driver's output reader, it
returns the 31-point profile `[(distance_m, pm25_ug_m3), ...]`; `derive` passes it to
`bands`, the bands' polygons go to the population and facilities tools as areas, and
`overlay` and `messages` take their answers. Until then `derive` never calls `bands`.

Standard library and PyYAML only (the brief's config is read by the caller).
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from hazbrief.brief import vsmoke_driver as V
from hazbrief.config import REPO_ROOT


class SmokeError(ValueError):
    """An input the smoke layer cannot use: a malformed table or profile. One line."""


# ── the AQI table ─────────────────────────────────────────────────────────────────────


def load_table(path: str | Path) -> dict:
    """The PM2.5 AQI table, checked: its categories in order, each range tiling the
    next at 0.1 ug/m3 and the index at 1. Refuses a table that does not tile."""
    p = Path(path)
    if not p.is_absolute():
        p = REPO_ROOT / p
    doc = json.loads(p.read_text(encoding="utf-8"))
    cats = doc.get("categories") or []
    if not cats:
        raise SmokeError(f"{p}: no categories")
    for a, b in zip(cats, cats[1:]):
        if round(b["pm25_lo_ug_m3"] - a["pm25_hi_ug_m3"], 1) != 0.1:
            raise SmokeError(
                f"{p}: {a['category']} ends at {a['pm25_hi_ug_m3']} and "
                f"{b['category']} starts at {b['pm25_lo_ug_m3']}; "
                "the ranges do not tile"
            )
        if b["aqi_lo"] - a["aqi_hi"] != 1:
            raise SmokeError(f"{p}: the index ranges do not tile at {b['category']}")
    if cats[0]["pm25_lo_ug_m3"] != 0.0:
        raise SmokeError(f"{p}: the first category does not start at 0.0")
    return doc


def truncate(pm25: float) -> Decimal:
    """`pm25` truncated to one decimal place (the table's method, p. 13)."""
    if not (isinstance(pm25, (int, float)) and math.isfinite(pm25)) or pm25 < 0:
        raise SmokeError(f"PM2.5 {pm25!r}: want a finite, non-negative number")
    return Decimal(repr(float(pm25))).quantize(Decimal("0.1"), rounding=ROUND_DOWN)


def category(pm25: float, table: dict) -> dict:
    """The category whose range holds `pm25` once truncated. Above the top breakpoint,
    the top category (Table 6's "225.5+")."""
    c = truncate(pm25)
    cats = table["categories"]
    for cat in cats:
        if (
            Decimal(str(cat["pm25_lo_ug_m3"]))
            <= c
            <= Decimal(str(cat["pm25_hi_ug_m3"]))
        ):
            return cat
    return cats[-1]


def aqi(pm25: float, table: dict) -> int | None:
    """The index for `pm25` by the table's equation, rounded to the nearest integer;
    None above the top breakpoint, where the index has no value (it ends at 500)."""
    c = truncate(pm25)
    cat = category(pm25, table)
    lo, hi = Decimal(str(cat["pm25_lo_ug_m3"])), Decimal(str(cat["pm25_hi_ug_m3"]))
    if c > hi:
        return None
    ilo, ihi = Decimal(cat["aqi_lo"]), Decimal(cat["aqi_hi"])
    ip = (ihi - ilo) / (hi - lo) * (c - lo) + ilo
    return int(ip.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _check_profile(profile: list, points: int) -> list[tuple[float, float]]:
    rows = [(float(d), float(c)) for d, c in profile]
    if len(rows) != points:
        raise SmokeError(
            f"the profile has {len(rows)} distances; VSMOKE reports {points}"
        )
    for (d0, _), (d1, _) in zip(rows, rows[1:]):
        if not d1 > d0:
            raise SmokeError(f"the profile's distances do not increase at {d1} m")
    if rows[0][0] <= 0:
        raise SmokeError("the profile's first distance is not downwind of the fire")
    for _, c in rows:
        truncate(c)
    return rows


def bands(profile: list, table: dict, points: int) -> list[dict]:
    """Runs of one category along the profile, nearest first: each with its category,
    its first and last distance, the peak concentration and its index. A category can
    return farther out (a plume that comes to ground and thins), so it can have more
    than one band."""
    out: list[dict] = []
    for d, c in _check_profile(profile, points):
        cat = category(c, table)
        if out and out[-1]["category"] == cat["category"]:
            b = out[-1]
            b["to_m"] = d
            b["points"] += 1
            if c > b["peak_pm25_ug_m3"]:
                b["peak_pm25_ug_m3"], b["peak_aqi"] = c, aqi(c, table)
            continue
        out.append(
            {
                "category": cat["category"],
                "rank": table["categories"].index(cat),
                "from_m": d,
                "to_m": d,
                "points": 1,
                "peak_pm25_ug_m3": c,
                "peak_aqi": aqi(c, table),
            }
        )
    return out


def worst(bands_: list[dict], n: int) -> list[dict]:
    """The bands of the `n` worst categories present (DN-021 section 5)."""
    ranks = sorted({b["rank"] for b in bands_}, reverse=True)[:n]
    return [b for b in bands_ if b["rank"] in ranks]


# ── the overlay ───────────────────────────────────────────────────────────────────────


def places_rows(
    tract_shares: dict[str, float], tracts: dict, spec: dict, measures: dict
) -> list[dict]:
    """Per tract in the band and per PLACES measure: the estimated adults with the
    condition, as prevalence among adults x adults (Census 2020) x the tract's area
    share in the band, the arithmetic printed; "not estimated" where the release prints
    no value, and where the tract is not in the held slice."""
    rows = []
    for fips, share in sorted(tract_shares.items()):
        if not 0 < share <= 1:
            raise SmokeError(f"tract {fips}: area share {share!r} is not in (0, 1]")
        t = tracts.get(fips)
        for key, name in measures.items():
            e = None if t is None else t.measures.get(key)
            if e is None:
                rows.append(
                    {
                        "tract": fips,
                        "measure": name,
                        "count": None,
                        "text": spec["places_not_estimated"],
                    }
                )
                continue
            count = e.percent / 100.0 * t.adults * share
            rows.append(
                {
                    "tract": fips,
                    "measure": name,
                    "count": count,
                    "text": spec["places_arithmetic"].format(
                        percent=e.percent, adults=t.adults, share=share, count=count
                    ),
                }
            )
    return rows


def overlay(
    band: dict,
    population: dict | None,
    tract_shares: dict[str, float],
    tracts: dict,
    facilities: dict | None,
    spec: dict,
    measures: dict,
    *,
    in_worst: bool,
) -> dict:
    """One band's sensitive-population overlay (DN-021 section 5). `population` and
    `facilities` are the tools' answers with the band as their area; `tract_shares` the
    share of each tract's area inside the band; `tracts` the PLACES file
    (`places.load`). Every number carries its source and vintage."""
    out: dict[str, Any] = {"category": band["category"], "from_m": band["from_m"]}
    chars = (population or {}).get("characteristics") or {}
    old = chars.get("age_65_and_over")
    out["age_65_and_over"] = (
        {
            "estimate": old["estimate"],
            "moe": old["moe"],
            "source": old["source"],
            "vintage": old["vintage"],
        }
        if old
        else None
    )
    # the population tool counts no under-18 cells (its B01001 cells are 65 and over
    # only); nothing is derived in its place
    out["children"] = None
    period = ((population or {}).get("day_night") or {}).get("period")
    which = (population or {}).get("primary_count")
    block = (population or {}).get(which) if which else None
    out["primary"] = (
        {
            "period": period,
            "count_kind": which,
            "counts": block.get("counts"),
            "value": block.get("workers", block.get("residents")),
            "source": block.get("source"),
            "vintage": block.get("vintage"),
        }
        if block
        else None
    )
    out["places"] = places_rows(tract_shares, tracts, spec, measures)
    out["facilities"] = (
        {
            words: [f.get("name") for f in (facilities or {}).get(key) or []]
            for key, words in spec["facility_kinds"].items()
        }
        if in_worst
        else None
    )
    return out


# ── the message block ─────────────────────────────────────────────────────────────────


def arrival(from_m: float, wind_ms: float, as_given: str, spec: dict, when_fn) -> dict:
    """When the smoke reaches a band's near edge: distance over wind speed, from the
    as-given time (DN-021 section 6), to the nearest minute."""
    if not wind_ms or wind_ms <= 0:
        raise SmokeError(f"wind speed {wind_ms!r} m/s: no arrival time without wind")
    minutes = int(
        Decimal(from_m / wind_ms / 60.0).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )
    at = datetime.fromisoformat(as_given) + timedelta(minutes=minutes)
    return {
        "minutes": minutes,
        "at": at.isoformat(),
        "text": spec["arrival"].format(
            from_m=from_m, minutes=minutes, when=when_fn(as_given), speed=wind_ms
        ),
    }


def messages(
    bands_: list[dict],
    table: dict,
    named: dict[int, list[str]],
    wind_ms: float,
    as_given: str,
    spec: dict,
    when_fn,
) -> list[dict]:
    """For each band (by its index in `bands_`): the guide's cautionary statement for
    its category, verbatim with its page, the named places and roads `named` holds for
    it, and the arrival time."""
    by_name = {c["category"]: c for c in table["categories"]}
    out = []
    for i, b in enumerate(bands_):
        g = by_name[b["category"]]["guide_cautionary"]
        r = g["receipt"]
        out.append(
            {
                "category": b["category"],
                # the receipt's quote, the page's own words, not the table's `text`:
                # for Unhealthy the text adds two full stops the page's bullet lines do
                # not print (HB-129 finding), and the block is quoted, not written
                "message": r["quote"],
                "doc_id": r["doc_id"],
                "pdf_page": r["pdf_page"],
                "printed_page": r["printed_page"],
                "places": list(named.get(i) or []),
                "arrival": arrival(b["from_m"], wind_ms, as_given, spec, when_fn),
            }
        )
    return out


# ── the derivation ────────────────────────────────────────────────────────────────────


def _sourced(fire: dict, key: str) -> V.Sourced | None:
    v = fire.get(key)
    if isinstance(v, dict) and "value" in v:
        return V.Sourced(float(v["value"]), str(v.get("source") or ""))
    return None


def inputs_of(brief, fp: dict | None, derived: dict) -> V.Inputs:
    """VSMOKE's inputs from what the brief holds: the spill point (or the incident's
    point where no footprint was drawn), the fire block's emission rate and heat
    release, the stability class, the footprint's wind (the brief's wind; the scenario's
    as given where no footprint was drawn) and the mixing height at hour 0. A value the
    brief does not hold is None, which the client refuses by name."""
    fire = brief.fire or {}
    lat = lon = None
    for f in ((fp or {}).get("footprint") or {}).get("features") or []:
        if f["properties"].get("zone") == "spill":
            lon, lat = f["geometry"]["coordinates"][:2]
    if lat is None and brief.point:
        lat, lon = brief.point
    # HB-133: the brief's one wind record once resolved (a brush fire has no footprint,
    # and the scenario's stated wind beside a held forecast is not the brief's wind)
    from hazbrief.brief import derive as D

    wind = D.brief_wind(brief, fp) or (fp or {}).get("wind") or brief.given_wind or {}
    speed = wind.get("speed_kmh")
    frm = wind.get("direction_deg_from")
    return V.Inputs(
        latitude=lat,
        longitude=lon,
        emission_rate_g_s=_sourced(fire, "emission_rate_g_s"),
        heat_release_w=_sourced(fire, "heat_release_w"),
        stability=(derived.get("stability") or {}).get("class"),
        wind_speed_ms=None if speed is None else float(speed) / 3.6,
        wind_from_deg=None if frm is None else float(frm),
        mixing_height_m=_mixing_height(brief, derived),
    )


def _mixing_height(brief, derived: dict) -> float | None:
    """VSMOKE's mixing height: the stated weather source's (HB-139; DN-019 ADDENDUM-01
    section 1) when the record states one, else the forecast's hour 0 (HB-129)."""
    rec = getattr(brief, "wind_record", None)
    if getattr(brief, "wind_resolved", False) and rec and rec.get("mixing_height_m"):
        return float(rec["mixing_height_m"])
    return (derived.get("forecast") or {}).get("mixing_height_m")


def derive(brief, fp: dict | None, derived: dict, cfg: dict) -> dict | None:
    """The smoke channel for a fire brief; None for a brief without a fire block. With
    VSMOKE not built every run refuses, so the result is `not_drawn` with the client's
    refusal lines (every input not supplied, by name) and its `engine_not_held` error
    and hint, and `follows` says why the overlay and the message block print no rows."""
    if not brief.fire:
        return None
    spec = cfg["weather"]["smoke"]
    vspec = V.load_spec()
    inputs = inputs_of(brief, fp, derived)
    refused = V.refusals(inputs, vspec)
    got = V.run(inputs, vspec, recordings_dir=REPO_ROOT / vspec["recordings_dir"])
    lines = list(refused)
    if got.output is None:
        # the engine is not built whatever the inputs: say so beside the missing inputs
        engine = " ".join(vspec["refusals"]["engine_not_held"].split())
        if engine not in lines:
            lines.append(engine)
        out = {
            "state": "not_drawn",
            "label": None,
            "lines": lines,
            "hint": vspec["hints"]["engine_not_held"],
            "note": (brief.fire or {}).get("note"),
            "inputs": V.canonical(inputs),
            "bands": [],
            "overlay": [],
            "messages": [],
        }
        out["follows"] = spec["follows"]
        return out
    # The seam (module docstring): VSMOKE's output reader is not written, so a recorded
    # run cannot be read into a profile yet. Refuse loudly rather than draw nothing
    # silently.
    raise SmokeError(
        "a recorded VSMOKE run exists but the output reader is not written "
        "(HB-128 deviation 1): add it before recording runs"
    )
