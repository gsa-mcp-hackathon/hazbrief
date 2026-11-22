#!/usr/bin/env python3
"""One live request per catalogued API endpoint, recorded (HB-06).

`corpus/api_catalog.yaml` names, per API, one `probe.url`. This sends exactly one GET to
each, with the server's own identity (`settings.user_agent`, DN-002 section 1), no key,
no retry and no enumeration, and appends what came back to `corpus/api_probe_log.jsonl`:
status, latency, content type, size, the caching and as-of headers, the as-of value the
catalog's `probe.as_of` names, and for an error the first bytes of the body. A probe is
the server's own per-incident call made once, so it is a runtime API call and not a
crawl (DN-002 section 1); the host must still be on `corpus/allowlist.txt`.

Constitution section 15, at this loop's size (one unit per API, under ten units, so
the whole run is its own pilot): each unit's row is fsynced before the next request;
the unit key is derived from the API id and the URL, and re-running the same command
skips every key already probed (`--reprobe` makes a new verification, a new row); a
wall-clock ceiling stops new requests and exits 3; a transport error is a row, never a
crash.

    uv run python scripts/probe_apis.py
    uv run python scripts/probe_apis.py --reprobe    # re-verify every API (currency)

A row whose `status` is `superseded` is never probed (HB-59 ADDENDUM-02).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "fetch_allowlisted", REPO / "scripts" / "fetch_allowlisted.py"
)
F = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(F)

CONFIG_KEYS = (
    "timeout_seconds",
    "ceiling_wall_clock_seconds",
    "body_excerpt_bytes",
    "max_body_bytes",
)
#: Response headers recorded for every probe: caching and as-of semantics, and the
#: identifiers an upstream asks a client to quote when reporting a problem.
HEADERS = (
    "content-type",
    "cache-control",
    "expires",
    "last-modified",
    "x-correlation-id",
    "x-request-id",
    "retry-after",
    # A redirect's target: the keyless Census query answered 302 and its target went
    # unrecorded in the first HB-06 run (one request per endpoint: it was not re-sent).
    "location",
)
EXIT_STOP = 3


class ProbeError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_config(path: Path) -> dict:
    import yaml

    if not path.exists():
        raise ProbeError(f"config not found: {path}")
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    missing = [k for k in CONFIG_KEYS if k not in cfg]
    if missing:
        raise ProbeError(f"{path}: missing required key(s): {', '.join(missing)}")
    return cfg


def load_catalog(path: Path) -> list:
    import yaml

    apis = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("apis")
    if not isinstance(apis, list) or not apis:
        raise ProbeError(f"{path}: top-level `apis:` must be a non-empty list")
    return apis


def unit_key(api_id: str, url: str) -> str:
    return hashlib.sha256(f"{api_id}\n{url}".encode()).hexdigest()[:16]


def as_of(spec: dict | None, url: str, headers: dict, body: bytes) -> str | None:
    """The as-of value `spec` names: a response header, a JSON member path, or a
    vintage segment of the request path."""
    if not spec:
        return None
    if "header" in spec:
        return headers.get(spec["header"].lower())
    if "json" in spec:
        try:
            v = json.loads(body)
            for k in spec["json"]:
                v = v[k]
            return str(v)
        except (ValueError, KeyError, TypeError, IndexError):
            return None
    if "path_vintage" in spec:
        return spec["path_vintage"] if spec["path_vintage"] in url else None
    raise ProbeError(f"unknown as_of spec {spec!r}")


def probe(client: httpx.Client, url: str, cfg: dict, spec: dict | None) -> dict:
    t0 = time.monotonic()
    try:
        with client.stream("GET", url) as r:
            body = bytearray()
            for chunk in r.iter_bytes():
                body.extend(chunk)
                if len(body) > cfg["max_body_bytes"]:
                    break
            seconds = time.monotonic() - t0
            hdrs = {k: r.headers[k] for k in HEADERS if k in r.headers}
            row = {
                "status": r.status_code,
                "latency_ms": round(seconds * 1000),
                "bytes": len(body),
                "truncated": len(body) > cfg["max_body_bytes"],
                "headers": hdrs,
                "as_of": as_of(spec, url, hdrs, bytes(body)),
            }
            if r.status_code >= 400:
                row["body_excerpt"] = bytes(body[: cfg["body_excerpt_bytes"]]).decode(
                    "utf-8", "replace"
                )
            return row
    except httpx.HTTPError as exc:
        return {
            "status": None,
            "latency_ms": round((time.monotonic() - t0) * 1000),
            "error": f"{type(exc).__name__}: {exc}",
        }


def run(
    apis: list,
    cfg: dict,
    log_path: Path,
    allowlist: tuple,
    user_agent: str,
    reprobe: bool = False,
    transport: httpx.BaseTransport | None = None,
) -> int:
    log = F.FetchLog(log_path)
    done = {r["key"] for r in log.rows() if r.get("event") == "probe"}
    # A superseded row stays in the catalog as the record that its data moved; probing
    # it again verifies nothing (HB-59 ADDENDUM-02: MRLC's GeoServer hangs on the CONUS
    # coverage it no longer serves), so not even --reprobe sends it.
    units = [a for a in apis if a.get("probe") and a.get("status") != "superseded"]
    todo = [
        a for a in units if reprobe or unit_key(a["id"], a["probe"]["url"]) not in done
    ]
    print(
        f"[probe] {len(units)} endpoint(s); {len(units) - len(todo)} done; "
        f"{len(todo)} to run"
    )
    t0 = time.monotonic()
    exit_code = 0
    with httpx.Client(
        headers={"User-Agent": user_agent},
        timeout=cfg["timeout_seconds"],
        follow_redirects=False,
        trust_env=False,
        transport=transport,
    ) as client:
        for n, a in enumerate(todo, 1):
            if time.monotonic() - t0 > cfg["ceiling_wall_clock_seconds"]:
                log.write({"event": "ceiling", "ceiling": "ceiling_wall_clock_seconds"})
                return EXIT_STOP
            url = a["probe"]["url"]
            host = (urllib.parse.urlsplit(url).hostname or "").lower()
            row = {
                "event": "probe",
                "api": a["id"],
                "key": unit_key(a["id"], url),
                "url": url,
            }
            if host not in allowlist:
                row.update(status=None, error=f"host {host!r} is not on the allowlist")
            else:
                row.update(probe(client, url, cfg, a["probe"].get("as_of")))
            row["date"] = _now()[:10]
            log.write(row)
            if row.get("status") is None:
                exit_code = 1
            print(
                f"[probe] {n}/{len(todo)} {a['id']}: {row.get('status')} "
                f"{row.get('latency_ms')} ms as_of={row.get('as_of')}"
            )
    return exit_code


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--catalog", type=Path, default=REPO / "corpus" / "api_catalog.yaml"
    )
    ap.add_argument(
        "--config", type=Path, default=REPO / "corpus" / "probe_config.yaml"
    )
    ap.add_argument("--log", type=Path, default=REPO / "corpus" / "api_probe_log.jsonl")
    ap.add_argument("--allowlist", type=Path, default=REPO / "corpus" / "allowlist.txt")
    ap.add_argument(
        "--user-agent", default=None, help="tests only; default settings.user_agent"
    )
    ap.add_argument("--reprobe", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.user_agent is None:
            sys.path.insert(0, str(REPO / "src"))
            from hazbrief.config import settings

            a.user_agent = settings.user_agent
        return run(
            load_catalog(a.catalog),
            load_config(a.config),
            a.log,
            F.load_allowlist(a.allowlist, env=os.environ),
            a.user_agent,
            reprobe=a.reprobe,
        )
    except (ProbeError, F.ConfigError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
