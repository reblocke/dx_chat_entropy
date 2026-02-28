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

## Repository Map
Core project files:
- `pyproject.toml`: package metadata, dependencies, notebook dependency group, Ruff, and pytest config.
- `uv.lock`: locked dependency set for reproducible environments.
- `Makefile`: standard local commands (`fmt`, `lint`, `test`, `audit`, `uv-sync`, `clean`).
- `AGENTS.md`: engineering and workflow rules for coding agents.
- `CONTINUITY.md`: session ledger for ongoing continuity.
- `CONTRIBUTING.md`: contribution and definition-of-done checklist.
- `CITATION.cff`: software citation metadata.

Code and checks:
- `src/dx_chat_entropy/__init__.py`: package exports.
- `src/dx_chat_entropy/paths.py`: repository-root discovery and canonical path helpers.
- `scripts/audit_repo.py`: policy scanner for absolute local paths, secret-like tokens, and retained notebook outputs.
- `tests/test_paths.py`: path utility invariants.
- `tests/test_repo_conventions.py`: policy tests for notebooks/docs.

Documentation and governance:
- `docs/PRINCIPLES.md`: scientific programming principles.
- `docs/DATA_MANAGEMENT.md`: data immutability and provenance rules.
- `docs/AI_ASSISTED_CODING.md`: guardrails for AI-authored changes.
- `docs/CODEX_WORKFLOW.md`: agent workflow loop.
- `docs/DECISIONS.md`: decision log.
- `docs/references/`: non-code reference material (papers/protocol/team docs).

Data and outputs:
- `data/raw/`: immutable source inputs (assessment PDFs/templates/transcripts).
- `data/processed/`: intermediate generated outputs (assessment answers, NNT/LR sheets).
- `data/derived/`: final analysis-ready outputs (`.gitkeep` placeholder at present).
- `data/external/`: external downloaded assets + sidecars (`.gitkeep` placeholder at present).
- `artifacts/`: generated artifacts (`.gitkeep` placeholder at present).
- `reports/display_reasoning.html`: committed report output example.
- `notebooks/`: notebook-first analysis workflows (reasoning evaluation, feature extraction, LR estimation, feedback generation).

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
- Some notebooks import `pystata`; those cells still require local Stata installation/licensing.
