# dx_chat_entropy
Clinical reasoning entropy and likelihood-ratio analysis with reproducible Python workflows.

This repository combines active analysis code/notebooks with an in-repo archive of historical runs and source artifacts.

## Quickstart
Prerequisites:
- Python 3.11+
- `uv`

From repository root:

```bash
uv sync
make fmt
make lint
make test
make audit
```

For notebooks (all tracked notebooks, full dependency set):

```bash
uv sync --group notebooks
```

Register and use a dedicated notebook kernel for this repo:

```bash
make notebook-kernel
```

In VS Code, select kernel `Python (dx-chat-entropy)` (top-right kernel picker).
If VS Code keeps using another kernel (for example `llm_py311`), notebook imports may fail
even when `uv sync --group notebooks` succeeded.

Build canonical differential-LR pair inputs (manifest + generated workbooks):
- run `notebooks/20_differential_build_inputs.ipynb` (self-contained canonical builder)

## Current Pipeline Map
Use `docs/PIPELINES.md` as the canonical source for current pipeline purpose,
inputs, outputs, and execution order.

At a glance:
- Assessment feature + LR labeling (active): `10_assessment_extract_features.ipynb` -> `11_assessment_estimate_lrs.ipynb`
- Differential LR (active, canonical runtime): `20_differential_build_inputs.ipynb` -> `scripts/run_differential_batch.py` (or notebook `21` wrapper) -> `scripts/audit_differential_outputs.py`
- One-vs-rest LR (active, canonical script-first): `scripts/build_one_vs_rest_inputs.py` -> `scripts/run_one_vs_rest_batch.py` -> `scripts/project_one_vs_rest_coherent_lrs.py` -> `scripts/audit_one_vs_rest_outputs.py`
- One-vs-rest agreement visualization (archive): `30_one_vs_rest_estimate_lrs.ipynb` -> `31_one_vs_rest_compare_lr_estimates.ipynb`

## Notebook Execution (VS Code)
Use this flow for notebooks such as `notebooks/11_assessment_estimate_lrs.ipynb`.

1. Sync notebook dependencies:

```bash
make uv-sync-notebooks
```

2. Register the repo-specific kernel:

```bash
make notebook-kernel
```

3. Open the notebook in VS Code and select kernel `Python (dx-chat-entropy)`.
4. Run this sanity check in a notebook cell:

```python
import sys
from markitdown import MarkItDown

print(sys.executable)
print(MarkItDown)
```

Expected interpreter path includes:
`.../dx_chat_entropy/.venv/bin/python3`

5. For OpenAI-backed notebooks, ensure `.env` contains a valid `OPENAI_API_KEY`.

### Troubleshooting
- Symptom: `ModuleNotFoundError` after syncing dependencies.
  Cause: notebook is attached to a different Python kernel/interpreter.
- Fix: re-select `Python (dx-chat-entropy)`, then run `Restart Kernel` in VS Code.
- CLI verification from repo root:

```bash
uv run --group notebooks python -c "from markitdown import MarkItDown; import llm; from openai import OpenAI; print('ok')"
```

## Assessment Feature + LR Label Pipeline
This is a separate assessment workflow from the differential LR and one-vs-rest
pipelines.

1. Run `notebooks/10_assessment_extract_features.ipynb` to extract transcript findings into assessment sheets:
- Inputs: `data/raw/chatbot_transcripts/*.pdf`, `data/raw/assessment_templates/asssessment_template_new.xlsx`
- Outputs: `data/processed/assessments/answers_*.xlsx`

2. Run `notebooks/11_assessment_estimate_lrs.ipynb` to fill missing LR labels in assessment sheets:
- Inputs: `data/raw/assessment_templates/asssessment_template_new.xlsx` (+ processed assessment answer sheets)
- Outputs: `data/processed/assessments/completed_lrs.xlsx`

## Differential LR Pipeline (Canonical)
Active LR-matrix inputs are canonicalized under `data/raw/lr_matrices/` and pairwise
differential inputs are generated under `data/processed/lr_differential/`.
`archive/*` remains historical-only provenance.

1. Sync notebook dependencies and kernel:

```bash
make uv-sync-notebooks
make notebook-kernel
```

2. Build pairwise differential-input workbooks + manifests:

