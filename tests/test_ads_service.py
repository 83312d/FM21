"""Ads service HTTP tests — duration limit, queue full, all fan-out (U24)."""

from __future__ import annotations

import asyncio
import io
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sqlalchemy import select

from services.ads import injector_client as ads_injector
from services.db.migrate import run_migrations
from services.db.models import Ad, AdStatus
from services.db.session import async_session_factory, reset_engine
from services.injector.main import app as injector_app
from services.injector.queue import QueueClient

TEST_TOKEN = "test-internal-token"


@pytest.fixture(autouse=True)
def _reset_engine():
    reset_engine()
    yield
    reset_engine()


@pytest.fixture(autouse=True)
def _null_pool_engine(monkeypatch: pytest.MonkeyPatch):
    from sqlalchemy.ext.asyncio import create_async_engine as real_create_async_engine
    from sqlalchemy.pool import NullPool

    def _create_engine(url: str, **kwargs):
        kwargs["poolclass"] = NullPool
        return real_create_async_engine(url, **kwargs)

    monkeypatch.setattr("services.db.session.create_async_engine", _create_engine)


@pytest.fixture
def active_cities() -> list[str]:
    from services.injector.fanout import load_active_cities

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
def auth_headers() -> dict[str, str]:
    return {"X-FM21-Internal-Token": TEST_TOKEN}


