---
name: feedback-wait-verify-pattern
description: "For \"wait N minutes then verify\" verification windows, prefer Monitor + until-loop over sleep-in-Bash — sleep loops get SIGKILLed when the harness times out or compresses context"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: bec5c8fb-3672-44ab-80af-c3f1189e3971
  project: TODO
  source_file: feedback_wait_verify_pattern.md
  migrated_on: 2026-05-17
---

When a bead requires a verification window (e.g. TODO-g4t0's "tail log for 10 min shows zero warnings"), don't use a single long `sleep` inside a Bash call. Two failure modes hit me in the g4t0 session:

1. **SIGKILL at minute 6 of 8.** A `sleep 60` loop inside Bash with `timeout=540000` got exit code 137 around the 6-min mark — looks like the harness/host can interrupt long-running foreground bash regardless of timeout. The verification probes lost the last 2 min of coverage.
2. **Context compression mid-wait.** The conversation was compressed between sleeps, and on resume the loop had to be re-reasoned from cached state rather than continued.

**Better pattern:** start a `Monitor` (background log watcher with an until-loop), do other useful work in the foreground (e.g. start the next bead's analysis), and let the Monitor notify when the window closes. Or — if the verification is small — schedule a wakeup with ScheduleWakeup at a specific timestamp (only valid inside /loop mode, so check first).

**Even better for log windows:** instead of waiting wall-clock N minutes, check the log mtime. If mtime hasn't advanced since the restart timestamp, that's stronger evidence than "no new lines in last N minutes of polling" — because mtime jumps the instant anything is written.

**Why:** verification windows are real wall-clock waits that don't compress well into a single Bash call. The harness reserves the right to interrupt long foreground operations. Background Monitor + parallel work is more resilient and uses the wait time productively.

**How to apply:** any bead with "tail for N min" or "wait for X then verify" in its Done-when. Especially if N >= 5 min.
