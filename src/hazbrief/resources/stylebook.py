"""The commander stylebook and its controlled vocabulary, as MCP resources (HB-02).

Data source: `docs/stylebook/COMMANDER_STYLEBOOK.md` and
`docs/stylebook/VOCABULARY.yaml`, authored in this repository from held, receipted
federal documents. Update cadence: changes only with a commit. As-of: the files as
shipped with this server version. Read once at registration, so a missing file stops the
server at startup instead of serving nothing.
"""

from __future__ import annotations

from hazbrief.stylebook_files import COMMANDER_STYLEBOOK, VOCABULARY, read_shipped

STYLEBOOK_URI = "hazbrief://stylebook/commander"
VOCABULARY_URI = "hazbrief://stylebook/vocabulary"


def register(mcp) -> None:
    stylebook_text = read_shipped(COMMANDER_STYLEBOOK)
    vocabulary_text = read_shipped(VOCABULARY)

    @mcp.resource(
        STYLEBOOK_URI,
        name="commander_stylebook",
        title="Commander Stylebook",
        description=(
            "The writing standard for the ICS 201 draft and the Protective Action "
            "Decision text: structure, sentence rules, terminology, numbers, and what "
            "is never written. Every rule carries its source receipt."
        ),
        mime_type="text/markdown",
    )
    def commander_stylebook() -> str:
        return stylebook_text

    @mcp.resource(
        VOCABULARY_URI,
        name="vocabulary",
        title="Controlled Vocabulary",
        description=(
            "One term per object, drawn from the ERG, the ICS forms and NIMS: each "
            "term's definition, source receipt and forbidden synonyms."
        ),
        mime_type="application/yaml",
    )
    def vocabulary() -> str:
        return vocabulary_text
