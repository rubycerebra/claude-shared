#!/bin/bash
# UserPromptSubmit — unified prompt skill detector
# Merges jim-skill-detect.sh (personal skills) + superpowers keyword matching.
# Jim's personal skill patterns take priority; superpowers patterns are fallback.

INPUT=""
if [ ! -t 0 ]; then
    INPUT=$(cat || true)
fi

PAYLOAD="$INPUT" python3 - <<'PY'
import json, os, sys, re

payload_str = os.environ.get("PAYLOAD", "") or "{}"
try:
    payload = json.loads(payload_str)
except Exception:
    sys.exit(0)

prompt = ""
if isinstance(payload, dict):
    prompt = payload.get("prompt", "")
    if not prompt:
        for block in payload.get("message", {}).get("content", []):
            if isinstance(block, dict) and block.get("type") == "text":
                prompt += block.get("text", "")

prompt = prompt.strip()
if not prompt or prompt.startswith("/"):
    sys.exit(0)

words = prompt.split()
if len(words) < 3:
    sys.exit(0)

first_word = words[0].lower().rstrip(".,!?")
if first_word in ("yes", "no", "ok", "sure", "done", "continue", "thanks",
                  "yeah", "nope", "cool", "great", "nice", "good", "perfect"):
    sys.exit(0)

p = prompt.lower()

# ── Jim's personal skill patterns (checked first) ────────────────────────────
PERSONAL = [
    (r"transcribe.{0,20}(diary|diar)|diary entry|morning entry|transcribe.{0,20}my.{0,20}(journal|notes)",
     "transcribe-diarium",
     "Use the `transcribe-diarium` skill (Skill tool) to process Jim's diary entry."),

    (r"\b(i watched|i've watched|i just watched|just watched|finished watching|mark.{0,20}as watched|mark.{0,20}watched)\b",
     "watched",
     "Use the `watched` skill (Skill tool) to log this film to Jim's Letterboxd watchlist."),

    (r"how (am i|is my day|is today going|are things today)|daily (status|check|rundown)|what.{0,10}(on today|have i got today|my day look)",
     "check-day",
     "Use the `check-day` skill (Skill tool) to show Jim's daily context."),

    (r"(load|recall|find|pull up|look for).{0,20}(session|conversation|context)|pick up where (we|i).{0,10}(left|stopped)|find.{0,30}work(ed)? on|what (was|were) (we|i) (doing|working|building)",
     "context",
     "Use the `/context` skill (Skill tool) to search and load the relevant prior session."),

    (r"(save|stamp|bookmark|label|tag).{0,10}(this session|this conversation)|remember this session",
     "id",
     "Use the `/id` skill (Skill tool) to stamp and save this session with a label."),

    (r"(feeling|i feel|i.m).{0,15}(stuck|overwhelmed|anxious|avoidant|frozen|paralysed|paralyzed)|pda.{0,10}(flare|mode|spike)|executive function|can.t (get started|begin|focus|concentrate)|don.t know where to start",
     "coach",
     "Jim needs coaching support. Invoke the `coach` skill (Skill tool) for regulation-first support."),

    (r"(cheapest|best price|where.{0,10}buy|find.{0,10}cheap).{0,30}(uk|\bin\b|for me)|buy.{0,20}for (cheap|less|a good price)",
     "cheapest",
     "Use the `cheapest` skill (Skill tool) to find the best UK price for this item."),

    (r"(refresh|sync|update|re-?import).{0,15}(diary|diar|diarium)",
     "refresh-diary",
     "Use the `refresh-diary` skill (Skill tool) to re-import and sync Jim's Diarium export."),

    (r"^(good morning|morning|start.{0,10}(my )?day|let.s start|ready to start)",
     "start-day",
     "Use the `/start-day` skill (Skill tool) to run Jim's morning session start."),

    (r"(wrapping up|done for (the )?day|end.{0,10}(my )?day|finishing up|that.s (it|all) for (today|now))",
     "end-day",
     "Use the `/end-day` skill (Skill tool) to close out Jim's day."),

    (r"what.{0,15}reddit.{0,15}(say|think|recommend|suggest)|search reddit (for|about)|reddit.{0,10}(opinion|view|recommendation)",
     "reddit-search",
     "Use the `reddit-search` skill (Skill tool) to search Reddit for Jim's query."),
]

for pattern, skill, instruction in PERSONAL:
    if re.search(pattern, p):
        context = f"SKILL MATCH: {skill}\n{instruction}\n(Jim typed: \"{prompt[:80]}{'…' if len(prompt) > 80 else ''}\")"
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": context}}))
        sys.exit(0)

# ── Superpowers skill patterns (fallback) ─────────────────────────────────────
# Gate: only if superpowers plugin is enabled
import subprocess
try:
    result = subprocess.run(
        ["jq", "-r", '.enabledPlugins["superpowers@claude-plugins-official"] // empty',
         os.path.expanduser("~/.claude/settings.json")],
        capture_output=True, text=True, timeout=2
    )
    sp_enabled = result.stdout.strip()
    if not sp_enabled or sp_enabled in ("false", "null"):
        sys.exit(0)
except Exception:
    sys.exit(0)

word_count = len(words)
if word_count < 5:
    sys.exit(0)

skill = ""
reason = ""

if re.search(r'fix|bug|error|broken|fail|crash|not working|issue|wrong|unexpected', p):
    skill, reason = "superpowers:systematic-debugging", "bug/error signals detected"
elif re.search(r'build|create|add feature|new feature|design|component|implement', p):
    skill, reason = "superpowers:brainstorming", "creative/feature work signals detected"
elif re.search(r'implement|code up|write the|develop', p):
    skill, reason = "superpowers:test-driven-development", "implementation signals detected"
elif re.search(r'plan|spec|requirements|multi.step|architecture|design doc', p):
    skill, reason = "superpowers:writing-plans", "planning signals detected"
elif re.search(r'done|complete|finish|ship|ready|merge|pull request|pr$', p):
    skill, reason = "superpowers:verification-before-completion", "completion signals detected"
elif re.search(r'parallel|concurrent|independent task|at the same time', p):
    skill, reason = "superpowers:dispatching-parallel-agents", "parallelisation signals detected"

if skill:
    msg = f"SKILL MATCH ({reason}): Invoke `{skill}` via the Skill tool BEFORE responding or writing code."
elif word_count > 15:
    msg = "SKILL CHECK: Before acting, check if any superpowers skill applies (see trigger table in CLAUDE.md)."
else:
    sys.exit(0)

print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": msg}}))
PY

exit 0
