"""Summary length validation for Russian radio copy (U17, ADR-009)."""

from __future__ import annotations

MIN_WORDS = 150
MAX_WORDS = 250


def count_words(text: str) -> int:
    """Count whitespace-delimited words in summary text."""
    stripped = text.strip()
    if not stripped:
        return 0
    return len(stripped.split())


def is_valid_word_count(text: str) -> bool:
    """Return True when summary is within the 150–250 word window."""
    count = count_words(text)
    return MIN_WORDS <= count <= MAX_WORDS
