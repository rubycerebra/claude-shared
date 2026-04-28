"""Local utility CSS for the standalone dashboard.

Keeps the generated HTML self-contained and removes the runtime Tailwind CDN
dependency while preserving the small subset of utility classes the dashboard
actually uses.
"""

from __future__ import annotations


UTILITY_RULES = {
    "block": "display:block;",
    "flex": "display:flex;",
    "grid": "display:grid;",
    "flex-1": "flex:1 1 0%;",
    "flex-col": "flex-direction:column;",
    "flex-wrap": "flex-wrap:wrap;",
    "flex-shrink-0": "flex-shrink:0;",
    "items-center": "align-items:center;",
    "items-start": "align-items:flex-start;",
    "justify-between": "justify-content:space-between;",
    "text-left": "text-align:left;",
    "text-right": "text-align:right;",
    "text-center": "text-align:center;",
    "font-medium": "font-weight:500;",
    "font-semibold": "font-weight:600;",
    "font-bold": "font-weight:700;",
    "font-mono": 'font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;',
    "text-base": "font-size:1rem; line-height:1.5rem;",
    "text-xl": "font-size:1.25rem; line-height:1.75rem;",
    "text-2xl": "font-size:1.5rem; line-height:2rem;",
    "text-3xl": "font-size:1.875rem; line-height:2.25rem;",
    "rounded": "border-radius:0.25rem;",
    "rounded-lg": "border-radius:0.5rem;",
    "rounded-xl": "border-radius:0.75rem;",
    "rounded-2xl": "border-radius:1rem;",
    "rounded-full": "border-radius:9999px;",
    "overflow-hidden": "overflow:hidden;",
    "truncate": "overflow:hidden; text-overflow:ellipsis; white-space:nowrap;",
    "object-cover": "object-fit:cover;",
    "w-full": "width:100%;",
    "w-32": "width:8rem;",
    "w-28": "width:7rem;",
    "w-14": "width:3.5rem;",
    "w-12": "width:3rem;",
    "w-10": "width:2.5rem;",
    "w-8": "width:2rem;",
    "w-4": "width:1rem;",
    "w-3.5": "width:0.875rem;",
    "w-3": "width:0.75rem;",
    "h-full": "height:100%;",
    "h-4": "height:1rem;",
    "h-3.5": "height:0.875rem;",
    "h-3": "height:0.75rem;",
    "h-2": "height:0.5rem;",
    "gap-1": "gap:0.25rem;",
    "gap-1.5": "gap:0.375rem;",
    "gap-2": "gap:0.5rem;",
    "gap-3": "gap:0.75rem;",
    "gap-4": "gap:1rem;",
    "p-2": "padding:0.5rem;",
    "p-3": "padding:0.75rem;",
    "p-4": "padding:1rem;",
    "p-5": "padding:1.25rem;",
    "px-1.5": "padding-left:0.375rem; padding-right:0.375rem;",
    "px-2": "padding-left:0.5rem; padding-right:0.5rem;",
    "px-3": "padding-left:0.75rem; padding-right:0.75rem;",
    "px-4": "padding-left:1rem; padding-right:1rem;",
    "py-0.5": "padding-top:0.125rem; padding-bottom:0.125rem;",
    "py-1": "padding-top:0.25rem; padding-bottom:0.25rem;",
    "py-1.5": "padding-top:0.375rem; padding-bottom:0.375rem;",
    "py-2": "padding-top:0.5rem; padding-bottom:0.5rem;",
    "py-2.5": "padding-top:0.625rem; padding-bottom:0.625rem;",
    "py-3": "padding-top:0.75rem; padding-bottom:0.75rem;",
    "pt-2": "padding-top:0.5rem;",
    "pt-3": "padding-top:0.75rem;",
    "pt-4": "padding-top:1rem;",
    "mt-1": "margin-top:0.25rem;",
    "mt-2": "margin-top:0.5rem;",
    "mt-3": "margin-top:0.75rem;",
    "mt-4": "margin-top:1rem;",
    "mt-6": "margin-top:1.5rem;",
    "mb-1": "margin-bottom:0.25rem;",
    "mb-2": "margin-bottom:0.5rem;",
    "mb-3": "margin-bottom:0.75rem;",
    "mb-4": "margin-bottom:1rem;",
    "mb-5": "margin-bottom:1.25rem;",
    "ml-2": "margin-left:0.5rem;",
    "ml-auto": "margin-left:auto;",
    "min-w-0": "min-width:0;",
    "cursor-pointer": "cursor:pointer;",
    "grid-cols-1": "grid-template-columns:minmax(0, 1fr);",
}

RESPONSIVE_RULES = {
    "md:grid-cols-2": "grid-template-columns:repeat(2, minmax(0, 1fr));",
    "md:grid-cols-3": "grid-template-columns:repeat(3, minmax(0, 1fr));",
}

COMPLEX_SELECTORS = {
    ".space-y-1 > :not([hidden]) ~ :not([hidden])": "margin-top:0.25rem;",
    ".space-y-2 > :not([hidden]) ~ :not([hidden])": "margin-top:0.5rem;",
}


