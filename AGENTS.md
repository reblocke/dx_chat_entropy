# AGENTS.md

## Project overview
- This repository is a Python-first scientific/clinical reasoning codebase for entropy- and likelihood-ratio-based analysis of chatbot-assisted diagnostic reasoning.
- Primary language is Python.
- Priorities:
  1) Human time (clarity, maintainability)
  2) Reproducibility
  3) Performance (only when measured)

## Behavioral guidelines
### 1) Think before coding
- State assumptions.
- Surface ambiguity and tradeoffs.
- Prefer explicit clarification over silent guessing.

### 2) Simplicity first
- Implement the minimum change that satisfies the request.
- Avoid speculative abstractions.

### 3) Surgical changes
- Touch only files needed for the task.
- Do not refactor unrelated areas without request.

### 4) Goal-driven execution
- Define concrete verification criteria.
- Verify behavior with tests/checks.

## Continuity ledger
Maintain `CONTINUITY.md` as the compaction-safe session ledger.

Recommended sections:
- Goal (incl. success criteria)
- Constraints/Assumptions
- Key decisions
- State (Done/Now/Next)
- Open questions
- Working set

## Authority hierarchy
1. Study protocol / domain requirements
2. Repository docs (`README.md`, `docs/DECISIONS.md`, this `AGENTS.md`)
3. Existing code/notebooks

## Non-negotiables
- Never commit secrets/credentials.
- No hard-coded absolute local machine paths in committed notebook/code source.
- Keep patient or sensitive data out of committed artifacts.
- Preserve raw input immutability.

## Environment
- Python >= 3.11
- Dependency management: `uv` + `pyproject.toml`
- Lint/format: Ruff
- Tests: pytest

## Repository structure
- `src/` importable core utilities
- `scripts/` thin orchestration / tooling
- `tests/` checks and policy tests
- `notebooks/` exploratory/analysis notebooks
- `reports/` deterministic report outputs

## Data/I-O rules
- Use `pathlib.Path` and repo-relative paths.
- Avoid `os.chdir` in committed code.
- Validate boundary inputs where feasible.

## Reproducibility
- Keep examples runnable from fresh sessions.
- Record assumptions in `docs/DECISIONS.md` when non-obvious.

## Tests/checks
Before handoff, run:
- `make fmt`
- `make lint`
- `make test`
- `make audit`
