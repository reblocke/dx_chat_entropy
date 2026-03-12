#!/usr/bin/env bash
set -euo pipefail

# End-to-end differential run wrapper:
# 1) resume/run full 4-scenario notebook pipeline with scenario ledger
# 2) audit outputs for the target model
# 3) build a review zip with code + manifests + outputs + logs
#
# Usage:
#   scripts/run_differential_and_package.sh [MODEL_ID] [REASONING_EFFORT]
#
# Example:
#   scripts/run_differential_and_package.sh gpt-5.3-chat-latest medium

MODEL_ID="${1:-gpt-5.3-chat-latest}"
REASONING_EFFORT="${2:-medium}"

REPO_ROOT="$(pwd)"
MANIFEST_DIR="${REPO_ROOT}/data/processed/lr_differential/manifests"
OUTPUTS_ROOT="${REPO_ROOT}/data/processed/lr_differential/outputs_by_model"
MODEL_LOG_DIR="${MANIFEST_DIR}/logs/${MODEL_ID}"

SUMMARY_OUT="${MANIFEST_DIR}/quality_summary_${MODEL_ID}.csv"
INVALID_OUT="${MANIFEST_DIR}/invalid_rows_${MODEL_ID}.csv"

echo "[run] model=${MODEL_ID} reasoning_effort=${REASONING_EFFORT}"
scripts/run_differential_notebook_ledger.sh "${MODEL_ID}" "${REASONING_EFFORT}"

echo "[audit] writing ${SUMMARY_OUT} and ${INVALID_OUT}"
uv run --group notebooks python scripts/audit_differential_outputs.py \
  --manifest data/processed/lr_differential/manifests/pairs_manifest.csv \
  --outputs-root data/processed/lr_differential/outputs_by_model \
  --summary-out "data/processed/lr_differential/manifests/quality_summary_${MODEL_ID}.csv" \
  --invalid-out "data/processed/lr_differential/manifests/invalid_rows_${MODEL_ID}.csv" \
  --model-id "${MODEL_ID}"

TS="$(date +%Y%m%dT%H%M%S)"
PKG_NAME="differential_4scenario_${MODEL_ID}_${TS}"
PKG_ROOT="${REPO_ROOT}/artifacts/packages/${PKG_NAME}"
ZIP_PATH="${REPO_ROOT}/artifacts/packages/${PKG_NAME}.zip"

mkdir -p "${PKG_ROOT}"

# Code bundle
mkdir -p \
  "${PKG_ROOT}/code/notebooks" \
  "${PKG_ROOT}/code/scripts" \
  "${PKG_ROOT}/code/src/dx_chat_entropy" \
  "${PKG_ROOT}/code/config" \
  "${PKG_ROOT}/docs"

cp "${REPO_ROOT}/notebooks/20_differential_build_inputs.ipynb" "${PKG_ROOT}/code/notebooks/"
cp "${REPO_ROOT}/notebooks/21_differential_estimate_lrs.ipynb" "${PKG_ROOT}/code/notebooks/"
cp "${REPO_ROOT}/notebooks/22_differential_prepare_inputs_qa.ipynb" "${PKG_ROOT}/code/notebooks/"
cp "${REPO_ROOT}/scripts/audit_differential_outputs.py" "${PKG_ROOT}/code/scripts/"
cp "${REPO_ROOT}/scripts/check_differential_bundle.py" "${PKG_ROOT}/code/scripts/"
cp "${REPO_ROOT}/scripts/run_differential_batch.py" "${PKG_ROOT}/code/scripts/"
cp "${REPO_ROOT}/scripts/run_differential_notebook_ledger.sh" "${PKG_ROOT}/code/scripts/"
cp "${REPO_ROOT}/scripts/run_differential_and_package.sh" "${PKG_ROOT}/code/scripts/"
cp "${REPO_ROOT}/src/dx_chat_entropy/__init__.py" "${PKG_ROOT}/code/src/dx_chat_entropy/"
cp "${REPO_ROOT}/src/dx_chat_entropy/paths.py" "${PKG_ROOT}/code/src/dx_chat_entropy/"
cp "${REPO_ROOT}/src/dx_chat_entropy/lr_differential_inputs.py" "${PKG_ROOT}/code/src/dx_chat_entropy/"
cp "${REPO_ROOT}/src/dx_chat_entropy/lr_differential_audit.py" "${PKG_ROOT}/code/src/dx_chat_entropy/"
cp "${REPO_ROOT}/src/dx_chat_entropy/lr_differential_runner.py" "${PKG_ROOT}/code/src/dx_chat_entropy/"
cp "${REPO_ROOT}/src/dx_chat_entropy/lr_differential_bundle.py" "${PKG_ROOT}/code/src/dx_chat_entropy/"
cp "${REPO_ROOT}/config/lr_differential_scenarios.yaml" "${PKG_ROOT}/code/config/"
cp "${REPO_ROOT}/README.md" "${PKG_ROOT}/README.md"
cp "${REPO_ROOT}/docs/PIPELINES.md" "${PKG_ROOT}/docs/PIPELINES.md"
cp "${REPO_ROOT}/docs/SPECIFICATION.md" "${PKG_ROOT}/docs/SPECIFICATION.md"
cp "${REPO_ROOT}/pyproject.toml" "${PKG_ROOT}/pyproject.toml"
cp "${REPO_ROOT}/uv.lock" "${PKG_ROOT}/uv.lock"

