"""The threat timeline (HB-171; DN-029): what the modelled cloud reaches and when, in
time order, with what the held sources say to consider and who can confirm each row,
and an exercise events list in HSEEP's MSEL columns from the same record.

A pure function of what a brief already holds (task item 4): the engine's held record
as the brief draws it (`derived["cloud"]`: each point's arrival, minutes above and clear
per level; each step's area per level; the area each level reaches at any time), the
brief's time, the named places, suggested points and roadblocks the map draws (their
kinds read from the same map data), and the blocks under the cloud
(`derived["modelled_population"]["rows"]`, recorded by HB-171). No model call writes any
word of it: the words are `threat.yaml`'s, and every consideration is a quotation of a
held document with its page. Same inputs, same bytes.

- **A row** (DN-029 decision 1) is one place reaching one health-effect level: the
  place and its kind, the level, first arrival, minutes above that level, clear of that
  level, and the lead from the brief's time. A place that can shelter (not a roadblock,
  a rail block or a suggested point) has a clear row of its own when the outermost
  level leaves it. The blocks under the cloud give one row per level at the first
  populated block reached (at the engine's 5-minute steps), with the residents inside
  that level's area reached at any time; a block holding group quarters gives one row
  per type and level.
- **The order** (decision 2): arrival, the worst level first, a place expected to be
  occupied before one that is not, nearest the source first, then kind and id.
- **Occupancy** (decision 8; HB-171 ADDENDUM-01): the first `occupancy` line of the
  row's kind whose days and clock window hold the arrival, worded as an expectation from
  typical hours, never as the place's status; each line is sourced or marked assumed.
- **No row is marked "little or no time"** (decision 5): the held times are ranges, so
  the page states them at the top and the lead is the signal.

The page (`page_html`) is written beside the brief as `timeline.html`, the download
(`msel_csv`) as `timeline.csv`; the first view's next rows are `first_view_html`.
"""

from __future__ import annotations

import csv
import html
import io
import math
from datetime import datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

HERE = Path(__file__).resolve().parent
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class ThreatError(RuntimeError):
    """`threat.yaml` breaks its own rule (an unknown quotation, a level not ranked)."""


@cache
def config() -> dict:
    return yaml.safe_load((HERE / "threat.yaml").read_text(encoding="utf-8"))


def esc(text: Any) -> str:
    return html.escape(str(text), quote=True)


# ── time ────────────────────────────────────────────────────────────────────────────


def _release_local(brief, cl: dict) -> datetime:
    from hazbrief.evidence import store as S

    tz = ZoneInfo(getattr(brief, "time_zone", None) or "UTC")
    return S.parse_time(cl["release_utc"]).astimezone(tz)


def _brief_minute(brief, cl: dict) -> float:
    """The brief's time in minutes after the release (the as-given time; the cloud's
    release is the as-given time, `cloud.request`, so this is 0 on every brief)."""
    from hazbrief.evidence import store as S

    if not getattr(brief, "as_given", None):
        return 0.0
    given = S.parse_time(brief.as_given)
    rel = S.parse_time(cl["release_utc"])
    return (given - rel).total_seconds() / 60.0


def hplus(minutes: float) -> str:
    from hazbrief.brief import derive as D

    return D.hplus(int(round(minutes)))


def span(minutes: float) -> str:
    """A duration as "1 h 10 min" (the lead)."""
    m = int(round(minutes))
    sign = "-" if m < 0 else ""
    h, mm = divmod(abs(m), 60)
    if h == 0:
        return f"{sign}{mm} min"
    return f"{sign}{h} h" + (f" {mm} min" if mm else "")


def _clock(t0: datetime, minutes: float) -> str:
    return (t0 + timedelta(minutes=round(minutes))).strftime("%H:%M")


def _hhmm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


# ── kinds and occupancy ─────────────────────────────────────────────────────────────


def _features_by_point(data: dict) -> dict[tuple[float, float, str], dict]:
    """(lat, lon, layer id) -> the drawn feature's properties, at the record's
    rounding."""
    out = {}
    for lay in data.get("layers") or []:
        for f in lay.get("features") or []:
            g = f.get("geometry") or {}
            if g.get("type") != "Point":
                continue
            lon, lat = (float(v) for v in g["coordinates"][:2])
            out[(round(lat, 6), round(lon, 6), lay["id"])] = f.get("properties") or {}
    return out


def kind_of(place: dict, feats: dict, tc: dict) -> dict:
    """The first `kinds` entry matching one of the place's layers (and, where the entry
    names one, the feature's `service`)."""
    for rank, k in enumerate(tc["kinds"]):
        for lid in place.get("layers") or []:
            if lid not in k["layers"]:
                continue
            if k.get("service"):
                props = feats.get((round(place["lat"], 6), round(place["lon"], 6), lid))
                if (props or {}).get("service") != k["service"]:
                    continue
            return {"id": k["id"], "name": k["name"], "rank": rank}
    return {"id": "place", "name": "place", "rank": len(tc["kinds"])}


def occupancy(kind: str, at: datetime, tc: dict) -> dict | None:
    """The first `occupancy` line of `kind` whose days and [from, to) window hold `at`
    (a window may run past midnight), with its phrase, its index and its sources or
    assumption; None where no line matches."""
    lines = (tc.get("occupancy") or {}).get(kind) or []
    day = DAYS[at.weekday()]
    m = at.hour * 60 + at.minute
    for i, ln in enumerate(lines):
        if day not in ln["days"]:
            continue
        a, b = _hhmm(ln["from"]), _hhmm(ln["to"])
        inside = (a <= m < b) if a < b else (m >= a or m < b)
        if not inside:
            continue
        phrase = ln["phrase"]
        if kind == "school" and at.month in tc["term_not_held"]:
            phrase += tc["term_note"]
        return {
            "phrase": phrase,
            "line": f"{kind}:{i}",
            "sources": [
                {k: s[k] for k in ("doc", "page", "block")}
                for s in ln.get("sources") or []
            ],
            "assumed": ln.get("assumed") or ln.get("assumed_bounds"),
        }
    return None


def _consider(kind: str, tc: dict) -> list[dict]:
    out = []
    for key in (tc.get("consider") or {}).get(kind) or []:
        q = tc["quotes"].get(key)
        if q is None:
            raise ThreatError(f"threat.yaml consider names no quotation {key!r}")
        out.append({"key": key, "text": q["text"], "ref": q["ref"], "doc": q["doc"]})
    return out


# ── the blocks under the cloud ──────────────────────────────────────────────────────


