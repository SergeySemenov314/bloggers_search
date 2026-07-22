// Клиент к бэкенду. Стрим трейса агента через SSE поверх fetch.

// В проде base = "/bloggers/" → API = "/bloggers/api"; в деве base = "/" → "/api".
const API = `${import.meta.env.BASE_URL}api`;

// Цены Claude, $/1M токенов (вход/выход) — для оценки стоимости прогона.
export const PRICING = {
  "claude-haiku-4-5": { in: 1.0, out: 5.0 },
  "claude-sonnet-5": { in: 3.0, out: 15.0 },
};

export function estimateCost(model, usage) {
  const p = PRICING[model] || PRICING["claude-haiku-4-5"];
  const cacheRead = usage.cache_read || 0;
  const cacheCreate = usage.cache_creation || 0;
  // "свежие" (не кэшированные) входные токены
  const fresh = Math.max(0, (usage.input_tokens || 0) - cacheRead - cacheCreate);
  // кэш-чтение ~0.1x, кэш-запись ~1.25x от цены входа
  const cost =
    (fresh * p.in +
      cacheRead * p.in * 0.1 +
      cacheCreate * p.in * 1.25 +
      (usage.output_tokens || 0) * p.out) /
    1_000_000;
  return cost;
}

// Универсальный SSE-стрим: POST на endpoint, onEvent на каждое событие трейса.
async function streamAgent(path, body, onEvent) {
  const res = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!res.ok || !res.body) {
    throw new Error(`Ошибка запроса: ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const parts = buffer.split("\n\n");
    buffer = parts.pop(); // хвост без завершающего разделителя

    for (const part of parts) {
      const line = part.split("\n").find((l) => l.startsWith("data:"));
      if (!line) continue;
      try {
        onEvent(JSON.parse(line.slice(5).trim()));
      } catch {
        // пропускаем некорректный кусок
      }
    }
  }
}

// Этап 1 — агент «Анализ базы»
export function streamAnalyze({ model }, onEvent) {
  return streamAgent("/agents/analyze/stream", { model }, onEvent);
}

// Этап 2 — агент «Поиск новых» (портрет из этапа 1 передаём, если есть)
export function streamSearch({ model, portrait }, onEvent) {
  return streamAgent(
    "/agents/search/stream",
    { model, portrait: portrait || null },
    onEvent
  );
}

// Этап 3 — агент «Офферы» (блогеры из этапа 2 + бриф бренда)
export function streamOffers({ model, bloggers, brief }, onEvent) {
  return streamAgent(
    "/agents/offers/stream",
    { model, bloggers: bloggers || null, brief: brief || null },
    onEvent
  );
}
