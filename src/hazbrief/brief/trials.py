"""What each dense-gas engine was checked or compared against, by material (HB-178 Part
A item 4; Issue d16f6882; DN-028 ADDENDUM-06).

One table (`trials.yaml`) of trial, material and source key. For a brief's SLAB section
(T7) and SCICHEM section (T45) it gives two "checked against" lines: the pooled
comparison with the measured stable field trials, its numbers read from the held
evidence files (HB-176's summary and arcs, HB-177's like-for-like scoring), and a line
naming the held trials and checks that are of the brief's own material, or saying that
none is and listing what is held for other materials as such. Nothing is written per
brief, and no engine is called validated: each line is a comparison or a check.
"""

from __future__ import annotations

import csv
from functools import cache
from pathlib import Path

import yaml

CONFIG_FILE = Path(__file__).with_name("trials.yaml")
REPO = Path(__file__).resolve().parents[3]


@cache
def load_config() -> dict:
    cfg = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8"))
    for key in ("files", "sections", "words", "trials"):
        if key not in cfg:
            raise RuntimeError(f"{CONFIG_FILE} is missing {key!r}")
    for t in cfg["trials"]:
        unknown = set(t["engines"]) - set(cfg["sections"])
        if unknown:
            raise RuntimeError(f"{CONFIG_FILE}: trial {t['id']}: engines {unknown}")
    return cfg


def _tsv_tables(path: Path) -> list[list[dict]]:
    """The tables of a TSV file whose tables are separated by blank lines."""
    out, block = [], []
    for line in path.read_text(encoding="utf-8").splitlines() + [""]:
        if line.strip():
            block.append(line)
        elif block:
            out.append(list(csv.DictReader(block, delimiter="\t")))
            block = []
    return out


@cache
def figures() -> dict:
    """Every figure the lines state, from the held evidence files (`files`)."""
    f = load_config()["files"]
    summary = {r["figure"]: r["value"] for r in _tsv_tables(REPO / f["summary"])[0]}
    arcs_t = _tsv_tables(REPO / f["arcs"])
    arcs = {(r["trial"], int(r["x_m"])): r for r in arcs_t[0]}
    conf = {r["configuration"]: r for r in arcs_t[1]}
    mean = next(r for k, r in conf.items() if "its ensemble mean" in k)
    peak = next(r for k, r in conf.items() if "like for like" in k)
    n = int(mean["n"])
    bench: dict[tuple[str, str, str], list[float]] = {}
    for r in _tsv_tables(REPO / f["benchmark"])[0]:
        key = (r["case"], r["engine"], r["hazbrief_variant"])
        bench.setdefault(key, []).append(float(r["hazbrief_over_published"]))
    return {
        "summary": {
            **summary,
            "mean_vg": f"{float(mean['vg']):.2f}",
            "mean_fac2": round(float(mean["fac2"]) * n),
            "peak_mg": f"{float(peak['mg']):.2f}",
            "peak_vg": f"{float(peak['vg']):.2f}",
            "peak_below": int(peak["below_observed"]),
        },
        "arcs": arcs,
        "benchmark": bench,
    }


def _engine_of(section_id: str) -> str | None:
    for engine, sid in load_config()["sections"].items():
        if sid == section_id:
            return engine
    return None


def _quote(t: dict, tevv_sections: dict, brief_cfg: dict) -> str:
    q = t["quote_from"]
    if q.get("section"):
        lines = tevv_sections[q["section"]].get(q["field"]) or []
        return next(x for x in lines if x.startswith(q["starts"]))
    if q.get("file") == "agreement":
        from hazbrief.brief import agreement as AG

        node = AG.load_config()
    else:
        node = brief_cfg
    for k in q.get("key") or q.get("config"):
        node = node[k]
    return node


def _row(t: dict, engine: str, tevv_sections: dict, brief_cfg: dict) -> str:
    w = load_config()["words"]
    name = {"slab": "SLAB", "scichem": "SCICHEM"}[engine]
    if t["kind"] == "field_trial" and t.get("arcs"):
        figs = figures()["arcs"]
        notes = {int(k): v for k, v in (t.get("note") or {}).items()}
        parts = []
        for x in t["arcs"]:
            r = figs[(t["id"], int(x))]
            ratio = (
                w["ratio_slab"].format(slab=float(r["slab_over_obs_hb176"]))
                if engine == "slab"
                else w["ratio_scichem"].format(
                    mean=float(r["scichem_mean_over_obs_hb176"]),
                    peak=float(r["scichem_like_for_like_over_obs"]),
                )
            )
            stat = w[
                "arc_in_statistic"
                if r["in_statistic"] == "yes"
                else "arc_outside_statistic"
            ]
            text = w["arc"].format(x=int(x), statistic=stat, engine=name, ratio=ratio)
            note = notes.get(int(x))
            parts.append(f"{text}, {note}" if note else text)
        head = w["arc_head"].format(title=t["title"], source=t["source"])
        return head + w["join"].join(parts)
    if t.get("benchmark"):
        b = t["benchmark"]
        vals = figures()["benchmark"][(b["case"], name, b[engine])]
        return w["benchmark"].format(
            title=t["title"],
            what=t["what"],
            engine=name,
            lo=min(vals),
            hi=max(vals),
            variant=b[engine],
            ref=f"{t['source']} {b['ref']}",
        )
    if t.get("quote_from"):
        # the configured sentence carries its own trial names and references
        return _quote(t, tevv_sections, brief_cfg).rstrip(".")
    what = f", {t['what']}" if t.get("what") else ""
    return f"{t['title']} ({t['source']}){what}"


def pooled_line(engine: str) -> str:
    """The pooled comparison with the measured stable field trials, for one engine."""
    cfg = load_config()
    w = cfg["words"]
    pooled = [
        w["pooled_trial"].format(title=t["title"], material=t["material"]["name"])
        for t in cfg["trials"]
        if t.get("pooled") and engine in t["engines"]
    ]
    return w["pooled"][engine].format(
        trials="Volume II: " + "; ".join(pooled), **figures()["summary"]
    )


def material_line(
    engine: str, un: str | None, tevv_sections: dict, brief_cfg: dict
) -> str:
    """The held trials and checks of the brief's own material (UN number `un`), or
    the line saying none is, with what is held for other materials named as such."""
    cfg = load_config()
    w = cfg["words"]
    rows = [t for t in cfg["trials"] if engine in t["engines"]]
    un = str(un or "")
    mine = [t for t in rows if un and un in t["material"]["un"]]
    if mine:
        return w["matching"].format(
            material=mine[0]["material"]["name"],
            un=un,
            rows=w["join"].join(
                dict.fromkeys(_row(t, engine, tevv_sections, brief_cfg) for t in mine)
            ),
        )
    others = list(
        dict.fromkeys(
            w["other"].format(title=t["title"], material=t["material"]["name"])
            for t in rows
        )
    )
    return w["none"].format(un=un or "not stated", others="; ".join(others))


def lines(section_id: str, un: str | None, tevv_sections: dict, brief_cfg: dict):
    """The "checked against" lines this table adds to section `section_id` (T7 or
    T45) for a brief whose material is `un`; [] for any other section."""
    engine = _engine_of(section_id)
    if engine is None:
        return []
    return [
        pooled_line(engine),
        material_line(engine, un, tevv_sections, brief_cfg),
    ]
