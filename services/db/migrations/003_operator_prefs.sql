-- U25: operator default city persistence across bot restarts.

CREATE TABLE IF NOT EXISTS operator_prefs (
    telegram_user_id BIGINT PRIMARY KEY,
    default_city_tag VARCHAR(64) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
