#!/usr/bin/env python3
"""HB-12: mine candidate flag rules from every orange guide, and admit them by receipt.

    $SQUIDDY_PY scripts/mine_flag_rules.py mine     # one model call per guide
    uv run python scripts/mine_flag_rules.py admit  # the substring test: admitted.jsonl
                                                    # and packs/build/REJECTED_RULES.md

**The invariant** (DN-001 section 4 invariant 2): every flag is a rule in a pack with a
source. The model proposes candidates; it never writes a rule. A candidate is admitted
only when its `trigger_text` is a verbatim substring, after whitespace normalisation, of
the Key A text of the page it cites (HB-03b's `packs/build/keyA/guides.jsonl`, the ERG
2024 PDF's text layer), and that page is a page of the guide the candidate names
(`admit`). No fuzzy match and no paraphrase is admitted. What makes an admitted rule
fire is its kind's predicate over tool values (`packs/src/flag_kinds.yaml`), never the
text.

**The model call** (`mine`, under Squiddy's python, as HB-03b's Key B): Squiddy's
`ClaudeCLIClient` for the seldon registry role `keys.role`, tools disabled, each call
reserved on a declared job of the spend ledger. The `claude` CLI has no temperature flag
(Squiddy's client says so), so the task's "temperature 0" cannot be set; the admission
test, not the sampling, is what makes the output deterministic.

**Checkpoint/restart** (standards section 15): the unit is one guide; its key is (guide,
sha256 of the prompt, model id); each settled call is appended to
`packs/build/flag_mining/calls.jsonl`, flushed and fsynced; re-running `mine` skips
every key already settled. The first run is the spend governor's pilot (at most 20
guides), which measures the per-call spend; the same command, re-run, continues under
that estimate. Progress is logged per call to `logs/2026-10-21_HB-12_mine.log`.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
KINDS = REPO / "packs" / "src" / "flag_kinds.yaml"
KEYA = REPO / "packs" / "build" / "keyA" / "guides.jsonl"
OUT = REPO / "packs" / "build" / "flag_mining"
LOG = REPO / "logs" / "2026-10-21_HB-12_mine.log"
REJECTED = REPO / "packs" / "build" / "REJECTED_RULES.md"
#: The admitted candidates: the input of record the flag rule pack is built from
#: (committed; packs/build/ is not, HB-03b).
ADMITTED = REPO / "packs" / "src" / "flag_rules_mined.jsonl"
#: The seldon registry role the mining pass runs as (sonnet, effort medium: a section
#: extraction, the registry's own description of `extractor`).
ROLE = "extractor"
TIMEOUT_SECONDS = 600
WORKERS = 4
RETRIES = 2
TOKEN_CAP = 3_000_000
GUESS_TOKENS_PER_CALL = 20_000


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def load_kinds() -> dict:
    return yaml.safe_load(KINDS.read_text(encoding="utf-8"))


def guide_pages() -> dict:
    """guide -> {"title", "pages": {page: [items]}} from Key A."""
    out: dict = {}
    for line in KEYA.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        g = out.setdefault(r["guide"], {"title": r["title"], "pages": {}})
        g["pages"].setdefault(r["page"], []).append(r)
    return out


def page_text(items: list) -> str:
    """The Key A text of one page, the string a trigger must be a substring of."""
    return norm(" ".join(i["text"] for i in items))


def prompt_for(guide: str, g: dict, kinds: dict) -> str:
    vocab = "\n".join(
        f"- {k}: {v['description']}"
        for k, v in kinds["kinds"].items()
        if v["origin"] in ("guide", "cross")
    )
    pages = []
    for p, items in sorted(g["pages"].items()):
        lines = [f"[page {p}]"]
        for i in items:
            lines.append(f"({i['section']} / {i['kind']}) {i['text']}")
        pages.append("\n".join(lines))
    return (
        f"Below is the text of ERG 2024 orange guide {guide} ({g['title']}), page by "
        "page, one printed item per line, each prefixed by its section and kind in "
        "parentheses (the prefix is not part of the text).\n\n"
        + "\n\n".join(pages)
        + "\n\nPropose flag rule candidates from this guide. A candidate is one "
        "statement of the guide that fits one of these kinds:\n"
        + vocab
        + "\n\nRules for every candidate:\n"
        "1. trigger_text is copied EXACTLY from the text above: the same words, "
        "spelling, capitals and punctuation, a contiguous span of one item (a whole "
        "item or a sentence of it). Never paraphrase, shorten inside, join two items, "
        "correct or reword. Do not include the parenthesized prefix.\n"
        "2. page is the page number the text is printed on, section its section.\n"
        "3. kind is one of the kinds above. For public_safety.evacuation, parameters "
        "is "
        '{"condition": "immediate" | "large_spill" | "spill" | "fire"}, from the '
        "sub-heading the item sits under; otherwise parameters is {}.\n"
        "4. Give every statement that fits a kind; a statement may fit two kinds.\n"
        'Return ONLY JSON, no prose, no code fence: {"candidates": [{"guide": '
        f'"{guide}", "section": "...", "kind": "...", "trigger_text": "...", "page": '
        '0, "parameters": {}}]}'
    )


def prompt_sha(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


def parse(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.index("\n") + 1 :] if "\n" in text else text
    obj = json.loads(text)
    if not isinstance(obj, dict) or not isinstance(obj.get("candidates"), list):
        raise ValueError("reply has no candidates list")
    return obj


# ------------------------------------------------------------------ admission
def admit_one(c: dict, pages: dict) -> tuple[bool, str]:
    """(admitted, reason). `pages`: guide -> {"pages": {page: items}}. The substring
    test only: the page must belong to the named guide, and the whitespace-normalised
    trigger must occur in that page's whitespace-normalised Key A text."""
    g = pages.get(str(c.get("guide")))
    if g is None:
        return False, f"guide {c.get('guide')!r} is not an orange guide"
    try:
        page = int(c.get("page"))
    except (TypeError, ValueError):
        return False, f"page {c.get('page')!r} is not a page number"
    if page not in g["pages"]:
        return False, f"page {page} is not a page of guide {c['guide']}"
    trig = norm(str(c.get("trigger_text") or ""))
    if not trig:
        return False, "empty trigger_text"
    if trig not in page_text(g["pages"][page]):
        return (
            False,
            "trigger_text is not a verbatim substring of the page's Key A text",
        )
    return True, "verbatim on the cited page"


