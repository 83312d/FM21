"""Audio duration probing via ffprobe (ADR-006)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class AudioProbeError(RuntimeError):
    """Raised when ffprobe cannot read duration."""


def ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


def probe_duration_sec(path: Path | str) -> float:
    """Return media duration in seconds (float, rounded to 3 decimals)."""
    if not ffprobe_available():
        raise AudioProbeError("ffprobe not found")

    target = Path(path)
    if not target.is_file():
        raise AudioProbeError(f"audio file not found: {target}")

    result = subprocess.run(
        [
            "ffprobe",
            "-hide_banner",
            "-loglevel",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(target),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "ffprobe failed").strip()
        raise AudioProbeError(detail)

    raw = result.stdout.strip()
    try:
        duration = float(raw)
    except ValueError as exc:
        raise AudioProbeError(f"invalid ffprobe duration: {raw!r}") from exc

    if duration <= 0:
        raise AudioProbeError(f"non-positive duration: {duration}")

    return round(duration, 3)
