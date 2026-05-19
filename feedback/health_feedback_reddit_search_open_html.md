---
name: Reddit search — auto-open HTML
description: After reddit-search completes, auto-open the HTML file in browser and offer Finder fallback link
type: feedback
metadata:
  node_type: memory
  type: feedback
  project: HEALTH
  source_file: feedback_reddit_search_open_html.md
  migrated_on: 2026-05-17
---

After `/reddit-search` completes, always `open` the generated HTML file so it launches in the browser automatically. If that fails, provide a `open ~/Documents/Claude\ Projects/claude-shared/shopping/` command as fallback.

**Why:** Jim wants to see the results immediately without hunting for the file.
**How to apply:** Add `open <html-path>` as the final step of every reddit-search run.
