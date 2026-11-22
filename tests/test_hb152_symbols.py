"""HB-152: the map's markers draw the FGDC HSWG symbols as SVG built from the held
fonts, hazbrief's own labelled symbol where no glyph is named, and the layer control
calls the set a draft prototype (HBD-315; Issue fa822d34; the operator's second review,
Issue 2924654f item 5: markers still read as dots).

- Every class in `symbols.yaml` has a committed SVG that parses, draws a non-empty frame
  and ink path, and matches `manifest.json`; the siting classes (command post, triage,
  staging) are built though no layer draws them yet (item 6).
- Every FGDC class's name, key stroke, row and row marking are the fetched reference
  page's (`docs/evidence/hb152/ref_glyphs.tsv`), and the key is one the fonts map
  (HB-150's glyph table).
- On the reference pair every drawn marker of a mapped class references its class's SVG,
  the nearby services per feature by `service` (ADDENDUM-01 section 1), and its popup
  keeps a Symbol row after the travel rows.
- No marker draws the HB-142R placeholder; the legend line is on all 28 briefs; an
  own-symbol class carries its sentence in its popup and its legend row."""

from __future__ import annotations

import asyncio
import csv
import functools
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

from hazbrief.brief import cli, layers, render
from hazbrief.brief.orchestrator import assemble, load_config
from hazbrief.evidence import labels as L
from hazbrief.evidence import store as S

REPO = Path(__file__).resolve().parents[1]
BRIEFS = REPO / "docs" / "briefs"
SYMBOLS = REPO / "src" / "hazbrief" / "brief" / "symbols.yaml"
EV = REPO / "docs" / "evidence" / "hb152"
PAIR = ["csx-point-of-rocks-day", "csx-point-of-rocks-night"]
SVG_NS = "{http://www.w3.org/2000/svg}"
OWN = "hazbrief's own symbol; no FGDC glyph is named for this class"


def _table() -> dict:
    return yaml.safe_load(SYMBOLS.read_text(encoding="utf-8"))


def _svg_dir() -> Path:
    return REPO / _table()["standard"]["svg_dir"]


@functools.lru_cache(maxsize=4)
def _layers(sid: str) -> dict:
    """The brief replayed from its committed scenario (HB-151's helper, 0 calls)."""
    s = cli.load_scenario(BRIEFS / sid / "scenario.json")
    brief = asyncio.run(
        assemble(
            s,
            now=S.parse_time(L.config()["fixture_now"]),
            replay_stores=cli.replay_stores(),
        )
    )
    return {x["id"]: x for x in layers.build(brief, load_config())["layers"]}


def _all_briefs() -> list[str]:
    return sorted(p.parent.name for p in BRIEFS.glob("*/brief.html"))


# ── items 2 and 6: one SVG per class ─────────────────────────────────────────────────


@pytest.mark.verifies("VR-159")
@pytest.mark.parametrize("cls", list(_table()["classes"]))
def test_every_class_has_an_svg_that_parses_and_draws(cls):
    path = _svg_dir() / f"{cls}.svg"
    assert path.is_file(), cls
    root = ET.fromstring(path.read_text(encoding="utf-8"))
    assert root.tag == f"{SVG_NS}svg" and root.get("data-hb-class") == cls
    paths = {p.get("data-hb"): p.get("d") for p in root.iter(f"{SVG_NS}path")}
    assert set(paths) == {"frame", "ink"}, cls
    assert all(d and d.startswith("M") and d.count("Z") >= 1 for d in paths.values())
    assert root.find(f"{SVG_NS}title").text, cls
    assert _table()["classes"][cls]["verified"] is True


