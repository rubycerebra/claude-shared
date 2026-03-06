# 🧠 claude-shared

This folder is now split by purpose.

## Keep at root

Only keep files here if they are:

- shared context used across projects
- dashboard generators / outputs
- current Codex prompts
- current weekly summaries you actively read

Examples:

- `journal/`
- `wins.md`
- `patterns.md`
- `mental-health-insights.md`
- `context-bridge.md`
- `PERSONAL-PREFERENCES-v3.md`
- `generate-dashboard.py`
- `dashboard.html`
- `CODEX-PROMPT-*.md`

## New homes

- `guides/` → integration notes, MCP rules, sync docs
- `reports/` → dated audits, status write-ups, system reviews
- `setup-notes/` → older setup instructions and setup-era status docs

### Auto-routing

The weekly tidy script also auto-files dated shared status-style docs into:

- `reports/auto/YYYY-MM/`

## Rule of thumb

- If it is **project-specific**, do **not** put it here.
- If it is **shared and current**, keep it here.
- If it is **shared but historical**, move it into a subfolder.
