"""Minimal UTC cron timing for FM21 scheduled jobs (U32)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

CRON_CACHE_CLEANUP = "0 3 * * *"
CRON_NEWS_CACHE_RESET = "0 0 * * *"
CRON_PLAYLIST_REFRESH = "0 * * * *"


def _parse_cron(expr: str) -> tuple[int, int | None]:
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError(f"Unsupported cron expression: {expr}")
    minute = int(parts[0]) if parts[0] != "*" else 0
    hour = None if parts[1] == "*" else int(parts[1])
    return minute, hour


def _next_run(minute: int, hour: int | None, *, now: datetime) -> datetime:
    if hour is None:
        candidate = now.replace(minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(hours=1)
        return candidate

    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def seconds_until_next_cron(expr: str, *, now: datetime | None = None) -> float:
    """Seconds until the next UTC fire time for minute/hour cron expressions."""
    current = now or datetime.now(UTC)
    minute, hour = _parse_cron(expr)
    next_run = _next_run(minute, hour, now=current)
    return max(0.0, (next_run - current).total_seconds())


def is_cron_due(expr: str, *, now: datetime | None = None, window_sec: int = 60) -> bool:
    """True when `now` falls in the first `window_sec` after the scheduled minute."""
    current = now or datetime.now(UTC)
    minute, hour = _parse_cron(expr)
    if hour is None:
        return current.minute == minute and current.second < window_sec
    return current.hour == hour and current.minute == minute and current.second < window_sec
