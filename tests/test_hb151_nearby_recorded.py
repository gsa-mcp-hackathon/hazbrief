"""HB-151: the nearby stations and travel roads recorded for the reference pair, and
the search that widens for a class short of `per_class`.

Seeded stations prove the widening rule (HB-151 item 2): a class with fewer than
`per_class` outside the footprint inside the radius widens until `per_class` are found
or `radius_ceiling_m` is reached, and the section prints the widened radius. The pair
(csx-point-of-rocks day and night, whose National Structures Dataset and TIGERweb travel
roads HB-151 recorded) proves fire, EMS, police and hospitals each list their nearest
outside the footprint with distance, bearing and free-flow travel time; every other
brief keeps its degraded line (DN-011 D2).
"""

from __future__ import annotations

import asyncio
import functools
import math
from pathlib import Path

import pytest
from shapely.geometry import Point
from shapely.ops import unary_union

from hazbrief import facilities
from hazbrief.brief import cli, derive, layers
from hazbrief.brief.orchestrator import assemble, load_config
from hazbrief.evidence import labels as L
from hazbrief.evidence import store as S

REPO = Path(__file__).resolve().parents[1]
BRIEFS = REPO / "docs" / "briefs"
PAIR = ["csx-point-of-rocks-day", "csx-point-of-rocks-night"]
#: HB-175 Part C item 10 (Issue 30ffc074): the briefs whose stations, travel roads,
#: offsets and siting are recorded live: the pair (HB-140R, HB-151) and, off the pair,
#: i81-md-pa-line-day (HB-175), the third case where its record supports it
RECORDED = [*PAIR, "i81-md-pa-line-day"]
#: HB-178 (Issue 76400690): every listed service has a time or a stated reason; on
#: i81 day one fire station's nearest held road is not joined to the incident's within
#: the travel classes, and its row says "no route in the held roads" with its
#: straight-line distance and bearing (docs/evidence/hb178/marion.md)
TIMED = RECORDED
OTHER = "un1977-wilson-bridge"

LAT0, LON0 = 39.0, -77.0
DLON = 1 / (facilities._M_PER_DEG * math.cos(math.radians(LAT0)))
DLAT = 1 / facilities._M_PER_DEG


def _xy(x_m: float, y_m: float) -> list[float]:
    return [LON0 + x_m * DLON, LAT0 + y_m * DLAT]


def _footprint(half_m: float = 1000, pad_m: float = 1000) -> dict:
    ring = [_xy(-half_m, -half_m), _xy(half_m, -half_m), _xy(half_m, half_m)]
    ring += [_xy(-half_m, half_m), _xy(-half_m, -half_m)]
    square = {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [ring]},
        "properties": {"zone": "protective_action_zone"},
    }
    return {
        "footprint": {"type": "FeatureCollection", "features": [square]},
        "zones": {"protective_action_zone": {"distance": {"metres": pad_m}}},
    }


def _station(name, x_m, y_m) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": _xy(x_m, y_m)},
        "properties": {"NAME": name, "PERMANENT_IDENTIFIER": name},
    }


@functools.lru_cache(maxsize=4)
def _brief(sid: str):
    s = cli.load_scenario(BRIEFS / sid / "scenario.json")
    return asyncio.run(
        assemble(
            s,
            now=S.parse_time(L.config()["fixture_now"]),
            replay_stores=cli.replay_stores(),
        )
    )


def _section(sid: str) -> str:
    page = (BRIEFS / sid / "brief.html").read_text(encoding="utf-8")
    sec = page[page.index('id="section-facilities"') :]
    return sec[: sec.index("</section>")]


# ── item 2: the search widens for a class short of per_class ─────────────────────────


def test_the_ceiling_is_configured_at_50_km():
    # HB-155 ADDENDUM-01 item 2 restated: one key, `derive.area`; the ceiling is 100
    # miles (160,934 m) and the radius 10 miles (ADDENDUM-02 item 2)
    spec = load_config()["derive"]["area"]
    assert spec["ceiling_m"] == 160934
    assert spec["ceiling_m"] >= spec["radius_m"] == 16093


