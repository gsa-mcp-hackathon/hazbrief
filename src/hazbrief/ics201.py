"""The ICS 201 form's configuration, sentences, receipts and Markdown (HB-11).

`build_ics_201` (tools/build_ics_201.py) assembles the FEMA ICS Form 201 blocks that
public data can fill from the other tools' outputs; this module holds what that assembly
is made of, so the tool module holds only the assembly:

* the configuration (`ics201.yaml`): the held form's block list, the labels of the
  blocks the Incident Commander writes, the ERG locators and heading rules
  `material_response_guidance` reads by;
* the sentence: printed text plus its receipts. A receipt is either a tool output field
  path with the value read there (`{"kind": "tool", "tool", "path", "value"}`) or a held
  document and page (`{"kind": "document", "doc_id", "page", "locator"}`). A sentence
  is our own, written to the commander stylebook and checked by `stylecheck`, or a
  marked ERG quotation (`quotation: true`, the ERG's words in `quote`), printed as the
  ERG prints it and exempt from the stylebook's vocabulary rules (HB-12 premise 8);
* the Markdown rendering of the assembled form.

Nothing here calls a model or the network: every sentence is a template filled from a
tool output value, or an ERG sentence quoted from a pack.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path
from typing import Any

import yaml

CONFIG_FILE = Path(__file__).with_name("ics201.yaml")
#: Every key the file must carry, by section (standards s4: a missing key is fatal).
REQUIRED = {
    "form": (
        "doc_id",
        "name",
        "blocks",
        "blank_label",
        "blank_blocks",
        "incident_name",
        "incident_name_fallback",
        "annex_title",
        "prepared_by",
        "resource_summary",
    ),
    "guidance": (
        "erg_doc",
        "erg_label",
        "general_first_aid",
        "p_sentence",
        "spill_headings",
        "fire_subsections",
        "fire_evacuation",
        "immediate_precautionary_heading",
        "placard_table_use_locator",
    ),
    "briefing": (
        "doc_labels",
        "objectives",
        "decision_flag_kinds",
        "names_per_sentence",
        "max_names",
        "wind_arrow_m",
        "limits",
        "flag_kinds",
        "fired_on",
    ),
    "names": ("upper", "lower", "mixed"),
    "place": (
        "doc_id",
        "service",
        "vintage",
        "places_layers",
        "counties_layer",
        "counties_layer_name",
        "identify_half_extent_deg",
        "identify_image",
        "outline_offset_deg",
    ),
    "map": (
        "service",
        "description",
        "layers",
        "href",
        "width_px",
        "min_height_px",
        "max_height_px",
        "pad_fraction",
        "image_format",
        "dpi",
        "scale_bar_fraction",
        "style",
    ),
}


#: Where a briefing-class limit prints (HB-11b step 1): under Block 5's population or
#: facilities subsection, or in Block 10.
LIMIT_PLACES = ("population", "facilities", "hospitals")


class ConfigError(RuntimeError):
    """ics201.yaml is missing a key or names something the packs do not hold."""


def load_config(path: Path = CONFIG_FILE) -> dict:
    """Read and check the file; a missing key raises ConfigError naming it."""
    try:
        cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"{path}: not found") from None
    if not isinstance(cfg, dict):
        raise ConfigError(f"{path}: not a mapping")
    for section, keys in REQUIRED.items():
        if not isinstance(cfg.get(section), dict):
            raise ConfigError(f"{path}: required section {section!r} is missing")
        for key in keys:
            if key not in cfg[section]:
                raise ConfigError(f"{path}: required key {section}.{key} is missing")
    numbers = [b.get("number") for b in cfg["form"]["blocks"]]
    if numbers != list(range(1, len(numbers) + 1)):
        raise ConfigError(f"{path}: form.blocks must be numbered 1, 2, 3, ... in order")
    for b in cfg["form"]["blocks"]:
        for key in ("title", "receipt"):
            if not b.get(key):
                raise ConfigError(f"{path}: form block {b['number']} has no {key}")
    lim = cfg["briefing"]["limits"]
    if len(lim["briefing"]) > lim["max_printed"]:
        raise ConfigError(
            f"{path}: briefing.limits names {len(lim['briefing'])} briefing limits, "
            f"more than max_printed {lim['max_printed']}"
        )
    for e in lim["briefing"]:
        if (
            e.get("place") not in LIMIT_PLACES
            or not e.get("tool")
            or not e.get("match")
        ):
            raise ConfigError(f"{path}: briefing.limits entry {e!r} is malformed")
    return cfg


@functools.lru_cache(maxsize=1)
def config() -> dict:
    """The shipped configuration, read once per process."""
    return load_config(CONFIG_FILE)


# ── Receipts and sentences ───────────────────────────────────────────────────


def walk(obj: Any, path: str) -> Any:
    """The value at a dotted path ("hospitals.0.name"); a wrong path raises, because a
    receipt that does not resolve is a defect, never a silent null."""
    for part in path.split("."):
        obj = obj[int(part)] if isinstance(obj, list) else obj[part]
    return obj


class Outputs:
    """The tool outputs a form is assembled from, by tool name. Every tool receipt is
    made here, so its value is the value at its path."""

    def __init__(self, outputs: dict[str, Any]):
        self.outputs = outputs

    def get(self, tool: str) -> Any:
        return self.outputs.get(tool)

    def receipt(self, tool: str, path: str) -> dict:
        return {
            "kind": "tool",
            "tool": tool,
            "path": path,
            "value": walk(self.outputs[tool], path),
        }

    def value(self, tool: str, path: str) -> Any:
        return walk(self.outputs[tool], path)


def doc_receipt(doc_id: str, page: int) -> dict:
    return {
        "kind": "document",
        "doc_id": doc_id,
        "page": page,
        "locator": f"{doc_id}#p{page}",
    }


def locator_receipt(locator: str) -> dict:
    """A receipt from a pack locator, `doc_id#pNNN`."""
    doc_id, page = locator.rsplit("#p", 1)
    return doc_receipt(doc_id, int(page))


def page_of(locator: str) -> int:
    return int(locator.rsplit("#p", 1)[1])


def sentence(text: str, receipts: list[dict], **extra) -> dict:
    """One of our sentences, written to the stylebook, with its receipts."""
    return {"text": text, "quotation": False, "receipts": receipts, **extra}


def quotation(quote: str, tag: str, receipts: list[dict], **extra) -> dict:
    """An ERG sentence as printed, in quotation marks, then its source tag."""
    return {
        "text": f"“{quote}” {tag}",
        "quotation": True,
        "quote": quote,
        "receipts": receipts,
        **extra,
    }


_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def mdy(text: str) -> str:
    """ISO dates in a source tag written month/day/year (SB-NUM-06)."""
    return _ISO_DATE.sub(r"\2/\3/\1", text)


def with_page(tag: str, page: int) -> str:
    """A bracketed source tag with the PDF page added before its closing bracket."""
    return f"{tag[:-1]}, PDF p. {page}]"


# ── Markdown ─────────────────────────────────────────────────────────────────


def _inline(value) -> str:
    """A value as one Markdown line's text: whitespace (a newline included) collapses
    to one space, and a leading `#` or `-` is escaped, so no value starts a heading, a
    list item or a source tag of its own (review L3-6; inputs already refuse control
    characters, `models.plain_text`)."""
    text = " ".join(str(value).split())
    return "\\" + text if text.startswith(("#", "-")) else text


def _blank_line(b: dict) -> str:
    return f"- {b['field']}: blank; {b['label']} writes it."


def _sentence_lines(sentences: list[dict]) -> list[str]:
    """One bullet per sentence. A printed flag is one entry (HB-11b step 2): its heading
    in bold, then its fired-on line, consequence and response beneath it. A sentence
    that fills a form field (`field`, Block 1's incident name, HB-94) prints as the
    field."""
    out = []
    for s in sentences:
        text = _inline(s["text"])
        if s.get("field"):
            out.append(f"- {s['field']}: {text}")
        elif not s.get("flag"):
            out.append(f"- {text}")
        elif s["role"] == "fired_on":
            out += [f"- **{_inline(s['heading'])}**", f"  - {text}"]
        else:
            out.append(f"  - {s['role'].capitalize()}: {text}")
    return out


def _table(columns: list[str], rows: list[list[str]]) -> list[str]:
    def line(cells):
        return "| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |"

    return [line(columns), "|" + "|".join("---" for _ in columns) + "|"] + [
        line(r) for r in rows
    ]


def _annex(a: dict) -> list[str]:
    out = [f"## {a['title']}", "", "### Limits", ""]
    out += [f"- {_inline(s['text'])}" for s in a["limits"] + a["notes"]]
    out += ["", "### Sources", ""]
    out += _table(
        ["Source", "Used for"],
        [[x["tag"], x["supports"].replace("_", " ")] for x in a["sources"]],
    )
    return out + [""]


def render_markdown(form: dict) -> str:
    """The form as Markdown, block by block in the form's order, then Annex A.
    Deterministic: the same form gives the same bytes (the frozen forms hold it)."""
    cfg = config()["form"]
    out = [
        f"# {cfg['name']}",
        "",
        form["preamble"],
        "",
    ]
    for b in form["blocks"]:
        out += [f"## {b['number']}. {b['title']}", ""]
        if b["filled_by"] == "Incident Commander":
            out += [f"Blank: the {cfg['blank_label']} writes this block.", ""]
            continue
        for k, v in b.get("fields", {}).items():
            if isinstance(v, dict):
                v = "; ".join(f"{kk} {vv}" for kk, vv in v.items())
            label = k.replace("_", " ")
            out.append(f"- {label[0].upper()}{label[1:]}: {_inline(v)}")
        if b.get("fields"):
            out.append("")
        if b.get("map"):
            out += [f"![{b['map']['alt']}]({b['map']['href']})", ""]
        for sec in b["sections"]:
            if not sec["sentences"] and not sec.get("table"):
                continue
            if sec["heading"]:
                out += [f"### {sec['heading']}", ""]
            out += _sentence_lines(sec["sentences"])
            if sec.get("table"):
                t = sec["table"]
                out += [""] + _table(t["columns"], [r["cells"] for r in t["rows"]])
            out.append("")
        if b.get("blank"):
            out += [_blank_line(x) for x in b["blank"]]
            out.append("")
    if form.get("annex"):
        out += _annex(form["annex"])
    return "\n".join(out).rstrip("\n") + "\n"