def planning_levels(brief) -> dict:
    """Level -> the planning area (a shapely geometry) under the stable treatment
    (DN-028 ADDENDUM-14 decision 6: the moving cloud's area over the horizon together
    with SLAB's time-bounded area; `agreement.build` sets `levels`); {} elsewhere."""
    import shapely
    from shapely.geometry import shape

    ag = (brief.derived or {}).get("agreement") or {}
    if ag.get("levels") != "planning":
        return {}
    return {
        t: shapely.make_valid(shape(p["geometry"]))
        for t, p in (ag.get("planning") or {}).items()
    }


def cloud_parts(brief) -> dict:
    """Level -> the moving cloud's part of the planning area (a shapely geometry, or
    None where the cloud does not reach the level), under the stable treatment (DN-028
    ADDENDUM-14 decisions 6 and 7: a count is stated with its parts, the cloud's and
    SLAB's extent check outside it); {} elsewhere."""
    import shapely
    from shapely.geometry import shape

    ag = (brief.derived or {}).get("agreement") or {}
    if ag.get("levels") != "planning":
        return {}
    return {
        t: shapely.make_valid(shape(p["cloud"])) if p.get("cloud") else None
        for t, p in (ag.get("planning") or {}).items()
    }


def setting_m(brief) -> float:
    """The moving cloud's vertical setting (m) under the stable treatment, which marks
    every time on the brief (DN-028 ADDENDUM-14 decision 10)."""
    ag = (brief.derived or {}).get("agreement") or {}
    return float(ag.get("vertical_setting_m") or 0.0)


def part_counts(brief, tier: str, cloud: int, total: int) -> dict:
    """A level's residents by part (DN-028 ADDENDUM-14 decision 6): `cloud` inside the
    moving cloud's area, `check` the further ones inside SLAB's extent check only, each
    with whether its own part is cut (the cloud's domain; SLAB's table or the time
    bound), so a part is written "at least" only where its own engine cut it."""
    p = (((brief.derived or {}).get("agreement") or {}).get("planning") or {}).get(
        tier
    ) or {}
    return {
        "cloud": cloud,
        "check": total - cloud,
        "cloud_cut": bool(p.get("scichem_cut")),
        "check_cut": bool(p.get("slab_cut")),
    }


def residents_in(blocks: list, area) -> float:
    """The residents of `blocks` ((row, geometry) pairs) inside `area`, each block by
    its area share, as the level's own count is made; 0 where `area` is None."""
    from hazbrief import geo

    if area is None:
        return 0.0
    out = 0.0
    for r, g in blocks:
        if not r.get("residents"):
            continue
        share, kind = geo.area_share(g, area)
        if kind is not None:
            out += r["residents"] * share
    return out


def _block_rows(brief, cl: dict, tc: dict, t0: datetime) -> tuple[list, dict]:
    """The population and group-quarters rows (decision 1), and the head's population
    note: one row per level at the first populated block that level reaches (at the
    engine's 5-minute steps) with the residents inside its area reached at any time;
    one row per group-quarters type and level for each block holding it. Under the
    stable treatment (DN-028 ADDENDUM-14 decision 6) a level's area is the planning
    area, and its first reach is the moving cloud's first step over a populated block
    inside that area, marked with the run's vertical setting; a level the cloud never
    reaches there has no row here (`_untimed` lists it)."""
    import shapely
    from shapely.geometry import shape

    from hazbrief import geo, lodes
    from hazbrief.census import Unit

    mp = (brief.derived or {}).get("modelled_population") or {}
    rows = mp.get("rows") or []
    if mp.get("absent") or not rows:
        return [], {"why": mp.get("reason") or "no block is held under the cloud"}
    blocks = []
    for r in rows:
        g = shape(r["geometry"])
        blocks.append((r, g))
    geoms = [g for _, g in blocks]
    shapely.prepare(geoms)
    tiers = [t["name"] for t in cl.get("tiers") or []]
    steps = cl.get("steps") or []
    step_shapes = {
        t: [
            (s["minute"], shape(s["tiers"][t]) if s["tiers"].get(t) else None)
            for s in steps
        ]
        for t in tiers
    }

    def first_reach(idx: list[int], tier: str) -> float | None:
        sub = [geoms[i] for i in idx]
        for minute, g in step_shapes[tier]:
            if g is None or g.is_empty:
                continue
            if any(shapely.intersects(sub, g)):
                return float(minute)
        return None

    slab = planning_levels(brief)
    parts = cloud_parts(brief)
    out = []
    for tier in tiers:
        if slab:
            area = slab.get(tier)
            if area is None:
                continue
        else:
            at = (cl.get("any_time") or {}).get(tier)
            if not at:
                continue
            area = shapely.make_valid(shape(at))
        units, residents, populated = [], 0.0, []
        for i, (r, g) in enumerate(blocks):
            share, kind = geo.area_share(g, area)
            if kind is None:
                continue
            if r.get("residents"):
                residents += r["residents"] * share
                populated.append(i)
            geoid = str(r["geoid"])
            units.append(
                Unit(
                    level="block",
                    geoid=geoid,
                    share=share,
                    kind=kind,
                    state=geoid[:2],
                    county=geoid[2:5],
                    tract=geoid[5:11],
                )
            )
        arrival = first_reach(populated, tier) if populated else None
        if arrival is not None:
            try:
                workers = round(lodes.jobs(units)["jobs"]) if units else 0
            except (OSError, ValueError):
                workers = None
            out.append(
                {
                    "event": "population",
                    "kind": "population",
                    "kind_name": tc["area_kinds"]["population"]["name"],
                    "name": tc["area_kinds"]["population"]["name"],
                    "level": tier,
                    "arrival_min": arrival,
                    "minutes_above": None,
                    "clear_min": None,
                    "residents": round(residents),
                    "workers": workers,
                    "distance_m": None,
                    "id": f"population:{tier}",
                    "unresolved": setting_m(brief) if slab else False,
                }
            )
            if slab:
                # DN-028 ADDENDUM-14 decision 6: the count stated with its parts, the
                # residents inside the moving cloud's area and the further ones inside
                # SLAB's extent check only (the rest of the count)
                inside = round(residents_in(blocks, parts.get(tier)))
                out[-1]["parts"] = part_counts(brief, tier, inside, round(residents))
        # group quarters: a block the level reaches that holds any
        for i, (r, g) in enumerate(blocks):
            gq = r.get("group_quarters") or {}
            if not gq or not g.intersects(area):
                continue
            arr = first_reach([i], tier)
            if arr is None:
                continue
            for typ, count in sorted(gq.items()):
                if not count:
                    continue
                out.append(
                    {
                        "event": "group_quarters",
                        "kind": "group_quarters",
                        "kind_name": tc["area_kinds"]["group_quarters"]["name"],
                        "name": tc["words"]["group_quarters_row"].format(
                            type=typ.replace("_", " "),
                            count=int(count),
                            geoid=r["geoid"],
                        ),
                        "level": tier,
                        "arrival_min": arr,
                        "minutes_above": None,
                        "clear_min": None,
                        "count": int(count),
                        "geoid": str(r["geoid"]),
                        "distance_m": None,
                        "id": f"gq:{r['geoid']}:{typ}:{tier}",
                        "unresolved": setting_m(brief) if slab else False,
                    }
                )
    return out, {"why": None}


