"""Pending voice ad conversation state (U26)."""

from __future__ import annotations

import secrets
import time
from typing import Any, TypedDict

from telegram.ext import ContextTypes

PENDING_VOICE_KEY = "pending_voice"
PENDING_VOICE_TTL_SEC = 600
MSG_STALE = "Голосовое сообщение устарело. Отправьте снова."


class PendingVoice(TypedDict):
    file_id: str
    duration: int
    nonce: str
    created_at: float


def new_pending_voice(*, file_id: str, duration: int) -> PendingVoice:
    return PendingVoice(
        file_id=file_id,
        duration=duration,
        nonce=secrets.token_hex(4),
        created_at=time.monotonic(),
    )


def store_pending_voice(context: ContextTypes.DEFAULT_TYPE, pending: PendingVoice) -> None:
    context.user_data[PENDING_VOICE_KEY] = pending


def clear_pending_voice(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop(PENDING_VOICE_KEY, None)


def _is_expired(pending: PendingVoice) -> bool:
    return (time.monotonic() - pending["created_at"]) > PENDING_VOICE_TTL_SEC


def consume_pending_voice(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    nonce: str,
) -> PendingVoice | None:
    """Atomically take pending voice state (prevents double-tap duplicate submit)."""
    pending = get_pending_voice(context, nonce=nonce)
    if pending is None:
        return None
    clear_pending_voice(context)
    return pending


def get_pending_voice(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    nonce: str | None = None,
) -> PendingVoice | None:
    raw: Any = context.user_data.get(PENDING_VOICE_KEY)
    if not raw:
        return None

    pending = PendingVoice(
        file_id=raw["file_id"],
        duration=int(raw["duration"]),
        nonce=raw["nonce"],
        created_at=float(raw["created_at"]),
    )

    if _is_expired(pending):
        clear_pending_voice(context)
        return None

    if pending["nonce"] != nonce:
        return None

    return pending
