"""Shared secret comparison helpers."""

from __future__ import annotations

import hmac


def secrets_match(provided: str | None, expected: str) -> bool:
    """Constant-time comparison; False when either side is empty."""
    if not provided or not expected:
        return False
    return hmac.compare_digest(provided, expected)
