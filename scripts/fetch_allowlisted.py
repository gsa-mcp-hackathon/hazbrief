#!/usr/bin/env python3
"""Fetch the corpus documents a source list names, from allowlisted hosts only.

**Zero model spend.**

Adapted from ai-readiness-kg `scripts/fetch_allowlisted.py` and the `Fetcher` in
`assessment/harness/scan/manners.py` (both at 0f2ffa29, 2026-10-11; repository HEAD
788400fd), per HB-01 rule 1. What is kept, and why it is the same contract:

* **Refuses any URL whose host is not on the allowlist, before any socket opens.** Exact
  hostnames, compared case-insensitively (RFC 4343); no wildcard or subdomain matching.
  The same check runs as an httpx `request` event hook, so a redirect to an off-list
  host is refused at that hop too, and so is the `robots.txt` read.
* **Robots-first, one identified user agent, rate-limited per host.** The `robots.txt`
  status is read through RFC 9309 s2.3.1 clause by clause (`robots_access`, ported
  unchanged): 2xx rules, 4xx allow all, 5xx or a network failure complete disallow. A
  host's `Crawl-delay` slows the client down and never speeds it up; a delay above
  `crawl_delay_max_s` sets the host aside for the run. 429 and 503 back off
  exponentially, bounded by `max_retries`.
* **One log line per request**, JSONL, flushed and fsynced: every response the client
  received (robots reads and redirect hops included) and every refusal, plus one
  `unit_done` row per document. The RESULT of the task quotes this log whole.

What changed, and why:

* **The allowlist source** is `corpus/allowlist.txt` (HB-01 rule 1 names it). When the
  dispatcher's `SELDON_NETWORK_ALLOWLIST` is also set, the effective list is the
  intersection: a session may narrow its declared network, never widen it.
* **The input is the source list** (`corpus/sources.yaml`), not URLs on the command
  line, and a document is stored as `corpus/raw/<doc_id><ext>`, so the manifest can join
  on `doc_id`.
* **The scanner machinery is dropped.** The original `Fetcher` serves a multi-threaded
  scan of hundreds of hosts and carries a measurement carve-out (it always fetches
  `/robots.txt`, `/sitemap.xml` and friends because those are what it measures). A
  corpus fetch is serial and measures nothing, so neither the per-host lock table nor
  the carve-out has a job here.
* **Constitution section 15** (`~/GitHub/CLAUDE.md`): each document is one unit with a
  key derived from `doc_id` and `url`; a unit's file is written atomically and its
  `unit_done` row fsynced before the next unit starts; re-running the same command is
  the resume (completed keys are skipped); progress on a fixed interval; a pilot that
  projects wall clock and bytes; wall-clock and byte ceilings that stop cleanly with
  exit 3.
* **An HTML 200 is checked for text** (HB-01c). HTML has no format signature, so HB-06
  stored data.cms.gov's "Page Not Found" JavaScript shell as `fetched`. A response that
  is HTML (by content type or declared format) whose title is a soft-404 title or whose
  visible text is under `html_min_visible_chars` is recorded `script_rendered` and not
  stored. This is soft-404 detection (Bar-Yossef, Broder, Kumar and Tomkins, "Sic
  transit gloria telae", WWW 2004: a server answering 200 for a page that is not
  there), measured by the visible text `corpus_text.html_text` extracts, the text
  Squiddy indexes. No precedent in the operator's repositories: Squiddy's acquire
  checks the leading bytes only, as `SIGNATURES` here does.
* **A redirect must land on the page asked for** (HB-47). HB-46b asked
  proceedings.esri.com for the CATS paper; the host 301'd every path to Esri's
  proceedings index on www.esri.com, an allowlisted host, and the index passed the text
  check, so it was stored as the paper. A 200 whose final URL is a different page
  (`same_page`) is recorded `redirected_elsewhere`, with its final URL and title, and
  not stored. The host and the scheme may change. The path and query are compared after
  the normalizations of RFC 3986 s6.2.2 (percent-encoding, dot segments), with the empty
  path read as "/" (s6.2.3), repeated slashes collapsed, one trailing slash dropped
  (Apache's DirectorySlash redirect), and case folded. RFC 3986 holds the path
  case-sensitive, but the redirects this log holds include training.fema.gov
  case-folding every ICS form path, and web archives match URLs case-insensitively
  (Heritrix's `LowercaseRule`). A web-archive capture (`memento_hosts`) is compared by
  the original URL it captures and its modifier, so a TimeGate redirect to the nearest
  capture (RFC 7089) stays `fetched`.
* **A refusal names the next rung** (HB-62, DN-002 ADDENDUM-00, the acquisition
  ladder). A unit refused by the host, robots.txt or the allowlist, or recorded
  `script_rendered` or `redirected_elsewhere`, carries `next_rung` in its row and its
  printed line: `browser` (the session in the operator's browser), or `operator` only
  when the response itself shows a credential gate (`next_rung`). The fetcher never
  climbs a rung itself; it never changes its identity to pass a block (HB-61).

**Enforcement is declarative plus audit, not a sandbox** (as in the original): nothing
stops a session from fetching some other way; the helper makes the declared path the
easy one and the log makes its use checkable.

    uv run python scripts/fetch_allowlisted.py             # every `plan: fetch` entry
    uv run python scripts/fetch_allowlisted.py --dry-run   # check hosts, contact none
    uv run python scripts/fetch_allowlisted.py --only cameo-unna-1017
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import posixpath
import re
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from corpus_text import html_text  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
DEFAULTS = {
    "sources": REPO / "corpus" / "sources.yaml",
    "allowlist": REPO / "corpus" / "allowlist.txt",
    "config": REPO / "corpus" / "fetch_config.yaml",
    "out_dir": REPO / "corpus" / "raw",
    "log": REPO / "corpus" / "fetch_log.jsonl",
}

#: The name Seldon's dispatcher sets (`seldon.core.dispatch.NETWORK_ALLOWLIST_ENV`).
ALLOWLIST_ENV = "SELDON_NETWORK_ALLOWLIST"
ACQUISITION_METHOD = "scripted_fetch"
ACQUIRED_BY = "scripts/fetch_allowlisted.py"
SCHEMES = ("http", "https")

#: Every key `corpus/fetch_config.yaml` must carry. A missing key is a startup failure.
CONFIG_KEYS = (
    "user_agent",
    "requests_per_second_per_host",
    "crawl_delay_max_s",
    "connect_timeout_seconds",
    "read_timeout_seconds",
    "backoff_on_status",
    "max_retries",
    "backoff_base_seconds",
    "follow_redirects",
    "max_redirects",
    "memento_hosts",
    "html_min_visible_chars",
    "html_shell_title_patterns",
    "credential_gate_path_patterns",
    "progress_every_units",
    "progress_every_seconds",
    "pilot_units",
    "ceiling_wall_clock_seconds",
    "ceiling_total_bytes",
    "ceiling_document_bytes",
)

#: Outcomes that end a unit. A re-run skips a unit whose latest `unit_done` row is one
#: of these (for `fetched`, only while its file still hashes to the logged sha256).
#: `failed` (transport errors, 5xx after retries) and `robots_unreachable` (RFC 9309
#: s2.3.1.4 complete disallow, which holds "for the cycle", not forever) are not
#: terminal: re-running retries.
TERMINAL = (
    "fetched",
    "refused_by_host",
    "robots_disallowed",
    "blocked_host",
    "host_set_aside",
    "too_large",
    "not_the_document",
    "script_rendered",
    "redirected_elsewhere",
)

#: Leading bytes by declared format. A 200 whose body does not start with its format's
#: signature is a page ABOUT the document (an error page, a landing page), not the
#: document.
SIGNATURES = {
    "pdf": (b"%PDF",),
    "xlsx": (b"PK\x03\x04",),
    # BIFF8 workbooks are OLE2 compound files ([MS-CFB] 2.2, the header signature).
    "xls": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
    "zip": (b"PK\x03\x04",),
    "json": (b"{", b"["),
    "xml": (b"<?xml", b"<"),
}

#: Content types that are HTML. A 200 in one of them, or for an entry declared
#: `format: html`, gets the text check (`html_shell`), since HTML has no signature.
HTML_TYPES = ("text/html", "application/xhtml+xml")
_TITLE_RE = re.compile(rb"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)

#: Content type -> stored file extension. A type not listed falls back to the URL's
#: suffix.
EXTENSIONS = {
    "application/pdf": ".pdf",
    "text/html": ".html",
    "application/json": ".json",
    "text/csv": ".csv",
    "text/plain": ".txt",
    "application/xml": ".xml",
    "text/xml": ".xml",
    "application/zip": ".zip",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
}


#: Outcomes a re-run retries; they make the exit code 1.
RETRYABLE = ("failed", "robots_unreachable")

#: The acquisition ladder (DN-002 ADDENDUM-00): a refusal is a hand-off, not an end.
#: These outcomes are this client being declined, by the host, its robots.txt, the
#: allowlist, a page its server does not send, or a redirect away from the page; the
#: next rung is the session in the operator's browser (rung 2), unless the response
#: shows a credential gate (`next_rung`). Every other outcome names no rung: `fetched`
#: is done, `failed` and `robots_unreachable` are retried here, and `too_large`,
#: `host_set_aside` and `not_the_document` are this client's own ceilings or a wrong
#: URL, not a refusal.
REFUSALS = (
    "refused_by_host",
    "robots_disallowed",
    "blocked_host",
    "script_rendered",
    "redirected_elsewhere",
)
#: RFC 9110 s15.5.2 (a 401 carries WWW-Authenticate) and s15.5.8 (a 407 carries
#: Proxy-Authenticate): the challenge that makes a status a credential gate.
CHALLENGES = {401: "www-authenticate", 407: "proxy-authenticate"}


class ConfigError(RuntimeError):
    """The config, allowlist or source list is missing or malformed."""


class OffAllowlist(RuntimeError):
    """A URL whose host is not on the effective allowlist. Raised before any request."""


class Ceiling(RuntimeError):
    """A section 15 ceiling was crossed; the run stops cleanly."""


# ------------------------------------------------------------------ configuration
def load_config(path: Path) -> dict:
    import yaml

    if not path.exists():
        raise ConfigError(f"fetch config not found: {path}")
    try:
        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from None
    missing = [k for k in CONFIG_KEYS if k not in cfg]
    if missing:
        raise ConfigError(f"{path}: missing required key(s): {', '.join(missing)}")
    return cfg


def load_allowlist(path: Path, env: dict | None = None) -> tuple:
    """Hosts from the allowlist file, narrowed by `SELDON_NETWORK_ALLOWLIST` if set."""
    env = os.environ if env is None else env
    if not path.exists():
        raise ConfigError(f"allowlist not found: {path}")
    hosts = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip().lower()
        if line:
            hosts.append(line)
    hosts = tuple(dict.fromkeys(hosts))
    if not hosts:
        raise ConfigError(
            f"{path} names no host; a run with no declared network fetches nothing"
        )
    declared = (env.get(ALLOWLIST_ENV) or "").strip()
    if declared:
        dispatcher = {h.strip().lower() for h in declared.split(",") if h.strip()}
        hosts = tuple(h for h in hosts if h in dispatcher)
        if not hosts:
            raise ConfigError(f"{path} and {ALLOWLIST_ENV} share no host")
    return hosts


def load_sources(path: Path) -> list:
    import yaml

    if not path.exists():
        raise ConfigError(f"source list not found: {path}")
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from None
    entries = doc.get("sources")
    if not isinstance(entries, list) or not entries:
        raise ConfigError(f"{path}: top-level `sources:` must be a non-empty list")
    seen = set()
    for e in entries:
        for k in ("doc_id", "plan"):
            if not e.get(k):
                raise ConfigError(f"{path}: entry {e!r} has no `{k}`")
        if e["doc_id"] in seen:
            raise ConfigError(f"{path}: duplicate doc_id {e['doc_id']!r}")
        seen.add(e["doc_id"])
        if e["plan"] == "fetch" and not e.get("url"):
            raise ConfigError(f"{path}: {e['doc_id']} has plan: fetch and no url")
    return entries


def check_url(url: str, allowlist: tuple) -> str:
    """The URL's host, if the URL may be fetched. Raises `OffAllowlist` otherwise."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme.lower() not in SCHEMES:
        raise OffAllowlist(f"{url!r}: scheme {parts.scheme!r} is not one of {SCHEMES}")
    host = (parts.hostname or "").lower()
    if host not in allowlist:
        raise OffAllowlist(f"{url!r}: host {host!r} is not on the allowlist")
    return host


