#!/bin/sh
# Priority dequeue wrapper — invoked from fm21.liq at each block boundary.
set -eu

CITY_TAG="${1:?city tag required}"
REDIS_HOST="${2:-redis}"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
QUEUE_KEY="fm21:queue:${CITY_TAG}"

redis-cli -h "${REDIS_HOST}" --raw --eval "${SCRIPT_DIR}/dequeue.lua" "${QUEUE_KEY}"
