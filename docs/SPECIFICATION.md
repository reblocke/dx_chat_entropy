# Specification

This document is the detailed contract for the repository.

Use `README.md` for human-oriented onboarding and day-to-day run guidance.
Use this document when you need exact workflow order, artifact paths, notebook roles, validation behavior, or review-bundle scope.

## Conventions

- Active source data lives under `data/raw/`.
- Generated outputs live under `data/processed/`, `data/derived/`, `artifacts/`, or `reports/`.
- `archive/` is historical-only unless a workflow explicitly says otherwise.
- Paths are repo-relative in committed code and documentation.

## Pipeline Specifications

### 1. Assessment Feature + LR Label Pipeline

Purpose:
- Extract findings from transcript PDFs and populate assessment LR sheets.

Canonical order:
1. `notebooks/10_assessment_extract_features.ipynb`
2. `notebooks/11_assessment_estimate_lrs.ipynb`

Primary inputs:
- `data/raw/chatbot_transcripts/*.pdf`
- `data/raw/assessment_templates/asssessment_template_new.xlsx`

Primary outputs:
- `data/processed/assessments/answers_*.xlsx`
- `data/processed/assessments/completed_lrs.xlsx`

### 2. Differential LR Pipeline

Purpose:
- Generate pairwise differential-LR inputs from raw LR matrices and estimate LR values by model.

Canonical order:
1. `notebooks/20_differential_build_inputs.ipynb`
2. `scripts/run_differential_batch.py`
3. `notebooks/21_differential_estimate_lrs.ipynb`
4. `scripts/audit_differential_outputs.py`

Primary inputs:
- `config/lr_differential_scenarios.yaml`
- `data/raw/lr_matrices/<scenario>/*.xlsx`
- generated pair inputs and manifests from step 1

Primary outputs:
- `data/processed/lr_differential/inputs/<scenario_id>/*.xlsx`
- `data/processed/lr_differential/outputs_by_model/<MODEL_ID>/<scenario_id>/*_filled.xlsx`
- `data/processed/lr_differential/manifests/pairs_manifest.csv`
- `data/processed/lr_differential/manifests/run_manifest.json`
- `data/processed/lr_differential/manifests/quality_summary.csv`
- `data/processed/lr_differential/manifests/invalid_rows.csv`
- `data/processed/lr_differential/manifests/invalid_rows_<MODEL_ID>.csv`
- `data/processed/lr_differential/manifests/run_ledger_differential_<MODEL_ID>.csv`
- `data/processed/lr_differential/manifests/logs/<MODEL_ID>/*.log`

Canonical commands:

Build pair inputs:
- Run `notebooks/20_differential_build_inputs.ipynb`

Estimate via script:

```bash
DX_MODEL_ID=gpt-5.3-chat-latest \
DX_RESUME_MODE=skip_passing \
uv run --group notebooks python scripts/run_differential_batch.py
```

Audit:

```bash
uv run --group notebooks python scripts/audit_differential_outputs.py \
  --manifest data/processed/lr_differential/manifests/pairs_manifest.csv \
  --outputs-root data/processed/lr_differential/outputs_by_model \
  --summary-out data/processed/lr_differential/manifests/quality_summary.csv \
  --invalid-out data/processed/lr_differential/manifests/invalid_rows.csv
```

Runtime controls:
- `DX_RESUME_MODE=recompute|skip_passing|repair_invalid`
- `DX_SCENARIO_FILTER`
- `DX_MAX_PAIRS`
- `DX_MAX_FINDINGS`
- `DX_INVALID_ROWS_PATH`
- legacy compatibility: `DX_REPAIR_MODE=true` maps to `DX_RESUME_MODE=repair_invalid` when unset

Validation behavior:
- Category-count mismatches fail closed by default during step 1.
- Set `ALLOW_CATEGORY_COUNT_MISMATCH=true` only for intentional overrides.

Operational wrappers:
- `scripts/run_differential_notebook_ledger.sh`
- `scripts/run_differential_and_package.sh`
- `scripts/check_differential_bundle.py`

### 3. One-vs-Rest LR + Coherence Pipeline

Purpose:
- Normalize LR matrices into one-vs-rest schema sheets.
- Estimate raw one-vs-rest LR cells.
- Project raw outputs into Bayes-coherent multiclass one-vs-rest LRs.
- Audit both raw and coherent outputs.

Canonical order:
1. `scripts/build_one_vs_rest_inputs.py`
2. `scripts/run_one_vs_rest_batch.py`
3. `scripts/project_one_vs_rest_coherent_lrs.py`
4. `scripts/audit_one_vs_rest_outputs.py`

Primary inputs:
- `config/lr_differential_scenarios.yaml`
- `data/raw/lr_matrices/<scenario>/*.xlsx`
- `data/processed/lr_one_vs_rest/manifests/inputs_manifest.csv`