Preferred (notebook-first, self-contained transformation code):
- run `notebooks/20_differential_build_inputs.ipynb`
- default is fail-closed on category-count mismatch; set `ALLOW_CATEGORY_COUNT_MISMATCH=true`
  only for intentional overrides.

3. Open `notebooks/21_differential_estimate_lrs.ipynb`, select kernel `Python (dx-chat-entropy)`,
   and run all cells.
The notebook reads:
- `data/processed/lr_differential/manifests/pairs_manifest.csv`

The notebook writes:
- `data/processed/lr_differential/outputs_by_model/<MODEL_ID>/<scenario_id>/*_filled.xlsx`

4. Preferred script-first execution (same runtime used by notebook):

```bash
DX_MODEL_ID=gpt-5.3-chat-latest \
DX_RESUME_MODE=skip_passing \
uv run --group notebooks python scripts/run_differential_batch.py
```

Supported runtime controls:
- `DX_RESUME_MODE=recompute|skip_passing|repair_invalid`
- `DX_SCENARIO_FILTER=scenario_a,scenario_b`
- `DX_MAX_PAIRS=<int>`
- `DX_MAX_FINDINGS=<int>`
- `DX_INVALID_ROWS_PATH=<path>` (optional repair CSV override; defaults to model-scoped `invalid_rows_<MODEL_ID>.csv` if present, else `invalid_rows.csv`)
- legacy compatibility: `DX_REPAIR_MODE=true` maps to `DX_RESUME_MODE=repair_invalid` when `DX_RESUME_MODE` is unset.

5. Run deterministic quality audit after estimation:

```bash
uv run --group notebooks python scripts/audit_differential_outputs.py \
  --manifest data/processed/lr_differential/manifests/pairs_manifest.csv \
  --outputs-root data/processed/lr_differential/outputs_by_model \
  --summary-out data/processed/lr_differential/manifests/quality_summary.csv \
  --invalid-out data/processed/lr_differential/manifests/invalid_rows.csv
```

Audit outputs:
- `data/processed/lr_differential/manifests/quality_summary.csv`
- `data/processed/lr_differential/manifests/invalid_rows.csv`

Pass/fail criterion:
- every workbook must satisfy `valid_positive_lrs == expected_findings` and `total_invalid_rows == 0`.

6. If audit reports failures, run targeted repair:
- set `DX_MODEL_ID` to the failing model
- set `DX_RESUME_MODE=repair_invalid`
- optional: `DX_REPAIR_SCENARIO_FILTER` and `DX_REPAIR_MAX_ROWS`
- optional: set `DX_INVALID_ROWS_PATH` if using a non-default invalid-rows CSV
- re-run estimation, then re-run the audit command and require zero invalid/missing rows.

7. For resumable scenario-by-scenario runs with logs + ledger:

```bash
scripts/run_differential_notebook_ledger.sh gpt-5.3-chat-latest medium
```

This writes:
- `data/processed/lr_differential/manifests/run_ledger_differential_<MODEL_ID>.csv`
- `data/processed/lr_differential/manifests/logs/<MODEL_ID>/*.log`

8. To create a self-contained differential review bundle:

```bash
scripts/run_differential_and_package.sh gpt-5.3-chat-latest medium
```

Packaging includes a completeness check (`scripts/check_differential_bundle.py`) and fails if:
- local imports used by bundled notebooks/scripts are missing
- repair targets (`invalid_rows.csv` or model-scoped equivalent) are missing
- stale `pairs_manifest_missing*.csv` artifacts are present
- logs are present but a run ledger is missing

Bundle scope note: this package is a differential-pipeline review bundle, not a
full repository snapshot.

## One-vs-Rest LR Pipeline (Canonical)
This pipeline normalizes raw scenario LR matrices into one-vs-rest schema sheets
and then estimates LR cells for each schema sheet. A final coherence stage projects
raw one-vs-rest LR vectors to Bayes-coherent multiclass one-vs-rest LRs.

1. Build normalized one-vs-rest inputs from raw scenario sheets:

```bash
uv run --group notebooks python scripts/build_one_vs_rest_inputs.py \
  --config config/lr_differential_scenarios.yaml
```

If an intentional category-count mismatch exists in source sheets, set:
`ALLOW_CATEGORY_COUNT_MISMATCH=true` for this step.

2. Run one-vs-rest batch estimation (standard mode) for a model:

