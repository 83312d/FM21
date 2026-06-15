# FM21 Icecast — production image with baked config (no source bind mounts).
FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        icecast2 \
        curl \
        ca-certificates \
        gettext-base \
    && rm -rf /var/lib/apt/lists/*

COPY docker/icecast-entrypoint.sh /usr/local/bin/icecast-entrypoint.sh
RUN chmod +x /usr/local/bin/icecast-entrypoint.sh
COPY broadcast/icecast/icecast.xml /etc/icecast2/icecast.xml

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
    CMD curl -sf http://localhost:8000/status-json.xsl > /dev/null || exit 1

ENTRYPOINT ["/usr/local/bin/icecast-entrypoint.sh"]
