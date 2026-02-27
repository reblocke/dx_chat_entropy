# Design principles (scientific programming)

This repository is organized around principles that keep clinical reasoning analysis code:
- correct
- reproducible
- reviewable
- extensible

## 1) Make the scientific claim explicit
- Encode questions/assumptions in issues or docs.
- Keep exploratory and confirmatory workflows distinct.

## 2) Prefer simple, boring structure
- Separate data/code/reports.
- Keep reusable logic in `src/`.

## 3) Functional core, imperative shell
- Pure transformations in `src/` where possible.
- I/O and orchestration in scripts/notebooks.

## 4) Reproducibility is a feature
- Use pinned environments.
- Avoid hidden local paths and hidden state.

## 5) Test what matters
- Unit tests for invariants.
- Policy checks for repo hygiene.

## 6) Make change safe
- Small PRs.
- Decision log in `docs/DECISIONS.md`.

## 7) Avoid hidden state
- No reliance on current working directory.
- Prefer deterministic and restartable notebooks.

## 8) Security and privacy by default
- No committed credentials.
- No sensitive data leakage in outputs.

## 9) Optimize late
- Profile first, optimize bottlenecks.

## 10) Treat AI assistance as a power tool
- Require explicit checks for agent-generated changes.
