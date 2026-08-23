from __future__ import annotations

import httpx


class UpstreamResponseTooLarge(ValueError):
    pass


def read_bounded_response(response: httpx.Response, *, max_bytes: int) -> bytes:
    """Read an identity-encoded response body up to a strict ceiling.

    Callers request identity encoding and this function rejects an upstream
    that ignores it. Counting raw chunks avoids allocating an attacker-chosen
    decompressed chunk before the bound can be checked. A valid Content-Length
    over the ceiling is rejected before consuming the stream.
    """

    content_encoding = response.headers.get("Content-Encoding", "identity").strip().lower()
    if content_encoding != "identity":
        raise UpstreamResponseTooLarge("Encoded upstream responses are not accepted.")

    declared = response.headers.get("Content-Length")
    if declared is not None:
        try:
            declared_bytes = int(declared)
        except ValueError as exc:
            raise UpstreamResponseTooLarge("Upstream Content-Length is invalid.") from exc
        if declared_bytes < 0 or declared_bytes > max_bytes:
            raise UpstreamResponseTooLarge("Upstream response exceeds the byte limit.")

    if response.is_stream_consumed:
        content = response.content
        if len(content) > max_bytes:
            raise UpstreamResponseTooLarge("Upstream response exceeds the byte limit.")
        return content

    body = bytearray()
    for chunk in response.iter_raw():
        if len(body) + len(chunk) > max_bytes:
            raise UpstreamResponseTooLarge("Upstream response exceeds the byte limit.")
        body.extend(chunk)
    return bytes(body)


def buffer_bounded_response(response: httpx.Response, *, max_bytes: int) -> httpx.Response:
    """Create a bounded in-memory response for generated-client parsing."""

    content = read_bounded_response(response, max_bytes=max_bytes)
    headers = {
        key: value
        for key, value in response.headers.items()
        if key.lower() not in {"content-encoding", "content-length", "transfer-encoding"}
    }
    return httpx.Response(
        status_code=response.status_code,
        headers=headers,
        content=content,
        request=response.request,
    )
