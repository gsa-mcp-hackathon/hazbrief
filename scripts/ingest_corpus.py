#!/usr/bin/env python3
"""Ingest the corpus into the Squiddy corpus graph (`the corpus graph`), with the
constitution section 15 checkpoint plan of HB-01b.

**No network. No model call.** The Squiddy build this drives has its `extract` valve
closed (the script refuses to run otherwise) and its `admin` valve closed (OpenAlex);
what it builds is the manifest, the ledger, a release, and the retrieval index that
`search` serves, all from the held bytes.

A unit is one corpus document; its key is derived from `doc_id`, the held file's sha256
and its disposition, so a changed file or a changed decision is a new unit. For each
pending unit, in order:

1. **derive** (held HTML, JSON, CSV, XML, XLSX): the form-feed text Squiddy reads
   (`corpus_text.text_blocks`), written to `<graph>/texts/<doc_id>.txt` via an fsynced
   temp file and an atomic rename, then a `derived` row. A held PDF is read in place.
2. **build** (per batch: the pilot, then the rest): the candidates file and the text
   records file are rewritten from every prepared unit, then `squiddy build`. Squiddy's
   own records are its resume (re-running the same version skips what it finished).
   Touchpoint 3 is answered only for this ingest's own entries (`ingest_config.yaml`).
3. **confirm**: the unit's Squiddy manifest entry is `in_graph` and the index holds its
   rows; then a terminal `unit_done` row (`ingested`, or `failed` with the reason,
   retried next run).

Checkpoint: `corpus/ingest_log.jsonl`, append-only, fsynced per row. Re-running the
same command is the resume: units whose terminal row has the same key are skipped.
Progress every `progress_every_units` and every build; a `pilot` row after the pilot
batch; wall-clock and token ceilings exit 3.

A unit ingested under one key whose key has since changed (its bytes changed, or a
metadata-only entry became held) is pending again, like a new unit: its derivative is
rewritten and its candidate carries the new bytes, and `squiddy build` re-admits it as a
revision under the same id, because the graph's candidates source declares the key's
content (`content_fields: [raw_sha256, withheld_reason, edition]` in graph.yaml; squiddy
SQ-023, DN-043 ADDENDUM 03 R-213). HB-01d held such a unit back and exited 1, because
Squiddy then had no re-admission path; that hold is retired. `edition` is declared
content but is not in the unit key (HB-88): a corrected edition needs no re-preparation,
and the candidates file carries every ingested unit's current sources.yaml metadata on
each run, so `squiddy build` revises the released entry from it. A run with no unit
pending rewrites the candidates and text records files too, logs `intake_refreshed`
with the entries that moved, and builds nothing (HB-101: before it, a corrected `reuse:`
waited for some other unit's ingest to reach the text records that the kit's
`text_record_moved: revise` reads). The build that carries such a correction into the
graph is the operator's, under its own label. To stop a live run,
touch `<graph>/STOP` (squiddy's stop: what is in flight lands); a kill must take the
process group, or the `squiddy build` child is orphaned and races the next run (found by
test_ingest_resume.py).

    uv run python scripts/ingest_corpus.py            # the whole ingest, resumable
    uv run python scripts/ingest_corpus.py --dry-run  # the plan, nothing written
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import squiddy_intake as I  # noqa: E402
from corpus_text import PAGE_BREAK, OcrError, ocr_pdf_blocks, text_blocks  # noqa: E402

CONFIG_KEYS = (
    "squiddy_python",
    "graph_dir",
    "candidates_file",
    "text_records_file",
    "texts_dir",
    "version_prefix",
    "recorded_decision",
    "touchpoint3_basis",
    "pilot_doc_ids",
    "progress_every_units",
    "ceiling_wall_clock_seconds",
    "ceiling_weighted_tokens",
    "build_timeout_seconds",
)
SQUIDDY_ENV = "SQUIDDY_PYTHON"
#: squiddy factory exit codes (squiddy/calls.py): 0 done, 3 stopped at a pause or
#: ceiling.
EXIT_STOP = 3
#: The text extractor named on a derivative's record.
DERIVED_EXTRACTOR = (
    "hazbrief scripts/corpus_text.py text_blocks (one block per form-feed page)"
)
#: A held PDF's source entry may name a converter (`text_converter:` in
#: corpus/sources.yaml); the only one is OCR of a scan with no text layer (HB-122),
#: whose settings are `ocr:` in corpus/ingest_config.yaml.
TEXT_CONVERTERS = ("ocr",)


class IngestError(RuntimeError):
    pass


class Ceiling(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_config(path: Path, env: dict | None = None) -> dict:
    import yaml

    if not path.exists():
        raise IngestError(f"config not found: {path}")
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    missing = [k for k in CONFIG_KEYS if k not in cfg]
    if missing:
        raise IngestError(f"{path}: missing required key(s): {', '.join(missing)}")
    env = os.environ if env is None else env
    if env.get(SQUIDDY_ENV):
        cfg["squiddy_python"] = env[SQUIDDY_ENV]
    return cfg


# ------------------------------------------------------------------ the log
class Log:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, row: dict) -> None:
        row = {"ts": _now(), **row}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def rows(self) -> list:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:  # a torn last line from a kill mid-write
                continue
        return out


def next_build_label(rows: list[dict], prefix: str) -> str:
    """The label of the next build: one past the highest `<prefix>_NN` a successful
    build row names (a hand release recorded as a build row counts). Not the count of
    successful builds: a hand release under a label past a failed build's leaves the
    count behind the labels, and a sealed export is never overwritten (DI-110;
    HB-49)."""
    nums = []
    for r in rows:
        if r.get("event") != "build" or r.get("rc") != 0:
            continue
        m = re.fullmatch(rf"{re.escape(prefix)}_(\d+)", r.get("version") or "")
        if m:
            nums.append(int(m.group(1)))
    return f"{prefix}_{max(nums, default=0) + 1:02d}"


def unit_key(e: dict) -> str:
    basis = "\n".join(
        (e["doc_id"], e.get("raw_sha256") or "", e.get("withheld_reason") or "text")
    )
    return hashlib.sha256(basis.encode()).hexdigest()[:16]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


# ------------------------------------------------------------------ squiddy
class Squiddy:
    """The squiddy kit, reached only through its interpreter (never imported here)."""

    def __init__(
        self, python: str, graph: Path, timeout: int, repo: Path = REPO
    ) -> None:
        self.python, self.graph, self.timeout, self.repo = python, graph, timeout, repo

    def _run(
        self, args: list, timeout: int | None = None
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            [self.python, *args],
            capture_output=True,
            text=True,
            timeout=timeout or self.timeout,
            cwd=self.repo,
        )

    def measure(self, paths: list) -> dict:
        if not paths:
            return {}
        r = self._run([str(REPO / "scripts" / "squiddy_measure.py"), *map(str, paths)])
        if r.returncode != 0:
            raise IngestError(f"squiddy_measure failed: {r.stderr[-1500:]}")
        return json.loads(r.stdout)

    def build(self, version: str) -> subprocess.CompletedProcess:
        return self._run(
            [
                "-m",
                "squiddy.cli",
                "build",
                "--graph",
                str(self.graph),
                "--version",
                version,
            ]
        )

    def export_decisions(self) -> subprocess.CompletedProcess:
        return self._run(
            [
                "-m",
                "squiddy.cli",
                "manifest",
                "export-decisions",
                "--graph",
                str(self.graph),
            ]
        )

    def parity(self) -> subprocess.CompletedProcess:
        return self._run(["-m", "squiddy.index", "parity", "--graph", str(self.graph)])


def valve(control: Path, name: str) -> str:
    m = re.search(
        rf"(?m)^  {re.escape(name)}:\s*(\w+)", control.read_text(encoding="utf-8")
    )
    if not m:
        raise IngestError(f"{control}: no `{name}` valve")
    return m.group(1)


def answer_touchpoint3(graph: Path, cfg: dict, log: Log) -> int:
    """Write the control file's `review:` line for this ingest's own undecided entries.
    Raises IngestError when anything else is undecided (the operator's, not ours)."""
    plan = json.loads((graph / "factory" / "plan.json").read_text(encoding="utf-8"))
    und = plan["undecided"]
    ours = " ".join(cfg["recorded_decision"].split())
    others = {
        k: v for k, v in und["by_cataloged_by"].items() if " ".join(k.split()) != ours
    }
    if others:
        raise IngestError(
            f"touchpoint 3: undecided entries this ingest did not catalog: {others}; "
            f"the plan is {graph / 'factory' / 'plan.json'}"
        )
    control = graph / "factory" / "control.yaml"
    text = control.read_text(encoding="utf-8")
    text = re.sub(r"(?ms)^review:.*?(?=^\S|\Z)", "", text).rstrip("\n") + "\n"
    text += (
        "\nreview:  # touchpoint 3 (DN-027 R-127), written by "
        f"scripts/ingest_corpus.py on the basis: {cfg['touchpoint3_basis']}\n"
        f"  undecided: {{count: {und['count']}, date: {date.today().isoformat()}}}\n"
    )
    _atomic_write(control, text.encode("utf-8"))
    log.write(
        {
            "event": "touchpoint3",
            "undecided": und["count"],
            "basis": cfg["touchpoint3_basis"],
        }
    )
    return und["count"]


def squiddy_state(graph: Path) -> tuple:
    """(manifest id -> stage, doc_id -> {"text": n, "meta": n}) from Squiddy's files."""
    import yaml

    man = (
        yaml.safe_load((graph / "corpus" / "manifest.yaml").read_text(encoding="utf-8"))
        or {}
    )
    stages = {d["id"]: d.get("stage") for d in (man.get("documents") or [])}
    rows: dict = {}
    idx = graph / "work" / "index" / "corpus_rows.jsonl"
    if idx.exists():
        for line in idx.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            # The latest line for a (doc, kind) is its current set of rows; a document
            # the index re-embedded after an interrupted release appears again, and is
            # not counted twice.
            rows.setdefault(d["doc_id"], {})[d["kind"]] = len(d.get("rows") or [])
    return stages, rows


# ------------------------------------------------------------------ the run
def prepare(
    e: dict, repo: Path, graph: Path, cfg: dict, log: Log, derived: dict
) -> tuple:
    """(text_path, text_sha256) for a unit; None, None for metadata only. Derives
    once: a `derived` row whose file still hashes to its sha256 is reused."""
    if e.get("withheld_reason"):
        return None, None
    raw = repo / e["raw_path"]
    converter = e.get("text_converter")
    if raw.suffix.lower() == ".pdf" and not converter:
        return raw.resolve(), e["raw_sha256"]
    extractor = extractor_for(e, cfg)
    out = (graph / cfg["texts_dir"] / f"{e['doc_id']}.txt").resolve()
    key = unit_key(e)
    prior = derived.get(key)
    # A derivative is reused only if it still hashes to its row and was made by the same
    # converter (a row from before HB-122 names none: the text_blocks converter).
    if (
        prior
        and out.exists()
        and _sha(out) == prior["text_sha256"]
        and prior.get("extractor", DERIVED_EXTRACTOR) == extractor
    ):
        return out, prior["text_sha256"]
    if converter == "ocr":
        try:
            blocks = ocr_pdf_blocks(raw, cfg["ocr"])
        except OcrError as exc:
            raise IngestError(f"{e['doc_id']}: {exc}") from exc
    else:
        blocks = text_blocks(raw)
    if not blocks:
        raise IngestError(f"{e['doc_id']}: no text converter or no text for {raw.name}")
    _atomic_write(out, PAGE_BREAK.join(blocks).encode("utf-8"))
    sha = _sha(out)
    log.write(
        {
            "event": "derived",
            "doc_id": e["doc_id"],
            "key": key,
            "text_path": str(out),
            "text_sha256": sha,
            "blocks": len(blocks),
            "extractor": extractor,
        }
    )
    derived[key] = {"text_sha256": sha, "extractor": extractor}
    return out, sha


def extractor_for(e: dict, cfg: dict) -> str:
    """The `extractor` a text record names for a derivative: the converter that wrote
    it."""
    converter = e.get("text_converter")
    if not converter:
        return DERIVED_EXTRACTOR
    if converter not in TEXT_CONVERTERS:
        raise IngestError(
            f"{e['doc_id']}: text_converter {converter!r} is not one of "
            f"{TEXT_CONVERTERS}"
        )
    ocr = cfg.get("ocr")
    if not ocr:
        raise IngestError(
            f"{e['doc_id']}: text_converter ocr needs the `ocr:` section of the "
            "ingest config"
        )
    return (
        f"{ocr['engine']} {ocr['version']} {ocr['dpi']}dpi --psm {ocr['psm']}, "
        "consumer converter (HB-122)"
    )


def write_intake(graph: Path, cfg: dict, prepared: list, measured: dict) -> None:
    """Rewrite the candidates and records files from every prepared unit (deterministic:
    source-list order), so a resumed run writes the bytes an uninterrupted one does."""
    import yaml

    cands, records = [], []
    for e, path, sha in prepared:
        cands.append(I.candidate(e, path, sha))
        if path is None:
            continue
        m = measured[str(path)]
        records.append(
            {
                "expression": e["doc_id"],
                "path": str(path),
                "sha256": sha,
                "bytes": path.stat().st_size,
                "pages": m["pages"],
                "text_chars": m["text_chars"],
                "extractor": "pypdfium2"
                if path.suffix == ".pdf"
                else extractor_for(e, cfg),
                "license": e["reuse"],
                "source_url": e.get("url"),
                "fetched_at": e.get("retrieved_at"),
                "state": "passed",
            }
        )
    doc = {
        "recorded_decision": " ".join(cfg["recorded_decision"].split()),
        "banner": "hazbrief-mcp corpus: generated by scripts/ingest_corpus.py from "
        "corpus/sources.yaml, "
        "corpus/fetch_log.jsonl and corpus/operator_downloads.jsonl. Do not edit.",
        "candidates": cands,
    }
    _atomic_write(
        graph / cfg["candidates_file"],
        yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100).encode(
            "utf-8"
        ),
    )
    _atomic_write(
        graph / cfg["text_records_file"],
        (
            json.dumps(
                {"tool": "scripts/ingest_corpus.py", "results": records}, indent=1
            )
            + "\n"
        ).encode(),
    )


