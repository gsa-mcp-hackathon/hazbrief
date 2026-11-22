"""The entry form: a point and a situation line, parsed into three fields and shown back
for correction (HB-132R Part B; DN-022 section 7).

**The parse** (`Parser.parse`). A situation line is read into three fields, each with
the span of the line it came from:

- `material`: an ID number or a name as the line gives it, resolved through the ERG
  yellow index (`incident.resolve_material`, the server's own resolver), or unknown;
- `container`: one of the container classes DN-017's properties pack and HB-110's
  source term know (`orchestrator.yaml` `entry.containers`), or unknown;
- `state`: burning, leaking or unknown.

The parse is one recorded call of the brief's model route (HB-131R's
`model_author.ModelAuthor`, entry point `parse`, this task's prompt and run name): a
replay reads the transcript and makes no call. A bare UN number ("UN1017", "1017") is
read by rule and makes no call. Every span is checked to be a substring of the line as
typed; a parse whose span is not is refused with a structured error, as HB-131R's
refusals are (`EntryRefused`), and nothing is built from it.

**The route** (`route_of`). An unknown material that is burning is toxic smoke until
told otherwise (DN-021): ERG Guide 111 with the smoke client's fire block. An unknown
material that is leaking takes HB-15's unidentified-load route, Guide 111. A known
material takes its guide and HB-120's release routing (`routing.route`). A state the
line leaves unknown is shown back, and the build refuses until the reader says burning
or leaking: the ERG tables read whether fire is involved, and nothing here guesses it.

**The fixture** (`scenario_of`, `write_fixture`). The build route writes the form's
values as a scenario file in `docs/briefs/<id>/scenario.json`'s shape (the CLI's input)
before the build starts, so every brief the form starts is a fixture that replays. The
situation line and the parse go into it beside the scenario keys: they are form inputs,
which the build does not read (HB-132R ADDENDUM-02 section 3).

The application's code, not the server's: the container image ships without
`src/hazbrief/brief/` (`.dockerignore`).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hazbrief.brief import model_author
from hazbrief.config import REPO_ROOT

FIELDS = ("material", "container", "state")


@dataclass
class EntryRefused(Exception):
    """A parse or a build the form will not use: `code` names the rule, `detail` the
    offending part (HB-131R's refusal shape)."""

    code: str
    detail: str

    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"

    def to_json(self) -> dict:
        return {"error": {"code": self.code, "detail": self.detail}}


def _refuse(cfg: dict, code: str, **kw) -> EntryRefused:
    return EntryRefused(code, cfg["entry"]["refusals"][code].format(**kw))


# ── the material, through the ERG index ──────────────────────────────────────────────


def resolve_material(text: str) -> dict:
    """The material `text` names, through the ERG yellow index as the server resolves
    it (`incident.resolve_material`): its ID number, guide and the index's name, or why
    it does not resolve (not in the index, or several candidates: never a guess)."""
    from hazbrief import packs as P
    from hazbrief.incident import AmbiguousLoad, AssessmentError
    from hazbrief.incident import resolve_material as erg_resolve

    erg = P.default_packs().erg.data
    try:
        m = erg_resolve(text, erg)
    except AmbiguousLoad as exc:
        return {
            "resolved": False,
            "reason": exc.error,
            "candidates": [
                {"id_number": c.id_number, "guide": c.guide} for c in exc.materials
            ],
        }
    except AssessmentError as exc:
        return {"resolved": False, "reason": exc.error}
    name = m.matched_name
    if name is None and m.entry is not None:
        # HB-207 item 6: a material resolved by its ID number carries its ERG name,
        # the first the index prints under it with the resolved guide
        name = next((n.name for n in m.entry.names if n.guide == m.guide), None)
    return {
        "resolved": True,
        "id_number": m.id_number,
        "un": m.un,
        "guide": m.guide,
        "name": name,
        "coverage": m.coverage,
    }


def _erg():
    from hazbrief import packs as P

    return P.default_packs().erg.data


def _row(id_number: str, name: str, guide: str | None) -> dict:
    return {"id_number": id_number, "name": name, "guide": guide}


def index_rows(text: str) -> tuple[list[dict], str | None]:
    """(the index rows `text` names by the server's own resolver, why none): one row
    for an ID number or a name the index prints once; every row for a name printed
    under several ID numbers or an ID number whose names carry different guides
    (HB-18's candidates, in the index's order). Never a guess: a text the index does
    not print returns no row and the resolver's reason."""
    from hazbrief.incident import AmbiguousLoad, AssessmentError
    from hazbrief.incident import resolve_material as erg_resolve

    erg = _erg()
    try:
        m = erg_resolve(text, erg)
    except AmbiguousLoad as exc:
        # HB-18's candidates carry the index's own name and guide (`matched_name`);
        # a candidate with no ID number (an explosive, HB-17) is not offered
        rows = [
            _row(c.id_number, c.matched_name, c.guide)
            for c in exc.materials
            if c.id_number and c.matched_name
        ]
        return rows, exc.error
    except AssessmentError as exc:
        return [], exc.error
    if m.id_number is None:
        # an index row with no ID number (the explosives, HB-17): offered by its name
        # as printed, and built by that name
        return [_row(None, m.matched_name or text, m.guide)], None
    r = resolve_material(text)
    return [_row(m.id_number, r["name"] or text, m.guide)], None


def check_choice(obj: Any, cfg: dict) -> list[dict]:
    """The chooser's answer, `{"choices": [{id_number, name}, ...]}`, each checked to be
    an ERG 2024 yellow-index row byte for byte (`index_candidates.in_index`) and
    returned with the guide the index prints beside it; or `EntryRefused`. The model
    never supplies a guide, a distance or a property (HB-207 item 4)."""
    from hazbrief.index_candidates import in_index

    if (
        not isinstance(obj, dict)
        or set(obj) != {"choices"}
        or not isinstance(obj["choices"], list)
    ):
        raise _refuse(cfg, "choice_shape", detail=repr(obj)[:200])
    out: list[dict] = []
    for c in obj["choices"]:
        if not isinstance(c, dict) or set(c) != {"id_number", "name"}:
            raise _refuse(cfg, "choice_shape", detail=repr(c)[:200])
        row = in_index(str(c["id_number"]), str(c["name"]), _erg())
        if row is None:
            raise _refuse(
                cfg, "choice_not_in_index", id_number=c["id_number"], name=c["name"]
            )
        if row not in out:
            out.append(row)
    return out


def choose_material(
    typed: str, line: str, chooser: model_author.ModelAuthor | None, cfg: dict
) -> dict:
    """The ERG entries the typed material could be, best first, for the reader to
    confirm one (HB-207 items 3 to 5). `typed` the index prints (an ID number, or a
    name once or under several ID numbers): its rows, read by the index, no call
    (`via` index). Otherwise the index rows the typed words point to
    (`index_candidates.candidates`) go to one recorded call of the entry's chooser,
    which returns the ones the words name, best first, each checked to be an index row
    (`via` model); none, or no row the words point to, is a plain refusal (`reason`)
    and nothing is offered."""
    from hazbrief.index_candidates import candidates

    e = cfg["entry"]
    out: dict[str, Any] = {"typed": typed, "candidates": [], "via": "index"}
    out["call"] = None
    rows, why = index_rows(typed)
    if rows:
        out["candidates"] = rows
        return out
    short = candidates(typed, _erg())
    if not short:
        out["reason"] = e["choice"]["none_near"].format(typed=typed)
        return out
    if chooser is None:
        out["reason"] = e["choice"]["no_route"].format(typed=typed)
        return out
    before = chooser.calls_made
    payload = {"line": line, "typed": typed, "candidates": short}
    try:
        rec = chooser.call("choose", payload)
    except model_author.NoRecordedCall as exc:
        raise EntryRefused("no_recorded_call", str(exc)) from exc
    except model_author.ModelRouteError as exc:
        raise EntryRefused("model_route", str(exc)) from exc
    out["via"] = "model"
    out["shortlist"] = short
    out["call"] = {
        "transcript": rec["key"],
        "request_sha256": rec["request_sha256"],
        "response_sha256": rec["response_sha256"],
        "model": rec["model"],
        "calls_made": chooser.calls_made - before,
    }
    if not rec["ok"]:
        raise EntryRefused("call_failed", rec["error"])
    try:
        obj = model_author.parse_answer(rec["result"])
    except model_author.Refusal as r:
        raise EntryRefused(r.code, r.detail) from r
    out["candidates"] = check_choice(obj, cfg)
    if not out["candidates"]:
        out["reason"] = e["choice"]["none_named"].format(typed=typed)
    return out


def confirmed_row(f: Any, cfg: dict) -> dict:
    """The ERG entry the reader confirmed (`{id_number, name}`), checked to be an index
    row byte for byte, with its guide; or `EntryRefused`."""
    from hazbrief.index_candidates import in_index

    if not isinstance(f, dict) or not f.get("name"):
        raise _refuse(cfg, "material_unconfirmed")
    row = in_index(f.get("id_number"), str(f["name"]), _erg())
    if row is None:
        raise _refuse(
            cfg, "choice_not_in_index", id_number=f["id_number"], name=f["name"]
        )
    return row


# ── the assumptions the form proposes (HB-207 Part C; ADDENDUM-03) ───────────────────


def _class_id(un: str | None) -> str | None:
    """The material's DN-001 hazard class, as `assess_incident` reads it (the
    `hazard_classes` pack's members)."""
    from hazbrief import packs as P

    if not un:
        return None
    hc = next(
        (c for c in P.default_packs().hazard_classes.data.classes if un in c.members),
        None,
    )
    return hc.class_id if hc else None


def release_state(row: dict) -> dict:
    """The storage state the build will route on for the confirmed entry, and its
    basis, by the build's own two readings (`routing.storage_state`, which the release
    route reads, and `source_term.route_state`, which the source term reads; both from
    the ERG name, else the DN-001 class), and the routing table's decision for its
    guide. The form proposes; the build decides the same way, from the same packs."""
    from hazbrief import packs as P
    from hazbrief.brief import routing

    un = row["id_number"][2:] if row.get("id_number") else None
    entry = P.default_packs().erg.data.index.get(un) if un else None
    names = [n.name for n in entry.names] if entry else [row["name"]]
    class_id = _class_id(un)
    state, basis = routing.storage_state(class_id, names)
    table, _ = routing.load_table()
    try:
        d = routing.route(table, row["guide"], state, basis)
        decision = {"status": d.status, "route": d.route, "reason": d.reason}
    except routing.RoutingError as exc:
        decision = {"status": "not_available", "route": None, "reason": str(exc)}
    return {"state": state, "basis": basis, "class_id": class_id, "route": decision}


def proposed_quantity(container: str, state: str | None, cfg: dict) -> dict:
    """The release quantity the form proposes (HB-207 item 8): the shipment amount the
    held ERG 2024 methodology profile gives for the container (Table 2.3 for a gas,
    Table 2.2 for a liquid), with its source in a few words; or, where no held row
    gives one, `kg` None and the question to ask. Never a number from anywhere else."""
    p = cfg["entry"]["profiles"]
    kind = p["kind_by_state"].get(state or "")
    cell = (p["rows"].get(kind) or {}).get(container) if kind else None
    if cell is None:
        why = (
            p["no_container"]
            if container == "unknown"
            else p["no_state"]
            if kind is None
            else p["no_row"].format(container=container)
        )
        return {"kg": None, "ask": p["ask"], "why": why}
    t = p["tables"][kind]
    source = p["source"].format(
        container=container,
        kg=cell["kg"],
        profile_container=cell["container"],
        table=t["table"],
        page=t["page"],
        printed=t["printed_page"],
        example=t["example"],
    )
    return {
        "kg": cell["kg"],
        "source": source,
        "short": p["short"].format(
            container=container,
            kg=cell["kg"],
            state=p["state_words"].get(state, state),
            table=t["table"],
        ),
        "basis": {"doc": p["doc"], "page": t["page"], "block": t["block"]},
    }


def levels_note(row: dict, cfg: dict) -> str | None:
    """HB-207 item 10: the plain sentence for a material whose health-effect levels are
    not held (no AEGL cell held at any duration in the materials pack, the cells the
    modelled cloud is drawn by: `scichem.tiers_from_pack`), else None."""
    from hazbrief import packs as P

    if not row.get("id_number"):
        return None
    un = row["id_number"][2:]
    try:
        mats = P.load_app_pack("materials_properties").data.model_dump(mode="json")
    except P.PackError:
        return None
    cells = ((mats.get("materials") or {}).get(un) or {}).get("aegl_ppm") or {}
    held = any(
        (v or {}).get("status") == "held"
        for by_min in cells.values()
        for v in (by_min or {}).values()
    )
    if held:
        return None
    return cfg["entry"]["levels_none"].format(
        id_number=row["id_number"], name=row["name"]
    )


def assumptions(
    fields: dict[str, dict], row: dict | None, incident_time: str, cfg: dict
) -> dict:
    """What the form proposes beside the parse, each with its source, for the reader to
    correct before the build (HB-207 item 9; ADDENDUM-03 item 1): the start time (now,
    unless the reader changes it), the storage state and the release quantity for the
    confirmed entry and the container, and the standing worst-case line."""
    e = cfg["entry"]
    out: dict[str, Any] = {
        "start_time": {"value": incident_time, "note": e["start_time_note"]},
        "worst_case": e["worst_case"],
    }
    if row is None:
        out["waits_on_material"] = e["waits_on_material"]
        return out
    rs = release_state(row)
    out["storage_state"] = rs
    note = levels_note(row, cfg)
    if note:
        out["levels"] = note
    if rs["route"]["status"] == "not_applicable":
        # HB-120: the guide takes no release model; no quantity is asked for
        out["quantity"] = {"kg": None, "why": rs["route"]["reason"]}
        return out
    out["quantity"] = proposed_quantity(fields["container"]["value"], rs["state"], cfg)
    return out


# ── the parse ────────────────────────────────────────────────────────────────────────


def _field(value: str | None, span: str | None) -> dict:
    return {"value": value if value is not None else "unknown", "span": span}


def check_parse(obj: Any, line: str, cfg: dict) -> dict[str, dict]:
    """The three fields of a parse, each `{value, span}` (`unknown` with no span when
    the line does not say), or `EntryRefused`. Every span must be a substring of the
    line as typed (HB-132R ADDENDUM-01 section 2); a container or a state must be one
    the form knows."""
    e = cfg["entry"]
    if not isinstance(obj, dict) or set(obj) - set(FIELDS):
        raise _refuse(cfg, "shape", detail=repr(obj)[:200])
    out: dict[str, dict] = {}
    for name in FIELDS:
        f = obj.get(name)
        if f is None:
            out[name] = _field(None, None)
            continue
        if (
            not isinstance(f, dict)
            or not isinstance(f.get("value"), str)
            or not isinstance(f.get("span"), str)
            or not f["value"].strip()
            or not f["span"]
        ):
            raise _refuse(cfg, "shape", detail=f"{name}: {f!r}"[:200])
        if f["span"] not in line:
            raise _refuse(cfg, "span_not_in_line", field=name, span=f["span"])
        out[name] = {"value": f["value"].strip(), "span": f["span"]}
    if out["container"]["value"] not in e["containers"]:
        raise _refuse(
            cfg,
            "container",
            value=out["container"]["value"],
            allowed=", ".join(e["containers"]),
        )
    if out["state"]["value"] not in e["states"]:
        raise _refuse(
            cfg, "state", value=out["state"]["value"], allowed=", ".join(e["states"])
        )
    return out


def route_of(fields: dict[str, dict], cfg: dict) -> dict:
    """Where the three fields send the brief (DN-022 section 7): the smoke case, the
    unidentified load, or the material's guide and HB-120's release routing. A state
    left unknown routes nowhere until the reader says which."""
    e = cfg["entry"]
    mat, state = fields["material"], fields["state"]["value"]
    if state == "unknown":
        return {"kind": None, "why": e["refusals"]["state_unknown"]}
    if mat["value"] == "unknown":
        kind = "smoke" if state == "burning" else "unidentified_load"
        return {
            "kind": kind,
            "guide": e["unidentified_guide"],
            "why": e["routes"][kind],
        }
    row = mat.get("confirmed")
    if row is None:
        res = mat.get("erg") or resolve_material(mat["value"])
        if not res["resolved"]:
            return {
                "kind": "guide",
                "guide": None,
                "why": e["routes"]["guide"],
                "unresolved": res["reason"],
            }
        row = _row(res["id_number"], res["name"] or mat["value"], res["guide"])
    # HB-207 item 10: the release route as the build reads it, from the ERG name and
    # the DN-001 class (before HB-207 the form read the name alone and showed a routed
    # guide as "the storage state is not held")
    rs = release_state(row)
    return {
        "kind": "guide",
        "guide": row["guide"],
        "why": e["routes"]["guide"],
        "release": {**rs["route"], "state": rs["state"], "state_basis": rs["basis"]},
    }


def with_erg(fields: dict[str, dict]) -> dict[str, dict]:
    """The fields with the material's ERG resolution beside it (`erg`), as the form
    shows it back: the confirmed entry's ID number where the reader confirmed one,
    else the value as typed."""
    mat = fields["material"]
    if mat["value"] == "unknown":
        return fields
    row = mat.get("confirmed")
    res = resolve_material((row["id_number"] or row["name"]) if row else mat["value"])
    if row is not None and not res["resolved"]:
        res = resolve_material(row["name"])
    return {**fields, "material": {**mat, "erg": res}}


class Parser:
    """The situation line's parser: a bare UN number by rule, any other line by one
    recorded call of the brief's model route. `author` None: only the rule (a line it
    does not read is refused, naming the missing route)."""

    def __init__(
        self,
        cfg: dict,
        author: model_author.ModelAuthor | None,
        chooser: model_author.ModelAuthor | None = None,
    ):
        self.cfg = cfg
        self.author = author
        #: HB-207 item 3: the second recorded call, which chooses among the index rows
        #: a typed name points to when the index does not print it
        self.chooser = chooser

    @property
    def calls_made(self) -> int:
        return sum(a.calls_made for a in (self.author, self.chooser) if a is not None)

    def parse(self, line: str, now: str | None = None) -> dict:
        """The parse of `line`: the three fields with their spans and the material's
        ERG resolution, the route, how it was read (`rule` or `model`) and, for a model
        call, the call's hashes; the ERG entries the material could be, best first, for
        the reader to confirm one (`material_choice`, HB-207 items 3 to 5); and what
        the form proposes beside them (`assumptions`, items 8 and 9 and ADDENDUM-03),
        with `now` as the start time; or `EntryRefused`."""
        e = self.cfg["entry"]
        if (
            not isinstance(line, str)
            or not line.strip()
            or len(line) > int(e["line_max_chars"])
        ):
            raise _refuse(self.cfg, "line", n=int(e["line_max_chars"]))
        bare = re.match(e["bare_un"], line, re.I)
        call = None
        if bare:
            span = bare.group(1)
            obj = {"material": {"value": span, "span": span}}
            via = "rule"
        else:
            if self.author is None:
                raise EntryRefused(
                    "no_model_route", "this form has no parser route for a line"
                )
            payload = {
                "line": line,
                "containers": [c for c in e["containers"] if c != "unknown"],
                "states": [s for s in e["states"] if s != "unknown"],
            }
            before = self.author.calls_made
            try:
                rec = self.author.call("parse", payload)
            except model_author.NoRecordedCall as exc:
                raise EntryRefused("no_recorded_call", str(exc)) from exc
            except model_author.ModelRouteError as exc:
                raise EntryRefused("model_route", str(exc)) from exc
            call = {
                "transcript": rec["key"],
                "request_sha256": rec["request_sha256"],
                "response_sha256": rec["response_sha256"],
                "model": rec["model"],
                "calls_made": self.author.calls_made - before,
            }
            if not rec["ok"]:
                raise EntryRefused("call_failed", rec["error"])
            try:
                obj = model_author.parse_answer(rec["result"])
            except model_author.Refusal as r:
                raise EntryRefused(r.code, r.detail) from r
            via = "model"
        fields = with_erg(check_parse(obj, line, self.cfg))
        mat = fields["material"]
        if mat["value"] == "unknown":
            choice = {
                "typed": None,
                "candidates": [],
                "via": None,
                "call": None,
                "question": e["material_question"],
            }
        else:
            choice = choose_material(mat["value"], line, self.chooser, self.cfg)
        first = (choice["candidates"] or [None])[0]
        return {
            "line": line,
            "fields": fields,
            "route": route_of(fields, self.cfg),
            "via": via,
            "call": call,
            "material_choice": choice,
            "assumptions": assumptions(fields, first, now, self.cfg),
        }


def parser_from_config(
    cfg: dict, *, replay: bool, transcripts: Path | None = None
) -> Parser:
    """The parser on the route `orchestrator.yaml` `entry` names: HB-131R's
    `ModelAuthor` with the entry form's own prompt file, run name and transcripts."""
    e = cfg["entry"]
    mcfg = {
        **cfg,
        "model": {**cfg["model"], "prompt": e["prompt"], "hold_run": e["hold_run"]},
    }
    path = transcripts or (REPO_ROOT / e["transcripts_dir"])
    held = tuple(REPO_ROOT / d for d in e.get("held_transcripts") or ())
    ccfg = {
        **cfg,
        "model": {
            **cfg["model"],
            "prompt": e["choice"]["prompt"],
            "hold_run": e["hold_run"],
        },
    }
    return Parser(
        cfg,
        model_author.ModelAuthor(mcfg, transcripts=path, replay=replay, held_dirs=held),
        model_author.ModelAuthor(ccfg, transcripts=path, replay=replay, held_dirs=held),
    )


# ── the fixture the build writes ─────────────────────────────────────────────────────


def corrected(fields: dict, cfg: dict) -> dict[str, dict]:
    """The three fields as the reader left them on the form (`{name: {value, span}}`
    or `{name: value}`), checked as a parse is: a corrected value keeps no span unless
    the reader left the parsed one."""
    out = {}
    for name in FIELDS:
        f = fields.get(name)
        if isinstance(f, str):
            f = {"value": f, "span": None}
        if not isinstance(f, dict) or not isinstance(f.get("value"), str):
            raise _refuse(cfg, "shape", detail=f"{name}: {f!r}"[:200])
        v = f["value"].strip() or "unknown"
        out[name] = {"value": v, "span": f.get("span")}
    e = cfg["entry"]
    if out["container"]["value"] not in e["containers"]:
        raise _refuse(
            cfg,
            "container",
            value=out["container"]["value"],
            allowed=", ".join(e["containers"]),
        )
    if out["state"]["value"] not in e["states"]:
        raise _refuse(
            cfg, "state", value=out["state"]["value"], allowed=", ".join(e["states"])
        )
    if out["material"]["value"] != "unknown":
        # HB-207 item 5: nothing is built until the reader confirms one ERG entry,
        # checked to be an index row byte for byte
        mat = fields.get("material")
        row = confirmed_row(
            mat.get("confirmed") if isinstance(mat, dict) else None, cfg
        )
        out["material"]["confirmed"] = row
    return with_erg(out)


def release_of(given: Any, fields: dict[str, dict], cfg: dict) -> dict | None:
    """The scenario's `release` block (DN-018 ADDENDUM-00 section 3) from the quantity
    the reader left on the form (HB-207 items 8 and 9): the proposal's own source where
    the reader kept the proposed number, the reader's entry where they changed it, and
    no block where none is given (the modelled layers then say the quantity is not
    given). A quantity that is not a positive number is refused."""
    e = cfg["entry"]
    kg = given.get("quantity_kg") if isinstance(given, dict) else None
    if kg is None or kg == "":
        return None
    try:
        kg = float(kg)
    except (TypeError, ValueError):
        raise _refuse(cfg, "quantity", value=repr(kg)[:40]) from None
    if not (0 < kg < float("inf")):
        raise _refuse(cfg, "quantity", value=repr(kg)[:40])
    row = fields["material"].get("confirmed")
    proposed: dict = {}
    if row is not None:
        rs = release_state(row)
        proposed = proposed_quantity(fields["container"]["value"], rs["state"], cfg)
    if proposed.get("kg") is not None and float(proposed["kg"]) == kg:
        source = f"{proposed['source']}; {e['worst_case']}"
    else:
        source = e["profiles"]["reader_source"]
    return {"quantity_kg": kg, "quantity_source": source}


def incident_time_of(given: Any, default: str, cfg: dict) -> str:
    """The start time the reader confirmed (ISO 8601 with an offset), else `default`;
    a time that does not parse, or names no offset, is refused (ADDENDUM-03 item 1)."""
    from datetime import datetime

    if given is None or given == "":
        return default
    try:
        t = datetime.fromisoformat(str(given).replace("Z", "+00:00"))
    except ValueError:
        raise _refuse(cfg, "incident_time", value=repr(given)[:60]) from None
    if t.tzinfo is None:
        raise _refuse(cfg, "incident_time", value=repr(given)[:60])
    return t.isoformat()


def incident_of(fields: dict[str, dict], cfg: dict) -> tuple[dict, dict | None]:
    """(the incident's load, container and fire, the scenario's `fire` block or None)
    for the three fields. Refuses a state left unknown."""
    e = cfg["entry"]
    route = route_of(fields, cfg)
    if route["kind"] is None:
        raise _refuse(cfg, "state_unknown")
    burning = fields["state"]["value"] == "burning"
    inc: dict[str, Any] = {}
    if route["kind"] in ("smoke", "unidentified_load"):
        inc["guide_number"] = e["unidentified_guide"]
    else:
        res = fields["material"].get("erg") or {}
        row = fields["material"].get("confirmed")
        if row is not None:
            # HB-207 item 5: the confirmed entry, by its ID number where the index
            # resolves that number to one guide, else by its name as printed
            by_id = resolve_material(row["id_number"]) if row["id_number"] else {}
            inc["material"] = row["id_number"] if by_id.get("resolved") else row["name"]
        else:
            # the ID number the index resolved, else the name as typed (the server
            # resolves it again and says why it cannot: an unresolved material is a
            # degraded brief, never a guessed one)
            inc["material"] = res.get("id_number") or fields["material"]["value"]
    inc["container"] = fields["container"]["value"]
    inc["fire_involved"] = burning
    inc["spill_size"] = e["spill_size"]
    inc["where_spilled"] = e["where_spilled"]
    fire = dict(e["smoke_fire"]) if route["kind"] == "smoke" else None
    return inc, fire


def scenario_of(
    *,
    point: dict | None,
    given: dict | None,
    fields: dict[str, dict],
    line: str,
    parse: dict | None,
    incident_time: str,
    weather: dict | None,
    cfg: dict,
    release: dict | None = None,
) -> dict:
    """The scenario file the build route writes before the build (HB-132R item 5), in
    the CLI's input shape: `id`, `incident`, `as_given`, `given` for a typed location,
    `fire` for the smoke case, and `weather` when the form's selection is not the
    default (HB-132R ADDENDUM-02 section 2). Its id is the sha256 of its content, so the
    same form values name the same fixture. `situation` and `entry` are the form's
    inputs, which the build does not read."""
    if point is None and given is None:
        raise _refuse(cfg, "no_point")
    inc, fire = incident_of(fields, cfg)
    if point is not None:
        inc["location"] = {
            "latitude": float(point["latitude"]),
            "longitude": float(point["longitude"]),
        }
    # a typed location carries no point: the brief locates it by its own DN-013
    # derivation and asks every tool about the shape's representative point, as the
    # location scenarios do (fixtures/location_scenarios.yaml)
    inc["incident_time"] = incident_time
    body: dict[str, Any] = {"incident": inc, "as_given": incident_time}
    if given is not None:
        body["given"] = given
    if fire is not None:
        body["fire"] = fire
    if weather is not None:
        body["weather"] = weather
    if release is not None:
        # HB-207 Part C (Issue dff94fb5): the quantity the form proposed or the reader
        # gave, so the modelled layers reach their source term
        body["release"] = release
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return {
        "id": f"entry-{digest[:12]}",
        **body,
        "situation": line,
        "entry": {"fields": fields, "parse": parse},
    }


def write_fixture(scenario: dict, cfg: dict, root: Path | None = None) -> Path:
    """`<entry.fixtures_dir>/<id>.json`, written whole and fsynced before the build
    starts (standards section 15 rule 1)."""
    d = Path(root) if root is not None else REPO_ROOT / cfg["entry"]["fixtures_dir"]
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{scenario['id']}.json"
    data = json.dumps(scenario, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)
    return path
