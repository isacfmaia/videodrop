"""HTTP routes for the VideoDrop web UI and public API."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response

from . import downloads, extractor, thumbnails
from .browser_auth import FirefoxNotFoundError, close_dedicated_firefox_login, launch_dedicated_firefox_login
from .config import (
    MAX_RECORDING_UPLOAD_BYTES,
    STATIC_DIR,
    logger,
    normalize_cookie_browser,
)
from .schemas import ProbeRequest
from .security import validate_url

router = APIRouter()


def _is_local_client(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host == "testclient" or host == "localhost" or host == "::1" or host.startswith("127.")


def _cookie_browser_for_request(request: Request, cookie_browser: str | None) -> str | None:
    if not cookie_browser:
        return None
    if not _is_local_client(request):
        raise HTTPException(status_code=403, detail="Login dedicado disponivel apenas no app local.")
    try:
        return normalize_cookie_browser(cookie_browser)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Navegador de login invalido.") from exc


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
    """Inject deployment-specific SEO URLs into the static HTML shell."""
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    canonical_url = _absolute_url(request, "/")
    image_url = _absolute_url(request, "/brand.png")
    return (
        html.replace("__CANONICAL_URL__", canonical_url)
        .replace("__OG_IMAGE_URL__", image_url)
        .replace("__SITE_URL__", _public_origin(request))
    )


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index(request: Request) -> HTMLResponse:
    return HTMLResponse(_render_index(request))


@router.get("/index.html", response_class=HTMLResponse, include_in_schema=False)
async def index_html(request: Request) -> HTMLResponse:
    return HTMLResponse(_render_index(request))


@router.get("/robots.txt", response_class=PlainTextResponse, include_in_schema=False)
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


@router.get("/sitemap.xml", include_in_schema=False)
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


@router.get("/.well-known/appspecific/com.chrome.devtools.json", include_in_schema=False)
async def chrome_devtools_probe() -> Response:
    return Response(status_code=204)


@router.post("/api/desktop/open", include_in_schema=False)
async def desktop_open(request: Request) -> dict[str, bool]:
    if not _is_local_client(request):
        raise HTTPException(status_code=403, detail="Controle desktop disponível apenas localmente.")

    callback = getattr(request.app.state, "desktop_open_callback", None)
    if not callable(callback):
        return {"ok": False}

    await asyncio.to_thread(callback)
    return {"ok": True}


@router.post("/api/browser-login/instagram")
async def browser_login_instagram(request: Request) -> dict[str, str | bool]:
    if not _is_local_client(request):
        raise HTTPException(status_code=403, detail="Login dedicado disponivel apenas no app local.")

    try:
        return await asyncio.to_thread(launch_dedicated_firefox_login)
    except FirefoxNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        logger.exception("Sem permissao para criar ou usar o perfil Firefox dedicado.")
        raise HTTPException(
            status_code=500,
            detail="Nao consegui criar o perfil Firefox do VideoDrop. Feche o app e abra normalmente, sem administrador.",
        ) from exc
    except OSError as exc:
        logger.exception("Falha abrindo Firefox dedicado para login do Instagram.")
        raise HTTPException(status_code=500, detail="Nao consegui abrir o Firefox para login.") from exc


@router.post("/api/browser-login/instagram/close")
async def browser_login_instagram_close(request: Request) -> dict[str, int | bool]:
    if not _is_local_client(request):
        raise HTTPException(status_code=403, detail="Login dedicado disponivel apenas no app local.")

    try:
        return await asyncio.to_thread(close_dedicated_firefox_login)
    except OSError as exc:
        logger.exception("Falha fechando Firefox dedicado do VideoDrop.")
        raise HTTPException(status_code=500, detail="Nao consegui fechar o Firefox dedicado.") from exc


@router.post("/api/probe")
async def probe_video(payload: ProbeRequest, request: Request) -> dict:
    url = validate_url(payload.url)
    cookie_browser = _cookie_browser_for_request(request, payload.cookie_browser)
    logger.info("POST /api/probe recebido: %s cookies=%s", url, cookie_browser or "nao")
    return await extractor.probe_url(url, cookie_browser)


@router.get("/api/thumbnail/{token}", include_in_schema=False)
async def thumbnail(token: str) -> Response:
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", token):
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="Token inválido.")
    try:
        body, content_type = await asyncio.to_thread(thumbnails.fetch_thumbnail_sync, token)
    except Exception:
        logger.exception("Falha carregando miniatura: token=%s", token)
        raise
    return Response(body, media_type=content_type)


@router.get("/api/download")
async def download_video(
    request: Request,
    background_tasks: BackgroundTasks,
    url: str = Query(...),
    format_id: str = Query(...),
    download_token: str | None = Query(default=None),
    cookie_browser: str | None = Query(default=None),
) -> FileResponse:
    valid_url = validate_url(url)
    valid_cookie_browser = _cookie_browser_for_request(request, cookie_browser)
    temp_dir = Path(tempfile.mkdtemp(prefix="videodrop-"))

    try:
        file_path = await downloads.download_to_temp(valid_url, format_id, temp_dir, valid_cookie_browser)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise

    background_tasks.add_task(shutil.rmtree, temp_dir, True)
    media_type = "audio/mpeg" if file_path.suffix.lower() == ".mp3" else "video/mp4"
    response = FileResponse(
        file_path,
        media_type=media_type,
        filename=file_path.name,
        background=background_tasks,
    )
    if download_token and re.fullmatch(r"[A-Za-z0-9_-]{8,80}", download_token):
        response.set_cookie(
            key=f"videodrop_download_{download_token}",
            value="ready",
            max_age=60,
            path="/",
            samesite="lax",
        )
    return response


@router.post("/api/recordings/whatsapp")
async def convert_recording_for_whatsapp(request: Request, background_tasks: BackgroundTasks) -> FileResponse:
    if not _is_local_client(request):
        raise HTTPException(status_code=403, detail="Conversão de gravação disponível apenas localmente.")

    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type and content_type not in {"video/webm", "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="Envie uma gravação WebM.")

    temp_dir = Path(tempfile.mkdtemp(prefix="videodrop-recording-"))
    input_path = temp_dir / "gravacao.webm"
    total_bytes = 0

    try:
        with input_path.open("wb") as output:
            async for chunk in request.stream():
                total_bytes += len(chunk)
                if total_bytes > MAX_RECORDING_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Gravação grande demais para converter localmente.")
                output.write(chunk)

        if total_bytes == 0:
            raise HTTPException(status_code=400, detail="Gravação vazia.")

        file_path = await downloads.convert_recording_to_whatsapp_mp4(input_path)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise

    background_tasks.add_task(shutil.rmtree, temp_dir, True)
    return FileResponse(
        file_path,
        media_type="video/mp4",
        filename="videodrop-gravacao-whatsapp.mp4",
        background=background_tasks,
    )
