"""Music buffer worker — maintain >= N MUSIC items per city (U12, R10)."""

from __future__ import annotations

import asyncio
import logging
import os
from services.db.session import async_session_factory
from services.injector.fanout import load_active_cities
from services.injector.queue import QueueClient
from services.music.config_service import PlaylistConfigService
from services.music.enqueue import MusicEnqueueFailure, enqueue_music
from services.music.provider import MusicProvider, ProviderUnavailable, TrackInfo, create_music_provider
from services.music.rules_loader import filter_tracks
from services.music.rules_schema import ResolvedCityRules
from services.music.static_provider import StaticProvider

logger = logging.getLogger(__name__)

BUFFER_TARGET = int(os.environ.get("MUSIC_BUFFER_TARGET", "10"))
POLL_INTERVAL_SEC = float(os.environ.get("MUSIC_BUFFER_POLL_INTERVAL_SEC", "15"))
DEFAULT_TRACK_DURATION_SEC = int(os.environ.get("DEFAULT_TRACK_DURATION_SEC", "180"))
STATIC_PLAYLIST_ID = "static"


class MusicBufferWorker:
    def __init__(
        self,
        *,
        queue: QueueClient,
        active_cities: list[str],
        session_factory=async_session_factory,
        buffer_target: int = BUFFER_TARGET,
    ) -> None:
        self._queue = queue
        self._active_cities = active_cities
        self._session_factory = session_factory
        self._buffer_target = buffer_target
        self._static: StaticProvider | None = None

    def _static_provider(self) -> StaticProvider:
        if self._static is None:
            music_dir = os.environ.get("STATIC_MUSIC_DIR", "data/music/static")
            self._static = StaticProvider(music_dir=music_dir)
        return self._static

    def _queued_track_ids(self, city_tag: str) -> set[str]:
        ids: set[str] = set()
        for item in self._queue.list_items(city_tag):
            if item.get("type") != "MUSIC":
                continue
            track_id = item.get("meta", {}).get("track_id")
            if track_id:
                ids.add(track_id)
        return ids

    def _buffer_track_ids(self, city_tag: str) -> set[str]:
        return set(self._queue.list_playlist_buffer(city_tag))

    def _collect_excluded_track_ids(self, city_tag: str) -> set[str]:
        # Recent MUSIC_ORDER plays plus tracks already waiting in the queue.
        excluded = self._buffer_track_ids(city_tag)
        excluded.update(self._queued_track_ids(city_tag))
        return excluded

    def _playlist_fingerprint(self, rules: ResolvedCityRules) -> str:
        return ",".join(rules.yandex_playlist_ids)

    def _sync_playlist_catalog(self, city_tag: str, rules: ResolvedCityRules) -> int:
        """Purge stale MUSIC filler when playlist policy changes."""
        fingerprint = self._playlist_fingerprint(rules)
        stored = self._queue.get_playlist_fingerprint(city_tag)
        if stored == fingerprint:
            return 0

        removed = 0
        if stored is not None or self._queue.count_pending_music(city_tag) > 0:
            removed = self._queue.remove_pending_items_by_type(city_tag, "MUSIC")
            self._queue.clear_playlist_buffer(city_tag)
            self._queue.set_catalog_cursor(city_tag, 0)
            if stored is not None:
                logger.info(
                    "Playlist changed for %s (%s -> %s); purged %s MUSIC items",
                    city_tag,
                    stored,
                    fingerprint,
                    removed,
                )
            elif removed:
                logger.info(
                    "Purged %s stale MUSIC items for %s during playlist sync",
                    removed,
                    city_tag,
                )

        self._queue.set_playlist_fingerprint(city_tag, fingerprint)
        return removed

    async def _load_catalog_tracks(
        self,
        provider: MusicProvider,
        rules: ResolvedCityRules,
    ) -> tuple[list[TrackInfo], MusicProvider]:
        tracks: list[TrackInfo] = []
        resolve_provider = provider
        playlist_ids = list(rules.yandex_playlist_ids)
        if isinstance(provider, StaticProvider):
            playlist_ids = [STATIC_PLAYLIST_ID]

        for playlist_id in playlist_ids:
            try:
                playlist_tracks = await provider.get_playlist_tracks(playlist_id)
            except ProviderUnavailable:
                logger.warning("Playlist %s unavailable for %s", playlist_id, rules.city_tag)
                continue
            tracks.extend(playlist_tracks)

        if not tracks:
            resolve_provider = self._static_provider()
            try:
                tracks = await resolve_provider.get_playlist_tracks(STATIC_PLAYLIST_ID)
            except ProviderUnavailable:
                return [], resolve_provider

        return filter_tracks(tracks, rules), resolve_provider

    def _track_duration(self, track: TrackInfo, rules: ResolvedCityRules) -> int:
        if track.duration_sec is not None and track.duration_sec > 0:
            return track.duration_sec
        return min(DEFAULT_TRACK_DURATION_SEC, rules.max_track_duration_sec)

    async def _resolve_track(
        self,
        provider: MusicProvider,
        track: TrackInfo,
    ) -> tuple[str, int] | None:
        try:
            stream = await provider.resolve_stream_url(track.track_id)
        except ProviderUnavailable:
            if isinstance(provider, StaticProvider):
                return None
            try:
                stream = await self._static_provider().resolve_stream_url(track.track_id)
            except ProviderUnavailable:
                return None
        duration = track.duration_sec or DEFAULT_TRACK_DURATION_SEC
        return stream.url, duration

    async def fill_city(self, city_tag: str) -> int:
        """Enqueue MUSIC items until queue has buffer_target pending MUSIC. Returns count added."""
        deficit = self._buffer_target - self._queue.count_pending_music(city_tag)
        if deficit <= 0:
            return 0

        async with self._session_factory()() as session:
            config = PlaylistConfigService(session)
            rules = await config.get_city_rules(city_tag)
            self._sync_playlist_catalog(city_tag, rules)
            provider = await create_music_provider(session)
            excluded = self._collect_excluded_track_ids(city_tag)
            catalog, resolve_provider = await self._load_catalog_tracks(provider, rules)

            if not catalog:
                logger.warning("No tracks available for city %s", city_tag)
                return 0

            added = 0
            catalog_index = self._queue.get_catalog_cursor(city_tag)
            attempts = 0
            max_attempts = max(deficit * len(catalog), len(catalog))

            while added < deficit and catalog and attempts < max_attempts:
                track = catalog[catalog_index % len(catalog)]
                catalog_index += 1
                attempts += 1
                if track.track_id in excluded:
                    continue

                resolved = await self._resolve_track(resolve_provider, track)
                if resolved is None:
                    continue

                uri, _resolved_duration = resolved
                result = await enqueue_music(
                    uri=uri,
                    city_tag=city_tag,
                    title=track.title,
                    artist=track.artist,
                    duration_sec=self._track_duration(track, rules),
                    track_id=track.track_id,
                )
                if isinstance(result, MusicEnqueueFailure):
                    logger.error(
                        "Enqueue failed for %s track %s: %s",
                        city_tag,
                        track.track_id,
                        result.message,
                    )
                    continue

                excluded.add(track.track_id)
                added += 1

            self._queue.set_catalog_cursor(city_tag, catalog_index % len(catalog))
            return added

    async def run_once(self) -> dict[str, int]:
        results: dict[str, int] = {}
        for city_tag in self._active_cities:
            results[city_tag] = await self.fill_city(city_tag)
        return results

    async def run_forever(self) -> None:
        logger.info(
            "Music buffer worker started (target=%s, cities=%s)",
            self._buffer_target,
            self._active_cities,
        )
        while True:
            try:
                results = await self.run_once()
                for city_tag, count in results.items():
                    if count:
                        logger.info("Enqueued %s MUSIC items for %s", count, city_tag)
            except Exception:
                logger.exception("Music buffer worker tick failed")
            await asyncio.sleep(POLL_INTERVAL_SEC)


def create_worker() -> MusicBufferWorker:
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    max_pending_ads = int(os.environ.get("MAX_PENDING_ADS_PER_CITY", "5"))
    cities_path = os.environ.get("CITIES_YAML_PATH", "broadcast/liquidsoap/cities.yaml")
    return MusicBufferWorker(
        queue=QueueClient(redis_url, max_pending_ads),
        active_cities=load_active_cities(cities_path),
    )


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    worker = create_worker()
    await worker.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
