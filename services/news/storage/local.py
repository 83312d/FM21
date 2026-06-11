"""Local filesystem news audio storage (ADR-008 dev)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

STINGER_FILENAME = "news-stinger.mp3"


class LocalNewsStorage:
    """Writes voiced news MP3s under a shared volume (default /data/news)."""

    def __init__(self, base_dir: str | Path | None = None) -> None:
        resolved = base_dir or os.environ.get("NEWS_AUDIO_DIR", "/data/news")
        self._base_dir = Path(resolved)

    @property
    def base_dir(self) -> Path:
        return self._base_dir

    def ensure_base_dir(self) -> None:
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def item_path(self, item_id: int) -> Path:
        return self._base_dir / f"{item_id}.mp3"

    def cache_path(self, summary_hash: str) -> Path:
        return self._base_dir / "cache" / f"{summary_hash}.mp3"

    def audio_url_for_path(self, path: Path) -> str:
        return f"file://{path.resolve()}"

    def audio_url_for_item(self, item_id: int) -> str:
        return self.audio_url_for_path(self.item_path(item_id))

    def write_bytes(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def write_item_mp3(self, item_id: int, data: bytes) -> str:
        target = self.item_path(item_id)
        self.write_bytes(target, data)
        return self.audio_url_for_item(item_id)

    def copy_to_item(self, source: Path, item_id: int) -> str:
        target = self.item_path(item_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return self.audio_url_for_item(item_id)

    def stinger_path(self) -> Path:
        return self._base_dir / STINGER_FILENAME

    def stinger_uri(self) -> str:
        return self.audio_url_for_path(self.stinger_path())
