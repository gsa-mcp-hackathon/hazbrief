"""HB-222 Part A: Animate, the slider and the step buttons never switch the roads image
on (the operator, 2026-11-23 12:33 EST). Part B of the task (the modelled population
layer's block count) is withdrawn by ADDENDUM 02; nothing of it is tested here.

The browser tests serve the committed csx day page (docs/briefs/, rebuilt by replay) in
headless Chrome through the suite's one-Chrome lock, two ways:

- with a basemap: the page's tile URLs are pointed at a tile the test's own server
  answers, so tiles load and the map script never switches the roads image on;
- with no basemap: every host but the test's server is unresolvable, the tiles fail,
  and the map script switches the roads image on by itself (`render.MAP_JS`, the tile
  check); Animate must leave it on, so the cloud still plays over something.
"""

from __future__ import annotations

import functools
import http.server
import json
import os
import re
import shutil
import struct
import tempfile
import threading
import zlib
from pathlib import Path

import pytest

from hazbrief.brief import cli, render
from hazbrief.brief.orchestrator import load_config
from hazbrief.evidence import labels as L
from hazbrief.evidence import store as S
from tests.one_chrome import run_chrome

REPO = Path(__file__).resolve().parents[1]
BRIEFS = REPO / "docs" / "briefs"
CFG = load_config()
TC = CFG["web"]["time_control"]
DAY = "csx-point-of-rocks-day"
ROADS = "roads"
MAP_CONFIG = re.compile(r'(<script[^>]*id="map-config"[^>]*>)(.*?)(</script>)', re.S)


def _png() -> bytes:
    """A 1x1 opaque PNG: the tile the test's server answers for every tile URL."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xee\xee\xee")
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", idat)
        + chunk(b"IEND", b"")
    )


DRIVE = """
<script>
(function () {
  var out = {}, waited = 0;
  function on() {
    var api = window.hbMapApi, m = api.map;
    return Object.keys(api.objs)
      .filter(function (id) { return m.hasLayer(api.objs[id]); })
      .sort();
  }
  function box() {
    var b = document.querySelector('#layer-list input[data-layer="roads"]');
    return b ? b.checked : null;
  }
  function snap(label) {
    out[label] = {on: on(), roads_box: box(), view: window.hbView,
                  note: document.getElementById('map-note').hidden ? null :
                    document.getElementById('map-note').textContent};
  }
  function step(label, fn) { fn(); snap(label); }
  var t = setInterval(function () {
    var m = document.getElementById('map');
    if (!m || !m.dataset.drawn || !m.dataset.timeStep || !window.hbMapApi) { return; }
    // with no basemap, wait for the tile check to switch the roads image on (or give
    // up after 10 s and let the assertions say so)
    waited += 100;
    if (NO_BASE && on().indexOf('roads') < 0 && waited < 10000) { return; }
    clearInterval(t);
    snap('open');
    var play = document.getElementById('time-play');
    play.click();
    snap('play0');
    setTimeout(function () { snap('play1'); }, PLAY + 200);
    setTimeout(function () { snap('play2'); }, 2 * PLAY + 200);
    setTimeout(function () {
      play.click();
      snap('stopped');
      // the step buttons and the slider while stopped
      var b = document.querySelector('#time-control button[data-step="1"]');
      step('step_button', function () { b.click(); });
      var r = document.getElementById('time-step');
      step('slider', function () {
        r.value = '2'; r.dispatchEvent(new Event('input'));
      });
      // Play then Stop restores the reader's layers
      play.click(); play.click();
      snap('restored');
      document.body.dataset.hb222 = JSON.stringify(out);
    }, 2 * PLAY + 600);
  }, 100);
})();
</script>
"""


def _chrome() -> str | None:
    """Chrome or Chromium: `HAZBRIEF_CHROME`, then the usual places. Its own copy, so
    this test imports no other test module and ships in the public tree."""
    for c in (
        os.environ.get("HAZBRIEF_CHROME"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        shutil.which("google-chrome"),
        shutil.which("chromium"),
    ):
        if c and Path(c).exists():
            return c
    return None


@functools.cache
def _brief(sid: str):
    scenario = cli.load_scenario(BRIEFS / sid / "scenario.json")
    return cli.replay_brief(scenario, S.parse_time(L.config()["fixture_now"]))


@functools.cache
def _driven(sid: str, basemap: bool) -> dict:
    """Serve the committed page, drive it, return the snapshots."""
    page = (BRIEFS / sid / "brief.html").read_text(encoding="utf-8")
    t = render._time_config(_brief(sid), CFG)
    drive = DRIVE.replace("PLAY", str(t["play_ms"])).replace(
        "NO_BASE", "false" if basemap else "true"
    )
    tile = _png()
    with tempfile.TemporaryDirectory(prefix=f"hb222_{sid}_") as d:
        root = Path(d) / "site"
        root.mkdir()

        class Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *a, **k):
                super().__init__(*a, directory=str(root), **k)

            def log_message(self, *a, **k):
                return None

            def do_GET(self):
                if self.path.startswith("/tile/"):
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(tile)))
                    self.end_headers()
                    self.wfile.write(tile)
                    return
                super().do_GET()

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        port = srv.server_address[1]
        if basemap:
            m = MAP_CONFIG.search(page)
            assert m, "the page has no map-config"
            cfg = json.loads(m.group(2))
            for i, tl in enumerate(cfg["tiles"]):
                tl["url"] = f"http://127.0.0.1:{port}/tile/{i}/{{z}}/{{x}}/{{y}}.png"
            page = page[: m.start(2)] + json.dumps(cfg) + page[m.end(2) :]
        (root / "brief.html").write_text(
            page.replace("</body>", drive + "</body>"), encoding="utf-8"
        )
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        try:
            dom = run_chrome(
                [
                    _chrome(),
                    "--headless=new",
                    "--disable-gpu",
                    f"--user-data-dir={Path(d) / 'profile'}",
                    "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
                    "--window-size=1440,900",
                    "--virtual-time-budget=30000",
                    "--dump-dom",
                    f"http://127.0.0.1:{port}/brief.html",
                ],
                capture_output=True,
                text=True,
                timeout=240,
                check=True,
            ).stdout
        finally:
            srv.shutdown()
    m = re.search(r'data-hb222="([^"]+)"', dom)
    assert m, "the page wrote no data-hb222"
    return json.loads(m.group(1).replace("&quot;", '"').replace("&amp;", "&"))


def _needs_chrome():
    if _chrome() is None:
        pytest.skip("no Chrome or Chromium (set HAZBRIEF_CHROME to run this check)")


MOVED = ("play0", "play1", "play2", "step_button", "slider")


def test_animate_keeps_no_roads_and_leaves_them_as_the_reader_had_them():
    """Item 1: the roads image is not in the set Animate forces on; it is in the set
    Animate leaves alone, and the page's time config carries both."""
    assert ROADS not in TC["animate_keep"]
    assert TC["animate_leave"] == [ROADS]
    assert not set(TC["animate_keep"]) & set(TC["animate_leave"])
    t = render._time_config(_brief(DAY), CFG)
    assert t["leave"] == [ROADS] and ROADS not in t["keep"]


