"""HB-48 (DN-013 section 5.2): the bare point gets its label. Every committed brief's
spill point renders from a DN-013 section 2 location record (`derivation:
caller_supplied`, `source: request`, `accuracy_m: null`), the popup carries the record's
label, and the record is written into the brief's evidence appendix beside the
request's other values."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from hazbrief.brief.orchestrator import load_config

REPO = Path(__file__).resolve().parents[1]
BRIEFS = REPO / "docs" / "briefs"
#: the briefs whose request gives a bare point; HB-49's located briefs (a milepost, a
#: crossing) carry a derived record instead (test_brief_union.py)
#: HB-129: a brief whose scenario does not run the footprint (the brush fire, which has
#: no load) asks no tool about its point, so it carries no location record
ALL = sorted(
    p.name
    for p in BRIEFS.iterdir()
    if (p / "brief.html").exists()
    and "location"
    in (s := json.loads((p / "scenario.json").read_text(encoding="utf-8")))["incident"]
    and "protective_action_footprint" not in (s.get("not_run") or {})
)
LABEL = "no accuracy stated; the footprint is drawn as if this point were exact"


def _record(page: str) -> dict | None:
    m = re.search(r'id="location-record">(.*?)</script>', page, re.S)
    return json.loads(m.group(1).replace("<\\/", "</")) if m else None


def _spill_popup(page: str) -> str:
    m = re.search(r'id="map-data">(.*?)</script>', page, re.S)
    data = json.loads(m.group(1).replace("<\\/", "</"))
    (spill,) = [lay for lay in data["layers"] if lay["id"] == "spill"]
    (feat,) = spill["features"]
    return feat["properties"]["popup"]


def test_twenty_one_briefs_are_committed():
    # HB-120 adds three demonstrations, each located by a bare point; HB-129 the
    # burning tank truck (the brush fire runs no footprint, so it is not one of them);
    # HB-175 the ammonia cargo tank (22; the name is kept)
    assert len(ALL) == 22


def test_the_label_is_the_configured_one():
    """The label text lives in orchestrator.yaml, not in code (standards s2)."""
    assert load_config()["location"]["caller_supplied"]["label"] == LABEL


@pytest.mark.parametrize("sid", ALL)
def test_the_bare_point_renders_from_its_location_record(sid):
    page = (BRIEFS / sid / "brief.html").read_text(encoding="utf-8")
    scenario = json.loads((BRIEFS / sid / "scenario.json").read_text(encoding="utf-8"))
    loc = scenario["incident"]["location"]
    rec = _record(page)
    assert rec is not None, "the brief carries no location record"
    assert rec["derivation"] == "caller_supplied"
    assert rec["source"] == "request"
    assert rec["accuracy_m"] is None
    assert rec["basis"] == "none"
    assert rec["collapsed_by"] is None
    assert rec["label"] == LABEL
    assert rec["shape"] == {
        "type": "Point",
        "coordinates": [loc["longitude"], loc["latitude"]],
    }
    assert rec["as_of"]
    popup = _spill_popup(page)
    assert LABEL in popup
    assert "as if it were exact" not in popup, "the HB-45 text is replaced"


@pytest.mark.parametrize("sid", ALL)
def test_the_record_is_in_the_evidence_appendix_beside_the_request(sid):
    text = (BRIEFS / sid / "appendix.txt").read_text(encoding="utf-8")
    rows = [
        ln for ln in text.splitlines() if ln.lstrip().startswith("request (location)")
    ]
    assert len(rows) == 1
    assert LABEL in rows[0]
    html = (BRIEFS / sid / "appendix.html").read_text(encoding="utf-8")
    assert "request (location)" in html and LABEL in html
