"""Gateway rate limits and static caching (U33) — nginx config contract."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
NGINX_PROD_CONF = REPO_ROOT / "deploy" / "production" / "gateway" / "nginx.conf"
NGINX_DEV_CONF = REPO_ROOT / "docker" / "nginx-gateway.conf"


def _location_block(conf: str, location_pattern: str) -> str:
    match = re.search(location_pattern, conf)
    assert match, f"missing location matching {location_pattern!r}"
    block_start = match.start()
    return conf[block_start : conf.find("}", block_start) + 1]


@pytest.mark.parametrize(
    ("conf_path", "label"),
    [
        (NGINX_PROD_CONF, "production"),
        (NGINX_DEV_CONF, "dev"),
    ],
)
def test_nginx_defines_geo_and_webhook_limit_zones(conf_path: Path, label: str) -> None:
    conf = conf_path.read_text(encoding="utf-8")
    assert "limit_req_zone $binary_remote_addr zone=geo_api:" in conf, (
        f"{label} nginx.conf must define geo_api limit_req_zone"
    )
    assert "limit_req_zone $binary_remote_addr zone=bot_webhook:" in conf, (
        f"{label} nginx.conf must define bot_webhook limit_req_zone"
    )


def test_prod_nginx_applies_limit_req_to_geo_with_burst() -> None:
    conf = NGINX_PROD_CONF.read_text(encoding="utf-8")
    block = _location_block(conf, r"location\s+/api/geo/\s*\{")
    assert "limit_req zone=geo_api" in block
    assert "burst=" in block


def test_prod_nginx_applies_limit_req_to_webhook_with_burst() -> None:
    conf = NGINX_PROD_CONF.read_text(encoding="utf-8")
    block = _location_block(conf, r"location\s*=\s*/api/bot/webhook\s*\{")
    assert "limit_req zone=bot_webhook" in block
    assert "burst=" in block
    assert "proxy_pass http://bot:8080/api/bot/webhook" in block


def test_prod_nginx_webhook_location_is_exact_match_before_general_bot() -> None:
    conf = NGINX_PROD_CONF.read_text(encoding="utf-8")
    webhook_idx = conf.index("location = /api/bot/webhook")
    bot_prefix_idx = conf.index("location /api/bot/")
    assert webhook_idx < bot_prefix_idx, (
        "exact webhook location should appear before general /api/bot/ block"
    )


def test_prod_nginx_static_assets_have_cache_headers() -> None:
    conf = NGINX_PROD_CONF.read_text(encoding="utf-8")
    block = _location_block(conf, r"location\s+~\*\s+\\\.\(")
    assert "expires" in block
    assert "Cache-Control" in block
    assert "immutable" in block


def test_dev_nginx_mirrors_geo_and_webhook_limits() -> None:
    conf = NGINX_DEV_CONF.read_text(encoding="utf-8")
    geo_block = _location_block(conf, r"location\s+/api/geo/\s*\{")
    webhook_block = _location_block(conf, r"location\s*=\s*/api/bot/webhook\s*\{")
    assert "limit_req zone=geo_api" in geo_block
    assert "limit_req zone=bot_webhook" in webhook_block
