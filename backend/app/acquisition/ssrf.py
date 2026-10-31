import asyncio
import ipaddress
import re
import socket
from typing import Any
from urllib.parse import urlsplit

import httpcore

ALLOWED_PORTS = {80, 443}
_OBSCURE_NUMERIC_HOST = re.compile(r"^(?:0x[0-9a-f]+|\d+)(?:\.(?:0x[0-9a-f]+|\d+)){0,3}\.?$", re.I)
_DOTTED_QUAD = re.compile(r"^(?:[1-9]\d{0,2}|0)(?:\.(?:[1-9]\d{0,2}|0)){3}$")
_CONTROL_CHARACTER = re.compile(r"[\x00-\x1f\x7f]")


class UrlRejected(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def parse_url(url: str) -> tuple[str, int]:
    """Return (host, port), or reject a URL that isn't plain http(s) on a standard port."""
    if _CONTROL_CHARACTER.search(url):
        raise UrlRejected("INVALID_URL", "That link isn't valid.")
    try:
        parts = urlsplit(url)
        scheme, host = parts.scheme.lower(), parts.hostname
        port = parts.port or (443 if scheme == "https" else 80)
        # DNS lookup raises on a name it can't encode, such as one with a 70-character label.
        (host or "").encode("idna")
    except ValueError as exc:
        raise UrlRejected("INVALID_URL", "That link isn't valid.") from exc
    if scheme not in ("http", "https") or not host:
        raise UrlRejected("INVALID_URL", "Enter a link starting with http or https.")
    if port not in ALLOWED_PORTS:
        raise UrlRejected("INVALID_URL", "That link uses a port we can't fetch from.")
    if parts.username or parts.password:
        raise UrlRejected("INVALID_URL", "Links with a username or password aren't supported.")
    if _OBSCURE_NUMERIC_HOST.match(host) and not _DOTTED_QUAD.match(host):
        # Forms like 2130706433 or 0x7f.0.0.1 mean 127.0.0.1 to a browser. No real site uses them.
        raise UrlRejected("URL_BLOCKED", "That link points somewhere we can't fetch from.")
    return host, port


def is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


async def resolve_public(host: str, port: int) -> list[str]:
    """Resolve a host, rejecting it if any address it points to isn't public."""
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addresses = list(dict.fromkeys(info[4][0] for info in infos))
    if not all(is_public(address) for address in addresses):
        raise UrlRejected("URL_BLOCKED", "That link points somewhere we can't fetch from.")
    return addresses


async def check_url(url: str) -> None:
    """Reject bad or internal URLs. A name that doesn't resolve is left for the fetcher to report."""
    host, port = parse_url(url)
    try:
        await resolve_public(host, port)
    except socket.gaierror:
        pass


class GuardedBackend(httpcore.AsyncNetworkBackend):
    """Connects only to the addresses it has just checked, so DNS can't change after the check."""

    def __init__(self, inner: httpcore.AsyncNetworkBackend) -> None:
        self._inner = inner

    async def connect_tcp(
        self, host: str, port: int, timeout: float | None = None, **kwargs: Any
    ) -> httpcore.AsyncNetworkStream:
        try:
            addresses = await resolve_public(host, port)
        except UrlRejected as exc:
            raise httpcore.ConnectError(exc.message) from exc
        except socket.gaierror as exc:
            raise httpcore.ConnectError(f"DNS lookup failed for {host}") from exc
        failure: Exception | None = None
        for address in addresses[:2]:
            try:
                return await self._inner.connect_tcp(address, port, timeout, **kwargs)
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                failure = exc
        raise failure

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)