@pytest.mark.verifies("VR-156")
def test_a_class_short_inside_the_radius_widens_to_its_nth_nearest():
    cfg = load_config()
    # HB-155 ADDENDUM-01 item 3 restated: every facility inside the radius is kept; a
    # class with none inside widens to exactly its nearest (not to its n-th)
    fire = [
        _station("past the radius", 0, 19000),
        _station("further", -25000, 0),
        _station("past the ceiling", 170000, 0),
    ]
    out = derive.nearby_services(
        Point(LON0, LAT0), _footprint(), {"fire": fire}, None, cfg
    )
    names = [r["name"] for r in out["classes"]["fire"]]
    assert names == ["past the radius"]
    assert [r["name"] for r in out["beyond"]["fire"]] == ["further"]
    s = out["search"]["fire"]
    assert s["widened"] is True and s["ceiling"] is False
    assert s["radius_m"] == out["classes"]["fire"][-1]["distance_m"]
    assert out["radius_m"] == 16093  # the class widens; the brief's radius stands


def test_a_class_with_enough_inside_the_radius_does_not_widen():
    cfg = load_config()
    # HB-155 ADDENDUM-01 item 3 restated: all four inside the radius are kept, not 3
    fire = [_station(f"s{i}", 1500 + 500 * i, 0) for i in range(4)]
    fire.append(_station("far", 19000, 0))
    out = derive.nearby_services(
        Point(LON0, LAT0), _footprint(), {"fire": fire}, None, cfg
    )
    assert [r["name"] for r in out["classes"]["fire"]] == ["s0", "s1", "s2", "s3"]
    assert out["search"]["fire"] == {
        "radius_m": 16093.0,
        "widened": False,
        "ceiling": False,
        "found": 4,
    }


@pytest.mark.verifies("VR-156")
def test_a_class_short_at_the_ceiling_says_so():
    cfg = load_config()
    # HB-155 ADDENDUM-01 item 3 restated: a class with none inside the ceiling prints
    # the ceiling line; one past the ceiling is never kept
    ceiling = float(cfg["derive"]["area"]["ceiling_m"])
    police = [_station("past", ceiling + 5000, 0)]
    out = derive.nearby_services(
        Point(LON0, LAT0), _footprint(), {"police": police}, None, cfg
    )
    assert out["classes"]["police"] == []
    s = out["search"]["police"]
    assert s == {"radius_m": ceiling, "widened": True, "ceiling": True, "found": 0}
    # a class with nothing at all reaches the ceiling too
    assert out["search"]["ems"]["ceiling"] is True
    assert out["search"]["ems"]["found"] == 0


def test_the_stations_are_read_in_the_ceilings_box():
    # HB-155 ADDENDUM-02 item 4 restated (it superseded ADDENDUM-01 item 4's ceiling
    # box): the stations are read in the box the caller names (stage one the area
    # radius's, stage two the 20-mile step's), not the ceiling's
    cfg = load_config()
    seen = []

    async def fake(api, path, bbox, out_fields, page):
        seen.append(bbox)
        return [], []

    orig = facilities.arcgis_features
    facilities.arcgis_features = fake
    try:
        asyncio.run(derive.fetch_stations(Point(LON0, LAT0), 18900.0, cfg))
    finally:
        facilities.arcgis_features = orig
    want = derive._bbox([Point(LON0, LAT0)], 18900.0)
    assert seen and set(seen) == {want}


# ── item 3: the pair draws fire, EMS, police and hospitals ───────────────────────────


@pytest.mark.verifies("VR-156")
@pytest.mark.parametrize("sid", RECORDED)
def test_on_the_pair_each_class_lists_per_class_or_the_ceiling(sid):
    d = _brief(sid).derived["nearby"]
    assert d["stations_reason"] is None and d["hospitals_reason"] is None
    assert d["travel_reason"] is None
    # HB-155 ADDENDUM-01 item 3 restated: every one inside the radius, or the nearest
    for cls in ("fire", "ems", "police", "hospital"):
        rows, s = d["classes"][cls], d["search"][cls]
        assert rows and (
            s["widened"] == (len(rows) == 1 and rows[0]["distance_m"] > d["radius_m"])
        ), cls
        assert s["found"] == len(rows)


