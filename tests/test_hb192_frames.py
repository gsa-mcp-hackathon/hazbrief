"""HB-192 (DN-024 ADDENDUM-01): the moving cloud's 15-minute frames on a coarse mesh,
the Play control and the status line, a page that carries only what it draws, and the
benchmark requirement in the graph.

One module, one cached assembly (ADDENDUM-03 item 7): the committed pages and the held
frames records are read as files; the one assembly here (`_assembled`) is made with the
mesh's decoder and outliner refused, so it also holds that a replay computes no frame.
"""

from __future__ import annotations

import asyncio
import functools
import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from shapely.geometry import MultiLineString, shape

from hazbrief.brief import cli, layers, threat
from hazbrief.brief import frames as F
from hazbrief.brief import scichem as SC
from hazbrief.brief import scichem_driver as DRV
from hazbrief.brief.orchestrator import assemble, load_config
from hazbrief.evidence import labels as L
from hazbrief.evidence import store as S

ROOT = Path(__file__).resolve().parents[1]
BRIEFS = ROOT / "docs" / "briefs"
EVIDENCE = ROOT / "docs" / "evidence" / "hb192"

#: every committed dense brief HB-189 runs at 1.25 m, and its request A (HB-189
#: `night_runs.tsv`), whose run the frames are taken from
DENSE = {
    "csx-point-of-rocks-night": "1ab3ae1616e7",
    "i495-wilson-bridge-night": "e299d4f64df8",
    "i81-md-pa-line-night": "85331d217411",
    "i83-md-pa-line-night": "f9bc1edb6801",
    "i81-md-pa-line-day": "99b9d82f9442",
    "csx-point-of-rocks-day": "0e814dc802c9",
    "i495-wilson-bridge-day": "7bedd60d90d9",
    "i83-md-pa-line-day": "98f0e376b1fc",
    "csx-point-of-rocks-crossing": "406b1d0f555f",
    "i495-wilson-bridge-address": "0fc9b5ac29dd",
    "i495-wilson-bridge-cross-streets": "cddf33eca272",
    "i81-md-pa-line-milepost": "06f0867e9474",
    "un1005-i81": "6ca55b1ae67c",
}
#: tools hazbrief does not run, named on the TEVV page only (the standing rule)
NOT_RUN = ("HPAC", "ALOHA")


def _held(prefix: str) -> dict:
    sc = SC.load_config()
    path = next((ROOT / sc["recordings_dir"]).glob(prefix + "*.json"))
    return json.loads(path.read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=None)
def _frames(prefix: str) -> dict:
    rec = F.read_record(_held(prefix)["request_sha256"])
    assert rec is not None, f"no frames record for request A {prefix}"
    return rec


def _page(bid: str, name: str = "brief.html") -> str:
    return (BRIEFS / bid / name).read_text(encoding="utf-8")


def _map_data(bid: str) -> dict:
    m = re.search(
        r'<script type="application/json" id="map-data">(.*?)</script>',
        _page(bid),
        re.S,
    )
    return json.loads(m.group(1))


_REFUSED: list[str] = []


@functools.lru_cache(maxsize=1)
def _assembled():
    """csx night assembled by replay with the mesh's decoder and outliner refused: a
    replay reads the stored outlines and computes no frame (ADDENDUM-03 item 7)."""
    saved = {n: getattr(F, n) for n in ("decode", "outline", "simplify", "stored")}

    def refuse(name):
        def f(*a, **k):
            _REFUSED.append(name)
            raise AssertionError(f"a replay called frames.{name}")

        return f

    for n in saved:
        setattr(F, n, refuse(n))
    try:
        s = cli.load_scenario(BRIEFS / "csx-point-of-rocks-night" / "scenario.json")
        return asyncio.run(
            assemble(
                s,
                now=S.parse_time(L.config()["fixture_now"]),
                replay_stores=cli.replay_stores(),
            )
        )
    finally:
        for n, f in saved.items():
            setattr(F, n, f)


# ── Part B: the frames ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("bid", sorted(DENSE))
def test_frames_are_every_15_minutes_over_the_horizon(bid):
    rec = _frames(DENSE[bid])
    held = _held(DENSE[bid])
    cfg = load_config()
    horizon_min = int(cfg["weather"]["puff"]["steps"]["horizon_h"] * 60)
    assert rec["spec"]["every_s"] == 900.0
    assert rec["spec"]["until_s"] == horizon_min * 60.0
    # to the horizon, or to the run's last output step where the run ends sooner
    # (the engine stops when the cloud has gone: day briefs)
    last_step = round(held["result"]["steps"][-1]["time_s"] / 60.0)
    last = min(horizon_min, last_step - last_step % 15)
    assert [f["minute"] for f in rec["frames"]] == list(range(15, last + 1, 15))
    assert rec["made"] == "backfill" and rec["check"]["contours_differing"] == 0


