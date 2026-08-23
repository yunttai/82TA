from __future__ import annotations

import json

import pytest

from provider_core.canonical import Coordinate
from routing_api.provider_probe import ProviderProbeError, probe_kakao_mobility_directions


class FakeResponse:
    def __init__(self, body, *, status=200, content_type="application/json") -> None:
        self.status = status
        self._body = body
        self._content_type = content_type
        self.closed = False

    def getheader(self, name, default=None):
        if name == "Content-Type":
            return self._content_type
        if name == "Content-Length":
            return str(len(self._body))
        return default

    def read(self, amount=-1):
        return self._body[:amount]

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, response) -> None:
        self.response = response
        self.request_values = None
        self.closed = False

    def request(self, method, target, headers=None):
        self.request_values = (method, target, headers)

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


def _factory(connection):
    return lambda *args, **kwargs: connection


def test_probe_uses_fixed_endpoint_and_never_returns_raw_secret() -> None:
    body = json.dumps(
        {"trans_id": "valid-id", "routes": []}, separators=(",", ":")
    ).encode()
    connection = FakeConnection(FakeResponse(body))
    secret = "probe-secret-must-not-render"

    result = probe_kakao_mobility_directions(
        Coordinate(127.1, 37.3),
        Coordinate(127.2, 37.4),
        secret,
        connection_factory=_factory(connection),
    )

    assert result == ()
    method, target, headers = connection.request_values
    assert method == "GET"
    assert target.startswith("/v1/directions?")
    assert "apis-navi" not in target
    assert headers["Authorization"] == f"KakaoAK {secret}"
    assert secret not in repr(result)
    assert connection.closed and connection.response.closed


def test_probe_rejects_redirect_non_json_and_missing_key_without_raw_body() -> None:
    for response in (
        FakeResponse(b"{}", status=302),
        FakeResponse(b"<html>bad</html>", content_type="text/html"),
    ):
        connection = FakeConnection(response)
        with pytest.raises(ProviderProbeError):
            probe_kakao_mobility_directions(
                Coordinate(127.1, 37.3),
                Coordinate(127.2, 37.4),
                "configured-secret",
                connection_factory=_factory(connection),
            )
        assert connection.closed

    with pytest.raises(ProviderProbeError, match="not configured"):
        probe_kakao_mobility_directions(
            Coordinate(127.1, 37.3), Coordinate(127.2, 37.4), ""
        )
