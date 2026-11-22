"""HB-39: the evidence store (DN-010 D1 to D3, D6): hashing, append-only writes, reads,
the schema, the RO-Crate manifest, the staleness predicate, and that the server never
imports it."""

from __future__ import annotations

import ast
import hashlib
import json
from datetime import timedelta
from pathlib import Path

import jsonschema
import pytest

from hazbrief.evidence import store as S
from hazbrief.packs import canonical_json

REPO = Path(__file__).resolve().parents[1]
SCHEMA = json.loads(S.repo_path("schema").read_text(encoding="utf-8"))


def _write(store: Path, body, name="t", params=None, t0="2026-10-25T12:00:00Z", **kw):
    args = {
        "activity": {
            "type": "mcp_tool_call",
            "name": name,
            "params": params or {"x": 1},
            "startedAtTime": t0,
            "endedAtTime": t0,
        },
        "server": {"name": "s", "version": "0", "tool_surface_sha256": None},
        "source": [{"id": "pack:erg", "endpoint": "packs/erg.json"}],
        "provenance_class": "recorded_pack",
        "as_of": t0,
        "as_of_basis": "endedAtTime",
        "horizon_s": 3600,
        "horizon_source": "pack:erg",
    }
    args.update(kw)
    return S.write_record(store, body, **args)


def test_canonical_hash_is_the_repositorys_canonical_json_and_raw_bytes():
    body = {"b": [1, 2.5, "é"], "a": None}
    assert S.canonical_hash(body) == hashlib.sha256(canonical_json(body)).hexdigest()
    assert S.canonical_hash({"a": None, "b": [1, 2.5, "é"]}) == S.canonical_hash(body)
    assert S.canonical_hash(b"\x89PNG") == hashlib.sha256(b"\x89PNG").hexdigest()


@pytest.mark.verifies("E-D2")
def test_an_entity_is_written_once_and_each_activity_is_its_own_record(tmp_path):
    sha1, r1 = _write(tmp_path, {"v": 1})
    entity = S.entity_path(tmp_path, sha1, "json")
    before = entity.stat().st_mtime_ns
    sha2, r2 = _write(tmp_path, {"v": 1}, t0="2026-10-25T12:00:01Z")
    assert sha1 == sha2 and entity.stat().st_mtime_ns == before
    assert r1["activity"]["id"] != r2["activity"]["id"]
    assert [r["activity"]["id"] for r in S.read_record(tmp_path, sha1)] == [
        r1["activity"]["id"],
        r2["activity"]["id"],
    ]
    # the same activity again: no new record, the held one untouched
    rec = S.record_path(tmp_path, sha1, r1["activity"]["id"])
    held = rec.read_bytes()
    _write(tmp_path, {"v": 1})
    assert rec.read_bytes() == held
    assert len(S.read_record(tmp_path, sha1)) == 2
    assert S.read_entity(tmp_path, sha1) == {"v": 1}


def test_a_used_entity_resolves_to_its_record_made_before_the_citing_call(tmp_path):
    """HB-49: an empty query result is one body two exchanges share, so one entity
    with two records. A brief resolved a call's `used` hash to the entity's newest
    record, and a later exchange with the same body from another source relabelled
    every earlier brief's appendix row and map. A call can only have read a record
    made before it."""
    old = "2026-10-22T12:52:00Z"
    sha, r_old = _write(tmp_path, {"features": []}, name="GET a", t0=old)
    _, r_new = _write(
        tmp_path, {"features": []}, name="GET b", t0="2026-10-27T03:38:00Z"
    )
    cite = "2026-10-25T21:35:00Z"
    assert S.record_by(tmp_path, sha, cite)["activity"]["id"] == r_old["activity"]["id"]
    assert S.record_by(tmp_path, sha)["activity"]["id"] == r_new["activity"]["id"]
    # a citing call older than every record still gets one (the newest)
    early = "2026-10-01T00:00:00Z"
    assert (
        S.record_by(tmp_path, sha, early)["activity"]["id"] == r_new["activity"]["id"]
    )


