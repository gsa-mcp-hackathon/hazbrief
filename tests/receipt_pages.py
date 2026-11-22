"""The reference text the flag receipts are checked against, committed for a clean clone
(HB-90 step 6; review L5-1).

A flag's receipt is a quote verified at build on the cited page, through one of two text
layers (`packs/flag_rules.json` `text_layer`):

- `pdf_text`: the page as `scripts/build_packs.py` `SourceSet.page` reads it from the
  held PDF (`corpus/raw/`, gitignored). This module writes each cited page to
  `pages/<doc_id>/p<N>.txt`, exactly as `SourceSet.page` returns
  it.
- `keyA`: the ERG guide pages keyed by HB-03b (`packs/build/keyA/guides.jsonl`,
  gitignored with the rest of `packs/build/`). `fixtures/receipt_text/keyA_guides.jsonl`
  is a byte copy, and `packs/build/MANIFEST.json` (committed) records its sha256.

Every cited document is a US Government work in the public domain, or the ERG 2024,
whose p. 382 notice permits reproduction (`packs/erg.json` `licence`
`reproduction-permitted`); `test_receipt_text.py` asserts that before anything is
committed here.

Regenerate on the build host, after a pack rebuild that changes a receipt:

    uv run python tests/receipt_pages.py

It needs `corpus/raw/` and `packs/build/keyA/`, and refuses without them.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FLAG_RULES = REPO / "packs" / "flag_rules.json"
OUT = REPO / "fixtures" / "receipt_text"
PAGES = OUT / "pages"
KEYA_BUILD = REPO / "packs" / "build" / "keyA" / "guides.jsonl"
KEYA_COPY = OUT / "keyA_guides.jsonl"
STATEMENTS = ("receipts", "consequence", "response")


def statements(layer: str) -> list[dict]:
    """Every receipt, consequence and response statement of every rule on `layer`."""
    rules = json.loads(FLAG_RULES.read_text(encoding="utf-8"))["data"]["rules"]
    out = []
    for r in rules:
        for field in STATEMENTS:
            v = r.get(field)
            for st in v if isinstance(v, list) else [v]:
                if st and st["text_layer"] == layer:
                    out.append(st | {"rule_id": r["rule_id"]})
    return out


def cited_pages() -> list[tuple[str, int]]:
    return sorted({(s["doc_id"], s["page"]) for s in statements("pdf_text")})


def page_path(doc_id: str, page: int) -> Path:
    return PAGES / doc_id / f"p{page}.txt"


def read_page(doc_id: str, page: int) -> str:
    """The committed page, byte for byte: some held pages end lines with CRLF, which a
    text-mode read would fold into LF."""
    return page_path(doc_id, page).read_bytes().decode("utf-8")


def _build_packs():
    spec = importlib.util.spec_from_file_location(
        "build_packs", REPO / "scripts" / "build_packs.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def write() -> int:
    raw = REPO / "corpus" / "raw"
    if not raw.is_dir() or not KEYA_BUILD.is_file():
        raise SystemExit(
            f"needs the build host's {raw.relative_to(REPO)}/ and "
            f"{KEYA_BUILD.relative_to(REPO)}"
        )
    B = _build_packs()
    sources = B.SourceSet(B.load_config(REPO / "packs" / "src" / "build_config.yaml"))
    if PAGES.exists():
        shutil.rmtree(PAGES)
    for doc_id, page in cited_pages():
        p = page_path(doc_id, page)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(sources.page(doc_id, page).encode("utf-8"))
    shutil.copyfile(KEYA_BUILD, KEYA_COPY)
    return len(cited_pages())


if __name__ == "__main__":
    n = write()
    print(f"wrote {n} pages under {PAGES.relative_to(REPO)} and {KEYA_COPY.name}")
    sys.exit(0)