def unit_key(doc_id: str, url: str) -> str:
    """Derived from the inputs: a changed URL is a new unit, never a stale reuse."""
    return hashlib.sha256(f"{doc_id}\n{url}".encode()).hexdigest()[:16]


def robots_access(status, transport_error: bool = False) -> tuple:
    """`(robots_status, decision, rfc9309_clause)` for one `robots.txt` read. **Pure.**

    Ported unchanged in substance from ai-readiness-kg `scan/manners.py::robots_access`.
    RFC 9309 s2.3.1: 2xx "MUST follow the parseable rules" (2.3.1.1); a final 3xx the
    client could not follow is unavailable (2.3.1.2); 4xx "MAY access any resources"
    (2.3.1.3); 5xx or a network error "MUST assume complete disallow" (2.3.1.4).
    """
    if status is None:
        return (
            ("unreachable", "disallow_all", "2.3.1.4")
            if transport_error
            else ("unavailable", "allow_all", "2.3.1.2")
        )
    if 200 <= status < 300:
        return "successful", "rules", "2.3.1.1"
    if 300 <= status < 400:
        return "unavailable", "allow_all", "2.3.1.2"
    if 400 <= status < 500:
        return "unavailable", "allow_all", "2.3.1.3"
    return "unreachable", "disallow_all", "2.3.1.4"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extension(content_type: str | None, url: str) -> str:
    base = (content_type or "").split(";", 1)[0].strip().lower()
    if base in EXTENSIONS:
        return EXTENSIONS[base]
    suffix = Path(urllib.parse.urlsplit(url).path).suffix.lower()
    return suffix if suffix and len(suffix) <= 6 else ".bin"


