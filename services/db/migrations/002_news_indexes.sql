-- U15: indexes for news pipeline queries (status, play_count, content_hash).

CREATE INDEX IF NOT EXISTS idx_news_items_status ON news_items (status);

CREATE INDEX IF NOT EXISTS idx_news_items_play_count ON news_items (play_count);

CREATE INDEX IF NOT EXISTS idx_news_items_status_play_count ON news_items (status, play_count);

CREATE INDEX IF NOT EXISTS idx_news_items_content_hash ON news_items (content_hash)
    WHERE content_hash IS NOT NULL;
