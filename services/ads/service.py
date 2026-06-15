"""Ads submit workflow — transcode, persist, enqueue (U24)."""

from __future__ import annotations

import logging
import math
import os
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from services.ads import injector_client
from services.ads.repository import AdRepository
from services.ads.transcode import TranscodeError, transcode_ogg_to_mp3
from services.injector.fanout import resolve_target_cities
from services.news.audio_probe import AudioProbeError, probe_duration_sec

logger = logging.getLogger(__name__)

MAX_AD_DURATION_SEC = int(os.environ.get("MAX_AD_DURATION_SEC", "60"))
ADS_DIR = Path(os.environ.get("ADS_DIR", "/data/ads"))


class DurationExceededError(Exception):
    """Voice ad exceeds maximum allowed duration."""


class InvalidCityTagError(Exception):
    """city_tag is not active and not 'all'."""


class TranscodeFailedError(Exception):
    """ffmpeg transcode failed."""


@dataclass(frozen=True)
class SubmitSuccess:
    id: int
    city_tag: str
    city_tags: list[str]
    audio_url: str


@dataclass(frozen=True)
class SubmitQueueFull:
    city_tag: str | None
    message: str


@dataclass(frozen=True)
class SubmitInjectorError:
    status_code: int
    message: str


def _upstream_http_status(injector_status: int) -> int:
    if injector_status == 503:
        return 503
    if injector_status == 409:
        return 409
    return 502


async def _reject_ad(
    repo: AdRepository,
    session: AsyncSession,
    ad_id: int,
    output_path: Path,
) -> None:
    await repo.mark_rejected(ad_id)
    await session.commit()
    output_path.unlink(missing_ok=True)


async def submit_voice_ad(
    session: AsyncSession,
    *,
    ogg_bytes: bytes,
    telegram_user_id: int,
    city_tag: str,
    duration_sec: int,
    active_cities: list[str],
) -> SubmitSuccess | SubmitQueueFull | SubmitInjectorError:
    if duration_sec > MAX_AD_DURATION_SEC:
        raise DurationExceededError(
            f"AD duration exceeds {MAX_AD_DURATION_SEC}s limit"
        )

    if not resolve_target_cities(city_tag, active_cities):
        raise InvalidCityTagError(f"Invalid city_tag: {city_tag}")

    file_id = uuid.uuid4().hex[:12]
    output_path = ADS_DIR / f"{file_id}.mp3"
    repo = AdRepository(session)

    try:
        with tempfile.TemporaryDirectory() as tmp:
            ogg_path = Path(tmp) / "input.ogg"
            ogg_path.write_bytes(ogg_bytes)
            transcode_ogg_to_mp3(ogg_path, output_path)
    except TranscodeError as exc:
        logger.exception("transcode failed for voice ad")
        output_path.unlink(missing_ok=True)
        raise TranscodeFailedError(str(exc)) from exc

    try:
        probed_sec = math.ceil(probe_duration_sec(output_path))
    except AudioProbeError as exc:
        output_path.unlink(missing_ok=True)
        raise TranscodeFailedError(str(exc)) from exc

    if probed_sec > MAX_AD_DURATION_SEC:
        output_path.unlink(missing_ok=True)
        raise DurationExceededError(
            f"AD duration exceeds {MAX_AD_DURATION_SEC}s limit"
        )

    enqueue_duration_sec = probed_sec
    audio_url = f"file://{output_path}"
    ad = await repo.create_pending(
        telegram_user_id=telegram_user_id,
        city_tag=city_tag,
        audio_url=audio_url,
    )

    result = await injector_client.enqueue_ad(
        uri=audio_url,
        city_tag=city_tag,
        duration_sec=enqueue_duration_sec,
    )

    if isinstance(result, injector_client.EnqueueResult):
        await repo.mark_queued(ad.id)
        await session.commit()
        return SubmitSuccess(
            id=ad.id,
            city_tag=city_tag,
            city_tags=result.city_tags,
            audio_url=audio_url,
        )

    if result.ambiguous:
        await session.commit()
        return SubmitInjectorError(
            status_code=_upstream_http_status(result.status_code),
            message=result.message,
        )

    await _reject_ad(repo, session, ad.id, output_path)

    if result.status_code == 409:
        return SubmitQueueFull(
            city_tag=result.city_tag or city_tag,
            message=result.message,
        )

    return SubmitInjectorError(
        status_code=_upstream_http_status(result.status_code),
        message=result.message,
    )