@pytest.mark.parametrize("bid", sorted(DENSE))
def test_a_frame_holds_a_mesh_and_its_outlines_only(bid):
    allowed = {"minute", "engine_wall_s", "shown_wall_s", "mesh", "outlines"}
    mesh_keys = {
        "x0_km",
        "y0_km",
        "dx_km",
        "dy_km",
        "nx",
        "ny",
        "floor_kg_m3",
        "per_decade",
        "codes_gz_b64",
    }
    for fr in _frames(DENSE[bid])["frames"]:
        assert set(fr) <= allowed
        if fr.get("mesh"):
            assert set(fr["mesh"]) == mesh_keys
            g = F.decode(fr["mesh"])
            assert g.values.shape == (fr["mesh"]["ny"], fr["mesh"]["nx"])


def test_a_stored_outline_is_within_the_stated_tolerance_of_the_unsimplified_one():
    cfg = SC.load_config()["frames"]
    tol_km = float(cfg["tolerance_m"]) / 1000.0
    within_km = float(cfg["drawn_within_m"]) / 1000.0
    held = _held(DENSE["csx-point-of-rocks-night"])
    levels = F.levels_of(held["request"])
    checked = 0
    for fr in _frames(DENSE["csx-point-of-rocks-night"])["frames"]:
        if not fr.get("mesh"):
            continue
        g = F.decode(fr["mesh"])
        for name, kg in levels:
            # the documented rule: parts smaller than the tolerance's square are dropped
            raw = F.small_parts_dropped(F.outline(g, kg), tol_km)
            rings = [r for poly in fr["outlines"][name] for r in poly]
            if raw.is_empty:
                assert not rings
                continue
            # the rings as the page draws them (rounded to a metre, `scichem._rings`),
            # as lines: no repair, which would drop a spike the rounding pinched
            stored = MultiLineString(rings)
            d = raw.boundary.hausdorff_distance(stored)
            assert d <= within_km, (fr["minute"], name, d)
            checked += 1
    assert checked >= 40


def test_the_mesh_is_finer_than_the_first_view_and_its_spacing_is_stated():
    cfg = SC.load_config()["frames"]
    assert cfg["spacing_m"] == 25.0 and cfg["drawn_within_m"] == 25.0
    for bid in DENSE:
        for fr in _frames(DENSE[bid])["frames"]:
            if fr.get("mesh"):
                assert fr["mesh"]["dx_km"] >= 0.025 - 1e-9


def test_the_lookup_reads_the_level_inside_its_outline():
    fr = next(
        f
        for f in _frames(DENSE["csx-point-of-rocks-night"])["frames"]
        if f["minute"] == 60
    )
    g = F.decode(fr["mesh"])
    levels = F.levels_of(_held(DENSE["csx-point-of-rocks-night"])["request"])
    for name, kg in levels:
        shp = SC.shape_of(fr["outlines"][name])
        if shp.is_empty:
            continue
        p = shp.representative_point()
        v = F.lookup(g, p.x, p.y)
        # inside the simplified outline (moved 25 m at most) the mesh reads near it
        assert v is not None and v >= kg / 2.0, name


def test_every_frames_record_states_the_lookups_accuracy():
    tsv = (EVIDENCE / "lookup_accuracy.tsv").read_text(encoding="utf-8")
    for bid, prefix in DENSE.items():
        acc = _frames(prefix)["accuracy"]
        assert set(acc) == {"all", "innermost"}
        assert bid in tsv


def test_the_driver_stages_a_frame_at_each_15_minute_dump_up_to_the_horizon():
    spec = {"every_s": 900.0, "until_s": 21600.0}
    assert DRV._frame_time(900.0, spec) == 900.0
    assert DRV._frame_time(1200.0, spec) is None
    assert DRV._frame_time(21600.0, spec) == 21600.0
    assert DRV._frame_time(22500.0, spec) is None
    assert DRV._frame_time(900.0, None) is None


def test_the_driver_doubles_the_spacing_past_the_cap_and_orders_the_grid():
    spec = {"spacing_km": 0.025, "margin_cells": 2, "max_points": 500000}
    x0, x1, y0, y1, sp, nx, ny = DRV.grid_spec((-30.0, 30.0, -30.0, 30.0), spec)
    assert nx * ny <= 500000 and sp > 0.025
    assert abs((x1 - x0) / sp + 1 - nx) < 1e-6
    text = "hdr\n====\n X Y Mean Variance\n" + "\n".join(
        f"{x} {y} {10 * x + y} 0" for x in range(3) for y in range(2)
    )
    # the file lists X outer and Y inner; the means are stored row by row, south first
    assert DRV.read_grid_means(text, 3, 2) == [0.0, 10.0, 20.0, 1.0, 11.0, 21.0]
    ovl = "#CONTOUR 1.0E-06\n!LINE\n1 2\n3 4\n#CONTOUR 1.0E-05\n!LINE\n0 0\n"
    assert DRV.overlay_box(ovl) == (1.0, 3.0, 2.0, 4.0)