# ── the record ──────────────────────────────────────────────────────────────────────


def build(brief, cfg: dict, data: dict | None = None) -> dict:
    """The timeline record of `brief` (module docstring). `cfg` is orchestrator.yaml;
    `data` the brief's map data (`layers.build`), built here when not given."""
    from hazbrief.brief import layers

    tc = config()
    cl = (brief.derived or {}).get("cloud") or {}
    if cl.get("state") != "drawn":
        return {
            "state": "not_modelled",
            "reason": cl.get("reason") or cfg["map"]["cloud"]["no_cloud"],
            "rows": [],
        }
    data = data if data is not None else layers.build(brief, cfg)
    feats = _features_by_point(data)
    t0 = _release_local(brief, cl)
    b0 = _brief_minute(brief, cl)
    worst = tc["levels_worst_first"]
    tiers = [t["name"] for t in cl.get("tiers") or []]
    if set(tiers) - set(worst):
        raise ThreatError(f"levels {sorted(set(tiers) - set(worst))} are not ranked")
    outer = tiers[0] if tiers else None
    # DN-028 ADDENDUM-10 decision 3, as ADDENDUM-12 decision 5 amends it: where SLAB's
    # area is part of the levels, a place SCICHEM's run reaches at a level is listed at
    # that level with its time, marked as from the unresolved run, wherever in the
    # planning area it lies; no row leaves for lying outside SLAB's area (`left` stays
    # in the record, 0, for the counts HB-184 reported)
    slab = planning_levels(brief)
    left = 0
    rows: list[dict] = []
    for p in cl.get("places") or []:
        k = kind_of(p, feats, tc)
        name = "; ".join(p.get("names") or []) or tc["words"]["unnamed"]
        reached = False
        for tier in tiers:
            x = (p.get("tiers") or {}).get(tier) or {}
            if x.get("arrival_s") is None:
                continue
            reached = True
            rows.append(
                {
                    "event": "arrival",
                    "kind": k["id"],
                    "kind_name": k["name"],
                    "kind_rank": k["rank"],
                    "name": name,
                    "level": tier,
                    "arrival_min": x["arrival_s"] / 60.0,
                    "minutes_above": float(x.get("minutes_above") or 0.0),
                    "clear_min": x["clear_s"] / 60.0
                    if x.get("clear_s") is not None
                    else None,
                    "distance_m": p.get("distance_m"),
                    "lat": p["lat"],
                    "lon": p["lon"],
                    "id": f"{p['id']}:{tier}",
                    "place": p["id"],
                    "unresolved": setting_m(brief) if slab else False,
                }
            )
        o = (p.get("tiers") or {}).get(outer) or {}
        shelters = k["id"] not in ("roadblock", "rail_block", "suggested_point")
        if reached and shelters and o.get("clear_s") is not None:
            rows.append(
                {
                    "event": "clear",
                    "kind": "clear",
                    "kind_name": tc["area_kinds"]["clear"]["name"],
                    "kind_rank": k["rank"],
                    "place_kind": k["id"],
                    "place_kind_name": k["name"],
                    "name": name,
                    "level": None,
                    "arrival_min": o["clear_s"] / 60.0,
                    "minutes_above": None,
                    "clear_min": None,
                    "distance_m": p.get("distance_m"),
                    "lat": p["lat"],
                    "lon": p["lon"],
                    "id": f"{p['id']}:clear",
                    "place": p["id"],
                    "unresolved": setting_m(brief) if slab else False,
                }
            )
    pop_rows, pop_note = _block_rows(brief, cl, tc, t0)
    rows += pop_rows
    step_minutes = [int(s["minute"]) for s in cl.get("steps") or []]
    for r in rows:
        at = t0 + timedelta(minutes=round(r["arrival_min"]))
        occ_kind = r.get("place_kind") if r["event"] == "clear" else r["kind"]
        r["occupancy"] = occupancy(occ_kind, at, tc)
        r["consider"] = _consider(r["kind"], tc)
        r["verify"] = tc["verify"].get(
            r.get("place_kind") if r["event"] == "clear" else r["kind"]
        )
        if r["event"] == "clear":
            r["verify"] = tc["verify"]["clear"]
        r["clock"] = _clock(t0, r["arrival_min"])
        r["hplus"] = hplus(r["arrival_min"])
        r["lead_min"] = r["arrival_min"] - b0
        r["clear_clock"] = (
            _clock(t0, r["clear_min"]) if r.get("clear_min") is not None else None
        )
        r.setdefault("kind_rank", len(tc["kinds"]))
        # the time control's step at the row's arrival: the first step at or after it
        later = [i for i, m in enumerate(step_minutes) if m >= r["arrival_min"]]
        r["step_index"] = later[0] if later else max(len(step_minutes) - 1, 0)
    rank = {lv: i for i, lv in enumerate(worst)}
    rows.sort(
        key=lambda r: (
            r["arrival_min"],
            rank.get(r["level"], len(worst)),
            0 if _expected(r) else 1,
            r["distance_m"] if r["distance_m"] is not None else math.inf,
            r["kind_rank"],
            r["id"],
        )
    )
    for n, r in enumerate(rows, 1):
        r["n"] = n
    # HB-173 (DN-028 ADDENDUM-04 decision 5): the places and residents inside a planning
    # shape and outside the cloud at that level, numbered after the timed rows, no time
    untimed = _untimed(
        brief,
        cl,
        tc,
        feats,
        cfg,
        {r["level"] for r in pop_rows if r["event"] == "population"},
    )
    for n, r in enumerate(untimed, len(rows) + 1):
        r["n"] = n
    # HB-178 (Issue 78ccbb4b, item 11): a row at or beyond the cut of its level's area
    # carries the cut's words; no row is added or removed
    mark_cut(brief, cl, rows + untimed, tc)
    steps = cl.get("steps") or []
    covering = [s["minute"] for s in steps if any(s["contains_source"].values())]
    after = [s["minute"] for s in steps if covering and s["minute"] > covering[-1]]
    met = sorted(cl.get("met") or [], key=lambda m: m["time"])
    return {
        "state": "drawn",
        "reason": None,
        "engine": cl.get("engine"),
        "record": cl.get("record"),
        "release_local": t0.isoformat(),
        "brief_minute": b0,
        "release_minutes": cl.get("release_minutes"),
        "scene_clear_min": after[0] if after else None,
        "last_step_min": steps[-1]["minute"] if steps else None,
        "met": met[0] if met else None,
        "population": pop_note,
        "rows": rows,
        "untimed": untimed,
        # DN-028 ADDENDUM-10 item 6: where SLAB carries the levels, the place rows that
        # left (reached by SCICHEM at a level outside SLAB's area at that level)
        "levels": "planning" if slab else "scichem",
        "left": left,
    }


