"""FM21 Telegram bot — webhook control plane for operator voice ads."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Request, status
from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from services.bot.handlers.city import ad_city_callback, city_command
from services.bot.handlers.voice import voice_message

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
TELEGRAM_WEBHOOK_URL = os.environ.get("TELEGRAM_WEBHOOK_URL", "")

bot_application: Application | None = None


async def coming_soon(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text("Скоро")


def build_application() -> Application:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .updater(None)
        .build()
    )

    application.add_handler(CommandHandler("city", city_command))
    application.add_handler(CommandHandler("order", coming_soon))
    application.add_handler(CommandHandler("status", coming_soon))
    application.add_handler(CommandHandler("playlist", coming_soon))
    application.add_handler(MessageHandler(filters.VOICE, voice_message))
    application.add_handler(CallbackQueryHandler(ad_city_callback, pattern=r"^ad:"))

    return application


@asynccontextmanager
async def lifespan(app: FastAPI):
    global bot_application
    bot_application = build_application()
    await bot_application.initialize()
    await bot_application.start()

    if TELEGRAM_WEBHOOK_URL:
        webhook_target = f"{TELEGRAM_WEBHOOK_URL.rstrip('/')}/api/bot/webhook"
        await bot_application.bot.set_webhook(
            url=webhook_target,
            secret_token=TELEGRAM_WEBHOOK_SECRET or None,
            allowed_updates=Update.ALL_TYPES,
        )
        logger.info("telegram webhook registered at %s", webhook_target)
    else:
        logger.warning("TELEGRAM_WEBHOOK_URL not set — webhook not registered with Telegram")

    yield

    await bot_application.stop()
    await bot_application.shutdown()
    bot_application = None


app = FastAPI(title="FM21 Telegram Bot", lifespan=lifespan)


def _validate_webhook_secret(
    x_telegram_bot_api_secret_token: str | None,
) -> None:
    if not TELEGRAM_WEBHOOK_SECRET:
        return
    if x_telegram_bot_api_secret_token != TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing webhook secret",
        )


@app.post("/api/bot/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None,
) -> dict[str, bool]:
    _validate_webhook_secret(x_telegram_bot_api_secret_token)

    if bot_application is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Bot not initialized",
        )

    data = await request.json()
    update = Update.de_json(data, bot_application.bot)
    await bot_application.update_queue.put(update)
    return {"ok": True}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
