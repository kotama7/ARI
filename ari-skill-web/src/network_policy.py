"""Pinned-address HTTP fetcher with redirect and response-size policy."""

from __future__ import annotations

import http.client
import ipaddress
import socket
from dataclasses import dataclass
from typing import Callable
from urllib.parse import SplitResult, urljoin, urlsplit, urlunsplit


ALLOWED_SCHEMES = frozenset({"http", "https"})
ALLOWED_PORTS = frozenset({80, 443})
ALLOWED_CONTENT_TYPES = frozenset(
    {
        "text/html",
        "text/plain",
        "application/json",
        "application/xml",
        "text/xml",
    }
)
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 5


class NetworkPolicyError(ValueError):
    """The URL or response violates the external-fetch security policy."""


@dataclass(frozen=True)
class FetchedResponse:
    url: str
    status: int
    headers: dict[str, str]
    body: bytes
    redirect_chain: tuple[str, ...]
    pinned_ip: str


Resolver = Callable[[str, int], tuple[str, ...]]


def resolve_public_ips(hostname: str, port: int) -> tuple[str, ...]:
    values: list[str] = []
    for family, _, _, _, sockaddr in socket.getaddrinfo(
        hostname, port, type=socket.SOCK_STREAM
    ):
        if family not in {socket.AF_INET, socket.AF_INET6}:
            continue
        value = str(sockaddr[0])
        if value not in values:
            values.append(value)
    if not values:
        raise NetworkPolicyError("hostname resolved to no usable address")
    return tuple(values)


def _public_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return bool(address.is_global)


def validate_url(
    url: str, resolver: Resolver = resolve_public_ips
) -> tuple[SplitResult, str]:
    if not url or any(ord(character) < 32 for character in url) or "\\" in url:
        raise NetworkPolicyError("URL contains unsafe characters")
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise NetworkPolicyError("only HTTP(S) URLs are allowed")
    if not parsed.hostname:
        raise NetworkPolicyError("URL must include a hostname")
    if parsed.username is not None or parsed.password is not None:
        raise NetworkPolicyError("URL userinfo is not allowed")
    if parsed.fragment:
        parsed = parsed._replace(fragment="")
    try:
        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    except ValueError as exc:
        raise NetworkPolicyError("invalid URL port") from exc
    if port not in ALLOWED_PORTS:
        raise NetworkPolicyError("URL port is not allowed")
    try:
        literal = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        literal = None
    addresses = (
        (str(literal),) if literal is not None else resolver(parsed.hostname, port)
    )
    if any(not _public_address(address) for address in addresses):
        raise NetworkPolicyError("hostname resolves to a non-public address")
    # Pin the first already-validated address. The socket layer never resolves
    # the hostname again, closing the validation/use DNS-rebinding window.
    return parsed, addresses[0]


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, hostname: str, address: str, port: int, timeout: float):
        super().__init__(hostname, port=port, timeout=timeout)
        self._ari_address = address

    def connect(self) -> None:
        raw = socket.create_connection(
            (self._ari_address, self.port), self.timeout, self.source_address
        )
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


def _request_once(
    parsed: SplitResult,
    pinned_ip: str,
    *,
    timeout: float,
    max_bytes: int,
):
    scheme = parsed.scheme.lower()
    port = parsed.port or (443 if scheme == "https" else 80)
    if scheme == "https":
        connection = _PinnedHTTPSConnection(
            parsed.hostname or "", pinned_ip, port, timeout
        )
    else:
        connection = http.client.HTTPConnection(pinned_ip, port, timeout=timeout)
    host = parsed.hostname or ""
    default_port = 443 if scheme == "https" else 80
    bracketed_host = f"[{host}]" if ":" in host else host
    host_header = bracketed_host if port == default_port else f"{bracketed_host}:{port}"
    path = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    try:
        connection.request(
            "GET",
            path,
            headers={
                "Host": host_header,
                "User-Agent": "ARIBot/2.0 (+https://ari.dev)",
                "Accept": "text/html,text/plain,application/json,application/xml;q=0.9",
                "Accept-Encoding": "identity",
                "Connection": "close",
            },
        )
        response = connection.getresponse()
        headers = {key.lower(): value for key, value in response.getheaders()}
        length = headers.get("content-length")
        if length:
            try:
                declared_length = int(length)
            except ValueError as exc:
                raise NetworkPolicyError("invalid Content-Length") from exc
            if declared_length < 0:
                raise NetworkPolicyError("invalid Content-Length")
            if declared_length > max_bytes:
                raise NetworkPolicyError("response exceeds the byte limit")
        body = response.read(max_bytes + 1)
    finally:
        connection.close()
    if len(body) > max_bytes:
        raise NetworkPolicyError("response exceeds the byte limit")
    return response.status, headers, body


def fetch_pinned(
    url: str,
    *,
    resolver: Resolver = resolve_public_ips,
    timeout: float = 15,
    max_bytes: int = MAX_RESPONSE_BYTES,
    max_redirects: int = MAX_REDIRECTS,
) -> FetchedResponse:
    if max_bytes < 1 or max_bytes > MAX_RESPONSE_BYTES:
        raise NetworkPolicyError("max_bytes is outside the allowed range")
    if max_redirects < 0 or max_redirects > MAX_REDIRECTS:
        raise NetworkPolicyError("max_redirects is outside the allowed range")
    current = url
    chain: list[str] = []
    for redirect_index in range(max_redirects + 1):
        parsed, pinned_ip = validate_url(current, resolver)
        status, headers, body = _request_once(
            parsed, pinned_ip, timeout=timeout, max_bytes=max_bytes
        )
        normalized = urlunsplit(parsed)
        if status in {301, 302, 303, 307, 308}:
            location = headers.get("location")
            if not location:
                raise NetworkPolicyError("redirect response has no Location")
            if redirect_index >= max_redirects:
                raise NetworkPolicyError("redirect limit exceeded")
            target = urljoin(normalized, location)
            target_scheme = urlsplit(target).scheme.lower()
            if parsed.scheme.lower() == "https" and target_scheme == "http":
                raise NetworkPolicyError("HTTPS downgrade redirect is not allowed")
            chain.append(normalized)
            current = target
            continue
        content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type not in ALLOWED_CONTENT_TYPES:
            raise NetworkPolicyError(
                f"response content type is not allowed: {content_type or '(missing)'}"
            )
        return FetchedResponse(
            url=normalized,
            status=status,
            headers=headers,
            body=body,
            redirect_chain=tuple(chain),
            pinned_ip=pinned_ip,
        )
    raise NetworkPolicyError("redirect limit exceeded")
