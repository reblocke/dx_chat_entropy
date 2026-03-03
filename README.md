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

## Notebook Execution (VS Code)
Use this flow for notebooks such as `notebooks/estimate_lrs.ipynb`.

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

## Notebook Inventory (Inputs/Outputs)
Current tracked notebooks in `notebooks/` and their expected file I/O:

- `extract_features.ipynb`
  - Inputs: `data/raw/chatbot_transcripts/*.pdf`, `data/raw/assessment_templates/asssessment_template_new.xlsx`
  - Outputs: `data/processed/assessments/answers_*.xlsx`
- `estimate_lrs.ipynb`
  - Inputs: `data/raw/assessment_templates/asssessment_template_new.xlsx` (+ processed assessment answer sheets)
  - Outputs: `data/processed/assessments/completed_lrs.xlsx`
- `estimate_lrs_matrix.ipynb`
  - Inputs: `archive/legacy_runs/lr_estimation_2025_07_21/est_lrs_by_*.xlsx`
  - Outputs: `archive/legacy_runs/lr_estimation_2025_07_21/est_lrs_by_*_filled.xlsx`
- `estimate_differential_lrs.ipynb`
  - Inputs: differential LR workbooks in `archive/legacy_runs/lr_estimation_2025_07_21/`
  - Outputs: corresponding `*_filled.xlsx` workbooks in the same directory
- `compare_lr_estimates.ipynb`
  - Inputs: `archive/legacy_runs/lr_estimation_2025_07_21/columns_to_plot.xlsx`
  - Outputs: comparison plots/PDFs in `archive/legacy_runs/lr_estimation_2025_07_21/`
- `feedback_generator.ipynb`
  - Inputs: in-notebook diagnosis/category definitions and API responses
  - Outputs: `artifacts/feedback_sheets/<date>_<model>_feedback_sheets/*.xlsx`

## Repository Map
Core project files:
- `pyproject.toml`: package metadata, dependencies, notebook dependency group, Ruff, and pytest config.
- `uv.lock`: locked dependency set for reproducible environments.
- `Makefile`: standard local commands (`uv-sync`, `uv-sync-notebooks`, `notebook-kernel`, `fmt`, `lint`, `test`, `audit`, `clean`).
- `CLAUDE.md`: engineering and workflow rules for Claude Code.
- `CONTRIBUTING.md`: contribution and definition-of-done checklist.
- `CITATION.cff`: software citation metadata.

Code and checks:
- `src/dx_chat_entropy/__init__.py`: package exports.
- `src/dx_chat_entropy/paths.py`: repository-root discovery and canonical path helpers.
- `scripts/audit_repo.py`: policy scanner for absolute local paths, secret-like tokens, and retained notebook outputs.
- `tests/test_paths.py`: path utility invariants.
- `tests/test_repo_conventions.py`: policy tests for notebooks/docs.
- `tests/test_notebook_dependencies.py`: checks that notebook imports resolve.

Documentation and governance:
- `docs/PRINCIPLES.md`: scientific programming principles.
- `docs/DATA_MANAGEMENT.md`: data immutability and provenance rules.
- `docs/AI_ASSISTED_CODING.md`: guardrails for AI-authored changes.
- `docs/CLAUDE_WORKFLOW.md`: agent workflow loop.
- `docs/DECISIONS.md`: decision log.
- `docs/references/`: non-code reference material (papers/protocol/team docs).

Data and outputs:
- `data/raw/`: immutable source inputs (assessment PDFs/templates/transcripts).
- `data/processed/`: intermediate generated outputs (assessment answers, NNT/LR sheets).
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
