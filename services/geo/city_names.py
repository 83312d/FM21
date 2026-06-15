"""Localized display names from cities.yaml (U29)."""

from __future__ import annotations

from pathlib import Path

from services.geo.cities import load_registry, resolve_cities_path


def display_name(tag: str, *, cities_path: Path | None = None) -> str:
    """Return badge label for city_tag; falls back to tag when unknown."""
    if tag == "all":
        return "Все города"
    registry = load_registry(cities_path=cities_path or resolve_cities_path())
    city = registry.get(tag)
    if city is None:
        return tag
    return city.display_name


def display_names_map(*, cities_path: Path | None = None) -> dict[str, str]:
    """Map city_tag → display_name for all active cities."""
    registry = load_registry(cities_path=cities_path or resolve_cities_path())
    return {tag: city.display_name for tag, city in registry.cities.items()}
