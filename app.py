"""Compatibility entrypoint for `uvicorn app:app`.

The application now lives in the `videodrop` package, but keeping this module
preserves the original local and deployment command used by the project.
"""

from videodrop.config import STATIC_DIR
from videodrop.downloads import (
    _download_sync,
    _ffmpeg_location,
    _ffmpeg_probe_text,
    _is_whatsapp_compatible_mp4,
)
from videodrop.extractor import _build_format_options, _probe_cache, _probe_locks, _probe_sync
from videodrop.main import app, create_app
from videodrop.thumbnails import _thumbnail_tokens

__all__ = [
    "STATIC_DIR",
    "_build_format_options",
    "_download_sync",
    "_ffmpeg_location",
    "_ffmpeg_probe_text",
    "_is_whatsapp_compatible_mp4",
    "_probe_cache",
    "_probe_locks",
    "_probe_sync",
    "_thumbnail_tokens",
    "app",
    "create_app",
]
