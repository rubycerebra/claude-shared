# Master Plan

## Goal
Establish `claude-shared` as the canonical shared-core source, keep `~/.claude` as runtime output, preserve NUC-as-base / Mac-as-interface behaviour, and make Claude the primary recovery/operator surface.

## Phases
1. Inventory + ownership docs
2. Shared-core bootstrap
3. Exact duplicate helper migration
4. Near-duplicate + device adapter split
5. Large-file decomposition
6. Final adapter pass and deploy tooling hardening

## Current phase
Phase 2/3 bootstrap is underway: package skeleton exists and several exact duplicate helpers now route through shared-core wrappers.
