from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app as app_module
from videodrop import downloads, extractor, thumbnails


@pytest.fixture(autouse=True)
def clear_runtime_state():
    extractor._probe_cache.clear()
    thumbnails._thumbnail_tokens.clear()
    yield
    extractor._probe_cache.clear()
    thumbnails._thumbnail_tokens.clear()


@pytest.fixture
def client():
    return TestClient(app_module.app)


def test_static_routes_and_seo(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "VideoDrop" in response.text
    assert "__CANONICAL_URL__" not in response.text

    assert client.get("/app.js").status_code == 200
    assert client.get("/styles.css").status_code == 200
    assert client.get("/videodrop_loader_animado.svg").status_code == 200
    assert client.get("/.well-known/appspecific/com.chrome.devtools.json").status_code == 204

    robots = client.get("/robots.txt")
    assert robots.status_code == 200
    assert "Sitemap:" in robots.text

    sitemap = client.get("/sitemap.xml")
    assert sitemap.status_code == 200
    assert "<urlset" in sitemap.text


def test_build_format_options_includes_mp3(monkeypatch):
    monkeypatch.setattr(extractor, "_ffmpeg_location", lambda: "ffmpeg")
    info = {
        "duration": 10,
        "formats": [
            {
                "format_id": "v720",
                "ext": "mp4",
                "height": 720,
                "width": 1280,
                "vcodec": "h264",
                "acodec": "none",
                "tbr": 1000,
            },
            {
                "format_id": "a1",
                "ext": "m4a",
                "vcodec": "none",
                "acodec": "aac",
                "abr": 128,
                "filesize": 1000,
            },
        ],
    }

    options = extractor._build_format_options(info)

    assert [option["format_id"] for option in options] == ["v720", "audio-mp3"]
    assert options[-1]["kind"] == "audio"
    assert options[-1]["resolution"] == "MP3"
    assert options[-1]["size_bytes"] == 240000


def test_probe_uses_cache(client, monkeypatch):
    calls = {"count": 0}

    def fake_probe(url: str):
        calls["count"] += 1
        return {
            "title": "Teste",
            "site": "Youtube",
            "duration": 10,
            "thumbnail": None,
            "thumbnail_proxy": None,
            "webpage_url": url,
            "formats": [{"format_id": "audio-mp3", "kind": "audio", "resolution": "MP3"}],
            "can_merge": True,
        }

    monkeypatch.setattr(extractor, "_probe_sync", fake_probe)

    body = {"url": "https://example.com/video"}
    first = client.post("/api/probe", json=body)
    second = client.post("/api/probe", json=body)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["title"] == "Teste"
    assert calls["count"] == 1


def test_probe_returns_yt_dlp_error(client, monkeypatch):
    def fake_probe(_url: str):
        raise HTTPException(status_code=422, detail="Sem formatos")

    monkeypatch.setattr(extractor, "_probe_sync", fake_probe)

    response = client.post("/api/probe", json={"url": "https://example.com/private"})

    assert response.status_code == 422
    assert response.json()["detail"] == "Sem formatos"


def test_download_mp3_sets_audio_media_type(client, monkeypatch):
    def fake_download(_url: str, _format_id: str, temp_dir: Path):
        file_path = temp_dir / "audio.mp3"
        file_path.write_bytes(b"fake mp3")
        return file_path

    monkeypatch.setattr(downloads, "_download_sync", fake_download)

    response = client.get(
        "/api/download",
        params={"url": "https://example.com/video", "format_id": "audio-mp3"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/mpeg")
    assert response.content == b"fake mp3"


def test_download_mp4_sets_video_media_type(client, monkeypatch):
    def fake_download(_url: str, _format_id: str, temp_dir: Path):
        file_path = temp_dir / "video.mp4"
        file_path.write_bytes(b"fake mp4")
        return file_path

    monkeypatch.setattr(downloads, "_download_sync", fake_download)

    response = client.get(
        "/api/download",
        params={"url": "https://example.com/video", "format_id": "720"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("video/mp4")
    assert response.content == b"fake mp4"


def test_download_ready_cookie_is_set_for_valid_token(client, monkeypatch):
    def fake_download(_url: str, _format_id: str, temp_dir: Path):
        file_path = temp_dir / "video.mp4"
        file_path.write_bytes(b"fake mp4")
        return file_path

    monkeypatch.setattr(downloads, "_download_sync", fake_download)

    response = client.get(
        "/api/download",
        params={
            "url": "https://example.com/video",
            "format_id": "720",
            "download_token": "download_token_123",
        },
    )

    assert response.status_code == 200
    assert "videodrop_download_download_token_123=ready" in response.headers["set-cookie"]


def test_thumbnail_rejects_invalid_token(client):
    response = client.get("/api/thumbnail/invalid.token")

    assert response.status_code == 400


def test_whatsapp_compatibility_detection(monkeypatch):
    file_path = Path("video.mp4")

    monkeypatch.setattr(
        downloads,
        "_ffmpeg_probe_text",
        lambda _path: "video: vp9, yuv420p\naudio: aac (he-aac)",
    )
    assert downloads._is_whatsapp_compatible_mp4(file_path) is False

    monkeypatch.setattr(
        downloads,
        "_ffmpeg_probe_text",
        lambda _path: "video: h264 (main), yuv420p\naudio: aac (lc)",
    )
    assert downloads._is_whatsapp_compatible_mp4(file_path) is True


def test_whatsapp_button_prepares_file_then_uses_native_share_without_text_fallback():
    app_js = (app_module.STATIC_DIR / "app.js").read_text(encoding="utf-8")
    share_function = app_js.split("async function shareToWhatsApp", 1)[1].split("function renderFormats", 1)[0]
    prepared_share_function = app_js.split("async function sharePreparedFile", 1)[1].split("async function shareToWhatsApp", 1)[0]

    assert "fetch(url)" in share_function
    assert "showShareSheet(file)" in share_function
    assert 'triggerButton.textContent = "Preparando..."' in share_function
    assert "Preparando arquivo para compartilhar..." in share_function
    assert "triggerButton.disabled = true" in share_function
    assert "navigator.canShare(sharePayload)" in share_function
    assert "navigator.share(sharePayload)" not in share_function
    assert "navigator.share(preparedSharePayload)" in prepared_share_function
    assert "fetch(" not in prepared_share_function
    assert "openWhatsAppFallback" not in app_js
    assert "text:" not in share_function
    assert "https://wa.me/" not in app_js
    assert "window.open" not in app_js


def test_download_button_shows_loading_until_backend_ready_cookie():
    app_js = (app_module.STATIC_DIR / "app.js").read_text(encoding="utf-8")
    download_helpers = app_js.split("function downloadUrl", 1)[1].split("// Chrome/Windows", 1)[0]
    render_formats = app_js.split("function renderFormats", 1)[1].split("// URL analysis flow", 1)[0]

    assert "download_token" in download_helpers
    assert "waitForDownloadReady(cookieName)" in download_helpers
    assert 'triggerLink.textContent = isLoading ? "Preparando..."' in download_helpers
    assert 'pasteHint.textContent = "Preparando download..."' in download_helpers
    assert "download.addEventListener(\"click\", (event) => prepareDownload(format, download, event))" in render_formats
