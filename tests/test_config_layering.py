"""DN-004: settings layer the project `.env` over the operator's master secrets file.

Each case imports `hazbrief.config` in a fresh interpreter with its own HOME, working
directory and environment, from a copy of the package placed under a temporary
repository root (`<tmp>/proj/src/hazbrief`, first on PYTHONPATH). The project `.env`
is that root's (HB-08 ADDENDUM-00), so the test exercises the import-time `model_config`
the server actually uses, and no real master file, `.env` or exported key on the test
machine can leak in.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

_PROBE = (
    "import json; from hazbrief.config import settings; "
    "print(json.dumps({'census_api_key': settings.census_api_key, "
    "'mcp_port': settings.mcp_port}))"
)
#: Variables a case may set; anything else from the parent environment is dropped.
_KEEP = ("PATH", "SYSTEMROOT")


#: The package under test, copied beneath each case's temporary repository root.
_PACKAGE = Path(__file__).resolve().parents[1] / "src" / "hazbrief"


def _probe(
    tmp_path: Path,
    *,
    master: str | None = None,
    project: str | None = None,
    env: dict | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess:
    """Run `_PROBE` with HOME=<tmp>/home and the package at <tmp>/proj/src/hazbrief, so
    <tmp>/proj is the repository root. `master` is written to the default master path,
    `project` to `<tmp>/proj/.env`. The working directory is the root unless `cwd`
    names another."""
    home, proj = tmp_path / "home", tmp_path / "proj"
    if not (proj / "src" / "hazbrief").is_dir():
        shutil.copytree(
            _PACKAGE,
            proj / "src" / "hazbrief",
            ignore=shutil.ignore_patterns("__pycache__"),
        )
    if master is not None:
        (home / ".secrets").mkdir(parents=True, exist_ok=True)
        (home / ".secrets" / "master.env").write_text(master, encoding="utf-8")
    if project is not None:
        (proj / ".env").write_text(project, encoding="utf-8")
    child = {k: os.environ[k] for k in _KEEP if k in os.environ}
    child["HOME"] = str(home)
    child["PYTHONPATH"] = str(proj / "src")
    child.update(env or {})
    return subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=cwd or proj,
        env=child,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _loaded(r: subprocess.CompletedProcess) -> dict:
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_project_env_wins_over_master(tmp_path):
    r = _probe(
        tmp_path,
        master="CENSUS_API_KEY=from-master\n",
        project="CENSUS_API_KEY=from-project\n",
    )
    assert _loaded(r)["census_api_key"] == "from-project"


def test_master_alone_loads_and_its_other_keys_are_ignored(tmp_path):
    """The master holds every key the operator owns (DN-004 section 1); keys this
    project does not read must not break it."""
    r = _probe(
        tmp_path,
        master="CENSUS_API_KEY=from-master\nNEO4J_WINTERMUTE_URI=bolt://x:7687\n",
    )
    assert _loaded(r)["census_api_key"] == "from-master"


def test_neither_file_constructs_with_defaults(tmp_path):
    r = _probe(tmp_path)
    assert _loaded(r) == {"census_api_key": "", "mcp_port": 8000}


def test_master_env_variable_redirects_the_master_path(tmp_path):
    elsewhere = tmp_path / "ci" / "secrets.env"
    elsewhere.parent.mkdir(parents=True)
    elsewhere.write_text("CENSUS_API_KEY=from-redirect\n", encoding="utf-8")
    r = _probe(
        tmp_path,
        master="CENSUS_API_KEY=from-default-path\n",
        env={"HAZBRIEF_MASTER_ENV": str(elsewhere)},
    )
    assert _loaded(r)["census_api_key"] == "from-redirect"


def test_redirect_to_a_missing_file_fails_naming_the_variable(tmp_path):
    """An explicit override that points nowhere is a misconfiguration, not an absent
    master: it fails at startup (standards section 4)."""
    r = _probe(tmp_path, env={"HAZBRIEF_MASTER_ENV": str(tmp_path / "nope.env")})
    assert r.returncode != 0
    assert "HAZBRIEF_MASTER_ENV" in r.stderr


def test_a_blank_project_line_does_not_erase_the_master_value(tmp_path):
    """`.env` copied from `.env.example` carries `CENSUS_API_KEY=` with no value; it
    must not override the master's key (env_ignore_empty)."""
    r = _probe(
        tmp_path,
        master="CENSUS_API_KEY=from-master\n",
        project="CENSUS_API_KEY=\nMCP_PORT=\n",
    )
    assert _loaded(r) == {"census_api_key": "from-master", "mcp_port": 8000}


def test_an_exported_variable_wins_over_both_files(tmp_path):
    """pydantic-settings: "environment variables will always take priority over values
    loaded from a dotenv file"; a container's --env-file and a platform secret store
    arrive this way."""
    r = _probe(
        tmp_path,
        master="CENSUS_API_KEY=from-master\n",
        project="CENSUS_API_KEY=from-project\n",
        env={"CENSUS_API_KEY": "from-environment"},
    )
    assert _loaded(r)["census_api_key"] == "from-environment"


def test_project_env_at_the_root_wins_when_launched_from_elsewhere(tmp_path):
    """HB-08 ADDENDUM-00: an MCP client (Claude Desktop, MCP Inspector) launches the
    server from another directory; the project `.env` is still the repository root's,
    and a `.env` in the launch directory is not read."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / ".env").write_text("CENSUS_API_KEY=from-cwd\n", encoding="utf-8")
    r = _probe(
        tmp_path,
        master="CENSUS_API_KEY=from-master\n",
        project="CENSUS_API_KEY=from-root\n",
        cwd=elsewhere,
    )
    assert _loaded(r)["census_api_key"] == "from-root"
