---
name: NUC NSSM services must run as LocalSystem with HOME env set
description: Both claude-api and claude-daemon were configured to run as .\James Cherry; password expiry caused logon failure (1069) on restart. Fixed to LocalSystem + USERPROFILE override.
type: feedback
originSessionId: 33870f04-c5d9-4935-923b-6e4940a46480
metadata:
  node_type: memory
  type: feedback
  project: HEALTH
  source_file: feedback_nuc_nssm_localsystem.md
  migrated_on: 2026-05-17
---
Both NUC NSSM services (claude-api, claude-daemon) were originally configured with `ObjectName = .\James Cherry`. Windows password expiry (default 42 days) caused error 1069 on any restart attempt. Services kept running continuously until a force-kill exposed the issue (2026-05-02).

**Fix applied:**
1. `nssm set claude-api ObjectName LocalSystem`
2. `nssm set claude-daemon ObjectName LocalSystem`
3. Set ALL env vars via PowerShell registry (USERPROFILE + CLAUDE_API_ALLOW_LAN):
```powershell
Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\claude-api\Parameters' -Name 'AppEnvironmentExtra' -Value @('CLAUDE_API_ALLOW_LAN=1', 'USERPROFILE=C:\Users\James Cherry') -Type MultiString
```

**Why:** LocalSystem has no `USERPROFILE` pointing to James Cherry's home, so Python's `Path.home()` resolves to `C:\Windows\System32\config\systemprofile\` and reads a stale/wrong token file. Without `CLAUDE_API_ALLOW_LAN=1`, the API binds to 127.0.0.1 only.

**CRITICAL: AppEnvironmentExtra REPLACES, not appends.** `nssm set <svc> AppEnvironmentExtra "FOO=1"` wipes ALL existing env vars and sets only FOO. Always include every required var in a single call. On 2026-05-02, setting only CLAUDE_API_ALLOW_LAN=1 wiped USERPROFILE, causing health-export 401 (wrong token file path).

**How to apply:** If either NUC service ever fails with 1069 or stops unexpectedly after a restart, check `nssm get <service> ObjectName` first. If it shows a user account, apply this pattern. Always verify AppEnvironmentExtra contains ALL required vars after any change.
