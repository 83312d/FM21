# FM21 Liquidsoap — broadcast engine (U4-A).
# Needs redis-cli for queue poll (fm21.liq) and curl for healthchecks.
FROM savonet/liquidsoap:v2.2.5

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        redis-tools \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /broadcast/liquidsoap

CMD ["liquidsoap", "/broadcast/liquidsoap/fm21.liq"]