def _escape_class_name(class_name: str) -> str:
    return class_name.replace("\\", "\\\\").replace(":", "\\:").replace(".", "\\.")


COMPONENT_CSS = """
/* ── Buttons ── */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  height: 30px;
  padding: 0 14px;
  font-size: 12px;
  font-weight: 600;
  line-height: 1;
  border-radius: var(--radius-sm);
  cursor: pointer;
  touch-action: manipulation;
  white-space: nowrap;
  transition: background var(--transition-fast), border-color var(--transition-fast), transform var(--transition-fast);
}
.btn--sm { height: 24px; padding: 0 10px; font-size: 11px; min-width: 72px; }
.btn--xs { height: 22px; padding: 0 8px; font-size: 11px; }
.btn--flex { height: auto; min-height: 30px; padding: 5px 14px; }
.btn:active { transform: scale(0.97); }
.btn:disabled { opacity: 0.5; pointer-events: none; }

.btn--primary {
  background: rgba(69,204,144,0.15);
  color: var(--accent-soft);
  border: 1px solid var(--accent-border);
}
.btn--primary:hover { background: rgba(69,204,144,0.25); }

.btn--secondary {
  background: var(--bg-secondary);
  color: var(--text-primary);
  border: 1px solid var(--border-default);
}
.btn--secondary:hover { background: rgba(30,41,59,0.8); }

.btn--ghost {
  background: transparent;
  color: var(--text-secondary);
  border: 1px solid var(--border-subtle);
}
.btn--ghost:hover { background: var(--bg-secondary); color: var(--text-primary); }

.btn--danger {
  background: var(--semantic-red-bg);
  color: var(--semantic-red);
  border: 1px solid var(--semantic-red-border);
}
.btn--danger:hover { background: rgba(127,29,29,0.28); }

.btn--amber {
  background: var(--semantic-amber-bg);
  color: var(--semantic-amber);
  border: 1px solid var(--semantic-amber-border);
}
.btn--amber:hover { background: rgba(120,53,15,0.28); }

.btn--blue {
  background: rgba(30,64,175,0.15);
  color: var(--color-day);
  border: 1px solid rgba(147,197,253,0.2);
}
.btn--blue:hover { background: rgba(30,64,175,0.25); }

.btn--purple {
  background: var(--semantic-purple-bg);
  color: var(--semantic-purple);
  border: 1px solid var(--semantic-purple-border);
}
.btn--purple:hover { background: rgba(88,28,135,0.25); }

/* ── Todoist task rows ── */
.todo-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  margin-bottom: 5px;
  background: rgba(15,23,42,0.5);
  border: none;
  border-left: 3px solid rgba(148,163,184,0.35);
  border-radius: var(--radius-md);
  transition: background var(--transition-fast), border-color var(--transition-fast), transform var(--transition-fast), box-shadow var(--transition-fast);
}
.todo-row:hover {
  background: rgba(22,33,62,0.75);
  border-left-color: rgba(181,255,217,0.7);
  box-shadow: 0 2px 10px rgba(0,0,0,0.22);
  transform: translateY(-1px);
}
.todo-row--p1 { border-left-color: rgba(248,113,113,0.75); }
.todo-row--p2 { border-left-color: rgba(251,191,36,0.7); }
.todo-row--p3 { border-left-color: rgba(134,239,172,0.65); }

/* Checkbox — uses a styled <span> to avoid Safari <button> sizing issues */
.todo-check {
  width: 18px;
  height: 18px;
  min-width: 18px;
  flex-shrink: 0;
  border-radius: 50%;
  border: 2px solid rgba(69,204,144,0.65);
  background: transparent;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: transparent;
  font-size: 10px;
  transition: background 0.15s, border-color 0.15s, color 0.15s, transform 0.15s;
}
.todo-check:hover {
  border-color: var(--accent);
  background: rgba(69,204,144,0.15);
  color: var(--accent);
  transform: scale(1.15);
}
.todo-check:active { transform: scale(0.9); }
.todo-row--p1 .todo-check { border-color: rgba(248,113,113,0.7); }
.todo-row--p1 .todo-check:hover { border-color: #f87171; background: rgba(248,113,113,0.14); color: #f87171; }
.todo-row--p2 .todo-check { border-color: rgba(251,191,36,0.65); }
.todo-row--p2 .todo-check:hover { border-color: #fbbf24; background: rgba(251,191,36,0.12); color: #fbbf24; }

.todo-body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.todo-title { font-size: 0.85rem; font-weight: 500; color: var(--text-primary); line-height: 1.4; }
.todo-meta { display: flex; align-items: center; gap: 5px; flex-wrap: wrap; }

.todo-actions {
  display: flex;
  gap: 3px;
  flex-shrink: 0;
  align-items: center;
  opacity: 0.3;
  transition: opacity var(--transition-fast);
}
.todo-row:hover .todo-actions { opacity: 1; }
.todo-actions details { display: inline-flex; position: relative; }
.todo-actions details > summary { list-style: none; }
.todo-actions details > summary::-webkit-details-marker { display: none; }
.todo-act {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-subtle);
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}
.todo-act:hover { background: rgba(148,163,184,0.12); border-color: var(--border-default); }
.todo-act--schedule { color: var(--semantic-purple); border-color: var(--semantic-purple-border); }
.todo-act--schedule:hover { background: var(--semantic-purple-bg); }
.todo-act--open { color: var(--color-day); border-color: rgba(147,197,253,0.2); }
.todo-act--open:hover { background: rgba(30,64,175,0.15); }

/* ── Schedule popup ── */
.todo-schedule-popup {
  position: absolute;
  right: 0;
  top: calc(100% + 6px);
  min-width: 248px;
  padding: 8px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-elevated);
  z-index: 8;
}
.todo-schedule-quick {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 4px;
}
.todo-schedule-quick .btn { text-align: center; justify-content: center; }
.todo-schedule-divider { height: 1px; background: var(--border-default); margin: 8px 0; }
.todo-schedule-timeblock { display: flex; flex-direction: column; gap: 6px; }
.todo-schedule-timeblock-row { display: flex; gap: 6px; align-items: center; }
.todo-schedule-time,
.todo-schedule-duration {
  flex: 1;
  height: 26px;
  padding: 0 6px;
  font-size: 11px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-default);
  background: rgba(15,23,42,0.7);
  color: var(--text-primary);
  -webkit-appearance: none;
}
.todo-schedule-time:focus,
.todo-schedule-duration:focus { border-color: var(--semantic-purple-border); outline: none; }

@media (max-width: 640px) {
  .todo-row {
    flex-wrap: wrap;
    align-items: flex-start;
  }
  .todo-body {
    flex: 1 1 calc(100% - 28px);
  }
  .todo-actions {
    width: 100%;
    justify-content: flex-end;
    opacity: 1;
    padding-left: 28px;
  }
  .todo-schedule-popup {
    right: auto;
    left: 0;
    min-width: 0;
    width: min(calc(100vw - 2rem), 248px);
  }
}

@media (hover: none) and (pointer: coarse) {
  .todo-actions {
    opacity: 1;
  }
}

/* ── Pills / Badges ── */
.pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 3px;
  height: 20px;
  padding: 0 8px;
  font-size: 11px;
  font-weight: 600;
  line-height: 1;
  border-radius: 4px;
  white-space: nowrap;
  border: none;
  background: rgba(148,163,184,0.1);
  color: var(--text-secondary);
}
.pill--sm { height: 18px; padding: 0 6px; font-size: 10px; }
.pill--green  { background: var(--semantic-green-bg); color: var(--semantic-green); }
.pill--amber  { background: var(--semantic-amber-bg); color: var(--semantic-amber); }
.pill--red    { background: var(--semantic-red-bg); color: var(--semantic-red); }
.pill--purple { background: var(--semantic-purple-bg); color: var(--semantic-purple); }
.pill--blue   { background: rgba(30,64,175,0.15); color: var(--color-day); }

/* ── Semantic text colors ── */
.text-green  { color: var(--semantic-green) !important; }
.text-amber  { color: var(--semantic-amber) !important; }
.text-red    { color: var(--semantic-red) !important; }
.text-purple { color: var(--semantic-purple) !important; }
.text-blue   { color: var(--color-day) !important; }
.text-dim    { color: var(--text-secondary) !important; }

/* ── Type scale extensions ── */
.text-micro   { font-size: 0.65rem !important; line-height: 1.3; }
.text-caption  { font-size: 0.72rem !important; line-height: 1.4; }
body[data-compact="on"] .text-micro  { font-size: 0.6rem !important; }
body[data-compact="on"] .text-caption { font-size: 0.66rem !important; }

/* ── Inline pills (badges, tags) ── */
.inline-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
  min-height: 1.2rem;
  padding: 0.15rem 0.45rem;
  font-size: 0.65rem;
  font-weight: 600;
  border-radius: 9999px;
  white-space: nowrap;
}

/* ── Section headers (details/summary) ── */
.summary-section {
  font-size: 1.2rem;
  font-weight: 600;
  cursor: pointer;
  color: var(--text-primary);
  list-style: none;
}
.summary-section::-webkit-details-marker { display: none; }
.summary-sub {
  font-size: 0.88rem;
  font-weight: 600;
  cursor: pointer;
  color: var(--text-secondary);
}
"""


def build_dashboard_utility_css() -> str:
    lines: list[str] = []
    for class_name, rule in UTILITY_RULES.items():
        lines.append(f'.{_escape_class_name(class_name)} {{{rule}}}')
    for selector, rule in COMPLEX_SELECTORS.items():
        lines.append(f"{selector} {{{rule}}}")
    if RESPONSIVE_RULES:
        lines.append("@media (min-width: 768px) {")
        for class_name, rule in RESPONSIVE_RULES.items():
            lines.append(f'  .{_escape_class_name(class_name)} {{{rule}}}')
        lines.append("}")
    lines.append(COMPONENT_CSS)
    return "\n".join(lines)
