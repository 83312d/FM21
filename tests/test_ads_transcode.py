"""Ads transcode pipeline — ffmpeg OGG→MP3 with loudnorm (U24)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from services.ads.transcode import TranscodeError, ffmpeg_available, transcode_ogg_to_mp3


@pytest.fixture
def sample_ogg(tmp_path: Path) -> Path:
    """Generate a short OGG Opus clip via ffmpeg."""
    if not ffmpeg_available():
        pytest.skip("ffmpeg not available")
    ogg_path = tmp_path / "sample.ogg"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-codec:a",
            "libopus",
            str(ogg_path),
        ],
        check=True,
        capture_output=True,
    )
    return ogg_path


def test_ffmpeg_available_in_container():
    assert ffmpeg_available() is True


def test_transcode_ogg_to_mp3(sample_ogg: Path, tmp_path: Path):
    mp3_path = tmp_path / "out.mp3"
    transcode_ogg_to_mp3(sample_ogg, mp3_path)

    assert mp3_path.is_file()
    assert mp3_path.stat().st_size > 0

    probe = subprocess.run(
        [
            "ffprobe",
            "-hide_banner",
            "-loglevel",
            "error",
            "-show_entries",
            "format=format_name",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(mp3_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "mp3" in probe.stdout.lower()


def test_transcode_missing_ffmpeg_raises(tmp_path: Path):
    with patch("services.ads.transcode.ffmpeg_available", return_value=False):
        with pytest.raises(TranscodeError, match="ffmpeg not found"):
            transcode_ogg_to_mp3(tmp_path / "in.ogg", tmp_path / "out.mp3")


def test_transcode_failure_raises(sample_ogg: Path, tmp_path: Path):
    with patch("services.ads.transcode.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1,
            cmd=["ffmpeg"],
            stderr="decode error",
        )
        with pytest.raises(TranscodeError, match="decode error"):
            transcode_ogg_to_mp3(sample_ogg, tmp_path / "out.mp3")
