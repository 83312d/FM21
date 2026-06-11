"""S3 news audio storage — stub for production cutover (ADR-008, U30)."""

from __future__ import annotations

import os
from pathlib import Path


class S3NewsStorage:
    """Placeholder S3 adapter; not required for Phase 3 exit."""

    def __init__(
        self,
        *,
        bucket: str | None = None,
        prefix: str | None = None,
    ) -> None:
        self._bucket = bucket or os.environ.get("NEWS_S3_BUCKET", "")
        self._prefix = (prefix or os.environ.get("NEWS_S3_PREFIX", "news")).strip("/")
        if not self._bucket:
            raise NotImplementedError(
                "S3 news storage is not configured (set NEWS_S3_BUCKET at U30)"
            )

    def ensure_base_dir(self) -> None:
        raise NotImplementedError("S3 news storage is not implemented yet (U30)")

    def item_path(self, item_id: int) -> Path:
        raise NotImplementedError("S3 news storage is not implemented yet (U30)")

    def cache_path(self, summary_hash: str) -> Path:
        raise NotImplementedError("S3 news storage is not implemented yet (U30)")

    def audio_url_for_item(self, item_id: int) -> str:
        raise NotImplementedError("S3 news storage is not implemented yet (U30)")

    def write_item_mp3(self, item_id: int, data: bytes) -> str:
        raise NotImplementedError("S3 news storage is not implemented yet (U30)")

    def copy_to_item(self, source: Path, item_id: int) -> str:
        raise NotImplementedError("S3 news storage is not implemented yet (U30)")

    def stinger_uri(self) -> str:
        raise NotImplementedError("S3 news storage is not implemented yet (U30)")
