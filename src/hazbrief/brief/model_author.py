"""The brief's model: a narrative author and the question box, one class behind one
prompt file (DN-022 section 5; DN-011 D4; HB-131R items 4 and 5).

`ModelAuthor` implements `author.NarrativeAuthor` (`write`) and adds `ask`. Both make
one call of the pinned Claude Code CLI in print mode (AD-035): `seldon models resolve
<role> --json` gives the model id, the CLI's path and its arguments, and `seldon models
hold --run <name>` holds the model lock around the call, so a refresh cannot move the
lock under it. The call has no tools (`--tools ""`, `--strict-mcp-config`), keeps no
session, and runs from an empty directory, so no project memory is read into it. The
system prompt is `prompts/brief_model.md`, the one file both entry points read.

**Read-only by construction** (HB-131R item 5). The model is given text and returns
text. Nothing here adds a layer, changes a number, runs a model or calls a tool: the
only operations are `write` (a section's Markdown) and `ask` (sentences, each with a
receipt, and at most one view proposal the page applies and the reader can undo).

**Checked before it is shown** (item 4). An answer is refused, as a structured error,
when it cites a receipt that is not a record of the brief's record set, carries a
number no record holds, names a tool the orchestrator does not run, or proposes a view
the page does not have. "A number a record holds" is read as: the number appears in a
record's body or the record itself, in a record's DN-010 D4 label line, or in the
brief's rendered sections, which are the deterministic rendering of those records and
`now` (DN-011 D7 test d). Numbers are compared by value, with thousands separators and
signs dropped ("1,609.0" is 1609).

**Recorded and replayable** (item 4; standards section 15). Each call is keyed by the
sha256 of its request (the prompt file's hash, the model id, the entry point and the
input), and written, before it is used, to `<transcripts>/<key>.json` with the
request, the response, both hashes and the checked answer. A key already held is read,
not asked again, so a replay answers from the record with no call (`calls_made` 0) and
re-running a recording is its resume. A failed call is a row (its exit code and its
error) and is asked again at most `model.max_attempts` times in all.

The application's code, not the server's: the container image ships without
`src/hazbrief/brief/` (`.dockerignore`).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

from hazbrief.brief.author import NoAuthor
from hazbrief.config import REPO_ROOT
from hazbrief.evidence import labels as L
from hazbrief.packs import canonical_json

#: one subprocess run: (argv, stdin text, env, timeout s, cwd) -> (exit, stdout, stderr)
Runner = Callable[[list[str], str, dict, float, str], tuple[int, str, str]]


class ModelRouteError(RuntimeError):
    """The model route cannot be used: the lock does not resolve, or a replay holds
    no record of the call. The message says which."""


class NoRecordedCall(ModelRouteError):
    """A replay was asked a call it holds no transcript of."""


# ── the brief as the model is shown it ───────────────────────────────────────────────


class _Text(HTMLParser):
    """The visible text of an HTML fragment: no script, style or SVG, one line per
    text node, whitespace collapsed."""

    SKIP = ("script", "style", "svg")

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.lines.append(" ".join(data.split()))


def visible_text(fragment: str) -> str:
    p = _Text()
    p.feed(fragment)
    p.close()
    return "\n".join(p.lines)


class _MapControls(HTMLParser):
    """The layer switches (`#layer-list input[data-layer]`) and the wind stepper's
    hours (`#wind-hour`'s max) a map fragment holds: what a view proposal may name."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.layers: list[dict] = []
        self.hour_max: int | None = None
        self._label: dict | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "input" and a.get("data-layer"):
            # the switch's name is the label's first text after it (the swatch before
            # the title is an empty span)
            self._label = {"id": a["data-layer"], "on": "checked" in a, "name": ""}
            self.layers.append(self._label)
        elif tag == "input" and a.get("id") == "wind-hour":
            self.hour_max = int(a["max"])

    def handle_endtag(self, tag):
        if tag == "label":
            self._label = None

    def handle_data(self, data):
        if self._label is not None and data.strip() and not self._label["name"]:
            self._label["name"] = " ".join(data.split())


_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def numbers(text: str) -> set[str]:
    """Every number in `text`, by value: "1,609.0" and "1609" are both "1609", a sign
    is dropped, and a comma that is not a thousands separator splits two numbers."""
    out: set[str] = set()
    for tok in _NUMBER.findall(text):
        whole, dot, frac = tok.partition(".")
        if re.fullmatch(r"\d{1,3}(?:,\d{3})+", whole):
            parts = [whole.replace(",", "") + dot + frac]
        else:
            bits = [b for b in whole.split(",") if b]
            parts = bits[:-1] + [bits[-1] + dot + frac] if bits else []
        for p in parts:
            try:
                d = Decimal(p)
            except InvalidOperation:
                continue
            out.add(str(int(d)) if d == d.to_integral() else format(d.normalize(), "f"))
    return out


@dataclass
class Receipt:
    """One record of the brief's record set as the model and the reader see it."""

    id: str  # the record hash prefix the appendix prints
    sha256: str
    tool: str
    line: str  # the DN-010 D4 label line, as the ICS 201's block sources print it


@dataclass
class BriefView:
    """What the question box reads of a finished brief: its record set with each
    record's label line, its rendered sections as text, the map's layer switches and
    stepper hours, and the numbers its records hold. Built from the blackboard by
    `of_brief`; nothing here is gathered."""

    brief_id: str
    receipts: dict[str, Receipt]
    sections: dict[str, dict]
    layers: list[dict]
    hours: list[str]
    tools: list[dict]
    held_numbers: set[str] = field(repr=False, default_factory=set)

    def input(self) -> dict:
        return {
            "brief": self.brief_id,
            "sections": self.sections,
            "receipts": [{"id": r.id, "label": r.line} for r in self.receipts.values()],
            "layers": self.layers,
            "hours": self.hours,
            "tools": self.tools,
        }


def _tool_of(record: dict) -> str:
    a = record["activity"]
    return a["name"] if a["type"] != "upstream_exchange" else a["params"]["url"]


def record_view(brief, sha: str) -> tuple[dict, Any, dict] | None:
    """(the record, its body, its label) for the record of entity `sha` this brief
    read (`Brief.records()`, the appendix's set: HB-99's rule, the record this brief
    read, not the newest of its body), or None when `sha` is not in the set."""
    rec = next((r for r in brief.records() if r["entity"]["sha256"] == sha), None)
    if rec is None:
        return None
    _, body = L.latest(brief.stores, sha)
    return rec, body, L.label_for(rec, brief.now, body)


def of_brief(brief, cfg: dict, parts: dict[str, str]) -> BriefView:
    """The question box's view of a finished brief. `parts` are its sections'
    fragments (`render.page_parts`), the page's own."""
    from hazbrief.brief.orchestrator import RENDER_ORDER

    n = L.config()["hash_prefix_chars"]
    receipts: dict[str, Receipt] = {}
    held: set[str] = set()
    for rec in brief.records():
        sha = rec["entity"]["sha256"]
        got = record_view(brief, sha)
        _, body, lab = got
        tool = _tool_of(rec)
        line = L.label_line(tool, rec, lab, brief.time_zone).removeprefix("- ")
        receipts[sha[:n]] = Receipt(sha[:n], sha, tool, line)
        held |= numbers(
            canonical_json(body).decode("utf-8") if body is not None else ""
        )
        held |= numbers(json.dumps(rec, sort_keys=True))
        held |= numbers(line)
    sections = {}
    for name in RENDER_ORDER:
        text = visible_text(parts[name])
        held |= numbers(text)
        sections[name] = {
            "title": cfg["sections"][name]["title"],
            "state": brief.sections[name]["state"],
            "text": text,
        }
    from hazbrief.brief import render

    ctl = _MapControls()
    ctl.feed(parts["map"])
    hours: list[str] = []
    if ctl.hour_max is not None:
        # the stepper's own labels, as the page prints them
        wf = (brief.derived or {}).get("wind_field") or {}
        hours = render._wind_hours(wf, brief.time_zone)[: ctl.hour_max + 1]
    tools = [
        {
            "name": c,
            "sections": [s for s, v in cfg["sections"].items() if c in v["channels"]],
        }
        for c in cfg["channels"]
    ]
    return BriefView(
        brief_id=brief.scenario_id,
        receipts=receipts,
        sections=sections,
        layers=ctl.layers,
        hours=hours,
        tools=tools,
        held_numbers=held,
    )


# ── the check ────────────────────────────────────────────────────────────────────────


@dataclass
class Refusal(Exception):
    """An answer the route will not show (HB-131R item 4): `code` names the rule,
    `detail` the offending part."""

    code: str
    detail: str

    def to_json(self) -> dict:
        return {"error": {"code": self.code, "detail": self.detail}}


def parse_answer(text: str) -> dict:
    """The one JSON object the prompt asks for. A code fence around it is tolerated;
    anything else is a refusal (`not_json`)."""
    s = text.strip()
    fence = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", s, flags=re.S)
    if fence:
        s = fence.group(1)
    try:
        obj = json.loads(s)
    except json.JSONDecodeError as exc:
        raise Refusal("not_json", f"the answer is not one JSON object: {exc}") from exc
    if not isinstance(obj, dict):
        raise Refusal("not_json", "the answer is not a JSON object")
    return obj


def check_answer(obj: dict, view: BriefView, cfg: dict) -> dict:
    """The answer the page shows, or `Refusal`. Each sentence's receipt must be a
    record of the brief's record set and each of its numbers one a record holds; a
    named tool must be one the orchestrator runs; a view must name a layer switch the
    map has or an hour its stepper shows."""
    m = cfg["model"]
    sentences = obj.get("sentences")
    if not isinstance(sentences, list) or not isinstance(obj.get("not_in_brief"), bool):
        raise Refusal("shape", "sentences must be a list and not_in_brief a boolean")
    if len(sentences) > m["max_sentences"]:
        raise Refusal("shape", f"{len(sentences)} sentences, over {m['max_sentences']}")
    tool = obj.get("tool")
    if tool is not None and tool not in cfg["channels"]:
        raise Refusal("tool_not_declared", f"{tool!r} is not a tool the brief runs")
    out_sentences = []
    for s in sentences:
        if not isinstance(s, dict) or not isinstance(s.get("text"), str):
            raise Refusal("shape", f"a sentence is not {{text, receipt}}: {s!r}")
        rid = s.get("receipt")
        r = view.receipts.get(rid) if isinstance(rid, str) else None
        if r is None:
            raise Refusal(
                "receipt_not_in_record_set",
                f"{rid!r} is not a record of this brief: {s['text']}",
            )
        stray = sorted(numbers(s["text"]) - view.held_numbers)
        if stray:
            raise Refusal(
                "number_not_in_record",
                f"{', '.join(stray)} is in no record of this brief: {s['text']}",
            )
        out_sentences.append(
            {"text": s["text"], "receipt": {"record": r.id, "line": r.line}}
        )
    if obj["not_in_brief"]:
        if out_sentences:
            raise Refusal("shape", "not_in_brief with sentences")
        out_sentences = [{"text": m["not_in_brief"], "receipt": None}]
    elif not out_sentences:
        raise Refusal("shape", "no sentence and not not_in_brief")
    view_out = _check_view(obj.get("view"), view)
    return {
        "kind": "not_in_brief" if obj["not_in_brief"] else "answer",
        "sentences": out_sentences,
        "tool": tool if obj["not_in_brief"] else None,
        "view": view_out,
    }


def _check_view(v: Any, view: BriefView) -> dict | None:
    """A view proposal is typed: a layer the map's list has, on or off; or an hour
    the stepper shows, by its index."""
    if v is None:
        return None
    if not isinstance(v, dict):
        raise Refusal("view_not_on_page", f"a view is an object: {v!r}")
    if v.get("layer") is not None:
        ids = {x["id"] for x in view.layers}
        if v["layer"] not in ids or not isinstance(v.get("on"), bool):
            raise Refusal("view_not_on_page", f"no layer switch {v.get('layer')!r}")
        return {"layer": v["layer"], "on": v["on"]}
    if v.get("hour") is not None:
        h = v["hour"]
        if (
            not isinstance(h, int)
            or isinstance(h, bool)
            or not 0 <= h < len(view.hours)
        ):
            raise Refusal("view_not_on_page", f"no stepper hour {h!r}")
        return {"hour": h, "label": view.hours[h]}
    return None


# ── the call ─────────────────────────────────────────────────────────────────────────


def _subprocess_runner(argv, stdin, env, timeout, cwd):
    p = subprocess.run(
        argv,
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
        cwd=cwd,
    )
    return p.returncode, p.stdout, p.stderr


def resolve_launch(role: str) -> dict:
    """`seldon models resolve ROLE --json`: the launch block (model, CLI path and
    version, env, args). A role that does not resolve stops the route."""
    p = subprocess.run(
        ["seldon", "models", "resolve", role, "--json"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if p.returncode != 0:
        raise ModelRouteError(
            f"seldon models resolve {role} failed ({p.returncode}): {p.stderr.strip()}"
        )
    return json.loads(p.stdout)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_atomic(path: Path, obj: dict) -> None:
    """Written whole and fsynced before it is used (standards section 15 rule 1)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


class ModelAuthor:
    """The model-backed author (`write`) and the question box (`ask`). `replay` reads
    only `transcripts`; a call it holds no record of raises `NoRecordedCall`. Live,
    a held call is read and a new one is made through the pinned CLI and recorded.
    `launch` is the role's launch block (default: resolved through Seldon on the
    first call); `runner` runs the command (a test passes a stub)."""

    name = "ModelAuthor"

    def __init__(
        self,
        cfg: dict,
        *,
        transcripts: Path,
        replay: bool,
        launch: dict | None = None,
        runner: Runner | None = None,
        held_dirs: tuple[Path, ...] = (),
    ):
        self.cfg = cfg
        self.m = cfg["model"]
        self.transcripts = Path(transcripts)
        # HB-207 item 1: committed transcripts read before `transcripts`, live or
        # replay; a live call is written only to `transcripts`
        self.held_dirs = tuple(Path(d) for d in held_dirs)
        self.replay = replay
        self._launch = launch
        self.runner = runner or _subprocess_runner
        self.prompt = (REPO_ROOT / self.m["prompt"]).read_text(encoding="utf-8")
        self.prompt_sha256 = _sha(self.prompt)
        self.calls_made = 0
        self._fallback = NoAuthor()

    # the launch block is resolved on the first live call only: a replay never
    # needs Seldon
    def launch(self) -> dict:
        if self._launch is None:
            self._launch = resolve_launch(self.m["role"])
        return self._launch

    def request(self, entry: str, payload: dict) -> dict:
        """What was asked: the entry point, the prompt file's hash, the role and the
        input. Its sha256 (`request_sha256`) finds a call in a replay."""
        return {
            "entry": entry,
            "prompt_sha256": self.prompt_sha256,
            "role": self.m["role"],
            "input": payload,
        }

    @staticmethod
    def key(request_sha256: str, model: str) -> str:
        """A transcript's file key: the request and the model that answered it, so a
        moved lock asks again rather than reusing another model's answer (standards
        section 15 rule 2)."""
        return _sha(f"{request_sha256}\n{model}")

    def held(self, request_sha256: str) -> list[dict]:
        """Every transcript of a request, any model, by file name."""
        out, seen = [], set()
        for d in (*self.held_dirs, self.transcripts):
            if not d.is_dir():
                continue
            for p in sorted(d.glob("*.json")):
                if p.name in seen:
                    continue
                t = json.loads(p.read_text(encoding="utf-8"))
                if t.get("request_sha256") == request_sha256:
                    seen.add(p.name)
                    out.append(t)
        return out

    def argv(self, launch: dict) -> list[str]:
        return [
            "seldon",
            "models",
            "hold",
            "--run",
            self.m["hold_run"],
            "--by",
            self.m["hold_by"],
            "--",
            launch["cli_path"],
            "-p",
            *launch["args"],
            "--output-format",
            "json",
            "--tools",
            "",
            "--strict-mcp-config",
            "--no-session-persistence",
            "--system-prompt",
            self.prompt,
        ]

    def call(self, entry: str, payload: dict) -> dict:
        """The transcript of one call: read when held (and not a failure that may be
        asked again), else made and recorded first."""
        req = self.request(entry, payload)
        req_sha = _sha(canonical_json(req).decode("utf-8"))
        if self.replay:
            got = self.held(req_sha)
            if len({t["model"] for t in got}) > 1:
                raise ModelRouteError(
                    f"request {req_sha[:12]} is held for several models "
                    f"({sorted({t['model'] for t in got})}): replay cannot choose"
                )
            if not got:
                raise NoRecordedCall(
                    f"no recorded call of request {req_sha[:12]} in {self.transcripts} "
                    "(a replay makes none)"
                )
            return got[0]
        launch = self.launch()
        key = self.key(req_sha, launch["model"])
        path = self.transcripts / f"{key}.json"
        for d in self.held_dirs:
            kept = d / f"{key}.json"
            if kept.is_file():
                t = json.loads(kept.read_text(encoding="utf-8"))
                if t["ok"] or t["attempts"] >= self.m["max_attempts"]:
                    return t
        held = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
        if held is not None and (
            held["ok"] or held["attempts"] >= self.m["max_attempts"]
        ):
            return held
        user = json.dumps(req["input"], ensure_ascii=False, sort_keys=True)
        env = {**os.environ, **launch["env"]}
        t0 = time.monotonic()
        # an empty directory: no project CLAUDE or settings is read into the call
        with tempfile.TemporaryDirectory(prefix="hazbrief-model-") as cwd:
            try:
                rc, out, err = self.runner(
                    self.argv(launch), user, env, self.m["timeout_s"], cwd
                )
            except subprocess.TimeoutExpired:
                rc, out, err = -1, "", f"timed out after {self.m['timeout_s']} s"
        self.calls_made += 1
        seconds = round(time.monotonic() - t0, 2)
        result, usage, ok = None, None, False
        if rc == 0:
            try:
                resp = json.loads(out)
                result = resp.get("result")
                usage = resp.get("usage")
                ok = not resp.get("is_error") and isinstance(result, str)
            except json.JSONDecodeError:
                err = (err + " the CLI's output is not JSON").strip()
        rec = {
            "key": key,
            "request": req,
            "request_sha256": req_sha,
            "model": launch["model"],
            "cli_version": launch["cli_version"],
            "response": out,
            "response_sha256": _sha(out),
            "result": result,
            "usage": usage,
            "exit_code": rc,
            "error": None if ok else (err.strip()[-2000:] or "the call failed"),
            "ok": ok,
            "seconds": seconds,
            "attempts": (held["attempts"] if held else 0) + 1,
        }
        _write_atomic(path, rec)
        return rec

    # ── the narrative author (DN-011 D4) ──

    def write(
        self, section: str, payloads: dict[str, Any], **context: Any
    ) -> str | None:
        """The section's Markdown, from the server's own text, the payloads and the
        records' labels. A section the model does not write (`model.sections`) is the
        server's own text. A reply carrying a number no input holds is not printed: the
        server's text is, under a line saying why."""
        own = self._fallback.write(section, payloads, **context)
        if section not in self.m["sections"] or own is None:
            return own
        payload = {
            "section": section,
            "server_text": own,
            "payloads": payloads,
            "labels": context.get("labels") or [],
        }
        rec = self.call("write", payload)
        if not rec["ok"]:
            return self.m["author_failed"].format(error=rec["error"]) + "\n\n" + own
        held = numbers(json.dumps(payload, sort_keys=True, ensure_ascii=False))
        stray = sorted(numbers(rec["result"]) - held)
        if stray:
            why = f"it carries {', '.join(stray)}, which no record holds"
            return self.m["author_refused"].format(why=why) + "\n\n" + own
        return rec["result"]

    # ── the question box (DN-022 section 5) ──

    def ask(self, question: str, view: BriefView) -> dict:
        """The checked answer to `question` over the brief, or a `{"error": ...}`
        refusal, each with the call's hashes. Raises `NoRecordedCall` in a replay that
        holds no record of the question."""
        q = question.strip()
        if not q or len(q) > self.m["question_max_chars"]:
            return Refusal(
                "question",
                f"a question is 1 to {self.m['question_max_chars']} characters",
            ).to_json()
        payload = {"question": q, **view.input()}
        size = len(json.dumps(payload, ensure_ascii=False))
        if size > self.m["max_input_chars"]:
            return Refusal(
                "input_too_long",
                f"the brief's text is {size} characters, "
                f"over {self.m['max_input_chars']}",
            ).to_json()
        before = self.calls_made
        rec = self.call("ask", payload)
        call = {
            "transcript": rec["key"],
            "request_sha256": rec["request_sha256"],
            "response_sha256": rec["response_sha256"],
            "model": rec["model"],
            "calls_made": self.calls_made - before,
        }
        if not rec["ok"]:
            return {**Refusal("call_failed", rec["error"]).to_json(), "call": call}
        try:
            answer = check_answer(parse_answer(rec["result"]), view, self.cfg)
        except Refusal as r:
            return {**r.to_json(), "call": call}
        return {"answer": answer, "call": call}


def from_config(
    cfg: dict, *, replay: bool, transcripts: Path | None = None
) -> ModelAuthor:
    """The model author `orchestrator.yaml` names, reading or writing `transcripts`
    (default `model.transcripts_dir`)."""
    path = transcripts or (REPO_ROOT / cfg["model"]["transcripts_dir"])
    return ModelAuthor(cfg, transcripts=path, replay=replay)
