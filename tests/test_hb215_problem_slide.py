"""HB-215 Part C: the problem slide, first after the title, from held records only.

Item 12: releases per year and the damage in dollars, each with its source and years,
from HB-127's base rates and HB-136R's incident data. Item 13: a U.S. map, one mark per
place, its area in proportion to the quantity shown (reported damage), one colour, a
scale key, the source and years under it. Item 14: at most 30 words besides the numbers.
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
import socket
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
# the deck's trace of every slide, this one included, is the deck's own test (its
# builder is held privately, so this test does not import it)
import build_problem_map as P  # noqa: E402

DECK = yaml.safe_load((REPO / "docs/submission/deck.yaml").read_text(encoding="utf-8"))
CFG = P.load_config()
OUT = CFG["outputs"]
#: item 14's own limit
MAX_WORDS = 30


def _slide() -> dict:
    return next(s for s in DECK["slides"] if s["id"] == "problem-scale")


def _record() -> dict:
    return json.loads((REPO / OUT["json"]).read_text(encoding="utf-8"))


def test_the_problem_slide_is_first_after_the_title():
    ids = [s["id"] for s in DECK["slides"]]
    assert ids[0] == "title"
    assert ids[1] == "problem-scale"
    assert _slide()["part"] == "problem"


def test_the_slide_has_at_most_thirty_words_besides_the_numbers():
    s = _slide()
    text = [s["title"]]
    for item in s["items"]:
        if "label" in item:
            text += [item["label"], item["value"]]
        elif "quote" in item:
            text.append(item["quote"])
    words = [
        w
        for w in re.findall(r"[A-Za-z][A-Za-z'-]*", " ".join(text))
        if not re.fullmatch(r"\d[\d,.]*", w)
    ]
    assert len(words) <= MAX_WORDS, (len(words), words)


def test_the_slides_numbers_are_the_records_and_the_record_is_read_from_held_files():
    rec = _record()
    rail, ph = rec["rail"], rec["phmsa_all_modes"]
    values = " ".join(i.get("value", "") for i in _slide()["items"])
    assert f"{ph['value']:,}" in values
    assert str(rail["released_incidents"]) in values
    assert str(rail["per_year_mean"]) in values
    assert f"${rail['damage_million_usd']} million" in values
    assert f"${rail['damage_million_usd_per_year_mean']} million a year" in values
    # the PHMSA row is HB-127's, held as a number with its document and page
    rows = list(
        csv.DictReader(
            io.StringIO((REPO / CFG["inputs"]["base_rates"]).read_text()),
            delimiter="\t",
        )
    )
    held = [
        r for r in rows if r["measure"] == ph["measure"] and r["value"] != "not_held"
    ]
    assert any(int(r["value"]) == ph["value"] for r in held)
    assert ph["doc_id"] == "bts-tsar-2024" and ph["period"] == "2023"
    # the rail numbers are HB-136R's points summed (each incident's damage once)
    pts = json.loads((REPO / CFG["inputs"]["points"]).read_text())["features"]
    assert rail["released_incidents"] == len(pts) == 146
    assert rail["damage_usd"] == sum(f["properties"]["damage_usd"] for f in pts)
    assert rail["per_year_mean"] == round(len(pts) / rec["years"], 1)
    # every slide label names its years
    labels = " ".join(i.get("label", "") for i in _slide()["items"])
    assert ph["period"] in labels and rec["period"] in labels


def test_the_map_one_mark_per_place_area_the_damage_one_colour_key_and_source():
    svg = (REPO / OUT["svg"]).read_text(encoding="utf-8")
    rec = _record()
    fc = CFG["figure"]
    circles = re.findall(
        r'<circle cx="[^"]+" cy="[^"]+" r="([^"]+)" fill="([^"]+)"', svg
    )
    marks = circles[: rec["rail"]["places"]]
    key = circles[rec["rail"]["places"] :]
    assert len(key) == len(fc["key_usd"])
    assert {c[1] for c in circles} == {fc["mark_color"]}, "one colour"
    pts = json.loads((REPO / CFG["inputs"]["points"]).read_text())["features"]
    places = P.places(CFG, pts)
    assert len(marks) == len(places) == rec["rail"]["places"]
    dmax = places[0]["damage_usd"]
    for (r, _), p in zip(marks, places):
        want = fc["max_radius_px"] * math.sqrt(p["damage_usd"] / dmax)
        if want >= fc["min_radius_px"]:
            # area in proportion: r^2 / rmax^2 == damage / largest damage
            assert float(r) == pytest.approx(want, abs=0.006)
        else:
            assert float(r) == pytest.approx(fc["min_radius_px"], abs=0.006)
    for (r, _), usd in zip(key, sorted(fc["key_usd"])):
        assert float(r) == pytest.approx(
            fc["max_radius_px"] * math.sqrt(usd / dmax), abs=0.006
        )
    for want in ("FRA Form 6180.54", rec["period"], "Blocks 36 and 37", "not held"):
        assert want in svg, want
    # no decoration: no title, no gradient, no drop shadow
    for banned in ("<title", "Gradient", "filter="):
        assert banned not in svg


def test_the_record_equals_a_fresh_build_and_makes_no_call(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("a network call was attempted")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    for rel, text in P.build(CFG).items():
        assert (REPO / rel).read_text(encoding="utf-8") == text, rel
