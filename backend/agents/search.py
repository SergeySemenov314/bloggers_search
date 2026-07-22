"""Этап 2 — агент «Поиск новых».

Берёт «портрет» из этапа 1 → собирает кандидатов из relatedProfiles базы (то,
что Instagram считает похожими аккаунтами) → добирает по ним реальные данные
через Apify → Claude отбирает 3–5 лучших под портрет с обоснованием.
"""

import os
from collections import Counter

import anthropic

from prompts import SEARCH_SYSTEM, SEARCH_USER
from services.sheet import fetch_handles
from services import apify
from agents.analyze import _format_profiles, synthesize_portrait

# Нишевые хэштеги (из портрета базы): маркетплейс-находки, женский стиль, WB/Ozon.
HASHTAGS = [
    "находкивайлдберриз",
    "wildberriesнаходки",
    "образыwb",
    "озоннаходки",
    "стильныеобразы",
    "вайлдберриз",
]
POSTS_PER_HASHTAG = 30  # сколько постов тянуть по каждому хэштегу
TOP_CANDIDATES = 15     # сколько топ-кандидатов добирать данными
MIN_FOLLOWERS = 1000    # отсев мелких/неактивных после скрейпа
MIN_POSTS = 3

# Маркеры магазинов/брендов в нике — отсеиваем ДО скрейпа (это не блогеры,
# и заодно экономим платные запросы Apify).
_SHOP_MARKERS = (
    "shop", "store", "official", "market", "brand", "optom", "_opt",
    "магазин", "dostavka", "sale", ".ru", "_ru",
)


def _looks_like_shop(username: str) -> bool:
    u = username.lower()
    return any(m in u for m in _SHOP_MARKERS)


def _candidates_from_posts(posts, exclude: set) -> Counter:
    """Считает авторов постов по хэштегам. Чем чаще автор попадается в нишевых
    хэштегах — тем сильнее сигнал, что он в нужной теме."""
    counter: Counter = Counter()
    for post in posts:
        if not isinstance(post, dict):
            continue
        u = (post.get("ownerUsername") or "").strip().lower()
        if u and u not in exclude:
            counter[u] += 1
    return counter


