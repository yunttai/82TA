"""Small exact-host CONNECT proxy for the local Routing live-E2E profile.

The proxy never receives Provider HTTP paths, headers, credentials, or bodies: it
only establishes a TLS tunnel to one of the explicitly configured hostnames on 443.
It emits no access logs and rejects private/special DNS answers.
"""

from __future__ import annotations

import ipaddress
import os
import select
import socket
import socketserver
import sys
import time


_MAXIMUM_HEADER_BYTES = 4_096
_MAXIMUM_TUNNEL_BYTES = 4_000_000
_TUNNEL_SECONDS = 15.0


def _allowed_hosts() -> frozenset[str]:
    raw = os.environ.get(
        "PROVIDER_EGRESS_ALLOWLIST",
        "dapi.kakao.com,apis-navi.kakaomobility.com",
    )
    values = tuple(item.strip().lower() for item in raw.split(",") if item.strip())
    if not values or len(values) != len(set(values)):
        raise SystemExit("Provider egress allowlist is invalid")
    for value in values:
        if (
            len(value) > 253
            or value.startswith(".")
            or value.endswith(".")
            or any(
                not label
                or len(label) > 63
                or label.startswith("-")
                or label.endswith("-")
                or not all(character.isascii() and (character.isalnum() or character == "-") for character in label)
                for label in value.split(".")
            )
        ):
            raise SystemExit("Provider egress allowlist is invalid")
    return frozenset(values)


def _global_addresses(hostname: str) -> tuple[str, ...]:
    records = socket.getaddrinfo(
        hostname,
        443,
        family=socket.AF_UNSPEC,
        type=socket.SOCK_STREAM,
        proto=socket.IPPROTO_TCP,
    )
    addresses = tuple(dict.fromkeys(record[4][0] for record in records))
    if not addresses:
        raise OSError("empty DNS response")
    if any(not ipaddress.ip_address(value).is_global for value in addresses):
        raise OSError("non-global DNS response")
    return addresses


def _read_header(connection: socket.socket) -> bytes:
    value = bytearray()
    while b"\r\n\r\n" not in value:
        remaining = _MAXIMUM_HEADER_BYTES + 1 - len(value)
        if remaining <= 0:
            raise ValueError("oversized proxy request")
        chunk = connection.recv(min(1_024, remaining))
        if not chunk:
            raise ValueError("incomplete proxy request")
        value.extend(chunk)
    header, separator, trailing = bytes(value).partition(b"\r\n\r\n")
    if not separator or trailing:
        raise ValueError("malformed proxy request")
    return header


def _parse_connect(header: bytes, allowed: frozenset[str]) -> str:
    try:
        lines = header.decode("ascii", "strict").split("\r\n")
    except UnicodeDecodeError:
        raise ValueError("non-ASCII proxy request") from None
    fields = lines[0].split(" ")
    if len(fields) != 3 or fields[0] != "CONNECT" or fields[2] != "HTTP/1.1":
        raise ValueError("CONNECT is required")
    authority = fields[1]
    hostname, separator, port = authority.rpartition(":")
    if separator != ":" or port != "443" or hostname.lower() not in allowed:
        raise PermissionError("CONNECT target is not allowlisted")
    parsed_headers: dict[str, str] = {}
    for line in lines[1:]:
        name, separator, value = line.partition(":")
        normalized = name.strip().lower()
        if (
            separator != ":"
            or not normalized
            or normalized in parsed_headers
            or "\r" in value
            or "\n" in value
        ):
            raise ValueError("malformed proxy header")
        parsed_headers[normalized] = value.strip()
    if parsed_headers.get("host", "").lower() != authority.lower():
        raise ValueError("CONNECT Host mismatch")
    if any(name in parsed_headers for name in ("proxy-authorization", "content-length", "transfer-encoding")):
        raise ValueError("forbidden proxy header")
    return hostname.lower()


def _connect_upstream(hostname: str) -> socket.socket:
    last_error: OSError | None = None
    for address in _global_addresses(hostname):
        try:
            return socket.create_connection((address, 443), timeout=5.0)
        except OSError as exc:
            last_error = exc
    raise last_error or OSError("Provider connection failed")


def _tunnel(client: socket.socket, upstream: socket.socket) -> None:
    deadline = time.monotonic() + _TUNNEL_SECONDS
    transferred = {client: 0, upstream: 0}
    sockets = (client, upstream)
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        ready, _, _ = select.select(sockets, (), (), min(1.0, remaining))
        if not ready:
            continue
        for source in ready:
            chunk = source.recv(65_536)
            if not chunk:
                return
            transferred[source] += len(chunk)
            if transferred[source] > _MAXIMUM_TUNNEL_BYTES:
                return
            destination = upstream if source is client else client
            destination.sendall(chunk)


class _ConnectHandler(socketserver.BaseRequestHandler):
    allowed_hosts: frozenset[str] = frozenset()

    def handle(self) -> None:
        client = self.request
        client.settimeout(5.0)
        upstream: socket.socket | None = None
        try:
            hostname = _parse_connect(_read_header(client), self.allowed_hosts)
            upstream = _connect_upstream(hostname)
            client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            _tunnel(client, upstream)
        except PermissionError:
            self._reject(403)
        except (OSError, ValueError):
            self._reject(400)
        finally:
            if upstream is not None:
                upstream.close()

    def _reject(self, status: int) -> None:
        try:
            self.request.sendall(
                f"HTTP/1.1 {status} Rejected\r\nConnection: close\r\nContent-Length: 0\r\n\r\n".encode("ascii")
            )
        except OSError:
            pass


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def _healthcheck() -> int:
    host = os.environ.get("PROVIDER_EGRESS_LISTEN_HOST", "0.0.0.0")
    target = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    port = int(os.environ.get("PROVIDER_EGRESS_LISTEN_PORT", "3128"))
    try:
        with socket.create_connection((target, port), timeout=1.0):
            return 0
    except OSError:
        return 1


def main() -> int:
    if sys.argv[1:] == ["--healthcheck"]:
        return _healthcheck()
    if sys.argv[1:]:
        raise SystemExit("unsupported Provider egress proxy argument")
    host = os.environ.get("PROVIDER_EGRESS_LISTEN_HOST", "0.0.0.0")
    port = int(os.environ.get("PROVIDER_EGRESS_LISTEN_PORT", "3128"))
    if not 1 <= port <= 65_535:
        raise SystemExit("Provider egress listen port is invalid")
    _ConnectHandler.allowed_hosts = _allowed_hosts()
    with _Server((host, port), _ConnectHandler) as server:
        server.serve_forever(poll_interval=0.5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
