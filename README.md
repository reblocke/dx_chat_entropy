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

Launch a notebook kernel with that group:

```bash
uv run --group notebooks python -m ipykernel install --user --name dx-chat-entropy
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
