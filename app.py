from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import re
import secrets
import shutil
import subprocess
import socket
import tempfile
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

try:
    import imageio_ffmpeg
except Exception:  # pragma: no cover - optional runtime helper
    imageio_ffmpeg = None


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
logger = logging.getLogger("uvicorn.error")
FORMAT_ID_RE = re.compile(r"^[A-Za-z0-9._:-]+$")
AUDIO_MP3_FORMAT_ID = "audio-mp3"
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
RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "0") == "1"
SECURITY_HEADERS_ENABLED = os.getenv("SECURITY_HEADERS_ENABLED", "0") == "1"
PROBE_TIMEOUT_SECONDS = int(os.getenv("PROBE_TIMEOUT_SECONDS", "120"))
PROBE_CACHE_TTL_SECONDS = int(os.getenv("PROBE_CACHE_TTL_SECONDS", "300"))
PROBE_SEMAPHORE = asyncio.Semaphore(int(os.getenv("PROBE_CONCURRENCY", "2")))
DOWNLOAD_SEMAPHORE = asyncio.Semaphore(int(os.getenv("DOWNLOAD_CONCURRENCY", "1")))
BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain"}
_rate_limit_hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
_probe_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_probe_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
_thumbnail_tokens: dict[str, dict[str, Any]] = {}

app = FastAPI(title=SITE_NAME, description=SITE_DESCRIPTION, version="1.0.0")


class ProbeRequest(BaseModel):
    url: str


def _add_security_headers(response: Response, request: Request) -> Response:
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
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


def _client_ip(request: Request) -> str:
    if os.getenv("TRUST_PROXY_HEADERS", "1") == "1":
        forwarded_for = request.headers.get("x-forwarded-for", "")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

    return request.client.host if request.client else "unknown"


def _is_limited(bucket: str, key: str, limit: int) -> bool:
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


def _validate_public_hostname(hostname: str, port: int | None) -> None:
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


