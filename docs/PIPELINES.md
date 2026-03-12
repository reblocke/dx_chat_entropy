# Pipeline Index

This file is a short navigation aid.

Use `README.md` for day-to-day understanding and run instructions.
Use `docs/SPECIFICATION.md` for exact inputs, outputs, manifests, validation rules, and bundle scope.

## Active Pipelines

### 1. Assessment Feature + LR Labeling
1. `notebooks/10_assessment_extract_features.ipynb`
2. `notebooks/11_assessment_estimate_lrs.ipynb`

### 2. Differential LR
1. `notebooks/20_differential_build_inputs.ipynb`
2. `scripts/run_differential_batch.py`
3. `notebooks/21_differential_estimate_lrs.ipynb`
4. `scripts/audit_differential_outputs.py`

Related QA notebook:
- `notebooks/22_differential_prepare_inputs_qa.ipynb`

### 3. One-vs-Rest LR + Coherence
1. `scripts/build_one_vs_rest_inputs.py`
2. `scripts/run_one_vs_rest_batch.py`
3. `scripts/project_one_vs_rest_coherent_lrs.py`
4. `scripts/audit_one_vs_rest_outputs.py`

Related notebook wrapper:
- `notebooks/32_one_vs_rest_project_coherent_lrs.ipynb`

## Archived Comparison Workflow

### 4. One-vs-Rest Agreement Visualization
1. `notebooks/30_one_vs_rest_estimate_lrs.ipynb`
2. `notebooks/31_one_vs_rest_compare_lr_estimates.ipynb`
