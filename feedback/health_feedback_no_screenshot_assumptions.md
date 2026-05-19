---
name: No screenshot assumptions
description: Never claim fixes are verified from screenshots alone — read actual API data programmatically to verify data-level changes
type: feedback
metadata:
  node_type: memory
  type: feedback
  project: HEALTH
  source_file: feedback_no_screenshot_assumptions.md
  migrated_on: 2026-05-17
---

Never claim dashboard fixes are "verified" based on Playwright screenshots alone. Screenshots are too small to read text reliably, leading to confabulation (filling gaps with expected results).

**Why:** Session 2026-03-27 — three code fixes were made but none actually worked in the browser. Claude reported them as "verified working in Playwright" by misreading tiny screenshots. Jim spent over an hour debugging what Claude claimed was already fixed. Root causes were: curly apostrophe vs straight apostrophe mismatch, case-sensitive type comparison (todo vs TODO), and sentence-splitting extracting noise from long Todoist tasks.

**How to apply:**
1. After data-level changes (noise filters, categorisation, strikethrough logic), verify by querying the API endpoint directly with Python (`/v1/ui/app/today`) and printing the actual data
2. Screenshots are for **layout verification only** — not for confirming whether specific text items appear or are styled correctly
3. If you can't read a screenshot clearly, say "I can't confirm from this screenshot" — never guess
4. Check for Unicode variants (curly quotes, em dashes, smart quotes) when writing regex patterns against user-generated text
5. Always check API response field types (case sensitivity, data shapes) before writing comparison code
