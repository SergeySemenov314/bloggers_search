"""Этап 3 — агент «Офферы».

Берёт отобранных блогеров (результат этапа 2) и бриф бренда → одним вызовом
Claude пишет по тёплому персональному сообщению о бартере на каждого. Apify
здесь не нужен — работаем только с уже собранными данными.
"""

import os

import anthropic

from prompts import OFFERS_SYSTEM, OFFERS_USER


def run(model: str, bloggers: str | None = None, brief: str | None = None):
    """Генератор событий трейса этапа 3."""
    if not bloggers or not bloggers.strip():
        yield {"type": "error", "message": "Нет отобранных блогеров — сначала "
               "запустите этап 2 «Поиск новых»."}
        return
    if not brief or not brief.strip():
        yield {"type": "error", "message": "Заполните бриф бренда (что предлагаем "
               "по бартеру)."}
        return

    yield {"type": "node", "name": "Генерация офферов (Claude)"}
    client = anthropic.Anthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY"), timeout=90.0, max_retries=1
    )
    user_prompt = OFFERS_USER.format(brief=brief.strip(), bloggers=bloggers.strip())
    try:
        with client.messages.stream(
            model=model,
            max_tokens=2500,
            system=OFFERS_SYSTEM,
            messages=[{"role": "user", "content": user_prompt}],
        ) as stream:
            msg = stream.get_final_message()
    except Exception as e:  # noqa: BLE001
        yield {"type": "error", "message": f"Ошибка Claude API: {e}"}
        return

    report = "".join(b.text for b in msg.content if b.type == "text")
    usage = {
        "input_tokens": msg.usage.input_tokens,
        "output_tokens": msg.usage.output_tokens,
        "cache_read": getattr(msg.usage, "cache_read_input_tokens", 0) or 0,
        "cache_creation": getattr(msg.usage, "cache_creation_input_tokens", 0) or 0,
    }
    yield {"type": "final", "report": report, "usage": usage}
