"""Priority dequeue tests — Broadcast Semantics §4, U13."""

from __future__ import annotations

from pathlib import Path

import pytest

from services.injector.fanout import TYPE_PRIORITIES, build_queue_item
from services.injector.queue import QueueClient

DEQUEUE_LUA = (Path(__file__).resolve().parents[1] / "broadcast/liquidsoap/dequeue.lua").read_text()
CITY = "moscow"

pytestmark = pytest.mark.usefixtures("queue_client")


def _enqueue_raw(queue_client: QueueClient, item: dict) -> None:
    queue_client.enqueue_item(CITY, item)


def _enqueue(
    queue_client: QueueClient,
    *,
    item_type: str,
    uri: str,
    title: str,
    artist: str = "",
    duration_sec: int = 180,
    extra_meta: dict | None = None,
) -> dict:
    meta = {"title": title, "artist": artist, "duration_sec": duration_sec}
    if extra_meta:
        meta.update(extra_meta)
    item = build_queue_item(
        item_type=item_type,
        uri=uri,
        city_tag=CITY,
        meta=meta,
    )
    _enqueue_raw(queue_client, item)
    return item


def _run_dequeue(queue_client: QueueClient) -> list[str]:
    key = queue_client.queue_key(CITY)
    result = queue_client._redis.eval(DEQUEUE_LUA, 1, key)
    if result is None:
        return []
    if isinstance(result, list):
        return [str(line) for line in result]
    return [str(result)]


def _parse_line(line: str) -> dict[str, str]:
    uri, type_, title, artist, duration, part = (line + "\t\t\t\t\t").split("\t")[:6]
    return {
        "uri": uri,
        "type": type_,
        "title": title,
        "artist": artist,
        "duration": duration,
        "part": part,
    }


def test_empty_queue_returns_nothing(queue_client: QueueClient) -> None:
    assert _run_dequeue(queue_client) == []


def test_ad_dequeued_before_music(queue_client: QueueClient) -> None:
    """Higher priority AD wins even when MUSIC was enqueued first."""
    music = _enqueue(
        queue_client,
        item_type="MUSIC",
        uri="https://storage.yandex.net/music/track-a.mp3",
        title="Track A",
        artist="Artist A",
    )
    ad = _enqueue(
        queue_client,
        item_type="AD",
        uri="file:///data/ads/voice.mp3",
        title="Voice ad",
        duration_sec=42,
    )

    lines = _run_dequeue(queue_client)
    assert len(lines) == 1
    picked = _parse_line(lines[0])
    assert picked["type"] == "AD"
    assert picked["uri"] == ad["uri"]
    assert picked["uri"] != music["uri"]

    remaining = queue_client.list_items(CITY)
    assert len(remaining) == 1
    assert remaining[0]["type"] == "MUSIC"


def test_music_order_before_music(queue_client: QueueClient) -> None:
    _enqueue(
        queue_client,
        item_type="MUSIC",
        uri="https://storage.yandex.net/music/filler.mp3",
        title="Filler",
    )
    order = _enqueue(
        queue_client,
        item_type="MUSIC_ORDER",
        uri="https://storage.yandex.net/music/ordered.mp3",
        title="Ordered",
        artist="Band",
    )

    lines = _run_dequeue(queue_client)
    picked = _parse_line(lines[0])
    assert picked["type"] == "MUSIC_ORDER"
    assert picked["uri"] == order["uri"]


def test_news_pair_before_music_order(queue_client: QueueClient) -> None:
    _enqueue(
        queue_client,
        item_type="MUSIC_ORDER",
        uri="https://storage.yandex.net/music/order.mp3",
        title="Order",
    )
    news = _enqueue(
        queue_client,
        item_type="NEWS_PAIR",
        uri="file:///data/news/segment.mp3",
        title="IT headline",
        duration_sec=90,
        extra_meta={"stinger_uri": "file:///data/news/stinger.mp3"},
    )

    lines = _run_dequeue(queue_client)
    assert len(lines) == 2
    stinger = _parse_line(lines[0])
    main = _parse_line(lines[1])
    assert stinger["type"] == "NEWS_PAIR"
    assert stinger["part"] == "stinger"
    assert stinger["uri"] == news["meta"]["stinger_uri"]
    assert main["part"] == "main"
    assert main["uri"] == news["uri"]


