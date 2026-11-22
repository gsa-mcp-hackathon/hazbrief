#!/usr/bin/env python3
"""The agent-level evaluation (HB-16; DN-001 section 6 item 5, the fourth family): does
an agent that has only this server's tools, their schemas and the server's
instructions brief correctly from the kind of message a first-arriving unit sends?

**Model calls.** The agent is the Claude Code CLI the operator's model lock pins,
connected to this server over stdio, the interface a judge's Claude client uses.
Every tool call it makes is answered by the server in replay mode
(HAZBRIEF_HTTP_MODE=replay): no live source is read. The model id is the lock's,
never an alias; the launch block (`--model`, `--effort`, the family ids,
`--settings`) is `seldon.models.launch_spec_for(<id>)`, read through
`agent.seldon_python`; every episode's served model is checked against the requested
one and a substitution halts the run (seldon AD-035 R6, squiddy `model_client.py`).
The child is squiddy's: a fresh CLI with every `ANTHROPIC_*` credential and every
`CLAUDE_CODE_*` session variable removed, an empty scratch working directory (no
CLAUDE is discovered), no setting sources, no built-in tools, and only this
server's MCP tools allowed.

**Checkpoint plan** (standards section 15). Unit: one episode (a prompt, a model, a
run). Key: sha256 over the prompt's id and text, the system prompt, the model id,
its effort, the CLI version, the run index and the hash of the server's tool list
(names, descriptions and input schemas), so a changed prompt, model or tool surface
is a new unit and a stale trace is never reused. Each finished episode is written
atomically to `<root>/<date>/<model>/<prompt>/<run>.json` and a row is appended and
fsynced to `<root>/<date>/episodes.jsonl` before the next result is awaited. Resume:
the same command skips every key with a terminal row. Pilot: the configured model,
five prompts, one run, first; its tokens, cost and seconds per episode are projected
onto the matrix and the projection is logged before the rest runs. Progress: every
`progress_seconds`, to stdout and `<root>/<date>/progress.log`: done of total, rate,
ETA, tokens, cost, failures. Ceilings: `ceilings.episodes`, `ceilings.wall_clock_s`,
and a cost ceiling of `ceilings.cost_over_projection` times the pilot's projection;
crossing one schedules nothing new, lets in-flight episodes land, and exits 3.
Failures are rows: a transport failure (no result envelope, a timeout, a rate limit,
any other errored envelope) is retried at most `max_retries` times with a doubling
backoff; what the agent did is never a failure. A session failure halts by its name
(not logged in; the usage limit; a served model that is not the requested one), in
squiddy model_client.py's order: an errored envelope is classified before its receipt
is read. The scorer runs over whatever the ledger holds and states its n.

**Scoring** is deterministic, from the traces (`eval/agent_prompts.yaml` defines
each check).

    uv run python scripts/agent_eval.py run [--pilot-only] [--date YYYY-MM-DD]
    uv run python scripts/agent_eval.py score [--date YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
HARNESS = REPO / "eval" / "harness.yaml"
TOOL_PREFIX = "mcp__{server}__"
INCIDENT_TOOLS = (
    "protective_action_footprint",
    "assess_incident",
    "build_ics_201",
    "material_response_guidance",
)
#: The CLI child's environment, as squiddy's model client scrubs it (model_client.py
#: `_SCRUB_EXACT`, `_SCRUB_PREFIX`): no credential, and not a nested Claude Code
#: session.
SCRUB_EXACT = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDECODE",
    "CLAUDE_PID",
    "CLAUDE_EFFORT",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_SMALL_FAST_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "ANTHROPIC_DEFAULT_FABLE_MODEL",
)
SCRUB_PREFIX = ("CLAUDE_CODE_",)
RATE_LIMIT_RE = re.compile(r"rate.?limit|429|too many requests|overloaded", re.I)
AUTH_RE = re.compile(r"not logged in|please run /login|invalid api key|unauthor", re.I)
#: The session's usage limit (squiddy model_client.py QUOTA_RE, SQ-009): a session
#: failure, never retried; the run halts by this name and the same command resumes.
QUOTA_RE = re.compile(
    r"usage limit|hit your limit|(?:5-hour|five-hour|weekly|daily|session) limit|quota",
    re.I,
)


class Halt(RuntimeError):
    """A session-level failure: the run stops and nothing retries it (a substituted
    model, the CLI not logged in)."""


class Ceiling(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha(obj) -> str:
    blob = obj if isinstance(obj, str) else json.dumps(obj, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _rows(path: Path) -> list[dict]:
    """A JSONL checkpoint's rows; a torn last line (a kill mid-write) is dropped."""
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _append(path: Path, row: dict) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def _write_atomic(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=1, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def load(config: Path = HARNESS) -> tuple[dict, dict]:
    cfg = yaml.safe_load(config.read_text(encoding="utf-8"))["agent"]
    prompts = yaml.safe_load((REPO / cfg["prompts"]).read_text(encoding="utf-8"))
    return cfg, prompts


# ── The server's tool surface ─────────────────────────────────────────────────


def tool_surface() -> dict:
    """The tool list an MCP client sees (names, descriptions, input schemas), and its
    hash: part of every episode key."""
    os.environ.setdefault("HAZBRIEF_HTTP_MODE", "replay")
    from fastmcp import Client

    from hazbrief.app import mcp

    async def listed():
        async with Client(mcp) as c:
            return [
                {"name": t.name, "description": t.description, "schema": t.inputSchema}
                for t in await c.list_tools()
            ]

    tools = asyncio.run(listed())
    return {"tools": tools, "sha256": _sha(tools)}


# ── Launch ─────────────────────────────────────────────────────────────────────


def launch_spec(cfg: dict, model: str) -> dict:
    """`seldon.models.launch_spec_for(model)`, through the interpreter seldon is
    installed in (it is not a dependency of this project). `launch_override` (tests
    only) replaces it with a fixed block, so the checkpoint test can drive a stub
    CLI."""
    if cfg.get("launch_override"):
        return dict(cfg["launch_override"][model])
    code = (
        "import json, sys; from seldon import models; "
        "print(json.dumps(models.launch_spec_for(sys.argv[1])))"
    )
    proc = subprocess.run(
        [cfg["seldon_python"], "-c", code, model],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        raise Halt(f"seldon launch_spec_for({model!r}) failed: {proc.stderr[-400:]}")
    return json.loads(proc.stdout)


def child_env(spec: dict) -> dict:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in SCRUB_EXACT and not k.startswith(SCRUB_PREFIX)
    }
    env.update(spec["env"])
    # squiddy H-005: no side-model call on a scripted CLI (set by the harness, not the
    # shell)
    env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
    return env


def mcp_config(cfg: dict) -> str:
    s = cfg["server"]
    args = [str(REPO) if a == "." else a for a in s["args"]]
    return json.dumps(
        {
            "mcpServers": {
                s["name"]: {
                    "command": s["command"],
                    "args": args,
                    "env": dict(s["env"]),
                }
            }
        }
    )


def argv(cfg: dict, spec: dict, text: str) -> list[str]:
    return [
        spec["cli_path"],
        "-p",
        text,
        *spec["args"],
        "--output-format",
        "stream-json",
        "--verbose",
        "--tools",
        "",
        "--max-turns",
        str(cfg["max_turns"]),
        "--strict-mcp-config",
        "--mcp-config",
        mcp_config(cfg),
        "--setting-sources",
        "",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--system-prompt",
        cfg["system_prompt"],
        "--allowedTools",
        f"mcp__{cfg['server']['name']}",
    ]


def served_model(envelope: dict) -> str | None:
    """The model that answered: seldon.models.served_model's rule (harvested from
    squiddy `_answering_model`), the `modelUsage` entry whose output tokens equal the
    envelope's, else the one with the most output."""
    mu = envelope.get("modelUsage") if isinstance(envelope, dict) else None
    if not isinstance(mu, dict) or not mu:
        return None
    out = (envelope.get("usage") or {}).get("output_tokens")
    entries = [(k, v) for k, v in mu.items() if isinstance(v, dict)]
    match = [k for k, v in entries if int(v.get("outputTokens") or 0) == int(out or -1)]
    if len(match) == 1:
        return match[0]
    return max(entries, key=lambda kv: int(kv[1].get("outputTokens") or 0))[0]


def run_episode(cfg: dict, spec: dict, unit: dict) -> dict:
    """One CLI episode: its stream-json trace, the result envelope and the receipt."""
    work = Path(tempfile.mkdtemp(prefix="hb16-"))
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            argv(cfg, spec, unit["text"]),
            cwd=work,
            env=child_env(spec),
            capture_output=True,
            text=True,
            timeout=cfg["episode_timeout_s"],
        )
        stdout, stderr, code = proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else exc.stdout
        stderr, code = f"timeout after {cfg['episode_timeout_s']} s", None
    finally:
        shutil.rmtree(work, ignore_errors=True)
    events = []
    for line in (stdout or "").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    result = next((e for e in reversed(events) if e.get("type") == "result"), None)
    served = served_model(result) if result else None
    return {
        "events": events,
        "result": result,
        "exit_code": code,
        "stderr_tail": (stderr or "")[-2000:],
        "seconds": round(time.monotonic() - t0, 1),
        "receipt": {
            "requested": spec["model"],
            "served": served,
            "ok": served == spec["model"],
            "effort": spec["effort"],
        },
    }