@pytest.mark.verifies("VR-159")
def test_the_manifest_names_every_class_and_every_file_hash():
    table = _table()
    man = json.loads((_svg_dir() / "manifest.json").read_text(encoding="utf-8"))
    assert [r["class"] for r in man["classes"]] == list(table["classes"])
    assert man["stage"] == table["standard"]["stage"]
    for r in man["classes"]:
        data = (_svg_dir() / r["file"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == r["sha256"], r["file"]
        assert r["own"] is bool(table["classes"][r["class"]].get("own"))
    on_disk = {p.name for p in _svg_dir().iterdir()}
    assert on_disk == {r["file"] for r in man["classes"]} | {"manifest.json"}


@pytest.mark.verifies("VR-159")
def test_the_siting_classes_are_built_though_no_layer_draws_them():
    for cls in ("command_post", "triage", "staging"):
        assert (_svg_dir() / f"{cls}.svg").is_file(), cls
        assert not layers.symbol_own(cls), cls


def test_the_stage_is_configured_and_the_size_is_28_px():
    std = _table()["standard"]
    assert std["stage"] == "S2" and std["size_px"] == 28
    assert std["held"] is True


# ── item 1: the names are the reference pages' ───────────────────────────────────────


@pytest.mark.verifies("VR-159")
def test_every_fgdc_class_is_the_reference_pages_row():
    with (EV / "ref_glyphs.tsv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    page_of = {
        "fgdc-hswg-ref-operations": "Operations",
        "fgdc-hswg-ref-infrastructures": "Infrastructures",
        "fgdc-hswg-ref-incidents": "Incidents",
    }
    table = _table()
    for cls, e in table["classes"].items():
        if e.get("own"):
            continue
        page = page_of[table["families"][e["family"]]["page"]]
        hit = [r for r in rows if r["page"] == page and r["key"] == e["key"]]
        assert len(hit) == 1, cls
        r = hit[0]
        assert (r["name"], r["row"], r["row_class"]) == (
            e["name"],
            e["row"],
            e["row_class"],
        ), cls


def test_every_fgdc_key_is_mapped_by_its_font():
    """HB-150's glyph table lists every mapped code of every txt font."""
    with (REPO / "docs/evidence/hb150/hswg_glyphs.tsv").open(encoding="utf-8") as f:
        mapped = {
            (r["font_file"], r["character"]) for r in csv.DictReader(f, delimiter="\t")
        }
    table = _table()
    stage = table["standard"]["stage"]
    for cls, e in table["classes"].items():
        fam = table["families"][e["family"]]
        font = "ersV2txt/" + fam["font"].format(stage=stage)
        for key in (
            [fam["background"], fam["frame"]]
            if e.get("own")
            else [fam["background"], e["key"]]
        ):
            assert (font, key) in mapped, (cls, key)


@pytest.mark.verifies("VR-159")
def test_no_class_names_a_glyph_the_pages_leave_unnamed():
    """Decontamination and the generic emergency-services marker have no page row."""
    table = _table()["classes"]
    assert table["decontamination"].get("own") and table["emergency_services"].get(
        "own"
    )
    with (EV / "ref_glyphs.tsv").open(encoding="utf-8") as f:
        names = {r["name"].lower() for r in csv.DictReader(f, delimiter="\t")}
    assert not any("decontam" in n for n in names)
    assert "emergency services" not in names


# ── items 3 and 4: the drawn markers ─────────────────────────────────────────────────


@pytest.mark.verifies("VR-159")
@pytest.mark.parametrize("sid", PAIR)
def test_every_drawn_marker_on_the_pair_references_its_class_svg(sid):
    table = _table()
    kinds = table["feature_kinds"]
    px = table["standard"]["size_px"]
    seen = set()
    for lid, lay in _layers(sid).items():
        if not lay["features"] or lay["kind"] != "point":
            continue
        st = lay["style"]
        # HB-157 item 8: the cordons on the modelled boundary are roadblock candidates;
        # HB-155: the suggested points draw the command post, triage and staging classes
        mapped = lid in table["classes"] or lid in (
            "nearby_services",
            "care",
            "modelled_cordons",
            "sited_points",
        )
        for f in lay["features"]:
            p = f["properties"]
            # HB-155 ADDENDUM-02 item 6: the area's ring is a line in the services layer
            if p.get("ring"):
                continue
            assert "glyph" not in p, lid
            if not mapped:
                assert "symbol" not in p, lid
                continue
            cls = p["symbol"]
            if lid == "nearby_services":
                assert cls == f"nearby_{p['service']}", p["service"]
            elif lid == "care":
                assert cls in kinds.values()
            elif lid == "modelled_cordons":
                assert cls == "roadblock_candidates"
            elif lid == "sited_points":
                assert cls in ("command_post", "triage", "staging")
            else:
                assert cls == lid
            assert st["symbols"][cls] == layers.symbol_svg(cls, st["fill"], px)
            assert (
                f"<th>Symbol</th><td>{layers.esc(layers.symbol_line(cls))}</td>"
                in p["popup"]
            )
            seen.add(cls)
        assert "glyph" not in st, lid
    # ADDENDUM-01 section 1: the pair draws all four nearby classes
    assert {"nearby_fire", "nearby_ems", "nearby_police", "nearby_hospital"} <= seen
    assert "spill" in seen


@pytest.mark.parametrize("sid", PAIR)
def test_the_nearby_symbol_row_stays_after_the_travel_rows(sid):
    for f in _layers(sid)["nearby_services"]["features"]:
        if f["properties"].get("ring"):  # HB-155: the area's ring, not a service
            continue
        pop = f["properties"]["popup"]
        assert pop.index("<th>Symbol</th>") > pop.index("Travel time"), pop


def test_the_ink_is_white_or_black_by_wcag_contrast():
    assert layers.ink_for("#000000") == "#ffffff"
    assert layers.ink_for("#ffffff") == "#000000"
    assert layers.ink_for("#0F766E") == "#ffffff"  # the nearby teal
    assert layers.ink_for("#FDE047") == "#000000"  # a light yellow


@pytest.mark.verifies("VR-159")
def test_both_map_branches_draw_the_svg_and_no_placeholder():
    src = Path(render.__file__).read_text(encoding="utf-8")
    assert "hb-glyph" not in src and "properties.glyph" not in src
    assert "getProperty('glyph')" not in src
    assert "html: sym" in src  # Leaflet: the SVG in a divIcon
    assert "data:image/svg+xml" in src  # Google: the SVG as the marker image
    assert "s.symbol_px" in src


# ── items 5 and 7: the committed briefs ──────────────────────────────────────────────


def test_the_rebuild_covers_all_28_briefs():
    # HB-175: 29 with the ammonia brief (the name is kept)
    assert len(_all_briefs()) == 29


@pytest.mark.verifies("VR-159")
@pytest.mark.parametrize("sid", _all_briefs())
def test_every_brief_carries_the_legend_line_and_no_placeholder(sid):
    page = (BRIEFS / sid / "brief.html").read_text(encoding="utf-8")
    line = render.esc(_table()["standard"]["legend_line"])
    # the layer list's last entry, inside the load read's protected place
    assert f'<li class="pl" id="symbols-note">{line}</li></ul>' in page
    assert "Placeholder glyph" not in page and "ANSI INCITS 415-2006" not in page
    assert "hb-glyph" not in page


def _layer_row(page: str, lid: str) -> str:
    # restated by HB-158 item 3: a drawn layer's row is one line that opens onto its
    # legend (`render._layer_row`); a muted row (nothing there) is `lrow lnone`
    m = re.search(
        rf'<li class="lrow" data-row="{lid}"><details>.*?</details></li>',
        page,
    )
    assert m, lid
    return m.group(0)


@pytest.mark.verifies("VR-159")
def test_the_nearby_row_shows_all_four_class_symbols_on_csx_day():
    page = (BRIEFS / PAIR[0] / "brief.html").read_text(encoding="utf-8")
    row = _layer_row(page, "nearby_services")
    for cls in ("nearby_fire", "nearby_ems", "nearby_police", "nearby_hospital"):
        assert row.count(f'data-hb-class="{cls}"') == 2, (
            cls
        )  # beside the toggle and in the list
        assert render.esc(layers.symbol_legend(cls)) in row, cls


@pytest.mark.verifies("VR-159")
def test_an_own_symbol_class_carries_its_sentence_in_popup_and_legend():
    drawn = [
        sid
        for sid in _all_briefs()
        # restated by HB-158 item 4: a muted row of a layer with nothing there keeps
        # its symbol too, so "drawn" is the drawn row
        if '<li class="lrow" data-row="emergency_services">'
        in (BRIEFS / sid / "brief.html").read_text(encoding="utf-8")
    ]
    assert drawn, "no brief draws the emergency services layer"
    line = layers.symbol_line("emergency_services")
    assert OWN in line
    for sid in drawn:
        page = (BRIEFS / sid / "brief.html").read_text(encoding="utf-8")
        row = _layer_row(page, "emergency_services")
        assert render.esc(line) in row, sid  # the legend row (the page's escaping)
        # the popup in the page's data script (the layers' escaping): JSON, with `</`
        # broken as `<\/`
        cell = json.dumps(f"<th>Symbol</th><td>{layers.esc(line)}</td>")[1:-1]
        assert cell.replace("</", "<\\/") in page, sid
