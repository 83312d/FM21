# FM21 music buffer worker (U12) — extends Python glue base.
FROM python:3.12-slim-bookworm AS base

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY services/ /app/services/
COPY broadcast/liquidsoap/cities.yaml /broadcast/liquidsoap/cities.yaml

ENV CITIES_YAML_PATH=/broadcast/liquidsoap/cities.yaml
ENV STATIC_MUSIC_DIR=/data/music/static
ENV PLAYLIST_RULES_PATH=/app/services/music/playlist_rules.yaml

CMD ["python", "-m", "services.music.buffer_worker"]
