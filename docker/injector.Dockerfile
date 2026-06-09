# FM21 queue injector (U5) — extends Python glue base.
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

COPY services/injector/ /app/services/injector/
COPY broadcast/liquidsoap/cities.yaml /broadcast/liquidsoap/cities.yaml

ENV CITIES_YAML_PATH=/broadcast/liquidsoap/cities.yaml

EXPOSE 8080

CMD ["uvicorn", "services.injector.main:app", "--host", "0.0.0.0", "--port", "8080"]
