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
- `notebooks/11_assessment_estimate_lrs.ipynb` — LR estimation via OpenAI
- `notebooks/10_assessment_extract_features.ipynb` — feature extraction from transcripts
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
- `notebooks/30_one_vs_rest_estimate_lrs.ipynb` — category-level and disease-level LR matrix filling (plain and plus-minus variants)
- `notebooks/21_differential_estimate_lrs.ipynb` — pairwise differential LR estimation (Chat Completions and Responses API variants)
- `notebooks/31_one_vs_rest_compare_lr_estimates.ipynb` — KDE overlays and Bland-Altman plots for model agreement

The superseded single-disease estimator ("old version") was archived to `archive/lr_estimator_single_disease.py`.

**Alternatives considered:**
- Extract shared functions to `src/dx_chat_entropy/lr_estimation.py` — rejected in favor of keeping each notebook fully self-contained for researcher independence
- Keep as one notebook with better section markers — rejected because the phases have distinct I/O contracts and no shared state

**Consequences:**
- Each notebook is independently runnable (no cross-notebook imports)
- Shared functions (LRResponse, estimate_lr, fill_matrix, build_plusminus_df) are duplicated where needed — independence over DRY for interactive notebooks
- Three copy-paste differential LR cells collapsed into one parameterized cell iterating a config list
- `lr_estimator_only.ipynb` removed
- Pipeline relationship is explicit:
  - Canonical active path: `20_differential_build_inputs.ipynb` -> `21_differential_estimate_lrs.ipynb`
  - Archive path: `30_one_vs_rest_estimate_lrs.ipynb` -> `31_one_vs_rest_compare_lr_estimates.ipynb`
  - `31_one_vs_rest_compare_lr_estimates.ipynb` is for one-vs-rest model-agreement visualization and is not consumed by canonical differential-LR generation

## 2026-03-10: Canonical one-vs-rest pipeline with schema-row normalization

**Context:**
Raw LR matrices may contain multiple pre-key-feature header rows. One-vs-rest estimation should support each category-defining row as its own schema instead of assuming a single fixed header row.

**Decision:**
Add a script-first canonical one-vs-rest pipeline:
- `scripts/build_one_vs_rest_inputs.py` normalizes raw scenario sheets into workbook-per-scenario schema sheets under `data/processed/lr_one_vs_rest/inputs/`.
- Each qualifying category-defining row above key-feature becomes its own schema sheet.
- Numeric-only header rows (e.g., priors) are excluded.
- Duplicate category sequences are deduplicated.
- `scripts/run_one_vs_rest_batch.py` runs model estimation across schema sheets.
- `scripts/audit_one_vs_rest_outputs.py` enforces completeness and positive numeric LR values.

**Consequences:**
- One-vs-rest runs are reproducible and manifest-driven.
- Multi-level header sheets are supported without manual workbook editing.
- Chest pain 18-category mismatch remains warning-only (`expected=18`, `observed=19`).

## 2026-03-10: Centralize pipeline purpose/input/output documentation

**Context:**
Pipeline details were documented in multiple places with partial overlap, which
increased drift risk after notebook/script renames and pipeline refactors.

**Decision:**
Add `docs/PIPELINES.md` as the canonical inventory of current workflows,
including purpose, primary inputs, primary outputs, and execution order.
`README.md` keeps an at-a-glance summary and links to `docs/PIPELINES.md`.
This arrangement was later superseded by the 2026-03-12 documentation split.

**Consequences:**
- Pipeline contracts are easier to audit after changes.
- Contributors have a single source to update when I/O or run order changes.

## 2026-03-11: Differential runtime and bundle hardening

**Context:**
Recent review of a differential pipeline package identified runtime and packaging
gaps: missing local imports in bundles, stale/contradictory manifest artifacts,
repair path mismatches, and warning-only category-count mismatches in active
scenario configs.

**Decision:**
- Make category-count mismatches fail closed by default in differential and
  one-vs-rest input parsing (`ALLOW_CATEGORY_COUNT_MISMATCH=true` required for
  intentional overrides).
- Centralize differential execution in
  `src/dx_chat_entropy/lr_differential_runner.py` and use it from both
  `scripts/run_differential_batch.py` and
  `notebooks/21_differential_estimate_lrs.ipynb`.
- Add explicit `DX_RESUME_MODE` (`recompute|skip_passing|repair_invalid`) plus
  dynamic repair CSV path resolution (`invalid_rows_<MODEL_ID>.csv` fallback to
  `invalid_rows.csv`).
- Add bundle structural validation in
  `src/dx_chat_entropy/lr_differential_bundle.py` and
  `scripts/check_differential_bundle.py`.
- Harden review packaging to include required runtime files (`paths.py`,
  `__init__.py`, `pyproject.toml`, `uv.lock`, config files), include run ledger
  and logs, and block stale `pairs_manifest_missing*.csv` artifacts.
- Route audit/runner normalization through shared cell normalization utilities to
  avoid `"nan"` text drift from blank spreadsheet cells.

**Consequences:**
- Differential runs are resumable with explicit, testable semantics.
- Repair runs work with model-scoped audit artifacts without manual path edits.
- Package generation fails early on structural inconsistency instead of producing
  misleading review bundles.
- CI-level tests now cover runtime config resolution/resume semantics and bundle
  completeness checks.

## 2026-03-11: Add Bayes-coherent one-vs-rest projection stage

**Context:**
Raw one-vs-rest LRs are estimated independently per category and can be
multiclass-incoherent for a finding row (independent posteriors do not sum to 1,
and sign-impossible all->1/all-<1 rows can appear).

**Decision:**
- Add durable schema prior propagation to one-vs-rest normalization via
  `data/processed/lr_one_vs_rest/manifests/schema_priors.csv`.
- Add solver module `src/dx_chat_entropy/lr_one_vs_rest_coherence.py` implementing
  multiclass coherent projection on log-LR scale with regularized score fitting.
- Add script-first projection stage
  `scripts/project_one_vs_rest_coherent_lrs.py` that writes coherent outputs to
  `data/processed/lr_one_vs_rest/coherent_outputs_by_model/<MODEL_ID>/` and emits
  projection diagnostics/failures manifests.
- Add notebook wrapper `notebooks/32_one_vs_rest_project_coherent_lrs.ipynb`.
- Extend `scripts/audit_one_vs_rest_outputs.py` with optional coherent mode for
  posterior-sum and sign-impossible checks plus scenario-level before/after stats.

**Consequences:**
- Raw and coherent outputs are retained as separate artifacts for reviewer
  traceability.
- Existing raw model outputs can be projected without rerunning LLM estimation via
  `--derive-priors-if-missing` in the projection script.
- One-vs-rest pipeline now has an explicit post-estimation coherence stage.

## 2026-03-12: Split operator documentation from specification

**Context:**
The README had become a hybrid of onboarding guide, runbook, and specification.
That made it harder for a human reader to understand what the repository does
and where to start, while also increasing the risk of duplicate contract
documentation drifting out of sync.

**Decision:**
- Keep `README.md` focused on human understanding, workflow selection, and
  normal run procedures.
- Make `docs/SPECIFICATION.md` the detailed source for pipeline contracts,
  artifact locations, manifests, validation behavior, and review-bundle scope.
- Keep `docs/PIPELINES.md` as a short navigation index rather than a second full
  specification document.

**Consequences:**
- New users get a clearer operator-facing entry point.
- Detailed workflow and artifact contracts still exist in one place.
- Future pipeline changes should update `README.md` and
  `docs/SPECIFICATION.md`, with `docs/PIPELINES.md` updated only when the
  pipeline inventory changes.
