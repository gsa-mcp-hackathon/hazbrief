"""Shared helpers: the one upstream HTTP client, its recorded exchanges, and pagination.

Every upstream call goes through `fetch_json` (DN-005 section 2). A tool names the API
(`"nws"`) and a relative path; the origin comes from `config.py` (HB-K1), never from a
tool argument. The client keeps the template's outbound boundary: no redirects, no proxy
or netrc from the environment, an explicit timeout, a response size cap, and failure
messages that carry no upstream text.

Recorded exchanges (`settings.hazbrief_http_mode`). Each exchange is one JSON file,
`<exchanges dir>/<api>/<sha256 of method, url and body>.json`, holding the method, the
url, the request headers that matter (User-Agent, Accept; never a key), the status, the
response headers that carry as-of (Date, Last-Modified, Expires, Cache-Control, ETag),
the body and `recorded_at`. `record` writes only an exchange that has no file and serves
the rest, so re-running a recording resumes it and never repeats a call (vcrpy's
`new_episodes`); `replay` serves files and refuses anything else (vcrpy's `none`);
`live` calls and writes nothing. The project writes its own recorder rather than adopt
vcrpy because the file must carry the as-of headers in a form the tools read back, and
a key must never land in a cassette (DN-005 section 2).

`fetch_bytes` is the same client and the same recorder for a response that is not JSON
(HB-11b: the TIGERweb `export` image). Its file holds the body base64-encoded, with
`body_encoding` and the response's `content_type`, so `fetch_json` never mistakes one
for a JSON exchange.

`fetch_range` is `fetch_bytes` for one byte range of a file (RFC 9110 section 14: a
`Range` request answered 206 with its `Content-Range`), the read a Cloud Optimized
GeoTIFF is built for (HB-59 ADDENDUM-03). The range is part of the exchange's key and
its recorded request headers, so each range of one url is its own file and replays
without the network.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Literal
from urllib.parse import unquote, urlsplit

import httpx

from hazbrief.config import settings

#: Response headers that say when the data was made or how long it holds (DN-005
#: section 2), plus Date, the server's own clock at the response.
AS_OF_HEADERS = ("Date", "Last-Modified", "Expires", "Cache-Control", "ETag")
#: The request headers a recorded exchange keeps. Nothing else is written: a header
#: that carried a credential would be a key in a committed file.
RECORDED_REQUEST_HEADERS = ("User-Agent", "Accept", "Range")
#: Query parameters that carry a credential (the Census Data API's `key`, a Socrata app
#: token). They are removed from the url an exchange is keyed and stored under, so the
#: same request records to the same file whatever key the operator holds.
SECRET_QUERY_PARAMS = frozenset({"key", "$$app_token"})


class UpstreamServiceError(RuntimeError):
    """Sanitized external-service failure safe to return to an MCP client."""


class PageCapExceeded(UpstreamServiceError):
    """A layer's query reached its configured page cap before the service ran out of
    features (HB-89; review L3-2). The footprint's bounding box holds more features than
    the server pages for one call; a smaller footprint is the remedy, not a retry."""


class UnrecordedExchangeError(UpstreamServiceError):
    """Replay mode was asked for an exchange that has no recorded file."""


class UpstreamTimeoutError(UpstreamServiceError):
    """The upstream did not answer within `settings.upstream_timeout_seconds` (HB-58: a
    live caller may fall back rather than wait again)."""


class UpstreamStatusError(UpstreamServiceError):
    """The upstream answered an HTTP error status, kept as `status` (HB-58: a live
    caller retries a 5xx once)."""

    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Exchange:
    """One upstream GET and its JSON body. `origin` says whether it was fetched now or
    read from a recorded file; `recorded_at` is when a recorded exchange was fetched."""

    api: str
    method: str
    url: str
    status: int
    as_of_headers: dict[str, str]
    body: Any
    origin: Literal["live", "recorded"]
    recorded_at: str | None = None
    request_headers: dict[str, str] = field(default_factory=dict)
    #: `fetch_bytes` only: the response's media type; its body is then bytes.
    content_type: str | None = None


def _validate_relative_path(path: str) -> str:
    """Reject paths that could select or escape the configured API origin."""
    parsed = urlsplit(path)
    decoded_path = parsed.path
    for _ in range(3):
        decoded = unquote(decoded_path)
        if decoded == decoded_path:
            break
        decoded_path = decoded
    segments = decoded_path.replace("\\", "/").split("/")
    if (
        not path
        or parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or decoded_path.startswith(("/", "\\"))
        or any(segment in {".", ".."} for segment in segments)
    ):
        raise ValueError("path must be a relative API path without a query or fragment")
    return path


def relative_to_origin(api: str, absolute_url: str) -> str:
    """The path of `absolute_url` beneath `api`'s configured origin.

    An upstream response may name its next URL absolutely (the NWS points response
    names the forecast grid). It is followed only when it lies under the same configured
    origin; any other origin is refused, so a response cannot steer the client."""
    base = settings.upstream_base_url(api)
    if not absolute_url.startswith(base):
        raise UpstreamServiceError(
            f"Upstream named a URL outside the configured {api} origin."
        )
    return _validate_relative_path(absolute_url[len(base) :])


def public_url(url: httpx.URL) -> str:
    """`url` with every credential-bearing query parameter removed."""
    kept = [(k, v) for k, v in url.params.multi_items() if k not in SECRET_QUERY_PARAMS]
    return str(url.copy_with(params=kept)) if kept else str(url.copy_with(query=None))


def exchange_key(method: str, url: str, body: bytes = b"") -> str:
    """sha256 over method, url and body, the file name of a recorded exchange."""
    h = hashlib.sha256()
    h.update(method.upper().encode("utf-8") + b"\n" + url.encode("utf-8") + b"\n")
    h.update(body)
    return h.hexdigest()


@dataclass
class Recording:
    """One recording scope (HB-208, Issue 8907cf6c): inside `recording(dir)`, this
    task's fetches run in `record` mode into `exchanges_dir`, whatever
    `settings.hazbrief_http_mode` is, and every exchange read or written is named in
    `touched` as (api, file key). The application's live brief runs each tool's body in
    such a scope before the server's call, so the call's record can name the exchanges
    it reads (its `used`), as the recorded briefs' records do; the server, started in
    `record` mode on the same directory, then reads the same files. A context
    variable, so concurrent calls (one task each) keep their own; the process's mode is
    untouched outside the scope. The server never opens one."""

    exchanges_dir: Path
    touched: set[tuple[str, str]] = field(default_factory=set)


_RECORDING: ContextVar[Recording | None] = ContextVar(
    "hazbrief_recording", default=None
)


@contextmanager
def recording(exchanges_dir: Path) -> Iterator[Recording]:
    """A `Recording` scope for the calling task (see `Recording`)."""
    rec = Recording(Path(exchanges_dir))
    token = _RECORDING.set(rec)
    try:
        yield rec
    finally:
        _RECORDING.reset(token)


def _http_mode() -> str:
    return "record" if _RECORDING.get() is not None else settings.hazbrief_http_mode


def _touch(path: Path) -> None:
    rec = _RECORDING.get()
    if rec is not None:
        rec.touched.add((path.parent.name, path.stem))


def exchange_file(api: str, key: str) -> Path:
    rec = _RECORDING.get()
    root = rec.exchanges_dir if rec is not None else settings.hazbrief_exchanges_dir
    return Path(root) / api / f"{key}.json"


def _secret_values() -> list[str]:
    return [v for v in (settings.census_api_key,) if v]


def _write_exchange(path: Path, ex: Exchange) -> None:
    """Write one exchange atomically (temporary file, fsync, rename), refusing any
    record in which a configured secret value appears."""
    record = {
        "api": ex.api,
        "method": ex.method,
        "url": ex.url,
        "request_headers": ex.request_headers,
        "status": ex.status,
        "response_headers": ex.as_of_headers,
        "body": ex.body,
        "recorded_at": ex.recorded_at,
    }
    if isinstance(ex.body, bytes):
        record |= {
            "body": base64.b64encode(ex.body).decode("ascii"),
            "body_encoding": "base64",
            "content_type": ex.content_type,
        }
    text = json.dumps(record, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    # Each secret as given and as the record's JSON writes it: a `"` or `\` in a value
    # is escaped in the text, which a raw substring match misses (review L3-11).
    forms = {
        f
        for secret in _secret_values()
        for f in (secret, json.dumps(secret, ensure_ascii=False)[1:-1])
    }
    if any(f in text for f in forms):
        raise RuntimeError(
            f"refusing to record {ex.url}: a configured key appears in the exchange"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        # mkstemp creates the file 0600; a fixture is committed and read by any user.
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    _touch(path)


def _read_exchange(path: Path, api: str, url: str, binary: bool = False) -> Exchange:
    """A recorded exchange. A file that is not the exchange its name says (another url,
    or a binary body where JSON is wanted, or the reverse) is a fixture defect and stops
    the call, naming the file."""
    _touch(path)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        if record["url"] != url or record["api"] != api:
            raise ValueError(f"records {record['api']} {record['url']}, not {url}")
        encoded = record.get("body_encoding") == "base64"
        if encoded != binary:
            raise ValueError(
                f"holds a {'binary' if encoded else 'JSON'} body, not a "
                f"{'binary' if binary else 'JSON'} one"
            )
        body = (
            base64.b64decode(record["body"], validate=True)
            if binary
            else record["body"]
        )
        return Exchange(
            api=api,
            method=record["method"],
            url=record["url"],
            status=record["status"],
            as_of_headers=dict(record["response_headers"]),
            body=body,
            origin="recorded",
            recorded_at=record["recorded_at"],
            request_headers=dict(record["request_headers"]),
            content_type=record["content_type"] if binary else None,
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(f"recorded exchange {path} is unusable: {exc}") from None


async def _get_raw(
    base: str, path: str, params, headers: dict[str, str], answers: tuple = ()
) -> tuple[int, dict[str, str], bytes, str, str]:
    """One GET under the template's boundary: (status, as-of headers, body, media
    type, Content-Range). Every failure is an UpstreamServiceError that carries no
    upstream text. A status in `answers` is not a failure: the caller declared it an
    answer (`fetch_json`), so its body is read like a 200's."""
    try:
        async with httpx.AsyncClient(
            base_url=base,
            follow_redirects=False,
            timeout=settings.upstream_timeout_seconds,
            trust_env=False,
        ) as client:
            async with client.stream(
                "GET", path, params=params, headers=headers
            ) as response:
                if response.status_code not in answers:
                    response.raise_for_status()
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > settings.upstream_max_response_bytes:
                        raise UpstreamServiceError(
                            "Upstream response exceeded the size limit."
                        )
                as_of = {
                    h: response.headers[h]
                    for h in AS_OF_HEADERS
                    if h in response.headers
                }
                media = response.headers.get("Content-Type", "").split(";")[0].strip()
                span = response.headers.get("Content-Range", "")
                return response.status_code, as_of, bytes(content), media, span
    except UpstreamServiceError:
        raise
    except httpx.HTTPStatusError as exc:
        raise UpstreamStatusError(
            f"Upstream service returned status {exc.response.status_code}.",
            exc.response.status_code,
        ) from None
    except httpx.TimeoutException:
        raise UpstreamTimeoutError("Upstream service request failed.") from None
    except httpx.RequestError:
        raise UpstreamServiceError("Upstream service request failed.") from None


