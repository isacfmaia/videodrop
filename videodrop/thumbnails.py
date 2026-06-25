"""Thumbnail token registration and proxy loading."""

from __future__ import annotations

import secrets
import time
from typing import Any
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from fastapi import HTTPException

from .config import MAX_THUMBNAIL_BYTES, MAX_THUMBNAIL_URL_LENGTH, THUMBNAIL_TTL_SECONDS
from .security import validate_remote_media_url

_thumbnail_tokens: dict[str, dict[str, Any]] = {}


def _cleanup_thumbnail_tokens() -> None:
    """Drop expired thumbnail proxy tokens from memory."""
    now = time.time()
    expired_tokens = [token for token, entry in _thumbnail_tokens.items() if entry["expires_at"] <= now]
    for token in expired_tokens:
        _thumbnail_tokens.pop(token, None)


def register_thumbnail(thumbnail_url: str | None, webpage_url: str, headers: dict[str, str] | None) -> str | None:
    """Create a short-lived local proxy URL for a remote thumbnail."""
    if not thumbnail_url:
        return None

    try:
        safe_url = validate_remote_media_url(thumbnail_url, MAX_THUMBNAIL_URL_LENGTH)
    except HTTPException:
        return None

    _cleanup_thumbnail_tokens()
    token = secrets.token_urlsafe(24)
    request_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Referer": webpage_url,
    }
    if headers:
        for key in ("User-Agent", "Accept", "Referer", "Cookie"):
            if headers.get(key):
                request_headers[key] = headers[key]

    _thumbnail_tokens[token] = {
        "url": safe_url,
        "headers": request_headers,
        "expires_at": time.time() + THUMBNAIL_TTL_SECONDS,
    }
    return f"/api/thumbnail/{token}"


def fetch_thumbnail_sync(token: str) -> tuple[bytes, str]:
    """Load the remote thumbnail referenced by a valid local token."""
    _cleanup_thumbnail_tokens()
    entry = _thumbnail_tokens.get(token)
    if not entry:
        raise HTTPException(status_code=404, detail="Miniatura expirada.")

    safe_url = validate_remote_media_url(entry["url"], MAX_THUMBNAIL_URL_LENGTH)
    request = UrlRequest(safe_url, headers=entry["headers"])
    with urlopen(request, timeout=12) as response:
        content_type = response.headers.get_content_type() or "application/octet-stream"
        if not content_type.startswith("image/"):
            raise HTTPException(status_code=422, detail="A miniatura retornada não é uma imagem.")

        body = response.read(MAX_THUMBNAIL_BYTES + 1)
        if len(body) > MAX_THUMBNAIL_BYTES:
            raise HTTPException(status_code=413, detail="Miniatura muito grande.")

    return body, content_type

