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
This is a separate assessment workflow from the differential LR and legacy matrix
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

3. Open `notebooks/21_differential_estimate_lrs.ipynb`, select kernel `Python (dx-chat-entropy)`,
   and run all cells.
The notebook reads:
- `data/processed/lr_differential/manifests/pairs_manifest.csv`

The notebook writes:
- `data/processed/lr_differential/outputs_by_model/<MODEL_ID>/<scenario_id>/*_filled.xlsx`

4. Optional notebook controls in `21_differential_estimate_lrs.ipynb`:
- `SCENARIO_FILTER`: run only selected scenario IDs from the manifest.
- `MAX_PAIRS`: cap processed pairs for chunked/cost-controlled runs.
- `REPAIR_MODE=True`: patch only invalid rows listed in `invalid_rows.csv` for the active `MODEL_ID`.

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
- set `REPAIR_MODE=True` in `notebooks/21_differential_estimate_lrs.ipynb`
- keep `MODEL_ID` aligned with the failing model in `invalid_rows.csv`
- optionally set `REPAIR_SCENARIO_FILTER` and `REPAIR_MAX_ROWS`
- run the notebook, then re-run the audit command and require zero invalid/missing rows.

## Legacy Matrix Agreement Pipeline (Archive)
This is a separate, legacy workflow and is **not** part of the canonical differential LR
pipeline above.

1. Run `notebooks/30_one_vs_rest_estimate_lrs.ipynb` to fill archived matrix workbooks:
- `archive/legacy_runs/lr_estimation_2025_07_21/est_lrs_by_*_filled.xlsx`

2. Prepare `archive/legacy_runs/lr_estimation_2025_07_21/columns_to_plot.xlsx`
with the LR columns you want to compare across models.

3. Run `notebooks/31_legacy_matrix_compare_lr_estimates.ipynb` to generate agreement visualizations:
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
  - Pipeline role: legacy matrix-estimation step (archive workflow), upstream of `31_legacy_matrix_compare_lr_estimates.ipynb`
- `20_differential_build_inputs.ipynb`
  - Inputs: `config/lr_differential_scenarios.yaml` + canonical LR matrices in `data/raw/lr_matrices/`
  - Outputs: pair inputs in `data/processed/lr_differential/inputs/<scenario_id>/` and manifests in `data/processed/lr_differential/manifests/`
- `21_differential_estimate_lrs.ipynb`
  - Inputs: `data/processed/lr_differential/manifests/pairs_manifest.csv` and pair workbooks in `data/processed/lr_differential/inputs/<scenario_id>/`
  - Outputs: corresponding `*_filled.xlsx` workbooks in `data/processed/lr_differential/outputs_by_model/<MODEL_ID>/<scenario_id>/`
  - Run modes: full recompute mode and targeted repair mode driven by `manifests/invalid_rows.csv`
- `22_differential_prepare_inputs_qa.ipynb`
  - Inputs: `config/lr_differential_scenarios.yaml`, canonical raw LR matrices in `data/raw/lr_matrices/`, and optional generated manifests/workbooks
  - Outputs: none (QA/inspection notebook only)
- `31_legacy_matrix_compare_lr_estimates.ipynb`
  - Inputs: `archive/legacy_runs/lr_estimation_2025_07_21/columns_to_plot.xlsx`
  - Outputs: comparison plots/PDFs in `archive/legacy_runs/lr_estimation_2025_07_21/`
  - Pipeline role: legacy model-agreement QA/visualization step, downstream of matrix outputs and not consumed by canonical differential LR generation
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
- `src/dx_chat_entropy/lr_differential_audit.py`: reusable audit logic for workbook-level and row-level LR quality checks.
- `scripts/audit_repo.py`: policy scanner for absolute local paths, secret-like tokens, and retained notebook outputs.
- `scripts/audit_differential_outputs.py`: differential-LR quality gate (compares expected findings vs valid positive LR outputs).
- `tests/test_paths.py`: path utility invariants.
- `tests/test_repo_conventions.py`: policy tests for notebooks/docs.
- `tests/test_notebook_dependencies.py`: checks that notebook imports resolve.
- `tests/test_lr_differential_audit.py`: differential-LR audit behavior tests (classification and invalid-row detection).

Documentation and governance:
- `docs/PRINCIPLES.md`: scientific programming principles.
- `docs/DATA_MANAGEMENT.md`: data immutability and provenance rules.
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
