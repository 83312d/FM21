"""Shared HTTP client settings for news workers."""

from __future__ import annotations

from services.news.ssl import httpx_verify

VERIFY_SSL_ENV = "NEWS_HTTP_VERIFY_SSL_CERTS"


def http_verify_ssl() -> bool | str:
    """httpx verify for RSS/article fetches — Russian CA bundle when mounted."""
    return httpx_verify(disable_env=VERIFY_SSL_ENV)
