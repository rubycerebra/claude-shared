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
    return "\n".join(lines)
