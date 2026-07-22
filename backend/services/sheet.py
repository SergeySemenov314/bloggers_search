"""Подключение к Google-таблице и извлечение ников Instagram.

Таблица опубликована только на чтение — берём её CSV-экспорт (без ключей и
OAuth). Из каждой строки достаём Instagram-ник, аккуратно разбирая и битые/
нестандартные ссылки (query-хвосты, /profilecard/, строку-заголовок вида
«… (@nick) • Instagram …»).
"""

import re
import requests

CSV_URL = "https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"

# Служебные сегменты пути, которые не являются ником
_SKIP_SEGMENTS = {"p", "reel", "reels", "stories", "explore", "profilecard", "s"}


def _handle_from_url(url: str) -> str | None:
    """Достаёт ник из instagram-ссылки. Возвращает None, если не вышло."""
    m = re.search(r"instagram\.com/([^/?#\s]+)", url, re.IGNORECASE)
    if not m:
        return None
    handle = m.group(1).strip().strip("@").lower()
    if not handle or handle in _SKIP_SEGMENTS:
        return None
    return handle


def _handle_from_text(text: str) -> str | None:
    """Запасной разбор: ник из текста-заголовка вида '… (@mishandkatya) …'."""
    m = re.search(r"@([A-Za-z0-9._]+)", text)
    return m.group(1).lower() if m else None


def fetch_handles(sheet_id: str, gid: str = "0") -> list[str]:
    """Скачивает таблицу и возвращает уникальные ники в порядке появления."""
    url = CSV_URL.format(sheet_id=sheet_id, gid=gid)
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    resp.encoding = "utf-8"

    handles: list[str] = []
    seen: set[str] = set()
    for raw_line in resp.text.splitlines():
        line = raw_line.strip().strip(",").strip()
        if not line:
            continue
        handle = _handle_from_url(line) or _handle_from_text(line)
        if handle and handle not in seen:
            seen.add(handle)
            handles.append(handle)
    return handles
