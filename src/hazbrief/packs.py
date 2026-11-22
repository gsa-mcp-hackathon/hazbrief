"""The runtime loader for the knowledge packs (HB-03; packs/SCHEMA.md).

The server reads reference knowledge (ERG, 49 CFR 172.101, CAMEO, hazard classes, flag
rules, the pack vocabulary) only from these files; nothing is read from Neo4j or Squiddy
at runtime (DN-001 section 4 invariant 3). A pack is refused, never half-used, when:

* its `schema_version` is not one this code knows (`SUPPORTED_SCHEMA_VERSIONS`);
* its `kind` has no model (`hazbrief.models.PACK_MODELS`, or `APP_PACK_MODELS` for the
  application's own packs, which `load_app_pack` reads and the server never loads);
* the sha256 of its canonical `data` is not the `sha256` it carries;
* it does not validate against its model (unknown or missing fields, wrong types).

Canonical form (the bytes the sha256 is taken over): `json.dumps(data,
sort_keys=True, separators=(",", ":"), ensure_ascii=False)` encoded as UTF-8. It follows
RFC 8785's choices for key order and whitespace; it is NOT RFC 8785 for numbers (Python
writes 11.0 where JCS writes 11), which is why the builder and this loader share this
one function.
"""

from __future__ import annotations

import functools
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from hazbrief.models import (
    APP_PACK_MODELS,
    PACK_MODELS,
    CameoPack,
    Cfr172Pack,
    ErgPack,
    FlagRulesPack,
    HazardClassesPack,
    PackEnvelope,
    SuggestedActionsPack,
    VocabularyPack,
)

#: Pack schema versions this loader reads. A pack of any other version is refused.
SUPPORTED_SCHEMA_VERSIONS = (8,)
#: Where the packs live: `packs/` at the repository root, which the container copies to
#: /app/packs beside /app/src (Dockerfile). Every function takes an explicit directory.
DEFAULT_PACKS_DIR = Path(__file__).resolve().parents[2] / "packs"


class PackError(RuntimeError):
    """A pack that must not be used, with the reason."""


def canonical_json(obj) -> bytes:
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def data_sha256(data) -> str:
    return hashlib.sha256(canonical_json(data)).hexdigest()


def load_pack(path: Path) -> PackEnvelope:
    """Read, verify and type one pack file. Raises PackError with the reason."""
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise PackError(f"{path}: pack file not found") from None
    except json.JSONDecodeError as exc:
        raise PackError(f"{path}: not valid JSON ({exc})") from None
    if not isinstance(raw, dict):
        raise PackError(f"{path}: a pack is a JSON object")
    version = raw.get("schema_version")
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise PackError(
            f"{path}: schema version {version!r} is not one this loader knows "
            f"{SUPPORTED_SCHEMA_VERSIONS}"
        )
    kind = raw.get("kind")
    model = PACK_MODELS.get(kind) or APP_PACK_MODELS.get(kind)
    if model is None:
        raise PackError(f"{path}: unknown pack kind {kind!r}")
    if "data" not in raw or "sha256" not in raw:
        raise PackError(f"{path}: a pack carries `data` and its `sha256`")
    actual = data_sha256(raw["data"])
    if actual != raw["sha256"]:
        raise PackError(
            f"{path}: sha256 of data is {actual}, the pack says {raw['sha256']}; "
            "the pack was altered after it was built"
        )
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        raise PackError(f"{path}: does not match the {kind} schema: {exc}") from None


@dataclass(frozen=True)
class PackSet:
    erg: ErgPack
    cfr172: Cfr172Pack
    cameo: CameoPack
    hazard_classes: HazardClassesPack
    flag_rules: FlagRulesPack
    vocabulary: VocabularyPack
    #: HB-207: the suggested actions to consider, read by the `decision_support` prompt
    suggested_actions: SuggestedActionsPack


def load_packs(packs_dir: Path = DEFAULT_PACKS_DIR) -> PackSet:
    """Every pack kind, each from `<packs_dir>/<kind>.json`. Raises PackError on the
    first pack that is missing or refused."""
    packs_dir = Path(packs_dir)
    return PackSet(**{k: load_pack(packs_dir / f"{k}.json") for k in PACK_MODELS})


@functools.lru_cache(maxsize=1)
def default_packs() -> PackSet:
    """The packs the server ships, loaded and verified once per process. The tools call
    it at registration, so a missing or altered pack stops the server at startup."""
    return load_packs(DEFAULT_PACKS_DIR)


@functools.lru_cache(maxsize=None)
def load_app_pack(kind: str, packs_dir: Path = DEFAULT_PACKS_DIR) -> PackEnvelope:
    """One of the application's packs (`hazbrief.models.APP_PACK_MODELS`: the
    first-order puff's materials, sigma curves and release scenarios, HB-66), read and
    verified like a server pack. The server never loads these, so they are not part of
    `PackSet` and a missing one stops only the channel that reads it."""
    if kind not in APP_PACK_MODELS:
        raise PackError(f"{kind!r} is not an application pack kind")
    pack = load_pack(Path(packs_dir) / f"{kind}.json")
    if pack.kind != kind:
        raise PackError(f"{packs_dir}/{kind}.json holds a {pack.kind} pack")
    return pack
