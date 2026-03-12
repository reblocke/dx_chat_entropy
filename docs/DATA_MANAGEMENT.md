# Data management

## Directory policy
- `data/raw/`: immutable project inputs.
- `data/external/`: downloaded artifacts with provenance sidecars.
- `data/processed/`: intermediate generated outputs.
- `data/derived/`: final analysis-ready outputs.
- `archive/`: historical/legacy data retained in-repo.

## Pipeline I/O contracts
For current pipeline purpose, inputs, outputs, and run order, see:
- `docs/PIPELINES.md`

Key active generated paths:
- Differential LR: `data/processed/lr_differential/`
- One-vs-rest LR: `data/processed/lr_one_vs_rest/`
- Assessment pipeline: `data/processed/assessments/`

Differential runtime artifacts:
- `data/processed/lr_differential/manifests/invalid_rows_<MODEL_ID>.csv`
- `data/processed/lr_differential/manifests/run_ledger_differential_<MODEL_ID>.csv`
- `data/processed/lr_differential/manifests/logs/<MODEL_ID>/`

One-vs-rest coherence artifacts:
- `data/processed/lr_one_vs_rest/manifests/schema_priors.csv`
- `data/processed/lr_one_vs_rest/coherent_outputs_by_model/<MODEL_ID>/`
- `data/processed/lr_one_vs_rest/manifests/coherence_projection_*.csv`

## Provenance sidecars
For external file `data/external/foo.ext`, include `foo.ext.source.json` with:
- source URL / DOI
- retrieval date
- version/tag/commit
- sha256 checksum
- license
- notes

## Immutability
If raw input errors are discovered:
- do not edit raw file in place
- add correction in code/pipeline
- write corrected output to `data/processed` or `data/derived`