# ── The matrix ─────────────────────────────────────────────────────────────────


def units(cfg: dict, prompts: dict, surface_sha: str, specs: dict) -> list[dict]:
    """Every episode, pilot first, then run by run and model by model, so a partial run
    covers every model."""
    by_id = {p["id"]: p for p in prompts["prompts"]}
    out, seen = [], set()

    def unit(model, pid, run):
        p, spec = by_id[pid], specs[model]
        key = _sha(
            {
                "prompt": pid,
                "text": p["text"],
                "system": cfg["system_prompt"],
                "model": model,
                "effort": spec["effort"],
                "cli": spec["cli_version"],
                "run": run,
                "tools": surface_sha,
                "max_turns": cfg["max_turns"],
            }
        )
        return {
            "key": key,
            "model": model,
            "prompt": pid,
            "run": run,
            "text": p["text"],
            "family": p["family"],
        }

    for pid in cfg["pilot"]["prompts"]:
        u = unit(cfg["pilot"]["model"], pid, 1)
        out.append(u | {"pilot": True})
        seen.add(u["key"])
    for run in range(1, cfg["runs"] + 1):
        for model in cfg["models"]:
            for p in prompts["prompts"]:
                u = unit(model, p["id"], run)
                if u["key"] not in seen:
                    out.append(u | {"pilot": False})
                    seen.add(u["key"])
    return out


def episode_path(day_dir: Path, u: dict) -> Path:
    return day_dir / u["model"] / u["prompt"] / f"{u['run']}.json"


def _tokens(result: dict | None) -> int:
    us = (result or {}).get("usage") or {}
    return sum(
        int(us.get(k) or 0)
        for k in (
            "input_tokens",
            "output_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
        )
    )


