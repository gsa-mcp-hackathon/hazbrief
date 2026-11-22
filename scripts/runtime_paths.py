"""The paths under the repository root that the running server reads (HB-34, HB-35).

Not listed by hand: every `Path` a `hazbrief` module holds at module level, and every
`Path` field of `Settings`, that lies under `REPO_ROOT` and outside `src/`. Whatever
ships the server ships each one at the same place beside `src/`, or exempts it for a
stated reason in `EXEMPT`. Two shippers read this: the container image
(`test_container_image.py` holds the Dockerfile's COPY lines to it) and the IBM
local toolkit (`deploy/ibm/local-mcp-toolkit/stage.py` stages from it). A new runtime
path is found here once and fails whichever shipper leaves it out.
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

import hazbrief
from hazbrief.config import REPO_ROOT, Settings

#: The application (DN-010 D2, DN-011 s3): the evidence store, the brief and the
#: console dispatcher. The server never imports them (tests/test_evidence_store.py), and
#: the image stays the server alone, so their paths are not the runtime's.
APPLICATION = ("hazbrief.evidence", "hazbrief.brief", "hazbrief.command")

#: Paths under the root the runtime names but no shipped tree may hold, and why.
EXEMPT = {
    ".": "the root itself; it is the WORKDIR",
    ".env": "the project secrets file; never in an image (DN-004; .dockerignore)",
    "fixtures/exchanges": (
        "recorded upstream exchanges, read only when HAZBRIEF_HTTP_MODE is replay or "
        "record; the image runs the default, live (config.py), and sets no mode"
    ),
}


def runtime_paths() -> dict[str, str]:
    """Repository-relative path -> where the code names it."""
    found: dict[str, str] = {}
    src = REPO_ROOT / "src"
    for info in pkgutil.walk_packages(hazbrief.__path__, "hazbrief."):
        if info.name.startswith(APPLICATION):
            continue
        module = importlib.import_module(info.name)
        for name, value in vars(module).items():
            if isinstance(value, Path) and _outside_src(value, src):
                found.setdefault(_rel(value), f"{info.name}.{name}")
    for name, spec in Settings.model_fields.items():
        if isinstance(spec.default, Path) and _outside_src(spec.default, src):
            found.setdefault(_rel(spec.default), f"Settings.{name}")
    return found


def shipped() -> list[str]:
    """The runtime paths a shipped tree holds: every one not exempt."""
    return sorted(rel for rel in runtime_paths() if rel not in EXEMPT)


def _outside_src(path: Path, src: Path) -> bool:
    path = path.resolve()
    return path.is_relative_to(REPO_ROOT) and not path.is_relative_to(src)


def _rel(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT).as_posix()
