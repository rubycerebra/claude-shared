---
name: Work Template Styling Standard
description: Internal WORK HTML templates (handovers, session notes, reports) use dashboard dark theme. External templates (invoices, client comms) do not.
type: feedback
originSessionId: 2817776d-5ead-4218-9bd2-cfd036b1a928
metadata:
  node_type: memory
  type: feedback
  project: WORK
  source_file: feedback_template_styling.md
  migrated_on: 2026-05-17
---
Internal-only HTML templates — handovers, session notes, canvases, reports for Jim's own use — must use the dashboard visual system.

**Rule:** Apply the full styled template format to internal templates only. External-facing documents (invoices, client emails, anything sent outside) should use clean, neutral, professional styling instead.

**Why:** AuDHD/dyslexia — colour-coded sections reduce cognitive load. Consistent visual language across all WORK output.

**How to apply:** Follow `.helpers/template-standards.md` for exact colours, border rules, layout, and the header block. Reference template at `.helpers/handover-email-template.html`.

Key rules:
- Dark background (`#0f1117` / `#111827`)
- 3px solid full borders, section-differentiated colours (mint=win, amber=issue, purple=locked specs, sky=notes, slate=status)
- Header always mint `#45CC90`
- All styles inline — email client safe
- Max width 620px centred
