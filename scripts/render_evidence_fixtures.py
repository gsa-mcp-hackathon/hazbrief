#!/usr/bin/env python3
"""Render the evidence fixtures from the seed (HB-40 steps 3 and 4).

    uv run python scripts/render_evidence_fixtures.py           # write
    fixtures/evidence/ uv run python scripts/render_evidence_fixtures.py --check   #
    exit 1 if any differs uv run python scripts/render_evidence_fixtures.py --labels  #
    the label table (RESULT)

From the tool-call seed (`evidence/seed_calls/`, its `used` resolved in
`evidence/seed/`), at the fixed instant and zone `labels.yaml` names, so the output is
deterministic:
* `appendix_seed.txt`, `.md`, `.html`: the evidence appendix of the seven tool-call
  records, each followed by the records it used;
* `ics201_labelled_<scenario>.md`: the scenario's ICS 201 with each block's labels under
  it and the appendix after it (`render_ics201`). `test_evidence_labels.py`
  compares each one to a fresh render.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from hazbrief.evidence import labels as L  # noqa: E402
from hazbrief.evidence import store as S  # noqa: E402

OUT = REPO / "fixtures" / "evidence"


def stores() -> list[Path]:
    return [S.repo_path("seed_calls_store_dir"), S.repo_path("seed_store_dir")]


def renders() -> dict[str, str]:
    cfg = L.config()
    now = S.parse_time(cfg["fixture_now"])
    tz = cfg["fixture_time_zone"]
    calls = S.all_records(stores()[0])
    if len(calls) != 7:
        raise SystemExit(f"FATAL: the tool-call seed holds {len(calls)} records, not 7")
    cited = {r["entity"]["sha256"]: r for r in calls}
    app = L.appendix(list(cited), now, stores(), tz, records=cited)
    ics = next(r for r in calls if r["activity"]["name"] == "build_ics_201")
    payload = S.read_entity(stores()[0], ics["entity"]["sha256"])
    scenario = S.config()["seed_calls_scenario"]
    return {
        "appendix_seed.txt": app["text"],
        "appendix_seed.md": app["markdown"],
        "appendix_seed.html": app["html"] + "\n",
        f"ics201_labelled_{scenario}.md": L.render_ics201(
            payload, calls, now, stores=stores(), tz=tz
        ),
    }


def label_table() -> str:
    """The RESULT's table: the label of each of the seven tools' seed records."""
    now = S.parse_time(L.config()["fixture_now"])
    tz = L.config()["fixture_time_zone"]
    rows = [
        "| Tool | Class | Governing source | As of | From | Stale | Margin | Record |"
    ]
    rows.append("|---|---|---|---|---|---|---|---|")
    for r in sorted(S.all_records(stores()[0]), key=lambda x: x["activity"]["name"]):
        body = S.read_entity(stores()[0], r["entity"]["sha256"])
        lab = L.label_for(r, now, body)
        as_of = L.when(lab["as_of"], tz, lab["as_of_precision"])
        rows.append(
            f"| `{r['activity']['name']}` | {lab['provenance_class']} | "
            f"{lab['source']} | {as_of} | {lab['as_of_from']} | "
            f"{'stale' if lab['stale'] else 'current'} | "
            f"{len(lab.get('margin', {})) or '-'} | `{lab['hash'][:12]}` |"
        )
    return "\n".join(rows) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--labels", action="store_true")
    args = ap.parse_args(argv)
    if args.labels:
        print(label_table(), end="")
        return 0
    differ = []
    for name, text in renders().items():
        path = OUT / name
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                differ.append(name)
        else:
            OUT.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    if differ:
        print(json.dumps({"differ": differ}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
