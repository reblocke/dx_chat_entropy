.DEFAULT_GOAL := help

.PHONY: help
help:
	@echo "Targets:"
	@echo "  uv-sync   Create/update local env"
	@echo "  uv-sync-notebooks   Create/update env with notebook deps"
	@echo "  notebook-kernel   Register local Jupyter kernel for this repo"
	@echo "  fmt       Format code (ruff)"
	@echo "  lint      Lint code (ruff)"
	@echo "  test      Run unit tests (pytest)"
	@echo "  audit     Run repository policy audit"
	@echo "  feedback-manifest   Build the deterministic feedback request manifest (no network)"
	@echo "  feedback-smoke      Run the deterministic fake-provider smoke workflow (no network)"
	@echo "  feedback-run        Execute a paid provider run (requires CONFIRM_PAID_RUN=1)"
	@echo "  feedback-materialize   Build workbooks from validated local response records"
	@echo "  feedback-audit      Audit a local feedback run (no network)"
	@echo "  clean     Remove caches / local build artifacts"

.PHONY: uv-sync
uv-sync:
	uv sync

.PHONY: uv-sync-notebooks
uv-sync-notebooks:
	uv sync --group notebooks

.PHONY: notebook-kernel
notebook-kernel:
	uv run --group notebooks python -m ipykernel install --user --name dx-chat-entropy --display-name "Python (dx-chat-entropy)"

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

FEEDBACK_CONFIG ?= config/feedback_generation.yaml
FEEDBACK_RUNS_ROOT ?= artifacts/feedback_sheets/runs
FEEDBACK_RUN_ID ?=

.PHONY: feedback-manifest
feedback-manifest:
	uv run python scripts/run_feedback_pipeline.py manifest --config $(FEEDBACK_CONFIG) --runs-root $(FEEDBACK_RUNS_ROOT)

.PHONY: feedback-smoke
feedback-smoke:
	uv run python scripts/run_feedback_pipeline.py smoke --config $(FEEDBACK_CONFIG) --runs-root $(FEEDBACK_RUNS_ROOT)

.PHONY: feedback-run
feedback-run:
	@test "$(CONFIRM_PAID_RUN)" = "1" || (echo "Refusing paid run: set CONFIRM_PAID_RUN=1" && exit 2)
	uv run --group notebooks python scripts/run_feedback_pipeline.py run --config $(FEEDBACK_CONFIG) --runs-root $(FEEDBACK_RUNS_ROOT) $(if $(FEEDBACK_RUN_ID),--run-id $(FEEDBACK_RUN_ID),)

.PHONY: feedback-materialize
feedback-materialize:
	uv run python scripts/run_feedback_pipeline.py materialize --runs-root $(FEEDBACK_RUNS_ROOT) $(if $(FEEDBACK_RUN_ID),--run-id $(FEEDBACK_RUN_ID),--latest-smoke)

.PHONY: feedback-audit
feedback-audit:
	uv run python scripts/run_feedback_pipeline.py audit --runs-root $(FEEDBACK_RUNS_ROOT) $(if $(FEEDBACK_RUN_ID),--run-id $(FEEDBACK_RUN_ID),--latest-smoke)

.PHONY: clean
clean:
	@rm -rf .pytest_cache .ruff_cache __pycache__ */__pycache__ src/*/__pycache__
	@rm -rf dist build .venv
