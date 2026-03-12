# dx_chat_entropy

`dx_chat_entropy` is a Python-first repository for estimating, auditing, and comparing
likelihood ratios (LRs) for clinical reasoning tasks from transcripts and scenario spreadsheets.

In practice, the repo supports three main jobs:
1. extract findings and populate assessment sheets,
2. estimate pairwise differential LRs from scenario spreadsheets, and
3. estimate one-vs-rest LRs and project them into Bayes-coherent multiclass outputs.

The repository mixes active workflows with archived historical material. For current work,
use `data/raw/`, `data/processed/`, `scripts/`, and the numbered notebooks. Treat `archive/`
as provenance unless a workflow explicitly says otherwise.

## Start Here

Prerequisites:
- Python 3.11+
- `uv`
- `OPENAI_API_KEY` in your environment or `.env` for model-backed runs

Initial setup:

```bash
make uv-sync-notebooks
make notebook-kernel
make fmt
make lint
make test
make audit
```

If you use VS Code notebooks, select the kernel `Python (dx-chat-entropy)`.
Most notebook import problems in this repo are kernel-selection problems rather than missing packages.

## Repository Shape

- `data/raw/`: active source spreadsheets, transcripts, and templates
- `data/processed/`: generated manifests, intermediate workbooks, and model outputs
- `notebooks/`: interactive entry points, QA, and legacy analysis notebooks
- `scripts/`: canonical batch runtimes and packaging tools
- `src/dx_chat_entropy/`: shared parsing, runtime, audit, and bundle logic
- `archive/`: historical inputs, runs, tickets, and legacy outputs

In general, the scripts are the canonical batch entry points. The notebooks are for
interactive execution, QA, or older workflows that are still kept for reference.

## Choose a Workflow

If you are not sure which path you need:
- use the assessment workflow to turn transcripts into assessment workbooks,
- use the differential workflow when each finding should compare two diagnoses at a time,
- use the one-vs-rest workflow when you want a full diagnosis-by-finding LR table plus a coherent version of that table.

### 1. Assessment Feature + LR Labeling

Use this when you want to extract findings from transcript PDFs and populate the assessment workbook.

Run order:
1. `notebooks/10_assessment_extract_features.ipynb`
2. `notebooks/11_assessment_estimate_lrs.ipynb`

Inputs:
- `data/raw/chatbot_transcripts/*.pdf`
- `data/raw/assessment_templates/asssessment_template_new.xlsx`

Outputs:
- `data/processed/assessments/answers_*.xlsx`
- `data/processed/assessments/completed_lrs.xlsx`

### 2. Differential LR Pipeline

Use this when each scenario should be broken into all diagnosis-pair comparisons and each finding should receive a differential LR for that pair.

Run order:
1. `notebooks/20_differential_build_inputs.ipynb`
2. `scripts/run_differential_batch.py` or `notebooks/21_differential_estimate_lrs.ipynb`
3. `scripts/audit_differential_outputs.py`

Example run:

```bash
DX_MODEL_ID=gpt-5.3-chat-latest \
DX_RESUME_MODE=skip_passing \
uv run --group notebooks python scripts/run_differential_batch.py

uv run --group notebooks python scripts/audit_differential_outputs.py \
  --manifest data/processed/lr_differential/manifests/pairs_manifest.csv \
  --outputs-root data/processed/lr_differential/outputs_by_model \
  --summary-out data/processed/lr_differential/manifests/quality_summary.csv \
  --invalid-out data/processed/lr_differential/manifests/invalid_rows.csv
```

Inputs:
- canonical raw LR matrices under `data/raw/lr_matrices/`
- scenario registry in `config/lr_differential_scenarios.yaml`

Outputs:
- pairwise input workbooks in `data/processed/lr_differential/inputs/`
- model-scoped filled outputs in `data/processed/lr_differential/outputs_by_model/`
- manifests, ledgers, logs, and audit CSVs in `data/processed/lr_differential/manifests/`

Notes:
- The model ID in the example is illustrative; swap in the model you actually want to run.
- `21_differential_estimate_lrs.ipynb` is the interactive wrapper around the same runtime logic used by the script.
- `22_differential_prepare_inputs_qa.ipynb` is for inspection and QA, not the canonical transformation step.

### 3. One-vs-Rest LR + Coherence Pipeline

Use this when you want a full LR table for each diagnosis versus all others in a scenario, followed by a coherence step that converts independently estimated one-vs-rest LRs into a Bayes-coherent multiclass version.

Run order:
1. `scripts/build_one_vs_rest_inputs.py`
2. `scripts/run_one_vs_rest_batch.py`
3. `scripts/project_one_vs_rest_coherent_lrs.py`
4. `scripts/audit_one_vs_rest_outputs.py`

Example run:

