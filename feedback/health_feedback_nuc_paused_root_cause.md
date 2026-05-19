---
name: NUC claude-api PAUSED root cause and fix
description: Root cause of recurring STATE 7 PAUSED on NUC claude-api service, and the fix pattern
type: feedback
originSessionId: 47cd2249-9cc4-4c50-91e2-f3517f61882f
metadata:
  node_type: memory
  type: feedback
  project: HEALTH
  source_file: feedback_nuc_paused_root_cause.md
  migrated_on: 2026-05-17
---
When claude-api shows STATE 7 PAUSED, the root cause is almost always an orphaned python.exe holding port 8765 that `taskkill /FI "SERVICES eq claude-api"` misses.

**Why:** `taskkill /FI "SERVICES eq ..."` only kills processes still registered under that service name. Once a python.exe drifts from NSSM's process tracking (e.g. from a prior restart that killed NSSM's tracked child but not its grandchild), the filter misses it. The new process starts, hits `[Errno 10048] EADDRINUSE`, crashes in <30s, NSSM AppThrottle fires, service goes PAUSED. ServiceWatchdog (every 5 min) repeats the cycle indefinitely.

**How to apply:** Always kill by port holder explicitly, not just by service name.

Immediate recovery:
```bash
# 1. Find and kill the orphan
sshpass -p 'Trekbike21' ssh "James Cherry"@100.73.88.14 \
  "powershell -Command \"(netstat -ano | Select-String ':8765.*LISTENING').ToString().Trim().Split()[-1]\" | xargs -I{} sshpass -p 'Trekbike21' ssh 'James Cherry'@100.73.88.14 'taskkill /F /PID {} /T'"
# Simpler: kill by known PID
sshpass -p 'Trekbike21' ssh "James Cherry"@100.73.88.14 "taskkill /F /PID <orphan_pid> /T"
# 2. Start service
sshpass -p 'Trekbike21' ssh "James Cherry"@100.73.88.14 "sc.exe start claude-api"
```

**Permanent fixes applied 2026-05-08:**
- `run-ServiceWatchdog.ps1` — `Kill-PortHolder 8765` added after service-name taskkill
- `restart-claude-api.ps1` — same, sleep increased 3s → 10s
- `nuc-daemon-recovery.sh` — netstat port-kill in RESTART_CMD and PAUSED_RECOVER
- `api_server/app.py` — port-kill block inside try: before uvicorn.run (NUC line ~11193)
- NSSM AppRestartDelay — 5000ms → 15000ms
