"""Yandex Music OAuth token handling (server-side only, never logged)."""

from __future__ import annotations

import os
from typing import Any

from yandex_music import ClientAsync
from yandex_music.exceptions import UnauthorizedError, YandexMusicError

from services.music.provider import ProviderUnavailable

TOKEN_ENV = "YANDEX_MUSIC_OAUTH_TOKEN"


class SafeYandexClient:
    """Delegates to ClientAsync without exposing the OAuth token in repr."""

    def __init__(self, client: ClientAsync) -> None:
        self._client = client

    def __repr__(self) -> str:
        return "SafeYandexClient(<redacted>)"

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


def get_oauth_token() -> str:
    token = os.environ.get(TOKEN_ENV, "").strip()
    if not token:
        raise ProviderUnavailable(f"{TOKEN_ENV} is not set")
    return token


async def create_yandex_client(token: str | None = None) -> SafeYandexClient:
    """Initialize an authenticated async Yandex Music client."""
    resolved = (token or get_oauth_token()).strip()
    if not resolved:
        raise ProviderUnavailable(f"{TOKEN_ENV} is not set")

    client = ClientAsync(resolved)
    try:
        await client.init()
    except UnauthorizedError:
        raise ProviderUnavailable("Yandex Music OAuth token is invalid") from None
    except YandexMusicError:
        raise ProviderUnavailable("Yandex Music client initialization failed") from None
    return SafeYandexClient(client)
