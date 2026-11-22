"""The harness's fake MCP server (HB-41 step 2; DN-011 D7). A test fixture, not shipped.

    HAZBRIEF_FAKE_CONTROL=control.json python tests/fake_mcp_server.py   # stdio

It is the real server, so it serves the surface's own schemas, in replay mode (answers
come from `fixtures/exchanges`), with one fastmcp middleware that injects behaviour per
tool from the control file:

    {"population_at_risk": {"delay_s": 1.5},
     "receiving_hospitals": {"hang": true},
     "facilities_in_footprint": {"error": "upstream refused"},
     "material_response_guidance": {"as_of": "01/01/2020"}}

* `delay_s`: wait that long, then answer;
* `hang`: never answer;
* `error`: answer a structured error, `{"error": ..., "hint": ...}`, the shape the tools
  use (DN-003 s1's no-key error);
* `as_of`: answer, with every date in the result's `basis` tags replaced by this one.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("HAZBRIEF_HTTP_MODE", "replay")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastmcp.server.middleware import Middleware  # noqa: E402
from fastmcp.tools import ToolResult  # noqa: E402

from hazbrief.app import mcp  # noqa: E402

CONTROL = os.environ.get("HAZBRIEF_FAKE_CONTROL")
_DATE = re.compile(r"\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2}")


def control() -> dict:
    return json.loads(Path(CONTROL).read_text(encoding="utf-8")) if CONTROL else {}


class Inject(Middleware):
    async def on_call_tool(self, context, call_next):
        c = control().get(context.message.name, {})
        if c.get("hang"):
            await asyncio.Event().wait()
        if c.get("delay_s"):
            await asyncio.sleep(float(c["delay_s"]))
        if c.get("error"):
            body = {"error": c["error"], "hint": "injected by the harness"}
            return ToolResult(structured_content=body)
        result = await call_next(context)
        if c.get("as_of") and isinstance(result.structured_content, dict):
            sc = result.structured_content
            for b in sc.get("basis") or []:
                b["tag"] = _DATE.sub(c["as_of"], b["tag"])
            result = ToolResult(structured_content=sc)
        return result


mcp.add_middleware(Inject())

if __name__ == "__main__":
    mcp.run()
