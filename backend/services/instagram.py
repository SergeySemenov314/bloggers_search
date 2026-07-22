"""Сбор публичных данных профиля Instagram через instaloader (без логина).

Anonymous-доступ отдаёт метаданные профиля (bio, подписчики, число постов,
имя, внешняя ссылка). Ленту постов Instagram анонимам обычно не отдаёт —
поэтому подписи к постам берём «по возможности» и молча пропускаем, если не
вышло. Никаких ключей и авторизации: если профиль закрыт/битый/залимичен —
возвращаем ошибку, а вызывающий код помечает его в трейсе и идёт дальше.
"""

from dataclasses import dataclass, asdict

import instaloader


@dataclass
class ProfileData:
    username: str
    ok: bool
    full_name: str = ""
    biography: str = ""
    followers: int = 0
    following: int = 0
    posts: int = 0
    external_url: str = ""
    is_private: bool = False
    is_verified: bool = False
    category: str = ""            # категория аккаунта (Apify)
    avg_likes: float = 0.0        # средние лайки по последним постам
    avg_comments: float = 0.0     # средние комментарии
    engagement_rate: float = 0.0  # вовлечённость, % = (лайки+комменты)/подписчики
    sample_captions: list[str] | None = None
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


import os

# Один общий экземпляр. Умеренные паузы, чтобы реже ловить лимиты.
_loader = instaloader.Instaloader(
    quiet=True,
    download_pictures=False,
    download_videos=False,
    download_video_thumbnails=False,
    download_geotags=False,
    download_comments=False,
    save_metadata=False,
    max_connection_attempts=1,
)

# Если задан IG_USERNAME и есть сохранённая сессия — логинимся.
# Анонимный доступ Instagram почти закрыл (429), с сессией данные идут стабильно.
# Сессия создаётся один раз командой:  instaloader --login=IG_USERNAME
LOGGED_IN = False
_ig_user = os.environ.get("IG_USERNAME", "").strip()
if _ig_user:
    try:
        _loader.load_session_from_file(_ig_user)
        LOGGED_IN = True
    except Exception:  # noqa: BLE001 — сессии нет/битая → работаем анонимно
        LOGGED_IN = False


def fetch_profile(username: str, want_captions: int = 3) -> ProfileData:
    """Тянет метаданные профиля. Ошибку возвращает в поле error (ok=False)."""
    try:
        p = instaloader.Profile.from_username(_loader.context, username)
    except instaloader.exceptions.ProfileNotExistsException:
        return ProfileData(username=username, ok=False, error="профиль не найден")
    except instaloader.exceptions.LoginRequiredException:
        return ProfileData(username=username, ok=False, error="Instagram требует вход (лимит/защита)")
    except Exception as e:  # noqa: BLE001 — сеть/лимиты/редкие случаи
        return ProfileData(username=username, ok=False, error=f"{type(e).__name__}: {e}")

    data = ProfileData(
        username=username,
        ok=True,
        full_name=p.full_name or "",
        biography=p.biography or "",
        followers=p.followers or 0,
        following=p.followees or 0,
        posts=p.mediacount or 0,
        external_url=p.external_url or "",
        is_private=p.is_private,
        is_verified=p.is_verified,
        sample_captions=[],
    )

    # Подписи к постам — по возможности. Для закрытых/анонимных часто недоступно.
    if want_captions and not p.is_private:
        try:
            for i, post in enumerate(p.get_posts()):
                if i >= want_captions:
                    break
                if post.caption:
                    data.sample_captions.append(post.caption[:400])
        except Exception:  # noqa: BLE001 — лента анонимам недоступна, это ок
            pass

    return data