def nearest(c: dict, pages: dict) -> str:
    """The Key A item on the cited page (or the guide) closest to a rejected trigger."""
    g = pages.get(str(c.get("guide")))
    if g is None:
        return "-"
    items = [i["text"] for p in g["pages"].values() for i in p]
    best = difflib.get_close_matches(str(c.get("trigger_text")), items, n=1, cutoff=0)
    return best[0] if best else "-"


def run_admit(kinds: dict) -> dict:
    pages = guide_pages()
    calls = [
        json.loads(x)
        for x in (OUT / "calls.jsonl").read_text(encoding="utf-8").splitlines()
        if x.strip()
    ]
    latest: dict = {}
    for r in calls:
        if r.get("ok"):
            latest[r["guide"]] = r
    allowed = {
        k for k, v in kinds["kinds"].items() if v["origin"] in ("guide", "cross")
    }
    admitted, rejected, seen = [], [], set()
    for g in sorted(latest):
        for c in latest[g]["reply"]["candidates"]:
            c = {**c, "guide": str(c.get("guide", g))}
            ok, why = admit_one(c, pages)
            if ok and c.get("kind") not in allowed:
                ok, why = False, f"kind {c.get('kind')!r} is not in the vocabulary"
            cond = (c.get("parameters") or {}).get("condition")
            if ok and c["kind"] == "public_safety.evacuation":
                if cond not in kinds["by_condition"]:
                    ok, why = False, f"evacuation condition {cond!r} is not one of "
                    why += f"{sorted(kinds['by_condition'])}"
            if not ok:
                rejected.append({**c, "reason": why, "nearest": nearest(c, pages)})
                continue
            key = (c["guide"], c["kind"], norm(c["trigger_text"]), cond)
            if key in seen:
                continue
            seen.add(key)
            text = page_text(pages[c["guide"]]["pages"][int(c["page"])])
            admitted.append(
                {
                    "guide": c["guide"],
                    "section": c.get("section"),
                    "kind": c["kind"],
                    "trigger_text": norm(c["trigger_text"]),
                    "page": int(c["page"]),
                    "parameters": c.get("parameters") or {},
                    "position": text.index(norm(c["trigger_text"])),
                    "model": latest[g]["model"],
                    "prompt_sha": latest[g]["prompt_sha"],
                }
            )
    admitted.sort(key=lambda a: (a["guide"], a["page"], a["position"], a["kind"]))
    _write_jsonl(ADMITTED, admitted)
    _write_rejected(rejected)
    per_guide: dict = {}
    for g in pages:
        cands = len((latest.get(g) or {}).get("reply", {}).get("candidates", []))
        per_guide[g] = {
            "candidates": cands,
            "admitted": sum(1 for a in admitted if a["guide"] == g),
            "rejected": sum(1 for r in rejected if r["guide"] == g),
            "mined": g in latest,
        }
    summary = {
        "calls_settled": len(latest),
        "calls_total_rows": len(calls),
        "candidates": sum(v["candidates"] for v in per_guide.values()),
        "admitted": len(admitted),
        "rejected": len(rejected),
        "per_guide": per_guide,
    }
    (OUT / "summary.json").write_text(
        json.dumps(summary, indent=1, sort_keys=True) + "\n"
    )
    return summary


def _write_jsonl(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows),
        encoding="utf-8",
    )