async def _get_live(
    base: str, path: str, params, headers: dict[str, str], **answers
) -> tuple[int, dict[str, str], Any]:
    status, as_of, content, _, _ = await _get_raw(
        base, path, params, headers, **answers
    )
    try:
        return status, as_of, json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise UpstreamServiceError("Upstream service returned invalid JSON.") from None


async def _get_live_bytes(
    base: str, path: str, params, headers: dict[str, str]
) -> tuple[int, dict[str, str], bytes, str]:
    status, as_of, content, media, _ = await _get_raw(base, path, params, headers)
    return status, as_of, content, media


def _request(api: str, path: str, params: dict[str, Any] | None):
    """(origin, checked path, stored url, exchange file) of a GET."""
    safe_path = _validate_relative_path(path)
    base = settings.upstream_base_url(api)
    url = httpx.URL(base).join(safe_path)
    if params:
        url = url.copy_merge_params(params)
    stored_url = public_url(url)
    return (
        base,
        safe_path,
        stored_url,
        exchange_file(api, exchange_key("GET", stored_url)),
    )


def _unrecorded(api: str, stored_url: str, file: Path) -> UnrecordedExchangeError:
    return UnrecordedExchangeError(
        f"No recorded exchange for GET {stored_url} (expected {file.name} under "
        f"{api}/); record it once with HAZBRIEF_HTTP_MODE=record."
    )


