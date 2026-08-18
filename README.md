# dx_chat_entropy

[![CI](https://github.com/reblocke/dx_chat_entropy/actions/workflows/ci.yml/badge.svg)](https://github.com/reblocke/dx_chat_entropy/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CITATION.cff](https://img.shields.io/badge/citation-CFF%201.2-blue)](CITATION.cff)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](pyproject.toml)

`dx_chat_entropy` is a Python-first research repository for estimating, auditing, and
comparing likelihood ratios (LRs) in clinical diagnostic-reasoning tasks. It supports
transcript-to-assessment workflows, pairwise differential LR estimation, and one-vs-rest LR
estimation with a Bayes-coherent projection step.

The manuscript associated with this work is under journal review. It is not accepted or
published, and there is no public article DOI, PMID, PMCID, volume, issue, or page/article
number to cite yet. Until a public scholarly record exists, cite the repository software and
the commit or release used.

## Start Here

Prerequisites:
- Python 3.11+
- `uv`
- `OPENAI_API_KEY` exported in the process environment for real OpenAI-backed runs

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

## Project Status

This public repository contains research software, public workflow inputs, and generated
aggregate/model-output artifacts needed to inspect the current analysis workflow. It does
not contain an accepted manuscript, a public preprint, publisher text, private reviewer
materials, API keys, or local machine state.

The internal preprint/manuscript draft is intentionally not mirrored here. When a public
preprint, accepted manuscript, or final article appears, update `README.md`, `llms.txt`,
`CITATION.cff`, and GitHub metadata in the same pull request.

## Authors, Affiliations, Funding, And COI

Maintainer and corresponding repository contact:
- Brian W. Locke, MD; ORCID: [0000-0002-3588-5238](https://orcid.org/0000-0002-3588-5238);
  GitHub: [@reblocke](https://github.com/reblocke)

Author order, affiliations, funding, acknowledgments, and conflicts of interest should be
taken from the eventual public manuscript record when it exists. Do not infer or publish
unverified publication metadata from private drafts.

## Repository Shape

- `config/`: scenario registries and workflow configuration
- `data/raw/`: active public source spreadsheets, transcript PDFs, and assessment templates
- `data/processed/`: generated manifests, intermediate workbooks, and model outputs retained
  for review of the current workflow
- `notebooks/`: interactive entry points, QA notebooks, and older analysis notebooks
- `scripts/`: canonical batch runtimes, audit tools, and packaging tools
- `src/dx_chat_entropy/`: shared parsing, runtime, audit, and bundle logic
- `docs/`: specifications, design decisions, pipeline notes, and data-management policy
- `archive/`: historical source code, run notes, and legacy provenance material that is not
  part of the active workflow unless explicitly named by a script

In general, the scripts are the canonical batch entry points. The notebooks are for
interactive execution, QA, or older workflows that are still kept for reference.

## Data And Privacy Boundaries

Committed active inputs are clinical-reasoning scenarios, LR matrices, assessment templates,
and transcript artifacts used by the current workflow. Do not add private manuscript drafts,
private reviewer materials, personal correspondence, API outputs containing secrets, local
machine state, or third-party/publisher PDFs.

For machine-readable variable and artifact documentation, see:
- `data_dictionary.md`
- `data_dictionary.csv`
- `docs/SPECIFICATION.md`
- `docs/DATA_MANAGEMENT.md`

If a raw source has a defect, do not edit it in place. Preserve the raw file and correct the
issue in code or in a generated output layer.

## Choose A Workflow

If you are not sure which path you need:
- use the assessment workflow to turn transcripts into assessment workbooks,
- use the differential workflow when each finding should compare two diagnoses at a time,
- use the one-vs-rest workflow when you want a full diagnosis-by-finding LR table plus a
  coherent version of that table.

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

Use this when each scenario should be broken into all diagnosis-pair comparisons and each
finding should receive a differential LR for that pair.

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
- `21_differential_estimate_lrs.ipynb` is the interactive wrapper around the same runtime
  logic used by the script.
- `22_differential_prepare_inputs_qa.ipynb` is for inspection and QA, not the canonical
  transformation step.

### 3. One-vs-Rest LR + Coherence Pipeline

Use this when you want a full LR table for each diagnosis versus all others in a scenario,
followed by a coherence step that converts independently estimated one-vs-rest LRs into a
Bayes-coherent multiclass version.

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
- The coherence step is a separate local projection stage. It does not overwrite the raw
  one-vs-rest outputs.
- `notebooks/32_one_vs_rest_project_coherent_lrs.ipynb` is a notebook wrapper for the
  coherence projection over existing raw outputs.
- `notebooks/30_one_vs_rest_estimate_lrs.ipynb` and
  `notebooks/31_one_vs_rest_compare_lr_estimates.ipynb` are the older comparison workflow,
  not the canonical batch runtime.

### 4. Restartable Feedback Generation

Use this workflow to generate ranked information-gathering feedback across the frozen
CREST/achalasia diagnosis inventory. The script builds every request before execution,
checkpoints one validated response per request, resumes by request identity, and creates
Excel workbooks only from stored validated records.

Safe local validation makes no network or paid provider call:

```bash
make feedback-manifest
make feedback-smoke
make feedback-materialize
make feedback-audit
```

The default manifest contains 110 requests over the combined subjective/historical
category. The expanded six-category contract contains 660 requests. Runtime artifacts live
under `artifacts/feedback_sheets/runs/<run_id>/` and are ignored by Git.

A real provider run is deliberately cost-gated:

```bash
export OPENAI_API_KEY="..."
CONFIRM_PAID_RUN=1 make feedback-run
```

The feedback CLI reads `OPENAI_API_KEY` from the process environment; it does not load
`.env` automatically. If you keep the key in a local ignored `.env`, source that file into
the shell before running the command. Manifest, smoke, materialization, and audit commands
do not require an API key and make no provider call.

Use `scripts/run_feedback_pipeline.py run --help` for request filters, worker limits, and
`skip_passing`, `repair_invalid`, or `recompute` behavior. The default is four workers and
`skip_passing`. `notebooks/feedback_generator.ipynb` only inspects local configuration and
run summaries; it never calls a provider.

Feedback rankings and explanations are model outputs for research review. They are not
empirical clinical evidence, reference-standard labels, or patient-care recommendations.

## Review Bundles

For external review or handoff:
- Differential pipeline: `scripts/run_differential_and_package.sh`
- One-vs-rest pipeline: `scripts/package_one_vs_rest_review_bundle.py`

These packages are meant to ship the relevant code, manifests, and outputs for a workflow.
They are not full-repository snapshots and should not include private manuscript drafts,
API keys, or local system state.

## Dependencies

Core package dependencies are declared in `pyproject.toml`. Use the `notebooks` dependency
group for model-backed notebook and batch runs.

| Use | Command | Notes |
| --- | --- | --- |
| Core development | `uv sync` | Installs package, tests, and lint tooling. |
| Notebook/model workflows | `make uv-sync-notebooks` | Installs the `notebooks` dependency group. |
| Notebook kernel | `make notebook-kernel` | Registers `Python (dx-chat-entropy)`. |
| Repository checks | `make fmt && make lint && make test && make audit` | Run before PRs. |

## Documentation Map

Use the document that matches the question:
- `llms.txt`: compact machine-readable index for LLMs and search systems
- `README.md`: what this repo does, which workflow to choose, and how to run it
- `data_dictionary.md` and `data_dictionary.csv`: source, derived, and output artifact dictionary
- `docs/SPECIFICATION.md`: detailed pipeline contracts, artifact paths, manifests, and review-bundle scope
- `docs/PIPELINES.md`: short index of current pipelines and notebook/script order
- `docs/DATA_MANAGEMENT.md`: active-vs-archive data placement and provenance rules
- `docs/DECISIONS.md`: non-obvious design and policy decisions
- `AGENTS.md`: project-specific coding-agent instructions

## Citation

Until a public paper, preprint, or conference record exists, cite the repository software:

```text
Locke BW. dx_chat_entropy: Clinical reasoning entropy and likelihood-ratio workflows.
GitHub. https://github.com/reblocke/dx_chat_entropy. Commit or release used.
```

Machine-readable citation metadata are in `CITATION.cff`. Do not add a
`preferred-citation` for the manuscript until the public scholarly record exists.

## License

Repository code is released under the MIT License. Third-party materials, clinical source
documents, private drafts, publisher artifacts, and externally supplied data remain under
their original terms and should not be copied into the public branch unless their public
license and provenance are documented.

## Common Problems

### Notebook imports fail even after syncing dependencies

Usually the notebook is attached to the wrong interpreter.

Fix:
1. Run `make uv-sync-notebooks`
2. Run `make notebook-kernel`
3. In VS Code, switch to `Python (dx-chat-entropy)`
4. Restart the kernel

### A script or notebook is still reading from `archive/`

Treat that as a migration or legacy-path issue. Active workflows should read from
`data/raw/` and write to `data/processed/` unless the workflow is explicitly labeled archival.

## Contact

Use GitHub issues or pull requests for repository-specific questions. For publication or
data-access questions, contact Brian W. Locke through the contact route listed on his
public GitHub profile or CV.
