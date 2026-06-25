"""yt-dlp probing, format selection metadata and probe cache."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from typing import Any

from fastapi import HTTPException
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from .config import (
    AUDIO_MP3_FORMAT_ID,
    FORMAT_ID_RE,
    PROBE_CACHE_TTL_SECONDS,
    PROBE_SEMAPHORE,
    PROBE_TIMEOUT_SECONDS,
    _base_ydl_opts,
    _ffmpeg_location,
    logger,
)
from .thumbnails import register_thumbnail

_probe_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_probe_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


def _first_video(info: dict[str, Any]) -> dict[str, Any]:
    """Return the first entry when yt-dlp resolves a playlist-like response."""
    entries = info.get("entries")
    if entries:
        first = next((entry for entry in entries if entry), None)
        if isinstance(first, dict):
            return first
    return info


def _size_from_format(
    fmt: dict[str, Any],
    duration: int | float | None,
    extra_audio_size: int | None = None,
) -> tuple[int | None, bool]:
    """Read or estimate a format size from yt-dlp metadata."""
    size = fmt.get("filesize") or fmt.get("filesize_approx")
    is_estimated = not bool(fmt.get("filesize"))

    if not size and duration and fmt.get("tbr"):
        size = int(float(fmt["tbr"]) * 1000 / 8 * float(duration))
        is_estimated = True

    if size and extra_audio_size:
        size = int(size) + int(extra_audio_size)
        is_estimated = True

    return (int(size), is_estimated) if size else (None, True)


def _best_audio_format(formats: list[dict[str, Any]]) -> dict[str, Any] | None:
    audio_formats = [
        fmt
        for fmt in formats
        if fmt.get("acodec") not in (None, "none") and fmt.get("vcodec") in (None, "none")
    ]
    audio_formats.sort(key=lambda item: item.get("abr") or item.get("tbr") or 0, reverse=True)
    return audio_formats[0] if audio_formats else None


def _best_audio_size(formats: list[dict[str, Any]]) -> int | None:
    audio_formats = [
        fmt
        for fmt in formats
        if fmt.get("acodec") not in (None, "none") and fmt.get("vcodec") in (None, "none")
    ]
    audio_formats.sort(key=lambda item: item.get("abr") or item.get("tbr") or 0, reverse=True)
    for fmt in audio_formats:
        size = fmt.get("filesize") or fmt.get("filesize_approx")
        if size:
            return int(size)
    return None


def _build_format_options(info: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert raw yt-dlp formats into the compact options shown in the UI."""
    formats = info.get("formats") or []
    duration = info.get("duration")
    has_ffmpeg = bool(_ffmpeg_location())
    best_audio_size = _best_audio_size(formats)
    by_height: dict[int, dict[str, Any]] = {}

    for fmt in formats:
        if fmt.get("vcodec") in (None, "none"):
            continue

        height = fmt.get("height")
        if not height:
            continue

        ext = (fmt.get("ext") or "").lower()
        protocol = (fmt.get("protocol") or "").lower()
        has_audio = fmt.get("acodec") not in (None, "none")
        is_mp4_family = ext == "mp4" or "m3u8" in protocol

        if not is_mp4_family:
            continue
        if not has_ffmpeg and not has_audio:
            continue

        format_id = str(fmt.get("format_id") or "")
        if not format_id or not FORMAT_ID_RE.match(format_id):
            continue

        needs_merge = not has_audio
        size, estimated = _size_from_format(
            fmt,
            duration,
            best_audio_size if needs_merge else None,
        )
        option = {
            "format_id": format_id,
            "resolution": f"{height}p",
            "height": int(height),
            "width": fmt.get("width"),
            "fps": fmt.get("fps"),
            "size_bytes": size,
            "size_estimated": estimated,
            "has_audio": has_audio,
            "needs_merge": needs_merge,
            "bitrate": fmt.get("tbr"),
        }

        current = by_height.get(int(height))
        current_score = (current or {}).get("bitrate") or 0
        option_score = option.get("bitrate") or 0
        if current is None or option_score >= current_score:
            by_height[int(height)] = option

    options = sorted(by_height.values(), key=lambda item: item["height"], reverse=True)
    best_audio = _best_audio_format(formats)
    if has_ffmpeg and best_audio:
        audio_size = int(192 * 1000 / 8 * float(duration)) if duration else None
        options.append(
            {
                "format_id": AUDIO_MP3_FORMAT_ID,
                "kind": "audio",
                "resolution": "MP3",
                "height": 0,
                "width": None,
                "fps": None,
                "size_bytes": audio_size,
                "size_estimated": True,
                "has_audio": True,
                "needs_merge": False,
                "bitrate": 192,
            }
        )

    return options