def _recorded_headers(request_headers: dict[str, str]) -> dict[str, str]:
    return {
        h: request_headers[h] for h in RECORDED_REQUEST_HEADERS if h in request_headers
    }


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def fetch_json(
    api: str,
    path: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    answers: tuple[int, ...] = (),
) -> Exchange:
    """GET `path` beneath `api`'s configured origin and return the exchange.

    `answers` names error statuses the caller reads as an answer, not a failure: the
    exchange is returned with that status and its JSON body, and recorded and replayed
    like a 200 (HB-119: PubChem PUG REST answers a name it does not know with 404 and a
    JSON Fault, the source's statement that it holds no such record, RFC 9110 section
    15.5.5). No server tool passes it; every other status still raises.

    Raises:
        ValueError: if path could select or escape the configured API origin.
        UnrecordedExchangeError: in replay mode, for an exchange with no file.
        UpstreamServiceError: with a sanitized message for external failures.
    """
    base, safe_path, stored_url, file = _request(api, path, params)
    mode = _http_mode()

    if mode in ("replay", "record") and file.is_file():
        return _read_exchange(file, api, stored_url)
    if mode == "replay":
        raise _unrecorded(api, stored_url, file)

    request_headers = {**(headers or {}), "User-Agent": settings.user_agent}
    # Passed only when declared, so a recorder that wraps `_get_live` or `_get_raw`
    # with the four-argument form (eval_harness.py) is unaffected.
    declared = {"answers": tuple(answers)} if answers else {}
    status, as_of, body = await _get_live(
        base, safe_path, params, request_headers, **declared
    )
    ex = Exchange(
        api=api,
        method="GET",
        url=stored_url,
        status=status,
        as_of_headers=as_of,
        body=body,
        origin="live",
        recorded_at=_now(),
        request_headers=_recorded_headers(request_headers),
    )
    if mode == "record":
        _write_exchange(file, ex)
    return ex