@pytest.fixture
def injector_client(queue_client: QueueClient, active_cities: list[str], monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("INTERNAL_ENQUEUE_TOKEN", TEST_TOKEN)
    injector_app.state.active_cities = active_cities
    injector_app.state.queue = queue_client
    with TestClient(injector_app) as client:
        yield client


@pytest.fixture
def migrated_db():
    reset_engine()
    asyncio.run(run_migrations())
    yield
    reset_engine()


@pytest.fixture
def ads_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    ads_path = tmp_path / "ads"
    ads_path.mkdir()
    monkeypatch.setenv("ADS_DIR", str(ads_path))
    return ads_path


@pytest.fixture
def patch_ads_injector(injector_client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch):
    from services.ads import injector_client as ads_injector

    async def _enqueue_ad(
        *,
        uri: str,
        city_tag: str,
        duration_sec: int,
    ) -> ads_injector.EnqueueResult | ads_injector.EnqueueFailure:
        payload = {
            "type": "AD",
            "uri": uri,
            "city_tag": city_tag,
            "meta": {
                "title": "Voice ad",
                "artist": "",
                "duration_sec": duration_sec,
            },
        }
        response = injector_client.post(
            "/internal/enqueue",
            json=payload,
            headers=auth_headers,
        )
        if response.status_code == 201:
            body = response.json()
            return ads_injector.EnqueueResult(city_tags=body.get("city_tags", [city_tag]))
        message = "Failed to enqueue AD."
        city: str | None = None
        try:
            detail = response.json().get("detail")
            if isinstance(detail, dict):
                message = detail.get("message", message)
                city = detail.get("city_tag")
            elif isinstance(detail, str):
                message = detail
        except (ValueError, AttributeError):
            pass
        return ads_injector.EnqueueFailure(
            status_code=response.status_code,
            message=message,
            city_tag=city,
        )

    monkeypatch.setattr(ads_injector, "enqueue_ad", _enqueue_ad)


@pytest.fixture
def fast_transcode(monkeypatch: pytest.MonkeyPatch):
    def _fake(source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"ID3\x03\x00\x00\x00\x00\x00\x00")

    monkeypatch.setattr("services.ads.service.transcode_ogg_to_mp3", _fake)
    monkeypatch.setattr("services.ads.service.probe_duration_sec", lambda _path: 30.0)


@pytest.fixture
def ads_client(
    active_cities: list[str],
    ads_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    patch_ads_injector,
    fast_transcode,
    migrated_db,
):
    monkeypatch.setenv("INTERNAL_ENQUEUE_TOKEN", TEST_TOKEN)
    monkeypatch.setenv("INJECTOR_URL", "http://injector:8080")
    from services.ads.main import app as ads_app

    ads_app.state.active_cities = active_cities
    with TestClient(ads_app) as client:
        yield client


def _latest_ad() -> Ad | None:
    async def _fetch() -> Ad | None:
        async with async_session_factory()() as session:
            result = await session.execute(select(Ad).order_by(Ad.id.desc()).limit(1))
            return result.scalar_one_or_none()

    return asyncio.run(_fetch())


def _ads_test_client(
    active_cities: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    monkeypatch.setenv("INTERNAL_ENQUEUE_TOKEN", TEST_TOKEN)
    monkeypatch.setenv("INJECTOR_URL", "http://injector:8080")
    from services.ads.main import app as ads_app

    ads_app.state.active_cities = active_cities
    return TestClient(ads_app)


def _submit(
    client: TestClient,
    headers: dict[str, str],
    *,
    duration_sec: int = 30,
    city_tag: str = "moscow",
    telegram_user_id: int = 42,
    audio: bytes = b"fake-ogg",
    expected_status: int = 201,
) -> dict:
    response = client.post(
        "/internal/ads/submit",
        headers=headers,
        data={
            "telegram_user_id": str(telegram_user_id),
            "city_tag": city_tag,
            "duration_sec": str(duration_sec),
        },
        files={"audio": ("voice.ogg", io.BytesIO(audio), "audio/ogg")},
    )
    assert response.status_code == expected_status, response.text
    return response.json()


def test_rejects_61_second_duration(ads_client: TestClient, auth_headers: dict[str, str]):
    response = ads_client.post(
        "/internal/ads/submit",
        headers=auth_headers,
        data={
            "telegram_user_id": "1",
            "city_tag": "moscow",
            "duration_sec": "61",
        },
        files={"audio": ("voice.ogg", io.BytesIO(b"fake-ogg"), "audio/ogg")},
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["error"] == "duration_exceeded"
    assert "60" in detail["message"]


def test_sixth_ad_rejected_with_409(
    ads_client: TestClient,
    auth_headers: dict[str, str],
    queue_client: QueueClient,
):
    for i in range(5):
        _submit(ads_client, auth_headers, duration_sec=10 + i)

    assert queue_client.count_pending_ads("moscow") == 5

    response = ads_client.post(
        "/internal/ads/submit",
        headers=auth_headers,
        data={
            "telegram_user_id": "99",
            "city_tag": "moscow",
            "duration_sec": "15",
        },
        files={"audio": ("voice.ogg", io.BytesIO(b"fake-ogg"), "audio/ogg")},
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["error"] == "queue_full"
    assert detail["city_tag"] == "moscow"
    assert queue_client.count_pending_ads("moscow") == 5


def test_all_fanout_both_cities(
    ads_client: TestClient,
    auth_headers: dict[str, str],
    queue_client: QueueClient,
    active_cities: list[str],
):
    body = _submit(ads_client, auth_headers, city_tag="all")

    assert set(body["city_tags"]) == set(active_cities)
    for city in active_cities:
        ads = [i for i in queue_client.list_items(city) if i["type"] == "AD"]
        assert len(ads) == 1
    assert body["city_tag"] == "all"


def test_injector_503_returns_non_409(
    ads_client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
):
    async def _enqueue_unavailable(**_kwargs) -> ads_injector.EnqueueFailure:
        return ads_injector.EnqueueFailure(
            status_code=503,
            message="INTERNAL_ENQUEUE_TOKEN not configured",
        )

    monkeypatch.setattr(ads_injector, "enqueue_ad", _enqueue_unavailable)

    response = ads_client.post(
        "/internal/ads/submit",
        headers=auth_headers,
        data={
            "telegram_user_id": "7",
            "city_tag": "moscow",
            "duration_sec": "20",
        },
        files={"audio": ("voice.ogg", io.BytesIO(b"fake-ogg"), "audio/ogg")},
    )
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["error"] == "injector_error"
    assert "queue_full" not in str(detail)


def test_success_marks_ad_queued_and_keeps_mp3(
    active_cities: list[str],
    auth_headers: dict[str, str],
    ads_dir: Path,
    patch_ads_injector,
    fast_transcode,
    migrated_db,
    monkeypatch: pytest.MonkeyPatch,
):
    with _ads_test_client(active_cities, monkeypatch) as client:
        body = _submit(client, auth_headers)
    reset_engine()

    row = _latest_ad()
    assert row is not None
    assert row.id == body["id"]
    assert row.status == AdStatus.QUEUED
    mp3_path = Path(row.audio_url.removeprefix("file://"))
    assert mp3_path.is_file()


def test_queue_full_marks_ad_rejected_and_unlinks_mp3(
    active_cities: list[str],
    auth_headers: dict[str, str],
    queue_client: QueueClient,
    patch_ads_injector,
    fast_transcode,
    migrated_db,
    monkeypatch: pytest.MonkeyPatch,
):
    with _ads_test_client(active_cities, monkeypatch) as client:
        for i in range(5):
            _submit(client, auth_headers, duration_sec=10 + i, telegram_user_id=100 + i)

        response = client.post(
            "/internal/ads/submit",
            headers=auth_headers,
            data={
                "telegram_user_id": "200",
                "city_tag": "moscow",
                "duration_sec": "12",
            },
            files={"audio": ("voice.ogg", io.BytesIO(b"fake-ogg"), "audio/ogg")},
        )
        assert response.status_code == 409
    reset_engine()

    row = _latest_ad()
    assert row is not None
    assert row.telegram_user_id == 200
    assert row.status == AdStatus.REJECTED
    mp3_path = Path(row.audio_url.removeprefix("file://"))
    assert not mp3_path.exists()


def test_missing_internal_token_returns_401(
    active_cities: list[str],
    ads_dir: Path,
    fast_transcode,
    migrated_db,
    monkeypatch: pytest.MonkeyPatch,
):
    with _ads_test_client(active_cities, monkeypatch) as client:
        response = client.post(
            "/internal/ads/submit",
            data={
                "telegram_user_id": "1",
                "city_tag": "moscow",
                "duration_sec": "10",
            },
            files={"audio": ("voice.ogg", io.BytesIO(b"fake-ogg"), "audio/ogg")},
        )
    assert response.status_code == 401
    detail = response.json()["detail"]
    assert detail["error"] == "unauthorized"


def test_injector_ambiguous_failure_keeps_pending_and_mp3(
    active_cities: list[str],
    auth_headers: dict[str, str],
    patch_ads_injector,
    fast_transcode,
    migrated_db,
    monkeypatch: pytest.MonkeyPatch,
):
    async def _enqueue_ambiguous(**_kwargs) -> ads_injector.EnqueueFailure:
        return ads_injector.EnqueueFailure(
            status_code=502,
            message="Injector request failed: read timeout",
            ambiguous=True,
        )

    monkeypatch.setattr(ads_injector, "enqueue_ad", _enqueue_ambiguous)

    with _ads_test_client(active_cities, monkeypatch) as client:
        response = client.post(
            "/internal/ads/submit",
            headers=auth_headers,
            data={
                "telegram_user_id": "301",
                "city_tag": "moscow",
                "duration_sec": "18",
            },
            files={"audio": ("voice.ogg", io.BytesIO(b"fake-ogg"), "audio/ogg")},
        )
        assert response.status_code == 502
    reset_engine()

    row = _latest_ad()
    assert row is not None
    assert row.telegram_user_id == 301
    assert row.status == AdStatus.PENDING
    mp3_path = Path(row.audio_url.removeprefix("file://"))
    assert mp3_path.is_file()


def test_injector_failure_marks_ad_rejected_and_unlinks_mp3(
    active_cities: list[str],
    auth_headers: dict[str, str],
    patch_ads_injector,
    fast_transcode,
    migrated_db,
    monkeypatch: pytest.MonkeyPatch,
):
    async def _enqueue_unavailable(**_kwargs) -> ads_injector.EnqueueFailure:
        return ads_injector.EnqueueFailure(
            status_code=503,
            message="Injector request failed: connection refused",
        )

    monkeypatch.setattr(ads_injector, "enqueue_ad", _enqueue_unavailable)

    with _ads_test_client(active_cities, monkeypatch) as client:
        response = client.post(
            "/internal/ads/submit",
            headers=auth_headers,
            data={
                "telegram_user_id": "300",
                "city_tag": "moscow",
                "duration_sec": "18",
            },
            files={"audio": ("voice.ogg", io.BytesIO(b"fake-ogg"), "audio/ogg")},
        )
        assert response.status_code == 503
    reset_engine()

    row = _latest_ad()
    assert row is not None
    assert row.telegram_user_id == 300
    assert row.status == AdStatus.REJECTED
    mp3_path = Path(row.audio_url.removeprefix("file://"))
    assert not mp3_path.exists()
