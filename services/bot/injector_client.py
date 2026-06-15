"""Backward-compatible re-export — prefer services.bot.clients.injector_client."""

from services.bot.clients.injector_client import (  # noqa: F401
    EnqueueFailure,
    EnqueueResult,
    enqueue_music_order,
)
