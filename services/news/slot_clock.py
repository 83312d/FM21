"""UTC news slot clock — materialize vs enqueue boundaries (ADR-010, U20)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

MATERIALIZE_MINUTES = frozenset({2, 17, 32, 47})
ENQUEUE_MINUTES = frozenset({0, 15, 30, 45})


def enqueue_slot_for_materialize(now: datetime) -> datetime:
    """Map a materialize cron fire time to the enqueue slot it prepares.

    Cron runs at :02, :17, :32, :47 UTC and pins audio for the next boundary
  at :15, :30, :45, or :00 (next hour) respectively.
    """
    current = now.astimezone(UTC).replace(second=0, microsecond=0)
    minute = current.minute
    if minute == 2:
        return current.replace(minute=15)
    if minute == 17:
        return current.replace(minute=30)
    if minute == 32:
        return current.replace(minute=45)
    if minute == 47:
        return (current.replace(minute=0) + timedelta(hours=1))
    raise ValueError(f"Not a materialize minute: {minute}")


def slot_iso(slot: datetime) -> str:
    """Canonical Redis slot key suffix (UTC, minute resolution)."""
    utc = slot.astimezone(UTC)
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def is_materialize_minute(now: datetime) -> bool:
    return now.astimezone(UTC).minute in MATERIALIZE_MINUTES


def next_materialize_at(now: datetime | None = None) -> datetime:
    """Next UTC wall-clock tick at :02, :17, :32, or :47."""
    current = (now or datetime.now(UTC)).astimezone(UTC).replace(second=0, microsecond=0)
    for minutes_ahead in range(1, 24 * 60 + 1):
        candidate = current + timedelta(minutes=minutes_ahead)
        if candidate.minute in MATERIALIZE_MINUTES:
            return candidate.replace(second=0, microsecond=0)
    raise RuntimeError("no materialize tick found within 24h")


def seconds_until_next_materialize(now: datetime | None = None) -> float:
    current = now or datetime.now(UTC)
    nxt = next_materialize_at(current)
    return max(0.0, (nxt - current.astimezone(UTC)).total_seconds())


def current_enqueue_slot(now: datetime) -> datetime:
    """UTC slot boundary at or before ``now`` (:00, :15, :30, :45)."""
    current = now.astimezone(UTC).replace(second=0, microsecond=0)
    slot_minute = (current.minute // 15) * 15
    return current.replace(minute=slot_minute)


def is_enqueue_minute(now: datetime) -> bool:
    return now.astimezone(UTC).minute in ENQUEUE_MINUTES


def next_enqueue_at(now: datetime | None = None) -> datetime:
    """Next UTC wall-clock tick at :00, :15, :30, or :45."""
    current = (now or datetime.now(UTC)).astimezone(UTC).replace(second=0, microsecond=0)
    for minutes_ahead in range(0, 24 * 60 + 1):
        candidate = current + timedelta(minutes=minutes_ahead)
        if candidate.minute in ENQUEUE_MINUTES and candidate > current:
            return candidate.replace(second=0, microsecond=0)
    raise RuntimeError("no enqueue tick found within 24h")


def seconds_until_next_enqueue(now: datetime | None = None) -> float:
    current = now or datetime.now(UTC)
    nxt = next_enqueue_at(current)
    return max(0.0, (nxt - current.astimezone(UTC)).total_seconds())


def next_news_at(now: datetime | None = None) -> datetime:
    """Next UTC news enqueue boundary at :00, :15, :30, or :45."""
    current = (now or datetime.now(UTC)).astimezone(UTC).replace(second=0, microsecond=0)
    if current.minute in ENQUEUE_MINUTES:
        return current
    for minutes_ahead in range(1, 24 * 60 + 1):
        candidate = current + timedelta(minutes=minutes_ahead)
        if candidate.minute in ENQUEUE_MINUTES:
            return candidate.replace(second=0, microsecond=0)
    raise RuntimeError("no news enqueue tick found within 24h")


def seconds_until_next_news(now: datetime | None = None) -> float:
    current = now or datetime.now(UTC)
    nxt = next_news_at(current)
    return max(0.0, (nxt - current.astimezone(UTC)).total_seconds())
