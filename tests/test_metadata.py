"""Metadata API tests (U7)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from services.metadata.main import app

CITIES_YAML = Path(__file__).resolve().parents[1] / "broadcast" / "liquidsoap" / "cities.yaml"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("CITIES_YAML_PATH", str(CITIES_YAML))
    monkeypatch.setenv("DEFAULT_CITY_TAG", "moscow")
    with TestClient(app) as test_client:
        yield test_client


def test_now_playing_unknown_city(client):
    response = client.get("/api/now-playing/berlin")
    assert response.status_code == 404
    assert response.json()["error"] == "unknown_city"


def test_now_playing_maps_redis_hash(client):
    mock_redis = MagicMock()
    mock_redis.hgetall.return_value = {
        "type": "MUSIC",
        "title": "Evening Drive",
        "artist": "FM21 Static Bed",
        "started_at": "1717867800",
        "duration_sec": "240",
    }
    app.state.redis = mock_redis

    response = client.get("/api/now-playing/moscow")
    assert response.status_code == 200
    payload = response.json()
    assert payload["city_tag"] == "moscow"
    assert payload["title"] == "Evening Drive"
    assert payload["artist"] == "FM21 Static Bed"
    assert payload["content_type"] == "music"
    assert payload["duration_sec"] == 240
    assert payload["started_at"].endswith("Z")


def test_now_playing_ad_type(client):
    mock_redis = MagicMock()
    mock_redis.hgetall.return_value = {
        "type": "AD",
        "title": "Voice ad",
        "artist": "",
        "started_at": "1717867800",
        "duration_sec": "42",
    }
    app.state.redis = mock_redis

    response = client.get("/api/now-playing/spb")
    assert response.status_code == 200
    assert response.json()["content_type"] == "ad"
    assert response.json()["artist"] is None