```bash
uv run --group notebooks python scripts/run_one_vs_rest_batch.py \
  --manifest data/processed/lr_one_vs_rest/manifests/inputs_manifest.csv \
  --model-id gpt-4o-mini
```

3. Project raw one-vs-rest outputs to coherent outputs (separate root, raw preserved):

```bash
uv run --group notebooks python scripts/project_one_vs_rest_coherent_lrs.py \
  --model-id gpt-4o-mini
```

Writes:
- `data/processed/lr_one_vs_rest/coherent_outputs_by_model/<MODEL_ID>/<scenario_id>_coherent.xlsx`
- `data/processed/lr_one_vs_rest/manifests/coherence_projection_summary_<MODEL_ID>.csv`
- `data/processed/lr_one_vs_rest/manifests/coherence_projection_top_rows_<MODEL_ID>.csv`
- `data/processed/lr_one_vs_rest/manifests/coherence_projection_failures_<MODEL_ID>.csv`

4. Audit raw outputs (shape/positivity quality gate):

```bash
uv run --group notebooks python scripts/audit_one_vs_rest_outputs.py \
  --manifest data/processed/lr_one_vs_rest/manifests/inputs_manifest.csv \
  --outputs-root data/processed/lr_one_vs_rest/outputs_by_model \
  --summary-out data/processed/lr_one_vs_rest/manifests/quality_summary.csv \
  --invalid-out data/processed/lr_one_vs_rest/manifests/invalid_cells.csv
```

5. Audit coherent outputs (positivity + posterior-sum + sign-impossible checks):

```bash
uv run --group notebooks python scripts/audit_one_vs_rest_outputs.py \
  --manifest data/processed/lr_one_vs_rest/manifests/inputs_manifest.csv \
  --outputs-root data/processed/lr_one_vs_rest/coherent_outputs_by_model \
  --summary-out data/processed/lr_one_vs_rest/manifests/coherent_quality_summary.csv \
  --invalid-out data/processed/lr_one_vs_rest/manifests/coherent_invalid_cells.csv \
  --coherence-mode \
  --priors-manifest data/processed/lr_one_vs_rest/manifests/schema_priors.csv \
  --raw-outputs-root data/processed/lr_one_vs_rest/outputs_by_model \
  --coherence-summary-out data/processed/lr_one_vs_rest/manifests/coherence_quality_summary.csv \
  --coherence-invalid-out data/processed/lr_one_vs_rest/manifests/coherence_invalid_rows.csv
```

6. Pass/fail criterion:
- every schema sheet must satisfy `valid_positive_cells == expected_cells_manifest`
- and `total_invalid_cells == 0`.
- coherent mode additionally requires:
  - posterior sums to 1 within tolerance for coherent rows
  - no sign-impossible rows remain after projection.

### One-vs-Rest Review Bundle Contract
Use this profile when shipping artifacts for external runtime/code review without
shipping full raw source inputs.

Supported in review bundles:
- inspect bundled raw and coherent outputs
- run coherence projection on bundled raw outputs
- run raw/coherent audits on bundled outputs
- run bundle structural checker

Unsupported in review bundles:
- rebuilding normalized OVR inputs from raw LR matrices
- rerunning raw one-vs-rest LLM estimation

Review-bundle package command:

```bash
uv run --group notebooks python scripts/package_one_vs_rest_review_bundle.py \
  --model-id gpt-5.3-chat-latest
```

The generated bundle includes `bundle_manifest.json` as the contract source of truth
for supported/unsupported commands and included/omitted paths.

### Multi-level schema behavior
- Candidate schema rows are rows above `Key feature`.
- Any qualifying category-defining row becomes a separate schema sheet.
- One-vs-rest estimation runs independently on each schema sheet.

### Existing-output projection (no LLM rerun)
To project existing model outputs (for example current `gpt-5.3` files) without
rerunning one-vs-rest estimation:

```bash
uv run --group notebooks python scripts/project_one_vs_rest_coherent_lrs.py \
  --model-id gpt-5.3-chat-latest \
  --derive-priors-if-missing \
  --overwrite
```

This one-time compatibility mode derives `schema_priors.csv` from existing
manifests/source sheets when needed, then projects existing raw outputs in place
to the coherent output root.

## One-vs-Rest Agreement Pipeline (Archive)
This workflow is for historical one-vs-rest matrix comparison artifacts and is
downstream of one-vs-rest matrix outputs.

