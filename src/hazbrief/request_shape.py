"""A tool's object argument wrapped a second time is refused with the fix (HB-37, A-11).

HB-36's Sonnet sent `protective_action_footprint` the whole request inside its
`incident` parameter, `{"incident": {"incident": {...}, "wind": {...}}}`, in 6 of its
episodes (HB-36 RESULT section 4). FastMCP's argument validation refused it with seven
Pydantic errors that never said what was wrong. DN-001 section 4 invariant 2 puts the
fix in the server's error, so the refusal now carries a `hint`. The tool still refuses:
nothing is unwrapped, as HB-18 repairs no malformed JSON (`models.ToolInput`).

The guard runs before validation, as call-tool middleware, so it reads each tool's
published parameter schema and changes none of it: the tool surface an agent sees, and
HB-36's surface hash, do not move.

**The rule.** An object parameter `p` whose schema forbids extra fields and has no field
named `p` cannot validly hold a key `p`. When its value does (an object, or a JSON
string that parses once to one, as HB-18 reads strings), the request is wrapped twice.
That reading is certain, not a guess: the call fails validation either way.
"""

from __future__ import annotations

import json
from typing import Any

from fastmcp.server.middleware import Middleware
from fastmcp.tools.base import ToolResult

#: The refusal and its fix, each one sentence; `{param}` is the parameter's name.
WRAPPED_TWICE_ERROR = (
    "`{param}` holds an object with its own `{param}` field: the request is wrapped "
    "twice, and the tool does not unwrap it."
)
WRAPPED_TWICE_HINT = "pass {param}'s fields directly; the request is wrapped twice"


def _resolve(schema: dict, defs: dict) -> dict:
    """A local `$ref` (`#/$defs/IncidentInput`) as its definition. The server holds a
    tool's schema with refs; FastMCP inlines them only in the listing a client sees."""
    ref = schema.get("$ref")
    if ref is None:
        return schema
    name = ref.rsplit("/", 1)[-1]
    if not ref.startswith("#/$defs/") or name not in defs:
        raise ValueError(f"a tool parameter's $ref {ref!r} is not in its $defs")
    return defs[name]


def _object_schema(schema: dict, defs: dict) -> dict | None:
    """The object schema a parameter takes, directly or as one branch of `anyOf`
    (an optional object such as `wind`)."""
    for s in [schema, *(schema.get("anyOf") or [])]:
        s = _resolve(s, defs)
        if s.get("type") == "object" and "properties" in s:
            return s
    return None


def object_parameters(parameters: dict) -> set[str]:
    """The parameters of a tool's input schema the rule can read a double wrap on: an
    object that forbids extra fields and has no field of its own name."""
    defs = parameters.get("$defs") or {}
    out = set()
    for name, schema in (parameters.get("properties") or {}).items():
        o = _object_schema(schema, defs)
        if (
            o is not None
            and o.get("additionalProperties") is False
            and name not in o["properties"]
        ):
            out.add(name)
    return out


def _as_object(value: Any) -> dict | None:
    """`value` as an object: itself, or a JSON string parsed once (HB-18's reading).
    Anything else is not an object, and validation answers it as before."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def wrapped_twice(parameters: dict, arguments: dict | None) -> str | None:
    """The first parameter (by name) whose argument holds its own name, else None."""
    for name in sorted(object_parameters(parameters)):
        inner = _as_object((arguments or {}).get(name))
        if inner is not None and name in inner:
            return name
    return None


def refusal(param: str) -> dict:
    """The structured error for a request wrapped twice at `param`."""
    return {
        "error": WRAPPED_TWICE_ERROR.format(param=param),
        "hint": WRAPPED_TWICE_HINT.format(param=param),
        "parameter": param,
    }


class WrappedTwiceGuard(Middleware):
    """Refuse a tool call whose object argument is wrapped twice, with the hint, as an
    error result (`is_error`), before FastMCP validates the arguments."""

    def __init__(self, server) -> None:
        self._server = server

    async def on_call_tool(self, context, call_next):
        msg = context.message
        tool = await self._server.get_tool(msg.name)
        # an unknown tool is FastMCP's to refuse, with its own error
        param = wrapped_twice(tool.parameters, msg.arguments) if tool else None
        if param is None:
            return await call_next(context)
        return ToolResult(structured_content=refusal(param), is_error=True)