def _validate_remote_media_url(url: str, max_length: int = MAX_URL_LENGTH) -> str:
    cleaned_url = url.strip()
    if len(cleaned_url) > max_length:
        raise HTTPException(status_code=400, detail="URL muito longa.")

    parsed = urlparse(cleaned_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Cole uma URL http(s) válida.")
    return parsed.geturl()


def _cleanup_thumbnail_tokens() -> None:
    now = time.time()
    expired_tokens = [token for token, entry in _thumbnail_tokens.items() if entry["expires_at"] <= now]
    for token in expired_tokens:
        _thumbnail_tokens.pop(token, None)


def _register_thumbnail(thumbnail_url: str | None, webpage_url: str, headers: dict[str, str] | None) -> str | None:
    if not thumbnail_url:
        return None

    try:
        safe_url = _validate_remote_media_url(thumbnail_url, MAX_THUMBNAIL_URL_LENGTH)
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


def _fetch_thumbnail_sync(token: str) -> tuple[bytes, str]:
    _cleanup_thumbnail_tokens()
    entry = _thumbnail_tokens.get(token)
    if not entry:
        raise HTTPException(status_code=404, detail="Miniatura expirada.")

    safe_url = _validate_remote_media_url(entry["url"], MAX_THUMBNAIL_URL_LENGTH)
    request = UrlRequest(safe_url, headers=entry["headers"])
    with urlopen(request, timeout=12) as response:
        content_type = response.headers.get_content_type() or "application/octet-stream"
        if not content_type.startswith("image/"):
            raise HTTPException(status_code=422, detail="A miniatura retornada não é uma imagem.")

        body = response.read(MAX_THUMBNAIL_BYTES + 1)
        if len(body) > MAX_THUMBNAIL_BYTES:
            raise HTTPException(status_code=413, detail="Miniatura muito grande.")

    return body, content_type


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    response = await call_next(request)
    if SECURITY_HEADERS_ENABLED:
        return _add_security_headers(response, request)
    return response


def _public_origin(request: Request) -> str:
    configured_url = os.getenv("PUBLIC_BASE_URL", "").strip()
    if configured_url:
        parsed = urlparse(configured_url)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return configured_url.rstrip("/")

    base_url = str(request.base_url).rstrip("/")
    return base_url


def _absolute_url(request: Request, path: str) -> str:
    return urljoin(f"{_public_origin(request)}/", path.lstrip("/"))


def _render_index(request: Request) -> str:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    canonical_url = _absolute_url(request, "/")
    image_url = _absolute_url(request, "/brand.png")
    return (
        html.replace("__CANONICAL_URL__", canonical_url)
        .replace("__OG_IMAGE_URL__", image_url)
        .replace("__SITE_URL__", _public_origin(request))
    )


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index(request: Request) -> HTMLResponse:
    return HTMLResponse(_render_index(request))


@app.get("/index.html", response_class=HTMLResponse, include_in_schema=False)
async def index_html(request: Request) -> HTMLResponse:
    return HTMLResponse(_render_index(request))


@app.get("/robots.txt", response_class=PlainTextResponse, include_in_schema=False)
async def robots_txt(request: Request) -> PlainTextResponse:
    body = "\n".join(
        [
            "User-agent: *",
            "Allow: /",
            "Disallow: /api/",
            f"Sitemap: {_absolute_url(request, '/sitemap.xml')}",
            "",
        ]
    )
    return PlainTextResponse(body)


@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap_xml(request: Request) -> Response:
    last_modified = (STATIC_DIR / "index.html").stat().st_mtime
    lastmod = datetime.fromtimestamp(last_modified, tz=timezone.utc).date().isoformat()
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>{_absolute_url(request, "/")}</loc>
    <lastmod>{lastmod}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>
</urlset>
"""
    return Response(body, media_type="application/xml")


@app.get("/.well-known/appspecific/com.chrome.devtools.json", include_in_schema=False)
async def chrome_devtools_probe() -> Response:
    return Response(status_code=204)


def _validate_url(url: str) -> str:
    return _validate_remote_media_url(url, MAX_URL_LENGTH)


def _ffmpeg_location() -> str | None:
    if imageio_ffmpeg is not None:
        try:
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            pass
    return shutil.which("ffmpeg")


def _base_ydl_opts() -> dict[str, Any]:
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
    return opts


def _first_video(info: dict[str, Any]) -> dict[str, Any]:
    entries = info.get("entries")
    if entries:
        first = next((entry for entry in entries if entry), None)
        if isinstance(first, dict):
            return first
    return info


def _size_from_format(fmt: dict[str, Any], duration: int | float | None, extra_audio_size: int | None = None) -> tuple[int | None, bool]:
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
    thumbnail_proxy = _register_thumbnail(thumbnail, webpage_url, info.get("http_headers"))
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
    if len(_probe_cache) > 200:
        now = time.time()
        expired_urls = [cache_url for cache_url, (expires_at, _) in _probe_cache.items() if expires_at <= now]
        for cache_url in expired_urls:
            _probe_cache.pop(cache_url, None)

    _probe_cache[url] = (time.time() + PROBE_CACHE_TTL_SECONDS, data)


@app.post("/api/probe")
async def probe_video(payload: ProbeRequest) -> dict[str, Any]:
    url = _validate_url(payload.url)
    logger.info("POST /api/probe recebido: %s", url)

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


@app.get("/api/thumbnail/{token}", include_in_schema=False)
async def thumbnail(token: str) -> Response:
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", token):
        raise HTTPException(status_code=400, detail="Token inválido.")
    try:
        body, content_type = await asyncio.to_thread(_fetch_thumbnail_sync, token)
    except Exception:
        logger.exception("Falha carregando miniatura: token=%s", token)
        raise
    return Response(body, media_type=content_type)


def _select_format(url: str, format_id: str) -> tuple[str, bool]:
    if not FORMAT_ID_RE.match(format_id):
        raise HTTPException(status_code=400, detail="Formato inválido.")

    with YoutubeDL({**_base_ydl_opts(), "skip_download": True}) as ydl:
        info = _first_video(ydl.extract_info(url, download=False))

    for fmt in info.get("formats") or []:
        if str(fmt.get("format_id")) == format_id:
            has_audio = fmt.get("acodec") not in (None, "none")
            needs_merge = not has_audio
            if needs_merge and not _ffmpeg_location():
                raise HTTPException(
                    status_code=422,
                    detail="Esse formato precisa mesclar áudio e vídeo, mas o ffmpeg não está disponível.",
                )
            selector = format_id if has_audio else f"{format_id}+bestaudio[ext=m4a]/best[ext=mp4]/best"
            return selector, needs_merge

    raise HTTPException(status_code=404, detail="Resolução não encontrada para esse vídeo.")


def _ffmpeg_probe_text(file_path: Path) -> str:
    ffmpeg = _ffmpeg_location()
    if not ffmpeg:
        return ""

    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(file_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return f"{result.stdout}\n{result.stderr}".lower()


def _is_whatsapp_compatible_mp4(file_path: Path) -> bool:
    info = _ffmpeg_probe_text(file_path)
    if not info:
        return file_path.suffix.lower() == ".mp4"

    has_h264_video = "video: h264" in info and "yuv420p" in info
    has_audio = "audio:" in info
    has_aac_lc_audio = not has_audio or ("audio: aac" in info and "he-aac" not in info)
    return file_path.suffix.lower() == ".mp4" and has_h264_video and has_aac_lc_audio


def _make_whatsapp_compatible_mp4(file_path: Path) -> Path:
    ffmpeg = _ffmpeg_location()
    if not ffmpeg:
        if file_path.suffix.lower() == ".mp4":
            return file_path
        raise HTTPException(
            status_code=422,
            detail="Esse vídeo precisa ser convertido para MP4 compatível, mas o ffmpeg não está disponível.",
        )

    if _is_whatsapp_compatible_mp4(file_path):
        return file_path

    output_path = file_path.with_name(f"{file_path.stem}-whatsapp.mp4")
    command = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(file_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-vf",
        "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-profile:v",
        "main",
        "-level",
        "4.0",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0 or not output_path.exists():
        logger.error("Falha convertendo MP4 para compatibilidade WhatsApp: %s", result.stderr)
        raise HTTPException(status_code=500, detail="Não consegui converter esse vídeo para MP4 compatível.")

    return output_path


def _download_sync(url: str, format_id: str, temp_dir: Path) -> Path:
    if format_id == AUDIO_MP3_FORMAT_ID:
        if not _ffmpeg_location():
            raise HTTPException(
                status_code=422,
                detail="O download em MP3 precisa do ffmpeg, mas ele não está disponível.",
            )

        opts = {
            **_base_ydl_opts(),
            "format": "bestaudio/best",
            "outtmpl": str(temp_dir / "%(title).180B-%(id)s.%(ext)s"),
            "restrictfilenames": True,
            "noplaylist": True,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
        }

        with YoutubeDL(opts) as ydl:
            ydl.download([url])

        files = sorted(temp_dir.glob("*"), key=lambda path: path.stat().st_mtime, reverse=True)
        audio = next((path for path in files if path.is_file() and path.suffix.lower() == ".mp3"), None)
        if audio is None:
            raise HTTPException(status_code=500, detail="O download terminou, mas o MP3 final não foi encontrado.")
        return audio

    selector, _ = _select_format(url, format_id)
    opts = {
        **_base_ydl_opts(),
        "format": selector,
        "merge_output_format": "mp4",
        "outtmpl": str(temp_dir / "%(title).180B-%(id)s.%(ext)s"),
        "restrictfilenames": True,
        "noplaylist": True,
    }

    with YoutubeDL(opts) as ydl:
        ydl.download([url])

    files = sorted(temp_dir.glob("*"), key=lambda path: path.stat().st_mtime, reverse=True)
    video = next((path for path in files if path.is_file() and path.suffix.lower() in {".mp4", ".m4v", ".mov", ".webm"}), None)
    if video is None:
        raise HTTPException(status_code=500, detail="O download terminou, mas o arquivo final não foi encontrado.")

    return _make_whatsapp_compatible_mp4(video)


@app.get("/api/download")
async def download_video(
    background_tasks: BackgroundTasks,
    url: str = Query(...),
    format_id: str = Query(...),
) -> FileResponse:
    valid_url = _validate_url(url)
    temp_dir = Path(tempfile.mkdtemp(prefix="videodrop-"))
    acquired = False

    try:
        await DOWNLOAD_SEMAPHORE.acquire()
        acquired = True

        file_path = await asyncio.to_thread(_download_sync, valid_url, format_id, temp_dir)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    finally:
        if acquired:
            DOWNLOAD_SEMAPHORE.release()

    background_tasks.add_task(shutil.rmtree, temp_dir, True)
    media_type = "audio/mpeg" if file_path.suffix.lower() == ".mp3" else "video/mp4"
    return FileResponse(
        file_path,
        media_type=media_type,
        filename=file_path.name,
        background=background_tasks,
    )


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
