"""HB-215 Part B: the Sources and MCP servers view lists every source the brief called,
one row each, grouped under plain headings, each with a mark whose shape and word say
its state (answered, answered from the recording, not called, failed), what it gave the
brief in at most six words, and its as-of; read from the brief's own records, no call.

Item 10's tests: every source in the brief's evidence appears once; no row is colour
only; the view makes no network call. The display rules are held prior art
(`docs/evidence/hb215/display_prior_art.md`: NUREG-0700 Rev. 4 1.3.8-10 and 3.2.2-3, FAA
HF-STD-001B 5.6.6.2.1.5, MIL-STD-1472H 5.1.3.1.16).
"""

from __future__ import annotations

import html
import re
import socket
from functools import cache
from pathlib import Path
from types import SimpleNamespace

import pytest

from hazbrief.brief import cli, data_sources, render, web
from hazbrief.brief.orchestrator import load_config
from hazbrief.evidence import labels as L
from hazbrief.evidence import store as S

REPO = Path(__file__).resolve().parents[1]
BRIEFS = REPO / "docs" / "briefs"
CFG = load_config()
SPEC = CFG["data_sources"]["board"]
#: item 8: what a source gave the brief, in at most six words
MAX_GIVES_WORDS = 6
#: the four states the operator named (item 8), and a live run's waiting
FOUR = ("answered", "recorded", "not_called", "failed")


def _ids() -> list[str]:
    return sorted(p.name for p in BRIEFS.iterdir() if (p / "scenario.json").is_file())


@cache
def _replayed(sid: str):
    scen = cli.load_scenario(BRIEFS / sid / "scenario.json")
    return cli.replay_brief(
        scen, S.parse_time(L.config()["fixture_now"]), lambda e: None
    )


def _annex(page: str) -> str:
    return page[page.index('id="data-sources"') :]


def _board(page: str) -> str:
    a = _annex(page)
    return a[
        a.index('<div class="board">') : a.index(
            "</div>", a.index('<div class="board">')
        )
    ]


# ---- the config


def test_the_four_states_each_have_their_own_shape_or_word_and_a_word():
    """No state is told by colour alone (NUREG-0700 1.3.8-10): each has a glyph and a
    word, and no two states share both."""
    st = SPEC["statuses"]
    assert set(FOUR) <= set(st)
    pairs = [(st[k]["glyph"], st[k]["words"]) for k in st]
    assert len(set(pairs)) == len(pairs)
    assert len({st[k]["words"] for k in st}) == len(st)
    for k in st:
        assert st[k]["glyph"].strip() and st[k]["words"].strip(), k
    assert st["recorded"]["words"] == "answered from the recording"
    assert st["not_called"]["words"] == "not called"


def test_every_source_says_what_it_gave_in_at_most_six_words_and_has_a_heading():
    groups = [g["id"] for g in SPEC["groups"]]
    assert [g["title"] for g in SPEC["groups"]][:3] == [
        "Public federal data",
        "State and local data",
        "Models",
    ]
    assert "The basemap" in [g["title"] for g in SPEC["groups"]]
    ids = [s["id"] for s in SPEC["sources"]]
    assert len(ids) == len(set(ids))
    for s in SPEC["sources"]:
        assert s["group"] in groups, s["id"]
        assert 1 <= len(s["gives"].split()) <= MAX_GIVES_WORDS, s["id"]
    # ADDENDUM-03 item 5: no camera source; the state and local heading lists only
    # what a brief called
    assert not any("camera" in s["id"] or "chart" in s["id"] for s in SPEC["sources"])


# ---- the committed briefs (every one, read from its page)


@pytest.mark.verifies("VR-165")
@pytest.mark.parametrize("sid", _ids())
def test_every_source_in_the_briefs_evidence_appears_once(sid):
    """Each source the per-tool table names (the records' labels) has exactly one
    board row; no row repeats."""
    page = (BRIEFS / sid / "brief.html").read_text(encoding="utf-8")
    board = _board(page)
    rows = re.findall(r'<tr data-source="([a-z_0-9]+)"', board)
    assert len(rows) == len(set(rows)), sid
    idx = data_sources._index(SPEC)
    annex = _annex(page)
    names = set()
    for srcs in re.findall(r'<span class="srcs">(.*?)</span>', annex):
        names |= {n for n in html.unescape(srcs).split("; ") if n}
    for n in names:
        assert idx[("labels", n)] in rows, (sid, n)


@pytest.mark.verifies("VR-165")
@pytest.mark.parametrize("sid", _ids())
def test_no_row_is_colour_only_and_the_page_links_to_the_view(sid):
    page = (BRIEFS / sid / "brief.html").read_text(encoding="utf-8")
    board = _board(page)
    marks = re.findall(
        r'<span (hidden )?class="bst bst-([a-z_]+)" data-status="([a-z_]+)">'
        r'<span class="mk" aria-hidden="true">(.)</span> ([^<]+)</span>',
        board,
    )
    shown = [m for m in marks if not m[0]]
    assert len(shown) == len(re.findall(r"<tr data-source=", board)), sid
    for _, cls, status, glyph, words in marks:
        assert cls == status
        assert glyph == SPEC["statuses"][status]["glyph"]
        assert words == SPEC["statuses"][status]["words"]
    # one control at the page's top opens the view
    link = re.search(r'<a id="sources-link" href="#data-sources">([^<]+)</a>', page)
    assert link and page.index('id="sources-link"') < page.index('id="map"'), sid
    # its words are the board's counts, the basemap rows (the browser's) left out
    counts: dict[str, int] = {}
    for status in re.findall(
        r'<tr data-source="[a-z_0-9]+" data-status="([a-z_]+)">', board
    ):
        counts[status] = counts.get(status, 0) + 1
    said = ", ".join(
        f"{counts[k]} {SPEC['statuses'][k]['words']}"
        for k in SPEC["precedence"]
        if counts.get(k)
    )
    assert html.unescape(link.group(1)) == SPEC["link"].format(counts=said), sid


