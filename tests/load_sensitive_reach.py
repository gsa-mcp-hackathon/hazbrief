"""HB-194: which test functions reach a call that launches headless Chrome, binds a port
or starts an MCP server, read from the source (`ast`), whatever a cache or a fixture
does at run time.

Why from the source: a helper under `@cache` (`test_hb154_shell._driven`,
`test_hb139_weather_source._stated`, ...) launches once per worker process, in
whichever test calls it first; every later caller reads the cache and launches nothing.
A run-time trace credits the launch to one test. When that test moved to the gate's
second step, an unmarked caller of the same cache launched Chrome under the parallel
step's load and ran past its 240 s timeout (HB-194 Part C, gate 2 of the first series).
So the mark goes on every test that can reach the launch, and
`test_hb194_serial_step.py` holds that it does.

The read: every `tests/test_*.py` and `tests/conftest.py`; each module-level function
(test, helper or fixture), the calls it makes to its own module's functions and to
other test modules' functions imported by name (at the top or inside the function),
the module functions it names (a helper passed along), and the fixtures it requests by
parameter name. A function launches a kind when its own source holds one of the kind's
constructs (`CONSTRUCTS`, or a live assembly, `_live_assembly`), or it reaches a
function that does. `NOT_LAUNCHING` names the reads that are wrong, each with why.
"""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from pathlib import Path

TESTS = Path(__file__).resolve().parent
#: the source constructs that launch each kind, the kinds named as
#: `docs/evidence/hb194/load_sensitive.tsv` names them. A live assembly is read from the
#: call itself (`_live_assembly`).
CONSTRUCTS = {
    "chrome": re.compile(r"\brun_chrome\("),
    "server_or_port": re.compile(
        r"uvicorn\.|\.bind\(|HTTPServer\(|ThreadingHTTPServer|make_server\(|serve_forever"
        r"|RecordingClient\(|stated_brief\.py|record_tool_call_seed"
        r"|PythonStdioTransport|StdioTransport"
    ),
}
#: test functions the read finds that launch nothing, each with why (read in the test)
NOT_LAUNCHING = {
    "test_hb130_event_stream.py::test_a_host_off_loopback_is_refused": (
        "calls web.bind('0.0.0.0', 0), which refuses before binding (SystemExit)"
    ),
}

Key = tuple[str, str]


def _live_assembly(fn: ast.AST) -> bool:
    """A live assembly anywhere in the function (a nested `start` included): a call to
    `assemble` with `env` or `server_entry` and without `replay_stores`, which spawns
    the MCP server over stdio (`hazbrief.brief.orchestrator.assemble`); with
    `replay_stores` it reads records and calls nothing."""
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            f = n.func
            name = f.id if isinstance(f, ast.Name) else getattr(f, "attr", "")
            kw = {k.arg for k in n.keywords}
            live = kw & {"env", "server_entry"} and "replay_stores" not in kw
            if name == "assemble" and live:
                return True
    return False


def _imports(nodes) -> dict[str, Key]:
    """name -> (module stem, function) for `from tests.X import f [as g]`."""
    out = {}
    for node in nodes:
        for n in ast.walk(node):
            if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("tests."):
                mod = n.module.split(".", 1)[1]
                for a in n.names:
                    out[a.asname or a.name] = (mod, a.name)
    return out


def reach() -> dict[str, set[str]]:
    """`tests/<module>.py::<test function>` -> the kinds it reaches, for every test
    function that reaches one (`NOT_LAUNCHING` left out)."""
    funcs: dict[Key, ast.AST] = {}
    calls: dict[Key, set[Key]] = defaultdict(set)
    direct: dict[Key, set[str]] = defaultdict(set)
    for p in sorted(TESTS.glob("test_*.py")) + [TESTS / "conftest.py"]:
        mod, text = p.stem, p.read_text(encoding="utf-8")
        tree = ast.parse(text)
        top = _imports(s for s in tree.body if isinstance(s, ast.ImportFrom))
        defs = {
            n.name: n
            for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for name, fn in defs.items():
            key = (mod, name)
            funcs[key] = fn
            seg = ast.get_source_segment(text, fn) or ""
            direct[key] = {k for k, rx in CONSTRUCTS.items() if rx.search(seg)}
            if _live_assembly(fn):
                direct[key].add("server_or_port")
            local = {**top, **_imports([fn])}
            # fixtures requested by parameter name
            calls[key] |= {(mod, a.arg) for a in fn.args.args if a.arg in defs}
            for n in ast.walk(fn):
                if isinstance(n, ast.Call):
                    f = n.func
                    while isinstance(f, ast.Attribute):
                        f = f.value
                    if isinstance(f, ast.Call):
                        f = f.func
                    if isinstance(f, ast.Name) and f.id in local:
                        calls[key].add(local[f.id])
                if isinstance(n, ast.Name) and n.id in defs and n.id != name:
                    calls[key].add((mod, n.id))
    # the kinds each function reaches: a fixed point over the call graph
    kinds = {k: set(v) for k, v in direct.items()}
    changed = True
    while changed:
        changed = False
        for key in funcs:
            got = set(kinds[key])
            for c in calls[key]:
                got |= kinds.get(c, set())
            if got != kinds[key]:
                kinds[key], changed = got, True
    return {
        f"tests/{mod}.py::{name}": kinds[(mod, name)]
        for (mod, name) in funcs
        if name.startswith("test_")
        and kinds[(mod, name)]
        and f"tests/{mod}.py::{name}" not in NOT_LAUNCHING
    }