def _intake_by_id(graph: Path, cfg: dict) -> tuple:
    """(candidate id -> candidate, record expression -> record) as the intake files
    stand; empty where a file is absent."""
    import yaml

    cand_p, rec_p = graph / cfg["candidates_file"], graph / cfg["text_records_file"]
    cands = (yaml.safe_load(cand_p.read_text("utf-8")) or {}) if cand_p.exists() else {}
    recs = json.loads(rec_p.read_text("utf-8")) if rec_p.exists() else {}
    return (
        {c["id"]: c for c in cands.get("candidates") or []},
        {r["expression"]: r for r in recs.get("results") or []},
    )


def refresh_intake(graph: Path, cfg: dict, sq: Squiddy, items: list, log: Log) -> dict:
    """Rewrite the intake files from every ingested unit when no unit is pending.

    A correction to a source entry's metadata (HB-95's `reuse:` for the five CAMEO guide
    pages) moves no unit key, so before HB-101 it reached the intake files only when
    some other unit was ingested. The kit's `text_record_moved: revise` (HB-92) reads
    the text records, so the correction waited on an unrelated document. This writes
    the bytes an ingest batch would (`write_intake` is deterministic), logs the entries
    whose candidate or record moved, and builds nothing: the build that opens the
    revisions is run under its own label (HB-92, HB-101)."""
    before = _intake_by_id(graph, cfg)
    measured = sq.measure([p for _, p, _ in items if p is not None])
    write_intake(graph, cfg, items, measured)
    after = _intake_by_id(graph, cfg)
    moved = {
        name: sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
        for name, b, a in zip(("candidates_moved", "records_moved"), before, after)
    }
    if any(moved.values()):
        log.write({"event": "intake_refreshed", **moved})
    return moved


