---
name: Slack timestamp ordering
description: Slack replies must be read in timestamp order — a message's context is the preceding message by time, not by visual proximity in API output
type: feedback
metadata:
  node_type: memory
  type: feedback
  project: WORK
  source_file: feedback_slack_timestamp_ordering.md
  migrated_on: 2026-05-17
---

Read Slack threads by timestamp order before attributing a reply to a question.

**Why:** In a session, I attributed "just ask now and we'll see what they say" (ts: 1776693092) to a later message about contacting The Ark (ts: 1776696384). It was actually a reply to the Filmax outreach question (ts: 1776693007), which came before it. Jim caught this and corrected it.

**How to apply:** When reading Slack channel history, sort messages by `ts` ascending before drawing any "X replied to Y" conclusions. Don't assume the visually nearest message in API output is the one being answered — check the timestamps explicitly.
