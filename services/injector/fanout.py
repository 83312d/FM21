"""Resolve target cities and build per-city queue items (Broadcast Semantics §5)."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

import yaml

PHASE1_TYPES = frozenset({"AD"})
PHASE2_TYPES = frozenset({"MUSIC", "MUSIC_ORDER"})
ENQUEUE_TYPES = PHASE1_TYPES | PHASE2_TYPES
TYPE_PRIORITIES = {
    "AD": 100,
    "NEWS_PAIR": 80,
    "MUSIC_ORDER": 50,
    "MUSIC": 10,
}


def load_active_cities(path: str | None = None) -> list[str]:
    yaml_path = Path(path or os.environ.get("CITIES_YAML_PATH", "broadcast/liquidsoap/cities.yaml"))
    with yaml_path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return [entry["tag"] for entry in data["cities"]]


def resolve_target_cities(city_tag: str, active_cities: list[str]) -> list[str]:
    if city_tag == "all":
        return list(active_cities)
    if city_tag in active_cities:
        return [city_tag]
    return []


def build_queue_item(
    *,
    item_type: str,
    uri: str,
    city_tag: str,
    meta: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "type": item_type,
        "priority": TYPE_PRIORITIES[item_type],
        "uri": uri,
        "city_tag": city_tag,
        "meta": meta,
    }


def prepare_enqueue(
    *,
    item_type: str,
    uri: str,
    city_tag: str,
    meta: dict[str, Any],
    active_cities: list[str],
) -> list[tuple[str, dict[str, Any]]]:
    targets = resolve_target_cities(city_tag, active_cities)
    if not targets:
        return []
    return [
        (
            target,
            build_queue_item(
                item_type=item_type,
                uri=uri,
                city_tag=target,
                meta=meta,
            ),
        )
        for target in targets
    ]
