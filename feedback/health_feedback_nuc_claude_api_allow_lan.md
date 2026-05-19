---
name: NUC API CLAUDE_API_ALLOW_LAN requirement
description: NUC claude-api NSSM service requires CLAUDE_API_ALLOW_LAN=1 env var or it binds to 127.0.0.1 only, blocking all external/Mac access
type: feedback
originSessionId: ff81eca7-d127-457a-958b-049d92f74e90
metadata:
  node_type: memory
  type: feedback
  project: HEALTH
  source_file: feedback_nuc_claude_api_allow_lan.md
  migrated_on: 2026-05-17
---
After any NSSM service reset or LocalSystem migration, `claude-api` binds to `127.0.0.1:8765` by default — connection refused from Mac.

Fix: `nssm set claude-api AppEnvironmentExtra "CLAUDE_API_ALLOW_LAN=1"` then restart.

**Why:** api-server.py line 840: `return "0.0.0.0" if _env_truthy("CLAUDE_API_ALLOW_LAN") else "127.0.0.1"`. Without the env var, only loopback is bound.

**How to apply:** After any NUC NSSM service reset/migration, check this env var is set. Verify with `curl -o /dev/null -w "%{http_code}" http://100.73.88.14:8765/health` — should return 200, not connection refused.

Note: `/v1/internal/health-export` may also have IP-based auth that blocks non-localhost even with correct token. If 401 persists after token sync, check this endpoint's auth logic in api-server.py.