1. Prepare `archive/legacy_runs/lr_estimation_2025_07_21/columns_to_plot.xlsx`
with the LR columns you want to compare across models.

2. Run `notebooks/31_one_vs_rest_compare_lr_estimates.ipynb` to generate agreement visualizations:
- KDE overlay PDF(s) in `archive/legacy_runs/lr_estimation_2025_07_21/`
- Bland-Altman pairwise PDF(s) in `archive/legacy_runs/lr_estimation_2025_07_21/`

## Notebook Inventory (Inputs/Outputs)
Current tracked notebooks in `notebooks/` and their expected file I/O:

- `10_assessment_extract_features.ipynb`
  - Inputs: `data/raw/chatbot_transcripts/*.pdf`, `data/raw/assessment_templates/asssessment_template_new.xlsx`
  - Outputs: `data/processed/assessments/answers_*.xlsx`
- `11_assessment_estimate_lrs.ipynb`
  - Inputs: `data/raw/assessment_templates/asssessment_template_new.xlsx` (+ processed assessment answer sheets)
  - Outputs: `data/processed/assessments/completed_lrs.xlsx`
- `30_one_vs_rest_estimate_lrs.ipynb`
  - Inputs: `archive/legacy_runs/lr_estimation_2025_07_21/est_lrs_by_*.xlsx`
  - Outputs: `archive/legacy_runs/lr_estimation_2025_07_21/est_lrs_by_*_filled.xlsx`
  - Pipeline role: notebook reference implementation for one-vs-rest LR filling
- `20_differential_build_inputs.ipynb`
  - Inputs: `config/lr_differential_scenarios.yaml` + canonical LR matrices in `data/raw/lr_matrices/`
  - Outputs: pair inputs in `data/processed/lr_differential/inputs/<scenario_id>/` and manifests in `data/processed/lr_differential/manifests/`
- `21_differential_estimate_lrs.ipynb`
  - Inputs: `data/processed/lr_differential/manifests/pairs_manifest.csv` and pair workbooks in `data/processed/lr_differential/inputs/<scenario_id>/`
  - Outputs: corresponding `*_filled.xlsx` workbooks in `data/processed/lr_differential/outputs_by_model/<MODEL_ID>/<scenario_id>/`
  - Run modes: `DX_RESUME_MODE` (`recompute`, `skip_passing`, `repair_invalid`) with repair driven by model-scoped or generic invalid-rows manifests
- `22_differential_prepare_inputs_qa.ipynb`
  - Inputs: `config/lr_differential_scenarios.yaml`, canonical raw LR matrices in `data/raw/lr_matrices/`, and optional generated manifests/workbooks
  - Outputs: none (QA/inspection notebook only)
- `32_one_vs_rest_project_coherent_lrs.ipynb`
  - Inputs: `data/processed/lr_one_vs_rest/outputs_by_model/<MODEL_ID>/<scenario_id>_filled.xlsx` and `data/processed/lr_one_vs_rest/manifests/schema_priors.csv`
  - Outputs: coherent workbook projections in `data/processed/lr_one_vs_rest/coherent_outputs_by_model/<MODEL_ID>/` and coherence diagnostics under `data/processed/lr_one_vs_rest/manifests/`
- `31_one_vs_rest_compare_lr_estimates.ipynb`
  - Inputs: `archive/legacy_runs/lr_estimation_2025_07_21/columns_to_plot.xlsx`
  - Outputs: comparison plots/PDFs in `archive/legacy_runs/lr_estimation_2025_07_21/`
  - Pipeline role: one-vs-rest model-agreement QA/visualization step, downstream of matrix outputs and not consumed by canonical differential LR generation
- `feedback_generator.ipynb`
  - Inputs: in-notebook diagnosis/category definitions and API responses
  - Outputs: `artifacts/feedback_sheets/<date>_<model>_feedback_sheets/*.xlsx`

## Repository Map
Core project files:
- `pyproject.toml`: package metadata, dependencies, notebook dependency group, Ruff, and pytest config.
- `uv.lock`: locked dependency set for reproducible environments.
- `Makefile`: standard local commands (`uv-sync`, `uv-sync-notebooks`, `notebook-kernel`, `fmt`, `lint`, `test`, `audit`, `clean`).
- `CLAUDE.md`: engineering and workflow rules for Claude Code.
- `AGENTS.md`: consolidated agent-facing guidance copied from `CLAUDE.md` + `docs/CLAUDE_WORKFLOW.md`.
- `CONTRIBUTING.md`: contribution and definition-of-done checklist.
- `CITATION.cff`: software citation metadata.

