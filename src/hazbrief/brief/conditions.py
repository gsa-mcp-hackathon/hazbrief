"""Each engine's conditions of use, from one table (HB-184 Part C item 7; DN-028
ADDENDUM-10 decision 5): `conditions.yaml`.

The TEVV page's two "Conditions of use" sections (SCICHEM's and SLAB's) are generated
from the table's rows, never written per brief: each row states a condition, what the
evidence shows, the evidence file and the held source it rests on. `resolve` checks a
row against the repository: the file is held, one of its lines holds every `find`
string, and the key is a corpus doc_id (corpus/sources.yaml) or a decision of the
register (`conditions.yaml` `register` and `register_records`; HB-213). A row that does
not resolve is refused (`ConditionsError`), so a page never states a condition its
evidence does not hold.

The form follows held prior art: 40 CFR 51 Appendix W states each preferred model's
regulatory use and accuracy in its summary (ecfr-40-cfr-51-appendix-w-2025 p. 15 #231,
p. 78 #810); ALOHA's user's manual lists the conditions that can produce unreliable
results (epa-aloha-users-manual-2007 p. 28 #174 to #182).
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
CONFIG = Path(__file__).with_name("conditions.yaml")
ENGINES = ("scichem", "slab")
_KEY = re.compile(r"^hazbrief-mcp:HBD-\d+$")


class ConditionsError(RuntimeError):
    """A row of the table does not resolve to a held file, line and key."""


@cache
def load(path: Path = CONFIG) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@cache
def corpus_ids(root: Path = ROOT) -> frozenset[str]:
    """Every doc_id the corpus manifest holds (corpus/sources.yaml)."""
    text = (root / "corpus" / "sources.yaml").read_text(encoding="utf-8")
    return frozenset(re.findall(r"^- doc_id: (\S+)\s*$", text, flags=re.M))


@cache
def decision_ids(root: Path = ROOT) -> frozenset[str]:
    """Every decision id the register holds, projected (`register`, REGISTER.md) or
    pending its next projection (`register_records`, its pending/ directory). The
    projection must be held; the records directory need not be (the public tree ships
    the register's lines its pages cite, not its records; HB-213)."""
    cfg = load()
    text = (root / cfg["register"]).read_text(encoding="utf-8")
    ids = set(re.findall(r"hazbrief-mcp:HBD-\d+", text))
    records = root / cfg["register_records"]
    if records.is_dir():
        for p in records.rglob("*_hazbrief-mcp-hbd-*_accept.yaml"):
            n = p.name.split("hbd-")[1].split("_")[0]
            ids.add(f"hazbrief-mcp:HBD-{int(n)}")
    return frozenset(ids)


def resolve(row: dict, root: Path = ROOT) -> dict:
    """The row with the line of its file that holds every `find` string (`line`, its
    1-based number); refused unless the file, the line and the key are all held."""
    for k in ("engine", "condition", "shows", "file", "find", "key"):
        if not row.get(k):
            raise ConditionsError(f"conditions row lacks {k!r}: {row}")
    if row["engine"] not in ENGINES:
        raise ConditionsError(f"conditions row names engine {row['engine']!r}")
    path = root / row["file"]
    if not path.is_file():
        raise ConditionsError(f"{row['file']}: not held")
    lines = path.read_text(encoding="utf-8").splitlines()
    hit = next(
        (i for i, ln in enumerate(lines, 1) if all(f in ln for f in row["find"])),
        None,
    )
    if hit is None:
        raise ConditionsError(f"{row['file']}: no line holds {row['find']}")
    key = row["key"]
    held = key in decision_ids(root) if _KEY.match(key) else key in corpus_ids(root)
    if not held:
        raise ConditionsError(f"conditions row key {key!r} is not held")
    return {**row, "line": hit}


def rows(engine: str, root: Path = ROOT) -> list[dict]:
    """The engine's rows, in the table's order, each resolved."""
    return [resolve(r, root) for r in load()["rows"] if r["engine"] == engine]
