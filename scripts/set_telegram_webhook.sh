#!/usr/bin/env bash
# Register Telegram webhook via Bot API (U30).
#
# Telegram requires HTTPS for setWebhook — HTTP localhost will be rejected.
# For local pet-project use BOT_MODE=polling instead (see deploy/production/env.template).
#
# When you add ngrok or a real domain:
#   TELEGRAM_WEBHOOK_URL=https://abc123.ngrok-free.app  # no path suffix
#   TELEGRAM_WEBHOOK_SECRET=your-secret
#   TELEGRAM_BOT_TOKEN=...
#   bash scripts/set_telegram_webhook.sh
#
# Verify: curl "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getWebhookInfo"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ -f "${REPO_ROOT}/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "${REPO_ROOT}/.env"
  set +a
fi

if [[ -z "${TELEGRAM_WEBHOOK_URL:-}" ]]; then
  echo "TELEGRAM_WEBHOOK_URL is not set." >&2
  echo "" >&2
  echo "Telegram webhooks require a public HTTPS URL (Telegram rejects plain HTTP)." >&2
  echo "For local-only pet project deploy, use BOT_MODE=polling — no webhook needed." >&2
  echo "" >&2
  echo "When ready for webhook mode:" >&2
  echo "  1. Expose gateway with HTTPS (ngrok, Caddy, or cloud load balancer)." >&2
  echo "  2. Set TELEGRAM_WEBHOOK_URL=https://your-host.example.com  (no /api/bot/webhook suffix)" >&2
  echo "  3. Set BOT_MODE=webhook and restart the bot service." >&2
  echo "  4. Re-run this script." >&2
  exit 1
fi

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
  echo "TELEGRAM_BOT_TOKEN is required." >&2
  exit 1
fi

webhook_url="${TELEGRAM_WEBHOOK_URL%/}/api/bot/webhook"

if [[ "${webhook_url}" != https://* ]]; then
  echo "TELEGRAM_WEBHOOK_URL must use HTTPS (got: ${TELEGRAM_WEBHOOK_URL})." >&2
  echo "Telegram Bot API rejects HTTP webhook endpoints." >&2
  exit 1
fi

payload="$(WEBHOOK_URL="${webhook_url}" TELEGRAM_WEBHOOK_SECRET="${TELEGRAM_WEBHOOK_SECRET:-}" python3 -c '
import json, os
body = {
    "url": os.environ["WEBHOOK_URL"],
    "allowed_updates": ["message", "callback_query"],
}
secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
if secret:
    body["secret_token"] = secret
print(json.dumps(body))
')"

echo "Setting Telegram webhook to ${webhook_url} ..."
response="$(curl -sf -X POST \
  "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
  -H "Content-Type: application/json" \
  -d "${payload}")"

if echo "${response}" | grep -q '"ok":true'; then
  echo "Webhook registered successfully."
  echo "Verify with: curl https://api.telegram.org/bot\${TELEGRAM_BOT_TOKEN}/getWebhookInfo"
else
  echo "setWebhook failed: ${response}" >&2
  exit 1
fi