def run(
    cfg: dict,
    repo: Path,
    log_path: Path,
    entries: list,
    dry_run: bool = False,
    squiddy: Squiddy | None = None,
    clock=time.monotonic,
) -> int:
    graph = (repo / cfg["graph_dir"]).resolve()
    control = graph / "factory" / "control.yaml"
    if not (graph / "graph.yaml").exists():
        raise IngestError(f"no Squiddy graph at {graph} (squiddy init it first)")
    if valve(control, "extract") != "closed" or valve(control, "admin") != "closed":
        raise IngestError(
            f"{control}: the extract and admin valves must be closed "
            "(no model, no network)"
        )
    sq = squiddy or Squiddy(
        cfg["squiddy_python"], graph, cfg["build_timeout_seconds"], repo
    )
    log = Log(log_path)
    rows = log.rows()
    done = {
        r["key"]: r
        for r in rows
        if r.get("event") == "unit_done" and r["outcome"] == "ingested"
    }
    derived = {r["key"]: r for r in rows if r.get("event") == "derived"}
    label = next_build_label(rows, cfg["version_prefix"])
    piloted = any(r.get("event") == "pilot" for r in rows)

    by_key = {unit_key(e): e for e in entries}
    pending = [e for k, e in by_key.items() if k not in done]
    pilot_ids = set(cfg["pilot_doc_ids"])
    batches = []
    if not piloted and any(e["doc_id"] in pilot_ids for e in pending):
        batches.append(("pilot", [e for e in pending if e["doc_id"] in pilot_ids]))
        pending = [e for e in pending if e["doc_id"] not in pilot_ids]
    if pending:
        batches.append(("rest", pending))
    print(
        f"[ingest] {len(entries)} unit(s); "
        f"{sum(1 for k in by_key if k in done)} done; "
        f"{sum(len(b) for _, b in batches)} to run in {len(batches)} batch(es)"
    )
    if dry_run:
        for name, b in batches:
            print(f"  {name}: {len(b)}: " + ", ".join(e["doc_id"] for e in b))
        return 0
    # The token ceiling binds through the valve: with `extract` closed (checked above)
    # no model is called, so the run's weighted tokens are 0 against the ceiling,
    # recorded here.
    log.write(
        {
            "event": "run_start",
            "units": len(entries),
            "done": len(done),
            "weighted_tokens_ceiling": cfg["ceiling_weighted_tokens"],
            "weighted_tokens_basis": "extract valve closed: no model call",
        }
    )
    t0 = clock()
    exit_code = 0
    # Every unit already ingested stays in the intake files, so a rebuild sees the whole
    # set.
    prepared = {e["doc_id"]: e for e in entries if unit_key(e) in done}
    paths = {}
    try:
        for e in prepared.values():
            paths[e["doc_id"]] = prepare(e, repo, graph, cfg, log, derived)
        for name, batch in batches:
            t_batch = clock()
            for n, e in enumerate(batch, 1):
                if clock() - t0 > cfg["ceiling_wall_clock_seconds"]:
                    raise Ceiling("ceiling_wall_clock_seconds")
                paths[e["doc_id"]] = prepare(e, repo, graph, cfg, log, derived)
                prepared[e["doc_id"]] = e
                if n % cfg["progress_every_units"] == 0:
                    log.write(
                        {
                            "event": "progress",
                            "batch": name,
                            "prepared": n,
                            "of": len(batch),
                        }
                    )
                    print(f"[ingest] {name}: prepared {n}/{len(batch)}")
            order = [e for e in entries if e["doc_id"] in prepared]
            items = [(e, *paths[e["doc_id"]]) for e in order]
            measured = sq.measure([p for _, p, _ in items if p is not None])
            write_intake(graph, cfg, items, measured)
            version = label
            r = sq.build(version)
            if r.returncode == EXIT_STOP:
                pause = json.loads(
                    (graph / "factory" / "pause.json").read_text(encoding="utf-8")
                )
                if pause.get("touchpoint") == 3:
                    answer_touchpoint3(graph, cfg, log)
                    r = sq.build(version)
            ok = r.returncode == 0
            log.write(
                {
                    "event": "build",
                    "batch": name,
                    "version": version,
                    "rc": r.returncode,
                    "seconds": round(clock() - t_batch, 1),
                    "stderr_tail": r.stderr[-600:],
                }
            )
            if ok:
                label = next_build_label(
                    [{"event": "build", "version": version, "rc": 0}],
                    cfg["version_prefix"],
                )
                sq.export_decisions()
            stages, idx = squiddy_state(graph)
            pages = 0
            for n, e in enumerate(batch, 1):
                path = paths[e["doc_id"]][0]
                text_rows = idx.get(e["doc_id"], {}).get("text", 0)
                meta_rows = idx.get(e["doc_id"], {}).get("meta", 0)
                stage = stages.get(e["doc_id"])
                reason = None
                if not ok:
                    reason = f"build {version} rc {r.returncode}"
                elif stage != "in_graph":
                    reason = f"squiddy stage {stage!r}, not in_graph"
                elif path is not None and text_rows == 0:
                    reason = "in_graph but the index holds no text rows for it"
                elif meta_rows == 0:
                    reason = "in_graph but the index holds no metadata row for it"
                if path is not None:
                    pages += measured[str(path)]["pages"]
                log.write(
                    {
                        "event": "unit_done",
                        "doc_id": e["doc_id"],
                        "key": unit_key(e),
                        "outcome": "failed" if reason else "ingested",
                        "reason": reason,
                        "raw_sha256": e.get("raw_sha256"),
                        "text_sha256": paths[e["doc_id"]][1],
                        "withheld_reason": e.get("withheld_reason"),
                        "squiddy_stage": stage,
                        "index_text_rows": text_rows,
                        "version": version,
                    }
                )
                if reason:
                    exit_code = 1
                if n % cfg["progress_every_units"] == 0:
                    print(f"[ingest] {name}: confirmed {n}/{len(batch)}")
            if name == "pilot":
                secs = clock() - t_batch
                rest = [
                    e for _, b in batches[1:] for e in b if not e.get("withheld_reason")
                ]
                rest_pdfs = [
                    (repo / e["raw_path"]).resolve()
                    for e in rest
                    if e.get("raw_path", "").endswith(".pdf")
                ]
                rest_pdf_pages = sum(m["pages"] for m in sq.measure(rest_pdfs).values())
                row = {
                    "event": "pilot",
                    "units": len(batch),
                    "pages": pages,
                    "seconds": round(secs, 1),
                    "seconds_per_page": round(secs / pages, 3) if pages else None,
                    "weighted_tokens": 0,
                    "rest_units": len(rest),
                    "rest_pdf_pages": rest_pdf_pages,
                    "projected_seconds_rest_pdf": round(
                        secs / pages * rest_pdf_pages, 1
                    )
                    if pages
                    else None,
                }
                log.write(row)
                print(f"[ingest] pilot: {json.dumps(row)}")
            if not ok:
                exit_code = 1
                break
        if not batches:
            items = [
                (e, *paths[e["doc_id"]]) for e in entries if e["doc_id"] in prepared
            ]
            moved = refresh_intake(graph, cfg, sq, items, log)
            if any(moved.values()):
                print(
                    "[ingest] intake files moved with no unit pending: candidates "
                    f"{moved['candidates_moved']}, records {moved['records_moved']}; "
                    "run `squiddy build` to carry them into the graph"
                )
            else:
                print("[ingest] intake files unchanged")
        if exit_code == 0:
            p = sq.parity()
            log.write(
                {"event": "parity", "rc": p.returncode, "stdout_tail": p.stdout[-600:]}
            )
            if p.returncode != 0:
                exit_code = 1
    except Ceiling as c:
        log.write({"event": "ceiling", "ceiling": str(c)})
        print(f"[ingest] ceiling crossed: {c}", file=sys.stderr)
        exit_code = EXIT_STOP
    log.write(
        {"event": "run_end", "exit": exit_code, "seconds": round(clock() - t0, 1)}
    )
    return exit_code


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", type=Path, default=REPO, help="repository root (tests)")
    ap.add_argument("--config", type=Path, default=None)
    ap.add_argument("--log", type=Path, default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    repo = a.repo.resolve()
    try:
        cfg = load_config(a.config or repo / "corpus" / "ingest_config.yaml")
        log = a.log or repo / "corpus" / "ingest_log.jsonl"
        return run(cfg, repo, log, I.load(repo), dry_run=a.dry_run)
    except IngestError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
