# Codex implementation ticket: add Bayes-coherent one-vs-rest LR projection stage

## Goal

Add a **new end-of-pipeline normalization step** for the canonical one-vs-rest LR workflow that converts independently estimated raw OVR LRs into a **Bayes-coherent multiclass set of OVR LRs** using the methodology in `coherent_multi_class.ipynb`.

The canonical artifact of this step is **coherent OVR LRs** (`fitted_ovr_lr` / `ovr_lr_fitted`) for each finding row and schema sheet. Coherent post-test probabilities may be emitted as diagnostics, but they are **not** the primary deliverable.

This ticket is intentionally **separate from repo/runtime/package hardening**. Do not mix those changes here except where they are strictly required to support coherent OVR projection.

## Why this exists

Current one-vs-rest estimation is mathematically under-constrained and often incoherent:

- many finding rows produce OVR LR vectors whose implied binary posteriors do **not** sum to 1
- many rows are **sign-impossible** for true OVR semantics (all categories > 1 or all categories < 1)
- priors exist in the raw LR matrices, but they are not propagated through the current OVR pipeline in a reusable way

The attached notebook already implements the correct normalization idea: fit class scores under a shared multiclass model, then derive **model-implied coherent OVR LRs** from those scores.



## Important caveat

This projection step fixes **multiclass Bayes coherence**, but it does **not** solve the separate prompt-design issue that the raw OVR estimator currently does not explicitly describe the comparator set (“rest of scenario”) or provide priors in-prompt. Keep the raw outputs and the coherent outputs separate so reviewers can inspect both.

## Scope

Touch the canonical one-vs-rest pipeline:

- `src/dx_chat_entropy/lr_one_vs_rest_inputs.py`
- `scripts/build_one_vs_rest_inputs.py`
- `scripts/run_one_vs_rest_batch.py` only as needed for manifest/path compatibility
- `scripts/audit_one_vs_rest_outputs.py`
- **new** `src/dx_chat_entropy/lr_one_vs_rest_coherence.py`
- **new** `notebooks/32_one_vs_rest_project_coherent_lrs.ipynb`
- optionally **new** `scripts/project_one_vs_rest_coherent_lrs.py` if you want a script-first automation mirror for CI/batch runs

## Required design

### A. Propagate priors through the OVR pipeline

Add a durable prior data contract so the coherent-projection step does **not** need to reverse-engineer priors ad hoc from raw workbooks every time.

Implement one of these two acceptable patterns:

#### Preferred
Create a **long-form priors manifest**:
- `data/processed/lr_one_vs_rest/manifests/schema_priors.csv`

Columns:
- `scenario_id`
- `source_workbook`
- `source_sheet`
- `schema_order`
- `schema_row_idx`
- `schema_sheet_name`
- `prior_row_idx`
- `category_order`
- `category`
- `prior_raw`
- `prior_normalized`
- `prior_vector_sum_raw`

Keep `inputs_manifest.csv` as the high-level summary and join to `schema_priors.csv` by:
- `scenario_id`
- `schema_order`
- `schema_sheet_name`

#### Acceptable fallback
Store priors directly in `inputs_manifest.csv` as JSON columns:
- `categories_json`
- `priors_raw_json`
- `priors_normalized_json`
- `prior_row_idx`
- `prior_vector_sum_raw`

The long-form CSV is preferred because it is inspectable, stable, and easier to diff/test.

### B. Implement robust prior extraction from raw LR matrices

Port this into reusable code, not notebook-only logic.

Add a helper that, for each schema row:

1. finds the `Key feature` row
2. infers the **prior row** as the last numeric-dense row between the schema row and the `Key feature` row
3. derives category spans from the **actual non-empty label cells in the schema row**
   - do **not** let the last category absorb trailing total columns
   - this matters for sheets where the priors row contains a final total cell like `1.0` or `0.995`
4. sums prior values across each category span
5. normalizes the prior vector to sum to 1 for downstream projection
6. records both raw and normalized priors

