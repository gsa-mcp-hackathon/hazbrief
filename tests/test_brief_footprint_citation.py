"""HB-99 step 1 (Issue e4074961): a brief cites its own scenario's footprint record.

The three tools that read the footprint (`orchestrator.yaml` `needs`) are handed it as
their input, and their record's `used` names the footprint entity they read. Two
scenarios whose footprints have the same shape hand those tools identical parameters,
so a held call keyed by `(tool, params)` alone was one record shared by both, and the
second scenario's brief printed the first scenario's footprint in its appendix. The
store now keys a held call by `(tool, params, used)` (`store.records_for`).

The assertions read the assembled `Brief` and the appendix text it writes, not bytes
against a committed copy (review L7-7: a byte-compare oracle cannot see this class of
defect, because the committed copy carried it).
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

from hazbrief.brief import cli, location
from hazbrief.brief.orchestrator import assemble, load_config
from hazbrief.evidence import labels as L
from hazbrief.evidence import store as S

REPO = Path(__file__).resolve().parents[1]
NOW = S.parse_time(L.config()["fixture_now"])
BRIEFS = sorted(
    p.parent.name for p in (REPO / "docs" / "briefs").glob("*/scenario.json")
)
READERS = sorted(
    name
    for name, spec in load_config()["channels"].items()
    if spec.get("needs") == location.FOOTPRINT
)
#: the asked() phrase of a footprint record, as the appendix prints it
FOOTPRINT_ROW = re.compile(r"protective action footprint(?: \([^)]*\))?")


def _brief(sid: str):
    scenario = cli.load_scenario(REPO / "docs" / "briefs" / sid / "scenario.json")
    return asyncio.run(assemble(scenario, now=NOW, replay_stores=cli.replay_stores()))


def test_the_footprint_readers_are_the_three():
    """The test below is about these three channels; a fourth reader joins it."""
    assert READERS == [
        "facilities_in_footprint",
        "population_at_risk",
        "receiving_hospitals",
    ]


@pytest.mark.parametrize("sid", BRIEFS)
def test_every_reader_record_a_brief_cites_used_its_own_footprint(sid, tmp_path):
    brief = _brief(sid)
    fp = brief.channels[location.FOOTPRINT]
    if fp["state"] != "ok":
        # no footprint, no reader call: each reader says why and cites no record
        for name in READERS:
            assert brief.channels[name].get("record") is None, name
        return
    own = set(fp.get("samples") or [fp["sha"]])
    checked = 0
    for name in READERS:
        ch = brief.channels[name]
        if ch["state"] == "not_run":
            continue
        rec = ch.get("record")
        assert rec is not None, f"{name}: {ch['state']} {ch.get('reason')}"
        assert own <= set(rec["used"]), (
            f"{name}'s record used {sorted(u[:12] for u in rec['used'])}, "
            f"not this scenario's footprint {sorted(u[:12] for u in own)}"
        )
        checked += 1
    assert checked, "no reader record was checked"

    # the appendix text: every footprint row it prints is this scenario's own
    own_rows = {L.asked(fp["record"])} | {L.asked(r) for r in brief.samples}
    cli.write_outputs(brief, tmp_path)
    text = (tmp_path / "appendix.txt").read_text(encoding="utf-8")
    printed = set(FOOTPRINT_ROW.findall(text))
    assert printed, "the appendix prints no footprint row"
    assert printed <= own_rows, sorted(printed - own_rows)


@pytest.mark.parametrize("sid", BRIEFS)
def test_every_record_row_of_the_appendix_is_the_request_this_brief_made(sid, tmp_path):
    """HB-99 step 3's finding: a body many scenarios' calls returned (the UN1017 guide,
    one entity with a record per scenario) printed the newest call's request, another
    scenario's location, as this brief's. Each top-level row of the appendix text is
    the request of a record this brief read. (A subset, not equality: the appendix
    prints one row per entity, and two channels that answered the same error, as the
    unresolved-material scenarios' assess and guidance calls do, share one.)"""
    brief = _brief(sid)
    own = {L.asked(r) for r in brief.records()}
    cli.write_outputs(brief, tmp_path)
    text = (tmp_path / "appendix.txt").read_text(encoding="utf-8")
    table = text.split("\nDerived:", 1)[0].splitlines()[2:]
    asked = {re.split(r" {2,}", ln)[1] for ln in table if ln and not ln[0].isspace()}
    if not own:
        # HB-129: a brief that calls no tool (the brush fire: every channel not_run)
        # reads no record, and its appendix prints none
        assert not asked, sorted(asked)
        return
    assert asked, "the appendix prints no record row"
    assert asked <= own, sorted(asked - own)
