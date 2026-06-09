"""Injector service tests — AE1, AE-QUEUE-FULL, AE-ALL-FANOUT (U5)."""

from __future__ import annotations

import concurrent.futures
import json

import pytest
from fastapi.testclient import TestClient

from services.injector.fanout import build_queue_item
from services.injector.queue import QueueClient

pytestmark = pytest.mark.usefixtures("queue_client")


def _enqueue(
    client: TestClient,
    headers: dict[str, str],
    payload: dict,
    *,
    expected_status: int = 201,
) -> dict:
    response = client.post("/internal/enqueue", json=payload, headers=headers)
    assert response.status_code == expected_status, response.text
    return response.json()


def test_enqueue_moscow_not_in_spb(injector_client, auth_headers, ad_payload, queue_client):
    body = _enqueue(injector_client, auth_headers, ad_payload)

    assert body["city_tags"] == ["moscow"]
    moscow_items = queue_client.list_items("moscow")
    spb_items = queue_client.list_items("spb")
    assert len(moscow_items) == 1
    assert len(spb_items) == 0
    assert moscow_items[0]["type"] == "AD"
    assert moscow_items[0]["priority"] == 100
    assert moscow_items[0]["city_tag"] == "moscow"
    assert moscow_items[0]["id"] == body["id"]


def test_sixth_ad_rejected_with_409(injector_client, auth_headers, ad_payload, queue_client):
    for i in range(5):
        payload = {**ad_payload, "uri": f"file:///data/ads/ad-{i}.mp3"}
        _enqueue(injector_client, auth_headers, payload)

    assert queue_client.count_pending_ads("moscow") == 5

    response = injector_client.post("/internal/enqueue", json=ad_payload, headers=auth_headers)
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["error"] == "queue_full"
    assert detail["city_tag"] == "moscow"
    assert queue_client.count_pending_ads("moscow") == 5


def test_ad_count_ignores_non_ad_items(injector_client, auth_headers, ad_payload, queue_client):
    """Capacity uses AD scan, not LLEN — mixed-type lists count AD only."""
    filler = build_queue_item(
        item_type="AD",
        uri="file:///data/ads/filler.mp3",
        city_tag="moscow",
        meta={"title": "filler", "artist": "", "duration_sec": 10},
    )
    filler["type"] = "MUSIC"
    filler["priority"] = 10
    queue_client._redis.lpush(queue_client.queue_key("moscow"), json.dumps(filler))

    for i in range(5):
        payload = {**ad_payload, "uri": f"file:///data/ads/ad-{i}.mp3"}
        _enqueue(injector_client, auth_headers, payload)

    response = injector_client.post("/internal/enqueue", json=ad_payload, headers=auth_headers)
    assert response.status_code == 409
    assert queue_client.count_pending_ads("moscow") == 5


def test_all_fanout_both_cities(injector_client, auth_headers, ad_payload, queue_client):
    payload = {**ad_payload, "city_tag": "all"}
    body = _enqueue(injector_client, auth_headers, payload)

    assert set(body["city_tags"]) == {"moscow", "spb"}
    assert len(body["ids"]) == 2
    assert body["ids"][0] != body["ids"][1]

    moscow_items = queue_client.list_items("moscow")
    spb_items = queue_client.list_items("spb")
    assert len(moscow_items) == 1
    assert len(spb_items) == 1
    assert moscow_items[0]["uri"] == spb_items[0]["uri"]
    assert moscow_items[0]["meta"] == spb_items[0]["meta"]
    assert moscow_items[0]["id"] != spb_items[0]["id"]
    assert moscow_items[0]["city_tag"] == "moscow"
    assert spb_items[0]["city_tag"] == "spb"


def test_all_fanout_rejects_when_any_city_full(injector_client, auth_headers, ad_payload, queue_client):
    for i in range(5):
        payload = {**ad_payload, "uri": f"file:///data/ads/moscow-{i}.mp3"}
        _enqueue(injector_client, auth_headers, payload)

    payload = {**ad_payload, "city_tag": "all", "uri": "file:///data/ads/global.mp3"}
    response = injector_client.post("/internal/enqueue", json=payload, headers=auth_headers)
    assert response.status_code == 409

    assert queue_client.count_pending_ads("moscow") == 5
    assert queue_client.count_pending_ads("spb") == 0


def test_invalid_city_tag_returns_400(injector_client, auth_headers, ad_payload):
    payload = {**ad_payload, "city_tag": "berlin"}
    response = injector_client.post("/internal/enqueue", json=payload, headers=auth_headers)
    assert response.status_code == 400


def test_duration_over_limit_returns_400(injector_client, auth_headers, ad_payload):
    payload = {**ad_payload, "meta": {**ad_payload["meta"], "duration_sec": 61}}
    response = injector_client.post("/internal/enqueue", json=payload, headers=auth_headers)
    assert response.status_code == 400


def test_missing_token_returns_401(injector_client, ad_payload):
    response = injector_client.post("/internal/enqueue", json=ad_payload)
    assert response.status_code == 401


def test_wrong_token_returns_401(injector_client, ad_payload):
    headers = {"X-FM21-Internal-Token": "wrong"}
    response = injector_client.post("/internal/enqueue", json=ad_payload, headers=headers)
    assert response.status_code == 401


def test_concurrent_enqueue_respects_capacity(injector_client, auth_headers, ad_payload, queue_client):
    """Atomic Lua script prevents more than 5 pending ADs under concurrency."""
    payloads = [
        {
            **ad_payload,
            "uri": f"file:///data/ads/concurrent-{i}.mp3",
            "meta": {**ad_payload["meta"], "title": f"ad-{i}"},
        }
        for i in range(10)
    ]

    def _post(payload: dict) -> int:
        return injector_client.post("/internal/enqueue", json=payload, headers=auth_headers).status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        statuses = list(pool.map(_post, payloads))

    assert statuses.count(201) == 5
    assert statuses.count(409) == 5
    assert queue_client.count_pending_ads("moscow") == 5
