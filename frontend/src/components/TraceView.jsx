// Живая визуализация цикла агента: шаги трейса.

function StepIcon({ type }) {
  const map = {
    node: "▸",
    tool_call: "🔧",
    tool_result: "📥",
    decision: "⚖️",
    info: "💡",
    error: "❌",
  };
  return <span className="step-icon">{map[type] || "•"}</span>;
}

const RESOLUTION_LABEL = {
  refund: "Возврат средств",
  exchange: "Обмен размера",
  reject: "Отказ",
  escalate: "Эскалация оператору",
};

export default function TraceView({ trace, running }) {
  if (!trace.length && !running) {
    return <p className="muted">Запустите агента, чтобы увидеть его шаги.</p>;
  }

  return (
    <div className="trace">
      {trace.map((ev, i) => (
        <div key={i} className={`step step-${ev.type}`}>
          <div className="step-head">
            <StepIcon type={ev.type} />
            {ev.type === "node" && <span className="node-name">{ev.name}</span>}
            {ev.type === "tool_call" && (
              <span>
                Вызов инструмента <code>{ev.name}</code>
              </span>
            )}
            {ev.type === "tool_result" && (
              <span>
                Результат <code>{ev.name}</code>
              </span>
            )}
            {ev.type === "decision" && (
              <span>
                Решение: <b>{RESOLUTION_LABEL[ev.resolution] || ev.resolution}</b>
              </span>
            )}
            {ev.type === "info" && <span className="node-name">{ev.name}</span>}
            {ev.type === "error" && <span>Ошибка</span>}
          </div>

          {ev.type === "tool_call" && (
            <pre className="step-body">{JSON.stringify(ev.args, null, 2)}</pre>
          )}
          {ev.type === "tool_result" && <pre className="step-body">{ev.output}</pre>}
          {ev.type === "decision" && (
            <div className="step-body">{ev.explanation}</div>
          )}
          {ev.type === "info" && <div className="step-body">{ev.text}</div>}
          {ev.type === "error" && <pre className="step-body">{ev.message}</pre>}
        </div>
      ))}

      {running && (
        <div className="step step-pending">
          <span className="step-icon spin">⏳</span> Агент работает…
        </div>
      )}
    </div>
  );
}
