"""FM21 geo API — city detection for the web player."""

from __future__ import annotations

import ipaddress
import logging
import os
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from services.geo.cities import CityRegistry, load_registry
from services.geo.geoip import GeoIPService, resolve_city_tag
from services.geo.reverse import CoordinateValidationError, reverse_geocode

logger = logging.getLogger(__name__)

GeoSource = Literal["geoip", "reverse", "default"]


class GeoCityResponse(BaseModel):
    city_tag: str
    city_name: str
    source: GeoSource


class ErrorResponse(BaseModel):
    error: str
    message: str | None = None


def _parse_trusted_proxies(raw: str | None) -> set[str]:
    if not raw:
        return {"127.0.0.1", "::1"}
    return {item.strip() for item in raw.split(",") if item.strip()}


def _trusts_forwarded_headers(peer: str, trusted_proxies: set[str]) -> bool:
    if peer in trusted_proxies:
        return True
    try:
        return ipaddress.ip_address(peer).is_private
    except ValueError:
        return False


def get_client_ip(request: Request, trusted_proxies: set[str]) -> str:
    peer = request.client.host if request.client else "127.0.0.1"
    if _trusts_forwarded_headers(peer, trusted_proxies):
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return peer


def build_response(registry: CityRegistry, tag: str, source: GeoSource) -> GeoCityResponse:
    city = registry.get(tag)
    if city is None:
        city = registry.default_city()
        source = "default"
    return GeoCityResponse(
        city_tag=city.tag,
        city_name=city.display_name,
        source=source,
    )


def default_response(registry: CityRegistry) -> GeoCityResponse:
    city = registry.default_city()
    return GeoCityResponse(
        city_tag=city.tag,
        city_name=city.display_name,
        source="default",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    registry = load_registry()
    geoip = GeoIPService()
    trusted_proxies = _parse_trusted_proxies(os.environ.get("TRUSTED_PROXY_IPS"))
    app.state.registry = registry
    app.state.geoip = geoip
    app.state.trusted_proxies = trusted_proxies
    yield
    geoip.close()


app = FastAPI(title="FM21 Geo API", version="0.1.0", lifespan=lifespan)


@app.get("/api/geo/detect", response_model=GeoCityResponse)
def geo_detect(request: Request) -> GeoCityResponse:
    registry: CityRegistry = app.state.registry
    geoip: GeoIPService = app.state.geoip
    trusted_proxies: set[str] = app.state.trusted_proxies

    if not geoip.available:
        response = default_response(registry)
        logger.info("geo detect fallback city_tag=%s source=%s", response.city_tag, response.source)
        return response

    client_ip = get_client_ip(request, trusted_proxies)
    hit = geoip.lookup(client_ip)
    tag = resolve_city_tag(registry, hit)
    if tag is None:
        response = default_response(registry)
        logger.info("geo detect fallback city_tag=%s source=%s", response.city_tag, response.source)
        return response

    response = build_response(registry, tag, "geoip")
    logger.info("geo detect city_tag=%s source=%s", response.city_tag, response.source)
    return response


@app.get("/api/geo/reverse", response_model=GeoCityResponse)
def geo_reverse(
    lat: float = Query(...),
    lon: float = Query(...),
) -> GeoCityResponse:
    registry: CityRegistry = app.state.registry
    try:
        tag = reverse_geocode(registry, lat, lon)
    except CoordinateValidationError as exc:
        return JSONResponse(
            status_code=400,
            content={
                "error": "invalid_coordinates",
                "message": exc.message,
            },
        )

    if tag is None:
        response = default_response(registry)
        logger.info("geo reverse fallback city_tag=%s source=%s", response.city_tag, response.source)
        return response

    response = build_response(registry, tag, "reverse")
    logger.info("geo reverse city_tag=%s source=%s", response.city_tag, response.source)
    return response
