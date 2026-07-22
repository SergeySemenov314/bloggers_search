import { useState, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  streamAnalyze,
  streamSearch,
  streamOffers,
  estimateCost,
} from "./api.js";
import TraceView from "./components/TraceView.jsx";
import Select from "./components/Select.jsx";

const MODELS = [
  { id: "claude-haiku-4-5", name: "Haiku 4.5 (дёшево)" },
  { id: "claude-sonnet-5", name: "Sonnet 5 (точнее)" },
];

const AGENTS = [
  { id: "analyze", name: "🔍 Анализ базы" },
  { id: "search", name: "🧭 Поиск новых" },
  { id: "offers", name: "✉️ Офферы" },
];

const RESULT_TITLE = {
  analyze: "Портрет идеального блогера",
  search: "Найденные блогеры",
  offers: "Готовые офферы",
};

// Бриф бренда по умолчанию (можно править прямо в интерфейсе).
const DEFAULT_BRIEF = `Бренд: LD LATTE (LDLATTE) — женская одежда, продаётся на Wildberries. Instagram: @ldlatte.
Стиль: женственные элегантные образы — костюмы-двойки, шорты, юбки, топы и корсеты, комплекты из льна, твида и атласа. Европейская эстетика, чистая подача. Ценник ~1500–4500 ₽.
Бартер: бесплатно отправляем комплект на выбор (1–2 вещи из актуальной коллекции) в обмен на 1 reels + 2 stories с отметкой @ldlatte и артикулами товаров. Одежда остаётся у блогера.`;

// ссылки в результатах открываем в новой вкладке (node из props отбрасываем —
// это служебное поле react-markdown, в DOM ему не место)
const MD_COMPONENTS = {
  a: ({ node, ...props }) => (
    <a {...props} target="_blank" rel="noopener noreferrer" />
  ),
};

