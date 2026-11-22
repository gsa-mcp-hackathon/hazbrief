"""HB-34: `requirements.txt` holds every runtime dependency, at the locked version.

HB-26 (ARCHITECTURE section 10, D-10) found `requirements.txt` claimed to be "kept in
sync with pyproject.toml" and omitted `shapely`, which `geo.py` imports, so a
buildpack host that installs from it (cloud.gov, `manifest.yaml`) would fail on the
first population query. Kept in sync by hand, it drifted.

So the file is generated from the lockfile, as uv documents
(`uv export --no-dev`, docs.astral.sh/uv/concepts/projects/export/): the buildpack
host gets the same versions the container installs from `uv.lock`. One test asserts
the file is that export; the other, that every third-party module the package
imports resolves to a distribution the file names, so a new import with no
dependency fails here.
"""

from __future__ import annotations

import ast
import importlib.util
import re
import shutil
import subprocess
import sys
from collections.abc import Iterator
from importlib.metadata import packages_distributions
from pathlib import Path

import pytest

from hazbrief.config import REPO_ROOT

REQUIREMENTS = REPO_ROOT / "requirements.txt"
PACKAGE = REPO_ROOT / "src" / "hazbrief"
#: The command that writes `requirements.txt`; its header names it.
EXPORT = ["uv", "export", "--frozen", "--no-dev", "--no-hashes", "--no-emit-project"]

_REQ = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;]+)")


def _norm(name: str) -> str:
    """PEP 503 normalised name."""
    return re.sub(r"[-_.]+", "-", name).lower()


def requirement_pins(text: str) -> dict[str, str]:
    pins = {}
    for line in text.splitlines():
        m = _REQ.match(line.strip())
        if m:
            pins[_norm(m.group(1))] = m.group(2)
    return pins


def imported_top_levels() -> dict[str, str]:
    """Top-level module -> the first file that imports it, over the package."""
    found: dict[str, str] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            for n in names:
                found.setdefault(n.split(".")[0], str(path.relative_to(REPO_ROOT)))
    return found


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not on PATH")
def test_requirements_txt_is_the_lockfile_export():
    out = subprocess.run(
        EXPORT, cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout
    regenerate = " ".join(EXPORT) + " -o requirements.txt"
    have = requirement_pins(REQUIREMENTS.read_text(encoding="utf-8"))
    assert have == requirement_pins(out), f"requirements.txt is stale: {regenerate}"


def test_every_runtime_import_resolves_to_a_listed_distribution():
    pins = requirement_pins(REQUIREMENTS.read_text(encoding="utf-8"))
    dists = packages_distributions()
    missing = []
    for module, where in sorted(imported_top_levels().items()):
        if module in sys.stdlib_module_names or module in ("hazbrief", "__future__"):
            continue
        names = [_norm(d) for d in dists.get(module, [])]
        if not names:
            missing.append(f"{module} ({where}): no installed distribution provides it")
        elif not any(n in pins for n in names):
            missing.append(f"{module} ({where}): {names} not in requirements.txt")
    assert not missing, "\n".join(missing)


def test_the_check_reads_a_missing_dependency():
    """The import check can fail: shapely, absent from the file, is caught."""
    pins = requirement_pins("httpx==0.28.1\n    # via hazbrief\n")
    assert "httpx" in pins and "shapely" not in pins


#: The application's modules, which the server never imports (ARCHITECTURE section 11),
#: as `scripts/runtime_paths.py` names them: one list, loaded the way
#: test_container_image.py loads it (HB-96 ADDENDUM-01 section 1).
_spec = importlib.util.spec_from_file_location(
    "runtime_paths", REPO_ROOT / "scripts" / "runtime_paths.py"
)
_rp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_rp)
APPLICATION: tuple[str, ...] = _rp.APPLICATION

#: Model SDKs by import name (review L1-4's list, and Google's current `google.genai`)
#: and by distribution. DN-001 section 4 invariant 2: the model never decides what is
#: alarming, so no server module reaches one.
MODEL_SDK_IMPORTS = (
    "anthropic",
    "openai",
    "google.generativeai",
    "google.genai",
    "mistralai",
    "cohere",
    "litellm",
    "ollama",
)
MODEL_SDK_DISTRIBUTIONS = (
    "anthropic",
    "openai",
    "google-generativeai",
    "google-genai",
    "mistralai",
    "cohere",
    "litellm",
    "ollama",
)
#: MCP sampling, the server asking the client's model for a completion: FastMCP's
#: `Context.sample` and the MCP SDK's `ServerSession.create_message`.
SAMPLING_CALLS = ("sample", "create_message")


