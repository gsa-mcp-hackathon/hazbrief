"""The `decision_support` prompt: what to know, suggested actions to consider, and by
when, each line with its source, from the server's tool results and the suggested
actions pack only (DN-029 ADDENDUM-00).

It sequences the server's tools, then carries the suggested actions table
(`packs/suggested_actions.json`): each entry the condition that brings it up, a test on
values a tool result holds; the action, a quotation of a held document verified on its
page when the pack is built, or the ERG guide's own cell as `material_response_guidance`
returns it; who acts, where the source says; and by when, only the sources' order and
their held ranges, quoted. The client tests each condition on the tool results, writes
every entry whose condition holds exactly as given with its source beside it, adds no
action of its own, and names each condition the table watches but has no entry for. No
clock time is computed: the server runs no dispersion model. The prompt is marked a
demonstration and says the incident commander decides.

Data source: the incident as the caller reports it, and the suggested actions pack.
Update cadence and as-of: the pack as shipped with this server version (its `version`
and `built_at`, printed in the prompt).
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from hazbrief.packs import default_packs

#: The tools whose results the entries' conditions read, in the order to call them.
TOOLS: tuple[tuple[str, str], ...] = (
    ("assess_incident", "the material, its ERG guide, the container and fire"),
    (
        "protective_action_footprint",
        "the ERG zones, the wind they are oriented by, and the flags",
    ),
    ("population_at_risk", "the people inside the footprint, day and night"),
    (
        "facilities_in_footprint",
        "the schools, hospitals, nursing homes and group quarters inside it",
    ),
    ("material_response_guidance", "the ERG guide's own lines, by section"),
)

_TEXT = """\
{label}: what to know, what to consider doing, and by when, for this incident.
{demonstration} {decides}

Incident, as reported:
- Material: {material}
- Container: {container}
- Location: {location}
- Time: {incident_time}

1. Call these tools on the incident, in this order, passing each result forward:
{tools}
If a tool is not available or returns an error, write that in one line under "What to
know", with the error as the tool gives it, and test no condition on that tool's result.

2. What to know. From the tool results only, one line each, each with the tool and the
field it comes from: the material and its ERG guide; the isolation and protective action
distances; the wind the footprint is oriented by and where that wind came from; the
people inside the footprint, day and night; the schools, hospitals, nursing homes and
group quarters inside it; and the flags the tools return, each with its rule and source.

3. {label}. Test each entry's condition below on the tool results, reading the fields it
names. For every entry whose condition holds, write its action exactly as given: a
quotation in quotation marks, or the guide's own lines as material_response_guidance
returns them under the named section and heading. Keep its source beside it, and who
acts where the entry names it. Write the entries in their order. Add no action of your
own, and do not reword, rank, merge or leave out an entry whose condition holds. You may
explain an entry in plain words after it; the entry and its source stay beside the
explanation. For each of these conditions that holds, write the condition and then
"{no_entry}":
{uncovered}

4. By when. Only the order of the entries and the times the entries give, quoted with
their sources. Compute no clock time and write none.

End with these two sentences: "{demonstration}" "{decides}"

The table (suggested actions pack {version}, built {built_at}):
{table}"""


def _source(r) -> str:
    return f"{r.doc_id}, p. {r.page}"


def _entry(key: str, a) -> str:
    """One entry of the table as the prompt prints it."""
    head = f"- [{a.order}] {key}. When: {a.when} (reads: {'; '.join(a.reads)})."
    if a.action is not None:
        cell = f'"{a.action.quote}"'
        if a.heading is not None:
            cell = f'{a.heading.quote} "{a.action.quote}"'
        body = f"  Action: {cell} Source: {_source(a.action)}."
    else:
        g = a.guide_cell
        under = f', under "{g.heading}"' if g.heading else ""
        body = (
            f"  Action: the guide's own lines, {g.tool} section {g.section}{under}, "
            "as the tool returns them, each with its locator."
        )
    lines = [head, body]
    if a.who:
        lines.append(f'  Who acts: "{a.who}" ({_source(a.action)}).')
    if a.by_when is not None:
        lines.append(f'  By when: "{a.by_when.quote}" ({_source(a.by_when)}).')
    return "\n".join(lines)


def render_decision_support(
    material: str, container: str, location: str, incident_time: str
) -> str:
    """The prompt text, apart from registration so tests can render it."""
    pack = default_packs().suggested_actions
    d = pack.data
    entries = sorted(d.actions.items(), key=lambda kv: (kv[1].order, kv[0]))
    return _TEXT.format(
        label=d.label,
        demonstration=d.demonstration,
        decides=d.decides,
        no_entry=d.no_entry,
        material=material,
        container=container,
        location=location,
        incident_time=incident_time,
        tools="\n".join(
            f"{i}. `{name}`: {what}" for i, (name, what) in enumerate(TOOLS, start=1)
        ),
        uncovered="\n".join(f"- {u}" for u in d.uncovered),
        version=pack.version,
        built_at=pack.built_at,
        table="\n".join(_entry(k, a) for k, a in entries),
    )


def register(mcp) -> None:
    # Read once now: a missing or altered pack stops the server at startup.
    default_packs()

    @mcp.prompt(
        name="decision_support",
        title="Suggested actions to consider",
        description=(
            "A demonstration of decision support for a transported-hazmat incident: "
            "what to know, suggested actions to consider and by when, each line from "
            "the server's tool results and a table of actions quoted from held "
            "sources, with its source. The incident commander decides."
        ),
    )
    def decision_support(
        material: Annotated[
            str,
            Field(
                min_length=1,
                description="Material name or UN/NA ID number, as reported.",
            ),
        ],
        container: Annotated[
            str,
            Field(
                min_length=1,
                description="Container, e.g. highway tank truck, rail tank car.",
            ),
        ],
        location: Annotated[
            str,
            Field(
                min_length=1,
                description="Where: road and mile marker, or latitude/longitude.",
            ),
        ],
        incident_time: Annotated[
            str,
            Field(
                min_length=1,
                description="When: month/day/year, 24-hour time and time zone.",
            ),
        ],
    ) -> str:
        return render_decision_support(material, container, location, incident_time)
