"""The text files the server ships beside the package: the commander stylebook (HB-02).

They live in `docs/stylebook/` at the repository root, one source of truth that the
resources, the ICS 201 prompt and `stylecheck` all read. The package resolves them
relative to its own location (`src/hazbrief/` -> repository root), which holds in every
way the server runs: `uv run` from a checkout, the cloud.gov buildpack (which runs the
checkout), and the container image, whose PYTHONPATH puts `/app/src` first and whose
Dockerfile copies `docs/stylebook` to `/app`.
"""

from __future__ import annotations

from pathlib import Path

STYLEBOOK_DIR = Path(__file__).resolve().parents[2] / "docs" / "stylebook"

COMMANDER_STYLEBOOK = STYLEBOOK_DIR / "COMMANDER_STYLEBOOK.md"
VOCABULARY = STYLEBOOK_DIR / "VOCABULARY.yaml"
STYLECHECK_CONFIG = STYLEBOOK_DIR / "STYLECHECK.yaml"
ATTRIBUTION = STYLEBOOK_DIR / "ATTRIBUTION.md"


def read_shipped(path: Path) -> str:
    """The file's text, or a FileNotFoundError that says where it was expected and why.

    A missing stylebook file is a packaging defect, never a condition to run without:
    the prompt and resources would serve nothing and the checker would check nothing.
    """
    if not path.is_file():
        raise FileNotFoundError(
            f"{path} is missing. The server ships docs/stylebook/ beside src/; a "
            "container image needs `COPY docs/stylebook ./docs/stylebook` (Dockerfile)."
        )
    return path.read_text(encoding="utf-8")