# Data bundle (raw + processed + outputs + manifests)
mkdir -p "${PKG_ROOT}/data/raw/lr_matrices"
cp -R "${REPO_ROOT}/data/raw/lr_matrices/"* "${PKG_ROOT}/data/raw/lr_matrices/"

mkdir -p "${PKG_ROOT}/data/processed/lr_differential/inputs"
cp -R "${REPO_ROOT}/data/processed/lr_differential/inputs/"* "${PKG_ROOT}/data/processed/lr_differential/inputs/"

mkdir -p "${PKG_ROOT}/data/processed/lr_differential/outputs_by_model/${MODEL_ID}"
cp -R "${OUTPUTS_ROOT}/${MODEL_ID}/"* "${PKG_ROOT}/data/processed/lr_differential/outputs_by_model/${MODEL_ID}/"

mkdir -p "${PKG_ROOT}/data/processed/lr_differential/manifests"
cp "${REPO_ROOT}/data/processed/lr_differential/manifests/pairs_manifest.csv" "${PKG_ROOT}/data/processed/lr_differential/manifests/"
if [[ -f "${REPO_ROOT}/data/processed/lr_differential/manifests/run_manifest.json" ]]; then
  cp "${REPO_ROOT}/data/processed/lr_differential/manifests/run_manifest.json" "${PKG_ROOT}/data/processed/lr_differential/manifests/"
fi
if [[ -f "${REPO_ROOT}/data/processed/lr_differential/manifests/run_ledger_differential_${MODEL_ID}.csv" ]]; then
  cp "${REPO_ROOT}/data/processed/lr_differential/manifests/run_ledger_differential_${MODEL_ID}.csv" "${PKG_ROOT}/data/processed/lr_differential/manifests/"
fi
cp "${SUMMARY_OUT}" "${PKG_ROOT}/data/processed/lr_differential/manifests/"
cp "${INVALID_OUT}" "${PKG_ROOT}/data/processed/lr_differential/manifests/"
# Generic repair default path for notebook/runtime compatibility.
cp "${INVALID_OUT}" "${PKG_ROOT}/data/processed/lr_differential/manifests/invalid_rows.csv"

mkdir -p "${PKG_ROOT}/data/processed/lr_differential/manifests/logs/${MODEL_ID}"
if [[ -d "${MODEL_LOG_DIR}" ]]; then
  cp -R "${MODEL_LOG_DIR}/"* "${PKG_ROOT}/data/processed/lr_differential/manifests/logs/${MODEL_ID}/" || true
fi

cat > "${PKG_ROOT}/PACKAGE_CONTENTS.txt" <<EOF
Package: Differential LR full-run review bundle
Model: ${MODEL_ID}
Reasoning effort: ${REASONING_EFFORT}
Includes:
- differential pipeline notebooks + scripts + core src modules
- scenario config and documentation snapshot
- raw LR-matrix sources
- generated differential inputs
- model-scoped outputs for all scenarios
- model-scoped audit outputs
- run ledger + execution logs
EOF

echo "[check] validating staged bundle completeness"
uv run --group notebooks python scripts/check_differential_bundle.py \
  --bundle-root "${PKG_ROOT}" \
  --model-id "${MODEL_ID}" \
  --repo-root "${REPO_ROOT}"

mkdir -p "${REPO_ROOT}/artifacts/packages"
(cd "${REPO_ROOT}/artifacts/packages" && zip -r "${PKG_NAME}.zip" "${PKG_NAME}" >/tmp/${PKG_NAME}_zip.log)

echo "[done] review zip: ${ZIP_PATH}"