def test_bytes_are_their_own_entity_kind(tmp_path):
    sha, rec = _write(tmp_path, b"\x89PNG\r\n", media_type="image/png")
    assert S.entity_path(tmp_path, sha, "bytes").read_bytes() == b"\x89PNG\r\n"
    assert rec["entity"] == {
        "sha256": sha,
        "bytes": 6,
        "encoding": "bytes",
        "media_type": "image/png",
    }
    assert S.read_entity(tmp_path, sha) == b"\x89PNG\r\n"


def test_records_for_matches_name_and_canonical_params(tmp_path):
    _write(tmp_path, {"v": 1}, name="a", params={"p": {"x": 1, "y": 2}})
    _write(tmp_path, {"v": 2}, name="a", params={"p": {"x": 1, "y": 3}})
    _write(tmp_path, {"v": 3}, name="b", params={"p": {"x": 1, "y": 2}})
    hits = S.records_for(tmp_path, "a", {"p": {"y": 2, "x": 1}})
    assert [h["entity"]["sha256"] for h in hits] == [S.canonical_hash({"v": 1})]


def test_a_held_call_is_keyed_by_what_it_used_as_well(tmp_path):
    """HB-99: two scenarios hand a reader tool identical parameters but different
    footprints; each finds its own record, and neither finds the other's."""
    land, water = "a" * 64, "b" * 64
    params = {"area": {"type": "Polygon"}}
    _write(tmp_path, {"v": 1}, name="r", params=params, used=[land, "e" * 64])
    assert [h["used"] for h in S.records_for(tmp_path, "r", params, used=[land])] == [
        [land, "e" * 64]
    ]
    assert S.records_for(tmp_path, "r", params, used=[water]) == []
    later = "2026-10-25T12:00:01Z"
    _write(tmp_path, {"v": 1}, name="r", params=params, t0=later, used=[water])
    assert [h["used"] for h in S.records_for(tmp_path, "r", params, used=[water])] == [
        [water]
    ]
    # without `used`, both (the key HB-94 found too coarse, still there for callers
    # that hand a tool no evidence)
    assert len(S.records_for(tmp_path, "r", params)) == 2


@pytest.mark.verifies("E-D3", "E-D5")
def test_a_narrated_value_is_never_a_record(tmp_path):
    with pytest.raises(ValueError, match="D5"):
        _write(tmp_path, {"v": 1}, provenance_class="narrated_by_model")


def test_every_record_written_validates_against_the_schema(tmp_path):
    _write(tmp_path, {"v": 1}, used=["a" * 64], was_revision_of="b" * 64)
    _write(tmp_path, b"x", media_type="image/png", horizon_s=None, horizon_source=None)
    for r in S.all_records(tmp_path):
        jsonschema.validate(r, SCHEMA)


@pytest.mark.verifies("E-D3")
def test_the_schema_refuses_a_narrated_class_and_an_unknown_field(tmp_path):
    _, rec = _write(tmp_path, {"v": 1})
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**rec, "provenance_class": "narrated_by_model"}, SCHEMA)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**rec, "model_note": "x"}, SCHEMA)


def test_the_crate_manifest_lists_every_entity_and_record_and_is_deterministic(
    tmp_path,
):
    sha, rec = _write(tmp_path, {"v": 1})
    _write(tmp_path, {"v": 2}, used=[sha])
    out = S.write_crate_manifest(tmp_path)
    first = out.read_bytes()
    doc = json.loads(first)
    assert doc["@context"] == S.config()["crate_context"]
    ids = {n["@id"]: n for n in doc["@graph"]}
    root = ids["./"]
    parts = [p["@id"] for p in root["hasPart"]]
    on_disk = sorted(
        p.relative_to(tmp_path).as_posix()
        for p in tmp_path.glob("??/*")
        if not p.name.startswith(".")
    )
    assert sorted(parts) == on_disk
    actions = [n for n in doc["@graph"] if n["@type"] == "CreateAction"]
    assert len(actions) == 2
    used = next(a for a in actions if a["object"])
    first_entity = S.entity_path(tmp_path, sha, "json").relative_to(tmp_path)
    assert used["object"] == [{"@id": first_entity.as_posix()}]
    assert S.write_crate_manifest(tmp_path).read_bytes() == first


