"""Loopback host for the deployment-owned Routing WSGI application.

The test process imports the exact deployment target.  Its dependency factory is
selected by ``ROUTING_PRODUCTION_DEPENDENCIES_FACTORY`` before Django constructs
the application; this module never replaces the container, view, or use case.
"""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
from typing import Any, Callable, Iterable
from wsgiref.simple_server import WSGIRequestHandler, make_server


class QuietHandler(WSGIRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return None


class RecordingWsgiApplication:
    """Record the private wire without changing the application under test."""

    def __init__(self, application: Callable[..., Iterable[bytes]], path: Path) -> None:
        self._application = application
        self._path = path

    def __call__(self, environ: dict[str, Any], start_response: Callable[..., Any]):
        content_length = int(environ.get("CONTENT_LENGTH") or 0)
        request_body = environ["wsgi.input"].read(content_length)
        environ["wsgi.input"] = io.BytesIO(request_body)
        captured_status: list[str] = []
        captured_headers: list[list[tuple[str, str]]] = []

        def capture(status: str, headers: list[tuple[str, str]], exc_info=None):
            captured_status.append(status)
            captured_headers.append(headers)
            return start_response(status, headers, exc_info)

        chunks = list(self._application(environ, capture))
        if environ.get("PATH_INFO") == "/v1/routes/optimize":
            response_body = b"".join(chunks)
            record = {
                "authorizationPresent": bool(environ.get("HTTP_AUTHORIZATION")),
                "correlationId": environ.get("HTTP_X_CORRELATION_ID"),
                "deadline": environ.get("HTTP_X_REQUEST_DEADLINE"),
                "idempotencyKey": environ.get("HTTP_IDEMPOTENCY_KEY"),
                "request": _json_or_none(request_body),
                "responseStatus": int(captured_status[0].split(" ", 1)[0]),
                "response": _json_or_none(response_body),
            }
            with self._path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, sort_keys=True) + "\n")
        return chunks


def _json_or_none(value: bytes) -> object | None:
    try:
        return json.loads(value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--record", type=Path, required=True)
    arguments = parser.parse_args()
    arguments.record.parent.mkdir(parents=True, exist_ok=True)
    arguments.record.write_text("", encoding="utf-8")

    # Import is intentionally inside main: deployment.wsgi must see the factory
    # environment before application/container construction begins.
    from routing_deployment.wsgi import application

    wrapped = RecordingWsgiApplication(application, arguments.record)
    with make_server(
        "127.0.0.1",
        arguments.port,
        wrapped,
        handler_class=QuietHandler,
    ) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
