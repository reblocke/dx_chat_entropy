# Coding-agent workflow (Claude Code)

## Default loop
1. Frame goal, assumptions, constraints, and checks.
2. Plan the smallest viable change set.
3. Execute with minimal, reviewable diffs.
4. Evaluate with `make fmt lint test audit`.

## Repo-specific rules
- Follow `CLAUDE.md`.
- Record non-obvious choices in `docs/DECISIONS.md`.
- Keep `README.md` human-oriented and keep `docs/SPECIFICATION.md` aligned with current pipeline purpose/input/output contracts.

## When stuck
- Reduce scope.
- Add a failing test/check.
- Add diagnostics behind a flag.
- Document attempted approaches.