def test_the_basemap_rows_are_the_browsers_and_print_their_three_marks():
    page = (BRIEFS / "csx-point-of-rocks-day" / "brief.html").read_text(
        encoding="utf-8"
    )
    board = _board(page)
    for i, t in enumerate(CFG["map"]["fallback_tiles"]):
        row = re.search(
            rf'<tr data-source="tile_{i}" data-status="not_called" data-browser="1">'
            r"(.*?)</tr>",
            board,
        )
        assert row, t["name"]
        assert html.escape(t["name"]) in row.group(1)
        assert row.group(1).count('class="bst ') == 3
        assert row.group(1).count("<span hidden ") == 2
    # the map script marks them as tiles load or fail (no words of its own)
    assert "baseMark('tile_' + i, 'answered')" in render.MAP_JS
    assert "baseMark('tile_' + first, 'failed')" in render.MAP_JS
    assert "baseMark('google', 'answered')" in render.MAP_JS


# ---- read from the records, no call


def test_a_replayed_brief_s_board_names_its_derivations_and_engines():
    brief = _replayed("csx-point-of-rocks-day")
    rows = {r["id"]: r for r in data_sources.board(brief, CFG)}
    assert rows["nws"]["status"] == "answered"
    assert rows["scichem"]["status"] == "answered"
    # radar is not held in a replay: no call was made
    assert rows["nowcoast"]["status"] == "not_called"
    groups = [r["group"] for r in rows.values()]
    assert groups == sorted(groups, key=[g["id"] for g in SPEC["groups"]].index)


def test_a_milepost_brief_lists_its_state_source():
    brief = _replayed("i81-md-pa-line-milepost")
    rows = {r["id"]: r for r in data_sources.board(brief, CFG)}
    assert rows["penndot"]["group"] == "state_local"
    assert rows["penndot"]["status"] == "answered"


@pytest.mark.verifies("VR-165")
def test_the_view_makes_no_network_call(monkeypatch):
    brief = _replayed("csx-point-of-rocks-day")

    def refuse(*a, **k):
        raise AssertionError("a network call was attempted")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    got = data_sources.table_html(data_sources.rows(brief, CFG), CFG, brief)
    assert '<div class="board">' in got
    # after the MCP server, before the per-tool table (VR-165's order kept)
    assert (
        got.index('<table class="mcp-servers">')
        < got.index('<div class="board">')
        < got.index('<table class="data-sources">')
    )


def _stub(derived=None, location=None):
    return SimpleNamespace(
        channels={},
        sections={},
        derived=derived or {},
        location=location,
        time_zone="UTC",
        now=None,
        google_key="",
    )


def test_a_derivation_s_reason_reads_as_not_called_or_failed():
    cfg = CFG
    unrec = _stub(
        {
            "forecast": {
                "rows": [],
                "reason": "its upstream answer is not recorded",
                "sources": [],
            }
        }
    )
    failed = _stub(
        {
            "forecast": {
                "rows": [],
                "reason": "Upstream service returned status 503.",
                "sources": [],
            }
        }
    )
    live = _stub(
        {
            "forecast": {
                "rows": [],
                "sources": [{"api": "nws", "retrieved": "2026-11-20T12:00:00Z"}],
            }
        }
    )

    def nws(b):
        return {r["id"]: r for r in data_sources.board(b, cfg, [])}["nws"]["status"]

    assert nws(unrec) == "not_called"
    assert nws(failed) == "failed"
    assert nws(live) == "answered"


def test_an_unknown_source_is_refused_not_dropped():
    b = _stub({"forecast": {"sources": [{"api": "nowhere", "retrieved": None}]}})
    with pytest.raises((data_sources.UnmappedSource, KeyError)):
        data_sources.board(b, CFG, [])


def test_the_shell_relabels_a_replays_answered_and_carries_the_words():
    """Item 9: a recorded run shows what answered when it was recorded; a served
    replay's shell says "answered from the recording" (not on the basemap rows, which
    the browser loads now). A live run's tab is fetched again as calls return."""
    js = (
        web.SHELL_JS
        if hasattr(web, "SHELL_JS")
        else (REPO / "src/hazbrief/brief/static/shell.js").read_text(encoding="utf-8")
    )
    assert 'tr:not([data-browser]) .bst[data-status="answered"]' in js
    assert "cfg.board_statuses.recorded" in js
    assert "window.hbBaseApply(root)" in js
    src = (REPO / "src/hazbrief/brief/web.py").read_text(encoding="utf-8")
    assert '"board_statuses": cfg["data_sources"]["board"]["statuses"]' in src
