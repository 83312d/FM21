# FM21 news workers (U16+).
FROM python:3.12-slim-bookworm

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY services/ /app/services/

ENV NEWS_SOURCES_PATH=/app/services/news/sources.yaml
ENV NEWS_FETCH_INTERVAL_SEC=600
ENV FM21_CERTS_DIR=/certs

CMD ["python", "-m", "services.news.workers.fetch_cron"]
