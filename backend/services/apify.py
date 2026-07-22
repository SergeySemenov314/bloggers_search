"""Сбор публичных данных профилей Instagram через Apify.

Актор apify/instagram-profile-scraper запускается одним синхронным вызовом на
весь список ников и возвращает надёжные данные: bio, подписчики, категория,
внешняя ссылка И последние посты с лайками/комментариями — из них считаем
вовлечённость (ER). Токен берётся из APIFY_TOKEN.
"""

import hashlib
import json
import os

import requests

from services.instagram import ProfileData

# run-sync-get-dataset-items: запускает актор и сразу отдаёт результаты (JSON).
_PROFILE_ACTOR = "apify~instagram-profile-scraper"
_HASHTAG_ACTOR = "apify~instagram-hashtag-scraper"
_URL_TMPL = "https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"

# Акторы отрабатывают за 1-3 минуты. Даём запас.
_TIMEOUT = 300

_DIR = os.path.dirname(__file__)
# Куда складывать кэш/журнал. Локально — корень backend; в Docker задаём
# DATA_DIR на смонтированный том, чтобы платный кэш Apify переживал пересборку.
_DATA_DIR = os.environ.get("DATA_DIR") or os.path.join(_DIR, "..")
# Кэш базы из таблицы — отдельный стабильный файл: собирается один раз и не
# зависит от прогонов поиска. Кэш поиска (хэштеги + кандидаты) можно чистить,
# не трогая базу.
_BASE_CACHE_FILE = os.path.join(_DATA_DIR, ".base_profiles.json")
# Кэш прочего (хэштеги, кандидаты) — можно удалять для свежего поиска.
_CACHE_FILE = os.path.join(_DATA_DIR, ".apify_cache.json")
# Журнал уже показанных кандидатов — чтобы «новые» не повторялись из кэша.
# Курсор двигается по одному и тому же собранному пулу авторов, поэтому каждый
# прогон поднимает СЛЕДУЮЩИХ авторов без единого нового запроса к Apify.
_SHOWN_FILE = os.path.join(_DATA_DIR, ".shown_candidates.json")


def load_shown() -> set[str]:
    """Ники, уже выданные как «новые» в прошлых прогонах."""
    try:
        with open(_SHOWN_FILE, encoding="utf-8") as f:
            return {str(u).lower() for u in json.load(f).get("shown", [])}
    except (OSError, ValueError):
        return set()


def add_shown(usernames) -> None:
    """Дописывает ники в журнал показанных (без дублей, сохраняя порядок)."""
    shown = []
    try:
        with open(_SHOWN_FILE, encoding="utf-8") as f:
            shown = list(json.load(f).get("shown", []))
    except (OSError, ValueError):
        shown = []
    seen = {str(u).lower() for u in shown}
    for u in usernames:
        lu = str(u).lower()
        if lu not in seen:
            shown.append(lu)
            seen.add(lu)
    try:
        with open(_SHOWN_FILE, "w", encoding="utf-8") as f:
            json.dump({"shown": shown}, f, ensure_ascii=False)
    except OSError:
        pass


def reset_shown() -> None:
    """Сбрасывает журнал (пул кандидатов пройден до конца — начинаем заново)."""
    try:
        os.remove(_SHOWN_FILE)
    except OSError:
        pass


def _cache_key(actor: str, payload: dict) -> str:
    blob = actor + "|" + json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(blob.encode("utf-8")).hexdigest()


def _cache_load(key: str, cache_file: str):
    try:
        with open(cache_file, encoding="utf-8") as f:
            return json.load(f).get(key)
    except (OSError, ValueError):
        return None


def _cache_save(key: str, items: list, cache_file: str) -> None:
    data = {}
    try:
        with open(cache_file, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    data[key] = items
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except OSError:
        pass


def has_token() -> bool:
    return bool(os.environ.get("APIFY_TOKEN", "").strip())


def _num(x) -> int:
    try:
        return int(x or 0)
    except (TypeError, ValueError):
        return 0


def _to_profile(item: dict) -> ProfileData:
    """Преобразует запись Apify в ProfileData, считая вовлечённость."""
    username = (item.get("username") or "").lower()

    # Актор для несуществующего профиля может вернуть запись с полем error.
    if item.get("error"):
        return ProfileData(username=username, ok=False, error=str(item["error"]))

    followers = _num(item.get("followersCount"))
    posts_list = item.get("latestPosts") or []

    likes = [_num(p.get("likesCount")) for p in posts_list if p.get("likesCount") is not None]
    comments = [_num(p.get("commentsCount")) for p in posts_list if p.get("commentsCount") is not None]
    avg_likes = sum(likes) / len(likes) if likes else 0.0
    avg_comments = sum(comments) / len(comments) if comments else 0.0
    er = (avg_likes + avg_comments) / followers * 100 if followers else 0.0

    captions = [
        p["caption"][:400]
        for p in posts_list
        if p.get("caption")
    ][:5]

    return ProfileData(
        username=username,
        ok=True,
        full_name=item.get("fullName") or "",
        biography=item.get("biography") or "",
        followers=followers,
        following=_num(item.get("followsCount")),
        posts=_num(item.get("postsCount")),
        external_url=item.get("externalUrl") or "",
        is_private=bool(item.get("private")),
        is_verified=bool(item.get("verified")),
        category=item.get("businessCategoryName") or "",
        avg_likes=round(avg_likes, 1),
        avg_comments=round(avg_comments, 1),
        engagement_rate=round(er, 2),
        sample_captions=captions,
    )


def _run_actor(actor: str, payload: dict, cache_file: str = _CACHE_FILE) -> list:
    """Запускает актор (с кэшем на диске) и возвращает сырой список записей."""
    key = _cache_key(actor, payload)
    items = _cache_load(key, cache_file)
    if items is not None:
        return items

    token = os.environ.get("APIFY_TOKEN", "").strip()
    resp = requests.post(
        _URL_TMPL.format(actor=actor),
        params={"token": token, "timeout": _TIMEOUT},
        json=payload,
        timeout=_TIMEOUT + 30,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:400]}")
    items = resp.json()
    if not isinstance(items, list):
        raise RuntimeError(f"Неожиданный ответ Apify: {str(items)[:400]}")
    _cache_save(key, items, cache_file)
    return items


def _profiles_from_items(items: list) -> tuple[dict[str, ProfileData], list]:
    result: dict[str, ProfileData] = {}
    for item in items:
        p = _to_profile(item)
        if p.username:
            result[p.username] = p
    return result, items


def fetch_profiles(usernames: list[str]) -> tuple[dict[str, ProfileData], list]:
    """Данные профилей-кандидатов (кэш поиска: .apify_cache.json)."""
    return _profiles_from_items(_run_actor(_PROFILE_ACTOR, {"usernames": usernames}))


def fetch_base_profiles(usernames: list[str]) -> tuple[dict[str, ProfileData], list]:
    """Данные профилей БАЗЫ из таблицы — отдельный стабильный кэш
    (.base_profiles.json), не зависящий от прогонов поиска."""
    return _profiles_from_items(
        _run_actor(_PROFILE_ACTOR, {"usernames": usernames}, _BASE_CACHE_FILE)
    )


def fetch_hashtag_posts(hashtags: list[str], results_limit: int = 30) -> list:
    """Посты по нишевым хэштегам. У каждого поста есть ownerUsername (кандидат)."""
    return _run_actor(
        _HASHTAG_ACTOR,
        {"hashtags": hashtags, "resultsType": "posts", "resultsLimit": results_limit},
    )
