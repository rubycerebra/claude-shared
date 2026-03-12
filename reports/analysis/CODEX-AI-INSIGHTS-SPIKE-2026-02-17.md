# Codex AI Insights Spike (Research Only) - 2026-02-17

## Decision status

- Scope: research spike only.
- Runtime cutover: not approved.
- Current production path remains Anthropic Haiku.

## Why this spike exists

You asked for a future option to switch AI insights from Haiku to Codex while keeping reliability of the existing daemon pipeline.

## Current baseline (today)

- Primary runtime files:
  - `~/.claude/daemon/data_collector.py`
  - `~/.claude/scripts/shared/ai_service.py`
  - `~/.claude/scripts/write-ai-insights.py`
- Pattern: AI-first with heuristic fallback.
- Main AI calls today:
  - daily insights
  - daily guidance
  - evening insights
  - tomorrow guidance
  - completion matching

## Compatibility matrix (Haiku vs Codex)

| Area | Haiku path today | Codex path target |
|---|---|---|
| SDK | `anthropic` | `openai` Responses API |
| Request shape | `messages.create(...)` | `responses.create(...)` |
| JSON handling | strict JSON + code-fence cleanup | strict JSON + tool/schema guardrails |
| Retry behavior | current fallback wrappers | same wrapper contract preserved |
| Operational fallback | heuristic fallback already in place | same fallback retained |
| Rollback | switch provider to Anthropic | immediate, no schema migration |

## Workload estimate for AI insights path

These are practical planning ranges from current prompt structures (not billing values):

- Daily insights call: medium prompt, medium response.
- Daily guidance call: medium-large prompt, short response list.
- Evening insights call: medium prompt, medium response.
- Tomorrow guidance call: medium-large prompt, short response list.
- Completion matching call: small-medium prompt, short structured output.

Expected result: model quality/latency and structured-output stability matter more than raw token volume for this pipeline.

## Provider abstraction design (proposed)

Target file: `~/.claude/scripts/shared/ai_service.py`

Introduce a provider-agnostic interface:

- `get_ai_client(provider=None)`
- `generate_json(prompt, model, max_tokens, label)`
- `generate_text(prompt, model, max_tokens, label)`

Provider routing:

- `AI_PROVIDER=anthropic` (default)
- `AI_PROVIDER=openai` (future optional)

Model routing config example:

- `AI_MODEL_DAILY_INSIGHTS`
- `AI_MODEL_DAILY_GUIDANCE`
- `AI_MODEL_EVENING_INSIGHTS`
- `AI_MODEL_TOMORROW_GUIDANCE`

## Go / no-go criteria

Go only if all pass in side-by-side test window:

1. JSON parse success rate >= current Haiku baseline.
2. No regression in completion matching precision.
3. Guidance quality acceptable for anxiety-support use case.
4. Runtime failures remain bounded by existing fallback behavior.
5. Cost envelope acceptable under your daily call volume.

## Rollback plan

1. Keep Anthropic provider code intact.
2. Gate Codex behind env/config flag.
3. If quality or stability drops, flip provider flag back to Anthropic.
4. No data migration required; cache schema remains unchanged.

## Backlog items if approved later

1. Add OpenAI provider implementation in `ai_service.py`.
2. Add model/route config keys.
3. Add response schema guards for structured outputs.
4. Add provider-level observability fields (`provider`, `model`, `latency_ms`, `parse_ok`).
5. Run 7-day A/B shadow evaluation before cutover.

## Reference links

- `https://platform.openai.com/docs/models/gpt-5-codex`
- `https://platform.openai.com/docs/models/gpt-5.2-codex`
- `https://platform.openai.com/docs/api-reference/responses/create`
