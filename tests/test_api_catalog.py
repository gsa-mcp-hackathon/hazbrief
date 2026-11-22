"""corpus/api_catalog.yaml (HB-06): every in-scope API has every field, every
documentation and terms URL is a corpus manifest entry, every key is wired, every probe
is recorded; and scripts/probe_apis.py keeps the section 15 contract."""

from __future__ import annotations

import importlib.util
import json
import os
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
CORPUS = REPO / "corpus"
SCRIPT = REPO / "scripts" / "probe_apis.py"
_spec = importlib.util.spec_from_file_location("probe_apis", SCRIPT)
P = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(P)

SERVER = yaml.safe_load((CORPUS / "api_catalog.yaml").read_text())["apis"]
#: HB-49: the APIs the workbench calls and no tool does, in the same schema
WORKBENCH = yaml.safe_load((CORPUS / "workbench_api_catalog.yaml").read_text())["apis"]
CATALOG = SERVER + WORKBENCH
SOURCES = yaml.safe_load((CORPUS / "sources.yaml").read_text())["sources"]
URLS = {s.get("url") for s in SOURCES}
DOC_IDS = {s["doc_id"] for s in SOURCES}
PROBES = [
    json.loads(x) for x in (CORPUS / "api_probe_log.jsonl").read_text().splitlines()
]

#: HB-06 "APIs in scope", by catalog id.
IN_SCOPE = {
    "nws",
    "census_data",
    "tigerweb",
    "lodes",
    "usgs_structures",
    "cms_data",
    "healthdata_socrata",
    "pubchem",
    "usgs_3dhp",
    # HB-10: the rail, Provider Data Catalog and geocoder sources of
    # facilities_in_footprint and receiving_hospitals
    "bts_ntad",
    "cms_provider_data",
    "census_geocoder",
}
#: HB-49: the state linear-referencing services the workbench's milepost derivation
#: reads (no tool calls them; corpus/workbench_api_catalog.yaml)
WORKBENCH_IN_SCOPE = {
    "pasda_penndot",
    "mdot_sha_milepoints",
    "vdot_lrs",
    # HB-50: the Census Geocoder's one-line address endpoint
    "census_geocoder_locations",
    # HB-54: the USGS NLDI, which the downstream path navigates
    "nldi",
    # HB-55: County Business Patterns, the elevation service and MRLC's NLCD WMS
    "census_cbp",
    "epqs",
    "mrlc_nlcd",
    # HB-56: nowCOAST's radar WMS
    "nowcoast_radar",
    # HB-59: the 3DEP elevation ImageServer, whose getSamples the terrain panel reads
    "usgs_3dep",
    # HB-59 ADDENDUM-02: USGS's Annual NLCD WMS, which replaced MRLC's for CONUS
    "usgs_annual_nlcd",
    # HB-59 ADDENDUM-03: the public-domain Annual NLCD COG mirror the land cover reads
    "nlcd_cog_mirror",
    # HB-119: the materials resolver's two sources, CAMEO Chemicals and PubChem
    "cameo_chemicals",
    "pubchem_pug_rest",
    "pubchem_pug_view",
}
FIELDS = (
    "id", "name", "runtime", "status", "base_url", "docs", "documentation_url", "auth",
    "rate_limits", "terms", "identification", "cadence", "as_of", "formats", "errors",
    "probe", "last_verified",
)  # fmt: skip
AUTH = ("type", "key", "env_var", "signup_url", "signup_procedure")


def test_every_in_scope_api_is_catalogued_once():
    assert sorted(a["id"] for a in SERVER) == sorted(IN_SCOPE)
    assert sorted(a["id"] for a in WORKBENCH) == sorted(WORKBENCH_IN_SCOPE)
    ids = [a["id"] for a in CATALOG]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("api", CATALOG, ids=lambda a: a["id"])
