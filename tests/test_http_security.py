"""Regression tests for the outbound request boundary and the recorded exchanges.

The boundary is the template's (no redirects, no environment proxies, a fixed origin,
sanitized errors), now with the origin read from config.py (HB-K1). The recorder tests
cover DN-005 section 2: record writes once and resumes, replay refuses, no key lands in
a file.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from hazbrief import utils


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setattr(utils.settings, "hazbrief_http_mode", "live")


@pytest.mark.parametrize(
    "path",
    [
        "http://169.254.169.254/latest/meta-data",
        "https://localhost/admin",
        "//127.0.0.1/admin",
        "/absolute/path",
        "../admin",
        "datasets/../../admin",
        "%2e%2e/admin",
        "%252e%252e/admin",
        "%2f%2f127.0.0.1/admin",
        "datasets?target=http://127.0.0.1",
        "datasets#fragment",
        "\\\\127.0.0.1\\admin",
        "",
    ],
)
def test_validate_relative_path_rejects_destination_override(path: str) -> None:
    with pytest.raises(ValueError, match="relative API path"):
        utils._validate_relative_path(path)


def test_validate_relative_path_accepts_expected_api_path() -> None:
    assert utils._validate_relative_path("datasets/search") == "datasets/search"


class _FakeClient:
    """Capture client policy while returning a controlled upstream response."""

    init_kwargs: dict[str, Any] = {}
    response = httpx.Response(200, json={"results": []})

    def __init__(self, **kwargs: Any) -> None:
        type(self).init_kwargs = kwargs

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    class _Stream:
        def __init__(self, response: httpx.Response) -> None:
            self.response = response

        async def __aenter__(self) -> httpx.Response:
            return self.response

        async def __aexit__(self, *args: object) -> None:
            return None

    def stream(self, method: str, path: str, **kwargs: Any) -> _Stream:
        self.response.request = httpx.Request(method, f"https://api.weather.gov/{path}")
        return self._Stream(self.response)


async def test_fetch_json_uses_configured_origin_and_safe_client_policy(
    monkeypatch, live
) -> None:
    _FakeClient.response = httpx.Response(200, json={"results": []})
    monkeypatch.setattr(utils.httpx, "AsyncClient", _FakeClient)

    ex = await utils.fetch_json("nws", "datasets", params={"q": "health"})
    assert ex.body == {"results": []} and ex.origin == "live"
    assert _FakeClient.init_kwargs["base_url"] == utils.settings.nws_api_base_url
    assert _FakeClient.init_kwargs["follow_redirects"] is False
    assert _FakeClient.init_kwargs["trust_env"] is False
    assert _FakeClient.init_kwargs["timeout"] == utils.settings.upstream_timeout_seconds


async def test_fetch_json_does_not_send_rejected_path(monkeypatch, live) -> None:
    class UnexpectedClient:
        def __init__(self, **kwargs: Any) -> None:
            raise AssertionError("HTTP client must not be created for rejected input")

    monkeypatch.setattr(utils.httpx, "AsyncClient", UnexpectedClient)

    with pytest.raises(ValueError, match="relative API path"):
        await utils.fetch_json("nws", "http://169.254.169.254/latest/meta-data")


async def test_an_unconfigured_api_name_is_refused() -> None:
    with pytest.raises(KeyError, match="no upstream named"):
        await utils.fetch_json("example", "datasets")


def test_a_response_cannot_steer_the_client_to_another_origin() -> None:
    assert (
        utils.relative_to_origin("nws", "https://api.weather.gov/gridpoints/LWX/1,2")
        == "gridpoints/LWX/1,2"
    )
    for url in (
        "https://evil.example/gridpoints/LWX/1,2",
        "https://api.weather.gov.evil.example/x",
        "http://api.weather.gov/x",
    ):
        with pytest.raises(utils.UpstreamServiceError):
            utils.relative_to_origin("nws", url)


async def test_upstream_error_does_not_expose_sensitive_response(
    monkeypatch, caplog, live
) -> None:
    sensitive = "SSN 123-45-6789 DOB 1940-01-01 token=secret"
    _FakeClient.response = httpx.Response(500, text=sensitive)
    monkeypatch.setattr(utils.httpx, "AsyncClient", _FakeClient)

    with pytest.raises(utils.UpstreamServiceError) as captured:
        await utils.fetch_json("nws", "datasets")

    message = str(captured.value)
    assert message == "Upstream service returned status 500."
    assert sensitive not in message
    assert sensitive not in caplog.text


async def test_invalid_json_is_sanitized(monkeypatch, live) -> None:
    sensitive = "not-json SSN 123-45-6789"
    _FakeClient.response = httpx.Response(200, content=sensitive)
    monkeypatch.setattr(utils.httpx, "AsyncClient", _FakeClient)

    with pytest.raises(utils.UpstreamServiceError) as captured:
        await utils.fetch_json("nws", "datasets")

    assert str(captured.value) == "Upstream service returned invalid JSON."
    assert sensitive not in str(captured.value)


class _CountingClient(_FakeClient):
    calls = 0

    def stream(self, method: str, path: str, **kwargs: Any):
        type(self).calls += 1
        type(self).last_headers = kwargs.get("headers")
        return super().stream(method, path, **kwargs)


@pytest.fixture
def recorder(monkeypatch, tmp_path):
    monkeypatch.setattr(utils.settings, "hazbrief_exchanges_dir", tmp_path)
    monkeypatch.setattr(utils.settings, "hazbrief_http_mode", "record")
    _CountingClient.calls = 0
    _CountingClient.response = httpx.Response(
        200,
        json={"ok": 1},
        headers={"Last-Modified": "Wed, 21 Oct 2026 00:06:12 GMT", "X-Other": "x"},
    )
    monkeypatch.setattr(utils.httpx, "AsyncClient", _CountingClient)
    return tmp_path


async def test_record_writes_once_then_serves_the_file(recorder) -> None:
    first = await utils.fetch_json("nws", "points/1,2", headers={"Accept": "a/b"})
    second = await utils.fetch_json("nws", "points/1,2", headers={"Accept": "a/b"})
    assert _CountingClient.calls == 1  # a re-run resumes; nothing is called twice
    assert (first.origin, second.origin) == ("live", "recorded")
    assert second.body == {"ok": 1}
    assert second.as_of_headers == {"Last-Modified": "Wed, 21 Oct 2026 00:06:12 GMT"}
    files = list((recorder / "nws").glob("*.json"))
    assert len(files) == 1
    record = json.loads(files[0].read_text())
    assert set(record["request_headers"]) == {"User-Agent", "Accept"}
    assert record["request_headers"]["User-Agent"] == utils.settings.user_agent


async def test_replay_refuses_an_unrecorded_exchange(recorder, monkeypatch) -> None:
    monkeypatch.setattr(utils.settings, "hazbrief_http_mode", "replay")
    with pytest.raises(utils.UnrecordedExchangeError, match="points/9,9"):
        await utils.fetch_json("nws", "points/9,9")
    assert _CountingClient.calls == 0


async def test_a_key_parameter_never_reaches_the_file(recorder) -> None:
    ex = await utils.fetch_json("nws", "data", params={"get": "x", "key": "SECRET123"})
    assert "SECRET123" not in ex.url and "key=" not in ex.url
    text = next((recorder / "nws").glob("*.json")).read_text()
    assert "SECRET123" not in text


async def test_a_configured_secret_in_a_response_is_not_recorded(
    recorder, monkeypatch
) -> None:
    monkeypatch.setattr(utils.settings, "census_api_key", "SECRET456")
    _CountingClient.response = httpx.Response(200, json={"echo": "SECRET456"})
    with pytest.raises(RuntimeError, match="refusing to record"):
        await utils.fetch_json("nws", "echo")
    assert not list((recorder / "nws").glob("*.json"))


#: A seeded secret JSON escapes: in the record's text `"` is `\"` and `\` is `\\`, so a
#: substring match on the raw value missed it (review L3-11).
ESCAPING_SECRET = 'SEC"RET\\789'


async def test_a_secret_that_json_escapes_is_still_refused(recorder, monkeypatch):
    monkeypatch.setattr(utils.settings, "census_api_key", ESCAPING_SECRET)
    _CountingClient.response = httpx.Response(200, json={"echo": ESCAPING_SECRET})
    with pytest.raises(RuntimeError, match="refusing to record"):
        await utils.fetch_json("nws", "echo")
    assert not list((recorder / "nws").glob("*.json"))


# ── Binary exchanges (HB-11b: the TIGERweb `export` image) ──────────────────

PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(256))


async def test_a_binary_exchange_records_once_then_serves_the_same_bytes(
    recorder,
) -> None:
    _CountingClient.response = httpx.Response(
        200, content=PNG, headers={"Content-Type": "image/png"}
    )
    first = await utils.fetch_bytes("nws", "export", params={"f": "image"})
    second = await utils.fetch_bytes("nws", "export", params={"f": "image"})
    assert _CountingClient.calls == 1
    assert (first.origin, second.origin) == ("live", "recorded")
    assert first.body == second.body == PNG
    assert second.content_type == "image/png"
    record = json.loads(next((recorder / "nws").glob("*.json")).read_text())
    assert record["body_encoding"] == "base64"
    assert record["content_type"] == "image/png"


async def test_a_binary_exchange_of_another_type_is_refused(recorder) -> None:
    """ArcGIS answers a failed export with a JSON error object and HTTP 200."""
    _CountingClient.response = httpx.Response(
        200, json={"error": {"code": 400}}, headers={"Content-Type": "application/json"}
    )
    with pytest.raises(utils.UpstreamServiceError, match="not an accepted type"):
        await utils.fetch_bytes("nws", "export", params={"f": "image"})
    assert not list((recorder / "nws").glob("*.json"))


async def test_replay_refuses_an_unrecorded_binary_exchange(
    recorder, monkeypatch
) -> None:
    monkeypatch.setattr(utils.settings, "hazbrief_http_mode", "replay")
    with pytest.raises(utils.UnrecordedExchangeError, match="export"):
        await utils.fetch_bytes("nws", "export", params={"f": "image"})
    assert _CountingClient.calls == 0


async def test_fetch_json_refuses_a_binary_exchange_file(recorder) -> None:
    _CountingClient.response = httpx.Response(
        200, content=PNG, headers={"Content-Type": "image/png"}
    )
    await utils.fetch_bytes("nws", "export", params={"f": "image"})
    with pytest.raises(RuntimeError, match="unusable"):
        await utils.fetch_json("nws", "export", params={"f": "image"})


# ── Range exchanges (HB-59 ADDENDUM-03: the land-cover COG read by HTTP range) ───────

TIFF = bytes(range(256)) * 4


def _partial(start: int, end: int, total: int = 4096, status: int = 206):
    return httpx.Response(
        status,
        content=TIFF[start : end + 1],
        headers={
            "Content-Type": "image/tiff",
            "Content-Range": f"bytes {start}-{end}/{total}",
            "Last-Modified": "Fri, 31 Jul 2026 02:51:33 GMT",
        },
    )


async def test_a_range_read_records_once_per_range_and_replays_its_bytes(
    recorder, monkeypatch
) -> None:
    _CountingClient.response = _partial(0, 15)
    first = await utils.fetch_range("nws", "nlcd/x.tif", 0, 15)
    again = await utils.fetch_range("nws", "nlcd/x.tif", 0, 15)
    assert _CountingClient.calls == 1
    assert _CountingClient.last_headers["Range"] == "bytes=0-15"
    assert (first.origin, again.origin) == ("live", "recorded")
    assert first.body == again.body == TIFF[:16]
    _CountingClient.response = _partial(16, 31)
    other = await utils.fetch_range("nws", "nlcd/x.tif", 16, 31)
    assert other.body == TIFF[16:32] and _CountingClient.calls == 2
    files = list((recorder / "nws").glob("*.json"))
    assert len(files) == 2  # one file per range of the same url
    records = [json.loads(f.read_text()) for f in files]
    assert {r["request_headers"]["Range"] for r in records} == {
        "bytes=0-15",
        "bytes=16-31",
    }
    monkeypatch.setattr(utils.settings, "hazbrief_http_mode", "replay")
    assert (await utils.fetch_range("nws", "nlcd/x.tif", 16, 31)).body == TIFF[16:32]
    with pytest.raises(utils.UnrecordedExchangeError, match="bytes=32-47"):
        await utils.fetch_range("nws", "nlcd/x.tif", 32, 47)


@pytest.mark.parametrize(
    "response",
    [
        # The server ignored Range and sent the whole object.
        httpx.Response(200, content=TIFF[:16], headers={"Content-Type": "image/tiff"}),
        # A partial answer for other bytes than those asked.
        _partial(16, 31),
        # A partial answer whose body is shorter than its Content-Range says.
        httpx.Response(
            206,
            content=TIFF[:8],
            headers={"Content-Type": "image/tiff", "Content-Range": "bytes 0-15/4096"},
        ),
    ],
    ids=["status-200", "other-range", "short-body"],
)
async def test_a_range_answer_that_is_not_the_bytes_asked_is_refused(
    recorder, response
) -> None:
    _CountingClient.response = response
    with pytest.raises(utils.UpstreamServiceError, match="range"):
        await utils.fetch_range("nws", "nlcd/x.tif", 0, 15)
    assert not list((recorder / "nws").glob("*.json"))


# Seeded tests for three guards that shipped without one (review L3-3, L4-18).


async def test_a_streamed_body_over_the_size_cap_stops_while_streaming(
    monkeypatch, live
) -> None:
    """SECURITY.md section 2: the size cap is enforced while streaming, so a refactor
    that read the whole body before checking its length fails here."""
    cap, chunk = 100, b"x" * 40
    sent: list[int] = []

    async def body():
        for i in range(10):
            sent.append(i)
            yield chunk

    monkeypatch.setattr(utils.settings, "upstream_max_response_bytes", cap)
    _FakeClient.response = httpx.Response(200, content=body())
    monkeypatch.setattr(utils.httpx, "AsyncClient", _FakeClient)
    with pytest.raises(utils.UpstreamServiceError) as exc:
        await utils.fetch_json("nws", "datasets")
    assert str(exc.value) == "Upstream response exceeded the size limit."
    assert len(sent) == 3  # 120 bytes read, over the cap; the other seven never


async def test_a_read_timeout_is_an_upstream_timeout_error(monkeypatch, live) -> None:
    class TimingOut(_FakeClient):
        def stream(self, method: str, path: str, **kwargs: Any):
            raise httpx.ReadTimeout("read timed out")

    monkeypatch.setattr(utils.httpx, "AsyncClient", TimingOut)
    with pytest.raises(utils.UpstreamTimeoutError) as exc:
        await utils.fetch_json("nws", "datasets")
    assert str(exc.value) == "Upstream service request failed."


def test_a_recorded_exchange_of_another_url_is_refused(tmp_path) -> None:
    """A fixture file whose url is not the one its name was keyed on is a defect that
    stops the call, naming the file (`_read_exchange`)."""
    path = tmp_path / "x.json"
    record = {
        "api": "nws",
        "method": "GET",
        "url": "https://api.weather.gov/points/1,1",
        "status": 200,
        "response_headers": {},
        "body": {},
        "recorded_at": "2026-10-21T00:00:00Z",
        "request_headers": {},
    }
    path.write_text(json.dumps(record), encoding="utf-8")
    ok = utils._read_exchange(path, "nws", record["url"])
    assert ok.url == record["url"] and ok.origin == "recorded"
    with pytest.raises(RuntimeError, match=r"x\.json is unusable: records nws"):
        utils._read_exchange(path, "nws", "https://api.weather.gov/points/2,2")
    with pytest.raises(RuntimeError, match="unusable"):
        utils._read_exchange(path, "census", record["url"])


# NWS: a malformed grid is an UpstreamServiceError, and its message carries no upstream
# value (review L2-13, L3-4; docs/SECURITY.md section 2).

#: A seeded upstream value: a message that quoted it would show this marker.
UPSTREAM_MARK = "UPSTREAM<x>MARK"


def test_an_nws_grid_value_without_valid_time_is_an_upstream_error() -> None:
    """The one NWS shape failure that escaped as KeyError (review L2-13)."""
    from datetime import datetime, timezone

    from hazbrief import nws

    when = datetime(2026, 10, 21, 18, tzinfo=timezone.utc)
    for layer in ({"values": [{"value": 5}]}, {"values": ["not a value"]}):
        with pytest.raises(utils.UpstreamServiceError, match="validTime"):
            nws.value_at(layer, when, "wind speed")


@pytest.mark.parametrize(
    "valid_time",
    [f"{UPSTREAM_MARK}/PT1H", f"2026-10-21T03:00:00+00:00/{UPSTREAM_MARK}"],
    ids=["not-an-interval", "not-readable"],
)
def test_an_nws_interval_error_names_the_field_not_its_value(valid_time) -> None:
    from hazbrief import nws

    with pytest.raises(utils.UpstreamServiceError) as exc:
        nws.parse_interval(valid_time)
    assert "validTime" in str(exc.value)
    assert UPSTREAM_MARK not in str(exc.value)


@pytest.mark.parametrize("layer", ["windSpeed", "windDirection"])
async def test_an_nws_unit_error_names_the_field_not_its_value(
    monkeypatch, layer
) -> None:
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from hazbrief import nws

    grid = {
        "windSpeed": {"uom": "wmoUnit:km_h-1", "values": []},
        "windDirection": {"uom": nws.DIRECTION_UOM, "values": []},
    }
    grid[layer]["uom"] = UPSTREAM_MARK
    base = utils.settings.upstream_base_url("nws")

    async def fake(api, path, params=None, headers=None):
        if path.startswith("points/"):
            props = {"forecastGridData": f"{base}gridpoints/LWX/1,1"}
            return SimpleNamespace(url=path, body={"properties": props})
        return SimpleNamespace(url=path, body={"properties": grid})

    monkeypatch.setattr(nws, "fetch_json", fake)
    with pytest.raises(utils.UpstreamServiceError) as exc:
        await nws.wind_at(39.7, -77.7, datetime(2026, 10, 21, tzinfo=timezone.utc))
    assert layer in str(exc.value)
    assert UPSTREAM_MARK not in str(exc.value)


# ── a declared status is an answer (HB-119) ───────────────────────────────────────────
# PubChem PUG REST answers a name it does not know with 404 and a JSON Fault
# (PUGREST.NotFound): the source's statement that it holds no such record (RFC 9110
# section 15.5.5), which the materials resolver records and replays like any answer.


async def test_a_declared_status_is_recorded_and_replayed(
    recorder, monkeypatch
) -> None:
    _CountingClient.response = httpx.Response(
        404, json={"Fault": {"Code": "PUGREST.NotFound"}}
    )
    first = await utils.fetch_json("nws", "name/x", answers=(404,))
    assert (first.status, first.origin) == (404, "live")
    assert first.body == {"Fault": {"Code": "PUGREST.NotFound"}}
    monkeypatch.setattr(utils.settings, "hazbrief_http_mode", "replay")
    again = await utils.fetch_json("nws", "name/x", answers=(404,))
    assert (again.status, again.origin, again.body) == (404, "recorded", first.body)
    assert _CountingClient.calls == 1


async def test_an_undeclared_error_status_still_raises_and_records_nothing(
    recorder,
) -> None:
    _CountingClient.response = httpx.Response(404, json={"Fault": {}})
    with pytest.raises(utils.UpstreamStatusError) as captured:
        await utils.fetch_json("nws", "name/y")
    assert captured.value.status == 404
    assert not list((recorder / "nws").glob("*.json"))
    _CountingClient.response = httpx.Response(503, json={"Fault": {}})
    with pytest.raises(utils.UpstreamStatusError):
        await utils.fetch_json("nws", "name/z", answers=(404,))
    assert not list((recorder / "nws").glob("*.json"))
