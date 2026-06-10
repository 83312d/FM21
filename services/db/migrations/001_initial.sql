-- U9: TZ §8.1 persistence tables + news workflow columns.

DO $$ BEGIN CREATE TYPE news_item_status AS ENUM ('fetched', 'summarized', 'voiced', 'ready', 'failed'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN CREATE TYPE ad_status AS ENUM ('pending', 'queued', 'played', 'rejected'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS news_items (
    id BIGSERIAL PRIMARY KEY,
    source_url TEXT NOT NULL UNIQUE,
    summary_ru TEXT,
    audio_url TEXT,
    play_count INTEGER NOT NULL DEFAULT 0,
    last_played_at TIMESTAMPTZ,
    status news_item_status NOT NULL DEFAULT 'fetched',
    content_hash TEXT UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ads (
    id BIGSERIAL PRIMARY KEY,
    telegram_user_id BIGINT NOT NULL,
    city_tag VARCHAR(64) NOT NULL,
    audio_url TEXT NOT NULL,
    status ad_status NOT NULL DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS tracks_cache (
    yandex_track_id VARCHAR(128) PRIMARY KEY,
    title TEXT NOT NULL,
    artist TEXT NOT NULL,
    stream_url TEXT NOT NULL,
    stream_url_expires TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS playlist_config (
    city_tag VARCHAR(64) PRIMARY KEY,
    rules_json JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS broadcast_log (
    id BIGSERIAL PRIMARY KEY,
    city_tag VARCHAR(64) NOT NULL,
    item_type VARCHAR(32) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ
);