def _write_rejected(rows: list) -> None:
    lines = [
        "# HB-12 rejected flag rule candidates",
        "",
        "Every candidate the mining pass proposed that failed the admission test "
        "(`scripts/mine_flag_rules.py admit`): its `trigger_text` is not a verbatim "
        "substring (whitespace-normalised) of the Key A text of the page it cites, the "
        "page is not in the guide it names, or its kind is not in the vocabulary. None "
        "is in the pack. `nearest` is the Key A item closest to the candidate text.",
        "",
        f"**Rejected: {len(rows)}.**",
        "",
        "| guide | page | kind | reason | candidate | nearest Key A text |",
        "|---|--:|---|---|---|---|",
    ]
    for r in rows:

        def cell(x):
            return str(x).replace("|", "/").replace("\n", " ")

        lines.append(
            f"| {cell(r.get('guide'))} | {cell(r.get('page'))} | {cell(r.get('kind'))} "
            f"| {cell(r['reason'])} | {cell(r.get('trigger_text'))} "
            f"| {cell(r['nearest'])} |"
        )
    REJECTED.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ------------------------------------------------------------------ the model pass
class Checkpoint:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def done(self) -> set:
        if not self.path.exists():
            return set()
        return {
            json.loads(x)["key"]
            for x in self.path.read_text(encoding="utf-8").splitlines()
            if x.strip() and json.loads(x).get("ok")
        }

    def append(self, row: dict) -> None:
        with self._lock, self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())


def emit(text: str) -> None:
    print(text, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(text + "\n")


def run_mine(kinds: dict) -> int:
    from squiddy import spend
    from squiddy.model_client import ClaudeCLIClient, run_pool

    client = ClaudeCLIClient(role=ROLE, minimal_scaffold=True, timeout=TIMEOUT_SECONDS)
    pages = guide_pages()
    ck = Checkpoint(OUT / "calls.jsonl")
    done = ck.done()
    tasks = []
    for g in sorted(pages):
        prompt = prompt_for(g, pages[g], kinds)
        key = f"{g}|{prompt_sha(prompt)}|{client.model}"
        if key not in done:
            tasks.append({"guide": g, "prompt": prompt, "key": key})
    emit(
        f"[mine] {len(pages)} guides, {len(pages) - len(tasks)} already mined, "
        f"{len(tasks)} to mine; model {client.model} role {client.role} effort "
        f"{client.effort}"
    )
    if not tasks:
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    spec = {
        "job": f"hazbrief-hb12-mine-{stamp}",
        "lane": "hazbrief",
        "model": client.model,
        "profile": client.spend_profile(),
        "node": "hazbrief.mine_flag_rules",
        "units": len(tasks),
        "token_cap": TOKEN_CAP,
        "call_cap": len(tasks) * (RETRIES + 1),
        "approval_dir": str(OUT),
    }
    rec = spend.declare_or_pilot(spec, guess=GUESS_TOKENS_PER_CALL * len(tasks))
    if rec["units"] != len(tasks):
        emit(
            f"[mine] the spend governor cut the run to its pilot: {rec['units']} guides"
        )
        tasks = tasks[: rec["units"]]
    state = {"done": 0, "failed": 0}

    def call(task: dict, workers: int = 1) -> dict:
        inv = client.invoke(task["prompt"])
        return {"reply": parse(inv.content), "inv": inv}

    def on_result(task: dict, r: dict) -> None:
        res = r.get("result") or {}
        inv = res.get("inv")
        ok = r.get("error") is None
        ck.append(
            {
                "key": task["key"],
                "guide": task["guide"],
                "prompt_sha": prompt_sha(task["prompt"]),
                "model": client.model,
                "ok": ok,
                "error": r.get("error"),
                "attempts": r.get("attempts"),
                "reply": res.get("reply"),
                "usage": inv.usage if inv else None,
                "cost_usd": inv.cost_usd if inv else None,
                "seconds": inv.seconds if inv else None,
                "receipt": inv.receipt if inv else None,
                "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "job": rec["job"],
            }
        )
        state["done" if ok else "failed"] += 1
        n = len(res.get("reply", {}).get("candidates", [])) if ok else 0
        emit(
            f"[mine] guide {task['guide']}: {'ok' if ok else 'FAILED'} {n} candidates; "
            f"settled {state['done'] + state['failed']}/{len(tasks)}; cost_equiv_usd "
            f"{client.total_cost_usd:.2f}"
        )

    with spend.job(rec):
        run_pool(tasks, call, workers=WORKERS, retries=RETRIES, on_result=on_result)
    return 0 if state["failed"] == 0 else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("command", choices=("mine", "admit"))
    a = ap.parse_args(argv)
    kinds = load_kinds()
    if a.command == "mine":
        return run_mine(kinds)
    s = run_admit(kinds)
    print(json.dumps({k: v for k, v in s.items() if k != "per_guide"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