# ------------------------------------------------------------------ the log
class FetchLog:
    """Append-only JSONL; each row is fsynced before the caller moves on."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, row: dict) -> None:
        row = {"ts": _now(), **row}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def rows(self) -> list:
        """Every parseable row. A torn last line (a kill mid-write) is skipped."""
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def latest_units(self) -> dict:
        """key -> the latest `unit_done` row for it."""
        return {r["key"]: r for r in self.rows() if r.get("event") == "unit_done"}


def completed(row: dict | None, repo: Path) -> bool:
    """A unit is done when its latest row is terminal and, for a stored file, the file
    still hashes to what was logged. A file that moved is fetched again (one document).
    """
    if not row or row.get("outcome") not in TERMINAL:
        return False
    if row["outcome"] != "fetched":
        return True
    path = repo / row["stored_at"]
    return (
        path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"]
    )


# ------------------------------------------------------------------ the polite client
class RealClock:
    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


class PoliteClient:
    """Robots-first, one identity, one request at a time per host, with backoff."""

    def __init__(
        self, cfg: dict, allowlist: tuple, log: FetchLog, transport=None, clock=None
    ) -> None:
        import httpx

        self.cfg, self.allowlist, self.log = cfg, allowlist, log
        self.clock = clock or RealClock()
        self._last: dict = {}
        self._robots: dict = {}  # netloc -> Protego parser, None (allow all), or "deny"
        self._delay: dict = {}  # netloc -> Crawl-delay seconds
        self._set_aside: dict = {}  # netloc -> reason
        self.doc_id = None  # tagged onto every log row while a unit runs

        def guard(request):
            try:
                check_url(str(request.url), allowlist)
            except OffAllowlist as exc:
                self.log.write(
                    {
                        "event": "refused",
                        "doc_id": self.doc_id,
                        "method": request.method,
                        "url": str(request.url),
                        "status": None,
                        "bytes": 0,
                        "sha256": None,
                        "reason": str(exc),
                    }
                )
                raise

        def hop(response):
            # Redirect hops only; the final response is logged with its body hash by
            # `get`.
            if response.is_redirect:
                self.log.write(
                    {
                        "event": "request",
                        "doc_id": self.doc_id,
                        "method": response.request.method,
                        "url": str(response.request.url),
                        "status": response.status_code,
                        "bytes": 0,
                        "sha256": None,
                        "location": response.headers.get("location"),
                    }
                )

        kw = {} if transport is None else {"transport": transport}
        self.http = httpx.Client(
            follow_redirects=cfg["follow_redirects"],
            max_redirects=cfg["max_redirects"],
            timeout=httpx.Timeout(
                connect=cfg["connect_timeout_seconds"],
                read=cfg["read_timeout_seconds"],
                write=cfg["read_timeout_seconds"],
                pool=cfg["read_timeout_seconds"],
            ),
            headers={"User-Agent": cfg["user_agent"]},
            event_hooks={"request": [guard], "response": [hop]},
            **kw,
        )

    def _wait(self, netloc: str) -> None:
        gap = max(
            1.0 / float(self.cfg["requests_per_second_per_host"]),
            self._delay.get(netloc, 0.0),
        )
        last = self._last.get(netloc)
        if last is not None:
            delta = self.clock.now() - last
            if delta < gap:
                self.clock.sleep(gap - delta)
        self._last[netloc] = self.clock.now()

    def _raw(self, url: str, cap: int | None) -> dict:
        """One GET with backoff; the body read is capped at `cap` bytes when given."""
        netloc = urllib.parse.urlsplit(url).netloc
        attempts = 0
        while True:
            self._wait(netloc)
            with self.http.stream("GET", url) as resp:
                if (
                    resp.status_code in self.cfg["backoff_on_status"]
                    and attempts < self.cfg["max_retries"]
                ):
                    self.log.write(
                        {
                            "event": "request",
                            "doc_id": self.doc_id,
                            "method": "GET",
                            "url": str(resp.url),
                            "status": resp.status_code,
                            "bytes": 0,
                            "sha256": None,
                            "note": "backoff",
                        }
                    )
                    attempts += 1
                    self.clock.sleep(
                        float(self.cfg["backoff_base_seconds"]) ** attempts
                    )
                    continue
                declared = resp.headers.get("content-length")
                if (
                    cap is not None
                    and declared
                    and declared.isdigit()
                    and int(declared) > cap
                ):
                    return {
                        "status": resp.status_code,
                        "final_url": str(resp.url),
                        "content_type": resp.headers.get("content-type"),
                        "body": None,
                        "too_large": int(declared),
                    }
                body = bytearray()
                for chunk in resp.iter_bytes():
                    body.extend(chunk)
                    if cap is not None and len(body) > cap:
                        return {
                            "status": resp.status_code,
                            "final_url": str(resp.url),
                            "content_type": resp.headers.get("content-type"),
                            "body": None,
                            "too_large": len(body),
                        }
                body = bytes(body)
                self.log.write(
                    {
                        "event": "request",
                        "doc_id": self.doc_id,
                        "method": "GET",
                        "url": str(resp.url),
                        "status": resp.status_code,
                        "bytes": len(body),
                        "sha256": hashlib.sha256(body).hexdigest(),
                        "content_type": resp.headers.get("content-type"),
                    }
                )
                challenge = CHALLENGES.get(resp.status_code)
                return {
                    "status": resp.status_code,
                    "final_url": str(resp.url),
                    "content_type": resp.headers.get("content-type"),
                    "body": body,
                    "challenge": resp.headers.get(challenge) if challenge else None,
                }

    def _robots_for(self, scheme: str, netloc: str):
        key = f"{scheme}://{netloc}"
        if key in self._robots:
            return self._robots[key]
        from protego import Protego

        url = f"{key}/robots.txt"
        status, text, transport_error, error = None, "", False, None
        try:
            r = self._raw(url, cap=None)
            status = r["status"]
            # utf-8-sig: a leading byte-order mark is an encoding signature, not part of
            # the first line (armypubs.army.mil serves one; read raw, `User-agent: *`
            # stops being a user-agent line and the file silently means allow-all).
            text = r["body"].decode("utf-8-sig", "replace") if r["body"] else ""
        except OffAllowlist:
            raise
        except Exception as exc:  # noqa: BLE001 - classified and logged, never guessed
            transport_error, error = True, f"{type(exc).__name__}: {exc}"
        robots_status, decision, clause = robots_access(status, transport_error)
        parsed = None
        if decision == "rules" and text.strip():
            parsed = Protego.parse(text)
        elif decision == "disallow_all":
            parsed = "deny"
        self._robots[key] = parsed
        delay = None
        if parsed not in (None, "deny"):
            raw = parsed.crawl_delay(self.cfg["user_agent"])
            delay = float(raw) if raw is not None and float(raw) >= 0 else None
        if delay is not None:
            if delay > float(self.cfg["crawl_delay_max_s"]):
                self._set_aside[netloc] = (
                    f"Crawl-delay {delay:g} s exceeds crawl_delay_max_s "
                    f"{self.cfg['crawl_delay_max_s']} s; host set aside for this run"
                )
            else:
                self._delay[netloc] = max(delay, self._delay.get(netloc, 0.0))
        self.log.write(
            {
                "event": "robots",
                "doc_id": self.doc_id,
                "netloc": netloc,
                "url": url,
                "status": status,
                "error": error,
                "robots_status": robots_status,
                "decision": decision,
                "rfc9309": clause,
                "crawl_delay_s": delay,
                "interval_s": max(
                    1.0 / float(self.cfg["requests_per_second_per_host"]),
                    self._delay.get(netloc, 0.0),
                ),
            }
        )
        return parsed

    def get(self, url: str) -> dict:
        """The outcome of fetching one document URL; `outcome` is always set."""
        check_url(url, self.allowlist)
        parts = urllib.parse.urlsplit(url)
        rp = self._robots_for(parts.scheme, parts.netloc)
        if parts.netloc in self._set_aside:
            return {
                "outcome": "host_set_aside",
                "reason": self._set_aside[parts.netloc],
            }
        if rp == "deny":
            return {
                "outcome": "robots_unreachable",
                "reason": "robots.txt unreachable: RFC 9309 s2.3.1.4 complete disallow "
                "for this run (see the robots row for the error)",
            }
        if rp is not None and not rp.can_fetch(url, self.cfg["user_agent"]):
            return {
                "outcome": "robots_disallowed",
                "reason": "robots.txt disallows this path for "
                f"{self.cfg['user_agent']}",
            }
        r = self._raw(url, cap=int(self.cfg["ceiling_document_bytes"]))
        if r.get("too_large"):
            return {
                "outcome": "too_large",
                "status": r["status"],
                "final_url": r["final_url"],
                "reason": f"body exceeds ceiling_document_bytes "
                f"({r['too_large']} > {self.cfg['ceiling_document_bytes']})",
            }
        return {"outcome": "response", **r}


# ------------------------------------------------------------------ redirects
#: A web-archive capture's path: /web/<datetime><modifier>/<original URL>, the datetime
#: 14 digits or a prefix of them. The modifier (`id_` original bytes, `im_`, `js_`, ...)
#: selects what the archive serves.
_MEMENTO_RE = re.compile(r"^/web/(\d{1,14})([a-z]{2}_)?/(.+)$")
#: RFC 3986 s2.3: unreserved characters, whose percent-encoding is equivalent to the
#: character itself (s6.2.2.2).
_UNRESERVED = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)


def _unescape_unreserved(text: str) -> str:
    def one(m: re.Match) -> str:
        ch = chr(int(m.group(1), 16))
        return ch if ch in _UNRESERVED else m.group(0)

    return re.sub(r"%([0-9A-Fa-f]{2})", one, text)


def _page_key(parts: urllib.parse.SplitResult) -> tuple:
    """The path and query a page is named by, with host and scheme left out."""
    path = re.sub(r"/{2,}", "/", _unescape_unreserved(parts.path))
    # normpath removes dot segments (RFC 3986 s5.2.4) and the trailing slash.
    path = posixpath.normpath(path) if path else "/"
    return path.lower(), _unescape_unreserved(parts.query).lower()


def _memento(parts: urllib.parse.SplitResult, cfg: dict) -> tuple | None:
    """`(modifier, original URL)` when the URL is a web-archive capture, else None."""
    if (parts.hostname or "").lower() not in cfg["memento_hosts"]:
        return None
    m = _MEMENTO_RE.match(parts.path)
    if not m:
        return None
    original = m.group(3) + (f"?{parts.query}" if parts.query else "")
    return m.group(2) or "", original


def same_page(requested: str, final: str, cfg: dict) -> bool:
    """Whether a redirect from `requested` ended on the same page. **Pure.**

    The host and the scheme may differ; the path and query must match after
    normalization (module docstring). A web-archive capture matches another capture
    with the same modifier of the same original URL, never a live URL."""
    a, b = urllib.parse.urlsplit(requested), urllib.parse.urlsplit(final)
    ma, mb = _memento(a, cfg), _memento(b, cfg)
    if ma or mb:
        if not (ma and mb) or ma[0] != mb[0]:
            return False
        return same_page(ma[1], mb[1], cfg)
    return _page_key(a) == _page_key(b)


# ------------------------------------------------------------------ the run
def html_title(body: bytes) -> str | None:
    """The `<title>` of an HTML body, whitespace collapsed, or None if it has none."""
    m = _TITLE_RE.search(body)
    if not m:
        return None
    return re.sub(
        r"\s+", " ", html.unescape(m.group(1).decode("utf-8", "replace"))
    ).strip()


def html_shell(body: bytes, cfg: dict) -> str | None:
    """Why an HTML body is a shell and not a document, or None if it is a document.

    A shell is a soft 404 (a "not found" title sent with a 200) or a page whose server
    sends almost no text, leaving the browser's JavaScript to draw it."""
    title = html_title(body) or ""
    for pattern in cfg["html_shell_title_patterns"]:
        if re.search(pattern, title, re.IGNORECASE):
            return f"title {title!r} is a not-found page"
    visible = len(html_text(body))
    if visible < int(cfg["html_min_visible_chars"]):
        return (
            f"{visible} visible characters < html_min_visible_chars "
            f"{cfg['html_min_visible_chars']} (title {title!r})"
        )
    return None