@pytest.mark.load_sensitive
@pytest.mark.xdist_group("chrome")
def test_with_a_basemap_animate_never_draws_the_roads_image_and_stop_restores():
    """Item 3: a served brief with a basemap, roads off; Animate, the step buttons and
    the slider never draw the roads image; stopping restores the reader's layers."""
    _needs_chrome()
    a = _driven(DAY, basemap=True)
    assert a["open"]["note"] is None, a["open"]["note"]
    assert ROADS not in a["open"]["on"] and a["open"]["roads_box"] is False
    for k in MOVED:
        assert a[k]["view"] == "time", (k, a[k]["view"])
        assert ROADS not in a[k]["on"], k
        assert a[k]["roads_box"] is False, k
    assert a["stopped"]["on"] == a["open"]["on"]
    assert a["restored"]["on"] == a["open"]["on"]
    assert a["stopped"]["view"] == a["restored"]["view"] == "path"


@pytest.mark.load_sensitive
@pytest.mark.xdist_group("chrome")
def test_with_no_basemap_the_page_shows_the_roads_image_and_animate_keeps_it():
    """Item 2: a page whose tiles do not load switches the roads image on by itself (the
    map script's tile check), and Animate, the step buttons and the slider leave it on,
    so the cloud plays over the roads image, not a blank map."""
    _needs_chrome()
    a = _driven(DAY, basemap=False)
    assert ROADS in a["open"]["on"], a["open"]
    assert a["open"]["note"] and "roads image shown" in a["open"]["note"]
    for k in MOVED:
        assert a[k]["view"] == "time", (k, a[k]["view"])
        assert ROADS in a[k]["on"], k
    assert a["stopped"]["on"] == a["open"]["on"]
    assert a["restored"]["on"] == a["open"]["on"]
