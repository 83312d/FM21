"""Telegram webhook secret validation (U30)."""

from __future__ import annotations

import os

from fastapi import HTTPException, status

from services.common.security import secrets_match

TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
BOT_OPEN_ACCESS = os.environ.get("BOT_OPEN_ACCESS", "").strip() == "1"


def validate_webhook_secret(x_telegram_bot_api_secret_token: str | None) -> None:
    """Reject webhook requests without a valid X-Telegram-Bot-Api-Secret-Token."""
    if not TELEGRAM_WEBHOOK_SECRET:
        if BOT_OPEN_ACCESS:
            return
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TELEGRAM_WEBHOOK_SECRET not configured",
        )
    if not secrets_match(x_telegram_bot_api_secret_token, TELEGRAM_WEBHOOK_SECRET):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing webhook secret",
        )
