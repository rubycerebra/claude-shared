# NUC Remote Access Plan

**Goal:** Open phone → see dashboard + browse/edit project files. No GitHub. 100% local via always-on NUC.

## Current State

- Tailscale mesh VPN already active: Mac, NUC (Windows), iPhone, iPad
- NUC is `100.73.88.14` (direct connection, always-on)
- Dashboard API already serves on port 8765
- Tailscale Serve already planned for NUC (PowerShell script exists)

## Recommended Stack

### Layer 1: Network — Tailscale (already done)
No work needed. Phone app installed, NUC online. All traffic encrypted, no port forwarding.

### Layer 2: Dashboard — Tailscale Serve → port 8765
One command on the NUC to expose the dashboard API:
```
tailscale serve --bg 8765
```
Then from phone: `https://nuc.tail649c3c.ts.net/app` → full dashboard.

### Layer 3: File Editing — Code-server (recommended)
**Why code-server over alternatives:**
- Full VS Code in the browser — familiar, powerful, works on phone
- Built-in terminal for Claude Code access
- Single binary, ~100MB, runs on Windows/WSL2
- Extensions work (except Remote Development, Live Share, Copilot)
- Responsive on mobile, even on 3G
- Active project: github.com/coder/code-server

**Alternative considered: FileBrowser**
- Lighter (single binary, ~10MB)
- Good for file browsing/uploading/downloading
- Has a built-in text editor but basic (no syntax highlighting, no terminal)
- Better as a companion alongside code-server, not a replacement

**Alternative considered: Tailscale SSH + mobile terminal app**
- Works but phone keyboard + CLI is painful for editing
- Fine for quick commands, not for real file editing

### Layer 4: Claude Code — via code-server terminal
- Open code-server on phone → open terminal → run `claude`
- No need for `/remote` (which requires desktop session to stay open)
- Code-server terminal IS the persistent session on the NUC

## Setup Steps (on NUC, in WSL2)

### 1. Install code-server
```bash
curl -fsSL https://code-server.dev/install.sh | sh
```

### 2. Configure
```bash
# ~/.config/code-server/config.yaml
bind-addr: 127.0.0.1:8080
auth: password
password: <generate-strong-password>
cert: false
```

### 3. Expose via Tailscale Serve
```bash
tailscale serve --bg --https 8080
```

### 4. Expose dashboard API
```bash
tailscale serve --bg --https=443 --set-path /api http://127.0.0.1:8765
```

### 5. Phone bookmarks
- Dashboard: `https://nuc.tail649c3c.ts.net/app`
- Code editor: `https://nuc.tail649c3c.ts.net:8080`

## Security
- Tailscale ACLs restrict access to your devices only
- Code-server has its own password auth
- No ports exposed to public internet
- All traffic encrypted (WireGuard)

## Optional: Landing page
A simple HTML page on the NUC with links to dashboard + code-server + any other tools. Serve on port 80 via Tailscale Serve for a clean `https://nuc/` bookmark.

## Dependencies
- WSL2 running on NUC (TODO-3pyn.1 — portability hardening)
- Tailscale installed in WSL2 (or use Windows Tailscale with port forwarding to WSL2)
- Claude Code installed in WSL2

## Blocked by
- TODO-3pyn.1: NUC portability hardening package (WSL2 must be bootstrapped first)
- The WSL2 bootstrap needs to happen ON the NUC physically or via VNC