Important:
- some source sheets sum to slightly less than 1 (example: ED tier 1 sums to `0.995`)
- normalize for projection, but preserve `prior_vector_sum_raw` for audit/debugging

### C. Port the coherent OVR projection algorithm into a reusable module

Create:
- `src/dx_chat_entropy/lr_one_vs_rest_coherence.py`

Required public API shape:

```python
@dataclass
class OVRProjectionResult:
    posterior: np.ndarray
    log_scores: np.ndarray
    fitted_ovr_lr: np.ndarray
    rmse_logLR: float
    success: bool
    message: str
    diagnostics: dict[str, Any]
```

Required function:

```python
def ovr_project_posterior(
    priors: ArrayLike,
    ovr_lr: ArrayLike,
    reg: float = 1e-6,
    weights: ArrayLike | None = None,
    baseline: int | None = None,
) -> OVRProjectionResult:
    ...
```

Use the same method as `coherent_multi_class.ipynb`:

- work on **log-LR** scale
- fit latent class scores `s_k`
- fix one baseline class for identifiability
- minimize residuals between:
  - input `log(ovr_lr_k)`
  - model-implied OVR log-LR for class `k`
- include light L2 regularization
- derive:
  - coherent posterior: `posterior_k ∝ prior_k * exp(s_k)`
  - coherent OVR LR: `fitted_ovr_lr_k`

Model-implied OVR log-LR for class `k` should be:

```text
log LR_k = s_k - log(sum_{j != k} prior_j * exp(s_j)) + log(1 - prior_k)
```

and the posterior should be:

```text
posterior_k = prior_k * exp(s_k) / sum_j prior_j * exp(s_j)
```

Keep the notebook’s `sum_q_init` diagnostic, where:

```text
q0_k = logistic(logit(prior_k) + log(raw_ovr_lr_k))
sum_q_init = sum_k q0_k
```

This is a useful first-pass coherence-gap metric.

### D. Add a new end-of-pipeline notebook

Add:

- `notebooks/32_one_vs_rest_project_coherent_lrs.ipynb`

This notebook should:

1. load raw OVR outputs from:
   - `data/processed/lr_one_vs_rest/outputs_by_model/<MODEL_ID>/<scenario_id>_filled.xlsx`
2. load priors from:
   - `data/processed/lr_one_vs_rest/manifests/schema_priors.csv`
3. for each finding row on each schema sheet:
   - read raw OVR LR vector
   - fit coherent OVR LR vector using `ovr_project_posterior`
4. write coherent output workbooks to:
   - `data/processed/lr_one_vs_rest/coherent_outputs_by_model/<MODEL_ID>/<scenario_id>_coherent.xlsx`
5. emit projection diagnostics/manifests:
   - `data/processed/lr_one_vs_rest/manifests/coherence_projection_summary_<MODEL_ID>.csv`
   - `data/processed/lr_one_vs_rest/manifests/coherence_projection_top_rows_<MODEL_ID>.csv`
   - `data/processed/lr_one_vs_rest/manifests/coherence_projection_failures_<MODEL_ID>.csv` (if any)

Notebook controls/environment variables:
- `MODEL_ID`
- `SCENARIO_FILTER`
- `MAX_SCHEMAS`
- `MAX_FINDINGS`
- `REG`
- `FAIL_ON_MISSING_PRIORS`
- `OVERWRITE`
- `WRITE_POSTERIOR_DEBUG` (optional)

Important behavior:
- leave raw outputs untouched
- write coherent outputs to a **separate root**
- preserve workbook/sheet layout so downstream consumers can swap roots without changing parsing code

### E. Define the coherent workbook output contract

Each coherent workbook should preserve the same shape as the raw OVR workbook:
- row 0 = category headers
- col 0 = finding text
- body cells = **coherent OVR LRs**

Optional but useful:
- write a parallel long-form CSV or parquet with columns:
  - `scenario_id`
  - `schema_sheet_name`
  - `finding`
  - `category`
  - `prior`
  - `raw_ovr_lr`
  - `fitted_ovr_lr`
  - `mult_change`
  - `abs_log_change`
  - `posterior_fitted`
  - `sum_q_init`
  - `rmse_logLR`