def test_a_replay_computes_no_frame_and_draws_the_stored_ones():
    b = _assembled()
    assert _REFUSED == []
    cl = b.derived["cloud"]
    assert cl["frames_run"]["count"] == 24
    assert [f["minute"] for f in cl["frames"]][:2] == [15, 30]
    assert all(set(f) == {"minute", "tiers"} for f in cl["frames"])


# ── Part C: the page ─────────────────────────────────────────────────────────────────


def test_the_page_states_how_far_the_run_has_computed_and_at_what_setting():
    page = _page("csx-point-of-rocks-night")
    m = re.search(
        r'<output class="pl" id="frames-status" role="status" title="([^"]*)">'
        r"(.*?)</output>",
        page,
    )
    assert m, "no status line"
    assert m.group(2) == "Computed: 24 frames to H+6 h, at the 1.25 m vertical setting"
    assert "every 15 minutes" in m.group(1) and "the last after" in m.group(1)


@pytest.mark.parametrize("bid", sorted(DENSE))
def test_play_is_one_control_off_by_default_and_steps_the_frames(bid):
    page = _page(bid)
    assert page.count('id="time-play"') == 1
    assert re.search(r'id="time-play" aria-pressed="false"[^>]*>Play</button>', page)
    assert "Animate</button>" not in page
    t = re.search(
        r'<script type="application/json" id="map-config">(.*?)</script>', page, re.S
    )
    steps = json.loads(t.group(1))["time"]["steps"]
    assert all(s["minute"] % 15 == 0 for s in steps)


@pytest.mark.parametrize("bid", sorted(DENSE))
def test_the_mesh_is_beside_the_page_not_in_it(bid):
    # the page's script reads the key; no mesh is in the page's data
    assert '"codes_gz_b64"' not in _page(bid)
    pub = json.loads(_page(bid, F.PUBLISHED))
    assert pub["record"].startswith(DENSE[bid])
    assert len(pub["frames"]) == len(_frames(DENSE[bid])["frames"])


def test_no_map_page_names_a_tool_hazbrief_does_not_run():
    for d in sorted(BRIEFS.iterdir()):
        if not (d / "brief.html").exists():
            continue
        page = _page(d.name)
        for name in NOT_RUN:
            # a word, not letters inside an embedded image's base64
            hit = re.search(rf"(?<![A-Za-z0-9+/]){name}(?![A-Za-z0-9+/])", page)
            assert hit is None, (d.name, name)


def test_the_tevv_page_names_the_benchmarks_with_their_status():
    tevv = html.unescape(_page("csx-point-of-rocks-night", "tevv.html"))
    assert "Benchmarks and requirement" in tevv
    for name in NOT_RUN:
        assert name in tevv
    assert tevv.count("hazbrief's status: not yet evaluated") == 7
    # HB-199: the like-for-like rows on Jack Rabbit II Trial 7, BENCH-8 and BENCH-9;
    # restated by HB-212 (DN-030 section 2): their state is by statistical
    # significance, and every ratio's limits include 1; HB-213: in the Census
    # Bureau's words
    assert (
        tevv.count("hazbrief's status: not statistically significant at 95 percent")
        == 2
    )
    assert "hazbrief's status: below" not in tevv
    assert "hazbrief's status: statistically significant" not in tevv


@pytest.mark.parametrize("bid", sorted(DENSE))
def test_population_is_drawn_dissolved_and_counted_block_by_block(bid):
    lay = next(x for x in _map_data(bid)["layers"] if x["id"] == "modelled_population")
    page = _page(bid)
    feats = lay.get("features") or []
    # one shape per colour class, never one per block
    assert len(feats) <= len(load_config()["map"]["population_ramp"])
    assert all("Census block " not in f["properties"]["popup"] for f in feats)
    blocks = sum(
        int(
            re.search(r"Blocks in this class</th><td>(\d+)<", f["properties"]["popup"])[
                1
            ]
        )
        for f in feats
    )
    residents = sum(
        int(
            re.search(
                r"Residents, whole blocks \(2020 Census\)</th><td>([\d,]+)<",
                f["properties"]["popup"],
            )[1].replace(",", "")
        )
        for f in feats
    )
    assert blocks > 0 and residents > 0 and "block by block" in page