def recorded_json(
    api: str, path: str, params: dict[str, Any] | None = None
) -> Exchange:
    """The recorded exchange of the GET `fetch_json` would make, read from its file
    whatever `settings.hazbrief_http_mode` is: replay for a caller that replays its own
    inputs while the process runs in another mode (the workbench's `--replay` brief,
    HB-49). An exchange with no file is refused as replay refuses it."""
    _, _, stored_url, file = _request(api, path, params)
    if not file.is_file():
        raise _unrecorded(api, stored_url, file)
    return _read_exchange(file, api, stored_url)


async def fetch_bytes(
    api: str,
    path: str,
    params: dict[str, Any] | None = None,
    accept: tuple[str, ...] = ("image/png",),
) -> Exchange:
    """`fetch_json` for a response that is not JSON: the body is bytes, and a response
    whose media type is not in `accept` is refused before it is recorded (an ArcGIS
    export that fails answers a JSON error object with HTTP 200).

    Raises: as `fetch_json`.
    """
    base, safe_path, stored_url, file = _request(api, path, params)
    mode = _http_mode()

    if mode in ("replay", "record") and file.is_file():
        return _read_exchange(file, api, stored_url, binary=True)
    if mode == "replay":
        raise _unrecorded(api, stored_url, file)

    request_headers = {"User-Agent": settings.user_agent}
    status, as_of, body, media = await _get_live_bytes(
        base, safe_path, params, request_headers
    )
    if media not in accept:
        raise UpstreamServiceError(
            f"Upstream returned {media or 'no media type'}, not an accepted type."
        )
    ex = Exchange(
        api=api,
        method="GET",
        url=stored_url,
        status=status,
        as_of_headers=as_of,
        body=body,
        origin="live",
        recorded_at=_now(),
        request_headers=_recorded_headers(request_headers),
        content_type=media,
    )
    if mode == "record":
        _write_exchange(file, ex)
    return ex


async def fetch_range(api: str, path: str, start: int, end: int) -> Exchange:
    """Bytes `start` to `end` (inclusive) of the file at `path` beneath `api`'s origin.

    Only the bytes asked are accepted: an answer that is not 206, whose Content-Range
    names other bytes, or whose body is not that long is refused before it is recorded
    (a server that ignores Range answers 200 with the whole object). A replayed range
    is checked for length as well.

    Raises: as `fetch_json`.
    """
    if not 0 <= start <= end:
        raise ValueError(f"not a byte range: {start}-{end}")
    want = f"bytes={start}-{end}"
    base, safe_path, stored_url, _ = _request(api, path, None)
    file = exchange_file(api, exchange_key("GET", stored_url, want.encode("ascii")))
    size = end - start + 1
    mode = _http_mode()

    if mode in ("replay", "record") and file.is_file():
        ex = _read_exchange(file, api, stored_url, binary=True)
        if len(ex.body) != size:
            raise RuntimeError(f"recorded exchange {file} is unusable: not {want}")
        return ex
    if mode == "replay":
        raise _unrecorded(api, f"{stored_url} ({want})", file)

    request_headers = {"User-Agent": settings.user_agent, "Range": want}
    status, as_of, body, media, span = await _get_raw(
        base, safe_path, None, request_headers
    )
    if status != 206 or not span.startswith(f"bytes {start}-{end}/"):
        raise UpstreamServiceError(
            f"Upstream did not answer the byte range asked ({status})."
        )
    if len(body) != size:
        raise UpstreamServiceError("Upstream range answer is short.")
    ex = Exchange(
        api=api,
        method="GET",
        url=stored_url,
        status=status,
        as_of_headers=as_of,
        body=body,
        origin="live",
        recorded_at=_now(),
        request_headers=_recorded_headers(request_headers),
        content_type=media,
    )
    if mode == "record":
        _write_exchange(file, ex)
    return ex


def paginate(items: list[Any], limit: int, offset: int) -> dict[str, Any]:
    """Slice a list and return a standard pagination envelope.

    Returns a dict with `total`, `count`, `offset`, `items`, `has_more`, and
    `next_offset` — the shape recommended in the MCP best-practices guide.
    """
    total = len(items)
    window = items[offset : offset + limit]
    next_offset = offset + len(window)
    return {
        "total": total,
        "count": len(window),
        "offset": offset,
        "items": window,
        "has_more": next_offset < total,
        "next_offset": next_offset if next_offset < total else None,
    }
