---
name: feedback-email-sending
description: Never attempt to send emails — Jim uses Outlook and Claude has no admin access to connect
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 6754a549-ecc3-4719-8ed1-0fd136bd37e9
  project: WORK
  source_file: feedback_email_sending.md
  migrated_on: 2026-05-17
---

Never attempt to send emails on Jim's behalf. Jim uses Outlook (Transfers@AtomicFilm.Services) and has no admin access to connect Claude to it. Always present email drafts as text for Jim to copy across manually.

**Why:** No Outlook MCP integration — Gmail MCP exists for james.cherry01@gmail.com personal account only, but work emails go through Outlook which Claude cannot access.

**How to apply:** On any /draft or email task, stop at the reviewable draft. Never call a send tool. Never confirm an email was sent.
