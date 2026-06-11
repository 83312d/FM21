"""Load human-maintained RSS source registry (U16, ADR-004)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_SOURCES_PATH = Path(__file__).with_name("sources.yaml")


class SourcesConfigError(ValueError):
    """Raised when sources.yaml is missing or invalid."""


@dataclass(frozen=True, slots=True)
class NewsSource:
    id: str
    name: str
    url: str
    enabled: bool
    weight: int


@dataclass(frozen=True, slots=True)
class SourcesRegistry:
    version: int
    sources: tuple[NewsSource, ...]

    @property
    def enabled_sources(self) -> tuple[NewsSource, ...]:
        return tuple(source for source in self.sources if source.enabled)


def sources_path_from_env() -> Path:
    env_path = os.environ.get("NEWS_SOURCES_PATH")
    if env_path:
        return Path(env_path)
    return DEFAULT_SOURCES_PATH


def _parse_source(raw: object, *, index: int) -> NewsSource:
    if not isinstance(raw, dict):
        raise SourcesConfigError(f"sources[{index}] must be a mapping")

    source_id = raw.get("id")
    name = raw.get("name")
    url = raw.get("url")
    enabled = raw.get("enabled")
    weight = raw.get("weight")

    if not isinstance(source_id, str) or not source_id.strip():
        raise SourcesConfigError(f"sources[{index}].id must be a non-empty string")
    if not isinstance(name, str) or not name.strip():
        raise SourcesConfigError(f"sources[{index}].name must be a non-empty string")
    if not isinstance(url, str) or not url.strip():
        raise SourcesConfigError(f"sources[{index}].url must be a non-empty string")
    if not isinstance(enabled, bool):
        raise SourcesConfigError(f"sources[{index}].enabled must be a boolean")
    if not isinstance(weight, int) or weight < 0:
        raise SourcesConfigError(f"sources[{index}].weight must be a non-negative integer")

    return NewsSource(
        id=source_id.strip(),
        name=name.strip(),
        url=url.strip(),
        enabled=enabled,
        weight=weight,
    )


def parse_sources_document(raw: object, *, source_path: Path) -> SourcesRegistry:
    if not isinstance(raw, dict):
        raise SourcesConfigError(f"{source_path}: root must be a mapping")

    version = raw.get("version")
    if not isinstance(version, int) or version < 1:
        raise SourcesConfigError(f"{source_path}: version must be a positive integer")

    sources_raw = raw.get("sources")
    if not isinstance(sources_raw, list) or not sources_raw:
        raise SourcesConfigError(f"{source_path}: sources must be a non-empty list")

    sources = tuple(_parse_source(item, index=index) for index, item in enumerate(sources_raw))
    ids = [source.id for source in sources]
    if len(ids) != len(set(ids)):
        raise SourcesConfigError(f"{source_path}: duplicate source id")

    return SourcesRegistry(version=version, sources=sources)


def load_sources(path: Path | str | None = None) -> SourcesRegistry:
    """Parse and validate services/news/sources.yaml."""
    sources_path = Path(path) if path is not None else sources_path_from_env()
    if not sources_path.is_file():
        raise SourcesConfigError(f"sources file not found: {sources_path}")

    try:
        with sources_path.open(encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise SourcesConfigError(f"malformed sources.yaml: {exc}") from exc

    return parse_sources_document(raw, source_path=sources_path)
