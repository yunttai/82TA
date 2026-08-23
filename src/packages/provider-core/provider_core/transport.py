"""Fail-closed HTTPS transport for allowlisted Provider endpoints.

The implementation uses the system trust store through ``ssl.create_default_context``
and pins the connection to an address that was validated before TLS.  It never follows
redirects and never logs request values or response bodies.  Network access is also
gated by an injected, expiring egress-control attestation; source code cannot prove an
external proxy/firewall deployment on its own.
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import math
import re
import socket
import ssl
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from time import monotonic
from typing import Any, Callable, Iterable, Protocol, Sequence
from urllib.parse import urlencode, urlsplit

from .canonical import require_aware
from .http import HttpRequest, HttpResponse, HttpValue, SensitiveValue
from .validation import EndpointRule, InputValidationError, SchemaValidationError


_HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,128}\Z")
_EVIDENCE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_ALLOWED_RESPONSE_MEDIA_TYPES = {"application/json", "application/problem+json"}
_FORBIDDEN_CALLER_HEADERS = {"connection", "content-length", "host", "transfer-encoding"}


class TransportSecurityError(RuntimeError):
    pass


class TransportTimeoutError(TimeoutError):
    pass


class TransportNetworkError(ConnectionError):
    pass


class EgressEnforcement(StrEnum):
    EXTERNAL_PROXY_OR_FIREWALL = "EXTERNAL_PROXY_OR_FIREWALL"


@dataclass(frozen=True, slots=True)
class NetworkEgressAttestation:
    """Deployment evidence that code cannot infer from local process state."""

    evidence_id: str
    artifact_sha256: str
    version: str
    issued_at: datetime
    expires_at: datetime
    enforcement: EgressEnforcement = EgressEnforcement.EXTERNAL_PROXY_OR_FIREWALL

    def __post_init__(self) -> None:
        if not _EVIDENCE_ID.fullmatch(self.evidence_id):
            raise ValueError("egress evidence id is invalid")
        if not _EVIDENCE_ID.fullmatch(self.version):
            raise ValueError("egress evidence version is invalid")
        if not _SHA256.fullmatch(self.artifact_sha256):
            raise ValueError("egress evidence hash must be lowercase SHA-256")
        require_aware(self.issued_at, "egress evidence issued_at")
        require_aware(self.expires_at, "egress evidence expires_at")
        if self.expires_at <= self.issued_at:
            raise ValueError("egress evidence expiry must follow issue time")

    def valid_at(self, now: datetime) -> bool:
        require_aware(now, "egress evidence evaluation time")
        return self.issued_at <= now < self.expires_at


class AddressResolver(Protocol):
    def resolve(self, hostname: str, port: int) -> Sequence[str]: ...


class SystemAddressResolver:
    def resolve(self, hostname: str, port: int) -> tuple[str, ...]:
        records = socket.getaddrinfo(
            hostname,
            port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
        return tuple(dict.fromkeys(record[4][0] for record in records))


class ResponseStream(Protocol):
    status: int

    def getheaders(self) -> list[tuple[str, str]]: ...

    def read(self, amount: int = -1) -> bytes: ...

    def close(self) -> None: ...


class HttpsConnection(Protocol):
    def request(
        self,
        method: str,
        target: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> None: ...

    def getresponse(self) -> ResponseStream: ...

    def set_read_timeout(self, seconds: float) -> None: ...

    def close(self) -> None: ...


class HttpsConnectionFactory(Protocol):
    external_target_resolution: bool

    def open(
        self,
        *,
        hostname: str,
        port: int,
        resolved_ip: str,
        connect_timeout_seconds: float,
    ) -> HttpsConnection: ...


class _PinnedHttpsConnection:
    def __init__(
        self,
        connection: http.client.HTTPSConnection,
        tls_socket: Any,
    ) -> None:
        self._connection = connection
        self._tls_socket = tls_socket

    def request(
        self,
        method: str,
        target: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._connection.request(method, target, body=body, headers=headers or {})

    def getresponse(self) -> ResponseStream:
        return self._connection.getresponse()

    def set_read_timeout(self, seconds: float) -> None:
        self._tls_socket.settimeout(seconds)

    def close(self) -> None:
        self._connection.close()


class PinnedHttpsConnectionFactory:
    """System-TLS connection pinned to the already validated DNS address."""

    external_target_resolution = False

    def __init__(
        self,
        *,
        socket_opener: Callable[[tuple[str, int], float], Any] | None = None,
        tls_context_factory: Callable[[], ssl.SSLContext] = ssl.create_default_context,
    ) -> None:
        self._socket_opener = socket_opener or (
            lambda address, timeout: socket.create_connection(address, timeout=timeout)
        )
        self._tls_context_factory = tls_context_factory

    def open(
        self,
        *,
        hostname: str,
        port: int,
        resolved_ip: str,
        connect_timeout_seconds: float,
    ) -> HttpsConnection:
        context = self._tls_context_factory()
        if not context.check_hostname or context.verify_mode != ssl.CERT_REQUIRED:
            raise TransportSecurityError("TLS hostname and certificate verification are required")
        raw_socket = self._socket_opener((resolved_ip, port), connect_timeout_seconds)
        try:
            raw_socket.settimeout(connect_timeout_seconds)
            tls_socket = context.wrap_socket(raw_socket, server_hostname=hostname)
            tls_socket.settimeout(connect_timeout_seconds)
        except BaseException:
            raw_socket.close()
            raise
        connection = http.client.HTTPSConnection(
            hostname,
            port=port,
            timeout=connect_timeout_seconds,
            context=context,
        )
        connection.sock = tls_socket
        return _PinnedHttpsConnection(connection, tls_socket)


class HttpsConnectProxyConnectionFactory:
    """Create a hostname-verified TLS tunnel through one fixed HTTP CONNECT proxy.

    The proxy is deployment infrastructure, not a caller-selected destination.  It
    receives only the fixed Provider hostname and port; Provider paths, query values,
    credentials, and bodies remain inside the end-to-end TLS tunnel.
    """

    _MAXIMUM_PROXY_RESPONSE_BYTES = 4_096
    # The attested CONNECT proxy resolves the exact allowlisted hostname and rejects
    # every private/special answer. This also permits a Routing-only internal Docker
    # network whose local resolver deliberately has no internet DNS path.
    external_target_resolution = True

    def __init__(
        self,
        proxy_url: str,
        *,
        socket_opener: Callable[[tuple[str, int], float], Any] | None = None,
        tls_context_factory: Callable[[], ssl.SSLContext] = ssl.create_default_context,
    ) -> None:
        try:
            parts = urlsplit(proxy_url)
            port = parts.port or 3128
        except ValueError:
            raise ValueError("Provider HTTPS proxy URL is invalid") from None
        if (
            parts.scheme != "http"
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.path not in {"", "/"}
            or parts.query
            or parts.fragment
            or not 1 <= port <= 65_535
        ):
            raise ValueError("Provider HTTPS proxy must be one credential-free HTTP origin")
        try:
            parts.hostname.encode("ascii", "strict")
        except UnicodeEncodeError:
            raise ValueError("Provider HTTPS proxy hostname must be canonical ASCII") from None
        self._proxy_host = parts.hostname
        self._proxy_port = port
        self._socket_opener = socket_opener or (
            lambda address, timeout: socket.create_connection(address, timeout=timeout)
        )
        self._tls_context_factory = tls_context_factory

    def open(
        self,
        *,
        hostname: str,
        port: int,
        resolved_ip: str,
        connect_timeout_seconds: float,
    ) -> HttpsConnection:
        # StrictHttpsTransport already validated the endpoint hostname, its exact URL,
        # and every DNS answer.  CONNECT intentionally uses that hostname so the
        # external allowlist proxy can enforce the same provider boundary.
        del resolved_ip
        context = self._tls_context_factory()
        if not context.check_hostname or context.verify_mode != ssl.CERT_REQUIRED:
            raise TransportSecurityError("TLS hostname and certificate verification are required")
        raw_socket = self._socket_opener(
            (self._proxy_host, self._proxy_port), connect_timeout_seconds
        )
        try:
            raw_socket.settimeout(connect_timeout_seconds)
            authority = f"{hostname}:{port}"
            request = (
                f"CONNECT {authority} HTTP/1.1\r\n"
                f"Host: {authority}\r\n"
                "Connection: keep-alive\r\n\r\n"
            ).encode("ascii", "strict")
            raw_socket.sendall(request)
            response = self._read_proxy_response(raw_socket)
            status_line = response.split(b"\r\n", 1)[0]
            fields = status_line.split(b" ", 2)
            if (
                len(fields) < 2
                or fields[0] not in {b"HTTP/1.0", b"HTTP/1.1"}
                or fields[1] != b"200"
            ):
                raise TransportSecurityError("Provider HTTPS proxy rejected the tunnel")
            tls_socket = context.wrap_socket(raw_socket, server_hostname=hostname)
            tls_socket.settimeout(connect_timeout_seconds)
        except BaseException:
            raw_socket.close()
            raise
        connection = http.client.HTTPSConnection(
            hostname,
            port=port,
            timeout=connect_timeout_seconds,
            context=context,
        )
        connection.sock = tls_socket
        return _PinnedHttpsConnection(connection, tls_socket)

    @classmethod
    def _read_proxy_response(cls, raw_socket: Any) -> bytes:
        value = bytearray()
        while b"\r\n\r\n" not in value:
            remaining = cls._MAXIMUM_PROXY_RESPONSE_BYTES + 1 - len(value)
            if remaining <= 0:
                raise TransportSecurityError("Provider HTTPS proxy response is oversized")
            chunk = raw_socket.recv(min(1_024, remaining))
            if not isinstance(chunk, bytes) or not chunk:
                raise TransportSecurityError("Provider HTTPS proxy response is incomplete")
            value.extend(chunk)
        header, separator, trailing = bytes(value).partition(b"\r\n\r\n")
        if not separator or trailing:
            raise TransportSecurityError("Provider HTTPS proxy response is malformed")
        try:
            header.decode("ascii", "strict")
        except UnicodeDecodeError:
            raise TransportSecurityError("Provider HTTPS proxy response is malformed") from None
        return header + separator


class StrictHttpsTransport:
    """Concrete bounded transport with exact endpoints and no redirect behavior."""

    def __init__(
        self,
        exact_endpoint_urls: Iterable[str],
        *,
        egress_attestation: NetworkEgressAttestation | None = None,
        resolver: AddressResolver | None = None,
        connection_factory: HttpsConnectionFactory | None = None,
        clock: Callable[[], datetime] | None = None,
        monotonic_clock: Callable[[], float] = monotonic,
        maximum_timeout_ms: int = 6_500,
        maximum_request_bytes: int = 256_000,
        maximum_response_bytes: int = 2_000_000,
        maximum_header_bytes: int = 32_768,
    ) -> None:
        urls: list[str] = []
        for index, url in enumerate(exact_endpoint_urls):
            EndpointRule("TRANSPORT", str(index), url)
            try:
                url.encode("ascii")
            except UnicodeEncodeError as exc:
                raise ValueError("Provider endpoints must use canonical ASCII URLs") from exc
            parts = urlsplit(url)
            if parts.port not in {None, 443}:
                raise ValueError("Provider HTTPS endpoints must use port 443")
            urls.append(url)
        if not urls or len(urls) != len(set(urls)):
            raise ValueError("transport requires unique allowlisted endpoints")
        for value, name in (
            (maximum_timeout_ms, "maximum_timeout_ms"),
            (maximum_request_bytes, "maximum_request_bytes"),
            (maximum_response_bytes, "maximum_response_bytes"),
            (maximum_header_bytes, "maximum_header_bytes"),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        self._urls = frozenset(urls)
        self._egress_attestation = egress_attestation
        self._resolver = resolver or SystemAddressResolver()
        self._connection_factory = connection_factory or PinnedHttpsConnectionFactory()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._monotonic = monotonic_clock
        self._maximum_timeout_ms = maximum_timeout_ms
        self._maximum_request_bytes = maximum_request_bytes
        self._maximum_response_bytes = maximum_response_bytes
        self._maximum_header_bytes = maximum_header_bytes

    def send(self, request: HttpRequest) -> HttpResponse:
        self._require_egress_attestation()
        if request.url not in self._urls:
            raise InputValidationError("provider endpoint is not transport-allowlisted")
        parts = urlsplit(request.url)
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
            or parts.port not in {None, 443}
        ):
            raise TransportSecurityError("provider endpoint failed strict HTTPS validation")
        if request.timeout_ms > self._maximum_timeout_ms:
            raise InputValidationError("provider timeout exceeds transport maximum")
        if request.maximum_response_bytes > self._maximum_response_bytes:
            raise InputValidationError("provider response bound exceeds transport maximum")

        if getattr(self._connection_factory, "external_target_resolution", False):
            addresses: tuple[str, ...] = ()
        else:
            try:
                addresses = tuple(dict.fromkeys(self._resolver.resolve(parts.hostname, 443)))
            except OSError:
                raise TransportNetworkError("provider DNS resolution failed") from None
            if not addresses:
                raise TransportSecurityError("provider DNS returned no addresses")
            for address in addresses:
                _require_global_address(address)

        deadline_at = self._monotonic() + request.timeout_ms / 1000.0
        connect_seconds = _remaining_seconds(deadline_at, self._monotonic)
        connection: HttpsConnection | None = None
        response: ResponseStream | None = None
        try:
            connection = self._connection_factory.open(
                hostname=parts.hostname,
                port=443,
                resolved_ip=addresses[0] if addresses else "",
                connect_timeout_seconds=connect_seconds,
            )
            read_seconds = _remaining_seconds(deadline_at, self._monotonic)
            connection.set_read_timeout(read_seconds)
            target, body, headers = self._prepare_request(request, parts.path or "/")
            connection.request(request.method, target, body=body, headers=headers)
            response = connection.getresponse()
            status, content_type, content_length = self._validate_response_head(
                response,
                maximum_bytes=request.maximum_response_bytes,
            )
            body_bytes = self._read_body(
                response,
                connection=connection,
                maximum_bytes=request.maximum_response_bytes,
                expected_length=content_length,
                deadline_at=deadline_at,
            )
            return HttpResponse(status, content_type, body_bytes)
        except TransportTimeoutError:
            raise
        except (socket.timeout, TimeoutError):
            raise TransportTimeoutError("provider HTTPS deadline exhausted") from None
        except (OSError, http.client.HTTPException):
            raise TransportNetworkError("provider HTTPS transport failed") from None
        finally:
            if response is not None:
                with suppress(Exception):
                    response.close()
            if connection is not None:
                with suppress(Exception):
                    connection.close()

    def _require_egress_attestation(self) -> None:
        evidence = self._egress_attestation
        if evidence is None or not evidence.valid_at(self._clock()):
            raise TransportSecurityError("valid external egress-control evidence is required")
        if evidence.enforcement is not EgressEnforcement.EXTERNAL_PROXY_OR_FIREWALL:
            raise TransportSecurityError("unsupported egress enforcement mode")

    def _prepare_request(
        self,
        request: HttpRequest,
        path: str,
    ) -> tuple[str, bytes | None, dict[str, str]]:
        if request.method == "GET" and request.json_body is not None:
            raise InputValidationError("GET provider requests cannot carry JSON bodies")
        pairs: list[tuple[str, str]] = []
        for name, value in request.query:
            _validate_query_name(name)
            pairs.append((name, _http_value(value, maximum_length=2_048)))
        encoded_query = urlencode(pairs)
        target = path + (("?" + encoded_query) if encoded_query else "")
        if len(target.encode("ascii", "strict")) > 8_192:
            raise InputValidationError("provider request target exceeds byte limit")

        headers: dict[str, str] = {}
        normalized_names: set[str] = set()
        for name, value in request.headers:
            _validate_header(name, value)
            normalized = name.lower()
            if normalized in _FORBIDDEN_CALLER_HEADERS or normalized in normalized_names:
                raise InputValidationError("provider request contains forbidden or duplicate header")
            normalized_names.add(normalized)
            headers[name] = _http_value(value, maximum_length=8_192)

        body: bytes | None = None
        if request.json_body is not None:
            try:
                body = json.dumps(
                    request.json_body,
                    allow_nan=False,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            except (TypeError, ValueError) as exc:
                raise InputValidationError("provider JSON body is not finite/serializable") from exc
            if len(body) > self._maximum_request_bytes:
                raise InputValidationError("provider request body exceeds byte limit")
            if "content-type" in normalized_names:
                supplied = next(value for name, value in headers.items() if name.lower() == "content-type")
                if supplied.split(";", 1)[0].strip().lower() != "application/json":
                    raise InputValidationError("provider request content type must be application/json")
            else:
                headers["Content-Type"] = "application/json"
        return target, body, headers

    def _validate_response_head(
        self,
        response: ResponseStream,
        *,
        maximum_bytes: int,
    ) -> tuple[int, str, int | None]:
        status = response.status
        if not isinstance(status, int) or isinstance(status, bool) or not 200 <= status <= 599:
            raise SchemaValidationError("provider response status is invalid")
        if 300 <= status <= 399:
            raise TransportSecurityError("provider redirects are forbidden")
        raw_headers = response.getheaders()
        if not isinstance(raw_headers, list) or len(raw_headers) > 64:
            raise SchemaValidationError("provider response header shape is invalid")
        total_bytes = 0
        values: dict[str, list[str]] = {}
        for name, value in raw_headers:
            if not isinstance(name, str) or not isinstance(value, str):
                raise SchemaValidationError("provider response headers must be text")
            if not _HEADER_NAME.fullmatch(name) or "\r" in value or "\n" in value:
                raise SchemaValidationError("provider response header is malformed")
            try:
                encoded_name = name.encode("ascii")
                encoded_value = value.encode("latin-1", "strict")
            except UnicodeEncodeError as exc:
                raise SchemaValidationError("provider response header encoding is invalid") from exc
            total_bytes += len(encoded_name) + len(encoded_value) + 4
            if total_bytes > self._maximum_header_bytes:
                raise SchemaValidationError("provider response headers exceed byte limit")
            values.setdefault(name.lower(), []).append(value.strip())

        for critical in ("content-type", "content-length", "content-encoding", "transfer-encoding"):
            if len(values.get(critical, ())) > 1:
                raise SchemaValidationError(f"duplicate provider {critical} header")
        if "content-length" in values and "transfer-encoding" in values:
            raise SchemaValidationError("ambiguous provider response framing")
        if values.get("content-encoding", ["identity"])[0].lower() not in {"", "identity"}:
            raise SchemaValidationError("compressed provider responses are not accepted")
        if "transfer-encoding" in values and values["transfer-encoding"][0].lower() != "chunked":
            raise SchemaValidationError("unsupported provider transfer encoding")

        content_types = values.get("content-type", [])
        if len(content_types) != 1:
            raise SchemaValidationError("provider response requires one content-type")
        content_type = content_types[0]
        if content_type.split(";", 1)[0].strip().lower() not in _ALLOWED_RESPONSE_MEDIA_TYPES:
            raise SchemaValidationError("provider response content type is unsupported")

        content_length: int | None = None
        if "content-length" in values:
            text = values["content-length"][0]
            if not text.isascii() or not text.isdigit():
                raise SchemaValidationError("provider content-length is invalid")
            try:
                content_length = int(text)
            except ValueError as exc:
                raise SchemaValidationError("provider content-length is invalid") from exc
            if content_length > min(self._maximum_response_bytes, maximum_bytes):
                raise SchemaValidationError("provider content-length exceeds response bound")
        return status, content_type, content_length

    def _read_body(
        self,
        response: ResponseStream,
        *,
        connection: HttpsConnection,
        maximum_bytes: int,
        expected_length: int | None,
        deadline_at: float,
    ) -> bytes:
        chunks: list[bytes] = []
        count = 0
        while True:
            connection.set_read_timeout(_remaining_seconds(deadline_at, self._monotonic))
            chunk = response.read(min(65_536, maximum_bytes + 1 - count))
            if not isinstance(chunk, bytes):
                raise SchemaValidationError("provider response body chunks must be bytes")
            if not chunk:
                break
            count += len(chunk)
            if count > maximum_bytes:
                raise SchemaValidationError("provider response exceeds byte limit")
            chunks.append(chunk)
        if expected_length is not None and count != expected_length:
            raise SchemaValidationError("provider response length does not match content-length")
        return b"".join(chunks)


def _remaining_seconds(deadline_at: float, clock: Callable[[], float]) -> float:
    remaining = deadline_at - clock()
    if remaining <= 0:
        raise TransportTimeoutError("provider HTTPS deadline exhausted")
    return remaining


def _require_global_address(value: str) -> None:
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise TransportSecurityError("provider DNS returned an invalid address") from exc
    if not address.is_global:
        raise TransportSecurityError("provider DNS returned a non-global address")


def _validate_query_name(name: str) -> None:
    if not _HEADER_NAME.fullmatch(name):
        raise InputValidationError("provider query name is invalid")


def _validate_header(name: str, value: HttpValue) -> None:
    if not _HEADER_NAME.fullmatch(name):
        raise InputValidationError("provider request header name is invalid")
    if isinstance(value, str) and ("\r" in value or "\n" in value):
        raise InputValidationError("provider request header value is invalid")


def _http_value(value: HttpValue, *, maximum_length: int) -> str:
    if isinstance(value, SensitiveValue):
        text = value.reveal_for_transport()
    elif isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise InputValidationError("provider request number must be finite")
        text = str(value)
    else:
        text = str(value)
    if not text or len(text) > maximum_length or any(ord(char) < 32 for char in text):
        raise InputValidationError("provider request value is invalid")
    return text
