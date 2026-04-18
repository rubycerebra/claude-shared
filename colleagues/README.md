
# Colleagues

A shared framework for project-bound Claude colleague personas.

## Layout
- `FRAMEWORK.md` — shared spine
- `persona-template.md` — starting brief
- `knowledge-template/` — starting knowledge tree
- `scope-manifest.yaml` — scope source of truth

## Add a new colleague
1. copy the persona template into the project
2. copy the knowledge template
3. add scope in `scope-manifest.yaml`
4. seed a few real files
5. run `python3 ~/.claude/scripts/colleagues-bridge.py --project PROJECT`
6. append the persona block to that project's CLAUDE file
7. run scope checks before calling it settled

## Principles
- mirror first
- stay inside scope
- keep bridges light
- log unknowns plainly
- write extractor output only into `learned/`
