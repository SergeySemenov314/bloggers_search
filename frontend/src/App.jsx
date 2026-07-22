import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { streamAnalyze, streamSearch, estimateCost } from "./api.js";
import TraceView from "./components/TraceView.jsx";
import Select from "./components/Select.jsx";

const MODELS = [
  { id: "claude-haiku-4-5", name: "Haiku 4.5 (дёшево)" },
  { id: "claude-sonnet-5", name: "Sonnet 5 (точнее)" },
];

const AGENTS = [
  { id: "analyze", name: "🔍 Анализ базы" },
  { id: "search", name: "🧭 Поиск новых" },
];

const RESULT_TITLE = {
  analyze: "Портрет идеального блогера",
  search: "Найденные блогеры",
};

export default function App() {
  const [agent, setAgent] = useState("analyze");
  const [model, setModel] = useState("claude-haiku-4-5");
  const [running, setRunning] = useState(false);
  const [trace, setTrace] = useState([]);
  const [usage, setUsage] = useState(null);
  const [error, setError] = useState(null);

  // результаты этапов держим отдельно; портрет из этапа 1 → вход этапа 2
  const [portrait, setPortrait] = useState("");
  const [found, setFound] = useState("");

  const result = agent === "analyze" ? portrait : found;

  function onEvent(ev) {
    if (ev.type === "final") {
      setUsage(ev.usage);
      if (agent === "analyze") setPortrait(ev.report);
      else setFound(ev.report);
    } else if (ev.type === "error") {
      setError(ev.message);
    } else {
      setTrace((prev) => [...prev, ev]);
    }
  }

  function reset() {
    setTrace([]);
    setUsage(null);
    setError(null);
  }

  async function run() {
    setRunning(true);
    reset();
    if (agent === "analyze") setPortrait("");
    else setFound("");
    try {
      if (agent === "analyze") await streamAnalyze({ model }, onEvent);
      else await streamSearch({ model, portrait }, onEvent);
    } catch (e) {
      setError(e.message);
    } finally {
      setRunning(false);
    }
  }

  const cost = usage ? estimateCost(model, usage) : 0;

  return (
    <>
      <header className="header">
        <span className="header-emoji">🔍</span>
        <div className="header-text">
          <h1>Поиск блогеров для бартера</h1>
          <p className="muted">Анализ базы → поиск похожих → офферы</p>
        </div>
      </header>

      <div className="app">
        {/* Переключатель этапов */}
        <div className="tabs">
          {AGENTS.map((a) => (
            <button
              key={a.id}
              className={`tab ${agent === a.id ? "tab-active" : ""}`}
              onClick={() => {
                setAgent(a.id);
                reset();
              }}
            >
              {a.name}
            </button>
          ))}
        </div>

        <div className="layout">
          {/* Панель управления */}
          <aside className="panel controls">
            {agent === "analyze" ? (
              <>
                <h2>🔍 Анализ базы</h2>
                <p className="muted small">
                  Инструмент подключается к Google-таблице, собирает данные
                  профилей через Apify и формирует портрет идеального блогера.
                </p>
              </>
            ) : (
              <>
                <h2>🧭 Поиск новых</h2>
                <p className="muted small">
                  По портрету из этапа 1 находит похожих блогеров (через
                  «похожие аккаунты» Instagram) и отбирает 3–5 лучших с
                  обоснованием.
                </p>
                <p className="field-hint">
                  {portrait
                    ? "Портрет из этапа 1 будет использован."
                    : "Портрет ещё не построен — инструмент синтезирует его сам."}
                </p>
              </>
            )}

            <label>
              Модель
              <Select value={model} options={MODELS} onChange={setModel} />
            </label>

            <button className="run-btn" onClick={run} disabled={running}>
              {running
                ? "Выполняется…"
                : agent === "analyze"
                ? "▶ Запустить анализ"
                : "▶ Найти похожих"}
            </button>

            {usage && (
              <div className="usage">
                <div>
                  Токены: <b>{usage.input_tokens}</b> вход /{" "}
                  <b>{usage.output_tokens}</b> выход
                </div>
                <div>
                  Стоимость прогона: <b>${cost.toFixed(5)}</b>
                </div>
              </div>
            )}
          </aside>

          {/* Трейс шагов */}
          <section className="panel">
            <h2>Ход работы агента</h2>
            <TraceView trace={trace} running={running} />
          </section>

          {/* Итог */}
          <section className="panel report-panel">
            <h2>{RESULT_TITLE[agent]}</h2>
            {error && <div className="error">⚠ {error}</div>}
            {result ? (
              <div className="markdown">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {result}
                </ReactMarkdown>
              </div>
            ) : (
              !error && <p className="muted">Результат появится здесь.</p>
            )}
          </section>
        </div>
      </div>
    </>
  );
}
