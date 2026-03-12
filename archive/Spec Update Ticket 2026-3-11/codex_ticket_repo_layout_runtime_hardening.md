# Codex implementation ticket: harden repo/runtime/layout for LR pipelines

## Goal

Fix the remaining **codebase, packaging, runtime, and layout** issues surfaced in the latest differential bundle review, without mixing in the separate OVR-coherence work.

This ticket is intentionally **not** about Bayes-coherent OVR projection. Keep mathematical/coherence changes out of scope here except where a structural quality gate is needed.

## Scope

Touch the current differential bundle/repo paths:

- `notebooks/20_differential_build_inputs.ipynb`
- `notebooks/21_differential_estimate_lrs.ipynb`
- `notebooks/22_differential_prepare_inputs_qa.ipynb`
- `scripts/audit_differential_outputs.py`
- `scripts/run_differential_notebook_ledger.sh`
- `scripts/run_differential_and_package.sh`
- `src/dx_chat_entropy/lr_differential_inputs.py`
- review-bundle packaging logic
- tests/docs as needed

If the canonical repo contains the OVR scripts described in the README, the same packaging/runtime standards should also be applied there, but the primary target here is the reviewed differential pipeline.

## Required changes

### A. Make the package/bundle actually self-contained

1. Include every runtime import required by packaged notebooks/scripts.
   - The reviewed bundle imported `dx_chat_entropy.paths.get_paths`, but `src/dx_chat_entropy/paths.py` was absent.
   - Also include `src/dx_chat_entropy/__init__.py` if package imports rely on it.

2. If rerun-from-bundle is a supported workflow, include minimal environment metadata:
   - `pyproject.toml`
   - `uv.lock` or minimal locked requirements snapshot
   - any config files that notebooks/scripts import at runtime

3. Add a bundle completeness check before packaging:
   - scan imports used by packaged notebooks/scripts
   - fail packaging if imported local modules are missing from the bundle

### B. Stop shipping contradictory or stale artifacts

4. Regenerate or omit stale manifests.
   - The reviewed bundle shipped `pairs_manifest_missing_gpt-5.3-chat-latest.csv` showing 73 missing outputs that actually existed.
   - Never package a “missing outputs” artifact unless it is recomputed against the final model-scoped output root for that same bundle.

5. Ensure repair artifacts align with packaged defaults.
   - Repair mode defaulted to `data/processed/lr_differential/manifests/invalid_rows.csv`
   - The bundle only contained `invalid_rows_gpt-5.3-chat-latest.csv`
   - Fix by either:
     - emitting the generic filename in addition to the model-scoped file, or
     - computing the default path dynamically from `MODEL_ID`

6. Package the run ledger if the logs imply resumptions/retries are part of the operational story.
   - The reviewed bundle logs suggested resumed attempts, but no `run_ledger_*.csv` was included.

### C. Tighten scenario/config validation

7. Escalate `expected_category_count` mismatches from warning to failure by default.
   - Current live issue:
     - `chest_pain_carter_18`
     - expected `18`
     - observed `19`
   - This should fail fast unless an explicit override flag is set.

8. Add an explicit override mechanism for intentional mismatches:
   - e.g. `ALLOW_CATEGORY_COUNT_MISMATCH=true`
   - but default behavior should be fail-closed

9. Normalize internal whitespace in prompt-facing category labels.
   - Collapse repeated spaces/tabs for prompt/manifests
   - Preserve raw workbook text only where exact fidelity is required

### D. Fix brittle cell handling

10. Remove all `str(cell).strip()` logic that can turn blank cells into the literal string `"nan"`.
    - Align notebook behavior with `normalize_text` / `normalize_cell` helpers used in audit code.
    - Add regression tests for blank findings and blank headers.

11. Use a single shared normalization utility across:
    - differential notebooks
    - audits
    - any packaging/repair scripts

### E. Improve rerun/resume behavior

12. Add skip-existing / resume semantics at workbook granularity.
    - Before estimating a workbook, check whether it already exists and passes audit.
    - If yes, skip it.
    - If no, compute it.

13. Add an explicit run mode env var:
    - `DX_RESUME_MODE=recompute|skip_passing|repair_invalid`

14. Persist progress per workbook and do not recompute earlier successful workbooks when a later workbook fails.

15. Add stronger retry/fallback behavior:
    - more than one retry for parse/validation failures
    - exponential backoff for transient API failures
    - backend fallback when auto mode is enabled

16. Prefer a script-first runner over fragile notebook-ledger orchestration if feasible.
    - The current `nbconvert`-driven orchestration is operationally brittle and hard to observe.

### F. Add structural QA gates

17. Extend the packaging/audit layer with non-mathematical structural checks:
    - imported modules included in bundle
    - repair target file exists
    - manifests do not contradict packaged outputs
    - run ledger presence/absence is consistent with logs
    - required config files are present

18. Add tests for:
    - bundle completeness
    - repair path resolution
    - resume-mode behavior
    - category-count mismatch failure
    - NaN/blank finding handling

19. Ensure README/package claims match reality.
    - If a review bundle is intentionally partial, say so clearly.
    - Do not present a full-repo map in a partial bundle without marking omitted components.

## Non-goals

- Do **not** implement coherent OVR projection in this ticket.
- Do **not** redesign the differential estimation prompt here.
- Do **not** change raw scientific assumptions unless needed for runtime correctness.

## Acceptance criteria

1. The packaged differential bundle can be rerun from its own contents without missing local imports.
2. Repair mode works without manual path overrides.
3. Build fails on the current 18-vs-19 chest pain mismatch unless explicitly overridden.
4. Reruns skip already-passing workbooks when `skip_passing` mode is selected.
5. Blank/NaN findings are never turned into `"nan"` prompt text.
6. No stale missing-output artifact is shipped.
7. Bundle completeness checks pass in CI.
8. README/package scope is truthful for the bundle actually produced.

## Reviewed issues that this ticket addresses

From the latest differential bundle review:

- missing module in bundle: `dx_chat_entropy.paths`
- repair default path mismatch
- stale `pairs_manifest_missing_*` artifact
- missing run ledger in packaged output
- live scenario/category-count mismatch
- brittle NaN finding handling

Reference artifacts:
- `d53_review_summary.md`
- `d53_code_and_package_issues.csv`
- `d53_stale_pairs_manifest_missing_check.csv`
- prior combined ticket: `codex_ticket_d53_residual_issues.md`
