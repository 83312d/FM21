"""SaluteSpeech OAuth token client with 30-minute cache (ADR-006)."""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

import httpx

OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
TOKEN_ENV = "SALUTESPEECH_CREDENTIALS"
SCOPE_ENV = "SALUTESPEECH_SCOPE"
VERIFY_SSL_ENV = "SALUTESPEECH_VERIFY_SSL_CERTS"
DEFAULT_SCOPE = "SALUTE_SPEECH_PERS"
# Refresh slightly before the documented 30-minute TTL.
_TOKEN_CACHE_SEC = 29 * 60


class SaluteSpeechAuthError(RuntimeError):
    """Raised when OAuth token exchange fails."""


def verify_ssl_from_env() -> bool:
    raw = os.environ.get(VERIFY_SSL_ENV, "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


class SaluteSpeechAuth:
    """Caches SaluteSpeech Bearer tokens for ~30 minutes."""

    def __init__(
        self,
        *,
        credentials: str | None = None,
        scope: str | None = None,
        verify_ssl: bool | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._credentials = (credentials or os.environ.get(TOKEN_ENV, "")).strip()
        self._scope = (scope or os.environ.get(SCOPE_ENV, DEFAULT_SCOPE)).strip()
        self._verify_ssl = verify_ssl if verify_ssl is not None else verify_ssl_from_env()
        self._client = client
        self._token: str | None = None
        self._expires_at: float = 0.0

    async def get_token(self) -> str:
        if self._token and time.monotonic() < self._expires_at:
            return self._token

        if not self._credentials:
            raise SaluteSpeechAuthError(f"{TOKEN_ENV} is not set")

        headers = {
            "Authorization": f"Basic {self._credentials}",
            "RqUID": str(uuid.uuid4()),
            "Content-Type": "application/x-www-form-urlencoded",
        }
        data = {"scope": self._scope}

        if self._client is not None:
            response = await self._client.post(
                OAUTH_URL,
                headers=headers,
                data=data,
            )
        else:
            async with httpx.AsyncClient(verify=self._verify_ssl, timeout=30.0) as client:
                response = await client.post(
                    OAUTH_URL,
                    headers=headers,
                    data=data,
                )

        if response.status_code != 200:
            raise SaluteSpeechAuthError(
                f"SaluteSpeech OAuth failed with status {response.status_code}"
            )

        payload: dict[str, Any] = response.json()
        token = payload.get("access_token")
        if not token:
            raise SaluteSpeechAuthError("SaluteSpeech OAuth response missing access_token")

        expires_in = payload.get("expires_in")
        if isinstance(expires_in, (int, float)) and expires_in > 60:
            ttl = min(int(expires_in) - 60, _TOKEN_CACHE_SEC)
        else:
            ttl = _TOKEN_CACHE_SEC

        self._token = str(token)
        self._expires_at = time.monotonic() + ttl
        return self._token

    def clear_cache(self) -> None:
        """Drop cached token (tests)."""
        self._token = None
        self._expires_at = 0.0