def _probe_sync(url: str) -> dict[str, Any]:
    """Run yt-dlp synchronously and return UI-ready metadata."""
    logger.info("Iniciando analise com yt-dlp: %s", url)
    with YoutubeDL({**_base_ydl_opts(), "skip_download": True}) as ydl:
        info = _first_video(ydl.extract_info(url, download=False))

    options = _build_format_options(info)
    if not options:
        raise HTTPException(
            status_code=422,
            detail="Não encontrei formatos MP4 baixáveis para esse post. Talvez ele seja privado, exija login, ou precise de cookies da plataforma.",
        )

    thumbnail = info.get("thumbnail")
    webpage_url = info.get("webpage_url") or url
    thumbnail_proxy = register_thumbnail(thumbnail, webpage_url, info.get("http_headers"))
    logger.info(
        "Analise concluida: site=%s formatos=%s thumbnail=%s thumbnail_proxy=%s",
        info.get("extractor_key") or info.get("extractor") or "Fonte",
        len(options),
        bool(thumbnail),
        bool(thumbnail_proxy),
    )

    return {
        "title": info.get("title") or "Video encontrado",
        "site": info.get("extractor_key") or info.get("extractor") or "Fonte",
        "duration": info.get("duration"),
        "thumbnail": thumbnail,
        "thumbnail_proxy": thumbnail_proxy,
        "webpage_url": webpage_url,
        "formats": options,
        "can_merge": bool(_ffmpeg_location()),
    }


def _get_cached_probe(url: str) -> dict[str, Any] | None:
    cached = _probe_cache.get(url)
    if not cached:
        return None

    expires_at, data = cached
    if expires_at <= time.time():
        _probe_cache.pop(url, None)
        return None

    return data


def _set_cached_probe(url: str, data: dict[str, Any]) -> None:
    """Store probe results briefly to avoid repeated slow extractor calls."""
    if len(_probe_cache) > 200:
        now = time.time()
        expired_urls = [cache_url for cache_url, (expires_at, _) in _probe_cache.items() if expires_at <= now]
        for cache_url in expired_urls:
            _probe_cache.pop(cache_url, None)

    _probe_cache[url] = (time.time() + PROBE_CACHE_TTL_SECONDS, data)


async def probe_url(url: str) -> dict[str, Any]:
    """Analyze a URL with lock + cache so duplicate requests share work."""
    cached_probe = _get_cached_probe(url)
    if cached_probe:
        logger.info("Cache hit para probe: %s", url)
        return cached_probe

    async with _probe_locks[url]:
        cached_probe = _get_cached_probe(url)
        if cached_probe:
            logger.info("Cache hit para probe apos aguardar lock: %s", url)
            return cached_probe

        await PROBE_SEMAPHORE.acquire()
        try:
            data = await asyncio.wait_for(asyncio.to_thread(_probe_sync, url), timeout=PROBE_TIMEOUT_SECONDS)
            _set_cached_probe(url, data)
            return data
        except HTTPException:
            raise
        except asyncio.TimeoutError as exc:
            logger.exception("Timeout analisando URL: %s", url)
            raise HTTPException(status_code=504, detail="A análise demorou demais. Tente novamente em instantes.") from exc
        except DownloadError as exc:
            logger.exception("yt-dlp falhou analisando URL: %s", url)
            raise HTTPException(status_code=422, detail=str(exc).splitlines()[-1]) from exc
        except Exception as exc:
            logger.exception("Erro inesperado analisando URL: %s", url)
            raise HTTPException(status_code=500, detail="Não consegui analisar esse link agora.") from exc
        finally:
            PROBE_SEMAPHORE.release()

