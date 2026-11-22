#!/usr/bin/env python3
"""One committed brief per fixture scenario that replays end to end (HB-45 step 8).

    uv run python scripts/build_scenario_briefs.py           # record, build all
    uv run python scripts/build_scenario_briefs.py --check   # rebuild and compare

A scenario replays end to end when no tool cell of it is `not_run` in
`fixtures/scenarios.yaml` (the scenario manifest). For each one:

1. its seven tool calls are recorded into the scenario-brief seed
   (`evidence/seed_briefs/`, `evidence.yaml` `seed_briefs_store_dir`) by
   `scripts/record_tool_call_seed.py`'s `record`, with `allow_errors`: a tool that
   answers a structured error (an unresolved material) is recorded as it answered, so
   the brief shows that section degraded. The tool-call seed's own scenario
   (`seed_calls_scenario`) is held in `evidence/seed_calls/` and is not recorded again;
2. `docs/briefs/<id>/scenario.json` is written from the manifest entry (`id`,
   `incident`, `wind`, `as_given`, and the application blocks `release` and
   `stated_wind` where authored), the CLI's input, as HB-41 wrote the first one;
3. the brief is built by `hazbrief brief ... --replay --now <fixture_now> --no-google`,
   so it is reproducible byte for byte (tests/test_brief.py) and carries no key.

The location scenarios (`fixtures/location_scenarios.yaml`, HB-49), whose location is a
milepost or a crossing, are built and checked the same way. Their calls are recorded by
`scripts/record_location_scenarios.py`, not here: a shape is one footprint call per
sample, which the manifest's one-call-per-tool recorder does not make.

No network (the server replays recorded exchanges), no model. Recording is idempotent: a
call the store holds is not made again, so the store is the checkpoint and a re-run is
the resume (Section 15's rule; seventeen scenarios take about a minute). Prints one line
per scenario: the material, container, the section states and the layers drawn.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib.util
import io
import json
import re
import sys
import tempfile
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from hazbrief.brief import cli  # noqa: E402
from hazbrief.evidence import labels as L  # noqa: E402
from hazbrief.evidence import store as S  # noqa: E402

BRIEFS = REPO / "docs" / "briefs"
SCENARIO_KEYS = (
    "id",
    "incident",
    "wind",
    "as_given",
    "given",
    "not_run",
    "release",
    "stated_wind",
    "fire",
    # HB-139: a scenario file may set the weather source only with a basis (DN-019
    # ADDENDUM-01 section 1; weather_source.select refuses it otherwise)
    "weather",
)
LOCATION_SCENARIOS = REPO / "fixtures" / "location_scenarios.yaml"
#: The fire fixtures (HB-129; DN-021 section 7): each one's fire block by scenario id,
#: and the fire scenarios the server takes no call for (a brush fire has no load).
FIRE_SCENARIOS = REPO / "fixtures" / "scenario_fires.yaml"


def replayable() -> list[dict]:
    doc = yaml.safe_load(
        (REPO / "fixtures" / "scenarios.yaml").read_text(encoding="utf-8")
    )
    return [
        s
        for s in doc["scenarios"]
        if all(c["status"] != "not_run" for c in s["tools"].values())
    ]


def _authored(name: str, key: str) -> dict:
    doc = yaml.safe_load((REPO / "fixtures" / name).read_text(encoding="utf-8"))
    return (doc or {}).get(key) or {}


def location_scenarios() -> list[dict]:
    """The scenarios located by a milepost or a crossing (HB-49), each with its release
    block from `fixtures/scenario_releases.yaml` (HB-69) and its stated_wind block from
    `fixtures/scenario_stated_winds.yaml` (HB-72), as the manifest carries the other
    scenarios'."""
    rel = _authored("scenario_releases.yaml", "releases")
    winds = _authored("scenario_stated_winds.yaml", "stated_winds")
    out = yaml.safe_load(LOCATION_SCENARIOS.read_text(encoding="utf-8"))["scenarios"]
    return [
        {
            **s,
            **({"release": rel[s["id"]]} if s["id"] in rel else {}),
            **({"stated_wind": winds[s["id"]]} if s["id"] in winds else {}),
        }
        for s in out
    ]