def _untimed(
    brief, cl: dict, tc: dict, feats: dict, cfg: dict, timed_levels: set | None = None
) -> list[dict]:
    """HB-173 (DN-028 ADDENDUM-04 decision 5; Part B item 7), as DN-028 ADDENDUM-10
    decision 3 and ADDENDUM-14 decision 10 amend it: under the stable treatment, each
    place inside a level's planning area (the moving cloud's area together with SLAB's
    extent check) whose sensor in the run did not reach that level
    (`agreement.untimed_places`: it lies in SLAB's part only), and per level the run
    reaches no populated block of (`timed_levels` holds the levels that have a timed
    population row), the residents inside the planning area at that level, with its
    parts. No time is invented: each row says why it has none. Worst level first, then
    nearest."""
    import shapely
    from shapely.geometry import shape

    from hazbrief import geo
    from hazbrief.brief import agreement as AG

    ag = (brief.derived or {}).get("agreement") or {}
    plan = ag.get("planning") or {}
    if not plan:
        return []
    engines = cfg["map"]["planning"]["engine"]
    out = []
    for u in AG.untimed_places(cl, ag):
        k = kind_of(u["place"], feats, tc)
        out.append(
            {
                "event": "planning",
                "kind": k["id"],
                "kind_name": k["name"],
                "kind_rank": k["rank"],
                "name": u["name"] or tc["words"]["unnamed"],
                "level": u["tier"],
                "engine": engines[u["engine"]],
                "distance_m": u["distance_m"],
                "lat": u["lat"],
                "lon": u["lon"],
                "id": f"{u['id']}:planning:{u['tier']}",
                "place": u["id"],
                "consider": _consider(k["id"], tc),
                "verify": tc["verify"].get(k["id"]),
            }
        )
    mp = (brief.derived or {}).get("modelled_population") or {}
    blocks = [(r, shape(r["geometry"])) for r in mp.get("rows") or []]
    for t, p in plan.items():
        if t in (timed_levels or set()):
            continue
        area = shapely.make_valid(shape(p["geometry"]))
        if area.is_empty:
            continue
        residents = 0.0
        for r, g in blocks:
            if not r.get("residents"):
                continue
            share, kind = geo.area_share(g, area)
            if kind is not None:
                residents += r["residents"] * share
        if round(residents) <= 0:
            continue
        inside = round(
            residents_in(
                blocks,
                shapely.make_valid(shape(p["cloud"])) if p.get("cloud") else None,
            )
        )
        out.append(
            {
                "parts": part_counts(brief, t, inside, round(residents)),
                "event": "planning_population",
                "kind": "population",
                "kind_name": tc["area_kinds"]["population"]["name"],
                "kind_rank": len(tc["kinds"]),
                "name": tc["area_kinds"]["population"]["name"],
                "level": t,
                "engine": engines[p["engine"]],
                "residents": round(residents),
                "distance_m": None,
                "id": f"population:planning:{t}",
                "consider": _consider("population", tc),
                "verify": tc["verify"].get("population"),
            }
        )
    rank = {lv: i for i, lv in enumerate(tc["levels_worst_first"])}
    out.sort(
        key=lambda r: (
            rank.get(r["level"], len(rank)),
            r["distance_m"] is not None,
            r["distance_m"] or 0.0,
            r["id"],
        )
    )
    return out


def _expected(r: dict) -> bool:
    """Whether the row's occupancy phrase expects people (a line whose phrase says "not
    expected" does not)."""
    occ = r.get("occupancy")
    return bool(occ) and "not expected" not in occ["phrase"]


def next_rows(rec: dict, n: int) -> list[dict]:
    """The first view's rows: the earliest `n` rows not yet past at the brief's time."""
    return [r for r in rec.get("rows") or [] if r["lead_min"] >= 0][:n]


# ── the cut (HB-178) ────────────────────────────────────────────────────────────────


def cut_by(brief, cl: dict) -> dict[tuple[str, str], str]:
    """(area, level) -> what cut it, for each area whose reach is a lower bound
    (HBD-419): ("cloud", level) where the level's area reached at any time meets the
    engine's grid; ("planning", level) where the planning area under a stable class
    (DN-028 ADDENDUM-12 decision 2: SLAB's area together with SCICHEM's) has a cut part:
    SLAB's band reaching the end of its table, or SCICHEM's forecast-turned part meeting
    its domain (decision 4: "at least" where either part is cut)."""
    from hazbrief.brief import agreement as AG

    w = AG.load_config()["words"]
    out = {}
    for t, is_cut in (cl.get("reach_cut") or {}).items():
        if is_cut:
            out[("cloud", t)] = w["cut_domain"]
    ag = (brief.derived or {}).get("agreement") or {}
    rows = {r["tier"]: r for r in ag.get("reaches") or []}
    for t, p in (ag.get("planning") or {}).items():
        by = []
        if p.get("slab_cut", (rows.get(t) or {}).get("slab_cut")):
            # HB-189 (DN-028 ADDENDUM-14 decision 5): cut by the time bound
            by.append(w["cut_time"])
        if p.get("scichem_cut"):
            by.append(w["cut_domain"])
        if by:
            out[("planning", t)] = " and ".join(by)
    return out


