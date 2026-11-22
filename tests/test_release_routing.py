"""Every ERG guide routed to a release model, or to "no dispersion model applies".

HB-120; DN-020 ADDENDUM-02 section 2 item 3: the routing table
(`packs/release_routing.json`, from `packs/src/release_routing.yaml`) covers every
orange guide of the held ERG pack, each row with the guide's own POTENTIAL HAZARDS
words on their page; item 4: the modelled tier's three states. HB-120 Part C step 5:
coverage, the basis quotes, the whole index through the lookup (replay: it reads
`packs/erg.json` and the routing pack only, no resolver call, ADDENDUM-01 section 4),
and a seeded unknown guide failing loudly. ADDENDUM-01 section 2: "not applicable" is
decided before any properties pack is read.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

from hazbrief import packs as P
from hazbrief.brief import derive
from hazbrief.brief import orchestrator as O
from hazbrief.brief import routing as RT

REPO = Path(__file__).resolve().parents[1]
RAW = REPO / "corpus" / "raw"
needs_raw = pytest.mark.skipif(
    not RAW.is_dir(),
    reason="corpus/raw/ absent: binaries are gitignored; provenance is url + sha256",
)
ERG = json.loads((REPO / "packs" / "erg.json").read_text(encoding="utf-8"))["data"]
TABLE = P.load_app_pack("release_routing").data.model_dump(mode="json")
STATUSES = {"routed", "not_applicable", "not_available"}
#: The three demonstrations (Part C step 5): a Class 1, a Class 7 and a Class 8 solid.
NOT_APPLICABLE_FIXTURES = ("anfo-fire-i81", "un2915-i81", "un1823-solid-i81")
#: The four DN-001 classes' fixtures (the drawn demonstrations).
CLASS_FIXTURES = (
    "csx-point-of-rocks-day",
    "un1075-fire-i81",
    "un1203-i83",
    "un1977-wilson-bridge",
)


def _builder():
    spec = importlib.util.spec_from_file_location(
        "build_packs", REPO / "scripts" / "build_packs.py"
    )
    B = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(REPO / "scripts"))
    spec.loader.exec_module(B)
    return B


def _footprint(sid: str) -> dict:
    d = json.loads((REPO / "fixtures" / "scenarios" / f"{sid}.json").read_text())
    return d["tools"]["protective_action_footprint"]


def _index_cases() -> list[tuple[str, str, str]]:
    """(UN number, name, guide) for every name of every ERG index entry."""
    return [
        (un, n["name"], n["guide"])
        for un, entry in sorted(ERG["index"].items())
        for n in entry["names"]
    ]


# ── Part A: the table covers the held ERG, and each row stands on the guide's words ──


def test_every_guide_of_the_held_erg_has_a_routing_block():
    assert set(TABLE["guides"]) == set(ERG["guides"])
    assert len(TABLE["guides"]) == 62


def test_each_guide_has_exactly_one_row_per_state_it_serves():
    names: dict[str, list[str]] = {g: [] for g in ERG["guides"]}
    for entry in ERG["index"].values():
        for n in entry["names"]:
            names[RT.base_guide(n["guide"])].append(n["name"])
    for g, block in TABLE["guides"].items():
        states = [r["state"] for r in block["rows"]]
        assert len(states) == len(set(states)), g
        if "any" in states:
            assert states == ["any"], g
            continue
        named = {RT.name_state([n])[0] for n in names[g]} - {None}
        assert named <= set(states), (g, sorted(named - set(states)))


def test_a_routed_row_names_its_class_and_a_not_applicable_row_its_reason():
    for g, block in TABLE["guides"].items():
        for r in block["rows"]:
            if r["route"] == "not_applicable":
                assert r["reason"] and r["loc_class"] is None, g
            else:
                assert r["loc_class"] and r["reason"] is None, g


def test_every_basis_is_one_of_its_guides_potential_hazards_items_on_that_page():
    for g, block in TABLE["guides"].items():
        ph = ERG["guides"][g]["sections"]["potential_hazards"]
        items = {" ".join(it["text"].split()) for it in ph["items"]}
        for r in block["rows"]:
            assert r["basis"]["locator"] == ph["locator"], g
            assert " ".join(r["basis"]["quote"].split()) in items, g


@needs_raw
def test_the_committed_pack_is_the_builders_output_with_every_quote_on_its_page():
    """The build re-reads every basis on its held page (`_receipt`); the committed pack
    equals a fresh build."""
    B = _builder()
    cfg = B.load_config(REPO / "packs" / "src" / "build_config.yaml")
    built = B.build_packs(cfg, REPO, ("release_routing",))["release_routing"]
    committed = json.loads((REPO / "packs" / "release_routing.json").read_text())
    assert built == committed
    sources = B.SourceSet(cfg, REPO)
    for block in built["data"]["guides"].values():
        for r in block["rows"]:
            b = r["basis"]
            assert sources.quote_on_page(b["doc_id"], b["page"], b["quote"])


def _seeded_build(B, tmp_path, mutate) -> None:
    """Build the pack from a mutated copy of the authored table, with the builder module
    `B` the caller expects its `BuildError` from (each load is a new module)."""
    cfg = B.load_config(REPO / "packs" / "src" / "build_config.yaml")
    spec = yaml.safe_load((REPO / "packs/src/release_routing.yaml").read_text())
    mutate(spec)
    p = tmp_path / "release_routing.yaml"
    p.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    cfg = copy.deepcopy(cfg)
    cfg["paths"]["release_routing"] = str(p)
    erg = json.loads((REPO / "packs" / "erg.json").read_text())
    B.build_release_routing(cfg, B.SourceSet(cfg, REPO), erg)


@needs_raw
@pytest.mark.parametrize(
    "seed, says",
    [
        (lambda s: s["guides"].pop("163"), "no block for ['163']"),
        (
            lambda s: s["guides"].__setitem__("999", s["guides"]["163"]),
            "no such guide for ['999']",
        ),
        (lambda s: s["guides"]["124"]["rows"][0].pop("basis"), "a row with no basis"),
        (
            lambda s: s["guides"]["124"]["rows"][0]["basis"].__setitem__(
                "quote", "Vapors may be lighter than air."
            ),
            "is not one of the guide's POTENTIAL HAZARDS items",
        ),
        (
            lambda s: s["guides"]["154"]["rows"].pop(1),
            "its index names state ['solid'], which have no row",
        ),
    ],
    ids=[
        "missing-guide",
        "unknown-guide",
        "no-basis",
        "basis-off-page",
        "no-solid-row",
    ],
)
def test_a_table_that_misses_a_guide_or_a_basis_fails_the_build(tmp_path, seed, says):
    B = _builder()
    with pytest.raises(B.BuildError) as exc:
        _seeded_build(B, tmp_path, seed)
    assert says in str(exc.value)


# ── Part C: the whole index through the lookup, and the lookup's edges ──


@pytest.mark.parametrize("un, name, guide", _index_cases(), ids=lambda x: str(x)[:40])
def test_every_index_entry_resolves_through_its_guide_to_a_route(un, name, guide):
    state, basis = RT.name_state([name])
    d = RT.route(TABLE, guide, state, basis)
    assert d.status in STATUSES
    assert d.guide == RT.base_guide(guide)
    if d.status == "routed":
        assert d.route in ("two_phase_jet", "evaporating_pool", "instantaneous")
        assert d.loc_class in ("toxic", "flammable_lfl", "oxygen_deficiency")
        assert d.basis["locator"].startswith("erg2024-en-pdf#p")
    elif d.status == "not_applicable":
        assert d.reason.startswith("No dispersion model applies")
    else:
        assert "storage state" in d.reason


@pytest.mark.parametrize("guide", ["999", "110", "12", "abc", None])
def test_a_seeded_unknown_guide_number_fails_loudly(guide):
    with pytest.raises(RT.RoutingError):
        RT.route(TABLE, guide, None)


def test_the_polymerization_letter_routes_as_its_guide():
    for g in ("116P", "131P", "153P"):
        assert RT.route(TABLE, g, None) == RT.route(TABLE, g[:3], None)


def test_the_lookup_reads_the_guide_and_the_state():
    jet = RT.route(TABLE, "124", "pressure_liquefied")
    assert (jet.status, jet.route, jet.loc_class) == (
        "routed",
        "two_phase_jet",
        "toxic",
    )
    pool = RT.route(TABLE, "128", "ambient_liquid")
    assert (pool.route, pool.loc_class) == ("evaporating_pool", "flammable_lfl")
    solid = RT.route(TABLE, "154", "solid")
    assert solid.status == "not_applicable" and "solid" in solid.reason
    liquid = RT.route(TABLE, "154", "ambient_liquid")
    assert (liquid.status, liquid.loc_class) == ("routed", "toxic")
    # the guide alone where its rows agree; else the storage state is named missing
    assert RT.route(TABLE, "124", None).route == "two_phase_jet"
    assert RT.route(TABLE, "163", "ambient_liquid").status == "not_applicable"
    unknown = RT.route(TABLE, "115", None, "nothing states it")
    assert unknown.status == "not_available"
    assert unknown.reason.startswith("the storage state is not held")
    # a stated state the guide has no row for is not available, never guessed
    assert RT.route(TABLE, "124", "ambient_liquid").status == "not_available"


def test_the_four_dn001_classes_route_to_their_own_dense_gas_class():
    """For the drawn demonstrations the routing names the class the footprint's DN-001
    class names, so the drawn layers do not move (HB-120 ADDENDUM-01 section 1)."""
    keys = O.load_config()["weather"]["dense_gas"]["loc_class_keys"]
    for sid in CLASS_FIXTURES:
        fp = _footprint(sid)
        d = RT.modelled_route(TABLE, fp)
        assert d.status == "routed", sid
        assert RT.class_key(d, keys) == fp["hazard_class"]["class_id"], sid


def test_every_loc_class_maps_to_a_dense_gas_class():
    spec = O.load_config()["weather"]["dense_gas"]
    for loc, key in spec["loc_class_keys"].items():
        for k in [key] if isinstance(key, str) else key.values():
            assert k in spec["classes"], (loc, k)


# ── Part B: the three states on the brief ──


@pytest.fixture
def no_properties(monkeypatch):
    """Every application pack but the routing table refuses: a channel that reads the
    properties, the sigma curves or the release scenarios fails the test."""
    real = P.load_app_pack

    def guarded(kind, *a, **k):
        if kind != "release_routing":
            raise AssertionError(f"read {kind} for a not-applicable guide")
        return real(kind, *a, **k)

    monkeypatch.setattr(P, "load_app_pack", guarded)


@pytest.mark.parametrize("sid", NOT_APPLICABLE_FIXTURES)
def test_not_applicable_is_decided_before_any_properties_pack(sid, no_properties):
    fp = _footprint(sid)
    cfg = O.load_config()
    dg = derive.dense_gas(None, fp, {}, cfg, replay=True)
    assert dg["state"] == "not_applicable"
    assert dg["footprint"] is None
    assert dg["reason"].startswith("No dispersion model applies")
    assert dg["release_route"]["status"] == "not_applicable"
    assert dg["evidence"]["record"]["state"] == "not_applicable"
    pf = derive.puff(None, fp, {}, cfg)
    assert pf["state"] == "not_applicable"
    assert pf["envelopes"] == []
    assert pf["lines"] == [
        cfg["weather"]["puff"]["not_applicable"].format(reason=dg["reason"])
    ]


def test_the_dense_gas_route_key_keeps_the_engines_meaning():
    """ADDENDUM-01 section 2: `route` stays the engine's route; the release route is
    its own key."""
    fp = _footprint("un2915-i81")
    dg = derive.dense_gas(None, fp, {}, O.load_config(), replay=True)
    assert dg["route"] is None
    assert dg["release_route"]["route"] == "not_applicable"


def test_a_routed_guide_without_a_storage_state_is_not_available_naming_it():
    fp = _footprint("un1057-fire-unresolved-i81")
    d = RT.modelled_route(TABLE, fp)
    assert d.status == "not_available"
    assert "storage state" in d.reason


def test_a_routed_guide_with_no_id_number_is_not_available():
    d = RT.modelled_route(TABLE, _footprint("placard-2-3-i81"))
    assert (d.status, d.reason) == (
        "not_available",
        "the material is not resolved to an ID number",
    )


@pytest.mark.parametrize("sid", NOT_APPLICABLE_FIXTURES)
def test_the_brief_shows_the_guidance_and_the_modelled_entry_reads_not_applicable(sid):
    """Part B step 4: `material_response_guidance` is untouched and present; the
    modelled entry reads "not applicable" with the guide's reason. The committed brief
    is a fresh replay build (tests/test_brief.py)."""
    page = (REPO / "docs" / "briefs" / sid / "brief.html").read_text(encoding="utf-8")
    assert "<h2>Response guidance</h2>" in page
    fp = _footprint(sid)
    reason = RT.modelled_route(TABLE, fp).reason
    spec = O.load_config()["weather"]
    import html

    for line in (
        spec["dense_gas"]["not_applicable"].format(reason=reason),
        spec["puff"]["not_applicable"].format(reason=reason),
    ):
        assert f"<p>{html.escape(line, quote=False)}</p>" in page
    appendix = (REPO / "docs" / "briefs" / sid / "appendix.txt").read_text()
    assert f"state  not applicable: {reason}" in appendix
    assert "release route  not applicable" in appendix


def test_the_three_demonstrations_are_the_three_classes():
    """Part C step 5: one Class 1 explosive, one Class 7, one Class 8 solid; synthetic,
    with no container and no release block."""
    want = {
        "anfo-fire-i81": ("112", {"1.1", "1.2", "1.3", "1.5"}, "placard_classes"),
        "un2915-i81": ("163", {"7"}, "hazard_classes"),
        "un1823-solid-i81": ("154", {"8"}, "hazard_classes"),
    }
    releases = yaml.safe_load((REPO / "fixtures/scenario_releases.yaml").read_text())
    manifest = yaml.safe_load((REPO / "fixtures/scenarios.yaml").read_text())
    by_id = {s["id"]: s for s in manifest["scenarios"]}
    for sid, (guide, classes, field) in want.items():
        fp = _footprint(sid)
        assert fp["guide"]["number"] == guide
        assert classes <= set(TABLE["guides"][guide][field])
        assert sid not in (releases.get("releases") or {})
        assert by_id[sid]["incident"]["container"] == "unknown"
        assert by_id[sid]["origin"] == "HB-120"
    assert RT.name_state(_footprint("un1823-solid-i81")["material"]["names"])[0] == (
        "solid"
    )
