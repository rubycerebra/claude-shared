# Device Contract

## Canonical roles
- **NUC / Windows**: authoritative always-on runtime, canonical writer for daemon/API/cache surfaces
- **Mac / Darwin**: interface, bridge, overlay, and local operator workflows

## Hard rules
- `~/.claude/cache/session-data.json` is NUC-owned canonical cache
- Mac may read canonical cache and may write only approved overlays/bridge outputs
- No active-active writes to the same synced runtime file
- Shared business logic can be unified; runtime/service adapters stay device-specific

## Service control
- NUC: scheduled-task / Windows-safe control only
- Mac: local bridge/interface flows only
