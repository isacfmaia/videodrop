"""Shared configuration and runtime constants for VideoDrop."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

try:
    import imageio_ffmpeg
except Exception:  # pragma: no cover - optional runtime helper
    imageio_ffmpeg = None


def _runtime_root() -> Path:
    """Return the project root in source runs or the PyInstaller bundle root."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


ROOT = _runtime_root()
STATIC_DIR = ROOT / "static"

logger = logging.getLogger("uvicorn.error")

FORMAT_ID_RE = re.compile(r"^[A-Za-z0-9._:-]+$")
AUDIO_MP3_FORMAT_ID = "audio-mp3"
DEDICATED_COOKIE_BROWSER = "firefox"
SUPPORTED_COOKIE_BROWSERS = frozenset({DEDICATED_COOKIE_BROWSER})

SITE_NAME = "VideoDrop"
SITE_DESCRIPTION = "Baixador de vídeos em MP4 para posts públicos do X, Instagram, Facebook e outras plataformas compatíveis."

MAX_URL_LENGTH = int(os.getenv("MAX_URL_LENGTH", "2048"))
MAX_JSON_BYTES = int(os.getenv("MAX_JSON_BYTES", "4096"))
MAX_THUMBNAIL_BYTES = int(os.getenv("MAX_THUMBNAIL_BYTES", str(8 * 1024 * 1024)))
MAX_THUMBNAIL_URL_LENGTH = int(os.getenv("MAX_THUMBNAIL_URL_LENGTH", "8192"))

RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
PROBE_RATE_LIMIT = int(os.getenv("PROBE_RATE_LIMIT", "12"))
DOWNLOAD_RATE_LIMIT = int(os.getenv("DOWNLOAD_RATE_LIMIT", "6"))
THUMBNAIL_RATE_LIMIT = int(os.getenv("THUMBNAIL_RATE_LIMIT", "60"))
THUMBNAIL_TTL_SECONDS = int(os.getenv("THUMBNAIL_TTL_SECONDS", "900"))
MAX_RECORDING_UPLOAD_BYTES = int(os.getenv("MAX_RECORDING_UPLOAD_BYTES", str(1024 * 1024 * 1024)))
RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "0") == "1"
SECURITY_HEADERS_ENABLED = os.getenv("SECURITY_HEADERS_ENABLED", "0") == "1"

PROBE_TIMEOUT_SECONDS = int(os.getenv("PROBE_TIMEOUT_SECONDS", "120"))
PROBE_CACHE_TTL_SECONDS = int(os.getenv("PROBE_CACHE_TTL_SECONDS", "300"))
PROBE_SEMAPHORE = asyncio.Semaphore(int(os.getenv("PROBE_CONCURRENCY", "2")))
DOWNLOAD_SEMAPHORE = asyncio.Semaphore(int(os.getenv("DOWNLOAD_CONCURRENCY", "1")))

BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain"}


def videodrop_app_data_dir() -> Path:
    """Return the per-user app data directory without creating it."""
    configured_dir = os.getenv("VIDEODROP_DATA_DIR", "").strip()
    if configured_dir:
        return Path(configured_dir).expanduser()

    base = os.getenv("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Local"
    return root / "VideoDrop"


def dedicated_firefox_profile_dir(create: bool = False) -> Path:
    """Return the Firefox profile used only for VideoDrop Instagram login."""
    configured_dir = os.getenv("VIDEODROP_FIREFOX_PROFILE_DIR", "").strip()
    path = Path(configured_dir).expanduser() if configured_dir else videodrop_app_data_dir() / "FirefoxProfile"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def _ffmpeg_location() -> str | None:
    """Return the bundled or system ffmpeg path when available."""
    if imageio_ffmpeg is not None:
        try:
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            pass
    return shutil.which("ffmpeg")


def normalize_cookie_browser(cookie_browser: str | None) -> str | None:
    """Normalize the only browser cookie source accepted by the local app."""
    if not cookie_browser:
        return None

    normalized = cookie_browser.strip().lower()
    if not normalized:
        return None
    if normalized not in SUPPORTED_COOKIE_BROWSERS:
        raise ValueError(f"Navegador de cookies invalido: {cookie_browser}")
    return normalized


def _base_ydl_opts(cookie_browser: str | None = None) -> dict[str, Any]:
    """Build the shared yt-dlp options used by probe and download flows."""
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "socket_timeout": 20,
        "retries": 2,
        "fragment_retries": 2,
    }
    ffmpeg = _ffmpeg_location()
    if ffmpeg:
        opts["ffmpeg_location"] = ffmpeg
    normalized_cookie_browser = normalize_cookie_browser(cookie_browser)
    if normalized_cookie_browser:
        opts["cookiesfrombrowser"] = (normalized_cookie_browser, str(dedicated_firefox_profile_dir()))
    return opts
