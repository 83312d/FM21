"""MaxMind GeoLite2 City lookups."""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from pathlib import Path

import geoip2.database
from geoip2.errors import AddressNotFoundError

from services.geo.cities import CityRegistry


@dataclass(frozen=True)
class GeoIPHit:
    city_name: str | None
    latitude: float | None
    longitude: float | None


class GeoIPService:
    def __init__(self, db_path: str | Path | None = None) -> None:
        path = Path(db_path or os.environ.get("GEOIP_DB_PATH", "/data/GeoLite2-City.mmdb"))
        self._reader: geoip2.database.Reader | None = None
        if path.is_file():
            self._reader = geoip2.database.Reader(str(path))

    @property
    def available(self) -> bool:
        return self._reader is not None

    def close(self) -> None:
        if self._reader is not None:
            self._reader.close()
            self._reader = None

    def lookup(self, ip: str) -> GeoIPHit | None:
        if self._reader is None:
            return None
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            return None
        try:
            response = self._reader.city(ip)
        except AddressNotFoundError:
            return None
        return GeoIPHit(
            city_name=response.city.name,
            latitude=response.location.latitude,
            longitude=response.location.longitude,
        )


def resolve_city_tag(registry: CityRegistry, hit: GeoIPHit | None) -> str | None:
    if hit is None:
        return None
    tag = registry.match_name(hit.city_name)
    if tag is not None:
        return tag
    if hit.latitude is not None and hit.longitude is not None:
        return registry.nearest_tag(hit.latitude, hit.longitude)
    return None
