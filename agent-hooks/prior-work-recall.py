#!/usr/bin/env python3
"""prior-work-recall — UserPromptSubmit hook
Searches QMD sessions + plans for prior work related to the current prompt.
Tiered response:
  score >= 0.82 → STOP: likely already done, halt and present context
  score >= 0.65 → context injection, proceed with awareness
"""
import json, sys, os, subprocess, re, tempfile

try:
    payload = json.load(sys.stdin)
except Exception:
    print(json.dumps({})); sys.exit(0)

# Per-session firing cap: max 3 times to avoid flooding context
current_session = os.environ.get("CLAUDE_SESSION_ID", "unknown")
cap_file = os.path.join(tempfile.gettempdir(), f"prior_work_recall_{current_session[:12]}.count")
try:
    count = int(open(cap_file).read().strip()) if os.path.exists(cap_file) else 0
except Exception:
    count = 0
if count >= 3:
    print(json.dumps({})); sys.exit(0)

prompt = ""
for block in payload.get("message", {}).get("content", []):
    if isinstance(block, dict) and block.get("type") == "text":
        prompt += block.get("text", "")

prompt = prompt.strip()
if len(prompt) < 20 or prompt.startswith("/"):
    print(json.dumps({})); sys.exit(0)

# Truncate to first sentence or 120 chars for better qmd score relevance
# Long conversational prompts dilute semantic similarity below threshold
search_query = prompt
first_sentence_end = re.search(r'[.!?]', prompt)
if first_sentence_end:
    search_query = prompt[:first_sentence_end.start()].strip()
if len(search_query) > 120:
    search_query = search_query[:120]
if len(search_query) < 20:
    search_query = prompt[:120]

first_word = prompt.split()[0].lower().rstrip(".,!?")
if first_word in ("yes", "no", "ok", "sure", "done", "continue", "thanks", "yeah", "nope", "cool"):
    print(json.dumps({})); sys.exit(0)

current_session = os.environ.get("CLAUDE_SESSION_ID", "")

def qmd_search(collection, query, limit=3):
    try:
        result = subprocess.run(
            ["qmd", "vsearch", "-c", collection, "--json", "-n", str(limit), query],
            capture_output=True, text=True, timeout=8
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except Exception:
        pass
    return []

sessions_hits = qmd_search("sessions", search_query)
plans_hits = qmd_search("plans", search_query)

all_hits = []

for hit in sessions_hits:
    score = hit.get("score", 0)
    if score < 0.65:
        continue
    file_path = hit.get("file", "")
    # skip current session
    if current_session and current_session[:8] in file_path:
        continue
    title = hit.get("title") or os.path.basename(file_path)
    date_match = re.search(r"(\d{4}-\d{2}-\d{2})", file_path)
    date = date_match.group(1) if date_match else ""
    all_hits.append({"type": "session", "score": score, "title": title, "date": date})

for hit in plans_hits:
    score = hit.get("score", 0)
    if score < 0.65:
        continue
    title = hit.get("title") or os.path.basename(hit.get("file", ""))
    all_hits.append({"type": "plan", "score": score, "title": title, "date": ""})

if not all_hits:
    print(json.dumps({})); sys.exit(0)

all_hits.sort(key=lambda x: x["score"], reverse=True)
best = all_hits[0]

lines = []
for h in all_hits:
    label = "session" if h["type"] == "session" else "plan"
    date_str = f" ({h['date']})" if h["date"] else ""
    lines.append(f"  • {label}: {h['title']}{date_str} — {h['score']:.2f}")

if best["score"] >= 0.74:
    context = (
        "🛑 STOP — PRIOR WORK DETECTED\n"
        f"The user's request closely matches existing work (score {best['score']:.2f}).\n"
        "DO NOT proceed with implementation. Instead:\n"
        "1. Show the user the matches below\n"
        "2. Ask if they want to load the context via /context <label>\n"
        "3. Only continue if they confirm this is genuinely new work\n\n"
        "Matches:\n" + "\n".join(lines)
    )
else:
    context = (
        "📎 Related prior work found — review before starting:\n"
        + "\n".join(lines)
        + "\nUse /context <label> to load full details."
    )

# Increment the per-session firing counter
try:
    open(cap_file, "w").write(str(count + 1))
except Exception:
    pass

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": context
    }
}))
