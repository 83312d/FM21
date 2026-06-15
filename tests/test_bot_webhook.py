"""Bot webhook security tests."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from services.bot import main as bot_main
from services.bot import webhook as bot_webhook


def test_webhook_secret_required_without_open_access(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bot_webhook, "TELEGRAM_WEBHOOK_SECRET", "")
    monkeypatch.setattr(bot_webhook, "BOT_OPEN_ACCESS", False)

    with pytest.raises(HTTPException) as exc:
        bot_webhook.validate_webhook_secret(None)

    assert exc.value.status_code == 503


def test_webhook_secret_skipped_in_dev_open_access(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bot_webhook, "TELEGRAM_WEBHOOK_SECRET", "")
    monkeypatch.setattr(bot_webhook, "BOT_OPEN_ACCESS", True)

    bot_webhook.validate_webhook_secret(None)


def test_use_polling_when_bot_mode_polling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bot_main, "BOT_MODE", "polling")
    assert bot_main.use_polling() is True

    monkeypatch.setattr(bot_main, "BOT_MODE", "webhook")
    assert bot_main.use_polling() is False


def test_webhook_secret_rejects_wrong_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bot_webhook, "TELEGRAM_WEBHOOK_SECRET", "expected-secret")
    monkeypatch.setattr(bot_webhook, "BOT_OPEN_ACCESS", False)

    with pytest.raises(HTTPException) as exc:
        bot_webhook.validate_webhook_secret("wrong")

    assert exc.value.status_code == 403