### F. Upgrade the OVR audit to understand coherence

Extend `scripts/audit_one_vs_rest_outputs.py` with an optional coherent-output mode:

- `--use-coherent-root` or `--outputs-root .../coherent_outputs_by_model`
- verify positive finite cells as before
- verify coherent rows by recomputing or checking:
  - posterior sums to 1 within tolerance
  - no sign-impossible rows remain
- emit scenario-level summaries:
  - median/p90 coherence gap for raw rows
  - median/p90 multiplicative adjustment size
  - sign-impossible rows before/after
  - solver failures (should be zero)

## Non-goals

- Do **not** redesign the raw LLM prompt in this ticket.
- Do **not** replace raw OVR outputs in place.
- Do **not** collapse this work into differential pairwise LR projection.
- Do **not** bury the solver only inside a notebook; the notebook must call reusable library code.

## Acceptance criteria

1. `build_one_vs_rest_inputs.py` produces durable prior metadata for every schema sheet.
2. Prior extraction ignores trailing total columns and records both raw + normalized priors.
3. New module `lr_one_vs_rest_coherence.py` reproduces the attached notebook’s solver behavior.
4. New notebook `32_one_vs_rest_project_coherent_lrs.ipynb` writes coherent workbooks to a separate root.
5. Every coherent row yields posteriors summing to 1 within numerical tolerance.
6. Rows that were previously sign-impossible are no longer sign-impossible after projection.
7. Raw and coherent outputs are both retained.
8. Audit can report projection metrics and validate coherent outputs.

## Required tests

### Unit tests
- prior extraction:
  - ignores trailing total column
  - handles raw prior sums slightly different from 1
  - preserves category order
- OVR solver:
  - coherent inputs remain nearly unchanged
  - incoherent inputs become coherent
  - posterior sums to 1
  - all fitted OVR LRs remain > 0

### Regression tests
Use the example from the attached notebook:

- priors = `(0.5, 0.3, 0.2)`
- raw OVR LRs = `(4, 3, 2)`

Expected behavior:
- `sum_q_init` substantially > 1 before projection
- fitted OVR LRs approximately:
  - `1.0706`
  - `0.9932`
  - `0.9042`
- posterior approximately:
  - `0.5170`
  - `0.2986`
  - `0.1844`

### Bundle-level smoke test
Run projection on the existing 4-scenario OVR bundle and verify:
- zero solver failures
- zero sign-impossible coherent rows
- coherent workbooks written for every scenario workbook

## Empirical reference from the reviewed OVR bundle

Using the current 4-scenario `gpt-4.1-nano` OVR outputs and the attached notebook’s method, the projection step would repair the incoherence cleanly.

Scenario-level summary from the reviewed bundle:

| scenario_id | median abs coherence gap | p90 abs coherence gap | median mult change | p90 mult change | max mult change |
|---|---:|---:|---:|---:|---:|
| chest_pain_carter_18 | 0.3823 | 0.5795 | 1.0261 | 1.6789 | 7.6177 |
| chest_pain_carter_8 | 0.2748 | 0.5173 | 1.1803 | 1.8501 | 4.7921 |
| erectile_dysfunction_torres_tier1 | 0.2696 | 0.5754 | 1.1953 | 2.0362 | 6.6846 |
| metrorrhagia_sperle_tier3 | 0.1434 | 0.3651 | 1.0185 | 1.4414 | 6.4084 |

And:
- raw sign-impossible rows: `94`
- fitted sign-impossible rows after projection: `0`

Reference artifacts for implementation:
- `ovr_projection_supporting_notes.md`
- `ovr_priors_by_schema.csv`
- `ovr_projection_adjustment_summary.csv`
- `ovr_projection_sign_fix_summary.csv`
- `ovr_projection_top100_category_adjustments.csv`
- `coherent_multi_class.ipynb`
