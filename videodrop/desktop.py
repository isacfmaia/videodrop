"""Windows desktop launcher for the local VideoDrop web app."""

from __future__ import annotations

import argparse
import ctypes
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Sequence

import uvicorn

from .config import STATIC_DIR
from .main import create_app

APP_NAME = "VideoDrop"
DEFAULT_PORT = int(os.getenv("VIDEODROP_DESKTOP_PORT", "8000"))
HOST = "127.0.0.1"
MUTEX_NAME = "Local\\VideoDropDesktop"
ERROR_ALREADY_EXISTS = 183

_mutex_handle: int | None = None


class NullStream:
    """Small stream used by windowed PyInstaller apps when stdio is absent."""

    encoding = "utf-8"

    def write(self, _text: str) -> int:
        return 0

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        return False


def ensure_standard_streams() -> None:
    if sys.stdout is None:
        sys.stdout = NullStream()  # type: ignore[assignment]
    if sys.stderr is None:
        sys.stderr = NullStream()  # type: ignore[assignment]


def app_data_dir() -> Path:
    base = os.getenv("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Local"
    path = root / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def setup_logging() -> None:
    ensure_standard_streams()
    log_dir = app_data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    try:
        logging.basicConfig(
            filename=log_dir / "desktop.log",
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
            force=True,
        )
    except OSError:
        logging.basicConfig(level=logging.INFO, handlers=[logging.NullHandler()], force=True)


def runtime_state_path() -> Path:
    return app_data_dir() / "runtime.json"


def write_runtime_state(url: str, port: int) -> None:
    runtime_state_path().write_text(
        json.dumps({"url": url, "port": port}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def read_runtime_url() -> str | None:
    try:
        data = json.loads(runtime_state_path().read_text(encoding="utf-8"))
    except Exception:
        return None
    url = data.get("url")
    return url if isinstance(url, str) and url.startswith("http") else None


def remove_runtime_state() -> None:
    runtime_state_path().unlink(missing_ok=True)


def is_windows() -> bool:
    return sys.platform.startswith("win")


def message_box(message: str, title: str = APP_NAME) -> None:
    if is_windows():
        ctypes.windll.user32.MessageBoxW(None, message, title, 0x00000040)
    else:
        print(f"{title}: {message}", file=sys.stderr)


def acquire_single_instance() -> bool:
    global _mutex_handle
    if not is_windows():
        return True
    _mutex_handle = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    return ctypes.windll.kernel32.GetLastError() != ERROR_ALREADY_EXISTS


def trusted_local_url(port: int) -> str:
    """Use a loopback IP so browser capture APIs remain available."""
    return f"http://{HOST}:{port}/"


def port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((HOST, port))
        except OSError:
            return False
    return True


def choose_port(preferred: int) -> int:
    for port in range(preferred, preferred + 20):
        if port_available(port):
            return port
    raise RuntimeError("Não encontrei uma porta local livre para o VideoDrop.")


def browser_candidates() -> list[Path]:
    candidates = [
        shutil.which("msedge"),
        shutil.which("chrome"),
        os.getenv("PROGRAMFILES", "") + r"\Microsoft\Edge\Application\msedge.exe",
        os.getenv("PROGRAMFILES(X86)", "") + r"\Microsoft\Edge\Application\msedge.exe",
        os.getenv("LOCALAPPDATA", "") + r"\Google\Chrome\Application\chrome.exe",
        os.getenv("PROGRAMFILES", "") + r"\Google\Chrome\Application\chrome.exe",
        os.getenv("PROGRAMFILES(X86)", "") + r"\Google\Chrome\Application\chrome.exe",
    ]
    return [Path(candidate) for candidate in candidates if candidate and Path(candidate).exists()]


def launch_browser_app(url: str) -> subprocess.Popen[bytes] | None:
    browsers = browser_candidates()
    if not browsers:
        webbrowser.open(url)
        return None

    profile_dir = app_data_dir() / "BrowserProfile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    args = [
        str(browsers[0]),
        f"--app={url}",
        "--new-window",
        "--start-maximized",
        "--no-first-run",
        "--disable-features=Translate",
        f"--user-data-dir={profile_dir}",
    ]
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class DesktopRuntime:
    def __init__(self, preferred_port: int = DEFAULT_PORT) -> None:
        self.port = choose_port(preferred_port)
        self.url = self.build_url()
        self.server: uvicorn.Server | None = None
        self.server_thread: threading.Thread | None = None
        self.tray_icon = None
        self.browser_process: subprocess.Popen[bytes] | None = None
        self.stopping = threading.Event()

    def build_url(self) -> str:
        return trusted_local_url(self.port)

    def start_server(self) -> None:
        config = uvicorn.Config(
            create_app(),
            host=HOST,
            port=self.port,
            log_level="warning",
            access_log=False,
            log_config=None,
        )
        self.server = uvicorn.Server(config)
        self.server_thread = threading.Thread(target=self.server.run, name="VideoDropServer", daemon=True)
        self.server_thread.start()
        self.wait_for_server()
        write_runtime_state(self.url, self.port)

    def wait_for_server(self) -> None:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                with socket.create_connection((HOST, self.port), timeout=0.25):
                    return
            except OSError:
                time.sleep(0.15)
        raise RuntimeError("O servidor local do VideoDrop não iniciou a tempo.")

    def open_app_window(self) -> None:
        self.browser_process = launch_browser_app(self.url)

    def open_in_browser(self) -> None:
        webbrowser.open(self.url)

    def tray_image(self):
        from PIL import Image

        image_path = STATIC_DIR / "icon-512.png"
        if not image_path.exists():
            image_path = STATIC_DIR / "brand.png"
        image = Image.open(image_path)
        return image.resize((64, 64))

    def start_tray(self) -> None:
        from pystray import Icon, Menu, MenuItem

        self.tray_icon = Icon(
            APP_NAME,
            self.tray_image(),
            APP_NAME,
            menu=Menu(
                MenuItem("Abrir VideoDrop", lambda _icon, _item: self.open_app_window(), default=True),
                MenuItem("Abrir no navegador", lambda _icon, _item: self.open_in_browser()),
                MenuItem("Encerrar", lambda _icon, _item: self.stop()),
            ),
        )
        threading.Thread(target=self.tray_icon.run, name="VideoDropTray", daemon=True).start()

    def stop(self) -> None:
        if self.stopping.is_set():
            return
        self.stopping.set()
        remove_runtime_state()

        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except Exception:
                logging.exception("Falha ao parar o ícone da bandeja.")

        if self.server is not None:
            self.server.should_exit = True

        if self.browser_process is not None and self.browser_process.poll() is None:
            try:
                self.browser_process.terminate()
            except Exception:
                logging.exception("Falha ao encerrar a janela do navegador.")

    def run(self, open_window: bool = True) -> int:
        self.start_server()
        self.start_tray()
        if open_window:
            self.open_app_window()

        while not self.stopping.wait(0.25):
            pass
        return 0


def run_desktop(preferred_port: int, open_window: bool) -> int:
    setup_logging()
    if not acquire_single_instance():
        existing_url = read_runtime_url()
        if existing_url:
            launch_browser_app(existing_url)
        return 0

    runtime = DesktopRuntime(preferred_port=preferred_port)
    try:
        return runtime.run(open_window=open_window)
    except Exception as exc:
        logging.exception("Falha iniciando o VideoDrop Desktop.")
        message_box(f"Não consegui iniciar o VideoDrop.\n\n{exc}")
        runtime.stop()
        return 1


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="VideoDrop Desktop")
    parser.add_argument("--no-open", action="store_true", help="Inicia apenas na bandeja.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Porta local preferencial.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    return run_desktop(preferred_port=args.port, open_window=not args.no_open)


if __name__ == "__main__":
    raise SystemExit(main())
