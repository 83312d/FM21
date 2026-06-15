"""SQLAlchemy ORM models for TZ §8.1 tables."""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _enum_values(enum_cls: type[enum.Enum]) -> list[str]:
    return [member.value for member in enum_cls]


class NewsItemStatus(str, enum.Enum):
    FETCHED = "fetched"
    SUMMARIZED = "summarized"
    VOICED = "voiced"
    READY = "ready"
    FAILED = "failed"


class AdStatus(str, enum.Enum):
    PENDING = "pending"
    QUEUED = "queued"
    PLAYED = "played"
    REJECTED = "rejected"


class NewsItem(Base):
    __tablename__ = "news_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    summary_ru: Mapped[str | None] = mapped_column(Text)
    audio_url: Mapped[str | None] = mapped_column(Text)
    play_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_played_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[NewsItemStatus] = mapped_column(
        Enum(
            NewsItemStatus,
            name="news_item_status",
            create_constraint=False,
            values_callable=_enum_values,
        ),
        nullable=False,
        server_default=NewsItemStatus.FETCHED.value,
    )
    content_hash: Mapped[str | None] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Ad(Base):
    __tablename__ = "ads"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    city_tag: Mapped[str] = mapped_column(String(64), nullable=False)
    audio_url: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[AdStatus] = mapped_column(
        Enum(
            AdStatus,
            name="ad_status",
            create_constraint=False,
            values_callable=_enum_values,
        ),
        nullable=False,
        server_default=AdStatus.PENDING.value,
    )


class TrackCache(Base):
    __tablename__ = "tracks_cache"

    yandex_track_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    artist: Mapped[str] = mapped_column(Text, nullable=False)
    stream_url: Mapped[str] = mapped_column(Text, nullable=False)
    stream_url_expires: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PlaylistConfig(Base):
    __tablename__ = "playlist_config"

    city_tag: Mapped[str] = mapped_column(String(64), primary_key=True)
    rules_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class BroadcastLog(Base):
    __tablename__ = "broadcast_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    city_tag: Mapped[str] = mapped_column(String(64), nullable=False)
    item_type: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OperatorPrefs(Base):
    __tablename__ = "operator_prefs"

    telegram_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    default_city_tag: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
