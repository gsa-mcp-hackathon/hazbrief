"""HB-150 Part C: the smoke engine decided from what is held (operator decision 5 of
2026-11-09: the smoke layer ships only if an open engine builds and reproduces a
documented example from held material; otherwise smoke is future work).

- The outcome is one of two states, `built` or `future_use`, stated once in
  src/hazbrief/brief/vsmoke.yaml with the decision and the candidates tried.
- The candidates table (docs/evidence/hb150/smoke_candidates.tsv) records at most two
  attempts, each against the three tests, and the state follows from it.
- With `future_use`, each fire brief's smoke panel says so in the client's words and
  draws no band; the coupled disclosure paragraph says so (test_judge_facing_
  documents.py holds the paragraph).
- The fire fixtures' emission rate and heat release are the manual's worked example,
  each citing the held manual's page (Issue f7196297), with the page image as the
  receipt: the scanned page has no text layer to quote.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path

import pytest
import yaml

from hazbrief.brief import vsmoke_driver as V

REPO = Path(__file__).resolve().parents[1]
BRIEFS = REPO / "docs" / "briefs"
EVIDENCE = REPO / "docs" / "evidence" / "hb150"
FIRE_BRIEFS = ("un1203-fire-i83", "brush-fire-co-canal-point-of-rocks")
STATES = ("built", "future_use")
MANUAL = "usfs-lavdas-1996-vsmoke-users-manual"
#: The manual's worked example (Appendix III, PDF p. 121, printed p. 118), period 1:
#: EMTQPM 47.0 g/s and EMTQH 590.0 MW, read by eye from the page image.
EXAMPLE_PM_G_S = 47.0
EXAMPLE_HEAT_W = 590.0e6


def _engine() -> dict:
    return V.load_spec()["engine"]


def _candidates() -> list[dict]:
    with (EVIDENCE / "smoke_candidates.tsv").open(encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def _panel(sid: str) -> str:
    page = (BRIEFS / sid / "brief.html").read_text(encoding="utf-8")
    m = re.search(r"<h3>Modelled, smoke \(VSMOKE\)</h3>(.*?)(?=<h[23]|<details)", page)
    assert m, f"{sid}: no smoke panel"
    return m.group(1)


def _layers(sid: str) -> dict:
    page = (BRIEFS / sid / "brief.html").read_text(encoding="utf-8")
    m = re.search(r'id="map-data">(.*?)</script>', page, re.S)
    data = json.loads(m.group(1).replace("<\\/", "</"))
    return {lay["id"]: lay for lay in data["layers"] if lay["features"]}


def test_the_smoke_outcome_is_one_of_two_states():
    engine = _engine()
    assert engine["state"] in STATES
    assert "HB-150" in engine["decision"] and "7a4dd74a" in engine["decision"]


def test_at_most_two_candidates_were_tried_and_the_state_follows_from_them():
    rows = _candidates()
    tried = [r for r in rows if r["attempted"] == "yes"]
    assert 1 <= len(tried) <= 2
    for r in tried:
        for test in ("licence", "builds", "example"):
            assert r[test] in ("pass", "fail", "not reached"), (r["name"], test)
    passed = [
        r
        for r in tried
        if all(r[t] == "pass" for t in ("licence", "builds", "example"))
    ]
    assert (_engine()["state"] == "built") == bool(passed)


@pytest.mark.verifies("VR-064")
@pytest.mark.parametrize("sid", FIRE_BRIEFS)
def test_a_fire_brief_says_the_smoke_layer_is_a_future_use_and_draws_no_band(sid):
    if _engine()["state"] != "future_use":
        pytest.skip("the engine is built; the bands are drawn")
    vspec = V.load_spec()
    panel = _panel(sid)
    assert " ".join(vspec["refusals"]["engine_not_held"].split()) in panel
    assert "future use" in vspec["refusals"]["engine_not_held"]
    assert vspec["hints"]["engine_not_held"] in panel
    assert "smoke" not in _layers(sid)


def test_the_fire_figures_are_the_manuals_example_with_its_page():
    doc = yaml.safe_load((REPO / "fixtures" / "scenario_fires.yaml").read_text("utf-8"))
    for sid, block in doc["fires"].items():
        pm, heat = block["emission_rate_g_s"], block["heat_release_w"]
        assert pm["value"] == EXAMPLE_PM_G_S and heat["value"] == EXAMPLE_HEAT_W, sid
        for v in (pm, heat):
            assert v["source"].startswith(f"{MANUAL} p. 121, the manual's example"), sid
        assert "not this fire's" in block["note"], sid


def test_the_manual_page_image_is_the_receipt():
    """The scanned page has no text layer, so its rendered image is committed with its
    sha256; the image is of the held file's PDF page 121."""
    rec = json.loads((EVIDENCE / "vsmoke_manual_example.json").read_text("utf-8"))
    assert rec["doc_id"] == MANUAL and rec["pdf_page"] == 121
    img = EVIDENCE / rec["image"]
    assert hashlib.sha256(img.read_bytes()).hexdigest() == rec["image_sha256"]
    assert rec["read"]["EMTQPM_g_s"] == EXAMPLE_PM_G_S
    assert rec["read"]["EMTQH_MW"] * 1e6 == EXAMPLE_HEAT_W
