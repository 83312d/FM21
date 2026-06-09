"""OGG Opus → MP3 transcode with EBU R128 loudness normalization."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class TranscodeError(Exception):
    """Raised when ffmpeg is unavailable or transcode fails."""


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def transcode_ogg_to_mp3(source: Path, destination: Path) -> None:
    """Transcode OGG to 128kbps MP3 with EBU R128 loudnorm."""
    if not ffmpeg_available():
        raise TranscodeError("ffmpeg not found")

    destination.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-af",
        "loudnorm=I=-16:TP=-1.5:LRA=11",
        "-codec:a",
        "libmp3lame",
        "-b:a",
        "128k",
        str(destination),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "ffmpeg failed").strip()
        raise TranscodeError(detail) from exc

    if not destination.is_file() or destination.stat().st_size == 0:
        raise TranscodeError("transcode produced empty output")
