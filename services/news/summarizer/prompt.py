"""Prompt templates for IT news radio summarization (U17, ADR-009)."""

from __future__ import annotations

from gigachat.models import Chat, Messages, MessagesRole

SYSTEM_PROMPT = (
    "Ты — редактор IT-радио. Пиши связный текст для озвучки в эфире: "
    "деловой IT-тон, без маркированных списков и нумерации. "
    "Итоговый текст должен быть на русском языке, строго 150–250 слов. "
    "Не добавляй заголовки, подписи и метаданные — только текст для чтения ведущим."
)

RETRY_USER_APPENDIX = (
    "Предыдущий ответ не подошёл по длине. "
    "Перепиши текст строго в диапазоне 150–250 русских слов. "
    "Сохрани связность и IT-тон, без списков."
)


def build_user_message(source_text: str, *, tightened: bool = False) -> str:
    """Build the user turn from article source text."""
    body = source_text.strip()
    prefix = "Подготовь радиосводку по следующей IT-новости:\n\n"
    message = f"{prefix}{body}"
    if tightened:
        message = f"{message}\n\n{RETRY_USER_APPENDIX}"
    return message


def build_chat(source_text: str, *, tightened: bool = False) -> Chat:
    """GigaChat request payload for one summarization attempt."""
    return Chat(
        messages=[
            Messages(role=MessagesRole.SYSTEM, content=SYSTEM_PROMPT),
            Messages(
                role=MessagesRole.USER,
                content=build_user_message(source_text, tightened=tightened),
            ),
        ],
    )
