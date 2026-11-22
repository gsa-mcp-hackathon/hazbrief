"""HB-41 steps 4, 6 and 7: the orchestrator's configuration, the CLI, and the committed
briefs, which a fresh replay build reproduces byte for byte with `now` held fixed (the
HB-38 pattern). HB-45 step 8 extends the golden master to one brief per fixture scenario
that replays end to end (`scripts/build_scenario_briefs.py`)."""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

import pytest

from hazbrief.brief import cli
from hazbrief.brief.orchestrator import RENDER_ORDER, assemble, load_config
from hazbrief.evidence import catalog
from hazbrief.evidence import labels as L
from hazbrief.evidence import store as S

REPO = Path(__file__).resolve().parents[1]
BRIEF = REPO / "docs" / "briefs" / "csx-point-of-rocks-day"
NOW = S.parse_time(L.config()["fixture_now"])
STORES = [S.repo_path("seed_calls_store_dir"), S.repo_path("seed_store_dir")]
BRIEFS = sorted(
    p.parent.name for p in (REPO / "docs" / "briefs").glob("*/scenario.json")
)


def _build(scenario: Path, out: Path) -> int:
    return cli.main(
        [
            str(scenario),
            "--out",
            str(out),
            "--replay",
            "--now",
            L.config()["fixture_now"],
            "--no-google",
        ]
    )


@pytest.mark.parametrize("sid", BRIEFS)
def test_each_committed_brief_equals_a_fresh_replay_build(sid, tmp_path):
    """Every committed brief, the first (HB-41) and one per replayable scenario (HB-45),
    rebuilds byte for byte from the two seeds."""
    src = REPO / "docs" / "briefs" / sid
    _build(src / "scenario.json", tmp_path)
    for name in ("brief.html", "appendix.html", "appendix.txt"):
        assert (src / name).read_bytes() == (tmp_path / name).read_bytes(), name


def test_every_replayable_scenario_has_a_committed_brief():
    """HB-45 step 8: each fixture scenario with no `not_run` cell has its brief."""
    import yaml

    doc = yaml.safe_load((REPO / "fixtures" / "scenarios.yaml").read_text())
    want = [
        s["id"]
        for s in doc["scenarios"]
        if all(c["status"] != "not_run" for c in s["tools"].values())
    ]
    # HB-49: the scenarios located by a milepost or a crossing have theirs too
    located = yaml.safe_load(
        (REPO / "fixtures" / "location_scenarios.yaml").read_text()
    )["scenarios"]
    # HB-129: the fire scenarios the server takes no call for (the brush fire)
    fires = (
        yaml.safe_load((REPO / "fixtures" / "scenario_fires.yaml").read_text())[
            "scenarios"
        ]
        or []
    )
    assert BRIEFS == sorted(want + [s["id"] for s in located + fires])


def test_every_channel_reads_the_catalogs_rows_for_its_tool():
    for tool, ch in load_config()["channels"].items():
        assert set(ch["sources"]) == {r["id"] for r in catalog.rows_for_tool(tool)}, (
            tool
        )


def test_the_brief_opens_from_a_file_url():
    page = (BRIEF / "brief.html").read_text(encoding="utf-8")
    for ref in re.findall(r'(?:src|href)="([^"]+)"', page):
        # HB-161: the TEVV page beside the brief, at its top or at a section
        assert (
            ref.startswith(("https://", "#", "data:"))
            or ref in ("appendix.html", "appendix.txt", "tevv.html", "timeline.html")
            or re.fullmatch(r"tevv\.html#t\d+", ref)
            # HB-171: the Timeline page beside the brief, at a row
            or re.fullmatch(r"timeline\.html#r\d+", ref)
        ), ref
    assert re.findall(r'<section[^>]* id="section-([a-z0-9]+)"', page) == list(
        RENDER_ORDER
    )


def test_the_committed_brief_carries_its_labels_and_the_requesters_wind():
    page = (BRIEF / "brief.html").read_text(encoding="utf-8")
    # every section prints its sources again: HB-140R recorded the population tool's
    # exchanges for the footprint HB-133 oriented on this brief's one wind record. It is
    # the only brief this file pins; the other 13 reoriented briefs keep their labelled
    # gaps until the fixture rewrite (L0 item E, Issue 8b992307)
    assert page.count('<p class="sources">') == len(RENDER_ORDER)
    assert "wind as given by the requester" in page
    # the CMS hospital file; restated by HB-158 item 5: its age and limit, not "stale"
    assert re.search(
        r'<span class="stale">\d+ days old, past its \d+-day limit</span>', page
    )


def test_a_scenario_snapshot_resolves_through_the_manifest():
    snap = REPO / "fixtures" / "scenarios" / "csx-point-of-rocks-day.json"
    s = cli.load_scenario(snap)
    assert s["id"] == "csx-point-of-rocks-day" and "incident" in s


def test_a_replay_with_no_record_degrades_and_says_so(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    s = cli.load_scenario(BRIEF / "scenario.json")
    brief = asyncio.run(assemble(s, replay_stores=[empty], now=NOW))
    assert brief.sections["map"]["state"] == "degraded"
    assert "no record in the store" in brief.sections["map"]["reason"]
    assert brief.sections["population"]["state"] == "degraded"
    assert (
        "needs the protective action footprint"
        in brief.sections["population"]["reason"]
    )


def test_the_console_script_routes_brief_and_leaves_the_server(monkeypatch):
    from hazbrief import command

    called = {}
    monkeypatch.setattr(sys, "argv", ["hazbrief", "brief", "x.json", "--out", "y"])
    monkeypatch.setattr(
        cli, "main", lambda argv: called.setdefault("brief", argv) and 0
    )
    with pytest.raises(SystemExit):
        command.main()
    assert called["brief"] == ["x.json", "--out", "y"]
    import hazbrief.app

    monkeypatch.setattr(sys, "argv", ["hazbrief"])
    monkeypatch.setattr(hazbrief.app, "main", lambda: called.setdefault("server", True))
    command.main()
    assert called["server"] is True


@pytest.mark.verifies("O-D4")
def test_no_author_writes_only_the_servers_text():
    """DN-011 D4, DN-009 C4: the one author writes no sentence of its own. The ICS 201
    is the Markdown it was handed; every guidance line is a line the guidance tool
    returned, with its locator."""
    from hazbrief.brief.author import NoAuthor

    st = S.repo_path("seed_calls_store_dir")
    recs = {r["activity"]["name"]: r for r in S.all_records(st)}
    mrg = S.read_entity(st, recs["material_response_guidance"]["entity"]["sha256"])
    author = NoAuthor()
    assert author.write("ics201", {}, ics201_markdown="# form\n") == "# form\n"
    md = author.write("guidance", {"material_response_guidance": mrg})
    given = {(it["text"], it.get("locator")) for key in mrg["order"] for it in mrg[key]}
    for line in md.splitlines():
        if line.startswith("- "):
            text, _, loc = line[2:].rpartition(" [")
            assert (text, loc.rstrip("]")) in given, line
    assert author.write("population", {}) is None
