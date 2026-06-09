"""Shared pytest fixtures for FM21 glue service tests."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from services.injector.fanout import load_active_cities
from services.injector.main import app
from services.injector.queue import QueueClient

TEST_TOKEN = "test-internal-token"


@pytest.fixture
def active_cities() -> list[str]:
    path = os.environ.get("CITIES_YAML_PATH", "broadcast/liquidsoap/cities.yaml")
    return load_active_cities(path)


@pytest.fixture
def queue_client(active_cities: list[str]) -> QueueClient:
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    max_pending = int(os.environ.get("MAX_PENDING_ADS_PER_CITY", "5"))
    client = QueueClient(redis_url, max_pending)
    client.flush_all(active_cities)
    yield client
    client.flush_all(active_cities)


@pytest.fixture
def injector_client(queue_client: QueueClient, active_cities: list[str], monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("INTERNAL_ENQUEUE_TOKEN", TEST_TOKEN)
    app.state.active_cities = active_cities
    app.state.queue = queue_client
    with TestClient(app) as client:
        yield client


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"X-FM21-Internal-Token": TEST_TOKEN}


@pytest.fixture
def ad_payload() -> dict:
    return {
        "type": "AD",
        "uri": "file:///data/ads/test-ad.mp3",
        "city_tag": "moscow",
        "meta": {
            "title": "Voice ad",
            "artist": "",
            "duration_sec": 42,
        },
    }