def test_every_api_has_every_field(api):
    missing = [k for k in FIELDS if k not in api]
    assert not missing, missing
    assert all(k in api["auth"] for k in AUTH)
    assert api["rate_limits"]["documented"] and "observed" in api["rate_limits"]
    assert api["terms"]["url"] and api["terms"]["clauses"]
    assert api["auth"]["type"] in ("none", "key", "app_token")
    assert api["auth"]["key"] in ("none", "optional", "required")
    if api["auth"]["key"] != "none":
        assert api["auth"]["env_var"] and api["auth"]["signup_url"]
    if api["runtime"]:
        assert api["probe"], "a runtime API is probed before any tool calls it"
    if not api["probe"]:
        assert api["probe_reason"] and api["last_verified"] is None


@pytest.mark.parametrize("api", CATALOG, ids=lambda a: a["id"])
def test_every_documentation_and_terms_url_is_a_manifest_entry(api):
    assert api["documentation_url"] in URLS, api["documentation_url"]
    assert api["terms"]["url"] in URLS, api["terms"]["url"]
    assert set(api["docs"]) <= DOC_IDS, set(api["docs"]) - DOC_IDS
    assert api["terms"]["doc"] in api["docs"]


@pytest.mark.parametrize(
    "api",
    [a for a in CATALOG if a["probe"] and a["status"] != "superseded"],
    ids=lambda a: a["id"],
)
def test_last_verified_is_the_latest_probe_of_that_api(api):
    rows = [
        r for r in PROBES if r["api"] == api["id"] and r["url"] == api["probe"]["url"]
    ]
    assert rows, "no probe recorded"
    assert api["last_verified"] == max(r["date"] for r in rows)
    assert rows[-1]["status"] is not None, rows[-1].get("error")


@pytest.mark.parametrize(
    "api", [a for a in CATALOG if a["status"] == "superseded"], ids=lambda a: a["id"]
)
def test_a_superseded_row_names_its_successor_its_scope_and_the_dated_basis(api):
    # HB-59 ADDENDUM-02: the row stays as the record that the data moved, so a later
    # task reads why and where to rather than probing it; last_verified is the date the
    # move was verified, not a probe's.
    sup = api["superseded"]
    assert sup["by"] in {a["id"] for a in CATALOG if a["status"] == "active"}
    assert sup["scope"].strip() and sup["basis"].strip()
    assert api["last_verified"] == sup["date"]
    assert set(sup["docs"]) <= set(api["docs"]) | DOC_IDS


def test_every_key_is_in_env_example_and_settings():
    """An active API's key is a setting and is in .env.example with its signup URL. A
    key for an API the server does not call (`status: reference`) is neither: no
    setting reads a credential that no call uses (HB-95, review L1-9)."""
    sys.path.insert(0, str(REPO / "src"))
    from hazbrief.config import Settings

    env_example = (REPO / ".env.example").read_text()
    for a in CATALOG:
        var = a["auth"]["env_var"]
        if not var:
            continue
        if a["status"] == "active":
            assert f"\n{var}=" in env_example, var
            assert var.lower() in Settings.model_fields, var
            assert a["auth"]["signup_url"] in env_example, var
        else:
            assert f"\n{var}=" not in env_example, var
            assert var.lower() not in Settings.model_fields, var


def test_user_agent_is_the_form_dn002_fixes():
    from hazbrief import __version__
    from hazbrief.config import Settings

    ua = Settings(hazbrief_contact_url="https://example.org/x").user_agent
    assert ua == f"hazbrief-mcp/{__version__} (+https://example.org/x)"


# ------------------------------------------------------------------ the probe loop
N = 6


class _Slow(BaseHTTPRequestHandler):
    hits: dict = {}

    def do_GET(self):  # noqa: N802
        _Slow.hits[self.path] = _Slow.hits.get(self.path, 0) + 1
        time.sleep(0.4)
        body = b'{"copyrightText": "Data Refreshed October, 2026."}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Slow)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _Slow.hits = {}
    yield srv
    srv.shutdown()


