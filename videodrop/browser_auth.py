"""Dedicated browser login helpers for local VideoDrop sessions."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .config import dedicated_firefox_profile_dir

INSTAGRAM_LOGIN_URL = "https://www.instagram.com/accounts/login/"


class FirefoxNotFoundError(RuntimeError):
    """Raised when the dedicated login flow cannot find Firefox."""


def _registry_firefox_candidates() -> list[Path]:
    if not sys.platform.startswith("win"):
        return []

    try:
        import winreg
    except Exception:
        return []

    candidates: list[Path] = []
    app_path_keys = [
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\firefox.exe",
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\firefox.exe",
    ]
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for key_path in app_path_keys:
            try:
                with winreg.OpenKey(root, key_path) as key:
                    value, _ = winreg.QueryValueEx(key, "")
                    if value:
                        candidates.append(Path(value))
            except OSError:
                pass

    mozilla_roots = [
        r"SOFTWARE\Mozilla\Mozilla Firefox",
        r"SOFTWARE\WOW6432Node\Mozilla\Mozilla Firefox",
    ]
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for key_path in mozilla_roots:
            try:
                with winreg.OpenKey(root, key_path) as key:
                    version, _ = winreg.QueryValueEx(key, "CurrentVersion")
                with winreg.OpenKey(root, rf"{key_path}\{version}\Main") as key:
                    value, _ = winreg.QueryValueEx(key, "PathToExe")
                    if value:
                        candidates.append(Path(value))
            except OSError:
                pass

    return candidates


def firefox_candidates() -> list[Path]:
    candidates = [
        os.getenv("FIREFOX_EXE"),
        shutil.which("firefox"),
        shutil.which("firefox.exe"),
        os.getenv("LOCALAPPDATA", "") + r"\Mozilla Firefox\firefox.exe",
        os.getenv("LOCALAPPDATA", "") + r"\Programs\Mozilla Firefox\firefox.exe",
        os.getenv("LOCALAPPDATA", "") + r"\Microsoft\WindowsApps\firefox.exe",
        os.getenv("PROGRAMFILES", "") + r"\Mozilla Firefox\firefox.exe",
        os.getenv("PROGRAMFILES(X86)", "") + r"\Mozilla Firefox\firefox.exe",
    ]
    found: list[Path] = []
    seen: set[str] = set()
    for candidate in [*candidates, *_registry_firefox_candidates()]:
        if not candidate:
            continue
        path = Path(candidate)
        key = str(path).lower()
        if key in seen or not path.exists():
            continue
        seen.add(key)
        found.append(path)
    return found


def find_firefox_executable() -> Path | None:
    candidates = firefox_candidates()
    return candidates[0] if candidates else None


def _hidden_process_kwargs() -> dict[str, int | subprocess.STARTUPINFO]:
    if not sys.platform.startswith("win"):
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return {"startupinfo": startupinfo, "creationflags": subprocess.CREATE_NO_WINDOW}


def launch_dedicated_firefox_login() -> dict[str, str | bool]:
    firefox = find_firefox_executable()
    if firefox is None:
        raise FirefoxNotFoundError("Instale o Firefox para usar o Login dedicado do VideoDrop com Instagram.")

    profile_dir = dedicated_firefox_profile_dir(create=True)
    args = [
        str(firefox),
        "-no-remote",
        "-profile",
        str(profile_dir),
        "-new-window",
        INSTAGRAM_LOGIN_URL,
    ]
    process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.5)
    if process.poll() is not None:
        if process.returncode == 0:
            return {"ok": True, "browser": "firefox", "pid": "", "path": str(firefox)}
        raise OSError(f"O Firefox fechou logo apos abrir. Codigo: {process.returncode}")
    return {"ok": True, "browser": "firefox", "pid": str(process.pid), "path": str(firefox)}


def close_dedicated_firefox_login() -> dict[str, int | bool]:
    """Close only Firefox processes launched with VideoDrop's dedicated profile."""
    if not sys.platform.startswith("win"):
        return {"ok": True, "closed": 0}

    profile_dir = dedicated_firefox_profile_dir()
    command = (
        "$profile = $env:VIDEODROP_FIREFOX_PROFILE_MATCH; "
        "$ids = @(Get-CimInstance Win32_Process -Filter \"name = 'firefox.exe'\" | "
        "Where-Object { $_.CommandLine -and $_.CommandLine.Contains($profile) } | "
        "Select-Object -ExpandProperty ProcessId); "
        "foreach ($id in $ids) { Stop-Process -Id $id -Force }; "
        "Write-Output $ids.Count"
    )
    env = {**os.environ, "VIDEODROP_FIREFOX_PROFILE_MATCH": str(profile_dir)}
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
        **_hidden_process_kwargs(),
    )
    if completed.returncode != 0:
        raise OSError(completed.stderr.strip() or "Nao consegui fechar o Firefox dedicado.")

    output = completed.stdout.strip().splitlines()
    closed = int(output[-1]) if output and output[-1].isdigit() else 0
    return {"ok": True, "closed": closed}
