"""FM21 Telegram bot — webhook (prod) or long polling (local dev)."""

from __future__ import annotations

import logging
import os
import traceback
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Request, status
from telegram import Update
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    TypeHandler,
    filters,
)

from services.bot.middleware.auth import auth_middleware
from services.bot.webhook import TELEGRAM_WEBHOOK_SECRET, validate_webhook_secret

from services.bot.handlers.city import ad_city_callback, city_command
from services.bot.handlers.order import order_callback, order_command
from services.bot.handlers.playlist import playlist_command
from services.bot.handlers.status import status_command
from services.bot.handlers.voice import voice_message

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_WEBHOOK_URL = os.environ.get("TELEGRAM_WEBHOOK_URL", "")
BOT_MODE = os.environ.get("BOT_MODE", "polling").strip().lower()

bot_application: Application | None = None


def use_polling() -> bool:
    """Long polling for local dev — no public HTTPS / ngrok required."""
    return BOT_MODE == "polling"


def _telegram_proxy_url() -> str | None:
    for key in ("TELEGRAM_PROXY_URL", "HTTPS_PROXY", "HTTP_PROXY"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return None


def _telegram_request() -> HTTPXRequest:
    kwargs: dict[str, object] = {
        "connection_pool_size": 20,
        "connect_timeout": 30.0,
        "read_timeout": 30.0,
        "write_timeout": 30.0,
        "pool_timeout": 30.0,
    }
    proxy = _telegram_proxy_url()
    if proxy:
        kwargs["proxy"] = proxy
    return HTTPXRequest(**kwargs)


async def _log_handler_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    exc = context.error
    update_id = update.update_id if isinstance(update, Update) else "?"
    exc_type = type(exc).__name__ if exc is not None else "Unknown"
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)) if exc else ""
    logger.error(
        "telegram handler error update_id=%s exc_type=%s\n%s",
        update_id,
        exc_type,
        tb,
    )


def build_application(*, polling: bool) -> Application:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")

    builder = Application.builder().token(TELEGRAM_BOT_TOKEN).request(_telegram_request())
    if not polling:
        builder = builder.updater(None)
    application = builder.build()

    application.add_handler(TypeHandler(Update, auth_middleware), group=-1)

    application.add_handler(CommandHandler("city", city_command))
    application.add_handler(CommandHandler("order", order_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("playlist", playlist_command))
    application.add_handler(MessageHandler(filters.VOICE, voice_message))
    application.add_handler(CallbackQueryHandler(ad_city_callback, pattern=r"^ad:"))
    application.add_handler(CallbackQueryHandler(order_callback, pattern=r"^order:"))

    application.add_error_handler(_log_handler_error)

    return application


@asynccontextmanager
async def lifespan(app: FastAPI):
    global bot_application
    polling = use_polling()
    bot_application = build_application(polling=polling)
    await bot_application.initialize()
    await bot_application.start()

    if polling:
        await bot_application.bot.delete_webhook(drop_pending_updates=True)
        if bot_application.updater is None:
            raise RuntimeError("polling mode requires Application updater")
        await bot_application.updater.start_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
        logger.info("telegram long polling started (BOT_MODE=polling, local dev)")
    elif TELEGRAM_WEBHOOK_URL:
        webhook_target = f"{TELEGRAM_WEBHOOK_URL.rstrip('/')}/api/bot/webhook"
        await bot_application.bot.set_webhook(
            url=webhook_target,
            secret_token=TELEGRAM_WEBHOOK_SECRET or None,
            allowed_updates=Update.ALL_TYPES,
        )
        logger.info("telegram webhook registered at %s", webhook_target)
    else:
        logger.warning(
            "TELEGRAM_WEBHOOK_URL not set and BOT_MODE is not polling — "
            "bot will not receive Telegram updates"
        )

    yield

    if bot_application.updater is not None and bot_application.updater.running:
        await bot_application.updater.stop()
    await bot_application.stop()
    await bot_application.shutdown()
    bot_application = None


app = FastAPI(title="FM21 Telegram Bot", lifespan=lifespan)


@app.post("/api/bot/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None,
) -> dict[str, bool]:
    validate_webhook_secret(x_telegram_bot_api_secret_token)

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
