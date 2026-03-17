# Windows Host Prep for NUC WSL2 Move (2026-03-16)

These scripts are for the **Windows host side** of the NUC migration.

## Why this folder exists

The portable core will run inside **WSL2**, but some setup still has to happen on the
Windows host:

- register a scheduled task to start the WSL runtime after login
- test the runtime immediately from PowerShell
- expose the API/dashboard to the tailnet via Tailscale

## Why the current VNC workflow helps

Because you already **VNC into the NUC**, the simplest first-stage automation path is:

1. reboot the NUC if needed
2. VNC in
3. sign into Windows
4. let the **logon task** start the WSL runtime

This is easier and lower-risk than trying to perfect a fully headless Windows boot path
before the first cutover.

## Scripts

### 1) Register the logon task

Run in an elevated PowerShell session on the NUC:

```powershell
.\register-claude-wsl-logon-task.ps1 -DistroName Ubuntu -LinuxUser jim -RunDoctor
```

This creates a task named **Claude WSL Runtime (Logon)** that runs:

```bash
~/.claude/scripts/wsl2-start-runtime.sh --doctor
```

inside WSL after Windows login.

### 2) Run the runtime now

Useful for testing immediately over VNC:

```powershell
.\run-claude-wsl-runtime-now.ps1 -DistroName Ubuntu -LinuxUser jim -RunDoctor
```

### 3) Set up Tailscale serve on the NUC

Run once in PowerShell on the NUC:

```powershell
.\setup-claude-tailscale-serve.ps1
```

This configures:

```text
tailscale serve --bg 127.0.0.1:8765
```

so the WSL-hosted API/dashboard is reachable over the tailnet.

## Remote access posture

- **Primary:** Tailscale
- **Admin fallback / first-setup tool:** VNC
- **Cloudflare:** keep as manual backup only, not always-on primary

## WSL-side counterpart scripts

These are called from Windows but live in the Linux home:

- `~/.claude/scripts/wsl2-start-runtime.sh`
- `~/.claude/scripts/wsl2-stop-runtime.sh`
- `~/.claude/scripts/wsl2-doctor.py`

## After running the Windows-side setup

From inside WSL, use:

```bash
python3 ~/.claude/scripts/wsl2-doctor.py --require-running --with-smoke
```

That is the best "am I actually ready?" check before you trust the NUC cutover.