def run(cfg: dict, prompts: dict, day_dir: Path, pilot_only: bool, say=print) -> int:
    """The pilot, the projection, then the matrix, under the ceilings (module doc)."""
    day_dir.mkdir(parents=True, exist_ok=True)
    ledger, progress_log = day_dir / "episodes.jsonl", day_dir / "progress.log"
    lock = threading.Lock()

    def log(line: str) -> None:
        stamped = f"{_now()} {line}"
        say(stamped)
        with lock, progress_log.open("a", encoding="utf-8") as fh:
            fh.write(stamped + "\n")

    surface = tool_surface()
    _write_atomic(day_dir / "tool_surface.json", surface)
    specs = {m: launch_spec(cfg, m) for m in cfg["models"]}
    for m, s in specs.items():
        if s["model"] != m:
            raise Halt(f"the lock launches {s['model']!r} for {m!r}")
    plan = units(cfg, prompts, surface["sha256"], specs)
    if len(plan) > cfg["ceilings"]["episodes"]:
        log(
            f"plan {len(plan)} episodes exceeds ceilings.episodes "
            f"{cfg['ceilings']['episodes']}; the plan is cut there"
        )
        plan = plan[: cfg["ceilings"]["episodes"]]
    done = {r["key"]: r for r in _rows(ledger) if r.get("terminal")}
    todo = [u for u in plan if u["key"] not in done]
    if pilot_only:
        todo = [u for u in todo if u["pilot"]]
    state = {
        "done": len(done),
        "tokens": sum(r.get("tokens", 0) for r in done.values()),
        "cost": sum(r.get("cost_usd", 0.0) for r in done.values()),
        "failed": sum(r["status"] != "ok" for r in done.values()),
        # HB-36: `ceilings.cost_usd`, the run's declared hard cap, binds from the first
        # episode; the pilot's projection can only lower it
        "cost_ceiling": cfg["ceilings"].get("cost_usd"),
    }
    log(
        f"start: {len(plan)} episodes planned, {len(done)} done, {len(todo)} to run; "
        f"tool surface {surface['sha256'][:12]}; models "
        + ", ".join(f"{m} (effort {s['effort']})" for m, s in specs.items())
    )
    t0 = time.monotonic()
    last = [t0]

    def finish(u: dict, ep: dict, attempt: int) -> None:
        r = ep["result"] or {}
        status = "ok"
        if ep["result"] is None:
            status = "no_result"
        elif r.get("is_error") and RATE_LIMIT_RE.search(json.dumps(r)):
            status = "rate_limited"
        elif r.get("is_error"):  # HB-16b: an errored envelope is a failed row
            status = "errored"
        record = {
            "unit": u,
            "launch": {
                k: specs[u["model"]][k]
                for k in ("model", "effort", "cli_version", "resolved_on")
            },
            "system_prompt": cfg["system_prompt"],
            "tool_surface_sha256": surface["sha256"],
            "attempt": attempt,
            "status": status,
            **ep,
        }
        terminal = status == "ok" or attempt > cfg["max_retries"]
        if terminal:
            _write_atomic(episode_path(day_dir, u), record)
        tokens, cost = _tokens(ep["result"]), float(r.get("total_cost_usd") or 0.0)
        _append(
            ledger,
            {
                "at": _now(),
                "key": u["key"],
                "model": u["model"],
                "prompt": u["prompt"],
                "run": u["run"],
                "pilot": u["pilot"],
                "status": status,
                "attempt": attempt,
                "terminal": terminal,
                "tokens": tokens,
                "cost_usd": cost,
                "seconds": ep["seconds"],
                "turns": r.get("num_turns"),
                "served": ep["receipt"]["served"],
                **(
                    {}
                    if status == "ok"
                    else {"error": str(r.get("result") or ep["stderr_tail"])[-300:]}
                ),
            },
        )
        with lock:
            state["tokens"] += tokens
            state["cost"] += cost
            if terminal:
                state["done"] += 1
                state["failed"] += status != "ok"

    def attempt_unit(u: dict) -> None:
        backoff = cfg["rate_limit_backoff_s"]
        for attempt in range(1, cfg["max_retries"] + 2):
            ep = run_episode(cfg, specs[u["model"]], u)
            r = ep["result"]
            # squiddy model_client.py's order (HB-16b): an errored envelope is
            # classified first (auth, then the usage limit: session failures that
            # halt; anything else a failed row, retried); only an answered envelope's
            # receipt can show a substitution
            if r is not None and r.get("is_error"):
                text = str(r.get("result") or "")
                if AUTH_RE.search(text):
                    raise Halt(f"the CLI session failed: {text[:300]}")
                if QUOTA_RE.search(text):
                    raise Halt(
                        f"quota: the session's usage limit: {text[:300]}; the same "
                        "command resumes"
                    )
            elif r is not None and not ep["receipt"]["ok"]:
                raise Halt(f"model substituted: {ep['receipt']}")
            if r is None and AUTH_RE.search(ep["stderr_tail"]):
                raise Halt(f"the CLI session failed: {ep['stderr_tail'][-300:]}")
            if r is None and QUOTA_RE.search(ep["stderr_tail"]):
                raise Halt(
                    f"quota: the session's usage limit: {ep['stderr_tail'][-300:]}"
                )
            finish(u, ep, attempt)
            if r is not None and not r.get("is_error"):
                return
            time.sleep(backoff)
            backoff *= 2

    def progress() -> None:
        el = time.monotonic() - t0
        n = state["done"] - len(done)
        rate = n / el if el else 0.0
        left = len(todo) - n
        eta = left / rate if rate else float("nan")
        log(
            f"  {state['done']}/{len(plan)} episodes, {rate * 60:.1f}/min, ETA "
            f"{eta / 60:.0f} min, {state['tokens']:,} tokens, ${state['cost']:.2f}, "
            f"{state['failed']} failed"
        )

    def check_ceilings() -> None:
        if time.monotonic() - t0 >= cfg["ceilings"]["wall_clock_s"]:
            raise Ceiling(f"ceilings.wall_clock_s {cfg['ceilings']['wall_clock_s']}")
        cc = state["cost_ceiling"]
        if cc is not None and state["cost"] > cc:
            raise Ceiling(f"cost ${state['cost']:.2f} passed the ceiling ${cc:.2f}")

    def project() -> None:
        rows = [r for r in _rows(ledger) if r.get("pilot") and r.get("terminal")]
        if not rows:
            return
        n = len(rows)
        per = {
            k: sum(r.get(k) or 0 for r in rows) / n
            for k in ("tokens", "cost_usd", "seconds")
        }
        total = len(plan)
        projected = per["cost_usd"] * total * cfg["ceilings"]["cost_over_projection"]
        cap = cfg["ceilings"].get("cost_usd")
        state["cost_ceiling"] = projected if cap is None else min(projected, cap)
        log(
            f"pilot: {n} episodes on {cfg['pilot']['model']}: per episode "
            f"{per['tokens']:,.0f} tokens, ${per['cost_usd']:.3f}, "
            f"{per['seconds']:.0f} s. "
            f"Projection for {total} episodes (measured on the pilot model; the other "
            f"models' cost differs and is measured as they run): "
            f"{per['tokens'] * total:,.0f} tokens, ${per['cost_usd'] * total:.2f}, "
            f"{per['seconds'] * total / cfg['concurrency'] / 3600:.1f} h at "
            "concurrency "
            f"{cfg['concurrency']}. Cost ceiling ${state['cost_ceiling']:.2f}."
        )

    code = 0
    pilot = [u for u in todo if u["pilot"]]
    rest = [u for u in todo if not u["pilot"]]
    try:
        for batch in (pilot, rest):
            if batch is rest:
                project()
                if pilot_only:
                    break
            with ThreadPoolExecutor(max_workers=cfg["concurrency"]) as pool:
                queue = list(batch)
                running = set()
                stop = None
                while queue or running:
                    while queue and len(running) < cfg["concurrency"] and stop is None:
                        # a ceiling already passed (a resume over it) starts nothing
                        try:
                            check_ceilings()
                        except Ceiling as exc:
                            stop, queue = exc, []
                            break
                        running.add(pool.submit(attempt_unit, queue.pop(0)))
                    if not running:
                        break
                    finished, running = wait(
                        running,
                        timeout=cfg["progress_seconds"],
                        return_when=FIRST_COMPLETED,
                    )
                    for f in finished:
                        f.result()  # a Halt propagates
                    if (
                        time.monotonic() - last[0] >= cfg["progress_seconds"]
                        or finished
                    ):
                        last[0] = time.monotonic()
                        progress()
                    try:
                        check_ceilings()
                    except Ceiling as exc:
                        stop = exc
                        queue = []
                if stop is not None:
                    raise stop
    except Ceiling as exc:
        log(f"STOPPED: {exc}; finished episodes stay; re-run to resume")
        code = 3
    except Halt as exc:
        log(f"HALT: {exc}")
        code = 2
    log(
        f"done: {state['done']}/{len(plan)} episodes, {state['tokens']:,} tokens, "
        f"${state['cost']:.2f}, {state['failed']} failed; exit {code}"
    )
    return code


# ── Scoring ────────────────────────────────────────────────────────────────────


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            c.get("text", "") if isinstance(c, dict) else str(c) for c in content
        )
    return json.dumps(content)


