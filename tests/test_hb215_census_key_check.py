"""HB-215 ADDENDUM-02 item 2 (Issue 89d222a4): PREFLIGHT's Census key check makes one
real data request and reads the answer, so a placeholder fails it. HB-209's check
(`test -n "$CENSUS_API_KEY"`) printed "set" for the literal `<key>` the operator found
in his file.

No network: the request goes through `census.fetch_json`, stubbed here."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from hazbrief import census
from hazbrief.config import settings
from hazbrief.utils import UpstreamServiceError

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "census_key_check.py"
PREFLIGHT = REPO / "docs" / "submission" / "demo" / "PREFLIGHT.md"


def _check():
    spec = importlib.util.spec_from_file_location("census_key_check", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Ex:
    def __init__(self, body):
        self.body = body


def _stub(monkeypatch, answer):
    calls = []

    async def fake(api, path, params=None, **_k):
        calls.append((api, path, dict(params or {})))
        if isinstance(answer, Exception):
            raise answer
        return _Ex(answer)

    monkeypatch.setattr(census, "fetch_json", fake)
    return calls


@pytest.mark.parametrize("value", ["<key>", "<your key>", "", "   "])
def test_a_placeholder_or_empty_key_fails_without_a_request(monkeypatch, capsys, value):
    monkeypatch.setattr(settings, "census_api_key", value)
    calls = _stub(monkeypatch, [["P1_001N", "state", "county"], ["1", "24", "021"]])
    assert _check().main([]) == 1
    assert calls == []
    assert capsys.readouterr().out.startswith("key not usable")


def test_a_refused_key_fails_on_the_answer(monkeypatch, capsys):
    """A key that is not a placeholder but that the API refuses (its "Missing Key" or
    "Invalid Key" page, not a table) fails on the answer the request reads."""
    monkeypatch.setattr(settings, "census_api_key", "0" * 40)
    calls = _stub(
        monkeypatch, UpstreamServiceError("Census Data API returned no table.")
    )
    assert _check().main([]) == 1
    assert len(calls) == 1
    assert capsys.readouterr().out.startswith("key refused")


def test_a_table_answer_passes_and_the_key_is_never_printed(monkeypatch, capsys):
    key = "a" * 40
    monkeypatch.setattr(settings, "census_api_key", key)
    calls = _stub(
        monkeypatch, [["P1_001N", "state", "county"], ["271717", "24", "021"]]
    )
    assert _check().main([]) == 0
    out = capsys.readouterr().out
    assert out.startswith("key works")
    assert key not in out
    (api, path, params) = calls[0]
    assert api == "census" and path == census.sources()["dhc"]["dataset"]
    assert params["key"] == key


def test_preflight_runs_the_request_not_a_presence_test():
    text = PREFLIGHT.read_text(encoding="utf-8")
    assert "scripts/census_key_check.py" in text
    assert 'test -n "$CENSUS_API_KEY"' not in text
