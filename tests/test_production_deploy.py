"""Production deploy manifests (U30) — env template, gateway, webhook script."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

from services.injector.fanout import load_active_cities

REPO_ROOT = Path(__file__).resolve().parents[1]
PROD_DIR = REPO_ROOT / "deploy" / "production"
ENV_TEMPLATE = PROD_DIR / "env.template"
NGINX_PROD_CONF = PROD_DIR / "gateway" / "nginx.conf"
COMPOSE_PROD = PROD_DIR / "docker-compose.prod.yml"
SET_WEBHOOK_SCRIPT = REPO_ROOT / "scripts" / "set_telegram_webhook.sh"
CITIES_YAML = REPO_ROOT / "broadcast" / "liquidsoap" / "cities.yaml"

REQUIRED_ENV_KEYS = (
    "TELEGRAM_BOT_TOKEN",
    "DATABASE_URL",
    "REDIS_URL",
    "ICECAST_SOURCE_PASSWORD",
    "INTERNAL_ENQUEUE_TOKEN",
    "TELEGRAM_WEBHOOK_SECRET",
    "BOT_MODE",
    "POSTGRES_PASSWORD",
    "POSTGRES_USER",
    "POSTGRES_DB",
)


@pytest.fixture
def active_cities() -> list[str]:
    return load_active_cities(str(CITIES_YAML))


def test_production_compose_exists() -> None:
    assert COMPOSE_PROD.is_file(), "deploy/production/docker-compose.prod.yml is required"


def test_env_template_exists_with_required_keys() -> None:
    assert ENV_TEMPLATE.is_file(), "deploy/production/env.template is required"
    text = ENV_TEMPLATE.read_text(encoding="utf-8")
    for key in REQUIRED_ENV_KEYS:
        assert key in text, f"env.template missing required key {key}"


def test_env_template_documents_polling_default() -> None:
    text = ENV_TEMPLATE.read_text(encoding="utf-8")
    assert "BOT_MODE" in text
    assert "polling" in text


@pytest.mark.parametrize("city", load_active_cities(str(CITIES_YAML)))
def test_prod_nginx_has_static_mount_location(city: str) -> None:
    conf = NGINX_PROD_CONF.read_text(encoding="utf-8")
    pattern = rf"location\s*=\s*/{re.escape(city)}\s*\{{"
    match = re.search(pattern, conf)
    assert match, f"missing static location = /{city} in production nginx.conf"
    block_start = match.start()
    block = conf[block_start : conf.find("}", block_start) + 1]
    assert f"proxy_pass http://icecast:8000/{city};" in block
    assert "$request_uri" not in block


def test_prod_nginx_listens_http_only() -> None:
    conf = NGINX_PROD_CONF.read_text(encoding="utf-8")
    assert "listen 80" in conf
    assert "ssl_certificate" not in conf
    assert "listen 443" not in conf


def test_set_telegram_webhook_script_exists_and_is_valid_bash() -> None:
    assert SET_WEBHOOK_SCRIPT.is_file(), "scripts/set_telegram_webhook.sh is required"
    result = subprocess.run(
        ["bash", "-n", str(SET_WEBHOOK_SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"bash -n failed: {result.stderr}"


def test_set_telegram_webhook_script_documents_https_requirement() -> None:
    text = SET_WEBHOOK_SCRIPT.read_text(encoding="utf-8")
    lowered = text.casefold()
    assert "https" in lowered
    assert "TELEGRAM_WEBHOOK_URL" in text


def test_cities_yaml_tags_match_prod_nginx(active_cities: list[str]) -> None:
    raw = yaml.safe_load(CITIES_YAML.read_text(encoding="utf-8"))
    tags = [entry["tag"] for entry in raw["cities"]]
    assert tags == active_cities
