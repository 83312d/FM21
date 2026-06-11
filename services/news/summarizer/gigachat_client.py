"""GigaChat REST client wrapper for news summarization (U17)."""

from __future__ import annotations

import os
from typing import Protocol, runtime_checkable

from gigachat import GigaChat

from services.news.summarizer.prompt import build_chat

DEFAULT_SCOPE = "GIGACHAT_API_PERS"


@runtime_checkable
class SummarizerClient(Protocol):
    """Injectable summarizer client for tests and pipeline callers."""

    async def summarize(self, source_text: str, *, tightened: bool = False) -> str: ...


class GigaChatSummarizer:
    """Official GigaChat SDK adapter (REST only)."""

    def __init__(self, **client_kwargs: object) -> None:
        self._client_kwargs = client_kwargs

    async def summarize(self, source_text: str, *, tightened: bool = False) -> str:
        async with GigaChat(**self._client_kwargs) as client:
            response = await client.achat(build_chat(source_text, tightened=tightened))
        content = response.choices[0].message.content
        if not isinstance(content, str) or not content.strip():
            raise ValueError("GigaChat returned empty summary")
        return content.strip()


def create_summarizer_client() -> GigaChatSummarizer:
    """Build a GigaChat client from GIGACHAT_CREDENTIALS and optional GIGACHAT_SCOPE."""
    credentials = os.environ.get("GIGACHAT_CREDENTIALS")
    if not credentials:
        raise RuntimeError("GIGACHAT_CREDENTIALS is not set")

    kwargs: dict[str, object] = {
        "credentials": credentials,
        "scope": os.environ.get("GIGACHAT_SCOPE", DEFAULT_SCOPE),
    }

    verify_ssl = os.environ.get("GIGACHAT_VERIFY_SSL_CERTS")
    if verify_ssl is not None:
        kwargs["verify_ssl_certs"] = verify_ssl.lower() in ("1", "true", "yes")

    return GigaChatSummarizer(**kwargs)
