"""JSON structured logging helpers."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("service", "event", "city_tag", "status"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_json_logging(
    *,
    service: str,
    level: int = logging.INFO,
) -> None:
    """Attach a JSON stream handler to the root logger (idempotent)."""
    root = logging.getLogger()
    root.setLevel(level)
    if any(isinstance(handler, logging.StreamHandler) for handler in root.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    logging.getLogger(service).info(
        "logging configured",
        extra={"service": service, "event": "logging_configured"},
    )
