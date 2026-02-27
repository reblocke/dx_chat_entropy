# dx_chat_entropy
Code to analyze clinical-reasoning efficiency via chat bot.

This repository combines project-specific clinical reasoning analyses with a reproducible scientific Python project structure.

## What This Repo Contains
- Clinical reasoning analysis notebooks (Bayesian/entropy workflows)
- Assessment templates, transcripts, and derived LR artifacts
- Reproducibility and governance scaffolding for agent-assisted coding

## Quickstart
Prerequisites:
- Python 3.11+
- `uv` installed

From repo root:

```bash
uv sync
make fmt
make lint
make test
make audit
```

Notes:
- `uv` is the primary environment manager for reproducibility.
- Conda users can still run notebooks, but dependency changes should be recorded in `pyproject.toml`.

## Repository Layout
- `src/dx_chat_entropy/` reusable Python utilities
- `scripts/` repo tooling and audit scripts
- `tests/` unit and policy tests
- `notebooks/` analysis notebooks (migrated from root/legacy locations)
- `data/`
  - `raw/` immutable project inputs
  - `external/` downloaded/reference external assets + provenance sidecars
  - `processed/` intermediate/generated datasets
  - `derived/` final analysis-ready outputs
- `artifacts/` generated run artifacts
- `reports/` publication/report outputs
- `docs/` project docs, policies, and references
- `archive/` in-repo archived legacy runs/data/external/local state

## Agent Workflow
Start with:
- `AGENTS.md`
- `CONTINUITY.md`
- `docs/CODEX_WORKFLOW.md`
- `docs/DECISIONS.md`

## Reproducibility Rules
- No hard-coded absolute local paths in committed code/notebooks.
- Keep secrets in `.env` (never committed).
- Use repo-relative paths via `src/dx_chat_entropy/paths.py`.
- Keep raw data immutable; write outputs to `data/processed`, `data/derived`, `artifacts`, or `reports`.
