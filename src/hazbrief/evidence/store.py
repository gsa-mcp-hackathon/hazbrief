"""The evidence store: content-addressed, append-only, PROV records (DN-010 D1 to D3,
D6).

An evidence entity is a response body, stored once under the sha256 of its canonical
form: `<store>/<sha[:2]>/<sha>.json` for a JSON body, `<sha>.bin` for bytes (the
TIGERweb roads image, which DN-010 D2's `.json` did not foresee). Each activity that
produced it is a record beside it, `<sha>.<activity id>.prov.json`: a second call that
returns the same bytes is a second record pointing at the same entity, so the record
name carries its activity id (D2's "a second record for the same entity"). Nothing is
rewritten. Writing an entity that exists is a no-op that returns its hash; writing a
record that exists (same activity id) is the same.

The canonical form is the repository's one: `hazbrief.packs.canonical_json` (RFC 8785
key order, UTF-8, no whitespace; packs/SCHEMA.md records its one departure, number
formatting). The manifest is RO-Crate 1.1 (`write_crate_manifest`): every entity a data
entity, every activity a `CreateAction` (the Process Run Crate's mapping of a PROV
activity) whose `result` is the entity.

This module is the application's, never the server's (D2, D7): no server module imports
it (tests/test_evidence_store.py).
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from hazbrief.config import REPO_ROOT
from hazbrief.packs import canonical_json

CONFIG_FILE = Path(__file__).with_name("evidence.yaml")
RECORD_VERSION = 1
ENTITY_SUFFIX = {"json": ".json", "bytes": ".bin"}
PROV_SUFFIX = ".prov.json"


@cache
def config() -> dict:
    """`evidence.yaml`, every key required (a missing one is a broken install, not a
    default)."""
    cfg = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8"))
    need = {
        "store_dir",
        "store_env",
        "catalog",
        "schema",
        "seed_exchanges_dir",
        "seed_store_dir",
        "seed_calls_store_dir",
        "seed_calls_scenario",
        "seed_briefs_store_dir",
        "crate_manifest",
        "crate_context",
        "crate_conforms_to",
        "server_entry",
        "call_timeout_s",
    }
    missing = sorted(need - set(cfg or {}))
    if missing:
        raise RuntimeError(f"{CONFIG_FILE} is missing {missing}")
    return cfg


def repo_path(key: str) -> Path:
    """A path `evidence.yaml` names, resolved against the repository root."""
    return REPO_ROOT / config()[key]


def default_store_dir() -> Path:
    """The store root: `HAZBRIEF_EVIDENCE_STORE` if set, else `evidence.yaml`
    `store_dir`."""
    override = os.environ.get(config()["store_env"])
    return Path(override) if override else repo_path("store_dir")


# ── hashing ───────────────────────────────────────────────────────────────────────────


def canonical_hash(body: Any) -> str:
    """sha256 of the canonical JSON of `body`; for `bytes`, of the bytes themselves."""
    return hashlib.sha256(_entity_bytes(body)).hexdigest()


def _entity_bytes(body: Any) -> bytes:
    return body if isinstance(body, bytes) else canonical_json(body)


def activity_id(activity: dict) -> str:
    """sha256 of the canonical activity, without its `id`."""
    return hashlib.sha256(
        canonical_json({k: v for k, v in activity.items() if k != "id"})
    ).hexdigest()


def utc_now() -> str:
    """UTC, ISO 8601, microseconds: two calls a millisecond apart are two activities."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_time(s: str) -> datetime:
    """An ISO 8601 instant (`Z` or an offset) as an aware datetime."""
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# ── the predicate HB-40's label reads ─────────────────────────────────────────────────


def is_stale(record: dict, now: datetime) -> bool:
    """DN-010 D4: stale exactly when `now - as_of` exceeds `horizon_s`. A record with no
    horizon (every source it read is `computed`) never goes stale."""
    horizon = record["horizon_s"]
    if horizon is None:
        return False
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return (now - parse_time(record["as_of"])).total_seconds() > horizon


# ── writing and reading ───────────────────────────────────────────────────────────────


