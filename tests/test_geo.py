"""Geo API tests (U6)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml
from fastapi.testclient import TestClient

from services.geo.cities import load_registry
from services.geo.geoip import GeoIPHit, GeoIPService, resolve_city_tag
from services.geo.main import app, get_client_ip
from services.geo.reverse import reverse_geocode


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "geo" / "city_coordinates.yaml"
CITIES_YAML = Path(__file__).resolve().parents[1] / "broadcast" / "liquidsoap" / "cities.yaml"


@pytest.fixture
def registry():
    return load_registry(cities_path=CITIES_YAML, default_tag="moscow")


@pytest.fixture
def coordinates():
    with FIXTURES.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("CITIES_YAML_PATH", str(CITIES_YAML))
    monkeypatch.setenv("DEFAULT_CITY_TAG", "moscow")
    monkeypatch.setenv("GEOIP_DB_PATH", "/nonexistent/GeoLite2-City.mmdb")
    with TestClient(app) as test_client:
        yield test_client


def test_detect_missing_geoip_db_returns_default(client):
    response = client.get("/api/geo/detect")
    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "city_tag": "moscow",
        "city_name": "Москва",
        "source": "default",
    }
    assert "ip" not in payload
    assert "lat" not in payload
    assert "lon" not in payload


def test_detect_moscow_ip_via_mock(client, monkeypatch, registry):
    mock_geoip = MagicMock(spec=GeoIPService)
    mock_geoip.available = True
    mock_geoip.lookup.return_value = GeoIPHit(
        city_name="Moscow",
        latitude=55.7558,
        longitude=37.6173,
    )
    monkeypatch.setattr(app.state, "geoip", mock_geoip)

    response = client.get("/api/geo/detect")
    assert response.status_code == 200
    assert response.json() == {
        "city_tag": "moscow",
        "city_name": "Москва",
        "source": "geoip",
    }


def test_detect_unknown_ip_returns_default(client, monkeypatch):
    mock_geoip = MagicMock(spec=GeoIPService)
    mock_geoip.available = True
    mock_geoip.lookup.return_value = None
    monkeypatch.setattr(app.state, "geoip", mock_geoip)

    response = client.get("/api/geo/detect")
    assert response.status_code == 200
    assert response.json()["source"] == "default"
    assert response.json()["city_tag"] == "moscow"


def test_detect_uses_x_forwarded_for_from_trusted_proxy(client, monkeypatch):
    mock_geoip = MagicMock(spec=GeoIPService)
    mock_geoip.available = True
    mock_geoip.lookup.return_value = GeoIPHit(
        city_name="Saint Petersburg",
        latitude=59.9343,
        longitude=30.3351,
    )
    monkeypatch.setattr(app.state, "geoip", mock_geoip)
    monkeypatch.setattr(app.state, "trusted_proxies", {"testclient"})

    response = client.get(
        "/api/geo/detect",
        headers={"X-Forwarded-For": "203.0.113.10, 10.0.0.1"},
    )
    assert response.status_code == 200
    mock_geoip.lookup.assert_called_once_with("203.0.113.10")
    assert response.json()["city_tag"] == "spb"
    assert response.json()["source"] == "geoip"


def test_detect_ignores_x_forwarded_for_from_untrusted_peer(client, monkeypatch):
    mock_geoip = MagicMock(spec=GeoIPService)
    mock_geoip.available = True
    mock_geoip.lookup.return_value = None
    monkeypatch.setattr(app.state, "geoip", mock_geoip)
    monkeypatch.setattr(app.state, "trusted_proxies", set())

    response = client.get(
        "/api/geo/detect",
        headers={"X-Forwarded-For": "203.0.113.10"},
    )
    assert response.status_code == 200
    called_ip = mock_geoip.lookup.call_args[0][0]
    assert called_ip != "203.0.113.10"


def test_reverse_moscow_coordinates(client, coordinates):
    point = coordinates["moscow"]
    response = client.get("/api/geo/reverse", params={"lat": point["lat"], "lon": point["lon"]})
    assert response.status_code == 200
    assert response.json() == {
        "city_tag": point["city_tag"],
        "city_name": point["city_name"],
        "source": "reverse",
    }


def test_reverse_spb_coordinates(client, coordinates):
    point = coordinates["spb"]
    response = client.get("/api/geo/reverse", params={"lat": point["lat"], "lon": point["lon"]})
    assert response.status_code == 200
    assert response.json() == {
        "city_tag": point["city_tag"],
        "city_name": point["city_name"],
        "source": "reverse",
    }


def test_reverse_invalid_coordinates_returns_400(client):
    response = client.get("/api/geo/reverse", params={"lat": 95, "lon": 0})
    assert response.status_code == 400
    payload = response.json()
    assert payload["error"] == "invalid_coordinates"
    assert "lat and lon" in payload["message"]


def test_reverse_response_has_no_pii(client, coordinates):
    point = coordinates["moscow"]
    response = client.get("/api/geo/reverse", params={"lat": point["lat"], "lon": point["lon"]})
    payload = response.json()
    assert set(payload.keys()) == {"city_tag", "city_name", "source"}


def test_geoip_resolve_city_tag_by_name(registry):
    hit = GeoIPHit(city_name="Moscow", latitude=None, longitude=None)
    assert resolve_city_tag(registry, hit) == "moscow"


def test_geoip_resolve_city_tag_by_coordinates(registry):
    hit = GeoIPHit(city_name=None, latitude=59.9343, longitude=30.3351)
    assert resolve_city_tag(registry, hit) == "spb"


def test_reverse_geocode_nearest_city(registry, coordinates):
    point = coordinates["between"]
    assert reverse_geocode(registry, point["lat"], point["lon"]) == point["nearest"]


def test_get_client_ip_trusted_proxy():
    request = MagicMock()
    request.client.host = "10.0.0.5"
    request.headers = {"X-Forwarded-For": "203.0.113.1, 10.0.0.5"}
    assert get_client_ip(request, {"10.0.0.5"}) == "203.0.113.1"


def test_get_client_ip_private_docker_peer_trusts_xff():
    request = MagicMock()
    request.client.host = "172.18.0.4"
    request.headers = {"X-Forwarded-For": "203.0.113.42"}
    assert get_client_ip(request, set()) == "203.0.113.42"


def test_geoip_service_unavailable_when_db_missing(monkeypatch):
    monkeypatch.setenv("GEOIP_DB_PATH", "/nonexistent/GeoLite2-City.mmdb")
    service = GeoIPService()
    try:
        assert service.available is False
        assert service.lookup("203.0.113.0") is None
    finally:
        service.close()
