"""The flag evaluator: the deterministic half of DN-001 section 4 invariant 2.

Every flag is a rule in `packs/flag_rules.json` with a source. This module decides which
rules fire for an incident, from the values the tools return, and writes each fired
rule's sentence from its template. It never reads text, never ranks, never asks a model:
a rule fires when its predicate holds over the supplied values, and a rule whose inputs
are not all supplied does not fire and says which are missing. The model narrates the
fired flags; it never decides what is alarming.

Which rules apply to an incident (HB-12): the rules of the material's hazard class rule
set (`rule_sets`, the seed classes), the rules mined from the material's orange guide
(`guide_rule_sets`), and the rules that read pack fields for every material
(`table_rule_set`).
"""

from __future__ import annotations

from typing import Any

from hazbrief.models import FlagComparison, FlagRule, FlagRulesData


def _num(v: Any) -> Any:
    """A measured value may be supplied as `{"value": 3300, "text": "3.3 km (2.1 mi)"}`:
    the predicate compares the number, the sentence prints the text the tool printed."""
    return v["value"] if isinstance(v, dict) and "value" in v else v


class FlagError(ValueError):
    """A rule the evaluator cannot apply as written (an undeclared value, a bad
    operator)."""


def _value(t: FlagComparison, rule: FlagRule, values: dict) -> Any:
    if t.ref is not None:
        return _num(values.get(t.ref))
    if t.param is not None:
        if t.param not in rule.params:
            raise FlagError(f"{rule.rule_id}: param {t.param!r} is not declared")
        return rule.params[t.param]
    return t.value


def _holds(t: FlagComparison, rule: FlagRule, values: dict) -> bool:
    x = _num(values.get(t.input))
    if t.op == "is_true":
        return x is True
    if t.op == "is_false":
        return x is False
    y = _value(t, rule, values)
    if t.op == "eq":
        return x == y
    if t.op == "ne":
        return x != y
    if t.op == "in":
        return x in (y or [])
    try:
        return {
            "gt": x > y,
            "ge": x >= y,
            "lt": x < y,
            "le": x <= y,
        }[t.op]
    except TypeError:
        raise FlagError(f"{rule.rule_id}: {t.input} {t.op} {y!r} on {x!r}") from None


def needed(rule: FlagRule) -> list[str]:
    """The values the rule's predicate reads."""
    names = []
    for t in rule.predicate.terms:
        names.append(t.input)
        if t.ref:
            names.append(t.ref)
    return list(dict.fromkeys(names))


def _fmt(v: Any) -> str:
    if isinstance(v, dict) and "text" in v:
        return str(v["text"])
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, float):
        return f"{v:,.0f}" if v.is_integer() else f"{v:,.2f}"
    return str(v)


def _cause(pred, rule: FlagRule, values: dict) -> tuple[bool, list]:
    """(holds, missing) of one predicate: a predicate with an unsupplied value does not
    hold, and names the value."""
    names = []
    for t in pred.terms:
        names.append(t.input)
        if t.ref:
            names.append(t.ref)
    missing = [n for n in dict.fromkeys(names) if values.get(n) is None]
    if missing:
        return False, missing
    terms = [_holds(t, rule, values) for t in pred.terms]
    return (all(terms) if pred.mode == "all" else any(terms)), []


def cause_that_held(rule: FlagRule, values: dict):
    """The first of the rule's causes (its predicate, then each merged one) that holds
    over `values`, or None: what a fired flag fired on (HB-11b step 2)."""
    for pred in [rule.predicate] + [m.predicate for m in rule.merged]:
        if _cause(pred, rule, values)[0]:
            return pred
    return None


def evaluate(rule: FlagRule, values: dict) -> dict:
    """`{rule_id, fired, missing, sentence}`. A rule fires when its predicate holds or
    any cause merged into it does (HB-12b; DN-006 section 3.4). `missing` lists, for a
    rule that did not fire, the values it could not read (None). A fired rule's sentence
    fills its template from `values` and the rule's params; a template value not
    supplied is written "not available"."""
    causes = [rule.predicate] + [m.predicate for m in rule.merged]
    results = [_cause(p, rule, values) for p in causes]
    fired = any(h for h, _ in results)
    missing = (
        [] if fired else list(dict.fromkeys(n for _, miss in results for n in miss))
    )
    out = {"rule_id": rule.rule_id, "fired": fired, "missing": missing}
    if fired:
        fill = {
            **{k: _fmt(v) for k, v in rule.params.items()},
            **{
                i.name: _fmt(values[i.name])
                if values.get(i.name) is not None
                else "not available"
                for i in rule.inputs
            },
        }
        out["sentence"] = rule.template.format(**fill)
    return out


def applicable(
    data: FlagRulesData, hazard_class: str | None, guide: str | None
) -> list:
    """The rule ids that apply to a material: its hazard class's rule set, its guide's
    mined rules and the table rules, in that order, each once."""
    ids: list[str] = []
    if hazard_class is not None:
        ids += data.rule_sets.get(f"rules.{hazard_class}", [])
    if guide is not None:
        # guides 116P and 116 share one orange guide page (the P marks polymerization)
        ids += data.guide_rule_sets.get(guide.rstrip("P"), [])
    ids += data.table_rule_set
    return list(dict.fromkeys(ids))


def evaluate_all(
    data: FlagRulesData, values: dict, hazard_class: str | None, guide: str | None
) -> list[dict]:
    by_id = {r.rule_id: r for r in data.rules}
    return [evaluate(by_id[i], values) for i in applicable(data, hazard_class, guide)]


#: DN-006 section 3.6: the most flags one briefing prints (ISA-18.2's flood: more than
#: 10 alarms in 10 minutes at one position).
BRIEFING_LIMIT = 10
_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def for_briefing(fired: list, limit: int = BRIEFING_LIMIT) -> tuple[list, int]:
    """(shown, withheld): the fired flags a briefing prints, high then medium then low,
    ties by id, at most `limit`, and how many alarms were withheld. An indication (no
    ERG response) is never printed and is not counted as withheld; the structured output
    always carries every fired flag (DN-006 section 3.6)."""
    alarms = [f for f in fired if not f.indication]
    alarms.sort(key=lambda f: (_PRIORITY_ORDER[f.priority], f.rule_id))
    return alarms[:limit], max(0, len(alarms) - limit)
