import { useEffect, useRef, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

/**
 * location field with geocoder autocomplete. debounced calls against our
 * /api/geocode/suggest/ proxy (which fronts nominatim) so the dispatcher can
 * tab through real place names instead of gambling on spellings.
 */
export default function GeocodeField({ label, value, onChange, placeholder }) {
  const [suggestions, setSuggestions] = useState([]);
  const [open, setOpen] = useState(false);
  const [activeIdx, setActiveIdx] = useState(-1);
  const timer = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => () => clearTimeout(timer.current), []);

  async function queryApi(q) {
    try {
      const resp = await fetch(`${API_BASE}/api/geocode/suggest/?q=${encodeURIComponent(q)}`);
      if (!resp.ok) return [];
      return await resp.json();
    } catch {
      return [];
    }
  }

  function handleChange(e) {
    const q = e.target.value;
    onChange(q);
    clearTimeout(timer.current);
    if (q.trim().length < 3) {
      setSuggestions([]);
      setOpen(false);
      return;
    }
    timer.current = setTimeout(async () => {
      const list = await queryApi(q.trim());
      setSuggestions(list);
      setActiveIdx(-1);
      setOpen(list.length > 0);
    }, 250);
  }

  function pick(item) {
    onChange(item.name);
    setOpen(false);
    setActiveIdx(-1);
    inputRef.current?.focus();
  }

  function onKeyDown(e) {
    if (!open || suggestions.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIdx((i) => Math.min(i + 1, suggestions.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      if (activeIdx >= 0) {
        e.preventDefault();
        pick(suggestions[activeIdx]);
      }
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  return (
    <label className="field">
      <span className="field-label">{label}</span>
      <span className="field-input-wrap">
        <input
          ref={inputRef}
          type="text"
          value={value}
          onChange={handleChange}
          onKeyDown={onKeyDown}
          onFocus={() => suggestions.length && setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 120)}
          placeholder={placeholder}
          autoComplete="off"
          aria-autocomplete="list"
          aria-expanded={open}
          aria-controls={`suggest-${label.replace(/\W/g, "")}`}
        />
        {open && suggestions.length > 0 && (
          <ul
            id={`suggest-${label.replace(/\W/g, "")}`}
            className="suggest"
            role="listbox"
          >
            {suggestions.map((s, i) => (
              <li
                key={`${s.lat}-${s.lon}-${i}`}
                role="option"
                aria-selected={i === activeIdx}
                className={i === activeIdx ? "suggest-item active" : "suggest-item"}
                onMouseDown={(e) => {
                  e.preventDefault();
                  pick(s);
                }}
              >
                {s.short_name}
                <span className="suggest-sub">{s.name}</span>
              </li>
            ))}
          </ul>
        )}
      </span>
    </label>
  );
}