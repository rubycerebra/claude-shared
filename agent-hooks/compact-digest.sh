#!/usr/bin/env bash
# compact-digest.sh — PreCompact hook
# Generates a structured digest of session activity to survive conversation
# compaction. Injects via additionalContext so the model does not re-read
# files it already processed.
#
# Data sources:
#   1. /tmp/circuit-breaker-${PPID}.json (file_reads, bash_retries)
#   2. git diff --name-only HEAD (modified files)
#   3. /tmp/bead-*-${PPID}* (active bead state)
#
# Fail gracefully — never block compaction
trap 'exit 0' ERR

# Consume stdin (Claude Code passes JSON payload)
INPUT=""
if [ ! -t 0 ]; then
  INPUT=$(cat)
fi

python3 - "$PPID" "$INPUT" << 'PYEOF'
import json
import sys
import os
import subprocess
import glob

def main():
    ppid = sys.argv[1]

    sections = []

    # --- 1. Circuit breaker state (files read this session) ---
    cb_file = f"/tmp/circuit-breaker-{ppid}.json"
    files_read = []
    bash_commands = 0

    if os.path.exists(cb_file):
        try:
            with open(cb_file, "r") as f:
                cb = json.load(f)

            fr = cb.get("file_reads", {})
            if fr:
                sorted_reads = sorted(fr.items(), key=lambda x: -x[1])[:30]
                paths = [p for p, _ in sorted_reads]
                files_read = paths
                section = "Files read this session ({} total):".format(len(fr))
                for p in paths:
                    section += "\n  " + p
                if len(fr) > 30:
                    section += "\n  ... and {} more".format(len(fr) - 30)
                sections.append(section)

            br = cb.get("bash_retries", {})
            if br:
                bash_commands = sum(br.values())
        except Exception:
            pass

    # --- 2. Fallback: scan /tmp for session state files ---
    if not files_read:
        pattern = f"/tmp/*{ppid}*"
        tmp_files = glob.glob(pattern)
        if tmp_files:
            state_files = [f for f in tmp_files if os.path.isfile(f)]
            if state_files:
                sections.append("Session state files found: " + ", ".join(
                    os.path.basename(f) for f in state_files[:10]
                ))

    # --- 3. Git modified files ---
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd=os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
        )
        if result.returncode == 0 and result.stdout.strip():
            modified = result.stdout.strip().split("\n")
            modified = [m for m in modified if m.strip()]
            if modified:
                section = "Files modified (git diff HEAD, {} files):".format(len(modified))
                for m in modified[:20]:
                    section += "\n  " + m
                if len(modified) > 20:
                    section += "\n  ... and {} more".format(len(modified) - 20)
                sections.append(section)
    except Exception:
        pass

    # --- 4. Bead state ---
    bead_pattern = f"/tmp/bead-*-{ppid}*"
    bead_files = glob.glob(bead_pattern)
    if not bead_files:
        bead_pattern = "/tmp/bead-*"
        bead_files = [f for f in glob.glob(bead_pattern) if os.path.isfile(f)]

    if bead_files:
        bead_info = []
        for bf in bead_files[:5]:
            try:
                with open(bf, "r") as fh:
                    content = fh.read(200).strip()
                bead_info.append(os.path.basename(bf) + ": " + content[:100])
            except Exception:
                bead_info.append(os.path.basename(bf))
        if bead_info:
            sections.append("Active bead state:\n  " + "\n  ".join(bead_info))

    # --- 5. Compose digest ---
    if not sections:
        return

    digest = "SESSION DIGEST (pre-compaction):\n"
    digest += "\n".join(sections)
    digest += "\n\nDo NOT re-read these files -- use the content you already have."
    if bash_commands > 0:
        digest += "\n{} bash commands were attempted this session.".format(bash_commands)

    # Truncate to ~2K chars
    if len(digest) > 2000:
        digest = digest[:1997] + "..."

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreCompact",
            "additionalContext": digest
        }
    }
    print(json.dumps(output))

try:
    main()
except Exception:
    pass
PYEOF
