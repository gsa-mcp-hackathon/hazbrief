"""Resources submodule — static/semi-static data the client can read directly.

Resources are addressable by URI and don't require a tool call. Good for data
dictionaries, reference tables, and schemas.

Each resource module exposes a `register(mcp)` function; this file aggregates
them into `register_resources(mcp)`.

Registered: the commander stylebook and its vocabulary (HB-02), and the
attribution notices (DN-003 section 2). Planned (DN-001): pack metadata.
"""

from __future__ import annotations

from hazbrief.resources import attribution, stylebook


def register_resources(mcp) -> None:
    """Register all resources with the MCP server."""
    stylebook.register(mcp)
    attribution.register(mcp)


__all__ = ["register_resources"]