def _module(path: Path, package: Path) -> str:
    parts = list(path.relative_to(package.parent).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def server_modules(package: Path = PACKAGE) -> Iterator[tuple[Path, ast.AST]]:
    """Every module under `package` that is not the application's, parsed."""
    for path in sorted(package.rglob("*.py")):
        if _module(path, package).startswith(APPLICATION):
            continue
        yield path, ast.parse(path.read_text(encoding="utf-8"))


def server_imports(package: Path = PACKAGE) -> Iterator[tuple[Path, str]]:
    """(path, dotted name) for every absolute import of every server module: `import
    a.b` gives `a.b`; `from a import b` gives `a` and `a.b`."""
    for path, tree in server_modules(package):
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    yield path, a.name
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                yield path, node.module
                for a in node.names:
                    yield path, f"{node.module}.{a.name}"


def _is(name: str, modules) -> bool:
    return any(name == m or name.startswith(m + ".") for m in modules)


def _dist(requirement: str) -> str:
    return _norm(re.split(r"[<>=!~;\[ ]", requirement, maxsplit=1)[0])


def test_numpy_is_the_applications_extra_and_no_server_module_imports_it():
    """HB-95 (review L1-10): numpy is declared for the `hazbrief brief` application as
    the `brief` extra, not among the server's dependencies, because no server module
    imports it. shapely installs it for its own use, so the server's environment still
    holds it. A server module that starts importing numpy fails here."""
    import tomllib

    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    project = tomllib.loads(text)["project"]
    runtime = {_dist(d) for d in project["dependencies"]}
    extra = {_dist(d) for d in project["optional-dependencies"]["brief"]}
    assert "numpy" not in runtime and "numpy" in extra
    server = sorted(
        {
            f"{path.relative_to(REPO_ROOT)}: {name}"
            for path, name in server_imports()
            if _is(name, ("numpy",))
        }
    )
    assert not server, server


def model_sdk_uses(package: Path = PACKAGE) -> list[str]:
    """Every server module's model SDK import and MCP sampling call."""
    found = {
        f"{path.name}: import {name}"
        for path, name in server_imports(package)
        if _is(name, MODEL_SDK_IMPORTS)
    }
    for path, tree in server_modules(package):
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in SAMPLING_CALLS
            ):
                found.add(f"{path.name}:{node.lineno}: .{node.func.attr}(...)")
    return sorted(found)


def model_sdk_pins(text: str) -> list[str]:
    pins = requirement_pins(text)
    return sorted(d for d in MODEL_SDK_DISTRIBUTIONS if _norm(d) in pins)


def test_no_server_module_reaches_a_model_and_no_runtime_pin_is_a_model_sdk():
    """REQUIREMENTS_TRACE I-3 (DN-001 section 4 invariant 2), over every server module,
    not two (review L1-4, L4-6): no model SDK import, no MCP sampling call, and no
    model SDK among the runtime pins a buildpack host installs."""
    walked = {str(p.relative_to(PACKAGE)) for p, _ in server_modules()}
    # the walk read the server (36 modules at HB-96), the two the old regex read among
    # them, and none of the application
    assert {"flags.py", "ics201.py", "tools/build_ics_201.py"} <= walked
    assert not [w for w in walked if w.startswith(("brief/", "evidence/", "command"))]
    assert model_sdk_uses() == []
    assert model_sdk_pins(REQUIREMENTS.read_text(encoding="utf-8")) == []


def test_the_model_check_catches_a_seeded_import_a_sampling_call_and_a_pin(tmp_path):
    """The check can fail: a server module that imports an SDK or samples the client's
    model, and a requirements text that pins one, are each caught; the same module in
    an application package is not the server's."""
    pkg = tmp_path / "hazbrief"
    (pkg / "tools").mkdir(parents=True)
    (pkg / "brief").mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "tools" / "seeded.py").write_text(
        "import anthropic\nfrom google import genai\n", encoding="utf-8"
    )
    (pkg / "flags_seeded.py").write_text(
        "async def f(ctx):\n    return await ctx.sample('is this alarming?')\n",
        encoding="utf-8",
    )
    (pkg / "brief" / "app_side.py").write_text("import openai\n", encoding="utf-8")
    assert model_sdk_uses(pkg) == [
        "flags_seeded.py:2: .sample(...)",
        "seeded.py: import anthropic",
        "seeded.py: import google.genai",
    ]
    pinned = "httpx==0.28.1\nopenai==1.50.0\n    # via hazbrief\n"
    assert model_sdk_pins(pinned) == ["openai"]
