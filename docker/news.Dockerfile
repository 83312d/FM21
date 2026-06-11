# FM21 news RSS fetch worker (U16).
FROM python:3.12-slim-bookworm

WORKDIR /app

COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY services/ /app/services/

ENV NEWS_SOURCES_PATH=/app/services/news/sources.yaml
ENV NEWS_FETCH_INTERVAL_SEC=600

CMD ["python", "-m", "services.news.workers.fetch_cron"]
