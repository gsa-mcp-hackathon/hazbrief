"""One recorded exchange as an evidence record (DN-010 s3.4; HB-39 step 6).

An exchange file (`hazbrief.utils` wrote it in `record` mode) becomes one record: the
activity is the upstream GET, the entity its body, the source the catalog row its url
falls under. As-of is the source's own Last-Modified when the exchange carries one, else
the time it was recorded (DN-010 D3). A body two exchanges share is one entity with two
records. A record's activity id is a hash of the activity, so writing it again writes
nothing.

`scripts/migrate_exchanges_to_store.py` writes the seed with it; the application's live
brief writes each call's exchanges into its run's store with it (HB-208, Issue
8907cf6c: `hazbrief.brief.live_exchanges`), so the map draws a live brief's geometry as
it draws a replay's.
"""

from __future__ import annotations

import base64
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from hazbrief.evidence import catalog
from hazbrief.evidence.store import (
    activity_id,
    canonical_hash,
    record_path,
    write_entity,
    write_record,
)

#: `hazbrief.utils.settings.user_agent`'s form: `hazbrief-mcp/<version> (+<url>)`.
UA_PREFIX = "hazbrief-mcp/"
#: The mode an exchange file is written in (`hazbrief.utils._write_exchange`).
RECORDING_MODE = "record"


def server_version(exchange: dict) -> str:
    """The server version the exchange's User-Agent names. An exchange without one was
    not recorded by this server, and is refused."""
    ua = (exchange.get("request_headers") or {}).get("User-Agent", "")
    if not ua.startswith(UA_PREFIX):
        raise ValueError(f"{exchange['url']}: User-Agent {ua!r} is not hazbrief's")
    return ua[len(UA_PREFIX) :].split(" ", 1)[0]


def as_of(exchange: dict) -> tuple[str, str]:
    """(as_of, its basis): the response's Last-Modified (RFC 9110 HTTP-date) as UTC ISO
    8601 when the exchange carries it, else `recorded_at`."""
    lm = (exchange.get("response_headers") or {}).get("Last-Modified")
    if lm:
        dt = parsedate_to_datetime(lm)
        return dt.isoformat().replace("+00:00", "Z"), "Last-Modified header"
    return exchange["recorded_at"], "recorded_at"


def body_of(exchange: dict) -> tuple[Any, str]:
    """(the body as the server read it, media type): JSON as parsed; base64 as bytes."""
    if exchange.get("body_encoding") == "base64":
        return base64.b64decode(exchange["body"], validate=True), exchange[
            "content_type"
        ]
    return exchange["body"], "application/json"


def record_exchange(exchange: dict, store: Path) -> dict[str, Any]:
    """Write `exchange` (an exchange file's JSON) into `store` as an upstream exchange
    record: `{sha256, source_id, record_held, entity_new}`."""
    row = catalog.row_for_exchange(exchange["api"], exchange["url"])
    body, media = body_of(exchange)
    sha, _, new_entity = write_entity(store, body)
    when, basis = as_of(exchange)
    params = {"method": exchange["method"], "url": exchange["url"]}
    # A byte-range exchange (utils.fetch_range; HB-59 ADDENDUM-03) is one of many
    # under one url: its range is part of what was asked, and of its file's key.
    # An exchange without one keeps the activity, and so the id, it always had.
    span = (exchange.get("request_headers") or {}).get("Range")
    if span:
        params["range"] = span
    activity = {
        "type": "upstream_exchange",
        "name": f"GET {exchange['api']}",
        "params": params,
        "startedAtTime": exchange["recorded_at"],
        "endedAtTime": exchange["recorded_at"],
        "http_mode": RECORDING_MODE,
    }
    held = record_path(store, canonical_hash(body), activity_id(activity)).is_file()
    write_record(
        store,
        body,
        activity=activity,
        server={
            "name": UA_PREFIX.rstrip("/"),
            "version": server_version(exchange),
            "tool_surface_sha256": None,
        },
        source=[{"id": row["id"], "endpoint": exchange["url"]}],
        provenance_class=row["provenance_class"],
        as_of=when,
        as_of_basis=basis,
        horizon_s=row["horizon_s"],
        horizon_source=row["id"],
        media_type=media,
    )
    return {
        "sha256": sha,
        "source_id": row["id"],
        "record_held": held,
        "entity_new": new_entity,
    }
