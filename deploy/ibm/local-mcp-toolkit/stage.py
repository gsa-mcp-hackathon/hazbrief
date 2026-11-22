#!/usr/bin/env python
"""Stage the local toolkit's `package_root` in the container image's layout (HB-35).

    uv run python deploy/ibm/local-mcp-toolkit/stage.py <dest>

`config.REPO_ROOT` is `parents[2]` of `src/hazbrief/config.py`, so the package is staged
at `<dest>/src/hazbrief/` and `REPO_ROOT` resolves to `<dest>`, as it resolves to `/app`
in the image. Beside it goes every runtime path the code names
(`scripts/runtime_paths.py`, the discovery the image's test uses), at its own
repository-relative place: the packs, the stylebook, the LODES and CMS caches. Then
`server.py`, and the root `requirements.txt`, which is `uv export` of `uv.lock`
(`tests/test_requirements.py`), so Orchestrate installs the versions the image runs.
What `.dockerignore` keeps out of the image's build context is kept out here too
(`packs/build/`, 34 MB of the pack build's local artifacts; byte-code caches). `<dest>`
is replaced if it exists.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from fnmatch import fnmatch
from pathlib import Path

KIT = Path(__file__).resolve().parent
REPO = KIT.parents[2]
PACKAGE = "hazbrief"


def dockerignore() -> list[str]:
    """The image's exclusions, as `test_container_image.py` reads them."""
    return [
        ln.strip().rstrip("/")
        for ln in (REPO / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.startswith("#")
    ]


def excluded(rel: str, patterns: list[str]) -> bool:
    """`rel` (repository-relative, POSIX) is one `.dockerignore` keeps out. Docker
    matches each pattern against the path from the context root, and a match on a
    directory keeps out everything under it (docs.docker.com, "build context",
    .dockerignore files)."""
    parts = rel.split("/")
    return any(
        fnmatch("/".join(parts[:i]), p)
        for p in patterns
        for i in range(1, len(parts) + 1)
    )


#: Byte-code caches: never shipped, wherever they sit (the template's rule).
_CACHES = shutil.ignore_patterns("__pycache__", "*.pyc")


def _ignore(patterns: list[str]):
    def ignore(directory: str, names: list[str]) -> set[str]:
        base = Path(directory).resolve().relative_to(REPO).as_posix()
        kept_out = {n for n in names if excluded(f"{base}/{n}", patterns)}
        return kept_out | set(_CACHES(directory, names))

    return ignore


def _runtime_paths():
    spec = importlib.util.spec_from_file_location(
        "runtime_paths", REPO / "scripts" / "runtime_paths.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def stage(dest: Path) -> list[str]:
    """Build the tree at `dest`; return the repository-relative paths staged."""
    rels = _runtime_paths().shipped()
    patterns = dockerignore()
    ignore = _ignore(patterns)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    shutil.copytree(REPO / "src" / PACKAGE, dest / "src" / PACKAGE, ignore=ignore)
    for rel in rels:
        src = REPO / rel
        if not src.exists():
            raise SystemExit(
                f"FATAL: the runtime reads {rel}, which is not in this checkout "
                f"({src}); build or fetch it before staging"
            )
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, out, ignore=ignore)
        else:
            shutil.copy2(src, out)
    shutil.copy2(KIT / "server.py", dest / "server.py")
    shutil.copy2(REPO / "requirements.txt", dest / "requirements.txt")
    return [f"src/{PACKAGE}", *rels]


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: stage.py <dest>", file=sys.stderr)
        return 2
    dest = Path(argv[0]).resolve()
    for rel in stage(dest):
        print(f"  staged {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
