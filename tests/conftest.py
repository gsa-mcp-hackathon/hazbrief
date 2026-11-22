"""Suite-wide settings: upstream calls replay recorded exchanges (DN-005 section 2), and
no test holds the machine's real model lock (HB-33).

HAZBRIEF_HTTP_MODE is set before any test imports `hazbrief.config`, whose settings are
read once at import. An exported HAZBRIEF_HTTP_MODE still wins, so a deliberate live run
is possible; nothing in the suite needs one.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

os.environ.setdefault("HAZBRIEF_HTTP_MODE", "replay")

#: seldon's model home, beside this checkout: the registry and the lock.
SELDON_MODELS = Path(__file__).resolve().parents[2] / "seldon" / "models"


@pytest.fixture(scope="session", autouse=True)
def _isolated_seldon_models_home(tmp_path_factory):
    """HB-33: a test that drives the kit under Squiddy's interpreter reads seldon's
    model registry and lock (`pin_cli`), and a hold taken there would land in the
    machine's `refresh.holds_dir`, deferring a real refresh and colliding with a real
    run of the same name. (HB-33's own holder, `model_hold.py`, was retired
    by HB-71 with the drivers that took it.) Every test, and every subprocess it starts
    with this environment, reads a copy instead: the real registry and lock, holds under
    a temporary directory, no dispatcher holders, refresh never automatic. Seldon's own
    suite does the same (`seldon/tests/conftest.py`, `models_fixture.py`). Where
    seldon is not checked out (CI), nothing can take a hold and nothing is set."""
    registry = SELDON_MODELS / "registry.yaml"
    if not registry.is_file() or "SELDON_MODELS_HOME" in os.environ:
        yield
        return
    root = tmp_path_factory.mktemp("seldon_models")
    home = root / "models"
    home.mkdir()
    reg = yaml.safe_load(registry.read_text(encoding="utf-8"))
    reg["refresh"].update(
        auto_on_register=False,
        auto_on_dispatch=False,
        holders=[],
        holds_dir=str(root / "model-holds"),
    )
    (home / "registry.yaml").write_text(
        yaml.safe_dump(reg, sort_keys=False), encoding="utf-8"
    )
    lock = SELDON_MODELS / "models.lock.yaml"
    if lock.is_file():
        (home / lock.name).write_bytes(lock.read_bytes())
    os.environ["SELDON_MODELS_HOME"] = str(home)
    try:
        yield
    finally:
        del os.environ["SELDON_MODELS_HOME"]


#: The value a replay run holds where no Census key resolves; the modules that supplied
#: their own (`test_population_at_risk.a_key` and five more) use the same string.
REPLAY_CENSUS_KEY = "replay-placeholder"


@pytest.fixture(scope="session", autouse=True)
def _replay_census_key():
    """HB-78: replay needs no real Census key, but the Census-backed code refuses to run
    without one, exactly as live (`census.api_key`, DN-003 section 1); the recorded urls
    carry none (`utils.SECRET_QUERY_PARAMS`). A machine with a key (environment,
    `.env`, master file) keeps it, so a local run is unchanged; a CI runner, which has
    none, gets the placeholder that six modules already supplied for themselves. A live
    run with no key is left to fail on the missing key, never to send a placeholder
    upstream. Session scope, because module fixtures (`test_brief_map`,
    `test_brief_union`) build their brief before any function fixture runs; a test that
    blanks the key with its own monkeypatch gets the placeholder back when it ends."""
    from hazbrief.config import settings

    with pytest.MonkeyPatch.context() as mp:
        if settings.hazbrief_http_mode == "replay" and not settings.census_api_key:
            mp.setattr(settings, "census_api_key", REPLAY_CENSUS_KEY)
        yield


@pytest.fixture(autouse=True)
def _isolated_spend_ledger(tmp_path, monkeypatch):
    """HB-64: since squiddy SQ-086R a driver's run declares itself on the kit's spend
    ledger before its first job (`kit_run.Run`, `spend.declare_run`).
    Every test, and every subprocess it starts with this environment, writes a temporary
    ledger, never the machine's (`~/.squiddy/spend/ledger.jsonl`, squiddy/spend.yaml
    `ledger`), which the kit reads to price and band every real run. A test that sets
    its own ledger in a child's environment keeps it."""
    monkeypatch.setenv("SQUIDDY_SPEND_LEDGER", str(tmp_path / "spend_ledger.jsonl"))


#: HB-147: the operator's acquisition queue page, regenerated on every gate.
QUEUE_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "acquisition_queue.py"
#: HB-213: the Seldon configuration, present only where the working record is
WORKING_RECORD = Path(__file__).resolve().parents[1] / "seldon"


def pytest_sessionstart(session):
    """HB-147: the gate (`seldon` dispatch.gate_command, a pytest run over tests/)
    regenerates docs/evidence/acquisition/queue.html from corpus/sources.yaml, so the
    page the operator opens is the manifest's queue as of the last gate. The render is
    byte-identical for identical inputs, so a gate that changed no queued row moves no
    tracked file. A collect-only run and an xdist worker render nothing (the controller
    renders once). A manifest the renderer refuses stops the session with the reason
    (engineering standards section 4)."""
    config = session.config
    if config.option.collectonly or hasattr(config, "workerinput"):
        return
    # HB-213: the queue is the working record's (Seldon's acquisition workflow, reading
    # the corpus graph's intake); the public package carries neither, so where this
    # repository's Seldon configuration is absent there is no queue to regenerate. The
    # private repository always has it, so the gate still renders the page there.
    if not WORKING_RECORD.is_file():
        return
    import importlib.util

    spec = importlib.util.spec_from_file_location("acquisition_queue", QUEUE_SCRIPT)
    aq = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(aq)
    aq.write_page()


#: HB-194: the mark the gate's second step selects (`seldon` gate_command).
LOAD_SENSITIVE = "load_sensitive"


def _requires_mark(markexpr: str, mark: str) -> bool:
    """Whether every test `-m markexpr` selects must carry `mark`: the expression is a
    plain conjunction (no `or`, no parentheses) with `mark` as one of its terms. Any
    other expression answers False, so its run collects every module."""
    if not markexpr or "(" in markexpr or " or " in f" {markexpr} ":
        return False
    return mark in (t.strip() for t in markexpr.split(" and "))


def pytest_ignore_collect(collection_path, config):
    """HB-194: a run that selects only `load_sensitive` tests (the gate's second step)
    does not collect a test module that never names the mark: it holds no test the run
    could select. A module-level skip in such a module (`test_slabx_reproduces_slab`'s
    `importorskip`) would otherwise count as skipped in both steps, and the two steps'
    tails would not add up to the one-step gate's (`test_evaluation_document.py`
    `two_step_tail`). It also spares the step collecting 160 modules for 33."""
    if collection_path.suffix != ".py" or not collection_path.name.startswith("test_"):
        return None
    if not _requires_mark(config.getoption("markexpr") or "", LOAD_SENSITIVE):
        return None
    text = collection_path.read_text(encoding="utf-8")
    return True if f"pytest.mark.{LOAD_SENSITIVE}" not in text else None


# HB-164: a parallel gate keeps its `deselected` count (tests/xdist_deselected.py).
from tests.xdist_deselected import pytest_deselected, pytest_testnodedown  # noqa: E402,F401
