"""Telegram inline keyboards for operator flows."""

from __future__ import annotations

import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from services.geo.cities import DISPLAY_NAMES
from services.injector.fanout import load_active_cities

CITIES_YAML_PATH = os.environ.get("CITIES_YAML_PATH", "broadcast/liquidsoap/cities.yaml")


def _display_city(tag: str) -> str:
    if tag == "all":
        return "Все города"
    return DISPLAY_NAMES.get(tag, tag)


def _ad_callback_data(city_tag: str, *, nonce: str | None = None) -> str:
    if nonce:
        return f"ad:{city_tag}:{nonce}"
    return f"ad:{city_tag}"


def build_city_keyboard(
    *,
    cities_yaml_path: str | None = None,
    nonce: str | None = None,
) -> InlineKeyboardMarkup:
    path = cities_yaml_path or CITIES_YAML_PATH
    rows = [
        [InlineKeyboardButton(_display_city(tag), callback_data=_ad_callback_data(tag, nonce=nonce))]
        for tag in load_active_cities(path)
    ]
    rows.append([InlineKeyboardButton("Все города", callback_data=_ad_callback_data("all", nonce=nonce))])
    return InlineKeyboardMarkup(rows)
