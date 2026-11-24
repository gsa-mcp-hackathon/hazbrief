"""Where a served live brief keeps the engine records it makes (HB-207 item 1).

The modelled layers' engines keep one record per request, by its hash, under
`fixtures/evidence/` (SCICHEM's runs and frames, the two-engine lines run, SLAB's runs):
committed records a replay reads, and a recording task commits. A served live brief
makes records too, for requests no task recorded, and before HB-207 it wrote them there
as well, so every live run left untracked files in a tracked directory (HB-207 item 5 of
the known items; HB-137's rule: an operator tool's runtime state is local).

`set_root(path)` names the live root for this process (`hazbrief brief --serve`, live
or replaying; `cli.py`). With it set, a record is read from the repository when it is
committed there, else from the live root, and a new one is written under the live root,
at the same relative path (`state/entry/records/fixtures/evidence/...`, ignored by git).
Unset (a written brief, a recording script, the tests), every path is the repository's,
as before.
"""

from __future__ import annotations

from pathlib import Path

from hazbrief.config import REPO_ROOT

#: the live root of this process, or None (`set_root`)
_LIVE: Path | None = None


def set_root(path: Path | None) -> None:
    """Name the live root (None: no live root, every path the repository's)."""
    global _LIVE
    _LIVE = Path(path) if path is not None else None


def live_root() -> Path | None:
    return _LIVE


def resolve(path: Path) -> Path:
    """The path to read or write for `path`, a record under the repository: itself when
    no live root is set, when it is not under the repository, or when it exists (a
    committed record); otherwise the same relative path under the live root."""
    path = Path(path)
    if _LIVE is None or path.exists():
        return path
    try:
        rel = path.resolve().relative_to(REPO_ROOT.resolve())
    except ValueError:
        return path
    return _LIVE / rel
