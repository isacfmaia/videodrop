from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app as app_module
from videodrop import downloads, extractor, thumbnails
from videodrop.config import _base_ydl_opts


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


def test_screen_recorder_ui_is_available_with_audio_toggles_off_by_default():
    html = (app_module.STATIC_DIR / "index.html").read_text(encoding="utf-8")

    assert 'id="screenRecordButton"' in html
    assert "Gravar tela" in html
    assert 'id="systemAudioToggle" type="checkbox"' in html
    assert 'id="microphoneToggle" type="checkbox"' in html
    assert 'id="systemAudioToggle" type="checkbox" checked' not in html
    assert 'id="microphoneToggle" type="checkbox" checked' not in html
    assert 'id="recordingDock" hidden' in html
    assert '<button class="ghost-button share-button" type="button">Compartilhar</button>' in html
    assert '<button class="ghost-button share-button" type="button">WhatsApp</button>' not in html


def test_browser_login_controls_are_available_for_local_instagram_cookies():
    html = (app_module.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    app_js = (app_module.STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert 'id="browserAuthPanel" hidden' in html
    assert 'id="browserAuthToggle" type="checkbox"' in html
    assert 'id="browserAuthSelect"' in html
    assert '<option value="edge">Edge</option>' in html
    assert "function browserCookieAuthAvailable()" in app_js
    assert "activeCookieBrowser()" in app_js
    assert 'payload.cookie_browser = cookieBrowser' in app_js
    assert 'params.set("cookie_browser", cookieBrowser)' in app_js


def test_screen_recorder_uses_browser_capture_and_share_apis():
    app_js = (app_module.STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert "navigator.mediaDevices.getDisplayMedia(displayOptions)" in app_js
    assert "navigator.mediaDevices.getUserMedia({ audio: true })" in app_js
    assert "new MediaRecorder(recordingStream" in app_js
    assert "MediaRecorder.isTypeSupported(type)" in app_js
    assert "createMediaStreamDestination()" in app_js
    assert "navigator.canShare(payload)" in app_js
    assert "navigator.share(preparedSharePayload)" in app_js
    assert 'fetch("/api/recordings/whatsapp"' in app_js
    assert "Convertendo gravação para MP4" in app_js
    assert "Seu navegador não aceitou compartilhar esse WebM" not in app_js


def test_screen_recorder_generates_srt_caption_download_when_microphone_is_used():
    app_js = (app_module.STATIC_DIR / "app.js").read_text(encoding="utf-8")
    recorder_helpers = app_js.split("// Screen recording flow.", 1)[1].split("// Chrome/Windows", 1)[0]

    assert 'const CAPTION_LANGUAGE = "pt-BR";' in app_js
    assert "window.SpeechRecognition || window.webkitSpeechRecognition" in recorder_helpers
    assert "recognition.lang = CAPTION_LANGUAGE" in recorder_helpers
    assert "recognition.continuous = true" in recorder_helpers
    assert "recognition.interimResults = true" in recorder_helpers
    assert "recognition.maxAlternatives = 1" in recorder_helpers
    assert "captionsRequestedForRecording ? buildCaptionFile(file.name, durationSeconds) : null" in recorder_helpers
    assert 'videoFileName.replace(/\\.webm$/i, ".srt")' in recorder_helpers
    assert 'type: "application/x-subrip;charset=utf-8"' in recorder_helpers
    assert "Baixar legenda" in recorder_helpers
    assert "Legendas indisponíveis neste navegador." in recorder_helpers
    assert '<button class="ghost-button recording-share-button" type="button">Compartilhar</button>' in recorder_helpers
    assert '<button class="ghost-button recording-share-button" type="button">WhatsApp</button>' not in recorder_helpers


def test_microphone_capture_failure_keeps_screen_recording_available():
    app_js = (app_module.STATIC_DIR / "app.js").read_text(encoding="utf-8")
    recorder_helpers = app_js.split("// Screen recording flow.", 1)[1].split("// Chrome/Windows", 1)[0]

    assert "const MICROPHONE_REQUEST_TIMEOUT_MS = 10000;" in app_js
    assert "async function requestOptionalMicrophoneStream()" in recorder_helpers
    assert "navigator.mediaDevices.getUserMedia({ audio: true })" in recorder_helpers
    assert "await Promise.race([" in recorder_helpers
    assert "MICROPHONE_REQUEST_TIMEOUT_MS" in recorder_helpers
    assert "return null;" in recorder_helpers
    assert "microphoneStream = await requestOptionalMicrophoneStream();" in recorder_helpers
    assert "resetCaptionCapture(hasMicrophoneAudio)" in recorder_helpers
    assert "A gravação seguirá sem microfone." in recorder_helpers


def test_switching_between_download_and_recording_clears_previous_results():
    app_js = (app_module.STATIC_DIR / "app.js").read_text(encoding="utf-8")
    recorder_helpers = app_js.split("// Screen recording flow.", 1)[1].split("// Chrome/Windows", 1)[0]
    analyze_flow = app_js.split("// URL analysis flow.", 1)[1]

    assert "function clearRecordingResultState()" in app_js
    assert "renderRecordingStartingState();" in recorder_helpers
    assert "activeController?.abort();" in recorder_helpers
    assert "currentData = null;" in recorder_helpers
    assert "clearRecordingResultState();" in analyze_flow
    assert "closeShareSheet();" in analyze_flow


def test_security_headers_allow_screen_capture_and_microphone():
    security_py = (app_module.STATIC_DIR.parent / "videodrop" / "security.py").read_text(encoding="utf-8")

    assert "microphone=(self)" in security_py
    assert "display-capture=(self)" in security_py


def test_desktop_launcher_has_tray_mode_browser_app_without_hosts_alias():
    desktop_py = (app_module.STATIC_DIR.parent / "videodrop" / "desktop.py").read_text(encoding="utf-8")
    config_py = (app_module.STATIC_DIR.parent / "videodrop" / "config.py").read_text(encoding="utf-8")

    assert 'MenuItem("Abrir VideoDrop"' in desktop_py
    assert 'MenuItem("Abrir no navegador"' in desktop_py
    assert 'MenuItem("Encerrar"' in desktop_py
    assert "focus_or_open_app_window" in desktop_py
    assert "activate_existing_instance()" in desktop_py
    assert "notify_existing_instance(state)" in desktop_py
    assert 'urljoin(url, "/api/desktop/open")' in desktop_py
    assert "SetForegroundWindow" in desktop_py
    assert "if self.browser_process is not None:" in desktop_py
    assert "allow_title_fallback: bool = True" in desktop_py
    assert "launch_browser_app(existing_url)" not in desktop_py
    assert 'f"--app={url}"' in desktop_py
    assert '"--start-maximized"' in desktop_py
    assert 'return trusted_local_url(self.port)' in desktop_py
    assert "--install-hosts" not in desktop_py
    assert "--uninstall-hosts" not in desktop_py
    assert "hosts" not in desktop_py.lower()
    assert "CreateMutexW" in desktop_py
    assert "ensure_standard_streams()" in desktop_py
    assert "def isatty(self) -> bool:" in desktop_py
    assert "logging.NullHandler()" in desktop_py
    assert "log_config=None" in desktop_py
    assert "sys._MEIPASS" in config_py


def test_desktop_open_endpoint_invokes_registered_callback(client):
    calls = []
    app_module.app.state.desktop_open_callback = lambda: calls.append("open")

    try:
        response = client.post("/api/desktop/open")
    finally:
        app_module.app.state.desktop_open_callback = None

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert calls == ["open"]


def test_screen_recorder_explains_insecure_local_alias_limitation():
    app_js = (app_module.STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert "window.isSecureContext" in app_js
    assert "http://127.0.0.1:8000" in app_js


def test_windows_packaging_scripts_include_icon_installer_and_shortcuts():
    root = app_module.STATIC_DIR.parent
    requirements = (root / "requirements-desktop.txt").read_text(encoding="utf-8")
    build_script = (root / "scripts" / "build_windows.ps1").read_text(encoding="utf-8")
    icon_script = (root / "scripts" / "make_windows_icon.py").read_text(encoding="utf-8")
    installer = (root / "installer" / "videodrop.iss").read_text(encoding="utf-8")

    assert "pystray" in requirements
    assert "pyinstaller" in requirements
    assert "Pillow" in requirements
    assert "pip install --upgrade -r" in build_script
    assert "videodrop.ico" in build_script
    assert "--windowed" in build_script
    assert "--collect-all\", \"yt_dlp" in build_script
    assert "icon-512.png" in icon_script
    assert "Name: \"{userdesktop}\\VideoDrop\"" in installer
    assert "Name: \"{userstartup}\\VideoDrop\"" in installer
    assert "PrivilegesRequired=lowest" in installer
    assert '#define MyAppVersion "1.0.10"' in installer
    assert "--install-hosts" not in installer
    assert "hosts" not in installer.lower()


def test_share_sheet_button_icon_keeps_compact_layout():
    styles = (app_module.STATIC_DIR / "styles.css").read_text(encoding="utf-8")

    assert ".share-sheet-actions .primary-button svg" in styles
    assert "width: 22px" in styles
    assert "height: 22px" in styles
    assert "white-space: nowrap" in styles


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


def test_probe_passes_local_browser_cookie_source(client, monkeypatch):
    calls = []

    def fake_probe(url: str, cookie_browser: str | None = None):
        calls.append((url, cookie_browser))
        return {
            "title": "Instagram",
            "site": "Instagram",
            "duration": 10,
            "thumbnail": None,
            "thumbnail_proxy": None,
            "webpage_url": url,
            "formats": [{"format_id": "720", "resolution": "720p"}],
            "can_merge": True,
        }

    monkeypatch.setattr(extractor, "_probe_sync", fake_probe)

    response = client.post(
        "/api/probe",
        json={"url": "https://www.instagram.com/reel/example/", "cookie_browser": "edge"},
    )

    assert response.status_code == 200
    assert calls == [("https://www.instagram.com/reel/example/", "edge")]


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


def test_recording_whatsapp_endpoint_converts_local_webm_to_mp4(client, monkeypatch):
    async def fake_convert(file_path: Path):
        assert file_path.read_bytes() == b"fake webm"
        output_path = file_path.with_name("gravacao-whatsapp.mp4")
        output_path.write_bytes(b"fake mp4")
        return output_path

    monkeypatch.setattr(downloads, "convert_recording_to_whatsapp_mp4", fake_convert)

    response = client.post(
        "/api/recordings/whatsapp",
        content=b"fake webm",
        headers={"content-type": "video/webm"},
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


def test_download_passes_local_browser_cookie_source(client, monkeypatch):
    calls = []

    def fake_download(_url: str, _format_id: str, temp_dir: Path, cookie_browser: str | None = None):
        calls.append(cookie_browser)
        file_path = temp_dir / "video.mp4"
        file_path.write_bytes(b"fake mp4")
        return file_path

    monkeypatch.setattr(downloads, "_download_sync", fake_download)

    response = client.get(
        "/api/download",
        params={
            "url": "https://www.instagram.com/reel/example/",
            "format_id": "720",
            "cookie_browser": "edge",
        },
    )

    assert response.status_code == 200
    assert calls == ["edge"]


def test_yt_dlp_options_include_browser_cookie_source():
    assert _base_ydl_opts("edge")["cookiesfrombrowser"] == ("edge",)


def test_chrome_cookie_copy_error_is_humanized():
    detail = extractor._friendly_ydl_error_detail(
        Exception(
            "ERROR: ERROR: Could not copy Chrome cookie database. "
            "See https://github.com/yt-dlp/yt-dlp/issues/7271 for more info"
        ),
        "chrome",
    )

    assert "Chrome bloqueou o banco de cookies" in detail
    assert "Feche todas as janelas do Chrome" in detail
    assert "ERROR:" not in detail
    assert "github.com" not in detail


def test_chrome_dpapi_error_is_humanized():
    detail = extractor._friendly_ydl_error_detail(
        Exception(
            "Failed to decrypt with DPAPI. "
            "See https://github.com/yt-dlp/yt-dlp/issues/10927 for more info"
        ),
        "chrome",
    )

    assert "Windows nao liberou a descriptografia dos cookies do Chrome" in detail
    assert "mesmo usuario do Windows" in detail
    assert "sem executar como administrador" in detail
    assert "github.com" not in detail


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


def test_ffmpeg_subprocesses_are_hidden_on_windows():
    downloads_py = (app_module.STATIC_DIR.parent / "videodrop" / "downloads.py").read_text(encoding="utf-8")

    assert "def _hidden_ffmpeg_window_kwargs()" in downloads_py
    assert "subprocess.STARTF_USESHOWWINDOW" in downloads_py
    assert "CREATE_NO_WINDOW" in downloads_py
    assert downloads_py.count("**_hidden_ffmpeg_window_kwargs()") == 2


def test_share_button_prepares_file_with_download_fallback_then_uses_native_share():
    app_js = (app_module.STATIC_DIR / "app.js").read_text(encoding="utf-8")
    html = (app_module.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    share_function = app_js.split("async function shareToWhatsApp", 1)[1].split("function renderFormats", 1)[0]
    prepared_share_function = app_js.split("async function sharePreparedFile", 1)[1].split("async function shareToWhatsApp", 1)[0]

    assert 'id="shareSheetDownload"' in html
    assert "fetch(url)" in share_function
    assert "showShareSheet(file)" in share_function
    assert 'triggerButton.textContent = "Preparando..."' in share_function
    assert "Preparando arquivo para compartilhar..." in share_function
    assert "triggerButton.disabled = true" in share_function
    assert "URL.createObjectURL(file)" in app_js
    assert "shareSheetDownload.download = file.name" in app_js
    assert "clearPreparedShareFile()" in app_js
    assert "O compartilhamento do Windows falhou." in prepared_share_function
    assert "navigator.canShare(payload)" in app_js
    assert "navigator.share(payload)" not in app_js
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
    assert "event.preventDefault();" in download_helpers
    assert "startBrowserDownload(href)" in download_helpers
    assert "document.createElement(\"a\")" in download_helpers
    assert 'triggerLink.textContent = isLoading ? "Preparando..."' in download_helpers
    assert 'pasteHint.textContent = "Preparando download..."' in download_helpers
    assert "download.addEventListener(\"click\", (event) => prepareDownload(format, download, event))" in render_formats