def _atomic_write(path: Path, data: bytes) -> None:
    """Temporary file, fsync, rename; never a torn file (constitution 15.1)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def entity_path(store: Path, sha: str, encoding: str) -> Path:
    return store / sha[:2] / f"{sha}{ENTITY_SUFFIX[encoding]}"


def record_path(store: Path, sha: str, act_id: str) -> Path:
    return store / sha[:2] / f"{sha}.{act_id}{PROV_SUFFIX}"


#: The settings that hold a credential (config.py; SECURITY section 3).
SECRET_SETTINGS = ("census_api_key",)


def configured_secrets() -> list[str]:
    """The operator's configured key values, as the server's own settings read them."""
    from hazbrief.config import settings

    return [v for v in (getattr(settings, n) for n in SECRET_SETTINGS) if v]


def _secret_forms(value: str) -> set[bytes]:
    """A secret as given and as JSON writes it inside a string: the blobs are canonical
    JSON and the record file is `json.dumps`, where a `"` or `\\` in the value is
    escaped, which a raw substring match misses (review L3-11; the exchange recorder
    compares the same forms, `hazbrief.utils._write_exchange`, since HB-96)."""
    return {
        value.encode("utf-8"),
        canonical_json(value)[1:-1],
        json.dumps(value, ensure_ascii=False)[1:-1].encode("utf-8"),
    }


def _refuse_secrets(blobs: list[bytes], secrets: list[str]) -> None:
    for value in {s for s in secrets if s}:
        if any(f in b for f in _secret_forms(value) for b in blobs):
            raise RuntimeError(
                "refusing to write an evidence record: a configured secret is in it"
            )


def write_entity(store: Path, body: Any) -> tuple[str, dict, bool]:
    """Store `body` once. Returns (sha256, the record's `entity` block, newly
    written)."""
    data = _entity_bytes(body)
    sha = hashlib.sha256(data).hexdigest()
    encoding = "bytes" if isinstance(body, bytes) else "json"
    path = entity_path(store, sha, encoding)
    new = not path.is_file()
    if new:
        _atomic_write(path, data)
    return sha, {"sha256": sha, "bytes": len(data), "encoding": encoding}, new


def write_record(
    store: Path,
    body: Any,
    *,
    activity: dict,
    server: dict,
    source: list[dict],
    provenance_class: str,
    as_of: str,
    as_of_basis: str,
    horizon_s: int | None,
    horizon_source: str | None,
    media_type: str = "application/json",
    used: list[str] | None = None,
    was_revision_of: str | None = None,
    secrets: list[str] | None = None,
) -> tuple[str, dict]:
    """Write the entity (once) and this activity's record. Returns (entity sha256,
    record).

    `activity` carries type, name, params and the two times; its id is computed here. A
    record whose activity id is already stored is not written again (append-only).

    A record or entity in which a configured secret appears is refused before anything
    is written, as the exchange recorder refuses one (`hazbrief.utils._write_exchange`,
    SECURITY section 3). The secrets are the operator's configured keys and any
    `secrets` the caller adds (the recording client adds the environment it hands the
    server)."""
    if provenance_class == "narrated_by_model":
        raise ValueError("a narrated value is never a store entry (DN-010 D5)")
    _refuse_secrets(
        [_entity_bytes(body), canonical_json(activity), canonical_json(source)],
        (secrets or []) + configured_secrets(),
    )
    sha, entity, _ = write_entity(store, body)
    act = {**activity}
    act["id"] = activity_id(act)
    record = {
        "record_version": RECORD_VERSION,
        "entity": {**entity, "media_type": media_type},
        "activity": act,
        "agent": {"server": server, "source": source},
        "provenance_class": provenance_class,
        "as_of": as_of,
        "as_of_basis": as_of_basis,
        "horizon_s": horizon_s,
        "horizon_source": horizon_source,
        "used": sorted(set(used or [])),
        "wasRevisionOf": was_revision_of,
    }
    path = record_path(store, sha, act["id"])
    if not path.is_file():
        _atomic_write(
            path,
            (
                json.dumps(record, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
            ).encode(),
        )
    return sha, record


def read_entity(store: Path, sha: str) -> Any:
    """The body stored under `sha`: parsed JSON, or bytes."""
    for encoding in ENTITY_SUFFIX:
        path = entity_path(store, sha, encoding)
        if path.is_file():
            data = path.read_bytes()
            return json.loads(data) if encoding == "json" else data
    raise FileNotFoundError(f"no entity {sha} in {store}")


def read_record(store: Path, sha: str) -> list[dict]:
    """Every record of the entity `sha`, oldest activity first (one entity, many
    calls)."""
    paths = sorted((store / sha[:2]).glob(f"{sha}.*{PROV_SUFFIX}"))
    if not paths:
        raise FileNotFoundError(f"no record for entity {sha} in {store}")
    records = [json.loads(p.read_text(encoding="utf-8")) for p in paths]
    return sorted(
        records, key=lambda r: (r["activity"]["endedAtTime"], r["activity"]["id"])
    )


def record_by(store: Path, sha: str, by: str | None = None) -> dict:
    """The newest record of entity `sha` whose activity ended no later than `by` (an
    ISO time), else the newest of all. A call's `used` names entities, and a body two
    exchanges share (an empty query result) is one entity with several records; the
    record a call read can only be one made before the call, so a reader of `used`
    passes the citing call's start and a later exchange with the same body never
    relabels it (HB-49)."""
    records = read_record(store, sha)
    if by is not None:
        t = parse_time(by)
        before = [r for r in records if parse_time(r["activity"]["endedAtTime"]) <= t]
        if before:
            return before[-1]
    return records[-1]


def all_records(store: Path) -> list[dict]:
    """Every record in the store, in entity then activity order."""
    out = []
    for p in sorted(store.glob(f"??/*{PROV_SUFFIX}")):
        out.append(json.loads(p.read_text(encoding="utf-8")))
    return out


def records_for(
    store: Path, name: str, params: dict, used: list[str] | None = None
) -> list[dict]:
    """The records of every activity named `name` (a tool, or `GET <api>`) with these
    parameters, compared in canonical form; oldest first.

    With `used`, only the records whose `used` names every one of those entities: a held
    call is keyed by `(tool, params, used)` (HB-99). Two scenarios whose footprints have
    the same shape but are not the same footprint (UN1746 spilled on land and in water)
    hand a reader tool identical parameters; keyed by the parameters alone they held one
    record, and the second scenario's brief cited the first one's footprint. A record's
    `used` may name more than the caller passes (the upstream exchanges a live recording
    adds, `assemble`'s `used_for`), so the match is "names at least these"."""
    want = canonical_json(params)
    need = set(used or [])
    hits = [
        r
        for r in all_records(store)
        if r["activity"]["name"] == name
        and canonical_json(r["activity"]["params"]) == want
        and need <= set(r["used"])
    ]
    return sorted(
        hits, key=lambda r: (r["activity"]["endedAtTime"], r["activity"]["id"])
    )


# ── the RO-Crate manifest (DN-010 D6) ─────────────────────────────────────────────────


def write_crate_manifest(store: Path) -> Path:
    """`ro-crate-metadata.json` at the store root: every entity a File, every record a
    File `about` its entity, every activity a CreateAction whose `result` is the entity,
    whose `object` is what it used and whose `instrument` is the server. Deterministic:
    rebuilt from the store, sorted."""
    cfg = config()
    records = all_records(store)

    def epath(e: dict) -> str:
        return (
            entity_path(store, e["sha256"], e["encoding"]).relative_to(store).as_posix()
        )

    by_sha = {r["entity"]["sha256"]: epath(r["entity"]) for r in records}
    entities, files, actions, sources = {}, [], [], {}
    for r in records:
        e, a = r["entity"], r["activity"]
        entities[by_sha[e["sha256"]]] = {
            "@id": by_sha[e["sha256"]],
            "@type": "File",
            "encodingFormat": e["media_type"],
            "contentSize": str(e["bytes"]),
            "identifier": f"sha256:{e['sha256']}",
        }
        rpath = record_path(store, e["sha256"], a["id"]).relative_to(store).as_posix()
        files.append(
            {
                "@id": rpath,
                "@type": "File",
                "encodingFormat": "application/json",
                "about": {"@id": by_sha[e["sha256"]]},
            }
        )
        for s in r["agent"]["source"]:
            sources[s["id"]] = {
                "@id": f"#source-{s['id']}",
                "@type": "Organization",
                "name": s["id"],
            }
        actions.append(
            {
                "@id": f"#activity-{a['id']}",
                "@type": "CreateAction",
                "name": a["name"],
                "startTime": a["startedAtTime"],
                "endTime": a["endedAtTime"],
                "result": {"@id": by_sha[e["sha256"]]},
                "instrument": {"@id": "#hazbrief-server"},
                "agent": [{"@id": f"#source-{s['id']}"} for s in r["agent"]["source"]],
                # an entity another store holds (the exchange seed, for the tool-call
                # seed) is named by its hash
                "object": [{"@id": by_sha.get(u, f"sha256:{u}")} for u in r["used"]],
            }
        )
    files.sort(key=lambda f: f["@id"])
    actions.sort(key=lambda x: x["@id"])
    graph = [
        {
            "@id": cfg["crate_manifest"],
            "@type": "CreativeWork",
            "conformsTo": {"@id": cfg["crate_conforms_to"]},
            "about": {"@id": "./"},
        },
        {
            "@id": "./",
            "@type": "Dataset",
            "name": "hazbrief evidence store",
            "description": "DN-010: one entity per response body, one record per "
            "activity (W3C PROV terms); docs/schema/evidence_record.schema.json",
            "hasPart": [{"@id": p} for p in sorted(entities)]
            + [{"@id": f["@id"]} for f in files],
            "mentions": [{"@id": a["@id"]} for a in actions],
        },
        {"@id": "#hazbrief-server", "@type": "SoftwareApplication", "name": "hazbrief"},
        *[entities[k] for k in sorted(entities)],
        *files,
        *[sources[k] for k in sorted(sources)],
        *actions,
    ]
    out = store / cfg["crate_manifest"]
    doc = {"@context": cfg["crate_context"], "@graph": graph}
    _atomic_write(out, (json.dumps(doc, indent=1, ensure_ascii=False) + "\n").encode())
    return out
