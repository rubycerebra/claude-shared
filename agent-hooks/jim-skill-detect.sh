#!/usr/bin/env bash
# jim-skill-detect.sh — UserPromptSubmit hook
# Detects natural language triggers for Jim's personal skills and injects guidance.
# Removes the need to remember slash commands for AuDHD-friendly interaction.

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

# Extract prompt text — try top-level 'prompt', then message.content[]
prompt = ""
if isinstance(payload, dict):
    prompt = payload.get("prompt", "")
    if not prompt:
        for block in payload.get("message", {}).get("content", []):
            if isinstance(block, dict) and block.get("type") == "text":
                prompt += block.get("text", "")

prompt = prompt.strip()
if not prompt:
    sys.exit(0)

# Skip slash commands (handled by skill tool directly)
if prompt.startswith("/"):
    sys.exit(0)

# Skip very short prompts and common conversational one-liners
words = prompt.split()
if len(words) < 3:
    sys.exit(0)

first_word = words[0].lower().rstrip(".,!?")
if first_word in ("yes", "no", "ok", "sure", "done", "continue", "thanks",
                  "yeah", "nope", "cool", "great", "nice", "good", "perfect"):
    sys.exit(0)

p = prompt.lower()

# ── Pattern → (skill_name, instruction) ──────────────────────────────────────

PATTERNS = [
    # 1. Diarium transcription
    (r"transcribe.{0,20}(diary|diar)|diary entry|morning entry|transcribe.{0,20}my.{0,20}(journal|notes)",
     "transcribe-diarium",
     "Use the `transcribe-diarium` skill (Skill tool) to process Jim's diary entry."),

    # 2. Letterboxd — watched a film
    (r"\b(i watched|i've watched|i just watched|just watched|finished watching|mark.{0,20}as watched|mark.{0,20}watched)\b",
     "watched",
     "Use the `watched` skill (Skill tool) to log this film to Jim's Letterboxd watchlist."),

    # 3. Daily check-in
    (r"how (am i|is my day|is today going|are things today)|daily (status|check|rundown)|what.{0,10}(on today|have i got today|my day look)",
     "check-day",
     "Use the `check-day` skill (Skill tool) to show Jim's daily context."),

    # 4. Session recall / context loading
    (r"(load|recall|find|pull up|look for).{0,20}(session|conversation|context)|pick up where (we|i).{0,10}(left|stopped)|find.{0,30}work(ed)? on|what (was|were) (we|i) (doing|working|building)",
     "context",
     "Use the `/context` skill (Skill tool) to search and load the relevant prior session."),

    # 5. Session stamping / bookmarking
    (r"(save|stamp|bookmark|label|tag).{0,10}(this session|this conversation)|remember this session",
     "id",
     "Use the `/id` skill (Skill tool) to stamp and save this session with a label."),

    # 6. Coaching / regulation support
    (r"(feeling|i feel|i.m).{0,15}(stuck|overwhelmed|anxious|avoidant|frozen|paralysed|paralyzed)|pda.{0,10}(flare|mode|spike)|executive function|can.t (get started|begin|focus|concentrate)|don.t know where to start",
     "coach",
     "Jim needs coaching support. Invoke the `coach` skill (Skill tool) for regulation-first support."),

    # 7. UK price / cheapest finder
    (r"(cheapest|best price|where.{0,10}buy|find.{0,10}cheap).{0,30}(uk|\bin\b|for me)|buy.{0,20}for (cheap|less|a good price)",
     "cheapest",
     "Use the `cheapest` skill (Skill tool) to find the best UK price for this item."),

    # 8. Diarium refresh / sync
    (r"(refresh|sync|update|re-?import).{0,15}(diary|diar|diarium)",
     "refresh-diary",
     "Use the `refresh-diary` skill (Skill tool) to re-import and sync Jim's Diarium export."),

    # 9a. Start of day
    (r"^(good morning|morning|start.{0,10}(my )?day|let.s start|ready to start)",
     "start-day",
     "Use the `/start-day` skill (Skill tool) to run Jim's morning session start."),

    # 9b. End of day
    (r"(wrapping up|done for (the )?day|end.{0,10}(my )?day|finishing up|that.s (it|all) for (today|now))",
     "end-day",
     "Use the `/end-day` skill (Skill tool) to close out Jim's day."),

    # 10. Reddit search
    (r"what.{0,15}reddit.{0,15}(say|think|recommend|suggest)|search reddit (for|about)|reddit.{0,10}(opinion|view|recommendation)",
     "reddit-search",
     "Use the `reddit-search` skill (Skill tool) to search Reddit for Jim's query."),
]

matched_skill = None
matched_instruction = None

for pattern, skill, instruction in PATTERNS:
    if re.search(pattern, p):
        matched_skill = skill
        matched_instruction = instruction
        break

if not matched_skill:
    sys.exit(0)

context = f"SKILL MATCH: {matched_skill}\n{matched_instruction}\n(Jim typed: \"{prompt[:80]}{'…' if len(prompt) > 80 else ''}\")"

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": context
    }
}))
PY

exit 0
