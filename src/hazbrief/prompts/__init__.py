"""Prompts submodule — reusable conversation starters.

Prompts appear in the client UI as slash commands / preset starters. Each
prompt module exposes a `register(mcp)` function; this file aggregates them
into `register_prompts(mcp)`.

To add a prompt:
  1. Create `prompts/<group>.py` with a `register(mcp)` function.
  2. Import it below and call `<group>.register(mcp)` inside register_prompts.

Registered: `ics201_brief` (HB-02), which sequences the tools and binds the
agent to the commander stylebook; `decision_support` (HB-207; DN-029 ADDENDUM-00), what
to know, suggested actions to consider and by when, each from the tool results and the
suggested actions pack with its source.
"""

from __future__ import annotations

from hazbrief.prompts import decision_support, ics201_brief


def register_prompts(mcp) -> None:
    """Register all prompts with the MCP server."""
    ics201_brief.register(mcp)
    decision_support.register(mcp)


__all__ = ["register_prompts"]
