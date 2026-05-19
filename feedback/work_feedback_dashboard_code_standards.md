---
name: dashboard-code-standards
description: Design system rules and common violations to check when editing any dashboard component (WorkTab, HealthTab, NowTab, etc.). Eliminates need for a design review after every edit.
type: feedback
originSessionId: b66c32e7-b6e8-4b70-a0cd-0bc85bb0e507
metadata:
  node_type: memory
  type: feedback
  project: WORK
  source_file: feedback_dashboard_code_standards.md
  migrated_on: 2026-05-17
---
Apply these checks to every dashboard component edit. Catch violations before deploy, not after.

**Why:** Running a design review after every edit wastes a full session cycle. These are the recurring violations found in the dashboard codebase.

**How to apply:** Before declaring a dashboard edit done, scan the changed file for each item below.

---

## Colours — use CSS vars, never hardcoded hex

| Wrong | Right |
|---|---|
| `#45CC90` | `var(--accent)` |
| `#f87171` | `var(--semantic-red)` |
| `#b8c5d6` | `var(--muted)` or `var(--text-secondary)` |
| `rgba(248,113,113,...)` | `var(--semantic-red-border)` / `var(--semantic-red-bg)` |
| `rgba(69,204,144,...)` | `var(--accent-border)` / `var(--accent-muted)` |

Spectrum colours (`spectrumStyle().text/border/bg`) are dynamic — inline is correct for those.

---

## Typography — use CSS vars, never px font sizes

| Wrong | Right |
|---|---|
| `fontSize: 11` | `var(--text-caption)` (0.88rem) |
| `fontSize: 12` | `var(--text-sm)` (0.92rem) |
| `fontSize: 13` | `var(--text-sm)` (0.92rem) |
| `fontSize: 15` | `var(--text-base)` (1.02rem) |
| `fontSize: 16` | `var(--text-md)` (1.12rem) |

Type scale: `--text-caption` → `--text-sm` → `--text-base` → `--text-md` → `--text-lg` → `--text-xl`

---

## Borders

- **Outer card (Section/os-card):** `3px solid` — uses `--border-card`
- **Inner card (os-card nested):** `borderLeft: 3px solid ${spectrum.border}` — dynamic colour is fine
- **Icon boxes:** `2px solid` — not 1px
- **Border opacity:** rgba borders must be ≥ 0.4 opacity. Check `rgba(r,g,b,X)` where X < 0.4

---

## Icon placement in sub-sections

The icon box must be in its OWN header row, never wrapping a component that expands content.

```tsx
// CORRECT — Deliverables pattern
<div className="os-card">
  <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginBottom: 6 }}>
    <SubSectionIcon icon={Clipboard} sp={sp} />
    <span>Label</span>
  </div>
  {items.map(...)}   {/* content BELOW the header row */}
</div>

// WRONG — wrapping an expanding component in the icon flex row
<div style={{ display: 'flex', alignItems: 'center' }}>
  <SubSectionIcon ... />
  <ExpandableSection />  {/* expands vertically inside a horizontal flex — breaks layout */}
</div>
```

For collapsible sections (like TasksSection): pass the icon as a prop into the section's own header button, or render it as a sibling above — never alongside.

---

## Touch targets

- All buttons: minimum `padding: '6px 10px'` — target ≥ 44px rendered height
- Expand/collapse toggles: `padding: '6px 0'` minimum — not `'0 0 4px 0'`
- Disabled state: `opacity: 0.5`, `cursor: 'not-allowed'`

---

## Hover states

- `<a>` links: need hover background shift — use a CSS class or `onMouseEnter`/`onMouseLeave`
- Buttons that don't use `.btn--*` classes: add `transition: 'background 0.2s'` + hover class
- Interactive rows: subtle `background: rgba(255,255,255,0.03)` on hover is sufficient

---

## Layout gotchas

- Trailing `marginBottom` on the last child inside a card creates unwanted whitespace. Remove it, or apply `marginBottom` to the card itself.
- `flexWrap: 'wrap'` on actions rows: lone items that wrap to a second line look odd. Test mentally with 1-item wrap.
- Never put an expanding/collapsible component inside a `display: flex, alignItems: 'center'` wrapper.

---

## Prefers-reduced-motion

Global wildcard in styles.css: `* { transition: none !important; animation: none !important; }` covers all components. No need to add per-component media queries. ✓

---

## Pre-deploy checklist (run mentally before every dashboard edit)

1. Any `#45CC90`, `#f87171`, `#b8c5d6`, or raw `rgba()` for semantic colours? → replace with vars
2. Any `fontSize: 11/12/13/15/16`? → replace with CSS var
3. Any icon box with `border: '1px solid'`? → 2px
4. Any expandable content inside a flex `alignItems: 'center'` wrapper? → pull out
5. Any button with `padding` < 6px vertical? → bump up
6. Any `<a>` link without hover feedback? → add class or transition
7. Any trailing `marginBottom` inside the last child of a card? → remove
