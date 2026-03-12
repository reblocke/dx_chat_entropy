# Supporting notes for Codex: OVR coherent projection port

## What the attached notebook is doing

`coherent_multi_class.ipynb` solves the OVR coupling problem by fitting a single multiclass model that is as close as possible to the raw one-vs-rest LR estimates on the **log-LR scale**.

The notebook’s core objects are:

- `OVRProjectionResult`
- `ovr_project_posterior(...)`
- `fitted_ovr_lr`
- `posterior`
- `sum_q_init`

The important output for the pipeline is **`fitted_ovr_lr`**.

## Core formulas to preserve

Let:

- `π_k` = prior probability for class `k`
- `λ_k` = raw OVR LR for class `k`
- `s_k` = fitted latent score for class `k`

Then:

### Initial binary slices
```text
q0_k = logistic(logit(π_k) + log(λ_k))
sum_q_init = sum_k q0_k
```

If the raw OVR LR vector is already coherent, `sum_q_init ≈ 1`.

### Shared multiclass model
```text
posterior_k ∝ π_k * exp(s_k)
posterior_k = π_k * exp(s_k) / sum_j π_j * exp(s_j)
```

### Model-implied coherent OVR LR
```text
log fitted_ovr_lr_k = s_k - log(sum_{j != k} π_j * exp(s_j)) + log(1 - π_k)
```

### Optimization target
Minimize weighted squared residuals on log-LR scale, with light ridge/L2 stabilization:
```text
min_s  Σ_k w_k [log(raw_ovr_lr_k) - log(fitted_ovr_lr_k)]² + reg * ||s_nonbaseline||²
```

## Important caveat

This method repairs **coherence**, not the upstream semantic under-specification of the raw OVR prompt. The current OVR estimator asks for a category-specific LR without explicitly providing the full comparator set or priors in-prompt. Keep raw and coherent outputs separate so the projection is transparent and reversible.

## Implementation recommendations

### 1. Put solver logic in `src/`, not in the notebook
Use the notebook as a thin orchestrator only.
Recommended new module:
- `src/dx_chat_entropy/lr_one_vs_rest_coherence.py`

### 2. Preserve raw and coherent outputs separately
Do not overwrite raw OVR workbooks.
Recommended roots:
- raw: `data/processed/lr_one_vs_rest/outputs_by_model/<MODEL_ID>/...`
- coherent: `data/processed/lr_one_vs_rest/coherent_outputs_by_model/<MODEL_ID>/...`

### 3. Propagate priors via manifest, not workbook parsing at projection time
Best data contract:
- `inputs_manifest.csv`
- `schema_priors.csv`

This keeps the projection notebook simple and auditable.

### 4. Handle prior extraction carefully
Raw matrices may contain a final trailing total cell like `1.0` or `0.995`.
Do **not** let the final category absorb that total.

Use schema spans defined by the **actual non-empty cells in the schema row**, bounded by the last labeled column.

### 5. Normalize priors for projection, but keep the raw sum
Example from the reviewed bundle:
- `erectile_dysfunction_torres_tier1` raw priors sum to `0.995`

Projection should use normalized priors, but the raw sum should be preserved in the priors manifest for audit/debugging.

## Suggested output artifacts from the new projection notebook

Required:
- coherent workbook(s)
- projection summary CSV
- top-rows adjustment CSV
- failure CSV

Useful optional long-form artifact:
- one row per `(scenario, sheet, finding, category)` with:
  - `prior`
  - `raw_ovr_lr`
  - `fitted_ovr_lr`
  - `mult_change`
  - `abs_log_change`
  - `posterior_fitted`
  - `sum_q_init`
  - `rmse_logLR`

## Empirical impact from the reviewed OVR bundle

I ran the attached notebook’s projection method against the available 4-scenario `gpt-4.1-nano` OVR outputs.

### Scenario-level adjustment summary

| scenario_id | median abs coherence gap | p90 abs coherence gap | median multiplicative change | p90 multiplicative change | p99 multiplicative change | max multiplicative change |
|---|---:|---:|---:|---:|---:|---:|
| chest_pain_carter_18 | 0.3823 | 0.5795 | 1.0261 | 1.6789 | 3.8904 | 7.6177 |
| chest_pain_carter_8 | 0.2748 | 0.5173 | 1.1803 | 1.8501 | 3.7581 | 4.7921 |
| erectile_dysfunction_torres_tier1 | 0.2696 | 0.5754 | 1.1953 | 2.0362 | 4.6512 | 6.6846 |
| metrorrhagia_sperle_tier3 | 0.1434 | 0.3651 | 1.0185 | 1.4414 | 3.0144 | 6.4084 |

### Sign-impossible rows

Before projection:
- `94` rows

After projection:
- `0` rows

Per-scenario:
- chest_pain_carter_18: `26 -> 0`
- chest_pain_carter_8: `34 -> 0`
- erectile_dysfunction_torres_tier1: `16 -> 0`
- metrorrhagia_sperle_tier3: `18 -> 0`

## Priors extracted from the reviewed source sheets

See:
- `ovr_priors_by_schema.csv`

A few notable details:
- `chest_pain_carter_18` currently has **19** categories, not 18
- `erectile_dysfunction_torres_tier1` priors sum to `0.995` before normalization

## Useful regression example from the attached notebook

Input:
- priors = `(0.5, 0.3, 0.2)`
- raw OVR LRs = `(4, 3, 2)`

Expected:
- `sum_q_init ≈ 1.6958`
- fitted OVR LRs ≈ `(1.0706, 0.9932, 0.9042)`
- posterior ≈ `(0.5170, 0.2986, 0.1844)`

That is the cleanest small regression test to carry into `tests/`.
