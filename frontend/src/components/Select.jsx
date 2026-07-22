// Кастомный селект: выпадающий список строго по ширине поля
// (у нативного <select> ширину списка задаёт ОС, стилизовать её нельзя).

import { useState, useRef, useEffect } from "react";

export default function Select({ value, options, onChange }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  // закрытие по клику вне и по Escape
  useEffect(() => {
    if (!open) return;
    const onDocClick = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    const onKey = (e) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const current = options.find((o) => o.id === value);

  return (
    <div className="select" ref={ref}>
      <button
        type="button"
        className="select-trigger"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span>{current ? current.name : value}</span>
        <span className="select-arrow">▾</span>
      </button>

      {open && (
        <ul className="select-list" role="listbox">
          {options.map((o) => (
            <li key={o.id}>
              <button
                type="button"
                role="option"
                aria-selected={o.id === value}
                className={`select-option ${o.id === value ? "is-selected" : ""}`}
                onClick={() => {
                  onChange(o.id);
                  setOpen(false);
                }}
              >
                {o.name}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
