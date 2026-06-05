# Data Dictionary

This dictionary documents the public artifact schemas and major variables used by
`dx_chat_entropy`. The repository works with heterogeneous Excel workbooks, transcript PDFs,
model-generated LR workbooks, and CSV/JSON manifests, so the dictionary is organized around
artifact families and workflow fields rather than a single rectangular study dataset.

The machine-readable companion is `data_dictionary.csv`.

## Scope And Data Boundaries

Public active inputs:
- LR matrices under `data/raw/lr_matrices/`
- assessment templates under `data/raw/assessment_templates/`
- chatbot transcript PDFs under `data/raw/chatbot_transcripts/`
- scenario configuration in `config/lr_differential_scenarios.yaml`

Public generated/review artifacts:
- assessment workbooks under `data/processed/assessments/`
- differential input/output workbooks and manifests under `data/processed/lr_differential/`
- one-vs-rest input/output workbooks and manifests under `data/processed/lr_one_vs_rest/`
- review bundles under `artifacts/packages/` when deliberately generated for handoff

Excluded from public branch:
- private manuscript drafts or internal preprints
- reviewer files and meeting notes
- API keys and `.env` files
- third-party publisher/reference PDFs
- local cache databases, package metadata, `.DS_Store`, model checkpoint blobs, and notebook scratch data

## Core Artifact Families

| Artifact | Path Pattern | Unit Of Observation | Notes |
| --- | --- | --- | --- |
| Scenario registry | `config/lr_differential_scenarios.yaml` | one scenario configuration | Maps scenario IDs to source workbooks, sheets, and parser profiles. |
| Raw LR matrices | `data/raw/lr_matrices/**/*.xlsx` | scenario workbook or worksheet | Human-authored or literature-derived diagnosis/finding matrices. |
| Assessment transcript PDFs | `data/raw/chatbot_transcripts/**/*.pdf` | one simulated encounter transcript | Used by assessment extraction notebooks. |
| Assessment templates | `data/raw/assessment_templates/*.xlsx` | assessment workbook template | Defines output sheet shape for transcript-derived findings and LR labels. |
| Differential pairs manifest | `data/processed/lr_differential/manifests/pairs_manifest.csv` | one diagnosis-pair workbook | Canonical manifest for pairwise differential LR runs. |
| Differential input workbook | `data/processed/lr_differential/inputs/**/*.xlsx` | one diagnosis-pair workbook | Normalized workbook sent to an LR estimator. |
| Differential model output workbook | `data/processed/lr_differential/outputs_by_model/<model_id>/**/*.xlsx` | one model-filled diagnosis-pair workbook | Contains model-completed LR cells. |
| One-vs-rest inputs manifest | `data/processed/lr_one_vs_rest/manifests/inputs_manifest.csv` | one scenario-schema workbook | Canonical manifest for one-vs-rest runs. |
| One-vs-rest prior manifest | `data/processed/lr_one_vs_rest/manifests/schema_priors.csv` | one diagnosis prior within a scenario schema | Source for coherence projection. |
| One-vs-rest model output workbook | `data/processed/lr_one_vs_rest/outputs_by_model/<model_id>/*.xlsx` | one model-filled scenario workbook | Raw one-vs-rest LR estimates. |
| Coherent one-vs-rest workbook | `data/processed/lr_one_vs_rest/coherent_outputs_by_model/<model_id>/*.xlsx` | one projected scenario workbook | Bayes-coherent projection of raw one-vs-rest LRs. |

## Key Manifest Fields

| Field | Description |
| --- | --- |
| `scenario_id` | Stable scenario identifier from `config/lr_differential_scenarios.yaml`. |
| `source_workbook` | Raw LR matrix workbook used to build a normalized input. |
| `source_sheet` | Worksheet within the source workbook. |
| `parser_profile` | Parser convention used to detect categories and findings. |
| `category_left`, `category_right` | Diagnosis categories in a pairwise differential comparison. |
| `findings_count` | Count of extracted findings included in an input workbook. |
| `input_workbook` | Differential normalized workbook path. |
| `output_workbook` | Differential model output workbook path expected by the manifest. |
| `normalized_input_workbook` | One-vs-rest normalized workbook path. |
| `schema_sheet_name` | Worksheet name for a one-vs-rest schema. |
| `category` | Diagnosis category receiving a prior or LR estimate. |
| `prior_raw`, `prior_normalized` | Prior probability before and after normalization. |
| `model_id` | Model/run identifier used to scope outputs and quality summaries. |
| `passes` | Boolean quality flag in audit summaries. |
| `invalid_reason` | Audit explanation for a failed or unparseable LR cell. |

## Value Conventions

LR cells should be positive numeric values when completed by a model or coherence projection.
Missing, nonnumeric, zero, negative, or structurally absent LR cells are surfaced by
`scripts/audit_differential_outputs.py`, `scripts/audit_one_vs_rest_outputs.py`, and
`scripts/audit_repo.py`.

`needs_review` in the CSV means the row documents an inferred or heterogeneous artifact
whose exact workbook-specific semantics should be checked before publication-facing reuse.

## Maintenance

Update this dictionary when:
- a new workflow becomes canonical,
- a manifest gains or drops columns,
- a new public input family is added,
- a generated-output path changes,
- publication metadata becomes public and citation surfaces are revised.
