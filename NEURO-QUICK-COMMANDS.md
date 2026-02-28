# Neuro Quick Commands

Simple commands with clear outcomes.
Use these instead of long chains.

## 1) See System State

```bash
~/.claude/scripts/neuro-ops.sh status
```

What it shows:
- daemon running or not
- API healthy or not
- cache freshness
- open bead counts in HEALTH / WORK / TODO
- next best command

## 2) Self-Heal Startup Services

```bash
~/.claude/scripts/neuro-ops.sh heal
~/.claude/scripts/neuro-ops.sh heal --wait 25
```

What it does:
- uses LaunchAgents to recover daemon + API if either is down
- waits briefly and confirms healthy state

## 3) Force Refresh Everything

```bash
~/.claude/scripts/neuro-ops.sh refresh
```

What it does:
- calls API `/v1/refresh`
- regenerates dashboard HTML

Use this when dashboard looks stale.

## 4) Open Dashboard in the Right Focus Mode

```bash
~/.claude/scripts/neuro-ops.sh open morning
~/.claude/scripts/neuro-ops.sh open day
~/.claude/scripts/neuro-ops.sh open evening
~/.claude/scripts/neuro-ops.sh open all
~/.claude/scripts/neuro-ops.sh open day --low-stim
~/.claude/scripts/neuro-ops.sh open day --compact
~/.claude/scripts/neuro-ops.sh open day --low-stim --compact
```

What it does:
- regenerates dashboard
- opens it with the selected focus mode

Dashboard shortcuts:
- `1` All
- `2` Morning
- `3` Day
- `4` Evening
- `5` Compact toggle

## 5) Therapy Summary Capture (Spark)

```bash
~/.claude/scripts/spark-therapy.sh
```

Flow:
1. Copy Spark summary to clipboard
2. Run command
3. It writes to today's journal under `## Therapy`

## 6) One-Command Morning Start

```bash
~/.claude/scripts/morning-start.sh
~/.claude/scripts/morning-start.sh --low-stim
~/.claude/scripts/morning-start.sh --compact
~/.claude/scripts/morning-start.sh --low-stim --compact
```

Flow:
1. Startup self-heal (daemon/API)
2. Status snapshot
3. Beads integrity watchdog
4. Refresh pipeline
5. Open dashboard in morning focus

## 7) Beads Integrity Watchdog

```bash
~/.claude/scripts/beads-integrity-watchdog.py
~/.claude/scripts/beads-integrity-watchdog.py --quiet
```

What it checks:
- `bd` open count vs `.beads/issues.jsonl` latest-open count
- duplicate open titles
- parse/file integrity issues

## 8) API Token Lifecycle

```bash
~/.claude/scripts/api-token-manager.py status
~/.claude/scripts/api-token-manager.py health
~/.claude/scripts/api-token-manager.py rotate
```

Use `rotate` if token exposure is suspected. It rotates and restarts API LaunchAgent.

## 9) Weekly Beads Hygiene

```bash
~/.claude/scripts/weekly-beads-hygiene.py
```

Creates a weekly markdown report and opens a TODO follow-up bead if issues are found.

## 10) Start API Server (if status shows unavailable)

```bash
~/.claude/scripts/start-api-server.sh
```

## 11) Restart Daemon (if status shows not running)

```bash
~/.claude/scripts/restart-daemon.sh
```

## 12) Dashboard Regression Checks

```bash
~/.claude/scripts/dashboard-contract-tests.py
~/.claude/scripts/dashboard-contract-tests.py --update-baseline
```

## Optional aliases (zsh)

Add to `~/.zshrc`:

```bash
alias nops='~/.claude/scripts/neuro-ops.sh'
alias nstatus='~/.claude/scripts/neuro-ops.sh status'
alias nheal='~/.claude/scripts/neuro-ops.sh heal'
alias nrefresh='~/.claude/scripts/neuro-ops.sh refresh'
alias nmorning='~/.claude/scripts/neuro-ops.sh open morning'
alias nday='~/.claude/scripts/neuro-ops.sh open day'
alias nevening='~/.claude/scripts/neuro-ops.sh open evening'
```

Then run:

```bash
source ~/.zshrc
```
