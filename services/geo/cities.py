"""Canonical city list from broadcast/liquidsoap/cities.yaml."""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

# WGS-84 centroids for Phase 1 reverse geocoding (nearest-city).
CITY_LOCATIONS: dict[str, tuple[float, float]] = {
    "moscow": (55.7558, 37.6173),
    "spb": (59.9343, 30.3351),
}

# Badge display names (Listener Contract §3, OpenAPI GeoCityResponse examples).
DISPLAY_NAMES: dict[str, str] = {
    "moscow": "Москва",
    "spb": "Санкт-Петербург",
}

# GeoIP / reverse lookup aliases → city_tag.
NAME_ALIASES: dict[str, tuple[str, ...]] = {
    "moscow": ("moscow", "москва"),
    "spb": (
        "saint petersburg",
        "st petersburg",
        "st. petersburg",
        "sankt-peterburg",
        "sankt peterburg",
        "санкт-петербург",
        "spb",
    ),
}


def _normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


@dataclass(frozen=True)
class City:
    tag: str
    name: str

    @property
    def display_name(self) -> str:
        return DISPLAY_NAMES.get(self.tag, self.name)


@dataclass
class CityRegistry:
    cities: dict[str, City]
    default_tag: str

    def get(self, tag: str) -> City | None:
        return self.cities.get(tag)

    def default_city(self) -> City:
        city = self.cities.get(self.default_tag)
        if city is None:
            raise ValueError(f"DEFAULT_CITY_TAG {self.default_tag!r} is not active")
        return city

    def match_name(self, raw_name: str | None) -> str | None:
        if not raw_name:
            return None
        normalized = _normalize_name(raw_name)
        for city in self.cities.values():
            if _normalize_name(city.name) == normalized:
                return city.tag
            if _normalize_name(city.display_name) == normalized:
                return city.tag
        for tag, aliases in NAME_ALIASES.items():
            if tag not in self.cities:
                continue
            if normalized in {_normalize_name(alias) for alias in aliases}:
                return tag
        return None

    def nearest_tag(self, lat: float, lon: float) -> str | None:
        best_tag: str | None = None
        best_distance = float("inf")
        for tag in self.cities:
            location = CITY_LOCATIONS.get(tag)
            if location is None:
                continue
            distance = _haversine_km(lat, lon, location[0], location[1])
            if distance < best_distance:
                best_distance = distance
                best_tag = tag
        return best_tag


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def resolve_cities_path() -> Path:
    env_path = os.environ.get("CITIES_YAML_PATH")
    if env_path:
        return Path(env_path)
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / "broadcast" / "liquidsoap" / "cities.yaml"


def load_registry(
    *,
    cities_path: Path | None = None,
    default_tag: str | None = None,
) -> CityRegistry:
    path = cities_path or resolve_cities_path()
    default = default_tag or os.environ.get("DEFAULT_CITY_TAG", "moscow")
    with path.open(encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    cities: dict[str, City] = {}
    for entry in payload.get("cities", []):
        tag = entry["tag"]
        cities[tag] = City(tag=tag, name=entry["name"])
    if default not in cities:
        raise ValueError(f"DEFAULT_CITY_TAG {default!r} is not listed in {path}")
    return CityRegistry(cities=cities, default_tag=default)
