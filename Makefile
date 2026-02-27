.DEFAULT_GOAL := help

.PHONY: help
help:
	@echo "Targets:"
	@echo "  uv-sync   Create/update local env"
	@echo "  uv-sync-notebooks   Create/update env with notebook deps"
	@echo "  fmt       Format code (ruff)"
	@echo "  lint      Lint code (ruff)"
	@echo "  test      Run unit tests (pytest)"
	@echo "  audit     Run repository policy audit"
	@echo "  clean     Remove caches / local build artifacts"

.PHONY: uv-sync
uv-sync:
	uv sync

.PHONY: uv-sync-notebooks
uv-sync-notebooks:
	uv sync --group notebooks

.PHONY: fmt
fmt:
	uv run ruff format src scripts tests

.PHONY: lint
lint:
	uv run ruff check src scripts tests

.PHONY: test
test:
	uv run pytest -q

.PHONY: audit
audit:
	uv run python scripts/audit_repo.py

.PHONY: clean
clean:
	@rm -rf .pytest_cache .ruff_cache __pycache__ */__pycache__ src/*/__pycache__
	@rm -rf dist build .venv
