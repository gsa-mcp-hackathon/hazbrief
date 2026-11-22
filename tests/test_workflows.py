"""HB-96 Part C: the two GitHub workflows, which run only when a person starts them
(HB-85), install what the container installs and hold no more than read access.

Review L3-10: CI installed uv at `version: "latest"` and ran `uv sync` without
`--locked`, while the Dockerfile pins uv by version and digest and installs with
`--locked`; neither
workflow had a `permissions:` block, so the job token took the repository's default.
The prior art is GitHub's documented least-privilege rule for `GITHUB_TOKEN`: declare
`permissions` and grant the job only what it needs (docs.github.com, GitHub Actions
security hardening). Review L4-3: the nightly named one file, so the other `slow` tests
(the paged-form sweep over all 18 scenarios) ran in no workflow.
"""

from __future__ import annotations

import re

import pytest
import yaml

from hazbrief.config import REPO_ROOT

WORKFLOWS = REPO_ROOT / ".github" / "workflows"
NAMES = ("ci.yml", "eval-nightly.yml")
_UV_IMAGE = re.compile(r"^FROM ghcr\.io/astral-sh/uv:(?P<v>[0-9.]+)@sha256:", re.M)


def _load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _triggers(doc: dict) -> dict:
    # YAML 1.1 reads a bare `on` key as the boolean true
    return doc.get("on", doc.get(True))


def _steps(doc: dict) -> list[dict]:
    return [s for job in doc["jobs"].values() for s in job["steps"]]


def _runs(doc: dict) -> list[str]:
    return [s["run"] for s in _steps(doc) if "run" in s]


def dockerfile_uv_version() -> str:
    m = _UV_IMAGE.search((REPO_ROOT / "Dockerfile").read_text(encoding="utf-8"))
    assert m, "the Dockerfile names no pinned uv image"
    return m.group("v")


@pytest.mark.parametrize("name", NAMES)
def test_a_workflow_runs_only_when_a_person_starts_it(name):
    """HB-85: no push, pull request or schedule; this task adds no trigger."""
    assert list(_triggers(_load(name))) == ["workflow_dispatch"]


@pytest.mark.parametrize("name", NAMES)
def test_a_workflow_installs_the_dockerfiles_uv_from_the_lock(name):
    doc = _load(name)
    (setup,) = [s for s in _steps(doc) if s.get("uses", "").startswith("astral-sh/")]
    assert setup["with"]["version"] == dockerfile_uv_version()
    syncs = [r for r in _runs(doc) if r.startswith("uv sync")]
    assert syncs and all("--locked" in r.split() for r in syncs), syncs


@pytest.mark.parametrize("name", NAMES)
def test_a_workflows_token_can_only_read_the_repository(name):
    assert _load(name)["permissions"] == {"contents": "read"}


def test_the_nightly_runs_every_slow_test_not_one_file():
    runs = _runs(_load("eval-nightly.yml"))
    assert "uv run pytest tests/ -m slow -v" in runs, runs