def mark_cut(brief, cl: dict, rows: list[dict], tc: dict) -> None:
    """HB-178 item 11: each row whose figure is counted under a cut area (the residents
    under a cut level, or inside a cut planning shape) or whose place lies at or beyond
    the engine's grid at a cut level gets `cut`, what cut it; `row_text` then writes
    its figure "at least" with that (HBD-419)."""
    from hazbrief import geometry as G
    from hazbrief.brief import agreement as AG

    def local_km(lat0: float, lon0: float, lat: float, lon: float) -> tuple:
        # the azimuthal equidistant plane the engine's rings are in (geometry.offset)
        g = G._WGS84.Inverse(lat0, lon0, lat, lon)
        a = math.radians(g["azi1"])
        return g["s12"] * math.sin(a) / 1000.0, g["s12"] * math.cos(a) / 1000.0

    cuts = cut_by(brief, cl)
    if not cuts:
        return
    # DN-028 ADDENDUM-10 decision 1, as ADDENDUM-12 decisions 2, 4 and 5 amend it:
    # where SLAB's area is part of the levels a population row's area is the planning
    # area, so its count is cut where either part is (SLAB's table, SCICHEM's domain);
    # a place row is SCICHEM's reading at the place, listed wherever in the planning
    # area it lies, so it carries the grid's cut at or beyond the edge, as by day
    slab = bool(planning_levels(brief))
    tol = float(AG.load_config()["reach"]["edge_tolerance_km"])
    site = cl.get("site") or {}
    for r in rows:
        lv = r.get("level")
        # HB-182: the nearest edge this level's own area meets; beyond it the field
        # is not computed on that stretch
        hw = min((cl.get("cut_edge_km") or {}).get(lv) or [math.inf])
        hw = None if hw == math.inf else hw
        if slab and r["event"] in ("population", "planning_population"):
            if ("planning", lv) in cuts:
                r["cut"] = cuts[("planning", lv)]
            continue
        if r["event"] in ("population",) and ("cloud", lv) in cuts:
            r["cut"] = cuts[("cloud", lv)]
        elif r["event"] == "planning_population" and ("planning", lv) in cuts:
            r["cut"] = cuts[("planning", lv)]
        elif (
            r["event"] == "arrival"
            and ("cloud", lv) in cuts
            and hw is not None
            and r.get("lat") is not None
            and site
        ):
            east, north = local_km(site["lat"], site["lon"], r["lat"], r["lon"])
            if max(abs(east), abs(north)) >= hw - tol:
                r["cut"] = cuts[("cloud", lv)]


# ── words ───────────────────────────────────────────────────────────────────────────


def row_text(r: dict, tc: dict) -> str:
    """The row's one line of facts (no consideration, no confirm line)."""
    w = tc["words"]
    if r["event"] == "planning":
        return w["planning_row"].format(
            name=r["name"], kind=r["kind_name"], level=r["level"], engine=r["engine"]
        )

    # HB-178: a figure counted under a cut area is "at least", with what cut it
    def res(n: int) -> str:
        if r.get("cut"):
            return w["at_least"].format(n=f"{n:,}")
        return f"{n:,}"

    tail = w["cut_area"].format(by=r["cut"]) if r.get("cut") else ""

    def parts_text() -> str:
        # DN-028 ADDENDUM-12 decision 4: a count under the planning area is stated
        # with its parts, each "at least" where its own engine cut it
        pt = r.get("parts")
        if not pt:
            return ""

        def one(n: int, cut: bool) -> str:
            return w["at_least"].format(n=f"{n:,}") if cut else f"{n:,}"

        return w["parts"].format(
            cloud=one(pt["cloud"], pt["cloud_cut"]),
            check=one(pt["check"], pt["check_cut"]),
        )

    if r["event"] == "planning_population":
        return (
            w["planning_population_row"].format(
                residents=res(r["residents"]), level=r["level"], engine=r["engine"]
            )
            + parts_text()
            + tail
        )
    # DN-028 ADDENDUM-14 decision 10 (amending ADDENDUM-10 decision 3): a time from the
    # run under the stable treatment is marked with its vertical setting, every row
    mark = (
        w["unresolved_row"].format(vres=float(r["unresolved"]))
        if r.get("unresolved")
        else ""
    )
    if r["event"] == "clear":
        return w["clear_row"].format(name=r["name"], kind=r["place_kind_name"]) + mark
    if r["event"] == "population":
        form = w["population_row_slab"] if r.get("unresolved") else w["population_row"]
        s = (
            form.format(level=r["level"], residents=res(r["residents"]))
            + parts_text()
            + tail
        )
        if r.get("occupancy") and "work hours" in r["occupancy"]["phrase"]:
            if r.get("workers") is not None:
                s += w["population_workers"].format(workers=f"{r['workers']:,}")
        return s + mark
    if r["event"] == "group_quarters":
        return r["name"] + mark
    parts = [w["row"].format(name=r["name"], kind=r["kind_name"])]
    parts.append(w["above"].format(level=r["level"], mins=r["minutes_above"]))
    if r.get("clear_clock"):
        parts.append(w["clear"].format(level=r["level"], clock=r["clear_clock"]))
    else:
        parts.append(w["clear_never"].format(level=r["level"]))
    return (
        "; ".join(parts)
        + (w["cut_row"].format(by=r["cut"], level=r["level"]) if r.get("cut") else "")
        + mark
    )


def lead_text(r: dict, tc: dict) -> str:
    if r["lead_min"] < 0:
        return tc["words"]["past"]
    return tc["words"]["lead"].format(lead=span(r["lead_min"]))


def head_lines(brief, cfg: dict, rec: dict) -> list[str]:
    """The top of the page (decision 9): engine, wind, release end, scene clear, the
    brief's time, the population note and any disagreement notice DN-028 requires."""
    from hazbrief.brief import tevv

    tc = config()
    h = tc["head"]
    t0 = datetime.fromisoformat(rec["release_local"])
    out = [h["engine"].format(engine=rec["engine"], record=(rec["record"] or "")[:12])]
    m = rec.get("met")
    if m:
        out.append(
            h["wind"].format(
                first=_clock(t0, 0),
                dir=float(m["direction_deg"]),
                kmh=float(m["speed_m_s"]) * 3.6,
            )
        )
    rm = float(rec.get("release_minutes") or 0.0)
    out.append(h["release"].format(clock=_clock(t0, rm), hplus=hplus(rm)))
    if rec.get("scene_clear_min") is not None:
        s = rec["scene_clear_min"]
        out.append(h["scene_clear"].format(clock=_clock(t0, s), hplus=hplus(s)))
    elif rec.get("last_step_min") is not None:
        s = rec["last_step_min"]
        out.append(h["scene_open"].format(clock=_clock(t0, s), hplus=hplus(s)))
    out.append(h["brief_time"].format(clock=_clock(t0, rec["brief_minute"])))
    why = (rec.get("population") or {}).get("why")
    out.append(h["population_none"].format(why=why) if why else h["population_used"])
    # HB-173 item 12: the two methods' line, from the agreement record the checklist
    # item reads, never separate prose
    ag = (brief.derived or {}).get("agreement")
    if ag:
        from hazbrief.brief import agreement as AG

        acfg = AG.load_config()
        if rec.get("levels") == "planning":
            # DN-028 ADDENDUM-10 decisions 2 to 4: the top line says the levels are
            # SLAB's and every time is from SCICHEM's unresolved run, with the
            # Conditions of use; the measure stays in its section, never a warning
            out.append(AG.stable_line(ag, acfg, tevv.ref(cfg, "conditions_scichem")))
        else:
            out.append(
                h["engines"].format(
                    line=AG.line(ag, acfg), ref=tevv.ref(cfg, "agreement")
                )
            )
        far = max(
            (
                r["distance_m"] or 0.0
                for r in rec["rows"] + rec.get("untimed", [])
                if r.get("distance_m")
            ),
            default=0.0,
        )
        if ag.get("alert") and far >= float(h["disagree_far_from_m"]):
            out.append(h["disagree_far"].format(km=far / 1000.0))
    if rec.get("untimed"):
        out.append(h["untimed"].format(n=len(rec["untimed"])))
    return out


