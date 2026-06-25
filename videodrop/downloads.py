"""Download, conversion and media compatibility helpers."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from fastapi import HTTPException
from yt_dlp import YoutubeDL

from .config import (
    AUDIO_MP3_FORMAT_ID,
    DOWNLOAD_SEMAPHORE,
    FORMAT_ID_RE,
    _base_ydl_opts,
    _ffmpeg_location,
    logger,
)
from .extractor import _first_video


def _select_format(url: str, format_id: str) -> tuple[str, bool]:
    """Translate a UI format id into a yt-dlp selector."""
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
    """Return ffmpeg stream metadata as lowercase text."""
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
    """Check the MP4 profile most reliably accepted by WhatsApp."""
    info = _ffmpeg_probe_text(file_path)
    if not info:
        return file_path.suffix.lower() == ".mp4"

    has_h264_video = "video: h264" in info and "yuv420p" in info
    has_audio = "audio:" in info
    has_aac_lc_audio = not has_audio or ("audio: aac" in info and "he-aac" not in info)
    return file_path.suffix.lower() == ".mp4" and has_h264_video and has_aac_lc_audio


def _make_whatsapp_compatible_mp4(file_path: Path) -> Path:
    """Normalize videos to H.264/AAC MP4 when the source codec is risky."""
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
    """Download one selected video format or extract MP3 audio into temp_dir."""
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


async def download_to_temp(url: str, format_id: str, temp_dir: Path) -> Path:
    """Run a serialized download in a worker thread."""
    acquired = False
    try:
        await DOWNLOAD_SEMAPHORE.acquire()
        acquired = True
        return await asyncio.to_thread(_download_sync, url, format_id, temp_dir)
    finally:
        if acquired:
            DOWNLOAD_SEMAPHORE.release()


async def convert_recording_to_whatsapp_mp4(file_path: Path) -> Path:
    """Convert a local browser recording to an MP4 accepted by native share targets."""
    acquired = False
    try:
        await DOWNLOAD_SEMAPHORE.acquire()
        acquired = True
        return await asyncio.to_thread(_make_whatsapp_compatible_mp4, file_path)
    finally:
        if acquired:
            DOWNLOAD_SEMAPHORE.release()
