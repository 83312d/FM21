"""HTTP routes for ads service (U24)."""

from __future__ import annotations

import os
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from services.ads.service import (
    DurationExceededError,
    InvalidCityTagError,
    SubmitInjectorError,
    SubmitQueueFull,
    SubmitSuccess,
    TranscodeFailedError,
    submit_voice_ad,
)
from services.common.security import secrets_match
from services.db.session import get_session

router = APIRouter()

MAX_UPLOAD_BYTES = int(os.environ.get("ADS_MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))


class SubmitResponse(BaseModel):
    id: int
    city_tag: str
    city_tags: list[str]
    audio_url: str


class ErrorDetail(BaseModel):
    error: str
    message: str
    city_tag: str | None = None


def _structured_detail(
    error: str,
    message: str,
    *,
    city_tag: str | None = None,
) -> dict[str, Any]:
    detail: dict[str, Any] = {"error": error, "message": message}
    if city_tag is not None:
        detail["city_tag"] = city_tag
    return detail


def _require_internal_token(
    x_fm21_internal_token: Annotated[str | None, Header()] = None,
) -> None:
    internal_token = os.environ.get("INTERNAL_ENQUEUE_TOKEN", "")
    if not internal_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_structured_detail(
                "misconfigured",
                "INTERNAL_ENQUEUE_TOKEN not configured",
            ),
        )
    if not secrets_match(x_fm21_internal_token, internal_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_structured_detail(
                "unauthorized",
                "Invalid or missing internal token",
            ),
        )


def _get_active_cities() -> list[str]:
    from services.ads.main import app

    return app.state.active_cities


@router.post(
    "/internal/ads/submit",
    response_model=SubmitResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorDetail},
        401: {"model": ErrorDetail},
        409: {"model": ErrorDetail},
        422: {"model": ErrorDetail},
        502: {"model": ErrorDetail},
        503: {"model": ErrorDetail},
    },
)
async def submit_ad(
    _: Annotated[None, Depends(_require_internal_token)],
    session: Annotated[AsyncSession, Depends(get_session)],
    audio: Annotated[UploadFile, File()],
    telegram_user_id: Annotated[int, Form()],
    city_tag: Annotated[str, Form()],
    duration_sec: Annotated[int, Form(ge=1)],
    active_cities: Annotated[list[str], Depends(_get_active_cities)],
) -> SubmitResponse:
    ogg_bytes = await audio.read()
    if len(ogg_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=_structured_detail(
                "payload_too_large",
                f"Audio upload exceeds {MAX_UPLOAD_BYTES} bytes",
            ),
        )

    try:
        result = await submit_voice_ad(
            session,
            ogg_bytes=ogg_bytes,
            telegram_user_id=telegram_user_id,
            city_tag=city_tag,
            duration_sec=duration_sec,
            active_cities=active_cities,
        )
    except DurationExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_structured_detail("duration_exceeded", str(exc)),
        ) from exc
    except InvalidCityTagError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_structured_detail("invalid_city", str(exc)),
        ) from exc
    except TranscodeFailedError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_structured_detail("transcode_failed", str(exc)),
        ) from exc

    if isinstance(result, SubmitQueueFull):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_structured_detail(
                "queue_full",
                result.message,
                city_tag=result.city_tag,
            ),
        )

    if isinstance(result, SubmitInjectorError):
        raise HTTPException(
            status_code=result.status_code,
            detail=_structured_detail("injector_error", result.message),
        )

    return SubmitResponse(
        id=result.id,
        city_tag=result.city_tag,
        city_tags=result.city_tags,
        audio_url=result.audio_url,
    )


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
