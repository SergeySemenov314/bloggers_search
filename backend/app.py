"""FastAPI-бэкенд инструмента поиска блогеров.

Отдаёт агентов по SSE: каждый шаг агента уходит во фронтенд событием трейса
(тот же протокол, что в референс-интерфейсе). Пока подключён этап 1 —
«Анализ базы». Этапы 2 (поиск) и 3 (офферы) добавим следующими.
"""

import json

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

load_dotenv()

from agents import analyze, search  # noqa: E402 — после load_dotenv, чтобы видеть ключи

app = FastAPI(title="Bloggers Search — AI Agents")

# Для локальной разработки: фронт на vite-dev-сервере ходит через прокси, но
# разрешаем CORS на случай прямого обращения.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def sse(gen):
    """Оборачивает генератор событий-словарей в поток SSE (data: {...}\\n\\n)."""
    for event in gen:
        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


class AnalyzeRequest(BaseModel):
    model: str = "claude-haiku-4-5"


class SearchRequest(BaseModel):
    model: str = "claude-haiku-4-5"
    portrait: str | None = None  # портрет из этапа 1 (если уже получен)


@app.get("/api/agents")
def list_agents():
    return [
        {"id": "analyze", "name": "🔍 Анализ базы"},
        {"id": "search", "name": "🧭 Поиск новых"},
    ]


@app.post("/api/agents/analyze/stream")
def analyze_stream(req: AnalyzeRequest):
    return StreamingResponse(
        sse(analyze.run(req.model)),
        media_type="text/event-stream",
    )


@app.post("/api/agents/search/stream")
def search_stream(req: SearchRequest):
    return StreamingResponse(
        sse(search.run(req.model, req.portrait)),
        media_type="text/event-stream",
    )


@app.get("/api/health")
def health():
    return {"ok": True}
