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

## 2026-03-03: Migrate from Codex CLI to Claude Code

**Context:**
The repository was initially set up with OpenAI Codex CLI conventions (AGENTS.md, CONTINUITY.md session ledger, docs/CODEX_WORKFLOW.md).

**Decision:**
Migrate to Anthropic Claude Code conventions (CLAUDE.md, .claude/settings.json) while preserving project rules and archiving historical session data.

**Alternatives considered:**
- Maintain both AGENTS.md and CLAUDE.md side-by-side
- Start from scratch with a minimal CLAUDE.md

**Consequences:**
- Claude Code automatically reads CLAUDE.md for project context
- Pre-approved make targets reduce permission prompts
- Historical session log preserved in docs/CONTINUITY_ARCHIVE.md
- AGENTS.md removed (no longer needed)

## 2026-03-02: Migrate visualization/reasoning notebooks to dedicated repository

**Context:**
Several notebooks focused on reasoning display, evaluation, and multi-class analysis were not core to the entropy/LR estimation pipeline. Keeping them here added dependency weight and blurred the repository's scope.

**Decision:**
Move five notebooks to a dedicated repository:
- `notebooks/display_reasoning.ipynb`
- `notebooks/multi_class_cont.ipynb`
- `notebooks/reasoning_eval.ipynb`
- `notebooks/extract_nnt_lrs.ipynb`
- `notebooks/test_notebook.ipynb`

Four notebooks remain in this repository:
- `notebooks/estimate_lrs.ipynb` — LR estimation via OpenAI
- `notebooks/extract_features.ipynb` — feature extraction from transcripts
- `notebooks/feedback_generator.ipynb` — feedback sheet generation
- `notebooks/lr_estimator_only.ipynb` — standalone LR estimator

**Consequences:**
- `reports/display_reasoning.html` removed (source notebook gone)
- `pystata` dependency note removed from README (no remaining notebooks use it)
- Leaner dependency surface for this repository

## 2026-03-03: Split lr_estimator_only.ipynb into focused notebooks

**Context:**
`lr_estimator_only.ipynb` grew to 29 cells covering four independent tasks: matrix LR estimation (category and disease level), differential LR estimation, and model comparison visualization. The phases had no data flow between them, mixed two OpenAI API generations, and contained near-identical copy-pasted cells.

**Decision:**
Split into three self-contained notebooks, each independently runnable:
- `notebooks/estimate_lrs_matrix.ipynb` — category-level and disease-level LR matrix filling (plain and plus-minus variants)
- `notebooks/01_estimate_differential_lrs.ipynb` — pairwise differential LR estimation (Chat Completions and Responses API variants)
- `notebooks/compare_lr_estimates.ipynb` — KDE overlays and Bland-Altman plots for model agreement

The superseded single-disease estimator ("old version") was archived to `archive/lr_estimator_single_disease.py`.

**Alternatives considered:**
- Extract shared functions to `src/dx_chat_entropy/lr_estimation.py` — rejected in favor of keeping each notebook fully self-contained for researcher independence
- Keep as one notebook with better section markers — rejected because the phases have distinct I/O contracts and no shared state

**Consequences:**
- Each notebook is independently runnable (no cross-notebook imports)
- Shared functions (LRResponse, estimate_lr, fill_matrix, build_plusminus_df) are duplicated where needed — independence over DRY for interactive notebooks
- Three copy-paste differential LR cells collapsed into one parameterized cell iterating a config list
- `lr_estimator_only.ipynb` removed
