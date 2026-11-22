"""HB-15 step 5: promoting a live recording into the replay fixtures copies it byte for
byte only when it is what its file name says, and never replaces a recording."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import promote_live_exchanges as P  # noqa: E402

from hazbrief.utils import exchange_key  # noqa: E402

URL = "https://example.invalid/query?geometry=1%2C2&f=json"


def _live(tmp_path: Path, api="tigerweb", url=URL, filed_as=None) -> tuple[Path, str]:
    key = exchange_key("GET", url)
    rec = {
        "api": api,
        "method": "GET",
        "url": url,
        "status": 200,
        "body": {"x": 1},
        "response_headers": {"ETag": '"1"'},
        "recorded_at": "2026-10-22T03:15:07Z",
    }
    d = tmp_path / "live" / (filed_as or api)
    d.mkdir(parents=True)
    (d / f"{key}.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
    return tmp_path / "live", key


def test_a_verified_file_is_copied_byte_for_byte(tmp_path):
    live, key = _live(tmp_path)
    dest = tmp_path / "exchanges"
    assert P.promote_one(live, dest, "tigerweb", key)
    src = (live / "tigerweb" / f"{key}.json").read_bytes()
    assert (dest / "tigerweb" / f"{key}.json").read_bytes() == src
    assert P.promote_one(live, dest, "tigerweb", key)  # already there: a no-op


def test_a_file_the_live_directory_lacks_is_reported_not_raised(tmp_path):
    live, _ = _live(tmp_path)
    assert not P.promote_one(live, tmp_path / "x", "tigerweb", "0" * 64)


def test_a_file_filed_under_another_api_is_refused(tmp_path):
    live, key = _live(tmp_path, api="census", filed_as="tigerweb")
    with pytest.raises(P.PromotionError, match="records api"):
        P.promote_one(live, tmp_path / "x", "tigerweb", key)


def test_a_file_whose_url_is_not_its_name_is_refused(tmp_path):
    live, key = _live(tmp_path)
    (live / "tigerweb" / f"{key}.json").rename(live / "tigerweb" / f"{'a' * 64}.json")
    with pytest.raises(P.PromotionError, match="hash"):
        P.promote_one(live, tmp_path / "x", "tigerweb", "a" * 64)


def test_a_recording_is_never_replaced(tmp_path):
    live, key = _live(tmp_path)
    dest = tmp_path / "exchanges" / "tigerweb"
    dest.mkdir(parents=True)
    (dest / f"{key}.json").write_text("{}", encoding="utf-8")
    with pytest.raises(P.PromotionError, match="other bytes"):
        P.promote_one(live, tmp_path / "exchanges", "tigerweb", key)
