# AGENTS.md

## Project Scope

This is a Python-first research repository for clinical diagnostic-reasoning LR workflows.
The active public code lives under `src/`, `scripts/`, `tests/`, `notebooks/`, `config/`,
`data/raw/`, and selected review artifacts in `data/processed/`.

The associated manuscript is under journal review, not accepted or published. Do not claim
Scientific Reports acceptance/publication, a DOI, PMID, PMCID, or article metadata until a
public record exists and the repository is updated deliberately.

## Authority Hierarchy

1. Public repository docs: `README.md`, `llms.txt`, `docs/SPECIFICATION.md`,
   `docs/DATA_MANAGEMENT.md`, and `docs/DECISIONS.md`
2. Existing scripts and tests
3. Notebook wrappers and archived material

When these disagree, keep the change narrow and document the correction.

## Data And Publication Rules

- Never commit API keys, `.env` files, credentials, or token-like strings.
- Do not commit private manuscript drafts, internal preprints, reviewer files, meeting notes,
  private protocols, or publisher/reference PDFs.
- Do not add full manuscript Markdown until a public preprint or accepted-author version is
  explicitly supplied for public release.
- Keep local paths repo-relative; no absolute user-home paths or machine-specific cloud-sync paths.
- Preserve raw input immutability. Correct source defects in code or generated layers.
- Strip notebook outputs unless a notebook is explicitly intended to be a committed artifact.
- Keep local machine state, package metadata, notebook scratch data, `.DS_Store`, binary model
  state, and external cache artifacts out of the public branch.

## Workflow Conventions

- Use `uv` and `pyproject.toml` for dependency management.
- Run commands from the repository root.
- Prefer scripts as canonical batch entry points; notebooks may wrap or inspect those workflows.
- Use `pathlib.Path` and explicit input/output paths.
- Avoid `os.chdir` in committed code.
- Keep model IDs and run outputs visibly separated by model-scoped output directories.

## Verification Before Handoff

Run the relevant subset for the change:

```bash
make fmt
make lint
make test
make audit
uvx --from cffconvert cffconvert --validate --infile CITATION.cff
git diff --check
```

For documentation-only changes, still run `make audit`, YAML/CFF validation when citation
metadata changes, and `git diff --check`.

## Publication Metadata Updates

When a public paper, preprint, or conference record appears, update these together:

- `README.md`
- `llms.txt`
- `CITATION.cff`
- GitHub repository description, homepage, and topics
- Any release notes or public package metadata that mention citation status

Do not add placeholders for missing DOI/PMID/PMCID fields.
