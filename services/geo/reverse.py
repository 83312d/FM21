"""Nearest-city reverse geocoding (no external provider)."""

from __future__ import annotations

from dataclasses import dataclass

from services.geo.cities import CityRegistry


@dataclass(frozen=True)
class CoordinateValidationError(Exception):
    message: str = "lat and lon must be valid WGS-84 decimal degrees"


def validate_coordinates(lat: float, lon: float) -> None:
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise CoordinateValidationError()


def reverse_geocode(registry: CityRegistry, lat: float, lon: float) -> str | None:
    validate_coordinates(lat, lon)
    return registry.nearest_tag(lat, lon)
