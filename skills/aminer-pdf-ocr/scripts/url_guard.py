"""Reject localhost / private-network URLs before fetching."""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import requests

MAX_REDIRECTS = 5
CHUNK = 8192


class UrlGuardError(ValueError):
    pass


def assert_public_http_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise UrlGuardError("only http(s) URLs are allowed")
    host = (parsed.hostname or "").strip("[]")
    if not host:
        raise UrlGuardError("URL is missing a hostname")
    lowered = host.lower()
    if lowered in {"localhost", "metadata.google.internal"} or lowered.endswith(".localhost"):
        raise UrlGuardError("refusing to fetch a local or metadata host")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UrlGuardError(f"cannot resolve host {host}: {exc}") from exc
    if not infos:
        raise UrlGuardError(f"cannot resolve host {host}")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise UrlGuardError("refusing to fetch a private or local URL")


def fetch_public_url(url: str, *, timeout: float, max_bytes: int) -> bytes:
    current = url
    for _ in range(MAX_REDIRECTS):
        assert_public_http_url(current)
        response = requests.get(current, timeout=timeout, allow_redirects=False, stream=True)
        try:
            if response.is_redirect or response.is_permanent_redirect:
                location = response.headers.get("Location")
                if not location:
                    raise UrlGuardError("redirect is missing Location")
                current = urljoin(current, location)
                continue
            response.raise_for_status()
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_content(CHUNK):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    raise UrlGuardError(f"download exceeds {max_bytes} bytes")
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            response.close()
    raise UrlGuardError("too many redirects")
