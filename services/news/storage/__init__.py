"""News audio storage backends (ADR-008)."""

from __future__ import annotations

import os
from typing import Protocol

from services.news.storage.local import LocalNewsStorage
from services.news.storage.s3 import S3NewsStorage


class NewsAudioStorage(Protocol):
    def ensure_base_dir(self) -> None: ...

    def item_path(self, item_id: int): ...

    def cache_path(self, summary_hash: str): ...

    def audio_url_for_item(self, item_id: int) -> str: ...

    def write_item_mp3(self, item_id: int, data: bytes) -> str: ...

    def copy_to_item(self, source, item_id: int) -> str: ...

    def stinger_uri(self) -> str: ...


def get_news_storage() -> NewsAudioStorage:
    backend = os.environ.get("NEWS_STORAGE", "local").strip().lower()
    if backend == "s3":
        return S3NewsStorage()
    return LocalNewsStorage()


__all__ = [
    "LocalNewsStorage",
    "NewsAudioStorage",
    "S3NewsStorage",
    "get_news_storage",
]