def counts(rec: dict) -> dict:
    """DN-028 ADDENDUM-10 item 6: per brief, the rows that keep a time, the rows with
    none and the place rows that left (where SLAB carries the levels)."""
    return {
        "levels": rec.get("levels"),
        "timed": len(rec.get("rows") or []),
        "untimed": len(rec.get("untimed") or []),
        "left": int(rec.get("left") or 0),
    }


# ── the page ────────────────────────────────────────────────────────────────────────


def swatch_defs(cfg: dict) -> str:
    """One hidden SVG holding each level's pattern (map.cloud.levels, map.patterns), as
    the map draws it, so a row's swatch reads in greyscale and on paper; once per
    page."""
    from hazbrief.brief.render import _pattern_body

    pats = []
    for lv in cfg["map"]["cloud"]["levels"].values():
        spec = cfg["map"]["patterns"][lv["id"]]
        g = spec["gap_px"]
        pats.append(
            f'<pattern id="tp-{lv["id"]}" patternUnits="userSpaceOnUse" width="{g}" '
            f'height="{g}" patternTransform="rotate({spec["angle"]})">'
            f'<rect width="{g}" height="{g}" fill="{esc(lv["color"])}" '
            f'fill-opacity="{cfg["map"]["cloud"]["fill_opacity"]}"/>'
            f"{_pattern_body(spec, lv['color'], cfg['map']['pattern_opacity'])}"
            "</pattern>"
        )
    return (
        '<svg class="tp-defs" width="0" height="0" aria-hidden="true" '
        f'style="position:absolute"><defs>{"".join(pats)}</defs></svg>'
    )


def _swatch(level: str | None, cfg: dict) -> str:
    """The level's swatch, filled with its pattern from `swatch_defs`."""
    if not level:
        return ""
    lv = cfg["map"]["cloud"]["levels"][level]
    return (
        f'<svg class="sw" width="22" height="14" role="img" aria-label="{esc(level)}">'
        f'<rect width="22" height="14" fill="url(#tp-{lv["id"]})" stroke="#333333" '
        'stroke-width="1"/></svg>'
    )


def _quote_html(q: dict) -> str:
    return (
        f'<blockquote class="quote" data-doc="{esc(q["doc"])}">'
        f"<q>{esc(q['text'])}</q> <cite>{esc(q['ref'])}</cite></blockquote>"
    )


def _row_html(r: dict, cfg: dict, tc: dict) -> str:
    w = tc["words"]
    occ = r.get("occupancy")
    occ_html = (
        f'<p class="occ" data-line="{esc(occ["line"])}">{esc(occ["phrase"])}</p>'
        if occ
        else ""
        if r["kind"] in tc["occupancy_not_applicable"]
        else f'<p class="occ none">{esc(w["no_expectation"])}</p>'
    )
    cons = "".join(_quote_html(q) for q in r.get("consider") or [])
    cons_html = (
        f'<div class="consider"><span class="h">{esc(w["consider_head"])}</span>'
        f"{cons}</div>"
        if cons
        else ""
    )
    ver = r.get("verify")
    ver_html = (
        f'<p class="verify"><span class="h">{esc(w["verify_head"])}:</span> '
        f'{esc(ver)} · <span class="ck" data-check="wind">'
        f"{esc(tc['checklist_words'])}</span></p>"
        if ver
        else ""
    )
    level = r.get("level")
    return (
        f'<li class="trow" id="r{r["n"]}" data-event="{esc(r["event"])}" '
        f'data-kind="{esc(r["kind"])}" data-level="{esc(level or "")}" '
        f'data-minute="{r["arrival_min"]:g}" data-step="{r["step_index"]}">'
        f'<p class="when"><span class="n">{r["n"]}</span> '
        f'<strong class="clock">{esc(r["clock"])}</strong> '
        f'<span class="hplus">{esc(r["hplus"])}</span> '
        f"{_swatch(level, cfg)}"
        f'<span class="lvl">{esc(level or "")}</span> '
        f'<span class="lead">{esc(lead_text(r, tc))}</span></p>'
        f'<p class="what">{esc(row_text(r, tc))}</p>'
        f"{occ_html}{cons_html}{ver_html}</li>"
    )


def _untimed_html(r: dict, cfg: dict, tc: dict) -> str:
    """HB-173: a row with no time (inside a planning shape, outside the cloud): its
    number, level, the words naming the engine, what the held sources say and who can
    confirm; no clock, no lead and no occupancy, which needs an hour."""
    w = tc["words"]
    cons = "".join(_quote_html(q) for q in r.get("consider") or [])
    cons_html = (
        f'<div class="consider"><span class="h">{esc(w["consider_head"])}</span>'
        f"{cons}</div>"
        if cons
        else ""
    )
    ver = r.get("verify")
    ver_html = (
        f'<p class="verify"><span class="h">{esc(w["verify_head"])}:</span> '
        f"{esc(ver)}</p>"
        if ver
        else ""
    )
    level = r.get("level")
    return (
        f'<li class="trow untimed" id="r{r["n"]}" data-event="{esc(r["event"])}" '
        f'data-kind="{esc(r["kind"])}" data-level="{esc(level or "")}">'
        f'<p class="when"><span class="n">{r["n"]}</span> '
        f'<strong class="clock">{esc(w["no_time"])}</strong> '
        f"{_swatch(level, cfg)}"
        f'<span class="lvl">{esc(level or "")}</span></p>'
        f'<p class="what">{esc(row_text(r, tc))}</p>'
        f"{cons_html}{ver_html}</li>"
    )


def _groups(rec: dict, tc: dict) -> list[tuple[str, list[dict]]]:
    t0 = datetime.fromisoformat(rec["release_local"])
    size = int(tc["group_minutes"])
    # half hours of clock time: the group a row's arrival clock falls in
    base = t0.hour * 60 + t0.minute
    out: dict[int, list[dict]] = {}
    for r in rec["rows"]:
        clock_min = base + round(r["arrival_min"])
        g = clock_min // size
        out.setdefault(g, []).append(r)
    groups = []
    for g, rows in sorted(out.items()):
        start = g * size - base
        end = start + size - 1
        groups.append(
            (
                tc["group_head"].format(
                    start=_clock(t0, start),
                    end=_clock(t0, end),
                    hstart=hplus(max(start, 0)),
                    hend=hplus(max(end, 0)),
                ),
                rows,
            )
        )
    return groups