def test_fifo_within_same_priority(queue_client: QueueClient) -> None:
    """Among equal priority, oldest enqueued item (tail) dequeues first."""
    first = _enqueue(
        queue_client,
        item_type="AD",
        uri="file:///data/ads/first.mp3",
        title="First ad",
        duration_sec=30,
    )
    _enqueue(
        queue_client,
        item_type="MUSIC",
        uri="https://storage.yandex.net/music/bed.mp3",
        title="Bed",
    )
    second = _enqueue(
        queue_client,
        item_type="AD",
        uri="file:///data/ads/second.mp3",
        title="Second ad",
        duration_sec=30,
    )

    lines = _run_dequeue(queue_client)
    picked = _parse_line(lines[0])
    assert picked["type"] == "AD"
    assert picked["uri"] == first["uri"]
    assert picked["uri"] != second["uri"]

    lines = _run_dequeue(queue_client)
    picked = _parse_line(lines[0])
    assert picked["uri"] == second["uri"]


def test_dequeue_removes_exact_item(queue_client: QueueClient) -> None:
    items = [
        _enqueue(
            queue_client,
            item_type="MUSIC",
            uri=f"https://example.com/{i}.mp3",
            title=f"Track {i}",
        )
        for i in range(3)
    ]
    assert len(queue_client.list_items(CITY)) == 3

    lines = _run_dequeue(queue_client)
    picked = _parse_line(lines[0])
    assert picked["uri"] == items[0]["uri"]

    remaining = queue_client.list_items(CITY)
    assert len(remaining) == 2
    remaining_uris = {item["uri"] for item in remaining}
    assert items[0]["uri"] not in remaining_uris
    assert items[1]["uri"] in remaining_uris
    assert items[2]["uri"] in remaining_uris


def test_priority_table_matches_contract() -> None:
    assert TYPE_PRIORITIES["AD"] == 100
    assert TYPE_PRIORITIES["NEWS_PAIR"] == 80
    assert TYPE_PRIORITIES["MUSIC_ORDER"] == 50
    assert TYPE_PRIORITIES["MUSIC"] == 10


def test_mixed_queue_full_priority_order(queue_client: QueueClient) -> None:
    """AD > NEWS_PAIR > MUSIC_ORDER > MUSIC in one mixed list."""
    _enqueue(
        queue_client,
        item_type="MUSIC",
        uri="file:///music/10.mp3",
        title="m",
    )
    _enqueue(
        queue_client,
        item_type="MUSIC_ORDER",
        uri="file:///music/50.mp3",
        title="o",
    )
    _enqueue(
        queue_client,
        item_type="NEWS_PAIR",
        uri="file:///news/main.mp3",
        title="n",
        extra_meta={"stinger_uri": "file:///news/stinger.mp3"},
    )
    _enqueue(
        queue_client,
        item_type="AD",
        uri="file:///ads/100.mp3",
        title="a",
        duration_sec=20,
    )
    expected_order = ["AD", "NEWS_PAIR", "MUSIC_ORDER", "MUSIC"]

    for expected_type in expected_order:
        lines = _run_dequeue(queue_client)
        if expected_type == "NEWS_PAIR":
            assert len(lines) == 2
            assert _parse_line(lines[0])["part"] == "stinger"
            assert _parse_line(lines[1])["type"] == "NEWS_PAIR"
        else:
            assert len(lines) == 1
            assert _parse_line(lines[0])["type"] == expected_type

    assert queue_client.list_items(CITY) == []


def test_dequeue_preserves_pipe_in_https_url(queue_client: QueueClient) -> None:
    """Yandex signed URLs may contain '|' — tab delimiter must not truncate uri."""
    signed = "https://api.music.yandex.net/get-mp3/abc|def/U2FsdGVkX1_test"
    item = _enqueue(
        queue_client,
        item_type="MUSIC",
        uri=signed,
        title="Pipe Test",
        artist="Artist",
    )
    lines = _run_dequeue(queue_client)
    assert len(lines) == 1
    parsed = _parse_line(lines[0])
    assert parsed["uri"] == signed
    assert parsed["type"] == "MUSIC"
    assert parsed["title"] == "Pipe Test"
    assert queue_client.list_items(CITY) == []
    assert item["id"]
