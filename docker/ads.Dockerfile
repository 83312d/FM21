# FM21 ads service (U24) — transcode, DB, injector enqueue.
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

COPY services/ads/ /app/services/ads/
COPY services/common/ /app/services/common/
COPY services/db/ /app/services/db/
COPY services/injector/ /app/services/injector/
COPY services/news/ /app/services/news/
COPY broadcast/liquidsoap/cities.yaml /broadcast/liquidsoap/cities.yaml

ENV CITIES_YAML_PATH=/broadcast/liquidsoap/cities.yaml
ENV ADS_DIR=/data/ads
ENV INJECTOR_URL=http://injector:8080

EXPOSE 8080

CMD ["uvicorn", "services.ads.main:app", "--host", "0.0.0.0", "--port", "8080"]