def test_population_counts_do_not_change_when_it_is_drawn_dissolved():
    b = _assembled()
    rows = [
        r
        for r in b.derived["modelled_population"]["rows"]
        if r["residents"] is not None
    ]
    lay = next(
        x
        for x in layers.build(b, load_config())["layers"]
        if x["id"] == "modelled_population"
    )
    pops = [f["properties"]["popup"] for f in lay["features"]]
    n = sum(int(re.search(r"Blocks in this class</th><td>(\d+)<", p)[1]) for p in pops)
    r = sum(
        int(
            re.search(r"Residents, whole blocks \(2020 Census\)</th><td>([\d,]+)<", p)[
                1
            ].replace(",", "")
        )
        for p in pops
    )
    assert n == len(rows)
    assert r == sum(int(x["residents"]) for x in rows)


def test_the_first_map_draws_blocks_on_major_roads_and_at_the_scene_only():
    b = _assembled()
    cfg = load_config()
    fm = cfg["map"]["first_map_blocks"]
    data = layers.build(b, cfg)
    drawn = 0
    for lid in ("roadblock_candidates", "modelled_cordons"):
        lay = next(x for x in data["layers"] if x["id"] == lid)
        for f in lay.get("features") or []:
            pop = f["properties"]["popup"]
            cls = re.search(r"Class \(MTFCC\)</th><td>(S\d+)<", pop)[1]
            scene = "initial isolation zone" in pop or "fire isolation" in pop
            assert cls in cfg["derive"]["roads"]["classes"] or scene, pop[:120]
            assert fm["staff_words"] in pop
            drawn += 1
    off = threat.off_map_blocks(b, cfg)
    held = sum(
        len((b.derived.get(n) or {}).get("candidates") or [])
        for n in ("roads", "modelled_cordons")
    )
    assert drawn + len(off) == held and len(off) > 0
    tl = threat.page_html(b, cfg)
    assert f"Candidate blocks not drawn on the first map ({len(off)})" in tl


def test_a_drawn_block_inside_the_aegl1_outline_says_so():
    b = _assembled()
    cfg = load_config()
    g = shape(b.derived["cloud"]["any_time"]["AEGL-1"])
    data = layers.build(b, cfg)
    lay = next(x for x in data["layers"] if x["id"] == "modelled_cordons")
    for f in lay.get("features") or []:
        inside = g.contains(shape(f["geometry"]))
        said = cfg["map"]["first_map_blocks"]["inside_aegl1_words"] in html.unescape(
            f["properties"]["popup"]
        )
        assert inside == said


def test_the_engine_sensors_keep_every_candidate_so_no_record_moves():
    # request A's name is the held one: the sensors are every candidate the data holds
    b = _assembled()
    assert b.derived["cloud"]["record_a"].startswith(DENSE["csx-point-of-rocks-night"])


def test_the_checklist_line_says_by_how_much_an_arrival_may_be_earlier():
    tsv = (EVIDENCE / "arrival_sign.tsv").read_text(encoding="utf-8").splitlines()
    allrow = next(r.split("\t") for r in tsv if r.startswith("all\tall\t"))
    assert allrow[8] == "720"
    # the stable line: at the top of the Timeline page (and in the checklist)
    assert "an arrival may be earlier than shown by up to 12 minutes" in html.unescape(
        _page("csx-point-of-rocks-night", "timeline.html")
    )


# ── Part A: the requirement in the graph ─────────────────────────────────────────────


def test_the_requirement_projection_has_a_minimum_an_objective_and_a_status_word():
    rows = [
        ln
        for ln in (EVIDENCE / "benchmark_rows.md")
        .read_text(encoding="utf-8")
        .splitlines()
        if ln.startswith("| BENCH-")
    ]
    # HB-199 added BENCH-8 and BENCH-9, the like-for-like rows on Jack Rabbit II Trial 7
    assert len(rows) == 10
    head = rows[0]
    assert "Minimum: equivalence" in head and "Objective: better" in head
    # HB-212: the states of scripts/benchmark_state.py and the minimum's (DN-030
    # section 2 items 1 and 4); "exceeds" and "equals", HB-199 section 5's count of
    # criteria, are withdrawn
    words = (
        "statistically significant at 95 percent, above",
        "statistically significant at 95 percent, below",
        "not statistically significant at 95 percent",
        "not statistically significant at 95 percent against HPAC or ALOHA"
        " (one trial, five arcs)",
        "not yet evaluated",
    )
    for r in rows:
        status = r.split(" | ")[3]
        assert status in words, r[:60]
    assert not any(" met" in r.split(" | ")[3] for r in rows)


def test_the_requirement_projection_equals_the_graph():
    exe = shutil.which("seldon")
    if exe is None:
        pytest.skip("the seldon command is not installed, so the graph cannot be read")
    run = subprocess.run(
        [sys.executable, str(EVIDENCE / "tools" / "benchmark_rows.py"), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if "ModuleNotFoundError" in run.stderr or "No such file" in run.stderr:
        pytest.skip(f"the graph cannot be read here: {run.stderr[-200:]}")
    assert run.returncode == 0, run.stdout + run.stderr
