#!/bin/sh
set -e

# Ensure log directory exists (Debian icecast2 package expects it).
mkdir -p /var/log/icecast2

# icecast2 changeowner requires this account (package may not create it in slim images).
if ! id icecast >/dev/null 2>&1; then
  useradd -r -g icecast -d /var/log/icecast2 -s /usr/sbin/nologin icecast
fi
chown -R icecast:icecast /var/log/icecast2

# Apply ICECAST_SOURCE_PASSWORD to mounted config (Liquidsoap reads the same env).
ICECAST_SOURCE_PASSWORD="${ICECAST_SOURCE_PASSWORD:-fm21dev}"
export ICECAST_SOURCE_PASSWORD
CONFIG=/etc/icecast2/icecast.xml
envsubst '${ICECAST_SOURCE_PASSWORD}' < "$CONFIG" > /tmp/icecast.xml
CONFIG=/tmp/icecast.xml

exec icecast2 -c "$CONFIG"