def crossings(brief, cfg: dict, rec: dict) -> list[dict]:
    """HB-189 Part C item 10 (Desktop's assumption, to carry time sensitivity as a short
    list): under the stable treatment, each major road (`derive.roads.classes`, the
    primary and secondary roads) where a candidate block crosses the AEGL-2 planning
    area's boundary, with the first step at which the moving cloud's AEGL-2 area comes
    within the road lookup's merge distance of the crossing, or no time where only
    SLAB's extent check reaches it there. Nothing new is fetched or recorded: the
    candidates and the cloud's steps are held. The nearest unit's drive time to a
    crossing is not held, and the list says so."""
    import shapely
    from shapely.geometry import Point, shape

    from hazbrief.brief import derive as D

    if rec.get("levels") != "planning":
        return []
    d = brief.derived or {}
    tc = config()
    cw = tc["crossings"]
    level = cw["level"]
    major = set(cfg["derive"]["roads"]["classes"])
    cands = [
        c
        for c in (d.get("modelled_cordons") or {}).get("candidates") or []
        if c.get("mtfcc") in major
    ]
    cl = d.get("cloud") or {}
    steps = [
        (s["minute"], shapely.make_valid(shape(s["tiers"][level])))
        for s in cl.get("steps") or []
        if (s.get("tiers") or {}).get(level)
    ]
    merge = float(cfg["derive"]["roads"]["merge_m"])
    t0 = _release_local(brief, cl)
    out = []
    for c in cands:
        x = Point(c["crossing"])
        first = next(
            (
                m
                for m, g in steps
                if D._metres(x, g.boundary, x) <= merge or g.covers(x)
            ),
            None,
        )
        when = (
            cw["at"].format(clock=_clock(t0, first), hplus=hplus(first))
            if first is not None
            else cw["no_time"]
        )
        out.append(
            {
                "road": c.get("road") or "unnamed",
                "minute": first,
                "text": cw["row"].format(road=c.get("road") or "unnamed", when=when),
            }
        )
    out.sort(key=lambda r: (r["minute"] is None, r["minute"] or 0, r["road"]))
    return out[: int(cw["max_rows"])]


def off_map_blocks(brief, cfg: dict) -> list[dict]:
    """HB-192 (DN-024 ADDENDUM-01 decision 9): every road candidate the first map does
    not draw (`layers.on_first_map`), from both road candidate layers, in the order
    the data holds them."""
    from hazbrief.brief import layers as LY

    fm = cfg["map"]["first_map_blocks"]
    d = brief.derived or {}
    out = []
    for name in ("roads", "modelled_cordons"):
        for k in (d.get(name) or {}).get("candidates") or []:
            if not LY.on_first_map(k, fm, cfg):
                out.append(k)
    return out


def blocks_table_html(brief, cfg: dict, tc: dict) -> str:
    """HB-192: the Timeline page's table of the candidate blocks not drawn on the first
    map (road, class, boundary, the point), so every candidate stays listed; none
    where the first map draws them all."""
    from hazbrief.brief import layers as LY

    rows = off_map_blocks(brief, cfg)
    if not rows:
        return ""
    w = tc["blocks_table"]
    body = "".join(
        f"<tr><td>{esc(k.get('road') or '')}</td><td>{esc(k.get('mtfcc') or '')}</td>"
        f"<td>{esc(LY._zone_text(k.get('zone') or ''))}</td>"
        f"<td>{k['coordinates'][1]:.5f}, {k['coordinates'][0]:.5f}</td></tr>"
        for k in rows
    )
    return (
        f'<section id="off-map-blocks"><h2>{esc(w["head"].format(n=len(rows)))}</h2>'
        f"<p>{esc(w['note'])}</p><table><thead><tr>"
        + "".join(f"<th>{esc(h)}</th>" for h in w["columns"])
        + f"</tr></thead><tbody>{body}</tbody></table></section>"
    )


