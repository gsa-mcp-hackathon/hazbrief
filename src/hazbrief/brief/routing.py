"""Every ERG guide routed to a release model, or to "no dispersion model applies".

HB-120; DN-020 ADDENDUM-02 section 2 item 3: a table, built from the held ERG and
committed as pack data (`packs/release_routing.json`, from
`packs/src/release_routing.yaml` by `scripts/build_packs.py release_routing`), maps
each orange guide and the storage state of the material to a release model (two-phase
jet, evaporating pool, instantaneous) with its level-of-concern class, or to
`not_applicable` with the reason in a responder's words. Item 4: the modelled tier has
three states, and this module decides which, before anything reads a material's
properties (HB-120 ADDENDUM-01 section 2):

* **routed**: the guide and state name a release model and a level-of-concern class;
* **not applicable**: the guide (or the guide for this state) takes no dispersion
  model, and the reason is the ERG's own words. That is the chemistry, not a
  degradation;
* **not available**: a routed guide, but an input is missing: the storage state when
  the material's name states none and the guide's rows disagree, or the ID number.

A guide the table does not hold is an error (`RoutingError`), never a silent omission:
the build refuses a table that misses a guide of the held ERG, so at runtime it means
the ERG pack and the routing pack disagree.

`route()` is the lookup Issue d8668053's fix (wiring `materials.resolve` into the
brief) calls: it reads only the table, never the properties.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

#: A guide number as the ERG index prints it: three digits, and the letter (P) for a
#: material that "present[s] a polymerization hazard under certain conditions"
#: (erg2024-en-pdf p. 347): the same orange guide, so the table is keyed on the digits.
GUIDE = re.compile(r"^(?P<n>\d{3})P?$")
#: The ERG name states the storage state where it says so: the shipping description
#: names a refrigerated liquid (as `source_term.route_state` already reads it) or a
#: solid.
_REFRIGERATED = re.compile(r"refrigerated liquid", re.I)
_SOLID = re.compile(r"\bsolids?\b", re.I)

Status = Literal["routed", "not_applicable", "not_available"]


class RoutingError(LookupError):
    """A guide the routing table does not hold, or a guide number that is not one."""


@dataclass(frozen=True)
class Decision:
    """The modelled tier's state for one material (DN-020 ADDENDUM-02 item 4)."""

    status: Status
    guide: str | None
    state: str | None
    state_basis: str | None
    route: str | None = None
    loc_class: str | None = None
    reason: str | None = None
    basis: dict | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "guide": self.guide,
            "state": self.state,
            "state_basis": self.state_basis,
            "route": self.route,
            "loc_class": self.loc_class,
            "reason": self.reason,
            "basis": self.basis,
        }


def base_guide(guide: str | int | None) -> str:
    """The orange guide's number without the (P) letter; a value that is not a guide
    number raises."""
    m = GUIDE.match(str(guide or "").strip().upper())
    if not m:
        raise RoutingError(f"{guide!r} is not an ERG guide number")
    return m.group("n")


def name_state(names: list[str] | None) -> tuple[str | None, str | None]:
    """(state, basis) the ERG names state, or (None, None): "refrigerated liquid" first,
    then "solid"."""
    for n in names or []:
        if _REFRIGERATED.search(n):
            return "refrigerated_liquid", f"ERG name: {n!r}"
    for n in names or []:
        if _SOLID.search(n):
            return "solid", f"ERG name: {n!r}"
    return None, None


def storage_state(
    class_id: str | None, names: list[str] | None
) -> tuple[str | None, str]:
    """(state, basis) for a material: what its ERG name states, else its DN-001
    class's storage state (`source_term.CLASS_STATES`, HB-102's derivation), else
    (None, why)."""
    from hazbrief.brief import source_term as ST

    state, basis = name_state(names)
    if state is not None:
        return state, basis
    state = ST.CLASS_STATES.get(class_id or "")
    if state is not None:
        return state, f"DN-001 class {class_id}"
    return None, (
        "neither the ERG name nor a DN-001 class states the material's storage state"
    )