Primary outputs:
- `data/processed/lr_one_vs_rest/inputs/<scenario_id>_inputs.xlsx`
- `data/processed/lr_one_vs_rest/manifests/inputs_manifest.csv`
- `data/processed/lr_one_vs_rest/manifests/run_manifest.json`
- `data/processed/lr_one_vs_rest/manifests/schema_priors.csv`
- `data/processed/lr_one_vs_rest/outputs_by_model/<MODEL_ID>/<scenario_id>_filled.xlsx`
- `data/processed/lr_one_vs_rest/coherent_outputs_by_model/<MODEL_ID>/<scenario_id>_coherent.xlsx`
- `data/processed/lr_one_vs_rest/manifests/quality_summary.csv`
- `data/processed/lr_one_vs_rest/manifests/invalid_cells.csv`
- `data/processed/lr_one_vs_rest/manifests/coherence_projection_summary_<MODEL_ID>.csv`
- `data/processed/lr_one_vs_rest/manifests/coherence_projection_top_rows_<MODEL_ID>.csv`
- `data/processed/lr_one_vs_rest/manifests/coherence_projection_failures_<MODEL_ID>.csv`

Canonical commands:

Normalize inputs:

```bash
uv run --group notebooks python scripts/build_one_vs_rest_inputs.py \
  --config config/lr_differential_scenarios.yaml
```

Estimate raw one-vs-rest LRs:

```bash
uv run --group notebooks python scripts/run_one_vs_rest_batch.py \
  --manifest data/processed/lr_one_vs_rest/manifests/inputs_manifest.csv \
  --model-id gpt-4o-mini
```

Project coherent outputs:

```bash
uv run --group notebooks python scripts/project_one_vs_rest_coherent_lrs.py \
  --model-id gpt-4o-mini
```

Audit raw outputs:

```bash
uv run --group notebooks python scripts/audit_one_vs_rest_outputs.py \
  --manifest data/processed/lr_one_vs_rest/manifests/inputs_manifest.csv \
  --outputs-root data/processed/lr_one_vs_rest/outputs_by_model \
  --summary-out data/processed/lr_one_vs_rest/manifests/quality_summary.csv \
  --invalid-out data/processed/lr_one_vs_rest/manifests/invalid_cells.csv
```

Audit coherent outputs:

```bash
uv run --group notebooks python scripts/audit_one_vs_rest_outputs.py \
  --manifest data/processed/lr_one_vs_rest/manifests/inputs_manifest.csv \
  --coherence-mode \
  --priors-manifest data/processed/lr_one_vs_rest/manifests/schema_priors.csv \
  --raw-outputs-root data/processed/lr_one_vs_rest/outputs_by_model \
  --coherence-summary-out data/processed/lr_one_vs_rest/manifests/coherence_quality_summary.csv \
  --coherence-invalid-out data/processed/lr_one_vs_rest/manifests/coherence_invalid_rows.csv
```

Validation behavior:
- Category-count mismatches fail closed by default in normalization.
- Set `ALLOW_CATEGORY_COUNT_MISMATCH=true` only for intentional overrides.
- Partial coherent projection writes are blocked by default.
- `--overwrite` together with `--max-schemas` or `--max-findings` requires `--allow-partial-write`.

Backward-compatibility path:

```bash
uv run --group notebooks python scripts/project_one_vs_rest_coherent_lrs.py \
  --model-id gpt-5.3-chat-latest \
  --derive-priors-if-missing \
  --overwrite
```

This allows coherent projection over existing raw one-vs-rest outputs without rerunning LLM estimation.

### 4. One-vs-Rest Agreement Visualization Pipeline (Archive)

Purpose:
- Compare archived one-vs-rest LR outputs across models using KDE and Bland-Altman diagnostics.

Canonical order:
1. `notebooks/30_one_vs_rest_estimate_lrs.ipynb`
2. `notebooks/31_one_vs_rest_compare_lr_estimates.ipynb`

Primary inputs:
- `archive/legacy_runs/lr_estimation_2025_07_21/est_lrs_by_*.xlsx`
- `archive/legacy_runs/lr_estimation_2025_07_21/columns_to_plot.xlsx`

Primary outputs:
- `archive/legacy_runs/lr_estimation_2025_07_21/est_lrs_by_*_filled.xlsx`
- KDE and Bland-Altman PDFs in `archive/legacy_runs/lr_estimation_2025_07_21/`

## Review Bundle Specifications

### Differential Review Bundle

Primary wrapper:
- `scripts/run_differential_and_package.sh`

Declared scope:
- Includes code, manifests, logs, raw LR matrices, generated inputs, and model outputs required for review.
- Not a full repository snapshot.

### One-vs-Rest Review Bundle

Primary wrapper:
- `scripts/package_one_vs_rest_review_bundle.py`

Declared scope:
- Inspect bundled raw outputs.
- Project bundled raw outputs to coherent outputs.
- Audit bundled raw and coherent outputs.
- Inspect manifests and diagnostics.

Explicitly unsupported in review bundles:
- Rebuilding normalized inputs from omitted raw LR matrices.
- Regenerating raw one-vs-rest outputs with LLM calls.

