import { useState, useEffect } from "react";
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

// ссылки в результатах открываем в новой вкладке
const MD_COMPONENTS = {
  a: (props) => <a {...props} target="_blank" rel="noopener noreferrer" />,
};

// пустое состояние по каждому этапу
const empty = () => ({ analyze: null, search: null });

// сохранение результатов между перезагрузками/переходами
const LS_KEY = "bloggers_search_state_v1";
const loadSaved = () => {
  try {
    return JSON.parse(localStorage.getItem(LS_KEY)) || {};
  } catch {
    return {};
  }
};

export default function App() {
  const saved = loadSaved();

  const [agent, setAgent] = useState("analyze");
  const [model, setModel] = useState("claude-haiku-4-5");

  // какой этап сейчас выполняется (null — ничего)
  const [runningAgent, setRunningAgent] = useState(null);

  // всё состояние держим ОТДЕЛЬНО по каждому этапу, чтобы переключение
  // вкладок не стирало результаты; и восстанавливаем из localStorage
  const [traces, setTraces] = useState(saved.traces || { analyze: [], search: [] });
  const [usages, setUsages] = useState(saved.usages || empty());
  const [errors, setErrors] = useState(saved.errors || empty());
  const [reports, setReports] = useState(saved.reports || { analyze: "", search: "" });

  // при любом изменении результатов — сохраняем, чтобы пережить перезагрузку
  useEffect(() => {
    try {
      localStorage.setItem(
        LS_KEY,
        JSON.stringify({ traces, usages, errors, reports })
      );
    } catch {
      // localStorage недоступен — не критично
    }
  }, [traces, usages, errors, reports]);

  // то, что показываем сейчас — срез по активной вкладке
  const trace = traces[agent];
  const usage = usages[agent];
  const error = errors[agent];
  const result = reports[agent];
  const running = runningAgent !== null;
  const cost = usage ? estimateCost(model, usage) : 0;

  async function run() {
    const a = agent; // фиксируем этап на момент запуска
    setRunningAgent(a);
    // очищаем ТОЛЬКО текущий этап
    setTraces((t) => ({ ...t, [a]: [] }));
    setUsages((u) => ({ ...u, [a]: null }));
    setErrors((e) => ({ ...e, [a]: null }));
    setReports((r) => ({ ...r, [a]: "" }));

    const onEvent = (ev) => {
      if (ev.type === "final") {
        setUsages((u) => ({ ...u, [a]: ev.usage }));
        setReports((r) => ({ ...r, [a]: ev.report }));
      } else if (ev.type === "error") {
        setErrors((e) => ({ ...e, [a]: ev.message }));
      } else {
        setTraces((t) => ({ ...t, [a]: [...t[a], ev] }));
      }
    };

    try {
      if (a === "analyze") await streamAnalyze({ model }, onEvent);
      else await streamSearch({ model, portrait: reports.analyze }, onEvent);
    } catch (e) {
      setErrors((er) => ({ ...er, [a]: e.message }));
    } finally {
      setRunningAgent(null);
    }
  }

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
        {/* Переключатель этапов — вкладки не сбрасывают результаты */}
        <div className="tabs">
          {AGENTS.map((a) => (
            <button
              key={a.id}
              className={`tab ${agent === a.id ? "tab-active" : ""}`}
              onClick={() => setAgent(a.id)}
            >
              {a.name}
              {runningAgent === a.id && " …"}
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
                  По портрету из этапа 1 находит похожих блогеров (по нишевым
                  хэштегам) и отбирает 3–5 лучших с обоснованием.
                </p>
                <p className="field-hint">
                  {reports.analyze
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
              {runningAgent === agent
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
            <TraceView trace={trace} running={runningAgent === agent} />
          </section>

          {/* Итог */}
          <section className="panel report-panel">
            <h2>{RESULT_TITLE[agent]}</h2>
            {error && <div className="error">⚠ {error}</div>}
            {result ? (
              <div className="markdown">
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={MD_COMPONENTS}>
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