def classify(
    r: dict, cfg: dict, declared_format: str | None = None, url: str | None = None
) -> tuple:
    """`(outcome, reason)` for a response to `url`; reason is None for `fetched`.
    401/403/407/429 are the host declining this client (ai-readiness-kg
    `unobservable_statuses`), not a statement about the document."""
    status = r["status"]
    fmt = (declared_format or "").split()[0].lower() if declared_format else ""
    ctype = (r.get("content_type") or "").split(";", 1)[0].strip().lower()
    if status == 200 and r["body"]:
        if url and not same_page(url, r["final_url"], cfg):
            return "redirected_elsewhere", (
                f"HTTP {status} {r.get('content_type')} from {r['final_url']}, "
                "a different page from the one requested"
            )
        expected = SIGNATURES.get(fmt)
        if expected and not r["body"].lstrip()[:8].startswith(expected):
            return "not_the_document", (
                f"HTTP {status} {r.get('content_type')}, body does "
                f"not start with the {declared_format} signature"
            )
        if fmt == "html" or ctype in HTML_TYPES:
            shell = html_shell(r["body"], cfg)
            if shell:
                return (
                    "script_rendered",
                    f"HTTP {status} {r.get('content_type')}, {shell}",
                )
        return "fetched", None
    if status in (401, 403, 407, 429):
        return "refused_by_host", f"HTTP {status}"
    return "failed", f"HTTP {status}"


