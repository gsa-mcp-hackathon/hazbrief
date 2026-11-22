"""Who writes a brief's narrative sections (DN-011 D4; DN-009 C4).

`NarrativeAuthor` is the protocol a narrative section is written through. This cut has
one author, `NoAuthor`: it writes no word of its own and returns the deterministic text
the server already produced. The ICS 201 is `build_ics_201`'s Markdown, deterministic
under DN-001 invariant 2. The guidance is the ERG orange guide's text as
`material_response_guidance` returned it. A model-backed author is a later task with its
own spend line (DN-011 D4).

An author returns Markdown in the subset `hazbrief.brief.render.markdown_html` reads, or
None when it has nothing for the section.
"""

from __future__ import annotations

from typing import Any, Protocol


class NarrativeAuthor(Protocol):
    name: str

    def write(
        self, section: str, payloads: dict[str, Any], **context: Any
    ) -> str | None:
        """The section's Markdown, from the payloads of the channels it reads."""


class NoAuthor:
    """The server's own text, unchanged. Writes nothing of its own."""

    name = "NoAuthor"

    def write(
        self, section: str, payloads: dict[str, Any], **context: Any
    ) -> str | None:
        if section == "guidance":
            return _guidance(payloads.get("material_response_guidance"))
        if section == "ics201":
            return context.get("ics201_markdown")
        return None


def _guidance(g: dict | None) -> str | None:
    """The orange guide's sections as `material_response_guidance` returned them, in its
    own order, each line with its locator."""
    if not isinstance(g, dict) or "order" not in g:
        return None
    guide = g.get("guide") or {}
    out = [f"**ERG 2024 Guide {guide.get('number')}: {guide.get('title')}**", ""]
    for key in g["order"]:
        items = g.get(key) or []
        out.append(f"### {key.replace('_', ' ').capitalize()}")
        out.append("")
        for it in items:
            text = it.get("text", "")
            if it.get("kind") == "heading":
                out += ["", f"**{text}**", ""]
            else:
                out.append(f"- {text} [{it.get('locator')}]")
        out.append("")
    return "\n".join(out).strip() + "\n"
