# FM21 Liquidsoap — production image with baked broadcast tree.
FROM savonet/liquidsoap:v2.2.5

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        redis-tools \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY broadcast/ /broadcast/

WORKDIR /broadcast/liquidsoap

CMD ["liquidsoap", "/broadcast/liquidsoap/fm21.liq"]