def _workspace(root: Path, port: int) -> list:
    root.mkdir(parents=True)
    apis = [
        {"id": f"a{i}", "probe": {"url": f"http://127.0.0.1:{port}/a{i}",
                                  "as_of": {"json": ["copyrightText"]}}}
        for i in range(N)
    ]  # fmt: skip
    (root / "catalog.yaml").write_text(yaml.safe_dump({"apis": apis}))
    (root / "config.yaml").write_text(
        yaml.safe_dump(
            {"timeout_seconds": 5, "ceiling_wall_clock_seconds": 60,
             "body_excerpt_bytes": 100, "max_body_bytes": 10000}
        )
    )  # fmt: skip
    (root / "allow.txt").write_text("127.0.0.1\n")
    return [
        sys.executable, str(SCRIPT), "--catalog", str(root / "catalog.yaml"),
        "--config", str(root / "config.yaml"), "--log", str(root / "log.jsonl"),
        "--allowlist", str(root / "allow.txt"), "--user-agent", "test/0",
    ]  # fmt: skip


def _probed(root: Path) -> dict:
    p = root / "log.jsonl"
    rows = [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []
    return {r["api"]: (r["status"], r["as_of"]) for r in rows if r["event"] == "probe"}


def _env():
    return {k: v for k, v in os.environ.items() if k != "SELDON_NETWORK_ALLOWLIST"}


@pytest.mark.load_sensitive
@pytest.mark.xdist_group("wall_clock")
def test_probe_sigkill_mid_run_then_resume_matches_an_uninterrupted_run(
    tmp_path, server
):
    port = server.server_address[1]
    assert (
        subprocess.run(_workspace(tmp_path / "ref", port), env=_env()).returncode == 0
    )
    reference = _probed(tmp_path / "ref")
    assert len(reference) == N
    assert reference["a0"] == (200, "Data Refreshed October, 2026.")

    _Slow.hits = {}
    cmd = _workspace(tmp_path / "run", port)
    proc = subprocess.Popen(cmd, env=_env(), stdout=subprocess.DEVNULL)
    deadline = time.time() + 30
    while time.time() < deadline and len(_probed(tmp_path / "run")) < 2:
        time.sleep(0.05)
    proc.send_signal(signal.SIGKILL)
    proc.wait()
    before = _probed(tmp_path / "run")
    assert 2 <= len(before) < N, "the kill must land mid-run"
    assert subprocess.run(cmd, env=_env()).returncode == 0
    assert _probed(tmp_path / "run") == reference
    for api in before:  # no completed probe was sent twice
        assert _Slow.hits[f"/{api}"] == 1


@pytest.mark.load_sensitive
@pytest.mark.xdist_group("server_or_port")
def test_an_off_allowlist_probe_is_a_row_not_a_request(tmp_path, server):
    cmd = _workspace(tmp_path / "w", server.server_address[1])
    tmp_path = tmp_path / "w"
    (tmp_path / "allow.txt").write_text("example.gov\n")
    assert subprocess.run(cmd, env=_env(), capture_output=True).returncode == 1
    rows = [json.loads(x) for x in (tmp_path / "log.jsonl").read_text().splitlines()]
    assert all("not on the allowlist" in r["error"] for r in rows)
    assert _Slow.hits == {}


@pytest.mark.load_sensitive
@pytest.mark.xdist_group("server_or_port")
def test_a_superseded_row_is_never_probed_even_on_reprobe(tmp_path, server):
    # HB-59 ADDENDUM-02: MRLC's GeoServer no longer serves CONUS NLCD, and a request for
    # the missing coverage hangs rather than answering; the row stays as the record
    # that it moved, and no later run probes it.
    cmd = _workspace(tmp_path / "w", server.server_address[1])
    cat = tmp_path / "w" / "catalog.yaml"
    apis = yaml.safe_load(cat.read_text())["apis"]
    apis[0]["status"] = "superseded"
    cat.write_text(yaml.safe_dump({"apis": apis}))
    assert subprocess.run(cmd + ["--reprobe"], env=_env()).returncode == 0
    assert set(_probed(tmp_path / "w")) == {f"a{i}" for i in range(1, N)}
    assert "/a0" not in _Slow.hits