Code and checks:
- `src/dx_chat_entropy/__init__.py`: package exports.
- `src/dx_chat_entropy/paths.py`: repository-root discovery and canonical path helpers.
- `src/dx_chat_entropy/lr_differential_runner.py`: script/notebook-shared differential LR runtime, retry policy, and resume/repair semantics.
- `src/dx_chat_entropy/lr_differential_bundle.py`: structural validation of staged differential review bundles.
- `src/dx_chat_entropy/lr_differential_audit.py`: reusable audit logic for workbook-level and row-level LR quality checks.
- `src/dx_chat_entropy/lr_one_vs_rest_inputs.py`: schema-row discovery and normalized one-vs-rest input sheet generation.
- `src/dx_chat_entropy/lr_one_vs_rest_coherence.py`: Bayes-coherent one-vs-rest projection solver and coherence diagnostics helpers.
- `src/dx_chat_entropy/lr_one_vs_rest_audit.py`: one-vs-rest output audit helpers for schema-sheet quality checks.
- `src/dx_chat_entropy/lr_one_vs_rest_bundle.py`: structural validation logic for staged one-vs-rest review bundles.
- `scripts/audit_repo.py`: policy scanner for absolute local paths, secret-like tokens, and retained notebook outputs.
- `scripts/audit_differential_outputs.py`: differential-LR quality gate (compares expected findings vs valid positive LR outputs).
- `scripts/run_differential_batch.py`: script-first differential runtime entrypoint (shared behavior with notebook 21).
- `scripts/run_differential_notebook_ledger.sh`: scenario-ledger differential runner (resumable by scenario).
- `scripts/run_differential_and_package.sh`: end-to-end differential run + audit + review bundle packaging.
- `scripts/check_differential_bundle.py`: bundle structural completeness checker.
- `scripts/build_one_vs_rest_inputs.py`: normalize raw scenario LR matrices into one-vs-rest schema-sheet workbooks.
- `scripts/run_one_vs_rest_batch.py`: batch one-vs-rest LR estimation over normalized schema-sheet manifest rows.
- `scripts/project_one_vs_rest_coherent_lrs.py`: project raw one-vs-rest outputs to coherent one-vs-rest outputs.
- `scripts/audit_one_vs_rest_outputs.py`: one-vs-rest quality gate (expected vs valid positive schema-sheet cells).
- `scripts/check_one_vs_rest_bundle.py`: one-vs-rest review bundle structural/completeness checker.
- `scripts/package_one_vs_rest_review_bundle.py`: one-vs-rest review bundle packager (writes bundle manifest + runs checker before zip).
- `tests/test_paths.py`: path utility invariants.
- `tests/test_repo_conventions.py`: policy tests for notebooks/docs.
- `tests/test_notebook_dependencies.py`: checks that notebook imports resolve.
- `tests/test_lr_differential_audit.py`: differential-LR audit behavior tests (classification and invalid-row detection).
- `tests/test_lr_differential_runner.py`: runtime config/resume/repair path and skip-passing behavior tests.
- `tests/test_lr_differential_bundle.py`: differential bundle completeness and consistency checks.
- `tests/test_lr_one_vs_rest_inputs.py`: one-vs-rest schema detection and prior extraction behavior tests.
- `tests/test_lr_one_vs_rest_coherence.py`: coherent OVR projection solver tests and regression checks.
- `tests/test_lr_one_vs_rest_audit.py`: one-vs-rest audit behavior tests.
- `tests/test_project_one_vs_rest_coherent_lrs.py`: projection runtime safety tests (partial-write guard).
- `tests/test_lr_one_vs_rest_bundle.py`: synthetic review-bundle integration tests (projection/audit/checker/build-capability behavior).

Documentation and governance:
- `docs/PRINCIPLES.md`: scientific programming principles.
- `docs/DATA_MANAGEMENT.md`: data immutability and provenance rules.
- `docs/PIPELINES.md`: canonical pipeline purpose/input/output/run-order inventory.
- `docs/AI_ASSISTED_CODING.md`: guardrails for AI-authored changes.
- `docs/CLAUDE_WORKFLOW.md`: agent workflow loop.
- `docs/DECISIONS.md`: decision log.
- `docs/TODO.md`: active backlog / pending workflow improvements.
- `docs/references/`: non-code reference material (papers/protocol/team docs).

