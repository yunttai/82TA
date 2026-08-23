from __future__ import annotations

import ipaddress
from functools import lru_cache

from django.conf import settings
from django.http import HttpRequest

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


def normalize_ip(value: object) -> IPAddress | None:
    try:
        address = ipaddress.ip_address(str(value).strip())
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


@lru_cache(maxsize=16)
def _parse_trusted_proxy_networks(values: tuple[str, ...]) -> tuple[IPNetwork, ...]:
    networks: list[IPNetwork] = []
    for value in values:
        try:
            networks.append(ipaddress.ip_network(value, strict=False))
        except ValueError:
            # Invalid development configuration trusts nobody. Production settings reject it at startup.
            return ()
    return tuple(networks)


def trusted_proxy_networks() -> tuple[IPNetwork, ...]:
    return _parse_trusted_proxy_networks(tuple(settings.TRUSTED_PROXY_IPS))


def is_trusted_proxy(address: IPAddress | None, networks: tuple[IPNetwork, ...]) -> bool:
    if address is None:
        return False
    return any(address.version == network.version and address in network for network in networks)


def client_ip(request: HttpRequest) -> str:
    """Resolve the nearest untrusted hop from an append-only proxy chain."""

    peer = normalize_ip(request.META.get("REMOTE_ADDR", ""))
    if peer is None:
        return "unknown"
    if not settings.TRUST_PROXY_HEADERS:
        return peer.compressed

    networks = trusted_proxy_networks()
    if not is_trusted_proxy(peer, networks):
        return peer.compressed

    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    raw_chain = [part.strip() for part in forwarded.split(",") if part.strip()]
    if not raw_chain or len(raw_chain) > 10:
        return peer.compressed
    chain = [normalize_ip(part) for part in raw_chain]
    if any(address is None for address in chain):
        return peer.compressed

    for address in reversed(chain):
        if not is_trusted_proxy(address, networks):
            return address.compressed
    return peer.compressed
