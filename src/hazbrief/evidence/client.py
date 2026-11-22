"""The recording client (DN-010 D2, D7; HB-39 step 4): every MCP tool call writes its
evidence record, and the caller gets the record's entity hash with the payload.

It spawns the server as an MCP client would, over stdio from `main.py`, and talks to it
only through MCP: no import from `hazbrief.tools`, so the record is of what a client
saw. The server is the one being recorded; the store and the record are the
application's. The client must spawn the checkout it is imported from (`cwd` is that
repository root), so its package version is the server's.

Per call it records: the activity (tool, parameters, start and end, the server's
`HAZBRIEF_HTTP_MODE`, whether MCP marked the result an error), the server (its name from
the MCP handshake, its package version, the handshake as reported, and the tool surface
hash, computed from `tools/list` the way `scripts/agent_eval.py` computes it, so it is
`fded04ec6c0e...` while the freeze holds), and from the catalog the sources the tool
reads, its provenance class and the shortest horizon among them. As-of is the call's
end: a tool's own as-of fields vary by tool, and reading them is the label's job
(HB-40), not the record's.

The entity is the structured result when the tool returns one, else the content blocks
as MCP sent them.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import PythonStdioTransport

from hazbrief import __version__
from hazbrief.config import REPO_ROOT
from hazbrief.evidence import catalog
from hazbrief.evidence.store import (
    SECRET_SETTINGS,
    config,
    default_store_dir,
    repo_path,
    utc_now,
    write_record,
)


def surface_sha256(tools: list[dict]) -> str:
    """`scripts/agent_eval.py` `tool_surface`'s hash: sha256 of
    `json.dumps([{name, description, schema}], sort_keys=True)`. Kept identical so the
    record names the surface HB-36 evaluated (test_recording_client.py)."""
    blob = json.dumps(tools, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class RecordingClient:
    """Use as `async with RecordingClient() as rc:`, then
    `sha, payload = await rc.call(tool, params)`."""

    def __init__(
        self,
        store: Path | None = None,
        *,
        env: dict[str, str] | None = None,
        server_entry: Path | None = None,
    ):
        self.store = Path(store) if store else default_store_dir()
        self.env = {**os.environ, **(env or {})}
        self.http_mode = self.env.get("HAZBRIEF_HTTP_MODE", "live")
        if self.http_mode not in ("live", "record", "replay"):
            raise ValueError(f"HAZBRIEF_HTTP_MODE={self.http_mode!r}")
        entry = server_entry or repo_path("server_entry")
        self._client = Client(
            PythonStdioTransport(script_path=entry, env=self.env, cwd=str(REPO_ROOT)),
            timeout=config()["call_timeout_s"],
        )
        self.server: dict | None = None

    async def __aenter__(self) -> RecordingClient:
        await self._client.__aenter__()
        info = self._client.server_info
        tools = [
            {"name": t.name, "description": t.description, "schema": t.input_schema}
            for t in await self._client.list_tools()
        ]
        # MCP's serverInfo.version is the framework's (FastMCP reports its own release),
        # so the server version is the spawned checkout's package version, the one its
        # User-Agent sends upstream; the handshake is kept as reported.
        self.server = {
            "name": info.name,
            "version": __version__,
            "tool_surface_sha256": surface_sha256(tools),
            "reported": {"name": info.name, "version": info.version},
        }
        return self

    async def __aexit__(self, *exc) -> None:
        await self._client.__aexit__(*exc)

    async def call(
        self, tool: str, params: dict[str, Any], used: list[str] | None = None
    ) -> tuple[str, Any]:
        """Call `tool`, write its record, return (entity sha256, payload)."""
        if self.server is None:
            raise RuntimeError("RecordingClient used outside `async with`")
        rows = catalog.rows_for_tool(tool)
        started = utc_now()
        result = await self._client.call_tool(tool, params, raise_on_error=False)
        ended = utc_now()
        if result.structured_content is not None:
            payload = result.structured_content
        else:
            payload = [b.model_dump(mode="json") for b in result.content]
        horizon, governing = catalog.governing_horizon(rows)
        sha, _ = write_record(
            self.store,
            payload,
            activity={
                "type": "mcp_tool_call",
                "name": tool,
                "params": params,
                "startedAtTime": started,
                "endedAtTime": ended,
                "http_mode": self.http_mode,
                "is_error": bool(result.is_error),
            },
            server=self.server,
            source=[{"id": r["id"], "endpoint": _endpoint(r)} for r in rows],
            provenance_class=catalog.provenance_class_of(rows),
            as_of=ended,
            as_of_basis="endedAtTime",
            horizon_s=horizon,
            horizon_source=governing,
            used=used,
            secrets=[self.env.get(n.upper(), "") for n in SECRET_SETTINGS],
        )
        return sha, payload


def _endpoint(row: dict) -> str | None:
    """A row's first endpoint, or None for a computation."""
    return row["endpoints"][0] if row["endpoints"] else None
