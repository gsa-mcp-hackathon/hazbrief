"""The TEVV page: one section per thing the brief draws or states from a method (HB-161
ADDENDA 01 to 05; the operator's statements of 2026-11-11 06:38, 07:12 and 07:29 EST).

The map carries a layer's name, its symbol and its key. How the layer was made, what it
was checked against, what it does not do and the sources it rests on are this page's,
read one action from the brief: a reference number ("T7") at the end of the layer's row,
on its popup, in a tab's summary, beside a method's heading and on each Sources and MCP
servers row that feeds it opens `tevv.html#t7` in a new tab.

- **The registry** (`orchestrator.yaml` `tevv.sections`): a number belongs to an id,
  never to a brief, so the same number means the same thing on all 28 briefs, and a
  number is never reused. `registry` refuses a duplicate number or id at load.
- **The fields** are fixed (`tevv.fields`), each a statement of fact: what it is;
  method and its source; inputs for this brief and where each came from; the run
  record; checked against; not checked against; limits the method's own source
  states; agreement between methods; further checks, not run. The documentation a
  modelled layer used to carry on the map (its legend's prose, its popup rows of
  method and caveat, its label lines) is moved here by `layers.build`
  (`layer["doc"]`) word for word; a string a section already holds from an earlier
  section reads "as in T<n>" instead of repeating.
- **What is not decided here.** "Checked against" and "not checked against" are HB-159's
  to set from the graph (HB-159 ADDENDUM-02); until then each section says
  `pending_state`. "Agreement between methods" for a modelled layer is HB-163's
  (ADDENDUM-03 item 1).
- **No tool hazbrief does not run is named on the brief** (ADDENDUM-02 item 1). On this
  page a tool's name appears only inside a cited document's title and in "Further
  checks, not run" (item 2 and 3).

The static page writes `tevv.html` beside `brief.html` (`cli.write_outputs`); the live
shell serves the same bytes from the run's brief (`web.create_app`, `GET /tevv.html`).
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

from hazbrief.brief import benchmark_table as BT
from hazbrief.evidence import labels as L


def esc(text: Any) -> str:
    return html.escape(str(text), quote=True)


class TevvError(RuntimeError):
    """The registry breaks its own rule (a number or id used twice)."""


def registry(cfg: dict) -> dict[str, dict]:
    """Section id -> its registry entry, in number order; a number or id used twice,
    retired or not, is refused (ADDENDUM-01 item 2: a number is never reused)."""
    secs = cfg["tevv"]["sections"]
    nums = [s["n"] for s in secs]
    ids = [s["id"] for s in secs]
    if len(set(nums)) != len(nums) or len(set(ids)) != len(ids):
        raise TevvError(f"tevv.sections reuses a number or an id: {nums} {ids}")
    return {s["id"]: s for s in sorted(secs, key=lambda s: s["n"])}


def section_of(cfg: dict, sid: str) -> str:
    """The section a layer id documents: its own, or the one `tevv.aliases` names
    (HB-163:
    the cloud's three level layers are one section, the harm path)."""
    return (cfg["tevv"].get("aliases") or {}).get(sid, sid)


def brief_cfg(cfg: dict, brief) -> dict:
    """The configuration a brief's sections are read with (HB-162R; DN-025 section 3
    item 5): where the brief's cloud is drawn by an engine `tevv.engine_aliases` names
    (the puff, on a passive release), its level layers, steps and point lines document
    that engine's sections; otherwise `cfg` itself, unchanged."""
    cl = ((getattr(brief, "derived", None) or {}).get("cloud")) or {}
    extra = (cfg["tevv"].get("engine_aliases") or {}).get(cl.get("engine_key") or "")
    if not extra:
        return cfg
    t = {**cfg["tevv"], "aliases": {**(cfg["tevv"].get("aliases") or {}), **extra}}
    return {**cfg, "tevv": t}


def ref(cfg: dict, sid: str) -> str | None:
    """Section `sid`'s number ("T7"); None for an id not held or retired."""
    sid = section_of(cfg, sid)
    s = registry(cfg).get(sid)
    if s is None or s.get("retired"):
        return None
    return f"{cfg['tevv']['prefix']}{s['n']}"


def anchor(cfg: dict, sid: str) -> str:
    return f"t{registry(cfg)[section_of(cfg, sid)]['n']}"


def href(cfg: dict, sid: str) -> str:
    return f"{cfg['tevv']['file']}#{anchor(cfg, sid)}"


def link_html(cfg: dict, sid: str) -> str:
    """The reference number as the brief prints it: a small link opening the section in
    a new tab; "" for an id with no live section."""
    r = ref(cfg, sid)
    if r is None:
        return ""
    s = registry(cfg)[section_of(cfg, sid)]
    title = cfg["tevv"]["link_title"].format(ref=r, what=s["what"].rstrip("."))
    return (
        f'<a class="tref" href="{esc(href(cfg, sid))}" target="_blank" '
        f'rel="noopener" title="{esc(title)}">{esc(r)}</a>'
    )


def layer_ref(cfg: dict, sid: str) -> dict | None:
    """The `tevv` entry a drawn layer carries in the map data, which the map script
    appends to every popup of the layer (one per layer, not per feature)."""
    r = ref(cfg, sid)
    if r is None:
        return None
    return {"ref": r, "href": href(cfg, sid)}


# ── which sections a brief has ──────────────────────────────────────────────────────


class _EveryCandidate:
    """HB-192 (DN-024 ADDENDUM-01 decision 9): the brief as the TEVV page reads it: a
    road layer's section documents every candidate the data holds, as the engine's
    sensors do, not only those the first map draws."""

    every_candidate = True

    def __init__(self, brief):
        self._brief = brief

    def __getattr__(self, name: str):
        return getattr(self._brief, name)


def _tevv_data(brief, cfg: dict) -> dict:
    from hazbrief.brief import layers

    return layers.build(_EveryCandidate(brief), cfg)


def present(brief, cfg: dict, data: dict | None = None) -> list[str]:
    """The section ids this brief refers to, in number order: every drawn layer (the
    built layers with a feature, the roads image, the weather layers drawn from the
    derivations) and the methods it states (the source term where a modelled layer is
    computed on one, the stability class, the time steps)."""

    cfg = brief_cfg(cfg, brief)
    data = data if data is not None else _tevv_data(brief, cfg)
    derived = getattr(brief, "derived", None) or {}
    have = {section_of(cfg, lay["id"]) for lay in data["layers"] if lay["features"]}
    # the layer list always lists the roads image's row (`render._layer_list_html`)
    have.add("roads")
    for name in ("radar", "satellite"):
        if (derived.get(name) or {}).get("held"):
            have.add(name)
    if (derived.get("wind_field") or {}).get("cells"):
        have.add("wind_field")
    for name in ("radar", "satellite"):
        if ((derived.get("snapshots") or {}).get(name) or {}).get("held"):
            have.add(f"{name}_snapshot")
    if source_term_of(brief) is not None:
        have.add("source_term")
    if (derived.get("stability") or {}).get("class"):
        have.add("stability_class")
    tl = ((derived.get("puff") or {}).get("timeline")) or {}
    if tl.get("steps") and not tl.get("reason"):
        have.add("time_steps")
    # HB-163: the selection rule wherever it classed a release; the cloud at a time and
    # its measured places wherever the cloud is drawn
    if derived.get("engine_rule"):
        have.add("engine_rule")
    cl = derived.get("cloud") or {}
    if cl.get("state") == "drawn":
        # the drawing engine's own sections (`brief_cfg`)
        have.add(section_of(cfg, "cloud_at_time"))
        kinds = {p["kind"] for p in cl.get("places") or []}
        if kinds & {"named_place", "sited"}:
            have.add(section_of(cfg, "arrival_lines"))
        if "roadblock" in kinds:
            have.add(section_of(cfg, "roadblock_lines"))
        # HB-171: the threat timeline wherever the cloud is drawn
        have.add("threat_timeline")
        # HB-173: the two engines' measure wherever SCICHEM's cloud is drawn
        if derived.get("agreement"):
            have.add("agreement")
            # HB-184 (DN-028 ADDENDUM-10 decision 5): both engines run for every such
            # release, so both engines' conditions of use are stated
            have.add("conditions_scichem")
            have.add("conditions_slab")
            # HB-192: the benchmark requirement wherever SCICHEM's cloud is drawn
            have.add("benchmarks")
            # HB-189 (DN-028 ADDENDUM-14 decision 6): under the stable treatment the
            # page states the planning area's method and refers to T56 wherever it
            # plans (`render`'s population row, `threat`'s untimed note), also where
            # SLAB's extent check adds no area and so draws no layer of its own
            if (derived.get("agreement") or {}).get("planning"):
                have.add("planning_shape")
    reg = registry(cfg)
    return [sid for sid in reg if sid in have and not reg[sid].get("retired")]


def source_term_of(brief) -> dict | None:
    """The source term the modelled layers were computed on: the puff's
    `source_term_run` (HB-110), else None."""
    p = ((getattr(brief, "derived", None) or {}).get("puff")) or {}
    st = p.get("source_term_run")
    return st if isinstance(st, dict) and st else None


# ── the fields ──────────────────────────────────────────────────────────────────────


def _record_line(r: dict, tz: str) -> str:
    """One input as a line: name, value, source, and as-of where there is one."""
    when = f", as of {L.when(r['as_of'], tz)}" if r.get("as_of") else ""
    sha = f", sha256 {r['sha256']}" if r.get("sha256") else ""
    return f"{r['name']}: {r['value']} ({r.get('source')}{when}{sha})"


def _empty(cfg: dict) -> dict[str, list[str]]:
    return {f["key"]: [] for f in cfg["tevv"]["fields"]}


def _layer_fields(brief, cfg: dict, lays: list[dict]) -> dict[str, list[str]]:
    """A drawn layer's fields (or, for a section several layers document, theirs in
    turn): the registry's words, then what `layers.build` moved off the map
    (`lay["doc"]`) into the field the moved row names; a string two layers share is
    listed once."""
    s = registry(cfg)[section_of(cfg, lays[0]["id"])]
    out = _empty(cfg)
    for lay in lays:
        doc = lay.get("doc") or {}
        out["inputs"] += doc.get("labels") or []
        for clause in doc.get("legend") or []:
            out["inputs"].append(clause)
        for head, value, field in doc.get("rows") or []:
            out[field].append(f"{head}: {value}")
        out["run_record"] += doc.get("records") or []
        out["method"] += doc.get("method") or []
    # HB-221 item 4: the cloud's levels' section states, in its own line, the forecast
    # precipitation the run was not given (the label's clause may print "as in" an
    # earlier section); nothing on a dry forecast
    from hazbrief.brief import layers

    if lays[0]["id"] in layers.cloud_level_ids(cfg):
        cl = (getattr(brief, "derived", None) or {}).get("cloud") or {}
        line = layers.rain_words(brief, cl, cfg, "tevv")
        if line is not None:
            out["limits"].append(line)
    for k in out:
        out[k] = list(dict.fromkeys(out[k]))
    return _with_registry(cfg, s, out, brief)


def _with_registry(cfg: dict, s: dict, out: dict[str, list[str]], brief=None) -> dict:
    out["what"].insert(0, s["what"])
    if s.get("method"):
        out["method"].insert(0, s["method"])
    out["checked"] = list(s.get("checked") or []) + out["checked"]
    # HB-178 (Issue d16f6882): SLAB's and SCICHEM's sections name the held trials of
    # this brief's own material, or say none is, from one table (`trials.yaml`)
    from hazbrief.brief import trials

    derived = (getattr(brief, "derived", None) or {}) if brief is not None else {}
    un = (derived.get("dense_gas") or {}).get("un")
    out["checked"][1:1] = trials.lines(s["id"], un, registry(cfg), cfg)
    out["not_checked"] = list(s.get("not_checked") or []) + out["not_checked"]
    out["limits"] = list(s.get("limits") or []) + out["limits"]
    out["further"] = list(s.get("further") or []) + out["further"]
    out["agreement"] = agreement(brief, cfg, s)
    return out


def agreement(brief, cfg: dict, s: dict) -> list[str]:
    """HB-163 ADDENDUM-05 item 2 (ADDENDA 02 and 03): "Agreement between methods". A
    section of the dense release's cloud, or SLAB's own, lists the other valid
    dense-gas method with its numbers: the held comparison (HB-167's evidence files,
    read, not retyped; ADDENDUM-06 item 7) where one is held for this brief's release,
    and SLAB's and SCICHEM's farthest reach per level from this brief's own runs. The
    puff never appears there: it is not a valid method for a dense release. Every
    other section, a passive release's included, reads "one method"."""
    t = cfg["tevv"]
    a = t["agreement"]
    derived = (getattr(brief, "derived", None) or {}) if brief is not None else {}
    cl = derived.get("cloud") or {}
    # HB-184: a Conditions of use section names the two engines' sections and the
    # measure's, rather than repeat the comparison the dense layers' sections list
    if s["id"] in ("conditions_scichem", "conditions_slab"):
        return [
            t["conditions"]["agreement"].format(
                scichem=ref(cfg, "conditions_scichem"),
                slab=ref(cfg, "conditions_slab"),
                measure=ref(cfg, "agreement"),
            )
        ]
    if s["id"] not in a["sections"] or cl.get("state") != "drawn":
        return [t["one_method"]]
    out = []
    case = a["cases"].get(getattr(brief, "scenario_id", None))
    if case:
        out += held_agreement(case, cfg)
    # HB-173 (DN-028 ADDENDUM-04): this brief's own measure and both reaches per level,
    # each lower bound written as one, from the agreement record the checklist reads
    ag = derived.get("agreement")
    if ag:
        from hazbrief.brief import agreement as AG

        out.append(
            a["measure_line"].format(
                line=AG.line(ag, AG.load_config()), ref=ref(cfg, "agreement")
            )
        )
    return out or [a["none"]]


def _agreement_fields(brief, cfg: dict) -> dict[str, list[str]]:
    """HB-173 (DN-028 ADDENDUM-04 decision 7): the measure's section, which the
    checklist item opens (its pop-out): the line, the measure with its source and every
    pair, each level's two reaches and areas, the inputs not shared, the release's kind
    by Volume II with what is known of each engine, the reason or "not traced", and the
    existing Verify items the shared inputs rest on; the three records it reads."""
    from hazbrief.brief import agreement as AG

    s = registry(cfg)["agreement"]
    derived = brief.derived or {}
    ag = derived.get("agreement") or {}
    cl = derived.get("cloud") or {}
    out = _empty(cfg)
    integ = cfg["checklist"]["integrity"]
    wind_item = next(i["text"] for i in integ if i["section"] == "map")
    cue = cfg["map"]["cue_block"]
    # the class both engines read, from the agreement record (SLAB's STAB), not a
    # read of the derived stability entry (DN-018 section 10 item 3 names its readers)
    acfg = AG.load_config()
    stab_cls = AG.class_letter(ag["stab"], acfg) if ag.get("stab") else ""
    stab_item = (
        cue["line"]
        .format(
            signal=cue["lines"]["night_stable"]["signal"].format(cls=stab_cls),
            text="",
        )
        .rstrip(": ")
    )
    out["inputs"] += AG.popout_lines(
        ag, AG.load_config(), stab_item, wind_item, ref(cfg, "conditions_scichem")
    )
    rec = cfg["tevv"]["agreement"]["records"]
    if ag.get("lines_record"):
        out["run_record"].append(rec["lines"].format(sha=ag["lines_record"]))
    if ag.get("slab_record"):
        out["run_record"].append(rec["slab"].format(sha=ag["slab_record"]))
    if cl.get("record"):
        out["run_record"].append(rec["cloud"].format(sha=cl["record"]))
    return _with_registry(cfg, s, out, brief)


def _conditions_fields(brief, cfg: dict, sid: str) -> dict[str, list[str]]:
    """HB-184 (DN-028 ADDENDUM-10 decision 5): an engine's Conditions of use, whose rows
    `sections` attaches from the one table (`conditions.rows`); the fields hold the
    registry's words and, for this brief, the class and the engine that carries its
    levels."""
    s = registry(cfg)[sid]
    ag = (brief.derived or {}).get("agreement") or {}
    out = _empty(cfg)
    if ag.get("stab"):
        from hazbrief.brief import agreement as AG

        acfg = AG.load_config()
        out["inputs"].append(
            cfg["tevv"]["conditions"]["this_brief"].format(
                cls=AG.class_letter(int(ag["stab"]), acfg),
                engine=cfg["tevv"]["conditions"]["engines"][ag.get("levels")],
            )
        )
    return _with_registry(cfg, s, out, brief)


def conditions_html(cfg: dict, rows: list[dict]) -> str:
    """An engine's Conditions of use as a table: the condition, what the evidence shows,
    the evidence file with the line that holds the figure, and the held source key."""
    c = cfg["tevv"]["conditions"]
    head = "".join(f"<th>{esc(h)}</th>" for h in c["columns"])
    body = "".join(
        f'<tr data-key="{esc(r["key"])}"><td>{esc(r["condition"])}</td>'
        f"<td>{esc(r['shows'])}</td>"
        f"<td><code>{esc(r['file'])}</code> {esc(c['line'].format(n=r['line']))}</td>"
        f"<td><code>{esc(r['key'])}</code></td></tr>"
        for r in rows
    )
    return (
        f'<table class="conditions"><caption>{esc(c["caption"])}</caption>'
        f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
    )


def held_agreement(case: str, cfg: dict) -> list[str]:
    """The held comparison for one case, read from HB-167's evidence files
    (`tevv.agreement.files`): per level the 60-minute reach of each engine and their
    ratio; by the case's rule, the paired centreline statistics (day) or the measured
    cause of the disagreement and the untraced remainder (night)."""
    import csv
    import json
    from pathlib import Path

    a = cfg["tevv"]["agreement"]
    root = Path(__file__).resolve().parents[3]
    rows = list(
        csv.DictReader(
            (root / a["files"]["table"]).read_text(encoding="utf-8").splitlines(),
            delimiter="\t",
        )
    )
    stats = json.loads((root / a["files"]["stats"]).read_text(encoding="utf-8"))
    rule = a["cases_rule"][case]
    out = []
    causes = []
    for r in rows:
        if r["case"] != case:
            continue
        if r["tier"].startswith("cloud at"):
            # the cloud's width, depth and speed at a distance: the measured cause
            causes.append(
                a["cause_line"].format(
                    at=r["tier"],
                    slab=f"{r['slab_reach_m']}, {r['slab_beyond_table']}",
                    scichem=f"{r['scichem_avg60_reach_m']}, "
                    f"{r['scichem_avg60_beyond_lines']}",
                    ratio=r["reach_ratio_scichem_over_slab"],
                    speed=r["scichem_instant_any_time_reach_m"],
                    centre=r["scichem_instant_any_time_area_km2"],
                )
            )
            continue
        out.append(
            a["held_reach_line"].format(
                case=case,
                tier=r["tier"],
                scichem=float(r["scichem_avg60_reach_m"]),
                slab=float(r["slab_reach_m"]),
                beyond=a["beyond"] if r["slab_beyond_table"] == "yes" else "",
                ratio=r["reach_ratio_scichem_over_slab"],
                file=a["files"]["table"],
            )
        )
    out.append(a["stats_line"].format(file=a["files"]["stats"], **stats[case]["stats"]))
    if rule == "disagree":
        out += causes
        out.append(a["untraced_line"])
    sl = a.get("stable_layer") or {}
    if case in (sl.get("cases") or {}):
        out.append(_stable_layer_line(sl, sl["cases"][case], root))
    return out


def _stable_layer_line(sl: dict, case: str, root) -> str:
    """HB-172: the held comparison's boundary layer, and the same release on the stable
    class's PGT layer, read from HB-169's fix run (`tevv.agreement.stable_layer`)."""
    import csv

    def tsv(key: str) -> list[dict]:
        text = (root / sl["files"][key]).read_text(encoding="utf-8")
        return list(csv.DictReader(text.splitlines(), delimiter="\t"))

    reach = next(
        r
        for r in tsv("reach")
        if r["case"] == case and r["tier"].split(" ")[0] == sl["tier"]
    )
    trace = next(r for r in tsv("trace") if r["variant"] == sl["trace_variant"])
    ds = list(sl["distances_m"])
    return sl["line"].format(
        tier=sl["tier"],
        after=float(reach["scichem_after_60min_reach_m"]),
        before=float(reach["scichem_before_60min_reach_m"]),
        slab=float(reach["slab_reach_m"]),
        ratios=", ".join(trace[f"slab_over_scichem_{d}m"] for d in ds[:-1])
        + f" and {trace[f'slab_over_scichem_{ds[-1]}m']}",
        distances=", ".join(_metres(d) for d in ds[:-1]) + f" and {_metres(ds[-1])}",
        files=f"{sl['files']['reach']}; {sl['files']['trace']}",
    )


def _metres(d: int) -> str:
    return f"{d // 1000} km" if d >= 1000 and d % 1000 == 0 else f"{d} m"


def _source_term_fields(brief, cfg: dict) -> dict[str, list[str]]:
    s = registry(cfg)["source_term"]
    st = source_term_of(brief) or {}
    p = (brief.derived or {}).get("puff") or {}
    out = _empty(cfg)
    model = st.get("model")
    if model in (s.get("method_by_model") or {}):
        out["method"].append(s["method_by_model"][model])
    elif st.get("method"):
        out["method"].append(st["method"])
    env = next(
        (e for e in p.get("envelopes") or [] if e.get("name") == "source_term"), None
    )
    if env and env.get("assumption"):
        out["inputs"].append(env["assumption"])
    out["inputs"] += list(s.get("assumptions_from") or [])
    for what in st.get("omitted") or []:
        out["limits"].append(f"not modelled: {what}")
    return _with_registry(cfg, s, out, brief)


def _stability_fields(brief, cfg: dict) -> dict[str, list[str]]:
    s = registry(cfg)["stability_class"]
    st = (brief.derived or {}).get("stability") or {}
    out = _empty(cfg)
    out["inputs"].append(f"class {st.get('class')} ({st.get('period')})")
    for r in st.get("inputs") or []:
        line = f"{r['name']}: {r['value']} {r.get('unit', '')} ({r.get('source')})"
        out["inputs"].append(" ".join(line.split()))
    c = st.get("ceiling")
    if c:
        out["inputs"].append(f"{c['name']}: {c.get('value')} ({c.get('source')})")
    return _with_registry(cfg, s, out, brief)


def _time_steps_fields(brief, cfg: dict) -> dict[str, list[str]]:
    s = registry(cfg)["time_steps"]
    tl = ((brief.derived or {}).get("puff") or {}).get("timeline") or {}
    out = _empty(cfg)
    out["inputs"].append(
        "steps: " + ", ".join(f"{x['hplus']} ({x['clock']})" for x in tl["steps"])
    )
    for k in ("level_line", "end_line", "one_wind"):
        if tl.get(k):
            out["inputs"].append(tl[k])
    return _with_registry(cfg, s, out, brief)


def _plain_fields(brief, cfg: dict, sid: str) -> dict[str, list[str]]:
    """A drawn thing with no layer in `layers.build` (the roads image, the weather
    layers the page draws from the derivations): its registry words and its label."""
    s = registry(cfg)[sid]
    out = _empty(cfg)
    derived = brief.derived or {}
    src = {
        "roads": derived.get("roads"),
        "radar": derived.get("radar"),
        "satellite": derived.get("satellite"),
        "wind_field": derived.get("wind_field"),
        "radar_snapshot": (derived.get("snapshots") or {}).get("radar"),
        "satellite_snapshot": (derived.get("snapshots") or {}).get("satellite"),
    }.get(sid) or {}
    if sid == "roads":
        from hazbrief.brief import render

        src = render._roads(brief, cfg["page"]) or {}
    if src.get("label"):
        out["inputs"].append(src["label"])
    if src.get("sha"):
        out["run_record"].append(f"record {src['sha']}")
    return _with_registry(cfg, s, out, brief)


def _engine_rule_fields(brief, cfg: dict) -> dict[str, list[str]]:
    """HB-163 (DN-026 section 3): the selection rule, its value for this release and
    every number it rests on."""
    s = registry(cfg)["engine_rule"]
    r = (brief.derived or {}).get("engine_rule") or {}
    w = cfg["tevv"]["rule_words"]
    out = _empty(cfg)
    out["inputs"].append(r.get("line") or "")
    out["inputs"].append(r.get("basis") or "")
    if r.get("ri_c") is not None:
        out["inputs"].append(
            w["numbers"].format(
                rho=r["rho_kg_m3"],
                rho_a=r["rho_air_kg_m3"],
                h=r["h_m"],
                u=r["u_star_ms"],
                q=r["rate_kg_s"],
                u10=r["wind_10m_ms"],
                z0=r["z0_m"],
                cls=r["stability_class"],
                kind=r["kind"],
            )
        )
    for m in r.get("missing") or []:
        out["inputs"].append(w["missing"].format(what=m))
    return _with_registry(cfg, s, out, brief)


def _cloud_at_time_fields(brief, cfg: dict) -> dict[str, list[str]]:
    """HB-163 item 5: the cloud at each output step, what Animate plays: its steps, the
    release's end, and the last step at which each level covers the source."""
    from hazbrief.brief import derive as D

    s = registry(cfg)[section_of(cfg, "cloud_at_time")]
    cl = (brief.derived or {}).get("cloud") or {}
    w = cfg["tevv"]["cloud_words"]
    out = _empty(cfg)
    steps = cl.get("steps") or []
    out["inputs"].append(
        w["steps"].format(
            n=len(steps),
            first=D.hplus(steps[0]["minute"]),
            last=D.hplus(steps[-1]["minute"]),
        )
    )
    out["inputs"].append(w["release"].format(m=cl["release_minutes"]))
    for t in cl.get("tiers") or []:
        over = [x["minute"] for x in steps if x["contains_source"].get(t["name"])]
        out["inputs"].append(
            w["source"].format(tier=t["name"], hplus=D.hplus(over[-1]))
            if over
            else w["source_never"].format(tier=t["name"])
        )
    if cl.get("cloud_left_domain"):
        out["inputs"].append(
            w["left"].format(hplus=D.hplus(round(cl["engine_end_s"] / 60)))
        )
    # HB-192 (DN-024 ADDENDUM-01): what the time control and Play show, the frames
    fr = cl.get("frames_run")
    if fr:
        acc = (frames_accuracy(fr["record"]) or {}).get("all") or {}
        out["inputs"].append(
            w["frames"].format(
                n=fr["count"],
                every=fr["every_min"],
                spacing=f"{float(fr['spacing_m']):g}",
                tol=f"{float(fr['tolerance_m']):g}",
                within=f"{float(fr.get('drawn_within_m') or 0):g}",
            )
        )
        out["checked"].append(
            w["frames_accuracy"].format(
                n=acc.get("n", 0), median=acc.get("median"), worst=acc.get("worst")
            )
        )
        out["run_record"].append(f"frames record {fr['record']}")
    out["run_record"].append(f"record {cl['record']}")
    return _with_registry(cfg, s, out, brief)


def frames_accuracy(sha: str) -> dict | None:
    """HB-192: the frames record's stated lookup accuracy (`frames.accuracy`)."""
    from hazbrief.brief import frames as F

    return (F.read_record(sha) or {}).get("accuracy")


#: HB-192 (Part C item 8): the benchmark requirement's projection of the graph, which
#: the brief reads (no Neo4j at runtime, DN-001 section 4)
BENCHMARK_ROWS = Path(__file__).resolve().parents[3] / (
    "docs/evidence/hb192/benchmark_rows.md"
)


def benchmark_rows(path: Path = BENCHMARK_ROWS) -> list[dict]:
    """The projection's rows: id, statement, status and note, in its order."""
    out = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        if not ln.startswith("| BENCH-"):
            continue
        cells = [x.strip() for x in ln.strip().strip("|").split(" | ")]
        out.append(
            {
                "id": cells[0],
                "statement": cells[2],
                "status": cells[3],
                "note": cells[4],
            }
        )
    return out


def benchmark_reason(row: dict) -> str:
    """HB-205 (Issue f35aa70b): the reason a scored row's note gives for its status,
    the note's sentence after "Status: {status}." (a sentence ends at a full stop
    followed by a capital or the end of the note). A scored status whose note states
    no reason fails loud: the line would otherwise print the word alone."""
    m = re.search(
        rf"Status: {re.escape(row['status'])}\.\s+(.+?\.)(?=\s+[A-Z]|\s*$)",
        row["note"],
    )
    if not m:
        raise ValueError(
            f"{row['id']}: status {row['status']!r} but its note states no reason "
            "after 'Status: {status}.' (docs/evidence/hb192/benchmark_rows.md)"
        )
    return m.group(1)


def _benchmark_fields(brief, cfg: dict) -> dict[str, list[str]]:
    """HB-192 (Part C item 8): Benchmarks and requirement: the accepted tools named here
    and only here, what each publishes about its own performance, limits and settings,
    the requirement's minimum and objective, and hazbrief's status against each, from
    the graph's projection (BENCH-0 to BENCH-9)."""
    s = registry(cfg)["benchmarks"]
    w = cfg["tevv"]["benchmark_words"]
    out = _empty(cfg)
    rows = benchmark_rows()
    for r in rows:
        if r["id"] == "BENCH-0":
            out["method"].append(r["statement"])
            out["method"].append(r["note"])
            continue
        if r["status"] in w["scored"]:
            line = w["row_reason"].format(
                id=r["id"],
                statement=r["statement"],
                status=r["status"],
                reason=benchmark_reason(r),
            )
        else:
            line = w["row"].format(
                id=r["id"], statement=r["statement"], status=r["status"]
            )
        out["checked"].append(line)
        out["further"].append(w["note"].format(id=r["id"], note=r["note"]))
    out["run_record"].append(w["projection"])
    return _with_registry(cfg, s, out, brief)


def _cloud_lines_fields(brief, cfg: dict, sid: str) -> dict[str, list[str]]:
    """HB-163 items 6 (and ADDENDUM-04 item 1): the arrival, minutes above and clear
    lines, read from the held record's points at breathing height."""
    s = registry(cfg)[sid]
    cl = (brief.derived or {}).get("cloud") or {}
    out = _empty(cfg)
    roadblocks = sid in ("roadblock_lines", "puff_roadblock_lines")
    kinds = ("roadblock",) if roadblocks else ("named_place", "sited")
    n = sum(1 for p in cl.get("places") or [] if p["kind"] in kinds)
    # DN-025 section 3 item 5: the puff's points are its own field at the ground
    words = "points_puff" if cl.get("engine_key") == "puff" else "points"
    out["inputs"].append(cfg["tevv"]["cloud_words"][words].format(n=n))
    out["run_record"].append(f"record {cl['record']}")
    return _with_registry(cfg, s, out, brief)


def _threat_fields(brief, cfg: dict) -> dict[str, list[str]]:
    """HB-171 (DN-029; ADDENDUM-01 item 2): the timeline's inputs, and every occupancy
    line of `threat.yaml` that is marked assumed, listed as an assumption with its
    ground; a sourced line names its documents."""
    from hazbrief.brief import threat

    s = registry(cfg)["threat_timeline"]
    tc = threat.config()
    cl = (brief.derived or {}).get("cloud") or {}
    out = _empty(cfg)
    out["inputs"].append(f"the modelled cloud's record {cl.get('record')}")
    mp = (brief.derived or {}).get("modelled_population") or {}
    out["inputs"].append(
        f"blocks under the cloud: {len(mp.get('rows') or [])}"
        + (f" (not read: {mp['reason']})" if mp.get("reason") else "")
    )
    for kind, lines in tc["occupancy"].items():
        for ln in lines:
            when = f"{kind}, {'/'.join(ln['days'])} {ln['from']} to {ln['to']}"
            why = ln.get("assumed") or ln.get("assumed_bounds")
            if ln.get("assumed"):
                out["inputs"].append(f'assumption: {when}, "{ln["phrase"]}": {why}')
            else:
                docs = ", ".join(
                    f"{x['doc']} p. {x['page']}" if x.get("page") else x["doc"]
                    for x in ln.get("sources") or []
                )
                extra = f"; assumption: {why}" if why else ""
                out["inputs"].append(f'{when}, "{ln["phrase"]}": {docs}{extra}')
    return _with_registry(cfg, s, out, brief)


def sections(brief, cfg: dict, data: dict | None = None) -> list[dict]:
    """The brief's sections in number order, each {id, ref, anchor, fields}; a string a
    section repeats from an earlier one reads "as in T<n>" (ADDENDUM-01 item 3: cut to
    one where it says the same thing twice)."""

    cfg = brief_cfg(cfg, brief)
    data = data if data is not None else _tevv_data(brief, cfg)
    by_id: dict[str, list[dict]] = {}
    for lay in data["layers"]:
        if lay["features"]:
            by_id.setdefault(section_of(cfg, lay["id"]), []).append(lay)
    special = {
        "source_term": _source_term_fields,
        "stability_class": _stability_fields,
        "time_steps": _time_steps_fields,
        "engine_rule": _engine_rule_fields,
        "cloud_at_time": _cloud_at_time_fields,
        "arrival_lines": _cloud_lines_fields,
        "roadblock_lines": _cloud_lines_fields,
        # HB-162R (DN-025): the puff's cloud by level, on a passive release
        "puff_cloud_at_time": _cloud_at_time_fields,
        "puff_arrival_lines": _cloud_lines_fields,
        "puff_roadblock_lines": _cloud_lines_fields,
        # HB-171 (DN-029)
        "threat_timeline": _threat_fields,
        # HB-173 (DN-028 ADDENDUM-04)
        "agreement": _agreement_fields,
        # HB-184 (DN-028 ADDENDUM-10 decision 5)
        "conditions_scichem": _conditions_fields,
        "conditions_slab": _conditions_fields,
        # HB-192 (Part C item 8)
        "benchmarks": _benchmark_fields,
    }
    t = cfg["tevv"]
    seen: dict[str, str] = {}
    out = []
    for sid in present(brief, cfg, data):
        if sid in special:
            fn = special[sid]
            fields = (
                fn(brief, cfg, sid)
                if fn in (_cloud_lines_fields, _conditions_fields)
                else fn(brief, cfg)
            )
        elif sid in by_id:
            fields = _layer_fields(brief, cfg, by_id[sid])
        else:
            fields = _plain_fields(brief, cfg, sid)
        r = ref(cfg, sid)
        for key, items in fields.items():
            kept: list[str] = []
            for item in items:
                if key in ("what", "agreement"):
                    kept.append(item)
                    continue
                first = seen.get(item)
                if first is None:
                    seen[item] = r
                    kept.append(item)
                elif first != r:
                    line = t["as_in"].format(ref=first)
                    if line not in kept:
                        kept.append(line)
            fields[key] = kept
        sec = {"id": sid, "ref": r, "anchor": anchor(cfg, sid), "fields": fields}
        if sid in ("conditions_scichem", "conditions_slab"):
            from hazbrief.brief import conditions

            sec["conditions"] = conditions.rows(sid.split("_", 1)[1])
        if sid == "benchmarks":
            # HB-214: the one benchmark table, its definitions first and its notes after
            sec["benchmark_table"] = BT.load()
        out.append(sec)
    return out


# ── the page ────────────────────────────────────────────────────────────────────────

_AS_IN = re.compile(r"^as in (T\d+)$")

#: HB-184: the Conditions of use tables' style
CONDITIONS_CSS = (
    " table.conditions { border-collapse: collapse; width: 100%; margin: 6px 0;"
    " font-size: 13px; table-layout: fixed; }"
    " table.conditions caption { text-align: left; font-weight: 700; }"
    " table.conditions th, table.conditions td { text-align: left;"
    " vertical-align: top; border-top: 1px solid #e0e0e0; padding: 3px 8px 3px 0; }"
    " table.conditions th:nth-child(1) { width: 24%; }"
    " table.conditions th:nth-child(2) { width: 44%; }"
    " table.conditions th:nth-child(3) { width: 20%; }"
    " table.conditions th:nth-child(4) { width: 12%; }"
    " table.conditions code { font-size: 11px; overflow-wrap: anywhere; }"
)


def _item_html(cfg: dict, item: str) -> str:
    m = _AS_IN.match(item)
    if m:
        n = m.group(1)[len(cfg["tevv"]["prefix"]) :]
        return f'<li>as in <a href="#t{esc(n)}">{esc(m.group(1))}</a></li>'
    return f"<li>{esc(item)}</li>"


def page_html(brief, cfg: dict, data: dict | None = None) -> str:
    """`tevv.html`: the EXERCISE banner at top and bottom, a lede, then each section
    with its number, anchor and fixed fields; an empty field says `none_stated`, and
    the two checked fields carry `pending_state` until HB-159 sets them."""
    from hazbrief.brief.render import _material_name

    t = cfg["tevv"]
    page = cfg["page"]
    fp = (brief.channels.get("protective_action_footprint") or {}).get("payload") or {}
    name = _material_name(fp.get("material") or {}) or brief.scenario_id
    title = t["title"].format(name=f"{name} ({brief.scenario_id})")
    secs = sections(brief, cfg, data)
    body = []
    for s in secs:
        reg = registry(cfg)[s["id"]]
        rows = []
        for f in t["fields"]:
            items = s["fields"].get(f["key"]) or []
            if f["key"] in ("checked", "not_checked"):
                items = items + [t["pending_state"]]
            if not items:
                items = [t["none_stated"]]
            rows.append(
                f'<tr data-field="{esc(f["key"])}"><th>{esc(f["name"])}</th><td><ul>'
                + "".join(_item_html(cfg, i) for i in items)
                + "</ul></td></tr>"
            )
        extra = conditions_html(cfg, s["conditions"]) if s.get("conditions") else ""
        if s.get("benchmark_table"):
            extra += BT.html(s["benchmark_table"])
        body.append(
            f'<section class="tevv" id="{esc(s["anchor"])}" data-id="{esc(s["id"])}">'
            f'<h2><span class="ref">{esc(s["ref"])}</span> '
            f"{esc(reg['what'].rstrip('.'))}</h2>"
            f'<table class="fields">{"".join(rows)}</table>{extra}</section>'
        )
    toc = "".join(
        f'<li><a href="#{esc(s["anchor"])}">{esc(s["ref"])}</a> '
        f"{esc(registry(cfg)[s['id']]['what'].rstrip('.'))}</li>"
        for s in secs
    )
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{esc(title)}</title><style>"
        f"body {{ font-family: {page['font_stack']}; margin: 0; color: #1a1a1a; }}"
        " main { margin: 16px 32px; max-width: 1100px; }"
        " .banner { background: #b00020; color: #fff; text-align: center;"
        " font-weight: 700; padding: 6px; letter-spacing: 0.08em; }"
        " section.tevv { border-top: 1px solid #cccccc; padding-top: 6px; }"
        " section.tevv:target { background: #fff8e1; }"
        " .ref { font-variant-numeric: tabular-nums; color: #595959; }"
        " table.fields { border-collapse: collapse; width: 100%; }"
        " table.fields th { text-align: left; vertical-align: top; width: 16em;"
        " padding: 3px 10px 3px 0; font-size: 13px; }"
        " table.fields td { font-size: 13px; padding: 3px 0; }"
        " table.fields ul { margin: 0; padding-left: 1.1em; }"
        # HB-184: the Conditions of use tables' style, only on a page that has them
        + (CONDITIONS_CSS if any(s.get("conditions") for s in secs) else "")
        # HB-214: the benchmark table's style, only on a page that has it
        + (BT.CSS if any(s.get("benchmark_table") for s in secs) else "")
        + "</style></head><body>"
        f'<header id="top" class="banner">{esc(page["banner"])}</header><main>'
        f"<h1>{esc(title)}</h1><p>{esc(t['lede'])}</p>"
        f'<ul class="toc">{toc}</ul>{"".join(body)}</main>'
        f'<footer id="bottom" class="banner">{esc(page["banner"])}</footer>'
        "</body></html>\n"
    )
