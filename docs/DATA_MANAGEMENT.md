# Data management

## Directory policy
- `data/raw/`: immutable project inputs.
- `data/external/`: downloaded artifacts with provenance sidecars.
- `data/processed/`: intermediate generated outputs.
- `data/derived/`: final analysis-ready outputs.
- `archive/`: historical/legacy data retained in-repo.

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
