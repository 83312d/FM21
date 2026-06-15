"""Health aggregation tests (U31)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from services.metadata.main import app

CITIES_YAML = Path(__file__).resolve().parents[1] / "broadcast" / "liquidsoap" / "cities.yaml"
REPO_ROOT = Path(__file__).resolve().parents[1]
NGINX_GATEWAY_CONF = REPO_ROOT / "docker/nginx-gateway.conf"
PROD_NGINX_CONF = REPO_ROOT / "deploy/production/gateway/nginx.conf"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("CITIES_YAML_PATH", str(CITIES_YAML))
    monkeypatch.setenv("DEFAULT_CITY_TAG", "moscow")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://fm21:fm21dev@postgres:5432/fm21",
    )
    with TestClient(app) as test_client:
        yield test_client


def _all_components_ok():
    return {
        "redis": {"status": "ok"},
        "postgres": {"status": "ok"},
        "icecast": {"status": "ok"},
        "liquidsoap": {"status": "ok"},
    }


def test_public_health_ok_when_redis_up(client):
    mock_redis = MagicMock()
    mock_redis.ping.return_value = True
    app.state.redis = mock_redis

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_public_health_degraded_when_redis_down(client):
    mock_redis = MagicMock()
    mock_redis.ping.side_effect = ConnectionError("redis unreachable")
    app.state.redis = mock_redis

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "degraded"}


def test_internal_health_reports_all_components(client):
    mock_redis = MagicMock()
    mock_redis.ping.return_value = True
    app.state.redis = mock_redis

    with (
        patch(
            "services.metadata.health.check_postgres",
            new_callable=AsyncMock,
            return_value={"status": "ok"},
        ),
        patch(
            "services.metadata.health.probe_http",
            side_effect=[
                {"status": "ok"},
                {"status": "ok"},
            ],
        ),
    ):
        response = client.get("/internal/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["components"] == _all_components_ok()


def test_internal_health_degraded_when_redis_down(client):
    mock_redis = MagicMock()
    mock_redis.ping.side_effect = ConnectionError("redis unreachable")
    app.state.redis = mock_redis

    with (
        patch(
            "services.metadata.health.check_postgres",
            new_callable=AsyncMock,
            return_value={"status": "ok"},
        ),
        patch(
            "services.metadata.health.probe_http",
            side_effect=[
                {"status": "ok"},
                {"status": "ok"},
            ],
        ),
    ):
        response = client.get("/internal/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["components"]["redis"]["status"] == "down"
    assert body["components"]["postgres"]["status"] == "ok"


def test_gateway_proxies_public_health_to_metadata():
    conf = NGINX_GATEWAY_CONF.read_text(encoding="utf-8")
    assert "location = /api/health" in conf
    assert "proxy_pass http://metadata:8080/api/health" in conf
    assert "return 200" not in conf.split("location = /api/health")[1].split("location")[0]


def test_production_gateway_does_not_expose_internal_health():
    conf = PROD_NGINX_CONF.read_text(encoding="utf-8")
    assert "location" not in conf or "internal/health" not in conf
    assert "proxy_pass http://metadata:8080/internal" not in conf


def test_runbook_stream_down_exists():
    runbook = REPO_ROOT / "docs/runbooks/stream-down.md"
    assert runbook.is_file()
    text = runbook.read_text(encoding="utf-8")
    assert "curl" in text.lower()
    assert "liquidsoap" in text.lower()
    assert "icecast" in text.lower()
