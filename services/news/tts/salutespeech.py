"""SaluteSpeech REST TTS — wav16 synthesis, ffmpeg MP3, Redis cache (U18)."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import redis

from services.news.audio_probe import probe_duration_sec
from services.news.db.repository import NewsItemRepository
from services.news.storage import NewsAudioStorage, get_news_storage
from services.news.tts.auth import SaluteSpeechAuth, verify_ssl_from_env

SYNTHESIZE_URL = "https://smartspeech.sber.ru/rest/v1/text:synthesize"
VOICE_ENV = "SALUTESPEECH_VOICE"
DEFAULT_VOICE = "Nec_24000"
TTS_CACHE_PREFIX = "fm21:tts:cache:"


class SaluteSpeechError(RuntimeError):
    """Raised when SaluteSpeech synthesis or transcoding fails."""


@dataclass(frozen=True, slots=True)
class VoiceResult:
    audio_url: str
    duration_sec: float
    cached: bool


def summary_cache_key(summary_ru: str) -> str:
    digest = hashlib.sha256(summary_ru.encode("utf-8")).hexdigest()
    return f"{TTS_CACHE_PREFIX}{digest}"


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def wav_bytes_to_mp3(wav_data: bytes, output_path: Path) -> None:
    if not ffmpeg_available():
        raise SaluteSpeechError("ffmpeg not found")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "wav",
            "-i",
            "pipe:0",
            "-codec:a",
            "libmp3lame",
            "-q:a",
            "4",
            str(output_path),
        ],
        input=wav_data,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "ffmpeg failed").decode(
            "utf-8", errors="replace"
        ).strip()
        raise SaluteSpeechError(detail)


class SaluteSpeechTTS:
    """Sync SaluteSpeech REST client with Redis-backed summary cache."""

    def __init__(
        self,
        *,
        auth: SaluteSpeechAuth | None = None,
        storage: NewsAudioStorage | None = None,
        redis_client: redis.Redis | None = None,
        voice: str | None = None,
        verify_ssl: bool | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._auth = auth or SaluteSpeechAuth(verify_ssl=verify_ssl, client=client)
        self._storage = storage or get_news_storage()
        self._redis = redis_client
        self._voice = (voice or os.environ.get(VOICE_ENV, DEFAULT_VOICE)).strip()
        self._verify_ssl = verify_ssl if verify_ssl is not None else verify_ssl_from_env()
        self._client = client

    def _redis_client(self) -> redis.Redis:
        if self._redis is None:
            url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
            self._redis = redis.Redis.from_url(url, decode_responses=True)
        return self._redis

    async def synthesize_wav(self, text: str) -> bytes:
        token = await self._auth.get_token()
        params = {"format": "wav16", "voice": self._voice}
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/text; charset=utf-8",
        }

        if self._client is not None:
            response = await self._client.post(
                SYNTHESIZE_URL,
                params=params,
                headers=headers,
                content=text.encode("utf-8"),
            )
        else:
            async with httpx.AsyncClient(verify=self._verify_ssl, timeout=120.0) as client:
                response = await client.post(
                    SYNTHESIZE_URL,
                    params=params,
                    headers=headers,
                    content=text.encode("utf-8"),
                )

        if response.status_code != 200:
            raise SaluteSpeechError(
                f"SaluteSpeech synthesis failed with status {response.status_code}"
            )

        if not response.content:
            raise SaluteSpeechError("SaluteSpeech synthesis returned empty audio")

        return response.content

    def _read_cache(self, summary_ru: str) -> dict[str, Any] | None:
        raw = self._redis_client().get(summary_cache_key(summary_ru))
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        cache_path = payload.get("cache_path")
        duration_sec = payload.get("duration_sec")
        if not cache_path or duration_sec is None:
            return None
        path = Path(str(cache_path))
        if not path.is_file():
            return None
        return {"cache_path": path, "duration_sec": float(duration_sec)}

    def _write_cache(self, summary_ru: str, cache_path: Path, duration_sec: float) -> None:
        payload = {
            "cache_path": str(cache_path.resolve()),
            "duration_sec": duration_sec,
        }
        self._redis_client().set(summary_cache_key(summary_ru), json.dumps(payload))

    async def synthesize_mp3_for_summary(self, summary_ru: str) -> tuple[Path, float, bool]:
        """Return (cache_mp3_path, duration_sec, cache_hit)."""
        self._storage.ensure_base_dir()
        cached = self._read_cache(summary_ru)
        if cached is not None:
            return cached["cache_path"], cached["duration_sec"], True

        wav_data = await self.synthesize_wav(summary_ru)
        digest = hashlib.sha256(summary_ru.encode("utf-8")).hexdigest()
        cache_path = self._storage.cache_path(digest)
        wav_bytes_to_mp3(wav_data, cache_path)
        duration_sec = probe_duration_sec(cache_path)
        self._write_cache(summary_ru, cache_path, duration_sec)
        return cache_path, duration_sec, False

    async def voice_news_item(
        self,
        repo: NewsItemRepository,
        item_id: int,
    ) -> VoiceResult:
        """Synthesize (or reuse cache), store MP3, update repository to ready."""
        item = await repo.get_by_id(item_id)
        if item is None:
            raise LookupError(f"News item {item_id} not found")
        if not item.summary_ru:
            raise SaluteSpeechError(f"News item {item_id} has no summary_ru")

        cache_path, duration_sec, cached = await self.synthesize_mp3_for_summary(item.summary_ru)
        audio_url = self._storage.copy_to_item(cache_path, item_id)

        await repo.update_audio(item_id, audio_url)
        await repo.mark_ready(item_id)

        return VoiceResult(
            audio_url=audio_url,
            duration_sec=duration_sec,
            cached=cached,
        )