def guide_rows(table: dict, guide: str | int) -> tuple[str, dict]:
    """(guide number, its block) from the pack's `data`; a guide the table does not
    hold raises."""
    g = base_guide(guide)
    block = (table.get("guides") or {}).get(g)
    if block is None:
        raise RoutingError(
            f"guide {g} is not in the release routing table "
            "(packs/release_routing.json); every guide of the held ERG must be"
        )
    return g, block


def _decision(g, state, basis, row) -> Decision:
    if row["route"] == "not_applicable":
        return Decision(
            "not_applicable",
            g,
            state,
            basis,
            route=row["route"],
            reason=row["reason"],
            basis=row["basis"],
        )
    return Decision(
        "routed",
        g,
        state,
        basis,
        route=row["route"],
        loc_class=row["loc_class"],
        basis=row["basis"],
    )


def route(
    table: dict, guide: str | int, state: str | None, state_basis: str | None = None
) -> Decision:
    """The guide's route for a material in `state` (None where nothing states it).

    * an `any` row answers every state;
    * a stated state takes its row; a state the guide has no row for is not available;
    * no stated state: the guide's rows decide alone when they agree on the route and
      the class (HB-120 ADDENDUM-01 section 2); else not available, naming the storage
      state as what is missing."""
    g, block = guide_rows(table, guide)
    rows = {r["state"]: r for r in block["rows"]}
    if "any" in rows:
        return _decision(g, state, state_basis, rows["any"])
    if state is not None:
        row = rows.get(state)
        if row is None:
            return Decision(
                "not_available",
                g,
                state,
                state_basis,
                reason=(
                    f"Guide {g} has no release route for a material stored as "
                    f"{state.replace('_', ' ')} (it routes "
                    f"{', '.join(s.replace('_', ' ') for s in sorted(rows))})"
                ),
            )
        return _decision(g, state, state_basis, row)
    kinds = {(r["route"], r.get("loc_class")) for r in rows.values()}
    if len(kinds) == 1:
        first = block["rows"][0]
        return _decision(
            g, None, state_basis or "the guide routes every state alike", first
        )
    return Decision(
        "not_available",
        g,
        None,
        state_basis,
        reason=(
            f"the storage state is not held: {state_basis or 'nothing states it'}, "
            f"and Guide {g} routes "
            + "; ".join(
                f"{s.replace('_', ' ')} to {r['route'].replace('_', ' ')}"
                for s, r in sorted(rows.items())
            )
        ),
    )


def class_key(decision: Decision, keys: dict) -> str | None:
    """The dense-gas channel's class (`orchestrator.yaml` `dense_gas.classes`) for a
    routed decision, by `dense_gas.loc_class_keys`: a class key, or a map from the
    storage state to one (`any` for a state not stated). None if not routed."""
    if decision.status != "routed":
        return None
    k = keys[decision.loc_class]
    if isinstance(k, str):
        return k
    return k.get(decision.state or "any") or k["any"]


def load_table() -> tuple[dict, Any]:
    """(the pack's data, the pack) for `packs/release_routing.json`."""
    from hazbrief import packs as P

    pack = P.load_app_pack("release_routing")
    return pack.data.model_dump(mode="json"), pack


def modelled_route(table: dict, fp: dict) -> Decision:
    """The modelled tier's state for one footprint (`protective_action_footprint`'s
    result), read before any properties pack (HB-120 ADDENDUM-01 section 2):

    1. no guide: not available;
    2. the guide's route for the material's storage state; `not_applicable` ends here,
       whether or not the material is identified (Guide 111, a placard alone);
    3. a routed guide with no ID number: not available, the material is not identified;
    4. a routed guide whose rows disagree and no stated state: not available, naming the
       storage state;
    5. routed."""
    g = (fp.get("guide") or {}).get("number")
    if not g:
        return Decision(
            "not_available", None, None, None, reason="the footprint names no guide"
        )
    mat = fp.get("material") or {}
    class_id = (fp.get("hazard_class") or {}).get("class_id")
    state, basis = storage_state(class_id, mat.get("names"))
    d = route(table, g, state, basis)
    if d.status == "not_applicable":
        return d
    if not mat.get("un_number"):
        return Decision(
            "not_available",
            d.guide,
            d.state,
            d.state_basis,
            reason="the material is not resolved to an ID number",
        )
    return d
