"""Dedicated browser login helpers for local VideoDrop sessions."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .config import dedicated_firefox_profile_dir

INSTAGRAM_LOGIN_URL = "https://www.instagram.com/accounts/login/"


class FirefoxNotFoundError(RuntimeError):
    """Raised when the dedicated login flow cannot find Firefox."""


def firefox_candidates() -> list[Path]:
    candidates = [
        os.getenv("FIREFOX_EXE"),
        shutil.which("firefox"),
        os.getenv("LOCALAPPDATA", "") + r"\Mozilla Firefox\firefox.exe",
        os.getenv("PROGRAMFILES", "") + r"\Mozilla Firefox\firefox.exe",
        os.getenv("PROGRAMFILES(X86)", "") + r"\Mozilla Firefox\firefox.exe",
    ]
    return [Path(candidate) for candidate in candidates if candidate and Path(candidate).exists()]


def find_firefox_executable() -> Path | None:
    candidates = firefox_candidates()
    return candidates[0] if candidates else None


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
        INSTAGRAM_LOGIN_URL,
    ]
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"ok": True, "browser": "firefox"}