```bash
uv run --group notebooks python scripts/build_one_vs_rest_inputs.py \
  --config config/lr_differential_scenarios.yaml

uv run --group notebooks python scripts/run_one_vs_rest_batch.py \
  --manifest data/processed/lr_one_vs_rest/manifests/inputs_manifest.csv \
  --model-id gpt-5.3-chat-latest

uv run --group notebooks python scripts/project_one_vs_rest_coherent_lrs.py \
  --model-id gpt-5.3-chat-latest

# audit raw outputs
uv run --group notebooks python scripts/audit_one_vs_rest_outputs.py \
  --manifest data/processed/lr_one_vs_rest/manifests/inputs_manifest.csv \
  --outputs-root data/processed/lr_one_vs_rest/outputs_by_model \
  --summary-out data/processed/lr_one_vs_rest/manifests/quality_summary_gpt-5.3-chat-latest.csv \
  --invalid-out data/processed/lr_one_vs_rest/manifests/invalid_cells_gpt-5.3-chat-latest.csv \
  --model-id gpt-5.3-chat-latest

# audit coherent outputs
uv run --group notebooks python scripts/audit_one_vs_rest_outputs.py \
  --manifest data/processed/lr_one_vs_rest/manifests/inputs_manifest.csv \
  --coherence-mode \
  --priors-manifest data/processed/lr_one_vs_rest/manifests/schema_priors.csv \
  --raw-outputs-root data/processed/lr_one_vs_rest/outputs_by_model \
  --outputs-root data/processed/lr_one_vs_rest/coherent_outputs_by_model \
  --summary-out data/processed/lr_one_vs_rest/manifests/coherent_quality_summary_gpt-5.3-chat-latest.csv \
  --invalid-out data/processed/lr_one_vs_rest/manifests/coherent_invalid_cells_gpt-5.3-chat-latest.csv \
  --coherence-summary-out data/processed/lr_one_vs_rest/manifests/coherence_quality_summary_gpt-5.3-chat-latest.csv \
  --coherence-invalid-out data/processed/lr_one_vs_rest/manifests/coherence_invalid_rows_gpt-5.3-chat-latest.csv \
  --model-id gpt-5.3-chat-latest
```

Inputs:
- raw LR matrices in `data/raw/lr_matrices/`
- scenario registry in `config/lr_differential_scenarios.yaml`

Outputs:
- normalized one-vs-rest input workbooks in `data/processed/lr_one_vs_rest/inputs/`
- raw model outputs in `data/processed/lr_one_vs_rest/outputs_by_model/`
- coherent outputs in `data/processed/lr_one_vs_rest/coherent_outputs_by_model/`
- manifests and quality summaries in `data/processed/lr_one_vs_rest/manifests/`

Notes:
- The model ID in the example is illustrative; swap in the model you actually want to run.
- The coherence step is a separate local projection stage. It does not overwrite the raw one-vs-rest outputs.
- `notebooks/32_one_vs_rest_project_coherent_lrs.ipynb` is a notebook wrapper for the coherence projection over existing raw outputs.
- `notebooks/30_one_vs_rest_estimate_lrs.ipynb` and `notebooks/31_one_vs_rest_compare_lr_estimates.ipynb` are the older comparison workflow, not the canonical batch runtime.

## Review Bundles

For external review or handoff:
- Differential pipeline: `scripts/run_differential_and_package.sh`
- One-vs-rest pipeline: `scripts/package_one_vs_rest_review_bundle.py`

These packages are meant to ship the relevant code, manifests, and outputs for a workflow. They are not full-repository snapshots.

## Where Data Should Live

- Put active source spreadsheets in `data/raw/`.
- Put generated workbooks and manifests in `data/processed/`.
- Keep final analysis artifacts in `data/derived/`, `reports/`, or `artifacts/` as appropriate.
- Keep historical material in `archive/`.

If a raw source has a defect, do not edit it in place. Preserve the raw file and correct the issue in code or in a generated output layer.

## Documentation Map

Use the document that matches the question:
- `README.md`: what this repo does, which workflow to choose, and how to run it
- `docs/SPECIFICATION.md`: detailed pipeline contracts, artifact paths, manifests, and review-bundle scope
- `docs/PIPELINES.md`: short index of current pipelines and notebook/script order
- `docs/DATA_MANAGEMENT.md`: active-vs-archive data placement and provenance rules
- `docs/DECISIONS.md`: non-obvious design and policy decisions
- `AGENTS.md`: project-specific coding-agent instructions

## Common Problems

### Notebook imports fail even after syncing dependencies

Usually the notebook is attached to the wrong interpreter.

Fix:
1. Run `make uv-sync-notebooks`
2. Run `make notebook-kernel`
3. In VS Code, switch to `Python (dx-chat-entropy)`
4. Restart the kernel

### A script or notebook is still reading from `archive/`

Treat that as a migration or legacy-path issue. Active workflows should read from `data/raw/` and write to `data/processed/` unless the workflow is explicitly labeled archival.
