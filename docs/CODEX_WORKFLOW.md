# Coding-agent workflow (Codex)

## Default loop
1. Frame goal, assumptions, constraints, and checks.
2. Plan the smallest viable change set.
3. Execute with minimal, reviewable diffs.
4. Evaluate with `make fmt lint test audit`.

## Repo-specific rules
- Follow `AGENTS.md`.
- Update `CONTINUITY.md` for non-trivial sessions.
- Record non-obvious choices in `docs/DECISIONS.md`.

## When stuck
- Reduce scope.
- Add a failing test/check.
- Add diagnostics behind a flag.
- Document attempted approaches.