@pytest.mark.verifies("VR-156")
@pytest.mark.verifies("VR-157")
@pytest.mark.parametrize("sid", TIMED)
def test_on_the_pair_every_service_is_outside_sorted_and_has_a_travel_time(sid):
    b = _brief(sid)
    d = b.derived["nearby"]
    fp = b.channels["protective_action_footprint"]["payload"]
    area = unary_union([p for _, p in derive.zone_polygons(fp)])
    incident = derive.incident_point(b, fp)
    n = 0
    for cls, rows in d["classes"].items():
        dists = [r["distance_m"] for r in rows]
        assert dists == sorted(dists), cls
        for r in rows:
            n += 1
            assert not area.covers(Point(r["coordinates"])), r["name"]
            assert r["distance_m"] <= d["search"][cls]["radius_m"]
            got = facilities.inverse(
                incident.y, incident.x, r["coordinates"][1], r["coordinates"][0]
            )[0]
            assert abs(got - r["distance_m"]) <= 1
            t = r["travel"]
            if t.get("no_route"):
                # HB-178: what is known, no time estimated
                assert t["minutes"] is None
                assert t["reason"].startswith("no route in the held roads"), t
                assert f"{r['distance_m'] / 1000:,.1f} km" in t["reason"], t
                assert "in a straight line, bearing" in t["reason"]
                continue
            assert t["minutes"] is not None and t["minutes"] > 0, r["name"]
            assert isinstance(t["crosses_footprint"], bool)
    assert n >= 4  # HB-155: each class drew at least its nearest


@pytest.mark.verifies("VR-156")
@pytest.mark.verifies("VR-157")
@pytest.mark.parametrize("sid", RECORDED)
def test_the_pairs_section_prints_each_class_with_its_time_and_the_label(sid):
    sec = _section(sid)
    out = sec[sec.index("Nearest outside the footprint: the services that respond") :]
    for title in ("Fire", "EMS", "Police", "Hospitals"):
        assert f"<td>{title}</td>" in out, title
    assert "not derived" not in out
    assert " min" in out
    assert "no live traffic; assumed speeds, no held source" in out


@pytest.mark.verifies("VR-156")
def test_csx_day_widens_for_its_hospitals_and_prints_the_widened_radius():
    d = _brief("csx-point-of-rocks-day").derived["nearby"]
    s = d["search"]["hospital"]
    assert s["widened"] is True and s["ceiling"] is False
    names = [r["name"] for r in d["classes"]["hospital"]]
    assert names[0] == "FREDERICK HEALTH HOSPITAL"
    # HB-155 ADDENDUM-01 item 3 restated: the line names the widening to the nearest
    words = load_config()["derive"]["nearby"]["widened_line"].format(
        title="Hospitals",
        radius=f"{d['radius_m'] / 1000:,.1f} km",
        widened=f"{s['radius_m'] / 1000:,.1f} km",
    )
    assert words in _section("csx-point-of-rocks-day").replace("&#x27;", "'")


@pytest.mark.verifies("VR-157")
@pytest.mark.parametrize("sid", TIMED)
def test_the_pairs_layer_draws_every_listed_service_with_its_travel_time(sid):
    lay = {x["id"]: x for x in layers.build(_brief(sid), load_config())["layers"]}[
        "nearby_services"
    ]
    d = _brief(sid).derived["nearby"]
    # HB-155 ADDENDUM-01 item 5 restated: the map draws every kept facility and those in
    # hand beyond the radius (the reader's wider steps filter them), and the area's ring
    places = [f for f in lay["features"] if not f["properties"].get("ring")]
    kept = sum(len(v) for v in d["classes"].values())
    beyond = sum(len(v) for v in d["beyond"].values())
    assert len(places) == kept + beyond
    for f in places:
        pop = f["properties"]["popup"]
        assert "Travel time" in pop
        if f["properties"]["area_m"] <= d["radius_m"]:
            assert "not computed" not in pop


@pytest.mark.verifies("VR-157")
def test_a_route_that_crosses_a_zone_keeps_its_flag():
    """The flag is the derivation's (HB-142R); here it is carried to the page and the
    popup wherever the pair's routes cross."""
    for sid in RECORDED:
        d = _brief(sid).derived["nearby"]
        lay = {x["id"]: x for x in layers.build(_brief(sid), load_config())["layers"]}[
            "nearby_services"
        ]
        # HB-155 restated: every row in hand (kept and beyond) carries its flag
        crossing = [
            r
            for v in [*d["classes"].values(), *d["beyond"].values()]
            for r in v
            if (r.get("travel") or {}).get("crosses_footprint")
        ]
        flagged = [
            f
            for f in lay["features"]
            if "the responder goes around it" in f["properties"]["popup"]
        ]
        assert len(flagged) == len(crossing), sid


@pytest.mark.verifies("VR-156")
def test_off_the_pair_the_degraded_line_still_prints():
    sec = _section(OTHER)
    assert "Fire, EMS and police: not derived: its upstream answer is not recorded" in (
        sec
    )