// пустое состояние по каждому этапу
const empty = () => ({ analyze: null, search: null, offers: null });

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
  const [brief, setBrief] = useState(saved.brief ?? DEFAULT_BRIEF);

  // какой этап сейчас выполняется (null — ничего) и какие уже завершены
  const [runningAgent, setRunningAgent] = useState(null);
  const [completed, setCompleted] = useState({
    analyze: false,
    search: false,
    offers: false,
  });

  // всё состояние держим ОТДЕЛЬНО по каждому этапу; домешиваем дефолты, чтобы
  // все три этапа всегда были в состоянии (localStorage может быть старого
  // формата, без offers), и восстанавливаем из localStorage
  const [traces, setTraces] = useState({
    analyze: [],
    search: [],
    offers: [],
    ...(saved.traces || {}),
  });
  const [usages, setUsages] = useState({ ...empty(), ...(saved.usages || {}) });
  const [errors, setErrors] = useState({ ...empty(), ...(saved.errors || {}) });
  const [reports, setReports] = useState({
    analyze: "",
    search: "",
    offers: "",
    ...(saved.reports || {}),
  });

  // при любом изменении — сохраняем, чтобы пережить перезагрузку
  useEffect(() => {
    try {
      localStorage.setItem(
        LS_KEY,
        JSON.stringify({ traces, usages, errors, reports, brief })
      );
    } catch {
      // localStorage недоступен — не критично
    }
  }, [traces, usages, errors, reports, brief]);

  // то, что показываем сейчас — срез по активной вкладке
  const trace = traces[agent];
  const usage = usages[agent];
  const error = errors[agent];
  const result = reports[agent];
  const running = runningAgent !== null;
  const cost = usage ? estimateCost(model, usage) : 0;

  // Прогон одного этапа: стримит, пишет состояние, возвращает итоговый отчёт.
  function runStage(a, extra) {
    setRunningAgent(a);
    setTraces((t) => ({ ...t, [a]: [] }));
    setUsages((u) => ({ ...u, [a]: null }));
    setErrors((e) => ({ ...e, [a]: null }));
    setReports((r) => ({ ...r, [a]: "" }));

    let report = "";
    let err = null;
    const onEvent = (ev) => {
      if (ev.type === "final") {
        report = ev.report;
        setUsages((u) => ({ ...u, [a]: ev.usage }));
        setReports((r) => ({ ...r, [a]: ev.report }));
      } else if (ev.type === "error") {
        err = ev.message;
        setErrors((e) => ({ ...e, [a]: ev.message }));
      } else {
        setTraces((t) => ({ ...t, [a]: [...t[a], ev] }));
      }
    };

    let call;
    if (a === "analyze") call = streamAnalyze({ model }, onEvent);
    else if (a === "search")
      call = streamSearch({ model, portrait: extra.portrait }, onEvent);
    else call = streamOffers({ model, bloggers: extra.bloggers, brief }, onEvent);

    return call
      .catch((e) => {
        err = e.message;
        setErrors((er) => ({ ...er, [a]: e.message }));
      })
      .then(() => ({ report, err }));
  }

  // Прогон всего процесса: этап 1 → 2 → 3, с переключением вкладок и зелёной
  // отметкой завершённых. Результат каждого этапа передаётся в следующий.
  async function runAll() {
    if (running) return;
    setCompleted({ analyze: false, search: false, offers: false });
    try {
      setAgent("analyze");
      const r1 = await runStage("analyze", {});
      if (r1.err) return;
      setCompleted((c) => ({ ...c, analyze: true }));

      setAgent("search");
      const r2 = await runStage("search", { portrait: r1.report });
      if (r2.err) return;
      setCompleted((c) => ({ ...c, search: true }));

      setAgent("offers");
      const r3 = await runStage("offers", { bloggers: r2.report });
      if (r3.err) return;
      setCompleted((c) => ({ ...c, offers: true }));
    } finally {
      setRunningAgent(null);
    }
  }

  return (
    <>
      <header className="header">
        <span className="header-emoji">🔍</span>
        <div className="header-text">
          <h1>Поиск блогеров для бартера — LD LATTE</h1>
          <p className="muted">Анализ базы → поиск похожих → офферы</p>
        </div>
      </header>

      <div className="app">
        {/* Верхняя панель: модель + запуск всего процесса */}
        <div className="runbar">
          <button className="run-btn" onClick={runAll} disabled={running}>
            {running ? "Выполняется…" : "▶ Запустить весь процесс"}
          </button>
          <div className="model-pick">
            <span className="model-label">Выбранная модель</span>
            <Select value={model} options={MODELS} onChange={setModel} />
          </div>
        </div>

        {/* Вкладки: активная подсвечена, завершённые — зелёные. Не сбрасывают
            результаты; во время прогона переключаются автоматически. */}
        <div className="tabs">
          {AGENTS.map((a) => (
            <button
              key={a.id}
              className={
                `tab ${agent === a.id ? "tab-active" : ""} ` +
                (completed[a.id] ? "tab-done" : "")
              }
              onClick={() => setAgent(a.id)}
            >
              {completed[a.id] && "✓ "}
              {a.name}
              {runningAgent === a.id && " …"}
            </button>
          ))}
        </div>

        <div className="layout">
          {/* Панель управления — без кнопок запуска, только пояснения/бриф */}
          <aside className="panel controls">
            {agent === "analyze" && (
              <>
                <h2>🔍 Анализ базы</h2>
                <p className="muted small">
                  Инструмент подключается к Google-таблице, собирает данные
                  профилей через Apify и формирует портрет идеального блогера.
                </p>
              </>
            )}

            {agent === "search" && (
              <>
                <h2>🧭 Поиск новых</h2>
                <p className="muted small">
                  По портрету из этапа 1 находит похожих блогеров (по нишевым
                  хэштегам) и отбирает 3–5 лучших с обоснованием.
                </p>
              </>
            )}

            {agent === "offers" && (
              <>
                <h2>✉️ Офферы</h2>
                <p className="muted small">
                  На каждого блогера из этапа 2 — тёплое персональное сообщение
                  о бартере с обоснованием.
                </p>
                <label>
                  Бриф бренда и условия бартера
                  <textarea
                    rows="8"
                    value={brief}
                    onChange={(e) => setBrief(e.target.value)}
                  />
                </label>
              </>
            )}

            {usage && (
              <div className="usage">
                <div>
                  Токены: <b>{usage.input_tokens}</b> вход /{" "}
                  <b>{usage.output_tokens}</b> выход
                </div>
                <div>
                  Стоимость этапа: <b>${cost.toFixed(5)}</b>
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
