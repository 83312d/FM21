"""Multi-city operations from cities.yaml (U29)."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from services.bot.keyboards import build_city_keyboard
from services.geo.cities import load_registry
from services.geo.main import app as geo_app
from services.injector.fanout import load_active_cities

REPO_ROOT = Path(__file__).resolve().parents[1]
CITIES_YAML = REPO_ROOT / "broadcast" / "liquidsoap" / "cities.yaml"
ICECAST_XML = REPO_ROOT / "broadcast" / "icecast" / "icecast.xml"
NGINX_GATEWAY_CONF = REPO_ROOT / "docker" / "nginx-gateway.conf"
DEPLOY_README = REPO_ROOT / "deploy" / "README.md"

EKB_LAT = 56.8389
EKB_LON = 60.6057


@pytest.fixture
def active_cities() -> list[str]:
    return load_active_cities(str(CITIES_YAML))


@pytest.fixture
def registry():
    return load_registry(cities_path=CITIES_YAML, default_tag="moscow")


def test_cities_yaml_lists_three_active_cities(active_cities: list[str]) -> None:
    assert active_cities == ["moscow", "spb", "ekb"]


def test_registry_loads_ekb_display_name_and_location(registry) -> None:
    ekb = registry.get("ekb")
    assert ekb is not None
    assert ekb.display_name == "Екатеринбург"
    assert registry.nearest_tag(EKB_LAT, EKB_LON) == "ekb"


def test_reverse_geocode_ekb_coordinates(registry) -> None:
    from services.geo.reverse import reverse_geocode

    assert reverse_geocode(registry, EKB_LAT, EKB_LON) == "ekb"


def test_geo_detect_resolves_ekb_name(registry, monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import MagicMock

    from services.geo.geoip import GeoIPHit, GeoIPService

    monkeypatch.setenv("CITIES_YAML_PATH", str(CITIES_YAML))
    monkeypatch.setenv("DEFAULT_CITY_TAG", "moscow")
    monkeypatch.setenv("GEOIP_DB_PATH", "/nonexistent/GeoLite2-City.mmdb")

    mock_geoip = MagicMock(spec=GeoIPService)
    mock_geoip.available = True
    mock_geoip.lookup.return_value = GeoIPHit(
        city_name="Yekaterinburg",
        latitude=EKB_LAT,
        longitude=EKB_LON,
    )

    with TestClient(geo_app) as client:
        geo_app.state.geoip = mock_geoip
        response = client.get("/api/geo/detect")
    assert response.status_code == 200
    payload = response.json()
    assert payload["city_tag"] == "ekb"
    assert payload["city_name"] == "Екатеринбург"
    assert payload["source"] == "geoip"


def test_ekb_ad_enqueue_isolated_from_moscow(
    injector_client, auth_headers, ad_payload, queue_client, active_cities: list[str]
) -> None:
    payload = {**ad_payload, "city_tag": "ekb", "uri": "file:///data/ads/ekb-only.mp3"}
    response = injector_client.post("/internal/enqueue", json=payload, headers=auth_headers)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["city_tags"] == ["ekb"]

    ekb_items = queue_client.list_items("ekb")
    moscow_items = queue_client.list_items("moscow")
    spb_items = queue_client.list_items("spb")
    assert len(ekb_items) == 1
    assert len(moscow_items) == 0
    assert len(spb_items) == 0
    assert ekb_items[0]["city_tag"] == "ekb"


def test_all_fanout_includes_three_cities(
    injector_client, auth_headers, ad_payload, queue_client, active_cities: list[str]
) -> None:
    payload = {**ad_payload, "city_tag": "all"}
    response = injector_client.post("/internal/enqueue", json=payload, headers=auth_headers)
    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body["city_tags"]) == set(active_cities)
    assert len(body["ids"]) == 3
    for city in active_cities:
        items = queue_client.list_items(city)
        assert len(items) == 1
        assert items[0]["city_tag"] == city


def test_bot_keyboard_includes_ekb(active_cities: list[str]) -> None:
    markup = build_city_keyboard(cities_yaml_path=str(CITIES_YAML))
    callback_tags = [
        button.callback_data.split(":", 1)[1]
        for row in markup.inline_keyboard
        for button in row
    ]
    assert callback_tags == [*active_cities, "all"]


@pytest.mark.parametrize("city", ["moscow", "spb", "ekb"])
def test_nginx_gateway_has_static_mount_location(city: str) -> None:
    conf = NGINX_GATEWAY_CONF.read_text(encoding="utf-8")
    pattern = rf"location\s*=\s*/{re.escape(city)}\s*\{{"
    match = re.search(pattern, conf)
    assert match, f"missing static location = /{city} in nginx gateway config"
    block_start = match.start()
    block = conf[block_start : conf.find("}", block_start) + 1]
    assert f"proxy_pass http://icecast:8000/{city};" in block
    assert "$request_uri" not in block


@pytest.mark.parametrize("city", ["moscow", "spb", "ekb"])
def test_icecast_declares_mount(city: str) -> None:
    xml = ICECAST_XML.read_text(encoding="utf-8")
    assert f"<mount-name>/{city}</mount-name>" in xml


def test_deploy_readme_documents_adding_a_city() -> None:
    assert DEPLOY_README.is_file(), "deploy/README.md must document adding a city"
    text = DEPLOY_README.read_text(encoding="utf-8").casefold()
    assert "adding a city" in text or "добав" in text
    for needle in ("cities.yaml", "icecast", "nginx"):
        assert needle in text
