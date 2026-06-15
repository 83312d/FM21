"""Injector service tests — AE1, AE2, AE-QUEUE-FULL, AE-ALL-FANOUT (U5, U22)."""

from __future__ import annotations

import concurrent.futures
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from services.injector.fanout import build_queue_item
from services.injector.queue import QueueClient

DEQUEUE_LUA = (Path(__file__).resolve().parents[1] / "broadcast/liquidsoap/dequeue.lua").read_text()
CITY = "moscow"

pytestmark = pytest.mark.usefixtures("queue_client")


def _run_dequeue(queue_client: QueueClient) -> list[str]:
    key = queue_client.queue_key(CITY)
    result = queue_client._redis.eval(DEQUEUE_LUA, 1, key)
    if result is None:
        return []
    if isinstance(result, list):
        return [str(line) for line in result]
    return [str(result)]


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


def test_all_fanout_both_cities(
    injector_client, auth_headers, ad_payload, queue_client, active_cities: list[str]
):
    payload = {**ad_payload, "city_tag": "all"}
    body = _enqueue(injector_client, auth_headers, payload)

    assert set(body["city_tags"]) == set(active_cities)
    assert len(body["ids"]) == len(active_cities)
    assert len(set(body["ids"])) == len(active_cities)

    items_by_city = {city: queue_client.list_items(city) for city in active_cities}
    for city, items in items_by_city.items():
        assert len(items) == 1
        assert items[0]["city_tag"] == city
    uris = {items[0]["uri"] for items in items_by_city.values()}
    metas = {tuple(items[0]["meta"].items()) for items in items_by_city.values()}
    assert len(uris) == 1
    assert len(metas) == 1


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


def test_ae2_injector_accepts_ad_during_simulated_news_pair_playback(
    injector_client,
    auth_headers,
    ad_payload,
    queue_client,
) -> None:
    """AE2: voice ad enqueued mid-NEWS_PAIR block waits in queue at AD priority."""
    news = build_queue_item(
        item_type="NEWS_PAIR",
        uri="file:///data/news/segment.mp3",
        city_tag=CITY,
        meta={
            "title": "IT headline",
            "artist": "",
            "duration_sec": 90,
            "stinger_uri": "file:///data/news/news-stinger.mp3",
        },
    )
    queue_client.enqueue_item(CITY, news)

    lines = _run_dequeue(queue_client)
    assert len(lines) == 2
    assert queue_client.list_items(CITY) == []

    body = _enqueue(injector_client, auth_headers, ad_payload)
    assert body["city_tags"] == [CITY]

    pending = queue_client.list_items(CITY)
    assert len(pending) == 1
    assert pending[0]["type"] == "AD"
    assert pending[0]["priority"] == 100
    assert pending[0]["uri"] == ad_payload["uri"]

    next_lines = _run_dequeue(queue_client)
    assert len(next_lines) == 1
    uri, type_, *_rest = (next_lines[0] + "\t\t\t\t\t").split("\t")[:2]
    assert type_ == "AD"
    assert uri == ad_payload["uri"]


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