def fire_scenarios() -> list[dict]:
    """The fire scenarios outside the manifest (HB-129): every channel `not_run` with
    its reason, so nothing is recorded for them, each with its fire block
    (`fixtures/scenario_fires.yaml`)."""
    fires = _authored("scenario_fires.yaml", "fires")
    doc = yaml.safe_load(FIRE_SCENARIOS.read_text(encoding="utf-8")) or {}
    return [{**s, "fire": fires[s["id"]]} for s in doc.get("scenarios") or []]


def _recorder():
    spec = importlib.util.spec_from_file_location(
        "record_tool_call_seed", REPO / "scripts" / "record_tool_call_seed.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def scenario_json(s: dict) -> str:
    return (
        json.dumps({k: s[k] for k in SCENARIO_KEYS if k in s}, indent=1, sort_keys=True)
        + "\n"
    )


def drawn_layers(page: str) -> list[str]:
    """The ids of the layers the page draws (those with features), from its map data."""
    m = re.search(r'id="map-data">(.*?)</script>', page, re.S)
    data = json.loads(m.group(1).replace("<\\/", "</"))
    return [lay["id"] for lay in data["layers"] if lay["features"]]


def build(out_root: Path, record: bool) -> list[dict]:
    rec = _recorder()
    seed = S.repo_path("seed_store_dir")
    store = S.repo_path("seed_briefs_store_dir")
    own = S.config()["seed_calls_scenario"]
    rows = []
    located = {s["id"] for s in location_scenarios()}
    unrecorded = located | {s["id"] for s in fire_scenarios()}
    for s in replayable() + location_scenarios() + fire_scenarios():
        sid = s["id"]
        counts = {}
        # HB-133: every scenario's calls are the brief's (its one wind record), the
        # tool-call seed's own scenario's too; a call its seed already holds is read
        # there, not recorded twice
        if record and sid not in unrecorded:
            counts = asyncio.run(
                rec.record(
                    store,
                    seed,
                    sid,
                    allow_errors=True,
                    brief=True,
                    held_in=(S.repo_path("seed_calls_store_dir"),)
                    if sid == own
                    else (),
                )
            )
        out = out_root / sid
        out.mkdir(parents=True, exist_ok=True)
        (out / "scenario.json").write_text(scenario_json(s), encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli.main(
                [
                    str(out / "scenario.json"),
                    "--out",
                    str(out),
                    "--replay",
                    "--now",
                    L.config()["fixture_now"],
                    "--no-google",
                ]
            )
        states = {
            ln.split()[0]: ln.split()[1]
            for ln in buf.getvalue().splitlines()[1:]
            if ln.startswith("  ") and len(ln.split()) >= 2
        }
        page = (out / "brief.html").read_text(encoding="utf-8")
        rows.append(
            {
                "id": sid,
                "material": s["incident"].get("material"),
                "container": s["incident"].get("container"),
                "fire": s["incident"].get("fire_involved"),
                "exit": rc,
                "states": states,
                "layers": drawn_layers(page),
                "calls_made": counts.get("calls_made", 0),
                "errors": counts.get("errors", {}),
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="build into a scratch directory without recording, and compare",
    )
    args = ap.parse_args(argv)
    if args.check:
        with tempfile.TemporaryDirectory() as tmp:
            rows = build(Path(tmp), record=False)
            bad = [
                f"{r['id']}/{name}"
                for r in rows
                for name in (
                    "scenario.json",
                    "brief.html",
                    "appendix.html",
                    "appendix.txt",
                    "tevv.html",
                )
                if (Path(tmp) / r["id"] / name).read_bytes()
                != (BRIEFS / r["id"] / name).read_bytes()
            ]
        print("differ:", bad or "none")
        return 1 if bad else 0
    rows = build(BRIEFS, record=True)
    S.write_crate_manifest(S.repo_path("seed_briefs_store_dir"))
    for r in rows:
        print(json.dumps(r, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