def next_rung(outcome: str, got: dict, url: str, cfg: dict) -> str | None:
    """The rung that takes a unit this client did not (DN-002 ADDENDUM-00), or None.

    `operator` (rung 3) only when the response itself shows a credential gate: an
    authentication challenge (`CHALLENGES`), or a redirect that ends on a login path
    (`credential_gate_path_patterns`). Otherwise `browser` (rung 2). A 403 alone is not
    a gate: PHMSA's CDN answers this client 403 and serves a browser (HB-61), and DTIC's
    CAC wall (HB-51) is found by the browser rung, which then names rung 3 itself.
    """
    if outcome not in REFUSALS:
        return None
    if got.get("challenge"):
        return "operator"
    final = got.get("final_url")
    if final and not same_page(url, final, cfg):
        path = urllib.parse.urlsplit(final).path
        if any(
            re.search(p, path, re.IGNORECASE)
            for p in cfg["credential_gate_path_patterns"]
        ):
            return "operator"
    return "browser"


def run(
    entries: list,
    allowlist: tuple,
    cfg: dict,
    log: FetchLog,
    out_dir: Path,
    repo: Path = REPO,
    transport=None,
    clock=None,
    say=print,
    retry=(),
) -> int:
    """Fetch every `plan: fetch` entry not already done. Returns the process exit code:
    0 all units ended, 1 some unit needs a retry (re-run), 3 a ceiling stopped the run.
    """
    clock = clock or RealClock()
    units = [e for e in entries if e["plan"] == "fetch"]
    latest = log.latest_units()
    todo = [
        e
        for e in units
        if e["doc_id"] in retry
        or not completed(latest.get(unit_key(e["doc_id"], e["url"])), repo)
    ]
    say(
        f"[fetch] {len(units)} fetch unit(s); {len(units) - len(todo)} already done; "
        f"{len(todo)} to run"
    )
    log.write(
        {
            "event": "run_start",
            "units": len(units),
            "todo": len(todo),
            "allowlist": list(allowlist),
            "config_sha256": hashlib.sha256(
                json.dumps(cfg, sort_keys=True).encode()
            ).hexdigest(),
        }
    )
    client = PoliteClient(cfg, allowlist, log, transport=transport, clock=clock)
    start, last_progress = clock.now(), clock.now()
    done = failures = total_bytes = 0
    exit_code = 0
    try:
        for e in todo:
            elapsed = clock.now() - start
            if elapsed > float(cfg["ceiling_wall_clock_seconds"]):
                raise Ceiling(
                    f"ceiling_wall_clock_seconds {cfg['ceiling_wall_clock_seconds']} "
                    f"crossed at {elapsed:.0f} s"
                )
            if total_bytes >= int(cfg["ceiling_total_bytes"]):
                raise Ceiling(
                    f"ceiling_total_bytes {cfg['ceiling_total_bytes']} crossed "
                    f"at {total_bytes} bytes"
                )
            key, url = unit_key(e["doc_id"], e["url"]), e["url"]
            client.doc_id = e["doc_id"]
            row = {
                "event": "unit_done",
                "key": key,
                "doc_id": e["doc_id"],
                "url": url,
                "stored_at": None,
                "sha256": None,
                "bytes": 0,
            }
            try:
                got = client.get(url)
            except OffAllowlist as exc:
                got = {"outcome": "blocked_host", "reason": str(exc)}
            except Exception as exc:  # noqa: BLE001 - a failure is a row, not a crash (s15.7)
                got = {"outcome": "failed", "reason": f"{type(exc).__name__}: {exc}"}
            if got["outcome"] == "response":
                outcome, reason = classify(got, cfg, e.get("format"), url)
                row.update(
                    {
                        "status": got["status"],
                        "final_url": got["final_url"],
                        "content_type": got["content_type"],
                    }
                )
                if outcome == "fetched":
                    body = got["body"]
                    out_dir.mkdir(parents=True, exist_ok=True)
                    dest = (
                        out_dir / f"{e['doc_id']}{_extension(got['content_type'], url)}"
                    )
                    tmp = dest.with_suffix(dest.suffix + ".part")
                    with tmp.open("wb") as fh:
                        fh.write(body)
                        fh.flush()
                        os.fsync(fh.fileno())
                    os.replace(tmp, dest)
                    row.update(
                        {
                            "stored_at": str(dest.relative_to(repo)),
                            "sha256": hashlib.sha256(body).hexdigest(),
                            "bytes": len(body),
                            "retrieved_at": _now(),
                            "acquisition_method": ACQUISITION_METHOD,
                            "acquired_by": ACQUIRED_BY,
                        }
                    )
                    total_bytes += len(body)
                else:
                    row["reason"] = reason
                    if outcome == "redirected_elsewhere":
                        row["title"] = html_title(got["body"])
            else:
                outcome = got["outcome"]
                row.update(
                    {k: got[k] for k in ("status", "final_url", "reason") if k in got}
                )
            row["outcome"] = outcome
            rung = next_rung(outcome, got, url, cfg)
            if rung:
                row["next_rung"] = rung
            log.write(row)
            done += 1
            failures += outcome in RETRYABLE
            say(
                f"[fetch] {e['doc_id']}: {outcome}"
                + (f" ({row.get('reason')})" if row.get("reason") else "")
                + (f"; next rung: {rung}" if rung else "")
            )
            if done == int(cfg["pilot_units"]) and len(todo) > done:
                per = (clock.now() - start) / done
                remaining = len(todo) - done
                proj_s, proj_b = per * len(todo), total_bytes / done * len(todo)
                log.write(
                    {
                        "event": "pilot",
                        "units": done,
                        "seconds_per_unit": round(per, 2),
                        "bytes_per_unit": round(total_bytes / done),
                        "projected_seconds": round(proj_s),
                        "projected_bytes": round(proj_b),
                    }
                )
                say(
                    f"[fetch] pilot: {done} units, {per:.1f} s/unit, projected "
                    f"{proj_s:.0f} s and {proj_b / 1e6:.1f} MB for {len(todo)} units "
                    f"({remaining} to go); measured on the pilot"
                )
                if proj_b > int(cfg["ceiling_total_bytes"]):
                    raise Ceiling(
                        f"pilot projects {proj_b:.0f} bytes > ceiling_total_bytes"
                    )
            if done % int(
                cfg["progress_every_units"]
            ) == 0 or clock.now() - last_progress >= float(
                cfg["progress_every_seconds"]
            ):
                last_progress = clock.now()
                rate = done / max(clock.now() - start, 1e-9)
                eta = (len(todo) - done) / rate if rate else None
                prog = {
                    "event": "progress",
                    "done": done,
                    "total": len(todo),
                    "rate_per_s": round(rate, 3),
                    "eta_s": round(eta) if eta is not None else None,
                    "bytes": total_bytes,
                    "failures": failures,
                }
                log.write(prog)
                say(
                    f"[fetch] progress {done}/{len(todo)}, {total_bytes / 1e6:.1f} MB, "
                    f"{failures} failed, eta {prog['eta_s']} s"
                )
    except Ceiling as exc:
        log.write({"event": "ceiling", "reason": str(exc), "done": done})
        say(
            f"[fetch] STOPPED: {exc}. Completed units are in {log.path}; "
            "re-run to resume."
        )
        exit_code = 3
    if exit_code == 0 and failures:
        exit_code = 1
    log.write(
        {
            "event": "run_end",
            "done": done,
            "failures": failures,
            "bytes": total_bytes,
            "exit": exit_code,
        }
    )
    return exit_code


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--sources", type=Path, default=DEFAULTS["sources"])
    ap.add_argument("--allowlist", type=Path, default=DEFAULTS["allowlist"])
    ap.add_argument("--config", type=Path, default=DEFAULTS["config"])
    ap.add_argument("--out-dir", type=Path, default=DEFAULTS["out_dir"])
    ap.add_argument("--log", type=Path, default=DEFAULTS["log"])
    ap.add_argument(
        "--repo",
        type=Path,
        default=REPO,
        help="root that `stored_at` paths are relative to",
    )
    ap.add_argument(
        "--only", nargs="+", metavar="DOC_ID", help="limit to these doc_ids"
    )
    ap.add_argument(
        "--retry",
        nargs="+",
        metavar="DOC_ID",
        default=[],
        help="re-attempt these units even if their latest row is terminal "
        "(the log is append-only; the new row supersedes the old)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="check every fetch URL against the allowlist; contact nothing",
    )
    a = ap.parse_args(argv)
    try:
        cfg = load_config(a.config)
        allowlist = load_allowlist(a.allowlist)
        entries = load_sources(a.sources)
    except ConfigError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    if a.only:
        unknown = set(a.only) - {e["doc_id"] for e in entries}
        if unknown:
            print(
                f"refused: unknown doc_id(s): {', '.join(sorted(unknown))}",
                file=sys.stderr,
            )
            return 2
        entries = [e for e in entries if e["doc_id"] in a.only]
    if a.dry_run:
        plan = []
        for e in entries:
            if e["plan"] != "fetch":
                continue
            try:
                check_url(e["url"], allowlist)
                plan.append({"doc_id": e["doc_id"], "allowed": True})
            except OffAllowlist as exc:
                plan.append(
                    {"doc_id": e["doc_id"], "allowed": False, "reason": str(exc)}
                )
        print(json.dumps({"allowlist": list(allowlist), "plan": plan}, indent=1))
        return 0
    unknown = set(a.retry) - {e["doc_id"] for e in entries}
    if unknown:
        print(
            f"refused: unknown --retry doc_id(s): {', '.join(sorted(unknown))}",
            file=sys.stderr,
        )
        return 2
    out_dir, repo = anchored(a.out_dir, a.repo)
    return run(
        entries,
        allowlist,
        cfg,
        FetchLog(a.log),
        out_dir,
        repo=repo,
        retry=tuple(a.retry),
    )


def anchored(out_dir: Path, repo: Path) -> tuple[Path, Path]:
    """`(out_dir, repo)` made absolute against the working directory. `stored_at` is the
    stored file's path relative to `repo`; a relative `--out-dir` beside the absolute
    default `--repo` made that a ValueError after the file was written and before its
    `unit_done` row (HB-95), so the unit re-ran on the next start."""
    # absolute(), not resolve(): corpus/raw is a symlink in a worktree, and resolving it
    # would move out_dir outside repo.
    return out_dir.absolute(), repo.absolute()


if __name__ == "__main__":
    raise SystemExit(main())
