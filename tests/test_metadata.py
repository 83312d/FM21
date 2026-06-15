"""Metadata API tests (U7, U28)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from services.injector.fanout import build_queue_item
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


def test_now_playing_not_playing_when_redis_empty(client):
    mock_redis = MagicMock()
    mock_redis.hgetall.return_value = {}
    app.state.redis = mock_redis

    response = client.get("/api/now-playing/moscow")
    assert response.status_code == 404
    body = response.json()
    assert body["error"] == "not_playing"


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


def test_now_playing_includes_remaining_sec(client):
    mock_redis = MagicMock()
    mock_redis.hgetall.return_value = {
        "type": "MUSIC",
        "title": "Evening Drive",
        "artist": "FM21 Static Bed",
        "started_at": "1717872600",
        "duration_sec": "240",
    }
    app.state.redis = mock_redis
    fixed_now = datetime(2024, 6, 8, 18, 52, 0, tzinfo=UTC)

    with patch("services.metadata.now_playing.utc_now", return_value=fixed_now):
        response = client.get("/api/now-playing/moscow")

    assert response.status_code == 200
    payload = response.json()
    assert payload["remaining_sec"] == 120


def test_now_playing_remaining_sec_never_negative(client):
    mock_redis = MagicMock()
    mock_redis.hgetall.return_value = {
        "type": "MUSIC",
        "title": "Evening Drive",
        "artist": "FM21 Static Bed",
        "started_at": "1717867800",
        "duration_sec": "240",
    }
    app.state.redis = mock_redis
    fixed_now = datetime(2024, 6, 8, 19, 30, 0, tzinfo=UTC)

    with patch("services.metadata.now_playing.utc_now", return_value=fixed_now):
        response = client.get("/api/now-playing/moscow")

    assert response.status_code == 200
    assert response.json()["remaining_sec"] == 0


def test_queue_unknown_city(client):
    response = client.get("/api/queue/berlin")
    assert response.status_code == 404
    assert response.json()["error"] == "unknown_city"


def test_queue_empty_returns_empty_items(client):
    mock_redis = MagicMock()
    mock_redis.lrange.return_value = []
    app.state.redis = mock_redis

    response = client.get("/api/queue/moscow")
    assert response.status_code == 200
    payload = response.json()
    assert payload["city_tag"] == "moscow"
    assert payload["items"] == []


def _queue_item(item_type: str, title: str, *, duration_sec: int = 180) -> str:
    item = build_queue_item(
        item_type=item_type,
        uri=f"file:///data/{item_type.lower()}.mp3",
        city_tag="moscow",
        meta={"title": title, "artist": "", "duration_sec": duration_sec},
    )
    return json.dumps(item, separators=(",", ":"))


def test_queue_preview_priority_order_and_limit(client):
    mock_redis = MagicMock()
    mock_redis.lrange.return_value = [
        _queue_item("MUSIC", "Bed track"),
        _queue_item("MUSIC_ORDER", "Ordered track"),
        _queue_item("NEWS_PAIR", "IT headline", duration_sec=90),
        _queue_item("AD", "Voice ad", duration_sec=42),
        _queue_item("MUSIC", "Second bed"),
        _queue_item("AD", "Second ad", duration_sec=30),
    ]
    app.state.redis = mock_redis

    response = client.get("/api/queue/moscow")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 5
    assert [item["content_type"] for item in items] == ["ad", "ad", "news", "music", "music"]
    assert items[0]["title"] == "Second ad"
    assert items[1]["title"] == "Voice ad"
    assert items[2]["title"] == "IT headline"
    assert items[3]["title"] == "Ordered track"
    assert items[4]["title"] == "Second bed"


def test_queue_preview_public_shape_excludes_internals(client):
    mock_redis = MagicMock()
    mock_redis.lrange.return_value = [_queue_item("AD", "Voice ad", duration_sec=42)]
    app.state.redis = mock_redis

    response = client.get("/api/queue/moscow")
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert set(item.keys()) == {"title", "artist", "content_type", "duration_sec"}
    assert item == {
        "title": "Voice ad",
        "artist": None,
        "content_type": "ad",
        "duration_sec": 42,
    }