def run(model: str, portrait: str | None = None):
    """Генератор событий трейса этапа 2."""
    sheet_id = os.environ.get("SHEET_ID", "")
    sheet_gid = os.environ.get("SHEET_GID", "0")

    # 1. Таблица
    yield {"type": "node", "name": "Подключение к таблице"}
    try:
        handles = fetch_handles(sheet_id, sheet_gid)
    except Exception as e:  # noqa: BLE001
        yield {"type": "error", "message": f"Не удалось прочитать таблицу: {e}"}
        return

    # 2. Данные базы (из кэша Apify — бесплатно)
    yield {"type": "node", "name": "Загрузка базы (кэш Apify)"}
    if not apify.has_token():
        yield {"type": "error", "message": "Не задан APIFY_TOKEN — этап 2 использует Apify."}
        return
    try:
        base_by_user, base_raw = apify.fetch_base_profiles(handles)
    except Exception as e:  # noqa: BLE001
        yield {"type": "error", "message": f"Ошибка Apify (база): {e}"}
        return
    base_ok = [p for p in base_by_user.values() if p.ok]
    yield {"type": "info", "name": "База загружена",
           "text": f"Профилей базы с данными: {len(base_ok)}."}

    # 3. Кандидаты — поиск по нишевым хэштегам
    yield {"type": "node", "name": "Поиск кандидатов по хэштегам (Apify)"}
    yield {"type": "info", "name": "Хэштеги",
           "text": "Ищу авторов постов по: " + ", ".join("#" + h for h in HASHTAGS)
           + " (из кэша либо ~1-2 мин)…"}
    try:
        posts = apify.fetch_hashtag_posts(HASHTAGS, POSTS_PER_HASHTAG)
    except Exception as e:  # noqa: BLE001
        yield {"type": "error", "message": f"Ошибка Apify (хэштеги): {e}"}
        return
    # Исключаем всех, кто уже в нашей базе (и по нику из таблицы, и по факту
    # спарсенных профилей) — нормализуем @ и регистр, чтобы ничего не просочилось.
    norm = lambda u: (u or "").strip().lstrip("@").lower()  # noqa: E731
    exclude = {norm(h) for h in handles} | {norm(p.username) for p in base_ok}
    counter = _candidates_from_posts(posts, exclude)
    if not counter:
        yield {"type": "error", "message": "По хэштегам не нашлось кандидатов. "
               "Попробуйте другие хэштеги."}
        return

    # Журнал показанных: исключаем уже выданных в прошлых прогонах, чтобы курсор
    # двигался по пулу и поднимал СЛЕДУЮЩИХ авторов (без новых запросов Apify).
    shown = apify.load_shown()

    def _pick_top(skip: set) -> list:
        """Топ-кандидаты по частоте, минус магазины и минус `skip`."""
        picked = []
        for u, _cnt in counter.most_common():
            if u in skip or _looks_like_shop(u):
                continue
            picked.append(u)
            if len(picked) >= TOP_CANDIDATES:
                break
        return picked

    top = _pick_top(exclude | shown)
    # Пул пройден до конца (новых авторов не осталось) — сбрасываем журнал и
    # начинаем цикл заново по тому же кэшу.
    if not top and shown:
        apify.reset_shown()
        shown = set()
        yield {"type": "info", "name": "Журнал сброшен",
               "text": "Все закэшированные авторы уже показывались — "
               "начинаю цикл заново."}
        top = _pick_top(exclude)
    preview = ", ".join(f"@{u}×{counter[u]}" for u in top[:10])
    yield {"type": "tool_result", "name": "hashtag_search",
           "output": f"Постов собрано: {len(posts)}. Уникальных авторов: "
           f"{len(counter)}. После отсева магазинов беру топ-{len(top)} по "
           f"частоте:\n{preview}"}

    # 4. Добор данных по кандидатам (Apify, кэшируется)
    yield {"type": "node", "name": "Добор данных по кандидатам (Apify)"}
    yield {"type": "info", "name": "Apify",
           "text": f"Собираю данные по {len(top)} кандидатам "
           "(из кэша либо ~1-2 мин)…"}
    try:
        cand_by_user, _ = apify.fetch_profiles(top)
    except Exception as e:  # noqa: BLE001
        yield {"type": "error", "message": f"Ошибка Apify (кандидаты): {e}"}
        return
    # Гарантированно исключаем тех, кто уже в базе (страховка поверх отсева выше)
    scraped = [p for p in cand_by_user.values()
               if p.ok and norm(p.username) not in exclude]
    # Отсев мелких/неактивных — чтобы Claude выбирал из чистого пула
    candidates = [p for p in scraped
                  if p.followers >= MIN_FOLLOWERS and p.posts >= MIN_POSTS]
    passed = {p.username for p in candidates}
    for p in scraped:
        out = f"@{p.username}: {p.followers} подписчиков"
        if p.engagement_rate:
            out += f", ER {p.engagement_rate}%"
        if p.username not in passed:
            out += "  — отсеян (мелкий/неактивный)"
        yield {"type": "tool_result", "name": "apify", "output": out}
    if not candidates:
        candidates = scraped  # фильтр убрал всех — отдаём что есть
    if not candidates:
        yield {"type": "error", "message": "Ни по одному кандидату не удалось "
               "получить данные. Повторите позже."}
        return

    # 5. Портрет: из этапа 1 или синтезируем на месте
    if not portrait or not portrait.strip():
        yield {"type": "node", "name": "Портрет не передан — синтезирую"}
        try:
            portrait, _ = synthesize_portrait(model, base_ok, len(handles))
        except Exception as e:  # noqa: BLE001
            yield {"type": "error", "message": f"Ошибка Claude (портрет): {e}"}
            return

    # 6. Отбор Claude
    yield {"type": "node", "name": "Отбор кандидатов (Claude)"}
    client = anthropic.Anthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY"), timeout=90.0, max_retries=1
    )
    user_prompt = SEARCH_USER.format(
        portrait=portrait.strip(),
        candidates=_format_profiles(candidates),
    )
    yield {"type": "info", "name": "📋 Промпт (system)", "text": SEARCH_SYSTEM}
    yield {"type": "info", "name": "📋 Промпт (запрос)", "text": user_prompt}
    try:
        with client.messages.stream(
            model=model,
            max_tokens=2500,
            system=SEARCH_SYSTEM,
            messages=[{"role": "user", "content": user_prompt}],
        ) as stream:
            msg = stream.get_final_message()
    except Exception as e:  # noqa: BLE001
        yield {"type": "error", "message": f"Ошибка Claude API: {e}"}
        return

    report = "".join(b.text for b in msg.content if b.type == "text")
    # Двигаем курсор: помечаем выданных кандидатов показанными, чтобы в следующий
    # раз из того же кэша поднялись следующие авторы.
    apify.add_shown(top)
    usage = {
        "input_tokens": msg.usage.input_tokens,
        "output_tokens": msg.usage.output_tokens,
        "cache_read": getattr(msg.usage, "cache_read_input_tokens", 0) or 0,
        "cache_creation": getattr(msg.usage, "cache_creation_input_tokens", 0) or 0,
    }
    yield {"type": "final", "report": report, "usage": usage}