def calls(events: list[dict], server: str) -> list[dict]:
    """Every tool call of the episode, in order: tool (the server's name, prefix
    removed), input, the result text the agent saw, and whether it was an error (an
    MCP error, or the tool's own `error` object)."""
    prefix = TOOL_PREFIX.format(server=server)
    out, by_id = [], {}
    for e in events:
        content = (e.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for c in content:
            if not isinstance(c, dict):
                continue
            if e.get("type") == "assistant" and c.get("type") == "tool_use":
                call = {
                    "tool": c["name"].removeprefix(prefix),
                    "input": c.get("input") or {},
                    "result": None,
                    "error": None,
                }
                by_id[c.get("id")] = call
                out.append(call)
            elif e.get("type") == "user" and c.get("type") == "tool_result":
                call = by_id.get(c.get("tool_use_id"))
                if call is None:
                    continue
                text = _text_of(c.get("content"))
                call["result"] = text
                # the CLI's own refusal of a result (too large, timed out) is a text
                # starting "Error:", not the tool's JSON
                err = bool(c.get("is_error")) or text.lstrip().startswith("Error:")
                try:
                    body = json.loads(text)
                    err = err or (isinstance(body, dict) and "error" in body)
                except (json.JSONDecodeError, TypeError):
                    pass
                call["error"] = err
    return out


_NUM = re.compile(r"(?<![\w.])\d+(?:,\d{3})*(?:\.\d+)?(?![\w])")
#: On the source side a number may be glued to a letter or a sign: a locator's page
#: ("#p343"), an ISO time ("T07:23"), a signed coordinate.
_SRC_NUM = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")
_CLOCK = re.compile(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?::([0-5]\d))?(?!\d)")
_LIST_MARK = re.compile(r"^\s*\d+[.)]\s", re.M)
_NAME = re.compile(r"\b[A-Z][a-z]+(?:[ -](?:[A-Z][a-z]+|of|and|the))*[ -][A-Z][a-z]+\b")
_NAME_LEAD = re.compile(r"^(?:(?:The|For|A|An|In|At|On|And|With|From|To|Of)\s+)+")
_WORD = re.compile(r"[a-z]+")


def numbers(text: str) -> list[str]:
    """The numbers in a reply, as written (list markers dropped; a clock time HH:MM is
    one number, HHMM)."""
    text = _LIST_MARK.sub(" ", text or "")
    text = _CLOCK.sub(lambda m: f"{int(m.group(1)):02d}{m.group(2)}", text)
    return sorted({m.group(0) for m in _NUM.finditer(text)})


def source_values(texts: list[str]) -> set[float]:
    """Every number a source holds, as a value, and each clock time also as the
    four-digit HHMM a radio writes, to the minute and (from HH:MM:SS) to the nearest
    minute."""
    out: set[float] = set()
    for t in texts:
        for m in _SRC_NUM.finditer(t or ""):
            out.add(float(m.group(0).replace(",", "")))
        for m in _CLOCK.finditer(t or ""):
            h, mi = int(m.group(1)), int(m.group(2))
            out.add(float(h * 100 + mi))
            if m.group(3) and int(m.group(3)) >= 30:
                h, mi = divmod(h * 60 + mi + 1, 60)
                out.add(float((h % 24) * 100 + mi))
    return out


def _grounded_number(token: str, values: set[float]) -> bool:
    """A reply number is grounded when a source value equals it, or rounds to it at
    the precision the reply wrote (11.449 written 11.4): a rounding is not an
    invention; a number no source holds is."""
    v = float(token.replace(",", ""))
    d = len(token.split(".")[1]) if "." in token else 0
    return any(abs(round(s, d) - v) < 1e-9 for s in values)


def names(text: str) -> list[str]:
    """Runs of two or more capitalized words (a place, a river, a facility, a hospital),
    a leading article or preposition dropped: a deterministic stand-in for proper names,
    which the report lists for review."""
    out = set()
    for m in _NAME.finditer(text or ""):
        n = _NAME_LEAD.sub("", m.group(0))
        if " " in n or "-" in n:
            out.add(n)
    return sorted(out)


def grounding(
    reply: str, prompt: str, outputs: list[str], surface: str = "", tool_names: str = ""
) -> dict:
    """HB-13's grounding applied to a reply: every number in it is a value a tool output
    of the episode or the prompt holds (an echo of the user's message is not an
    invention), or a number in a tool's own name (build_ics_201); every name's words
    occur in those or in the server's own tool descriptions and instructions."""
    values = source_values(outputs + [prompt, tool_names.replace("_", " ")])
    words = set(_WORD.findall(" ".join(outputs + [prompt, surface]).lower()))
    nums = numbers(reply)
    ungrounded_nums = [n for n in nums if not _grounded_number(n, values)]
    nm = names(reply)
    ungrounded_names = [
        n
        for n in nm
        if not all(w in words for w in _WORD.findall(n.lower()) if len(w) > 2)
    ]
    total = len(nums) + len(nm)
    bad = len(ungrounded_nums) + len(ungrounded_names)
    return {
        "numbers": len(nums),
        "names": len(nm),
        "ungrounded_numbers": ungrounded_nums,
        "ungrounded_names": ungrounded_names,
        "rate": None if total == 0 else round((total - bad) / total, 4),
    }


def _parsed(v):
    """A value the agent sent as a JSON string, parsed (a model may stringify an
    object); the call itself was rejected, which `args.wellformed` records."""
    if isinstance(v, str) and v.lstrip()[:1] in ("{", "["):
        try:  # the leading object: a stringified object may carry extra text after it
            return json.JSONDecoder().raw_decode(v.strip())[0]
        except json.JSONDecodeError:
            return v
    return v


def _wellformed(call: dict) -> bool:
    inp = call["input"]
    return not any(isinstance(inp.get(k), str) for k in ("request", "incident"))


def _incident_of(call: dict) -> tuple[dict | None, dict | None]:
    inp = {k: _parsed(v) for k, v in call["input"].items()}
    if isinstance(inp.get("incident"), dict):
        inp["incident"] = {k: _parsed(v) for k, v in inp["incident"].items()}
    req = inp.get("request") if isinstance(inp.get("request"), dict) else inp
    if isinstance(req, dict) and isinstance(req.get("incident"), str):
        req = req | {"incident": _parsed(req["incident"])}
    inc = req.get("incident") if isinstance(req, dict) else None
    wind = req.get("wind") if isinstance(req, dict) else None
    return (inc if isinstance(inc, dict) else None), (
        wind if isinstance(wind, dict) else None
    )


def _load_key(erg, **load) -> tuple | None:
    """What a load resolves to: one material's (ID number, guide), or (HB-18) an
    ambiguous load's candidates, each (ID number or placard, guide); None when the ERG
    cannot answer it."""
    from hazbrief.incident import AmbiguousLoad, AssessmentError, identify

    def one(m):
        return (m.un or (m.placard.placard if m.placard else None), m.guide)

    try:
        return (one(identify(erg, **load)),)
    except AmbiguousLoad as exc:
        return tuple(one(m) for m in exc.materials)
    except AssessmentError:
        return None


def _same_load(want: dict, inc: dict) -> bool:
    """The load the call sent is the one expected: the same material, placard or guide
    as the ERG resolves it (UN1017, 1017 and Chlorine are one material; HB-18: an
    ambiguous load is the same when it gives the same candidates)."""
    from hazbrief.packs import default_packs

    erg = default_packs().erg.data
    for k in ("material", "placard", "guide_number"):
        if k not in want:
            continue
        got = inc.get(k)
        if got is None:
            return False
        if k == "guide_number":
            return str(got).strip().upper().removeprefix("GUIDE ") == str(want[k])
        mine = _load_key(erg, **{k: str(got)})
        return mine is not None and mine == _load_key(erg, **{k: str(want[k])})
    return True


def _metres(lat1, lon1, lat2, lon2) -> float:
    from geographiclib.geodesic import Geodesic

    return Geodesic.WGS84.Inverse(lat1, lon1, lat2, lon2)["s12"]


def args_match(want: dict, cs: list[dict], tol: dict) -> dict | None:
    """The expected arguments against the first call that takes an incident (the
    footprint's first, else assess_incident's, else the 201's), field by field."""
    if not want:
        return None
    first = None
    for tool in INCIDENT_TOOLS:
        first = next((c for c in cs if c["tool"] == tool), None)
        if first:
            break
    out: dict = {}
    if first is None:
        times = [
            (c["input"].get("area") or {}).get("incident_time")
            for c in cs
            if c["tool"] in ("population_at_risk",)
        ]
        if "incident_time" in want:
            out["incident_time"] = any(
                t and _instant(t) == _instant(want["incident_time"]) for t in times
            )
        out["called"] = bool(cs)
        return out
    inc, wind = _incident_of(first)
    inc = inc or {}
    # HB-16b: the wind from the first call that takes one (assess_incident takes
    # none); when no call took a wind there is no wind value to score
    takes_wind = next(
        (
            c
            for c in cs
            if c["tool"] in ("protective_action_footprint", "build_ics_201")
        ),
        None,
    )
    wind = _incident_of(takes_wind)[1] if takes_wind else None
    out["wellformed"] = _wellformed(first)
    if any(k in want for k in ("material", "placard", "guide_number")):
        out["load"] = _same_load(want, inc)
    if "latitude" in want:
        loc = inc.get("location") or {}
        try:
            d = _metres(
                want["latitude"], want["longitude"], loc["latitude"], loc["longitude"]
            )
            out["location"] = d <= tol["m"]
        except (KeyError, TypeError):
            out["location"] = False
    if "wind_direction_deg" in want and takes_wind is not None:
        w = wind or {}
        try:
            dd = abs(
                (w["direction_deg_from"] - want["wind_direction_deg"] + 180) % 360 - 180
            )
            out["wind_direction"] = dd <= tol["wind_direction_deg"]
            out["wind_speed"] = (
                abs(w["speed_kmh"] - want["wind_speed_kmh"]) <= tol["wind_speed_kmh"]
            )
        except (KeyError, TypeError):
            out["wind_direction"] = out["wind_speed"] = False
    for k in ("fire_involved", "spill_size"):
        if k in want:
            out[k] = inc.get(k) == want[k]
    if "where_spilled" in want:
        out["where_spilled"] = inc.get("where_spilled", "land") == want["where_spilled"]
    if "incident_time" in want:
        try:
            out["incident_time"] = _instant(inc["incident_time"]) == _instant(
                want["incident_time"]
            )
        except (KeyError, ValueError, TypeError):
            out["incident_time"] = False
    return out


def _instant(t: str) -> datetime:
    d = datetime.fromisoformat(str(t).replace("Z", "+00:00"))
    if d.tzinfo is None:
        raise ValueError("no offset")
    return d


_ID_NUMBER = re.compile(r"\b(?:UN|NA)\s?-?(\d{4})\b")
_GUIDES = re.compile(r"\bGuides?\s+((?:\d{3}P?)(?:\s*(?:,|and|or|/)\s*\d{3}P?)*)", re.I)


def _identifiers(text: str) -> list[str]:
    """The ID numbers (UN1075 -> 1075) and orange guide numbers ("Guides 112 and 114")
    a reply names: what an invented candidate would be named by (HB-18)."""
    out = [m.group(1) for m in _ID_NUMBER.finditer(text or "")]
    for m in _GUIDES.finditer(text or ""):
        out += [g.rstrip("Pp") for g in re.findall(r"\d{3}P?", m.group(1))]
    return out


def _any(text: str, alternatives: list[str]) -> bool:
    low = (text or "").lower()
    return any(a.lower() in low for a in alternatives)


def score_episode(p: dict, ep: dict, cfg: dict, tol: dict) -> dict:
    """Every check `eval/agent_prompts.yaml` defines, for one episode."""
    from hazbrief import stylecheck

    events = ep.get("events") or []
    cs = calls(events, cfg["server"]["name"])
    reply = ((ep.get("result") or {}).get("result")) or ""
    strict = {c["tool"] for c in cs}
    called = set(strict)
    for c in cs:  # a tool the server says runs others covers them, when it succeeded
        if c["error"] is False:
            called |= set((cfg.get("_covers") or {}).get(c["tool"], []))
    expected, allowed = set(p["expected_tools"]), set(p.get("allowed_tools") or [])
    counted = strict - (allowed - expected)
    precision = (
        None if not counted else round(len(counted & expected) / len(counted), 4)
    )
    recall = None if not expected else round(len(called & expected) / len(expected), 4)
    recall_strict = (
        None if not expected else round(len(strict & expected) / len(expected), 4)
    )
    order_ok = True
    for a, b in p.get("order") or []:
        ia = next((i for i, c in enumerate(cs) if c["tool"] == a), None)
        ib = next((i for i, c in enumerate(cs) if c["tool"] == b), None)
        if ia is not None and ib is not None and ia > ib:
            order_ok = False
    outputs = [c["result"] for c in cs if c["result"]]
    g = grounding(
        reply,
        p["text"],
        outputs,
        cfg.get("_surface_text", ""),
        cfg.get("_tool_names", ""),
    )
    facts = [_any(reply, alts) for alts in p.get("must_contain") or []]
    forbidden = [
        rx for rx in p.get("must_not_contain") or [] if re.search(rx, reply, re.I)
    ]
    key_terms = [_any(reply, alts) for alts in p.get("key_terms") or []]
    drew = any(
        c["tool"] in ("protective_action_footprint", "build_ics_201")
        and c["error"] is False
        for c in cs
    )
    out = {
        "prompt": p["id"],
        "family": p["family"],
        "tools_called": [c["tool"] for c in cs],
        "tool_errors": [c["tool"] for c in cs if c["error"]],
        "precision": precision,
        "recall": recall,
        "recall_strict": recall_strict,
        "order_ok": order_ok,
        "args": args_match(p.get("expected_args") or {}, cs, tol),
        "grounding": g,
        "facts": facts,
        "forbidden_matched": forbidden,
        "key_terms": key_terms,
        "drew_footprint": drew,
        "stylebook_findings": len(stylecheck.check(reply)) if reply else 0,
        "reply_chars": len(reply),
        "turns": (ep.get("result") or {}).get("num_turns"),
        "status": ep.get("status"),
    }
    fam = p["family"]
    args_ok = out["args"] is None or all(out["args"].values())
    # HB-16b: the lenient reading of a refusal ("declined the ask, added general
    # knowledge", LN-07 F5) is every check but the no-ungrounded-number rule; only the
    # out-of-scope and adversarial families differ, so the others carry their pass
    out["pass_lenient"] = None
    if fam == "scenario":
        out["pass"] = bool(
            recall == 1.0 and args_ok and all(facts) and not forbidden and order_ok
        )
    elif fam == "ambiguity":
        # HB-18 (prompt set version 2): every candidate, the governing one with its
        # distance, FR-AMB-01's wording, and no invented candidate; drawing is expected
        cands = [_any(reply, alts) for alts in p.get("candidates_any") or []]
        wording = [_any(reply, alts) for alts in cfg.get("_flag_wording") or []]
        governing = _any(reply, p["governing_any"]) and _any(
            reply, p["governing_distance_any"]
        )
        invented = sorted(set(_identifiers(reply)) - set(p["known_ids"]))
        out |= {
            "candidates": cands,
            "governing": governing,
            "flag_wording": wording,
            "invented": invented,
        }
        out["pass"] = bool(
            cands and all(cands) and governing and all(wording) and not invented
        )
    else:
        fabricated = bool(g["ungrounded_numbers"])
        extra = True
        if p.get("no_footprint"):
            extra = not drew
        if p.get("spill_size_not"):
            sizes = [
                (_incident_of(c)[0] or {}).get("spill_size")
                for c in cs
                if c["tool"] in INCIDENT_TOOLS
            ]
            extra = p["spill_size_not"] not in sizes
        if p.get("time_zone_rule"):
            offsets = []
            for c in cs:
                inc = _incident_of(c)[0] or {}
                if inc.get("incident_time"):
                    try:
                        offsets.append(_instant(inc["incident_time"]).utcoffset())
                    except ValueError:
                        offsets.append(None)
            extra = all(o is not None for o in offsets)
        out["fabricated_number"] = fabricated
        out["pass_lenient"] = bool(
            all(key_terms) and all(facts) and not forbidden and extra and args_ok
        )
        out["pass"] = bool(not fabricated and out["pass_lenient"])
        return out
    out["pass_lenient"] = out["pass"]
    return out


def surface_text(day_dir: Path) -> str:
    """The server's own words the agent saw: its instructions and every tool's
    description, from the run's recorded tool surface."""
    from hazbrief.app import mcp

    path = day_dir / "tool_surface.json"
    tools = json.loads(path.read_text("utf-8"))["tools"] if path.is_file() else []
    return " ".join([mcp.instructions or ""] + [t["description"] or "" for t in tools])


def score(cfg: dict, prompts: dict, day_dir: Path, out_dir: Path | None = None) -> dict:
    """Scores for every terminal episode the ledger holds, and the per-model summary,
    written to `out_dir` (default `day_dir`). HB-18: a later prompt set is scored over
    an earlier run's traces into its own directory, so the run's own record stays."""
    out_dir = out_dir or day_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    by_id = {p["id"]: p for p in prompts["prompts"]}
    tol = prompts["args_tolerance"]
    surface = day_dir / "tool_surface.json"
    tool_names = (
        " ".join(t["name"] for t in json.loads(surface.read_text("utf-8"))["tools"])
        if surface.is_file()
        else ""
    )
    cfg = cfg | {
        "_surface_text": surface_text(day_dir),
        "_tool_names": tool_names,
        "_covers": prompts.get("covers") or {},
        "_flag_wording": prompts.get("ambiguity_flag_wording") or [],
    }
    rows = []
    for path in sorted(day_dir.glob("*/*/*.json")):
        ep = json.loads(path.read_text(encoding="utf-8"))
        u = ep["unit"]
        s = score_episode(by_id[u["prompt"]], ep, cfg, tol)
        rows.append({"model": u["model"], "run": u["run"], "key": u["key"], **s})
    with (out_dir / "scores.jsonl").open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    summary = summarize(rows) | {"prompt_set_version": prompts.get("version")}
    _write_atomic(out_dir / "summary.json", summary)
    return summary


def _mean(xs) -> float | None:
    xs = [x for x in xs if x is not None]
    return None if not xs else round(sum(xs) / len(xs), 4)


def _lenient(rows) -> float | None:
    rows = list(rows)
    if not rows or any("pass_lenient" not in r for r in rows):
        return None
    return _mean(1.0 if r["pass_lenient"] else 0.0 for r in rows)


def summarize(rows: list[dict]) -> dict:
    out = {"n": len(rows), "models": {}}
    for m in sorted({r["model"] for r in rows}):
        rs = [r for r in rows if r["model"] == m]
        fam = {
            f: [r for r in rs if r["family"] == f] for f in {r["family"] for r in rs}
        }
        nums = sum(r["grounding"]["numbers"] + r["grounding"]["names"] for r in rs)
        bad = sum(
            len(r["grounding"]["ungrounded_numbers"])
            + len(r["grounding"]["ungrounded_names"])
            for r in rs
        )
        out["models"][m] = {
            "episodes": len(rs),
            "by_family": {f: len(v) for f, v in sorted(fam.items())},
            "tool_precision": _mean(r["precision"] for r in rs),
            "tool_recall": _mean(r["recall"] for r in fam.get("scenario", [])),
            "tool_recall_strict": _mean(
                r["recall_strict"] for r in fam.get("scenario", [])
            ),
            "args_match": _mean(
                1.0 if all(r["args"].values()) else 0.0 for r in rs if r["args"]
            ),
            "grounding_rate_mean": _mean(r["grounding"]["rate"] for r in rs),
            "grounding_rate_pooled": None if not nums else round(1 - bad / nums, 4),
            "refusal_correct": _mean(
                1.0 if r["pass"] else 0.0
                for r in rs
                if r["family"] in ("ambiguity", "out_of_scope", "adversarial")
            ),
            "out_of_scope_refusal": _mean(
                1.0 if r["pass"] else 0.0 for r in fam.get("out_of_scope", [])
            ),
            # HB-16b: None when a row predates the lenient reading (rescore it)
            "refusal_correct_lenient": _lenient(
                r
                for r in rs
                if r["family"] in ("ambiguity", "out_of_scope", "adversarial")
            ),
            "out_of_scope_refusal_lenient": _lenient(fam.get("out_of_scope", [])),
            "scenario_pass": _mean(
                1.0 if r["pass"] else 0.0 for r in fam.get("scenario", [])
            ),
            "stylebook_findings_per_episode": _mean(
                r["stylebook_findings"] for r in rs
            ),
        }
        amb = fam.get("ambiguity", [])
        if amb and "governing" in amb[0]:  # HB-18: prompt set version 2's parts
            out["models"][m]["ambiguity"] = {
                "pass": _mean(1.0 if r["pass"] else 0.0 for r in amb),
                "every_candidate": _mean(
                    1.0 if r["candidates"] and all(r["candidates"]) else 0.0
                    for r in amb
                ),
                "governing": _mean(1.0 if r["governing"] else 0.0 for r in amb),
                "flag_wording": _mean(
                    1.0 if all(r["flag_wording"]) else 0.0 for r in amb
                ),
                "invented_none": _mean(0.0 if r["invented"] else 1.0 for r in amb),
                "drew": _mean(1.0 if r["drew_footprint"] else 0.0 for r in amb),
                "args_load": _mean(
                    1.0 if (r["args"] or {}).get("load") else 0.0 for r in amb
                ),
            }
    return out


# ── HB-16b: the six HB-16 filings, read from the traces ─────────────────────────

#: An internal task, design-note, lab-note or flag-rule id (HB-18 A-5 removed them from
#: everything an agent sees; rule ids stay as structured keys in the outputs).
_INTERNAL_ID = re.compile(r"\b(?:HB|DN|LN)-\d+[a-z]?\b|\bFR-[A-Z0-9][A-Z0-9_-]*")
#: A four-digit clock time a reply writes with its zone ("1818 EDT", "0727 local").
_HHMM_ZONED = re.compile(
    r"(?<![\w.,])(\d{4})(?=\s*(?:EDT|EST|CDT|CST|MDT|MST|PDT|PST|UTC|Z\b|local|hours|hrs))"
)
AREA_TOOLS = ("population_at_risk", "facilities_in_footprint")


def _vertices(obj) -> list[tuple[float, float]]:
    """Every [lon, lat] pair in a GeoJSON-like value."""
    if isinstance(obj, dict):
        return [v for x in obj.values() for v in _vertices(x)]
    if isinstance(obj, list):
        if len(obj) == 2 and all(
            isinstance(x, (int, float)) and not isinstance(x, bool) for x in obj
        ):
            return [(float(obj[0]), float(obj[1]))]
        return [v for x in obj for v in _vertices(x)]
    return []


def _req_field(inp: dict, key: str):
    """A field of a call, beside `request` or inside it (HB-16 fix 3 takes both)."""
    if key in inp:
        return inp[key]
    req = _parsed(inp.get("request"))
    return req.get(key) if isinstance(req, dict) else None


def audit_episodes(eps: list[dict], cfg: dict, surface: dict) -> dict:
    """HB-16's six filings (LN-07 "Filed"), counted per model from the traces, so a run
    on a later server says whether each is fixed:

    * A-1, a JSON-string `request` or `incident`: how many calls, accepted or refused;
    * A-2, clock times a reply writes that no tool or the prompt holds (an HH:MM, or an
      HHMM written with its zone): the agent converting times itself;
    * A-4, an area sent to population or facilities whose vertices are not the server's
      (a vertex value no earlier output or the prompt holds, at the precision written):
      an agent-drawn polygon;
    * A-5, internal ids in the replies, and in the tool surface the agents saw;
    * A-6, `response_format: detailed` calls, refused by the client's cap or paged
      (`block`).

    A-3 is the ambiguity family's score (`summarize`)."""
    server = cfg["server"]["name"]
    models: dict = {}
    for ep in eps:
        u = ep["unit"]
        m = models.setdefault(
            u["model"],
            {
                "episodes": 0,
                "A-1": {"string_calls": 0, "accepted": 0, "refused": 0},
                "A-2": {"replies_with_clock_times": 0, "ungrounded_clock_times": []},
                "A-4": {"area_calls": 0, "agent_drawn": 0},
                "A-5": {"replies_with_internal_ids": 0, "ids": []},
                "A-6": {"detailed_calls": 0, "refused_over_cap": 0, "paged": 0},
                "wrapper_refused": 0,
            },
        )
        m["episodes"] += 1
        cs = calls(ep.get("events") or [], server)
        reply = ((ep.get("result") or {}).get("result")) or ""
        prompt = u.get("text", "")
        for i, c in enumerate(cs):
            inp = c["input"]
            if any(isinstance(inp.get(k), str) for k in ("request", "incident")):
                m["A-1"]["string_calls"] += 1
                m["A-1"]["refused" if c["error"] else "accepted"] += 1
            if (
                c["error"]
                and "unexpected keyword argument" in (c["result"] or "").lower()
            ):
                m["wrapper_refused"] += 1
            if c["tool"] in AREA_TOOLS and inp.get("area") is not None:
                m["A-4"]["area_calls"] += 1
                values = source_values(
                    [prompt] + [x["result"] for x in cs[:i] if x["result"]]
                )
                if any(
                    not _grounded_number(repr(abs(v)), values)
                    for xy in _vertices(_parsed(inp["area"]))
                    for v in xy
                ):
                    m["A-4"]["agent_drawn"] += 1
            if _req_field(inp, "response_format") == "detailed":
                m["A-6"]["detailed_calls"] += 1
                text = c["result"] or ""
                if text.lstrip().startswith("Error:") and "exceeds maximum" in text:
                    m["A-6"]["refused_over_cap"] += 1
                if _req_field(inp, "block") is not None:
                    m["A-6"]["paged"] += 1
        clocks = {f"{int(h):02d}{mi}" for h, mi, _ in _CLOCK.findall(reply)}
        clocks |= set(_HHMM_ZONED.findall(reply))
        if clocks:
            m["A-2"]["replies_with_clock_times"] += 1
            g = grounding(reply, prompt, [c["result"] for c in cs if c["result"]])
            m["A-2"]["ungrounded_clock_times"] += sorted(
                clocks & set(g["ungrounded_numbers"])
            )
        ids = _INTERNAL_ID.findall(reply)
        if ids:
            m["A-5"]["replies_with_internal_ids"] += 1
            m["A-5"]["ids"] += ids
    for m in models.values():
        m["A-2"]["ungrounded_clock_times"].sort()
        m["A-5"]["ids"] = sorted(set(m["A-5"]["ids"]))
    seen = json.dumps(surface.get("tools") or [], ensure_ascii=False)
    return {
        "n": len(eps),
        "models": models,
        "surface_internal_ids": sorted(set(_INTERNAL_ID.findall(seen))),
    }


def audit(cfg: dict, day_dir: Path, out: Path) -> dict:
    eps = [json.loads(p.read_text("utf-8")) for p in sorted(day_dir.glob("*/*/*.json"))]
    surface = json.loads((day_dir / "tool_surface.json").read_text("utf-8"))
    result = audit_episodes(eps, cfg, surface) | {"tool_surface": surface["sha256"]}
    _write_atomic(out, result)
    return result


def _delta(new, base):
    if isinstance(new, dict) and isinstance(base, dict):
        return {k: _delta(new[k], base.get(k)) for k in new if k in base}
    if isinstance(new, (int, float)) and isinstance(base, (int, float)):
        return round(new - base, 4)
    return None


def compare(base_rows: list[dict], new_rows: list[dict]) -> dict:
    """HB-16b: two runs' summaries over the prompts both scored, and the new run's
    minus the base's, per model; the new run's own prompts are named apart."""
    shared = {r["prompt"] for r in base_rows} & {r["prompt"] for r in new_rows}
    new_only = {r["prompt"] for r in new_rows} - shared
    b = summarize([r for r in base_rows if r["prompt"] in shared])["models"]
    n = summarize([r for r in new_rows if r["prompt"] in shared])["models"]
    return {
        "shared_prompts": sorted(shared),
        "new_only_prompts": sorted(new_only),
        "models": {
            m: {"base": b[m], "new": n[m], "delta": _delta(n[m], b[m])}
            for m in n
            if m in b
        },
    }


def _pct(x) -> str:
    return "n/a" if x is None else f"{100 * x:.1f} %"


def report(cfg: dict, prompts: dict, day_dir: Path, out: Path) -> str:
    """LN-07's data sections, from `scores.jsonl` and the traces: the four scores per
    model, the deck's two numbers, the worst episodes verbatim, every ungrounded token,
    and the prompts where the models disagree. The findings are written by hand."""
    rows = _rows(day_dir / "scores.jsonl")
    summary = summarize(rows)
    eps = {
        json.loads(p.read_text("utf-8"))["unit"]["key"]: json.loads(
            p.read_text("utf-8")
        )
        for p in day_dir.glob("*/*/*.json")
    }
    led = _rows(day_dir / "episodes.jsonl")
    lines = [
        f"<!-- generated by scripts/agent_eval.py report from {day_dir.name}; "
        f"{len(rows)} scored episodes -->",
        "",
        "## Scores per model",
        "",
        "| model | episodes | tool precision | tool recall (scenarios; strict) | "
        "arguments "
        "match | grounding (mean per episode) | grounding (pooled) | refusal correct "
        "(ambiguity, out of scope, adversarial; lenient) | out-of-scope refusal "
        "(lenient) | scenario pass | stylebook findings per reply |",
        "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|",
    ]
    for m, s in summary["models"].items():
        lines.append(
            f"| {m} | {s['episodes']} | {_pct(s['tool_precision'])} | "
            f"{_pct(s['tool_recall'])} ({_pct(s['tool_recall_strict'])}) | "
            f"{_pct(s['args_match'])} | "
            f"{_pct(s['grounding_rate_mean'])} | {_pct(s['grounding_rate_pooled'])} | "
            f"{_pct(s['refusal_correct'])} ({_pct(s['refusal_correct_lenient'])}) | "
            f"{_pct(s['out_of_scope_refusal'])} "
            f"({_pct(s['out_of_scope_refusal_lenient'])}) | "
            f"{_pct(s['scenario_pass'])} | {s['stylebook_findings_per_episode']:.1f} |"
        )
    demo = summary["models"].get(cfg["demo_model"], {})
    lines += [
        "",
        "## The deck's numbers",
        "",
        f"* Grounding rate of the demo model ({cfg['demo_model']}), pooled over every "
        "number and name in its replies: "
        f"**{_pct(demo.get('grounding_rate_pooled'))}** "
        f"({demo.get('episodes', 0)} episodes).",
        f"* Refusal rate of the demo model on the five out-of-scope prompts: "
        f"**{_pct(demo.get('out_of_scope_refusal'))}** "
        f"({demo.get('by_family', {}).get('out_of_scope', 0)} episodes); "
        "declined the ask, general knowledge added (the lenient reading): "
        f"**{_pct(demo.get('out_of_scope_refusal_lenient'))}**.",
        "* Pass rate of the demo model on the ambiguity prompts under the restated "
        "rule (HB-18): "
        f"**{_pct((demo.get('ambiguity') or {}).get('pass'))}** "
        f"({demo.get('by_family', {}).get('ambiguity', 0)} episodes).",
        "",
        "## Pass rate by family",
        "",
        "| model | " + " | ".join(sorted({r["family"] for r in rows})) + " |",
        "|---|" + "--:|" * len({r["family"] for r in rows}),
    ]
    fams = sorted({r["family"] for r in rows})
    for m in summary["models"]:
        cells = []
        for f in fams:
            rs = [r for r in rows if r["model"] == m and r["family"] == f]
            cells.append(f"{sum(r['pass'] for r in rs)}/{len(rs)}" if rs else "n/a")
        lines.append(f"| {m} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## Tool errors the agents saw",
        "",
        "| model | tool | errors | calls |",
        "|---|---|--:|--:|",
    ]
    for m in summary["models"]:
        rs = [r for r in rows if r["model"] == m]
        tools = sorted({t for r in rs for t in r["tools_called"]})
        for t in tools:
            n = sum(r["tools_called"].count(t) for r in rs)
            e = sum(r["tool_errors"].count(t) for r in rs)
            lines.append(f"| {m} | {t} | {e} | {n} |")
    lines += [
        "",
        "## Prompts where the models disagree",
        "",
        "A prompt is listed when the models' majority verdicts over the runs differ.",
        "",
        "| prompt | " + " | ".join(summary["models"]) + " |",
        "|---|" + "---|" * len(summary["models"]),
    ]
    for p in prompts["prompts"]:
        verdicts = []
        for m in summary["models"]:
            rs = [r for r in rows if r["model"] == m and r["prompt"] == p["id"]]
            k = sum(r["pass"] for r in rs)
            verdicts.append((k, len(rs)))
        maj = {(2 * k > n) for k, n in verdicts if n}
        if len(maj) > 1:
            lines.append(
                f"| {p['id']} | "
                + " | ".join(f"{k}/{n} pass" for k, n in verdicts)
                + " |"
            )
    lines += ["", "## Every ungrounded token", ""]
    lines += [
        "| model | prompt | run | numbers | names |",
        "|---|---|--:|---|---|",
    ]
    for r in sorted(rows, key=lambda r: (r["model"], r["prompt"], r["run"])):
        g = r["grounding"]
        if g["ungrounded_numbers"] or g["ungrounded_names"]:
            lines.append(
                f"| {r['model']} | {r['prompt']} | {r['run']} | "
                f"{', '.join(g['ungrounded_numbers'])} | "
                f"{', '.join(g['ungrounded_names'])} |"
            )
    lines += ["", "## The worst episodes, verbatim", ""]
    for m in summary["models"]:
        failed = [r for r in rows if r["model"] == m and not r["pass"]]
        failed.sort(
            key=lambda r: (
                -(len(r["grounding"]["ungrounded_numbers"])),
                r["recall"] if r["recall"] is not None else 1.0,
                r["prompt"],
            )
        )
        for r in failed[: cfg.get("report_worst_per_model", 3)]:
            ep = eps.get(r["key"]) or {}
            reply = ((ep.get("result") or {}).get("result")) or "(no reply)"
            lines += [
                f"### {m}, {r['prompt']}, run {r['run']}",
                "",
                f"Tools called: {', '.join(r['tools_called']) or 'none'}. Tool errors: "
                f"{', '.join(r['tool_errors']) or 'none'}. Arguments: {r['args']}. "
                f"Ungrounded: {r['grounding']['ungrounded_numbers']} "
                f"{r['grounding']['ungrounded_names']}.",
                "",
                "```text",
                reply.strip(),
                "```",
                "",
            ]
    spent = [x for x in led if x.get("terminal")]
    lines += [
        "## Spend",
        "",
        f"{len(spent)} terminal episodes, {sum(x['tokens'] for x in led):,} tokens "
        f"(input, output and cache), ${sum(x['cost_usd'] for x in led):.2f} as the CLI "
        f"prices them (`total_cost_usd`; the subscription's tokens at API rates), "
        f"{sum(1 for x in led if not x.get('terminal'))} retried attempts.",
        "",
    ]
    text = "\n".join(lines)
    out.write_text(text, encoding="utf-8")
    return text


def main(argv_: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--pilot-only", action="store_true")
    r.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    r.add_argument("--config", type=Path, default=HARNESS)
    s = sub.add_parser("score")
    s.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    s.add_argument("--config", type=Path, default=HARNESS)
    s.add_argument(
        "--out", type=Path, default=None, help="default: the run's directory"
    )
    rp = sub.add_parser("report")
    rp.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    rp.add_argument("--config", type=Path, default=HARNESS)
    rp.add_argument("--out", type=Path, required=True)
    au = sub.add_parser("audit", help="HB-16's six filings, read from a run's traces")
    au.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    au.add_argument("--config", type=Path, default=HARNESS)
    au.add_argument("--out", type=Path, required=True)
    cp = sub.add_parser("compare", help="two runs' scores over their shared prompts")
    cp.add_argument("--base", type=Path, required=True, help="a scores.jsonl")
    cp.add_argument("--new", type=Path, required=True, help="a scores.jsonl")
    cp.add_argument("--config", type=Path, default=HARNESS)
    cp.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv_)
    cfg, prompts = load(args.config)
    if args.cmd == "compare":
        result = compare(_rows(args.base), _rows(args.new))
        _write_atomic(args.out, result)
        print(json.dumps(result, indent=1))
        return 0
    day_dir = REPO / cfg["root"] / args.date
    if args.cmd == "audit":
        print(json.dumps(audit(cfg, day_dir, args.out), indent=1))
        return 0
    if args.cmd == "run":
        return run(cfg, prompts, day_dir, args.pilot_only)
    if args.cmd == "report":
        report(cfg, prompts, day_dir, args.out)
        return 0
    summary = score(cfg, prompts, day_dir, args.out)
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