def test_stale_exactly_past_the_horizon():
    rec = {"as_of": "2026-10-25T12:00:00Z", "horizon_s": 3600}
    at = S.parse_time(rec["as_of"])
    assert not S.is_stale(rec, at + timedelta(seconds=3600))
    assert S.is_stale(rec, at + timedelta(seconds=3601))
    assert not S.is_stale({**rec, "horizon_s": None}, at + timedelta(days=10**4))
    with pytest.raises(ValueError, match="aware"):
        S.is_stale(rec, at.replace(tzinfo=None))


#: The application (DN-010 D2, DN-011): the evidence store, the brief, and the console
#: dispatcher that reaches the brief only for `hazbrief brief` (HB-41).
APPLICATION = ("evidence", "brief", "command.py")


@pytest.mark.verifies("E-D2")
def test_no_server_module_imports_the_application():
    """DN-010 D2, D7: the store and the brief are the application's. Every module under
    src/hazbrief outside them is checked for an import of either."""
    pkg = REPO / "src" / "hazbrief"
    offenders = []
    for path in pkg.rglob("*.py"):
        if path.relative_to(pkg).parts[0] in APPLICATION:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            if any(
                n.startswith(("hazbrief.evidence", "hazbrief.brief")) for n in names
            ):
                offenders.append(str(path.relative_to(REPO)))
    assert offenders == []


def test_the_store_directory_honours_its_override(monkeypatch, tmp_path):
    monkeypatch.setenv(S.config()["store_env"], str(tmp_path))
    assert S.default_store_dir() == tmp_path
    monkeypatch.delenv(S.config()["store_env"])
    assert S.default_store_dir() == S.repo_path("store_dir")


def test_a_record_holding_a_configured_secret_is_refused_and_nothing_is_written(
    tmp_path, monkeypatch
):
    """SECURITY section 3: the store refuses a secret as the exchange recorder does."""
    from hazbrief.config import settings

    monkeypatch.setattr(settings, "census_api_key", "k" * 40)
    with pytest.raises(RuntimeError, match="secret"):
        _write(tmp_path, {"v": "the key is " + "k" * 40})
    with pytest.raises(RuntimeError, match="secret"):
        _write(tmp_path, {"v": 1}, params={"x": "k" * 40})
    with pytest.raises(RuntimeError, match="secret"):
        _write(
            tmp_path,
            {"v": 1},
            secrets=["passed-in-secret"],
            params={"x": "passed-in-secret"},
        )
    assert not any(tmp_path.rglob("*"))


def test_a_secret_that_json_escapes_is_still_refused_by_the_store(
    tmp_path, monkeypatch
):
    """Review L3-11, the store half (HB-99 step 5): in canonical JSON a `"` or `\\` in
    the value is escaped, so the raw value is not a substring of the blob; the store
    compares the escaped form too, as the exchange recorder does since HB-96
    (tests/test_http_security.py). The configured key and a caller's `secrets` both."""
    from hazbrief.config import settings

    secret = 'SEC"RET\\789'
    assert secret.encode() not in canonical_json({"v": secret})
    monkeypatch.setattr(settings, "census_api_key", secret)
    with pytest.raises(RuntimeError, match="secret"):
        _write(tmp_path, {"v": secret})
    with pytest.raises(RuntimeError, match="secret"):
        _write(tmp_path, {"v": 1}, params={"x": secret})
    monkeypatch.setattr(settings, "census_api_key", "")
    passed = 'PASS"ED\\456'
    with pytest.raises(RuntimeError, match="secret"):
        _write(tmp_path, {"v": passed}, secrets=[passed])
    assert not any(tmp_path.rglob("*"))
