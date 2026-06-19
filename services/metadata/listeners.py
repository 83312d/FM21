"""Icecast listener counts per city mount."""

from __future__ import annotations

from urllib.parse import urlparse

import httpx

from services.metadata.health import _icecast_status_url


def _normalize_sources(raw: object) -> list[dict]:
    if raw is None:
        return []
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, list):
        return [source for source in raw if isinstance(source, dict)]
    return []


def _mount_matches(listenurl: str, city_tag: str) -> bool:
    path = urlparse(listenurl).path.rstrip("/") or "/"
    return path == f"/{city_tag}"


def _parse_listeners(value: object) -> int:
    try:
        return max(0, int(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def read_listener_count(city_tag: str, *, timeout_sec: float = 3.0) -> int | None:
    """Return listener count for /{city_tag}, 0 if mount absent, None on fetch/parse error."""
    try:
        response = httpx.get(
            _icecast_status_url(),
            timeout=timeout_sec,
            follow_redirects=True,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:  # noqa: BLE001 — probe must not raise
        return None

    icestats = payload.get("icestats")
    if not isinstance(icestats, dict):
        return None

    for source in _normalize_sources(icestats.get("source")):
        listenurl = source.get("listenurl")
        if isinstance(listenurl, str) and _mount_matches(listenurl, city_tag):
            return _parse_listeners(source.get("listeners"))

    return 0
