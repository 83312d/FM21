"""Canonical city list from broadcast/liquidsoap/cities.yaml."""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


def _normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


@dataclass(frozen=True)
class City:
    tag: str
    name: str
    display_name: str = ""
    lat: float | None = None
    lon: float | None = None
    aliases: tuple[str, ...] = field(default_factory=tuple)


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
            if normalized in {_normalize_name(alias) for alias in city.aliases}:
                return city.tag
            if normalized == _normalize_name(city.tag):
                return city.tag
        return None

    def nearest_tag(self, lat: float, lon: float) -> str | None:
        best_tag: str | None = None
        best_distance = float("inf")
        for tag, city in self.cities.items():
            if city.lat is None or city.lon is None:
                continue
            distance = _haversine_km(lat, lon, city.lat, city.lon)
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


def _parse_city_entry(entry: dict) -> City:
    aliases = entry.get("aliases") or []
    return City(
        tag=entry["tag"],
        name=entry["name"],
        display_name=entry.get("display_name") or entry["name"],
        lat=entry.get("lat"),
        lon=entry.get("lon"),
        aliases=tuple(str(alias) for alias in aliases),
    )


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
        city = _parse_city_entry(entry)
        cities[city.tag] = city
    if default not in cities:
        raise ValueError(f"DEFAULT_CITY_TAG {default!r} is not listed in {path}")
    return CityRegistry(cities=cities, default_tag=default)


def display_names_map(*, cities_path: Path | None = None) -> dict[str, str]:
    registry = load_registry(cities_path=cities_path)
    return {tag: (city.display_name or city.name) for tag, city in registry.cities.items()}


# Back-compat for bot handlers — populated from cities.yaml at import.
DISPLAY_NAMES: dict[str, str] = display_names_map()
