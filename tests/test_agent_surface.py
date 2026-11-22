"""HB-18 (A-5): what an agent sees of the server names no internal task or note.

HB-16's agents read "(HB-15)", "(HB-09)" and "(DN-006)" in the tool schemas (LN-07
A-5): this repository's task and note ids, which mean nothing to a client and cite
nothing it can open. They stay in code comments and the docs. The surface is every
tool's name, description and input schema, every prompt's and resource's listing, the
server's instructions, and the prompt's own words (the stylebook it embeds is a
document, and keeps its citations).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml
from fastmcp import Client

from hazbrief.app import mcp
from hazbrief.prompts.ics201_brief import _INSTRUCTIONS, TOOL_SEQUENCE
from hazbrief.resources.stylebook import VOCABULARY_URI

INTERNAL_ID = re.compile(r"\b(?:HB|DN|LN|FR)-\d")


async def _surface() -> dict:
    async with Client(mcp) as c:
        return {
            "instructions": mcp.instructions,
            "tools": [
                {"name": t.name, "description": t.description, "schema": t.input_schema}
                for t in await c.list_tools()
            ],
            "prompts": [p.model_dump(mode="json") for p in await c.list_prompts()],
            "resources": [r.model_dump(mode="json") for r in await c.list_resources()],
            "templates": [
                t.model_dump(mode="json") for t in await c.list_resource_templates()
            ],
        }


async def test_the_tool_surface_names_no_internal_task_or_note():
    text = json.dumps(await _surface())
    assert not INTERNAL_ID.findall(text), [
        text[max(0, m.start() - 60) : m.end() + 10] for m in INTERNAL_ID.finditer(text)
    ]


def test_the_prompts_own_words_name_none():
    words = _INSTRUCTIONS + json.dumps(TOOL_SEQUENCE)
    assert not INTERNAL_ID.findall(words)


# ── HB-90 (review L1-5): "plume" is in nothing the server registers or returns ──

#: DN-001 section 4 invariant 1, as whole words in any case: `PLUMERIA STREET` (an
#: address in fixtures/cms/hospitals.json) is not the word.
PLUME = re.compile(r"\bplumes?\b", re.I)
REPO = Path(__file__).resolve().parents[1]
#: The stylebook's rule that bans the word has to name it (SB-NEV-01, and the
#: vocabulary's `never_written` list the stylecheck reads). Those are cut from the
#: served text before the search, and the cut is asserted to be the ban.
NEVER_SECTION = re.compile(r"^### SB-NEV-01 .*?(?=^### )", re.S | re.M)
SEVEN_TOOLS = {
    "assess_incident",
    "protective_action_footprint",
    "population_at_risk",
    "facilities_in_footprint",
    "receiving_hospitals",
    "material_response_guidance",
    "build_ics_201",
}


def _served_text(uri: str, text: str) -> str:
    if uri == VOCABULARY_URI:
        vocab = yaml.safe_load(text)
        banned = {e["term"] for e in vocab.pop("never_written")}
        assert {"plume", "plumes"} <= banned
        return yaml.safe_dump(vocab)
    if NEVER_SECTION.search(text):
        (rule,) = NEVER_SECTION.findall(text)
        assert 'Never write "plume"' in rule
        return NEVER_SECTION.sub("", text)
    return text


def _hits(text: str) -> list[str]:
    return [text[max(0, m.start() - 60) : m.end() + 20] for m in PLUME.finditer(text)]


def _keys_and_strings(obj) -> list[str]:
    """Every field name and every string value in a tool result. A field name is read
    with its underscores as spaces: `\\b` does not fall inside `plume_extent`."""
    if isinstance(obj, dict):
        return [
            s
            for k, v in obj.items()
            for s in (str(k).replace("_", " "), *_keys_and_strings(v))
        ]
    if isinstance(obj, list):
        return [s for v in obj for s in _keys_and_strings(v)]
    return [obj] if isinstance(obj, str) else []


async def test_no_tool_prompt_or_resource_the_server_registers_writes_plume():
    """Every tool's name, description and schema, every prompt's listing and rendered
    messages, every resource's listing and content. The tests this extends checked five
    materials' assessments and four footprints by substring (review L1-5)."""
    surface = await _surface()
    # tool and parameter names are snake_case: read them with underscores as spaces
    assert not _hits(json.dumps(surface).replace("_", " "))
    async with Client(mcp) as c:
        for p in await c.list_prompts():
            args = {a.name: "chlorine" for a in p.arguments or [] if a.required}
            got = await c.get_prompt(p.name, args)
            # the prompt embeds the stylebook, its ban rule with it
            texts = [_served_text("", m.content.text) for m in got.messages]
            assert not _hits(json.dumps(texts) + str(got.description)), p.name
        for r in await c.list_resources():
            uri = str(r.uri)
            (content,) = await c.read_resource(uri)
            assert not _hits(_served_text(uri, content.text)), uri


SNAPSHOTS = sorted((REPO / "fixtures" / "scenarios").glob("*.json"))


@pytest.mark.parametrize("path", SNAPSHOTS, ids=[p.stem for p in SNAPSHOTS])
def test_no_field_name_or_value_any_tool_returned_writes_plume(path):
    """The seven tools' frozen outputs on every scenario (`fixtures/scenarios/`, which
    `test_eval_regression.py` holds equal to a fresh replay), field names and
    values both, the ICS 201's Markdown and fired flags among them."""
    tools = json.loads(path.read_text(encoding="utf-8"))["tools"]
    # open-water-day exercises the two area tools only
    assert tools and set(tools) <= SEVEN_TOOLS, sorted(tools)
    for name, out in tools.items():
        hits = [h for s in _keys_and_strings(out) for h in _hits(s)]
        assert not hits, (name, hits)


def test_the_plume_search_can_fail():
    """Seeded: the search finds the word in a field name, a value and a cut-down
    stylebook, and does not find a street name that begins with it."""
    seeded = {"plume_extent": "PLUMERIA STREET", "note": "the vapor Plumes"}
    assert len([h for s in _keys_and_strings(seeded) for h in _hits(s)]) == 2
    assert _hits("### SB-NEV-02 x\nNever write plume\n### SB-NEV-03 y\n")


def test_no_flag_rule_template_writes_plume():
    rules = json.loads((REPO / "packs" / "flag_rules.json").read_text())["data"]
    for r in rules["rules"]:
        assert not _hits(json.dumps(r)), r["id"]
