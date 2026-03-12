# Pipelines

This document is the canonical inventory of current workflows, with each
pipeline's purpose, primary inputs, primary outputs, and execution order.

## Pipeline inventory

### 1) Assessment feature + LR label pipeline (active)
- Purpose: extract findings from transcript PDFs and populate assessment LR sheets.
- Order:
  1. `notebooks/10_assessment_extract_features.ipynb`
  2. `notebooks/11_assessment_estimate_lrs.ipynb`
- Inputs:
  - `data/raw/chatbot_transcripts/*.pdf`
  - `data/raw/assessment_templates/asssessment_template_new.xlsx`
  - interim extracted answers from step 1
- Outputs:
  - `data/processed/assessments/answers_*.xlsx`
  - `data/processed/assessments/completed_lrs.xlsx`

### 2) Differential LR pipeline (active, canonical)
- Purpose: generate pairwise differential-LR inputs from raw LR matrices and estimate LR values by model.
- Order:
  1. `notebooks/20_differential_build_inputs.ipynb`
  2. `scripts/run_differential_batch.py` (canonical runtime)
  3. `notebooks/21_differential_estimate_lrs.ipynb` (interactive wrapper around step 2 runtime)
  4. `scripts/audit_differential_outputs.py` (quality gate)
- Inputs:
  - `config/lr_differential_scenarios.yaml`
  - `data/raw/lr_matrices/<scenario>/*.xlsx`
  - manifests and generated pair inputs from step 1
- Outputs:
  - `data/processed/lr_differential/inputs/<scenario_id>/*.xlsx`
  - `data/processed/lr_differential/outputs_by_model/<MODEL_ID>/<scenario_id>/*_filled.xlsx`
  - `data/processed/lr_differential/manifests/pairs_manifest.csv`
  - `data/processed/lr_differential/manifests/run_manifest.json`
  - `data/processed/lr_differential/manifests/quality_summary.csv`
  - `data/processed/lr_differential/manifests/invalid_rows.csv`
  - `data/processed/lr_differential/manifests/invalid_rows_<MODEL_ID>.csv`
  - `data/processed/lr_differential/manifests/run_ledger_differential_<MODEL_ID>.csv`
  - `data/processed/lr_differential/manifests/logs/<MODEL_ID>/*.log`
- Runtime controls:
  - `DX_RESUME_MODE=recompute|skip_passing|repair_invalid`
  - `DX_SCENARIO_FILTER`, `DX_MAX_PAIRS`, `DX_MAX_FINDINGS`
  - `DX_INVALID_ROWS_PATH` (optional override; default resolves model-scoped then generic)
- Validation defaults:
  - category-count mismatches fail closed by default during step 1
  - set `ALLOW_CATEGORY_COUNT_MISMATCH=true` only for intentional overrides
- Operational wrappers:
  - `scripts/run_differential_notebook_ledger.sh`: scenario-level resumable runs with logs/ledger
  - `scripts/run_differential_and_package.sh`: run + audit + package
  - `scripts/check_differential_bundle.py`: structural bundle gate

### 3) One-vs-rest LR pipeline (active, canonical script-first)
- Purpose: normalize LR matrices into one-vs-rest schema sheets, estimate raw LR cells,
  and project raw outputs to Bayes-coherent multiclass one-vs-rest LRs.
- Order:
  1. `scripts/build_one_vs_rest_inputs.py`
  2. `scripts/run_one_vs_rest_batch.py`
  3. `scripts/project_one_vs_rest_coherent_lrs.py`
  4. `scripts/audit_one_vs_rest_outputs.py` (quality gate; supports coherent mode)
- Inputs:
  - `config/lr_differential_scenarios.yaml`
  - `data/raw/lr_matrices/<scenario>/*.xlsx`
  - `data/processed/lr_one_vs_rest/manifests/inputs_manifest.csv` (execution source of truth)
- Outputs:
  - `data/processed/lr_one_vs_rest/inputs/<scenario_id>_inputs.xlsx`
  - `data/processed/lr_one_vs_rest/manifests/schema_priors.csv`
  - `data/processed/lr_one_vs_rest/outputs_by_model/<MODEL_ID>/<scenario_id>_filled.xlsx`
  - `data/processed/lr_one_vs_rest/coherent_outputs_by_model/<MODEL_ID>/<scenario_id>_coherent.xlsx`
  - `data/processed/lr_one_vs_rest/manifests/inputs_manifest.csv`
  - `data/processed/lr_one_vs_rest/manifests/run_manifest.json`
  - `data/processed/lr_one_vs_rest/manifests/quality_summary.csv`
  - `data/processed/lr_one_vs_rest/manifests/invalid_cells.csv`
  - `data/processed/lr_one_vs_rest/manifests/coherence_projection_summary_<MODEL_ID>.csv`
  - `data/processed/lr_one_vs_rest/manifests/coherence_projection_top_rows_<MODEL_ID>.csv`
  - `data/processed/lr_one_vs_rest/manifests/coherence_projection_failures_<MODEL_ID>.csv`
- One-time backward compatibility path:
  - `scripts/project_one_vs_rest_coherent_lrs.py --derive-priors-if-missing` can
    generate `schema_priors.csv` from existing manifests/source sheets and project
    already-generated raw outputs without rerunning LLM estimation.
- Validation defaults:
  - category-count mismatches fail closed by default in normalization
  - set `ALLOW_CATEGORY_COUNT_MISMATCH=true` only for intentional overrides

### 4) One-vs-rest agreement visualization pipeline (archive)
- Purpose: compare archived one-vs-rest LR outputs across models (KDE/Bland-Altman diagnostics).
- Order:
  1. `notebooks/30_one_vs_rest_estimate_lrs.ipynb` (archive matrix generation/reference)
  2. `notebooks/31_one_vs_rest_compare_lr_estimates.ipynb`
- Inputs:
  - `archive/legacy_runs/lr_estimation_2025_07_21/est_lrs_by_*.xlsx`
  - `archive/legacy_runs/lr_estimation_2025_07_21/columns_to_plot.xlsx`
- Outputs:
  - `archive/legacy_runs/lr_estimation_2025_07_21/est_lrs_by_*_filled.xlsx`
  - KDE/Bland-Altman PDFs in `archive/legacy_runs/lr_estimation_2025_07_21/`

## Non-pipeline notebooks

### `notebooks/22_differential_prepare_inputs_qa.ipynb`
- Purpose: QA/inspection for differential input preparation.
- Inputs: scenario config, canonical raw LR matrices, optional generated manifests/workbooks.
- Outputs: none (inspection only).

### `notebooks/32_one_vs_rest_project_coherent_lrs.ipynb`
- Purpose: notebook wrapper for coherent OVR projection over existing raw OVR outputs.
- Inputs: model-scoped raw one-vs-rest outputs + `schema_priors.csv`.
- Outputs: coherent workbooks + coherence projection summaries/failures under
  `data/processed/lr_one_vs_rest/`.

### `notebooks/feedback_generator.ipynb`
- Purpose: generate model feedback sheets from in-notebook diagnosis/category definitions.
- Inputs: in-notebook definitions and API responses.
- Outputs: `artifacts/feedback_sheets/<date>_<model>_feedback_sheets/*.xlsx`.
