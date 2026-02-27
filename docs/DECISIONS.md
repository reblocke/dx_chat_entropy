# Decisions

Use this file to record decisions that are hard to infer from the code alone.

## 2026-02-24: Starter integration and repository normalization

**Context:**
The project started as a notebook-heavy research repo with mixed root-level data/artifacts and minimal reproducibility scaffolding.

**Decision:**
Adopt a starter-kit scientific Python structure with `src/`, `tests/`, `config/`, `data/`, `artifacts/`, `reports/`, `docs/`, and `archive/`, while preserving legacy artifacts in-repo under `archive/`.

**Alternatives considered:**
- Keep current layout and only add docs
- Fully refactor notebook logic into modules immediately

**Consequences:**
- Better reproducibility and governance
- Larger one-time migration diff
- Legacy paths needed rewriting in notebooks

## 2026-02-24: Security cleanup for exposed API key output

**Context:**
A notebook output contained an exposed OpenAI key string.

**Decision:**
Clear notebook outputs across migrated notebooks, remove key-printing behavior, add repository secret-pattern audits, and require key rotation operationally.

**Alternatives considered:**
- Defer cleanup
- Rewrite full git history immediately

**Consequences:**
- Current tree is cleaned and guardrails added
- Historical commit remediation remains an operational follow-up task