def page_html(brief, cfg: dict, data: dict | None = None) -> str:
    """`timeline.html` (task item 9): the EXERCISE banner at top and bottom, the head,
    the first minutes and the time to act from the held sources, then every row in time
    order grouped by half hour; a brief whose cloud is not drawn says why in one
    line."""
    from hazbrief.brief.render import _material_name

    tc = config()
    page = cfg["page"]
    fp = (brief.channels.get("protective_action_footprint") or {}).get("payload") or {}
    name = _material_name(fp.get("material") or {}) or brief.scenario_id
    title = tc["title"].format(name=f"{name} ({brief.scenario_id})")
    rec = build(brief, cfg, data)
    from hazbrief.brief import tevv

    tref = tevv.link_html(cfg, "threat_timeline") if rec["state"] == "drawn" else ""
    if rec["state"] != "drawn":
        why = tc["head"]["not_modelled"].format(why=rec["reason"])
        body = f'<p id="not-modelled">{esc(why)}</p>'
    else:
        head = "".join(f"<li>{esc(x)}</li>" for x in head_lines(brief, cfg, rec))
        first = "".join(_quote_html(tc["quotes"][k]) for k in tc["first_minutes"])
        act = "".join(_quote_html(tc["quotes"][k]) for k in tc["time_to_act"])
        groups = "".join(
            f'<section class="tgroup"><h2>{esc(h)}</h2><ol class="trows">'
            + "".join(_row_html(r, cfg, tc) for r in rows)
            + "</ol></section>"
            for h, rows in _groups(rec, tc)
        )
        if rec.get("untimed"):
            groups += (
                f'<section class="tgroup" id="untimed">'
                f"<h2>{esc(tc['words']['untimed_head'])}</h2>"
                f"<p>{esc(tc['words']['untimed_note'])} "
                f"{tevv.link_html(cfg, 'planning_shape')}</p>"
                '<ol class="trows">'
                + "".join(_untimed_html(r, cfg, tc) for r in rec["untimed"])
                + "</ol></section>"
            )
        cross = crossings(brief, cfg, rec)
        cw = tc["crossings"]
        cross_html = (
            f'<section id="crossings"><h2>{esc(cw["head"])}</h2>'
            f"<p>{esc(cw['note'])}</p><ol>"
            + "".join(f"<li>{esc(x['text'])}</li>" for x in cross)
            + "</ol></section>"
            if cross
            else ""
        )
        body = (
            f'{swatch_defs(cfg)}<ul id="head">{head}</ul>{cross_html}'
            f'<p id="occupancy-note">{esc(tc["occupancy_note"])}</p>'
            f'<p id="msel"><a href="{esc(tc["csv_file"])}" download>'
            f"{esc(tc['msel']['link'])}</a> {esc(tc['msel']['note'])}</p>"
            f'<section id="first-minutes">'
            f"<h2>{esc(tc['head']['first_minutes_head'])}</h2>"
            f"{first}</section>"
            f'<section id="time-to-act"><h2>{esc(tc["head"]["time_to_act_head"])}</h2>'
            f"{act}</section>"
            f'<div id="rows">{groups}</div>'
            f"{blocks_table_html(brief, cfg, tc)}"
        )
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{esc(title)}</title><style>"
        f"body {{ font-family: {page['font_stack']}; margin: 0; color: #1a1a1a; }}"
        " main { margin: 16px 32px; max-width: 1100px; }"
        " .banner { background: #b00020; color: #fff; text-align: center;"
        " font-weight: 700; padding: 6px; letter-spacing: 0.08em; }"
        " #head { font-size: 14px; } #head li { margin: 2px 0; }"
        " h2 { font-size: 16px; border-top: 1px solid #cccccc; padding-top: 6px; }"
        " blockquote.quote { margin: 4px 0 4px 16px; font-size: 13px; }"
        " blockquote.quote cite { color: #595959; font-style: normal; }"
        " ol.trows { list-style: none; padding: 0; margin: 0; }"
        " li.trow { border-bottom: 1px solid #e0e0e0; padding: 4px 0; }"
        " li.trow:target { background: #fff8e1; }"
        " li.trow p { margin: 2px 0; font-size: 13px; }"
        " .when .n { color: #595959; font-variant-numeric: tabular-nums; }"
        " .when .clock { font-size: 15px; font-variant-numeric: tabular-nums; }"
        " .when .hplus, .lead { color: #595959; }"
        " svg.sw { vertical-align: middle; margin: 0 4px; }"
        " .lvl { font-weight: 700; }"
        " .occ { font-style: italic; } .consider { font-size: 13px; }"
        " .verify .h, .consider .h { font-weight: 700; }"
        " @media print { .banner { -webkit-print-color-adjust: exact;"
        " print-color-adjust: exact; } li.trow { break-inside: avoid; }"
        " svg.sw { -webkit-print-color-adjust: exact; print-color-adjust: exact; }"
        " main { margin: 0 12px; max-width: none; } a { color: #1a1a1a; } }"
        "</style></head><body>"
        f'<header id="top" class="banner">{esc(page["banner"])}</header><main>'
        f"<h1>{esc(title)}</h1><p>{esc(tc['lede'])} {tref}</p>{body}</main>"
        f'<footer id="bottom" class="banner">{esc(page["banner"])}</footer>'
        "</body></html>\n"
    )


# ── the exercise events list ────────────────────────────────────────────────────────


def message(r: dict, tc: dict, rec: dict) -> str:
    s = row_text(r, tc)
    if r.get("level") and r["event"] in ("arrival", "population", "group_quarters"):
        s = f"{r['level']}: {s}"
    return (
        s
        + ". "
        + tc["words"]["source"].format(
            engine=rec.get("engine"), record=(rec.get("record") or "")[:12]
        )
    )


def msel_csv(brief, cfg: dict, data: dict | None = None) -> str:
    """`timeline.csv` (task item 12): one row per timeline row in the HSEEP doctrine's
    MSEL entry columns, marked EXERCISE; the event number, time and message filled
    from the record and the planner's columns left empty."""
    tc = config()
    ms = tc["msel"]
    rec = build(brief, cfg, data)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow([ms["marking_column"]] + [c["name"] for c in ms["columns"]])
    # HB-173 Part B item 7: the events list follows the timeline, its untimed rows too
    for r in rec["rows"] + rec.get("untimed", []):
        vals = {
            "n": str(r["n"]),
            "time": ms["time"].format(clock=r["clock"], hplus=r["hplus"])
            if r.get("clock")
            else tc["words"]["no_time"],
            "message": message(r, tc, rec),
        }
        w.writerow(
            [ms["marking"]]
            + [vals[c["fill"]] if c["fill"] else "" for c in ms["columns"]]
        )
    return buf.getvalue()


# ── the first view ──────────────────────────────────────────────────────────────────


def first_view_html(brief, cfg: dict, data: dict | None = None) -> str:
    """Task item 10: the next rows from the brief's time, above the Hazard group's
    rows; each a button that moves the time control to the row's arrival, with a link
    to its row on the Timeline page; then one line naming the rest. Nothing where no
    cloud is drawn."""
    tc = config()
    rec = build(brief, cfg, data)
    if rec["state"] != "drawn":
        return ""
    n = int(tc["first_view_rows"])
    nxt = next_rows(rec, n)
    rest = len([r for r in rec["rows"] if r["lead_min"] >= 0]) - len(nxt)
    items = "".join(
        f'<li class="tn"><button type="button" class="tn-go" '
        f'data-step="{r["step_index"]}" data-minute="{r["arrival_min"]:g}">'
        f'<span class="clock">{esc(r["clock"])}</span> '
        f"{_swatch(r.get('level'), cfg)}"
        f"{esc(_short(r, tc))}</button> "
        f'<a class="tn-ref" href="{esc(tc["file"])}#r{r["n"]}" target="_blank" '
        f'rel="noopener" title="{esc(row_text(r, tc))}">#{r["n"]}</a></li>'
        for r in nxt
    )
    more = (
        f'<li class="tn-more"><a href="{esc(tc["file"])}" target="_blank" '
        f'rel="noopener">{esc(tc["first_view_more"].format(n=rest))}</a></li>'
        if rest > 0
        else ""
    )
    if not items:
        items = f'<li class="tn-more">{esc(tc["first_view_none"])}</li>'
    return (
        f'<li id="threat-next" class="tnext" aria-label="{esc(tc["first_view_head"])}">'
        f'{swatch_defs(cfg)}<ul class="tn-rows">{items}{more}</ul></li>'
    )


def _short(r: dict, tc: dict) -> str:
    """A first-view row's few words: the place (or the population row's kind) and its
    level."""
    if r["event"] == "clear":
        return f"{r['name']}: {tc['area_kinds']['clear']['name']}"
    if r["event"] == "population":
        return f"{r['level']}: {tc['area_kinds']['population']['name']}"
    return f"{r['level']}: {r['name']}"


def link_html(cfg: dict) -> str:
    """The header link beside TEVV's."""
    tc = config()
    return (
        f'<a id="timeline-link" href="{esc(tc["file"])}" target="_blank" '
        f'rel="noopener" title="{esc(tc["link_title"])}">{esc(tc["link_text"])}</a>'
    )
