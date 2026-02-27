# Continuity ledger

Use this file to maintain continuity across coding sessions.

## Current status
- Goal: Ensure notebook dependencies are explicitly declared and reproducible via `uv`.
- Last known good commit: Not recorded in this session.
- Next step: Run notebooks from the `notebooks` dependency group environment and prune unused imports over time.

## Session log

### 2026-02-27

**Objective:**
- Perform a quick repository-wide audit and explain file roles.
- Update `README.md` so it reflects the current structure and responsibilities.

**Plan:**
- Inventory tracked files and high-volume directories (`archive/`, `data/`, `notebooks/`).
- Review core code/docs/tests and compare with README claims.
- Patch README with an accurate repository map.
- Run standard checks (`make fmt`, `make lint`, `make test`, `make audit`).

**Work completed:**
- Audited tracked tree structure and key file roles across code, docs, data, archive, CI, and config.
- Updated `README.md` with current directory/file-role mappings and working rules.
- Confirmed large-file concentration is in `archive/legacy_runs` (historical outputs), while active code surface remains small (`src/`, `scripts/`, `tests/`, `notebooks/`).

**Verification:**
- `make fmt` passed.
- `make lint` passed.
- `make test` passed (`4` tests).
- `make audit` passed.

**Open questions / risks:**
- Whether to formalize policy for long-term retention vs pruning of historical archive artifacts.
- Whether untracked local folders (for example, `3b1b-wordle-solver/`) should be intentionally integrated, ignored, or removed locally.

### 2026-02-27 (notebook dependency reproducibility)

**Objective:**
- Fix missing notebook module imports (for example `markitdown`) by declaring notebook runtime dependencies in a reproducible way.

**Plan:**
- Extract imports from all tracked notebooks.
- Add a dedicated notebook dependency group in `pyproject.toml`.
- Lock dependencies in `uv.lock`.
- Add a policy test to ensure notebook imports are declared.
- Run full repo checks.

**Work completed:**
- Added `dependency-groups.notebooks` with third-party packages used across tracked notebooks.
- Added `make uv-sync-notebooks` helper target.
- Updated README notebook setup instructions and caveat for `pystata`/local Stata.
- Added `tests/test_notebook_dependencies.py` to enforce notebook import coverage and I/O engine dependencies.
- Updated `uv.lock` to pin notebook dependency resolution.
- Cleared retained error output from `notebooks/estimate_lrs.ipynb` to satisfy policy tests.

**Verification:**
- `make fmt` passed.
- `make lint` passed.
- `make test` passed (`7` tests).
- `make audit` passed.
- `uv run --group notebooks` import smoke for `estimate_lrs.ipynb` core imports passed (`MarkItDown`, `llm`, `OpenAI`, `pandas`, `numpy`).

**Open questions / risks:**
- The notebook dependency group is intentionally large and includes heavyweight ML packages; environment creation is slower.
- Some notebook cells importing `pystata` still require local Stata installation/licensing outside Python package management.
