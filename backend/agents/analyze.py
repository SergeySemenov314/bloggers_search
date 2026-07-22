"""Этап 1 — агент «Анализ базы».

Подключается к таблице → собирает профили → одним вызовом Claude синтезирует
«портрет идеального блогера». Источник данных: Apify (если задан APIFY_TOKEN,
надёжнее и с вовлечённостью) либо анонимный instaloader как запасной. По ходу
yield-ит события трейса, которые эндпоинт транслирует во фронтенд по SSE.
"""

import os
import time

import anthropic

from prompts import ANALYZE_SYSTEM, ANALYZE_USER
from services.sheet import fetch_handles
from services.instagram import fetch_profile, LOGGED_IN
from services import apify

# Пауза между обращениями к Instagram (instaloader-путь) — снижает риск лимита.
FETCH_DELAY_SEC = 1.5


def _format_profiles(profiles: list) -> str:
    """Собирает читаемый блок из успешно прочитанных профилей для промпта."""
    blocks = []
    for p in profiles:
        lines = [f"@{p.username}  (https://www.instagram.com/{p.username}/)"]
        if p.full_name:
            lines.append(f"  имя: {p.full_name}")
        if p.category:
            lines.append(f"  категория: {p.category}")
        lines.append(f"  подписчики: {p.followers}, постов: {p.posts}")
        if p.engagement_rate:
            lines.append(
                f"  вовлечённость: {p.engagement_rate}% "
                f"(≈{p.avg_likes} лайков, {p.avg_comments} комм. на пост)"
            )
        if p.external_url:
            lines.append(f"  ссылка в bio: {p.external_url}")
        if p.biography:
            lines.append(f"  bio: {p.biography.strip()}")
        if p.sample_captions:
            joined = " | ".join(c.replace(chr(10), " ") for c in p.sample_captions)
            lines.append(f"  примеры подписей: {joined}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _collect_apify(handles):
    """Сбор через Apify — один запуск актора на весь список. Генератор событий;
    последним yield-ит ('collected', список ProfileData)."""
    yield {"type": "node", "name": "Сбор профилей (Apify)"}
    yield {"type": "info", "name": "Apify: запускаю актор",
           "text": f"instagram-profile-scraper на {len(handles)} профилей. "
           "Актор работает на стороне Apify, это займёт 1-3 минуты…"}
    try:
        by_user, raw = apify.fetch_base_profiles(handles)
    except Exception as e:  # noqa: BLE001
        yield {"type": "error", "message": f"Ошибка Apify: {e}"}
        yield ("collected", None)
        return

    # Диагностика: сколько записей вернул актор и какие в них поля
    diag = f"Актор вернул {len(raw)} записей, распознано профилей: {len(by_user)}."
    if raw:
        first = raw[0]
        if isinstance(first, dict):
            diag += " Поля первой записи: " + ", ".join(sorted(first.keys())[:20])
    yield {"type": "info", "name": "Apify: диагностика", "text": diag}

    collected = []
    for h in handles:
        p = by_user.get(h)
        if p and p.ok:
            collected.append(p)
            out = f"@{h}: {p.followers} подписчиков, {p.posts} постов"
            if p.engagement_rate:
                out += f", ER {p.engagement_rate}%"
            if p.biography:
                out += f"\nbio: {p.biography.strip()[:200]}"
            yield {"type": "tool_result", "name": "apify", "output": out}
        else:
            reason = p.error if p else "не вернулся из Apify"
            yield {"type": "info", "name": f"@{h} — недоступен", "text": reason}
    yield ("collected", collected)


def _collect_instaloader(handles):
    """Запасной сбор — анонимный instaloader, по одному профилю с паузой."""
    yield {"type": "node", "name": "Сбор профилей (instaloader)"}
    if LOGGED_IN:
        yield {"type": "info", "name": "Instagram: залогинен",
               "text": "Сбор идёт через сохранённую сессию."}
    else:
        yield {"type": "info", "name": "Instagram: анонимно",
               "text": "Ни APIFY_TOKEN, ни сессия (IG_USERNAME) не заданы — "
               "Instagram, скорее всего, будет отбивать запросы (429)."}
    collected = []
    for h in handles:
        yield {"type": "tool_call", "name": "instaloader", "args": {"username": h}}
        data = fetch_profile(h)
        if data.ok:
            collected.append(data)
            out = f"@{h}: {data.followers} подписчиков, {data.posts} постов"
            if data.biography:
                out += f"\nbio: {data.biography.strip()[:200]}"
            yield {"type": "tool_result", "name": "instaloader", "output": out}
        else:
            yield {"type": "info", "name": f"@{h} — недоступен", "text": data.error}
        time.sleep(FETCH_DELAY_SEC)
    yield ("collected", collected)


def run(model: str):
    """Генератор событий трейса этапа 1."""
    sheet_id = os.environ.get("SHEET_ID", "")
    sheet_gid = os.environ.get("SHEET_GID", "0")

    # 1. Подключение к таблице
    yield {"type": "node", "name": "Подключение к таблице"}
    try:
        handles = fetch_handles(sheet_id, sheet_gid)
    except Exception as e:  # noqa: BLE001
        yield {"type": "error", "message": f"Не удалось прочитать таблицу: {e}"}
        return
    yield {
        "type": "tool_result",
        "name": "google_sheet",
        "output": f"Найдено {len(handles)} ников: " + ", ".join("@" + h for h in handles),
    }

    # 2. Сбор профилей — Apify приоритетнее, instaloader как запасной
    collector = _collect_apify(handles) if apify.has_token() else _collect_instaloader(handles)
    collected = []
    for ev in collector:
        if isinstance(ev, tuple) and ev[0] == "collected":
            collected = ev[1] or []
        else:
            yield ev

    yield {
        "type": "info",
        "name": "Сбор завершён",
        "text": f"Прочитано {len(collected)} из {len(handles)} профилей "
        f"(недоступно: {len(handles) - len(collected)}).",
    }

    if not collected:
        yield {"type": "error", "message": "Ни один профиль не удалось прочитать. "
               "Проверьте APIFY_TOKEN, либо повторите позже."}
        return

    # 3. Синтез портрета через Claude
    yield {"type": "node", "name": "Синтез портрета (Claude)"}
    user_prompt = ANALYZE_USER.format(
        collected=len(collected), total=len(handles),
        profiles=_format_profiles(collected),
    )
    yield {"type": "info", "name": "📋 Промпт (system)", "text": ANALYZE_SYSTEM}
    yield {"type": "info", "name": "📋 Промпт (запрос)", "text": user_prompt}
    try:
        report, usage = synthesize_portrait(model, collected, len(handles))
    except Exception as e:  # noqa: BLE001
        yield {"type": "error", "message": f"Ошибка Claude API: {e}"}
        return
    yield {"type": "final", "report": report, "usage": usage}


def synthesize_portrait(model, collected, total):
    """Один вызов Claude → «портрет». Стриминг + таймаут, чтобы не зависало.
    Переиспользуется этапом 2, если портрет не передан из интерфейса."""
    client = anthropic.Anthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY"), timeout=90.0, max_retries=1
    )
    user_prompt = ANALYZE_USER.format(
        collected=len(collected),
        total=total,
        profiles=_format_profiles(collected),
    )
    with client.messages.stream(
        model=model,
        max_tokens=2000,
        system=ANALYZE_SYSTEM,
        messages=[{"role": "user", "content": user_prompt}],
    ) as stream:
        msg = stream.get_final_message()
    report = "".join(b.text for b in msg.content if b.type == "text")
    usage = {
        "input_tokens": msg.usage.input_tokens,
        "output_tokens": msg.usage.output_tokens,
        "cache_read": getattr(msg.usage, "cache_read_input_tokens", 0) or 0,
        "cache_creation": getattr(msg.usage, "cache_creation_input_tokens", 0) or 0,
    }
    return report, usage