Bundle contract file:
- `bundle_manifest.json`

## Non-Pipeline Notebooks

### `notebooks/22_differential_prepare_inputs_qa.ipynb`

Purpose:
- QA and inspection for differential input preparation.

Inputs:
- `config/lr_differential_scenarios.yaml`
- canonical raw LR matrices
- optional generated manifests and workbooks

Outputs:
- none

### `notebooks/32_one_vs_rest_project_coherent_lrs.ipynb`

Purpose:
- Notebook wrapper for coherent one-vs-rest projection over existing raw outputs.

Inputs:
- `data/processed/lr_one_vs_rest/outputs_by_model/<MODEL_ID>/<scenario_id>_filled.xlsx`
- `data/processed/lr_one_vs_rest/manifests/schema_priors.csv`

Outputs:
- coherent workbooks
- coherence projection diagnostics under `data/processed/lr_one_vs_rest/manifests/`

### `notebooks/feedback_generator.ipynb`

Purpose:
- Generate feedback sheets from in-notebook diagnosis/category definitions.

Outputs:
- `artifacts/feedback_sheets/<date>_<model>_feedback_sheets/*.xlsx`

## Notebook Inventory

- `notebooks/10_assessment_extract_features.ipynb`
  - Inputs: `data/raw/chatbot_transcripts/*.pdf`, `data/raw/assessment_templates/asssessment_template_new.xlsx`
  - Outputs: `data/processed/assessments/answers_*.xlsx`
- `notebooks/11_assessment_estimate_lrs.ipynb`
  - Inputs: assessment template plus processed answer sheets
  - Outputs: `data/processed/assessments/completed_lrs.xlsx`
- `notebooks/20_differential_build_inputs.ipynb`
  - Inputs: scenario config plus canonical LR matrices in `data/raw/lr_matrices/`
  - Outputs: differential pair inputs and manifests
- `notebooks/21_differential_estimate_lrs.ipynb`
  - Inputs: `pairs_manifest.csv` plus generated pair workbooks
  - Outputs: differential `*_filled.xlsx` workbooks under `outputs_by_model/`
- `notebooks/22_differential_prepare_inputs_qa.ipynb`
  - Inputs: config, raw LR matrices, optional generated manifests and workbooks
  - Outputs: none
- `notebooks/30_one_vs_rest_estimate_lrs.ipynb`
  - Inputs: archived `est_lrs_by_*.xlsx`
  - Outputs: archived `*_filled.xlsx`
- `notebooks/31_one_vs_rest_compare_lr_estimates.ipynb`
  - Inputs: archived `columns_to_plot.xlsx`
  - Outputs: archived comparison plots
- `notebooks/32_one_vs_rest_project_coherent_lrs.ipynb`
  - Inputs: raw one-vs-rest outputs plus `schema_priors.csv`
  - Outputs: coherent one-vs-rest outputs plus projection diagnostics
- `notebooks/feedback_generator.ipynb`
  - Inputs: in-notebook definitions and API responses
  - Outputs: feedback spreadsheets under `artifacts/feedback_sheets/`

## Repository and Data Map

Core files:
- `pyproject.toml`: package metadata, dependencies, Ruff, pytest config
- `uv.lock`: locked dependency set
- `Makefile`: `uv-sync`, `uv-sync-notebooks`, `notebook-kernel`, `fmt`, `lint`, `test`, `audit`
- `README.md`: human-oriented overview and run guide
- `docs/SPECIFICATION.md`: detailed workflow and artifact contract
- `docs/DECISIONS.md`: design and workflow decisions

Code:
- `src/dx_chat_entropy/`: importable runtime and utility modules
- `scripts/`: orchestration, audits, packaging, and review-bundle checkers
- `tests/`: unit and integration tests
- `notebooks/`: notebook workflows and wrappers

Data:
- `data/raw/`: immutable active inputs
- `data/raw/lr_matrices/`: canonical active LR-matrix workbooks
- `data/processed/lr_differential/`: differential inputs, outputs, manifests, logs
- `data/processed/lr_one_vs_rest/`: normalized inputs, raw outputs, coherent outputs, manifests
- `data/processed/assessments/`: assessment pipeline outputs
- `archive/`: historical-only runs, spreadsheets, and legacy data

Generated artifact contracts:
- Differential outputs live under `data/processed/lr_differential/outputs_by_model/<MODEL_ID>/`
- One-vs-rest raw outputs live under `data/processed/lr_one_vs_rest/outputs_by_model/<MODEL_ID>/`
- One-vs-rest coherent outputs live under `data/processed/lr_one_vs_rest/coherent_outputs_by_model/<MODEL_ID>/`
- Differential audit targets live under `data/processed/lr_differential/manifests/`
- One-vs-rest audit and coherence diagnostics live under `data/processed/lr_one_vs_rest/manifests/`

## Usage Rules

- Keep raw inputs immutable.
- Write new outputs to generated-output locations, not back into source files.
- Treat `archive/` as historical unless a workflow explicitly points there.
- Keep committed paths repo-relative.
