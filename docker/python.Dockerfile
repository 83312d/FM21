# FM21 Python 3.12 base — glue services (U5–U8) and test runners (U4-A).
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

COPY services ./services

FROM base AS test
CMD ["pytest", "tests/"]

FROM base AS e2e
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        nodejs \
        npm \
        chromium \
        fonts-liberation \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY package.json vitest.config.ts ./
COPY tests/e2e ./tests/e2e
RUN npm install
# Chrome for Testing has no Linux ARM64 build; use system Chromium there.
ENV AGENT_BROWSER_EXECUTABLE_PATH=/usr/bin/chromium
RUN if [ "$(dpkg --print-architecture)" = "amd64" ]; then npx agent-browser install --with-deps; fi
CMD ["npm", "run", "test:e2e"]
