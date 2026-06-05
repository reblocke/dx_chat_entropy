# Data management

## Directory policy
- `data/raw/`: immutable project inputs.
- `data/external/`: downloaded artifacts with provenance sidecars.
- `data/processed/`: intermediate generated outputs.
- `data/derived/`: final analysis-ready outputs.
- `archive/`: historical/legacy source code and provenance notes retained in-repo when
  appropriate.

Do not use the public branch as a storage location for local tool state, external model
checkpoints, downloaded binary datasets, private manuscript drafts, internal preprints,
reviewer materials, publisher PDFs, or team/project administration files.

## Pipeline I/O contracts
For current pipeline purpose, inputs, outputs, and run order, see:
- `docs/SPECIFICATION.md`

For a shorter pipeline index, see:
- `docs/PIPELINES.md`

Key active generated paths:
- Differential LR: `data/processed/lr_differential/`
- One-vs-rest LR: `data/processed/lr_one_vs_rest/`
- Assessment pipeline: `data/processed/assessments/`

Machine-readable artifact documentation:
- `data_dictionary.md`
- `data_dictionary.csv`

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

## Publication Boundary
The associated manuscript is under journal review and is not yet a public scholarly record.
Do not commit private drafts, internal preprints, or publication metadata placeholders. Add
DOI/PMID/PMCID metadata only after a public record exists.
