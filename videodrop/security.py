"""Security helpers for request validation, headers and lightweight limits."""

from __future__ import annotations

import ipaddress
import os
import socket
import time
from collections import defaultdict, deque
from urllib.parse import urlparse

from fastapi import HTTPException, Request
from fastapi.responses import Response

from .config import BLOCKED_HOSTNAMES, MAX_URL_LENGTH, RATE_LIMIT_WINDOW_SECONDS

_rate_limit_hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)


def add_security_headers(response: Response, request: Request) -> Response:
    """Attach opt-in browser security headers to a response."""
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(self), display-capture=(self), geolocation=(), payment=()"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; "
        "img-src 'self' data: https:; "
        "connect-src 'self'; "
        "form-action 'self'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'"
    )
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


def client_ip(request: Request) -> str:
    """Resolve the client IP, optionally trusting reverse proxy headers."""
    if os.getenv("TRUST_PROXY_HEADERS", "1") == "1":
        forwarded_for = request.headers.get("x-forwarded-for", "")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

    return request.client.host if request.client else "unknown"


def is_limited(bucket: str, key: str, limit: int) -> bool:
    """Track in-memory request counts for optional rate limiting."""
    now = time.monotonic()
    if len(_rate_limit_hits) > 10000:
        stale_keys = [
            hit_key
            for hit_key, hit_values in _rate_limit_hits.items()
            if not hit_values or now - hit_values[-1] > RATE_LIMIT_WINDOW_SECONDS
        ]
        for hit_key in stale_keys:
            _rate_limit_hits.pop(hit_key, None)

    hits = _rate_limit_hits[(bucket, key)]
    while hits and now - hits[0] > RATE_LIMIT_WINDOW_SECONDS:
        hits.popleft()
    if len(hits) >= limit:
        return True
    hits.append(now)
    return False


def _is_public_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_public_hostname(hostname: str, port: int | None) -> None:
    """Reject hostnames that resolve to local or private network addresses."""
    normalized = hostname.strip(".").lower()
    if normalized in BLOCKED_HOSTNAMES or normalized.endswith(".localhost"):
        raise HTTPException(status_code=400, detail="URL bloqueada por segurança.")

    try:
        parsed_ip = ipaddress.ip_address(normalized)
    except ValueError:
        parsed_ip = None

    if parsed_ip is not None:
        if not _is_public_ip(normalized):
            raise HTTPException(status_code=400, detail="URL bloqueada por segurança.")
        return

    try:
        resolved = socket.getaddrinfo(normalized, port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise HTTPException(status_code=400, detail="Não consegui resolver o domínio informado.") from exc

    addresses = {item[4][0] for item in resolved}
    if not addresses or any(not _is_public_ip(address) for address in addresses):
        raise HTTPException(status_code=400, detail="URL bloqueada por segurança.")


def validate_remote_media_url(url: str, max_length: int = MAX_URL_LENGTH) -> str:
    """Normalize and validate user-provided http(s) URLs."""
    cleaned_url = url.strip()
    if len(cleaned_url) > max_length:
        raise HTTPException(status_code=400, detail="URL muito longa.")

    parsed = urlparse(cleaned_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Cole uma URL http(s) válida.")
    return parsed.geturl()


def validate_url(url: str) -> str:
    """Validate the primary post URL accepted by the public API."""
    return validate_remote_media_url(url, MAX_URL_LENGTH)
