#!/usr/bin/env python3
"""Key B of the HB-03b triple keying: a vision read of each rendered ERG 2024 page.

Run by Squiddy's python (`squiddy_python` in corpus/ingest_config.yaml), where the
operator's one model client and spend governor live:

    $SQUIDDY_PY scripts/erg_keyb.py pilot   # step 4a: 10 pilot pages, then projection
    $SQUIDDY_PY scripts/erg_keyb.py run     # step 4b: every page in the Key B set
    $SQUIDDY_PY scripts/erg_keyb.py status  # what the checkpoint holds

**The model call.** `squiddy.model_client.ClaudeCLIClient` for the seldon registry role
in config (`keyb.role`): the lock's CLI on the operator's Max session, the model id from
the lock, a receipt on every call (a substituted model halts the run), every call
reserved on a declared job of the machine-wide spend ledger (`squiddy.spend`). The only
change made here is to let the child read the page image: `--tools Read` in place of
`--tools ""`, the image written into the child's own empty working directory. The prompt
asks for a transcription, never a judgement.

**Checkpoint/restart** (standards section 15). The unit is one page. Its key is (table,
page, sha256 of the prompt, model id); a changed prompt or model is a new key, so a
stale reading is never reused. Each settled page (its parsed reading, or its error) is
appended to `packs/build/keyB/pages.jsonl`, flushed and fsynced, before the pool goes
on; re-running the same command skips every key already read, so the command is its own
resume. Progress (done/total, rate, ETA, tokens, cost-equivalent, failures) is printed
and logged every `progress_seconds`. Ceilings: the spend job's token and call caps (the
governor refuses the next reservation), and `wall_clock_seconds` (no new page starts
after it). A failed page is a row, retried by the pool `retries` times, and never takes
the read pages down with it.

**Pilot** (step 4a). Five pages drawn from the disagreement set and five controls drawn
from pages where Key A and Key C agree on every row (`scripts/erg_join.py pilot`). The
run is the spend governor's pilot for this node, so its measured spend becomes the basis
of the full run's estimate. The projection (pages, tokens, seconds, cost-equivalent) is
written to the log; `run` refuses when the page count exceeds `max_page_reads`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "packs" / "src" / "erg_keys.yaml"

COMMON = (
    "Read the image file ./{image}. It is page {page} (PDF page) of the Emergency "
    "Response Guidebook 2024, rendered at {dpi} dpi. Transcribe it exactly as printed: "
    "copy every character as it appears, keep the printed spelling, capitalization and "
    "punctuation, and do not correct, complete, reorder or summarize anything. Where a "
    "name or a sentence wraps onto the next printed line, join the lines with one "
    "space "
    "(no space after a line-ending hyphen inside a word). Ignore page numbers, side "
    "tabs and running heads. Return ONLY one JSON object, no prose, no code fence."
)

SCHEMAS = {
    "yellow": (
        "The page is an index in two columns: read the left column top to bottom, then "
        'the right. Each row prints an ID number (four digits, or "— —" for entries '
        "with no ID), a guide number (three digits, sometimes followed by P) and a "
        "name "
        'of material. JSON: {"rows": [{"id": "1005" or "—", "guide": "125", "name": '
        '"Ammonia, anhydrous", "highlighted": true}]}. "highlighted" is true when the '
        "row is printed on a green band."
    ),
    "blue": (
        "The page is an index in two columns: read the left column top to bottom, then "
        "the right. Each row prints a name of material, a guide number (three digits, "
        'sometimes followed by P) and an ID number (four digits, or "— —"). JSON: '
        '{"rows": [{"id": "1005" or "—", "guide": "125", "name": "Ammonia, anhydrous", '
        '"highlighted": true}]}. "highlighted" is true when the row is printed on a '
        "green band."
    ),
    "table1": (
        "The page is printed sideways: it is Table 1, Initial Isolation and Protective "
        "Action Distances. Each record prints one or more ID numbers, each with its "
        "guide "
        'number and name (a name may end in a bold qualifier such as "(when spilled in '
        'water)", which is part of the name), then the small spill distances (isolate '
        "metres and feet; protect day km and mi; protect night km and mi) and the "
        "large "
        "spill distances, or the words Refer to Table 3. Give one row per ID-and-name; "
        "rows of one record repeat the record's distances. Copy each distance as "
        "printed, "
        'keeping a trailing "+". JSON: {"rows": [{"id": "1017", "guide": "124", '
        '"name": '
        '"Chlorine", "small": {"isolate_m": "60", "isolate_ft": "200", "day_km": '
        '"0.3", '
        '"day_mi": "0.2", "night_km": "1.5", "night_mi": "0.9"}, "large": {...the same '
        'keys...} or "Refer to Table 3"}]}.'
    ),
    "table2": (
        "The page is Table 2, Water-Reactive Materials Which Produce Toxic Gases. Each "
        "row prints an ID number, a guide number, a name of material and one or more "
        "gas symbols (write subscripts as plain digits: H2S). Do not transcribe the "
        'legend of chemical symbols. JSON: {"rows": [{"id": "1162", "guide": "155", '
        '"name": "Dimethyldichlorosilane", "gases": ["HCl"]}], "legend": [["HCl", '
        '"Hydrogen chloride"]]}, the legend being the printed list of chemical symbols '
        "and their names."
    ),
    "table3": (
        "The page is printed sideways: it is Table 3, Initial Isolation and Protective "
        "Action Distances for Large Spills. It prints one block per gas, headed like "
        '"UN1017 Chlorine: Large Spills", and one row per transport container: the '
        "container, isolate metres and (feet), then twelve values: day low, moderate, "
        "high wind km and (miles), then night low, moderate, high km and (miles). Copy "
        'each number as printed, keeping a trailing "+", without parentheses. JSON: '
        '{"rows": [{"un": "1017", "heading": "UN1017 Chlorine: Large Spills", '
        '"container": "Rail tank car", "values": ["1000", "3000", "9.6", "6.0", ...14 '
        "strings in printed order...]}]}."
    ),
    "guides": (
        "The page is one page of an orange guide. Give the guide number, its title as "
        "printed at the top, and every printed item of the guide text in order, each "
        "with "
        'the section it falls under ("POTENTIAL HAZARDS", "PUBLIC SAFETY" or '
        '"EMERGENCY RESPONSE") and its kind: "section" for those three headings, '
        '"heading" for a sub-heading (FIRE OR EXPLOSION, HEALTH, EVACUATION, '
        'Immediate precautionary measure, Small Fire, ...), "bullet" for a bulleted '
        "line "
        '(without the bullet character), "text" for any other paragraph (a CAUTION: '
        "line). Leave out footnotes at the foot of the page and the note about an "
        'Emergency Response Assistance Plan. JSON: {"guide": "124", "title": "...", '
        '"items": [{"section": "POTENTIAL HAZARDS", "kind": "section", "text": '
        '"POTENTIAL HAZARDS"}]}.'
    ),
}


def load_config(path: Path = CONFIG) -> dict:
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    for k in ("paths", "keya", "keyb"):
        if k not in cfg:
            raise SystemExit(f"{path}: missing required key {k!r}")
    return cfg


def prompt_for(table: str, page: int, dpi: int) -> str:
    image = f"p{page:04d}.png"
    return COMMON.format(image=image, page=page, dpi=dpi) + " " + SCHEMAS[table]


def prompt_sha(table: str, page: int, dpi: int) -> str:
    return hashlib.sha256(prompt_for(table, page, dpi).encode("utf-8")).hexdigest()[:16]


def unit_key(table: str, page: int, dpi: int, model: str) -> str:
    return f"{table}|{page}|{prompt_sha(table, page, dpi)}|{model}"


def parse_reading(table: str, content: str) -> dict:
    """The model's JSON, shape-checked; raises ValueError for anything else (the pool
    retries the page)."""
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.index("\n") + 1 :] if "\n" in text else text
    obj = json.loads(text)
    if not isinstance(obj, dict):
        raise ValueError("reading is not a JSON object")
    want = "items" if table == "guides" else "rows"
    if not isinstance(obj.get(want), list) or not obj[want]:
        raise ValueError(f"reading has no {want!r} list")
    return obj


# ------------------------------------------------------------------ checkpoint
class Checkpoint:
    """Append-only JSONL of settled pages, fsynced per row (standards section 15.1)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def rows(self) -> list:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
        return out

    def done_keys(self) -> set:
        return {r["key"] for r in self.rows() if r.get("ok")}

    def append(self, row: dict) -> None:
        line = json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
        with self._lock, self.path.open("a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())


# ------------------------------------------------------------------ rendering
#: PDFium is not thread-safe (pypdfium2's documentation says so); the pool's threads
#: take turns to render.
_RENDER_LOCK = threading.Lock()


def render(pdf_path: Path, page: int, dpi: int, out: Path) -> None:
    import pypdfium2 as pdfium

    with _RENDER_LOCK:
        doc = pdfium.PdfDocument(str(pdf_path))
        try:
            doc[page - 1].render(scale=dpi / 72).to_pil().save(out)
        finally:
            doc.close()


def pdf_path() -> Path:
    """The held ERG 2024 PDF, located by its corpus record (the fetch log's raw
    path)."""
    for line in (REPO / "corpus" / "fetch_log.jsonl").read_text().splitlines():
        r = json.loads(line)
        if r.get("doc_id") == "erg2024-en-pdf" and r.get("raw_path"):
            p = REPO / r["raw_path"]
            if p.exists():
                return p
    p = REPO / "corpus" / "raw" / "erg2024-en-pdf.pdf"
    if not p.exists():
        raise SystemExit("erg2024-en-pdf is not held under corpus/raw/")
    return p


# ------------------------------------------------------------------ the run
def make_client(cfg: dict):
    from squiddy.model_client import ClaudeCLIClient

    class VisionClient(ClaudeCLIClient):
        """The kit's client, with the child allowed to read the page image."""

        def command(self, prompt: str) -> list:
            cmd = super().command(prompt)
            i = cmd.index("--tools")
            cmd[i + 1] = "Read"
            return cmd + ["--allowedTools", "Read"]

        def spend_profile(self) -> str:
            return (
                super().spend_profile() + ",tools=Read,dpi=" + str(cfg["keyb"]["dpi"])
            )

    kb = cfg["keyb"]
    return VisionClient(
        role=kb["role"],
        minimal_scaffold=True,
        max_turns=kb["max_turns"],
        timeout=kb["timeout_seconds"],
    )


class Progress:
    def __init__(self, total: int, log: Path, client, every: float):
        self.total, self.log, self.client, self.every = total, log, client, every
        self.done = self.failed = 0
        self.t0 = time.monotonic()
        self._stop = threading.Event()
        self._lock = threading.Lock()

    def line(self) -> str:
        el = time.monotonic() - self.t0
        rate = self.done / el if el > 0 else 0.0
        eta = (
            (self.total - self.done - self.failed) / rate if rate > 0 else float("nan")
        )
        u = self.client.usage_totals
        return (
            f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ} done {self.done}/"
            f"{self.total} failed {self.failed} rate {rate * 60:.1f}/min eta "
            f"{eta / 60:.1f} min tokens in {u.get('input_tokens', 0)} out "
            f"{u.get('output_tokens', 0)} cache_read "
            f"{u.get('cache_read_input_tokens', 0)} "
            f"cache_write {u.get('cache_creation_input_tokens', 0)} cost_equiv_usd "
            f"{self.client.total_cost_usd:.2f}"
        )

    def emit(self, text: str) -> None:
        print(text, flush=True)
        with self.log.open("a", encoding="utf-8") as f:
            f.write(text + "\n")

    def settle(self, ok: bool) -> None:
        with self._lock:
            if ok:
                self.done += 1
            else:
                self.failed += 1

    def start(self) -> None:
        def loop():
            while not self._stop.wait(self.every):
                self.emit(self.line())

        threading.Thread(target=loop, daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        self.emit(self.line())


def run_pages(cfg: dict, pages: list, job_name: str, log: Path) -> dict:
    """Read every (table, page) not yet in the checkpoint. Returns the run's totals."""
    from squiddy import spend
    from squiddy.model_client import run_pool

    kb = cfg["keyb"]
    ck = Checkpoint(REPO / cfg["paths"]["keyb_dir"] / "pages.jsonl")
    client = make_client(cfg)
    done = ck.done_keys()
    todo = [
        p
        for p in pages
        if unit_key(p["table"], p["page"], kb["dpi"], client.model) not in done
    ]
    prog = Progress(len(todo), log, client, kb["progress_seconds"])
    prog.emit(
        f"[keyB] {job_name}: {len(pages)} pages, {len(pages) - len(todo)} already "
        "read, "
        f"{len(todo)} to read; model {client.model} role {client.role} effort "
        f"{client.effort}"
    )
    if not todo:
        return {"read": 0, "failed": 0, "pages": len(pages)}
    src = pdf_path()
    prog.emit(
        f"[keyB] source {src.relative_to(REPO)} sha256 "
        f"{hashlib.sha256(src.read_bytes()).hexdigest()}"
    )
    cwd = client._cwd_for_child()
    deadline = time.monotonic() + kb["wall_clock_seconds"]

    def call(task: dict, workers: int = 1) -> dict:
        if time.monotonic() > deadline:
            return {"skipped": "wall_clock"}
        table, page = task["table"], task["page"]
        render(src, page, kb["dpi"], cwd / f"p{page:04d}.png")
        inv = client.invoke(prompt_for(table, page, kb["dpi"]))
        reading = parse_reading(table, inv.content)
        return {
            "reading": reading,
            "usage": inv.usage,
            "cost_usd": inv.cost_usd,
            "seconds": inv.seconds,
            "receipt": inv.receipt,
            "model": inv.resolved_model,
        }

    def on_result(task: dict, r: dict) -> None:
        res = r.get("result") or {}
        if res.get("skipped"):
            return  # not called: the next run reads it
        ok = r.get("error") is None
        ck.append(
            {
                "key": unit_key(task["table"], task["page"], kb["dpi"], client.model),
                "table": task["table"],
                "page": task["page"],
                "prompt_sha": prompt_sha(task["table"], task["page"], kb["dpi"]),
                "model": client.model,
                "ok": ok,
                "error": r.get("error"),
                "attempts": r.get("attempts"),
                "reading": res.get("reading"),
                "usage": res.get("usage"),
                "cost_usd": res.get("cost_usd"),
                "seconds": res.get("seconds"),
                "receipt": res.get("receipt"),
                "read_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "job": job_name,
            }
        )
        prog.settle(ok)

    spec = {
        "job": job_name,
        "lane": kb["lane"],
        "model": client.model,
        "profile": client.spend_profile(),
        "node": kb["node"],
        "units": len(todo),
        "token_cap": kb["token_cap"],
        "call_cap": len(todo) * (kb["retries"] + 1),
        "approval_dir": str(REPO / cfg["paths"]["keyb_dir"]),
    }
    rec = spend.declare_or_pilot(spec, guess=kb["guess_tokens_per_page"] * len(todo))
    if rec.get("units") != len(todo):
        prog.emit(
            f"[keyB] the spend governor cut the job to its pilot: {rec.get('units')} "
            "of "
            f"{len(todo)} pages (no measured basis yet for this node)"
        )
        todo = todo[: rec["units"]]
    prog.start()
    try:
        with spend.job(rec):
            run_pool(
                todo,
                call,
                workers=kb["workers"],
                retries=kb["retries"],
                on_result=on_result,
            )
    finally:
        prog.stop()
    return {"read": prog.done, "failed": prog.failed, "pages": len(pages)}


def projection(cfg: dict, pilot_rows: list, n_pages: int) -> dict:
    ok = [r for r in pilot_rows if r.get("ok")]
    if not ok:
        raise SystemExit("the pilot read no page; nothing to project from")
    keys = ("input_tokens", "output_tokens", "cache_read_input_tokens",
            "cache_creation_input_tokens")  # fmt: skip
    per = {k: sum((r["usage"] or {}).get(k, 0) for r in ok) / len(ok) for k in keys}
    secs = sum(r["seconds"] or 0 for r in ok) / len(ok)
    cost = sum(r["cost_usd"] or 0 for r in ok) / len(ok)
    w = cfg["keyb"]["workers"]
    return {
        "pilot_pages_read": len(ok),
        "per_page": {**per, "seconds": round(secs, 1), "cost_usd": round(cost, 4)},
        "pages": n_pages,
        "projected_tokens": {k: round(v * n_pages) for k, v in per.items()},
        "projected_cost_usd": round(cost * n_pages, 2),
        "projected_wall_minutes": round(secs * n_pages / w / 60, 1),
        "max_page_reads": cfg["keyb"]["max_page_reads"],
        "within_ceiling": n_pages <= cfg["keyb"]["max_page_reads"],
    }


def _stamp() -> str:
    """A spend job is declared once; each run of the command is its own job."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("command", choices=("pilot", "run", "status"))
    a = ap.parse_args(argv)
    cfg = load_config()
    jd = REPO / cfg["paths"]["join_dir"]
    log = REPO / cfg["paths"]["log_dir"] / "2026-10-21_HB-03b_keyb.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    summary = json.loads((jd / "summary.json").read_text(encoding="utf-8"))
    every = [
        {"table": t, "page": p} for t, s in summary.items() for p in s["pages_for_keyB"]
    ]
    pilot = json.loads((jd / "pilot_pages.json").read_text(encoding="utf-8"))
    ck = Checkpoint(REPO / cfg["paths"]["keyb_dir"] / "pages.jsonl")
    if a.command == "status":
        rows = ck.rows()
        print(
            json.dumps(
                {
                    "rows": len(rows),
                    "ok": sum(1 for r in rows if r.get("ok")),
                    "failed": sum(1 for r in rows if not r.get("ok")),
                    "pages_in_set": len(every),
                },
                indent=1,
            )
        )
        return 0
    if a.command == "pilot":
        run_pages(cfg, pilot, f"hazbrief-hb03b-keyb-pilot-{_stamp()}", log)
        keys = {(p["table"], p["page"]) for p in pilot}
        rows = [r for r in ck.rows() if (r["table"], r["page"]) in keys]
        proj = projection(cfg, rows, len(every))
        line = "[keyB] projection " + json.dumps(proj, sort_keys=True)
        print(line)
        with log.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        (REPO / cfg["paths"]["keyb_dir"] / "projection.json").write_text(
            json.dumps(proj, indent=1, sort_keys=True) + "\n", encoding="utf-8"
        )
        return 0
    if len(every) > cfg["keyb"]["max_page_reads"]:
        print(
            f"refused: {len(every)} pages exceed max_page_reads "
            f"{cfg['keyb']['max_page_reads']} (task step 4: stop and report)",
            file=sys.stderr,
        )
        return 2
    res = run_pages(cfg, every, f"hazbrief-hb03b-keyb-run-{_stamp()}", log)
    return 0 if res["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