Data and outputs:
- `data/raw/`: immutable source inputs (assessment PDFs/templates/transcripts).
- `data/raw/lr_matrices/`: canonical active LR-matrix source workbooks by scenario.
- `data/processed/`: intermediate generated outputs (assessment answers, NNT/LR sheets).
- `data/processed/lr_differential/inputs/`: generated pairwise differential-LR input workbooks.
- `data/processed/lr_differential/outputs/`: canonical output path references in manifest rows.
- `data/processed/lr_differential/outputs_by_model/`: model-scoped differential-LR outputs (`<MODEL_ID>/<scenario_id>/*_filled.xlsx`).
- `data/processed/lr_differential/manifests/`: reproducibility manifests (`pairs_manifest.csv`, `run_manifest.json`).
- `data/processed/lr_differential/manifests/quality_summary.csv`: workbook-level validity audit output.
- `data/processed/lr_differential/manifests/invalid_rows.csv`: row-level invalid/missing LR audit output (repair input).
- `data/processed/lr_differential/manifests/invalid_rows_<MODEL_ID>.csv`: model-scoped audit output for targeted repair runs.
- `data/processed/lr_differential/manifests/run_ledger_differential_<MODEL_ID>.csv`: scenario-level resumable run ledger.
- `data/processed/lr_differential/manifests/logs/<MODEL_ID>/`: scenario-level run logs.
- `data/processed/lr_one_vs_rest/inputs/`: normalized one-vs-rest schema-sheet workbooks (`<scenario_id>_inputs.xlsx`).
- `data/processed/lr_one_vs_rest/manifests/schema_priors.csv`: per-schema long-form prior vectors (raw + normalized).
- `data/processed/lr_one_vs_rest/outputs_by_model/`: model-scoped one-vs-rest outputs (`<MODEL_ID>/<scenario_id>_filled.xlsx`).
- `data/processed/lr_one_vs_rest/coherent_outputs_by_model/`: model-scoped coherent one-vs-rest outputs (`<MODEL_ID>/<scenario_id>_coherent.xlsx`).
- `data/processed/lr_one_vs_rest/manifests/`: one-vs-rest manifests (`inputs_manifest.csv`, `run_manifest.json`, `quality_summary.csv`, `invalid_cells.csv`).
- `data/processed/lr_one_vs_rest/manifests/coherence_projection_*.csv`: projection summaries/top-row deltas/failures for coherent stage.
- `data/derived/`: final analysis-ready outputs (`.gitkeep` placeholder at present).
- `data/external/`: external downloaded assets + sidecars (`.gitkeep` placeholder at present).
- `artifacts/`: generated artifacts (`.gitkeep` placeholder at present).
- `reports/`: generated report outputs (`.gitkeep` placeholder at present).
- `notebooks/`: notebook-first analysis workflows (feature extraction, LR estimation, feedback generation).

Archived historical material:
- `archive/legacy_runs/`: historical run outputs (predominantly feedback-sheet spreadsheets and LR-estimation exports).
- `archive/legacy_external/`: older external/model artifacts retained for traceability.
- `archive/legacy_root_data/`: root-level historical spreadsheets migrated into archive.
- `archive/local_state/`: legacy local state retained intentionally.

Project scaffolding:
- `.github/workflows/ci.yml`: CI checks (`ruff format --check`, `ruff check`, `pytest`, `audit`).
- `.github/ISSUE_TEMPLATE/`, `.github/PULL_REQUEST_TEMPLATE.md`: collaboration templates.
- `config/config.example.yaml`: example path/config wiring for scripts/notebooks.
- `stata/`: optional non-interactive Stata template workflow.

## Working Rules
- Keep raw inputs immutable; write new outputs to `data/processed/`, `data/derived/`, `artifacts/`, or `reports/`.
- Keep paths repo-relative (use `src/dx_chat_entropy/paths.py` in Python code).
- Do not commit secrets or absolute local machine paths.
- Keep notebook outputs stripped unless intentionally required and documented.
- Keep comments concise and technical: explain intent/constraints, not obvious syntax.
- Prefer removing stale commented-out debug code before commit.
- Visualization and reasoning-evaluation notebooks have been migrated to a dedicated repository (see `docs/DECISIONS.md`).
