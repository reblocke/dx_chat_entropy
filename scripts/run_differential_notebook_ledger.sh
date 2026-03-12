#!/usr/bin/env bash
set -u

# Run differential LR estimation scenario-by-scenario with a resumable ledger.
# Uses script-first runner for better operational stability than nbconvert orchestration.
# Usage:
#   scripts/run_differential_notebook_ledger.sh [MODEL_ID] [REASONING_EFFORT]
# Example:
#   scripts/run_differential_notebook_ledger.sh gpt-5.3-chat-latest medium

MODEL_ID="${1:-gpt-5.3-chat-latest}"
REASONING_EFFORT="${2:-medium}"

REPO_ROOT="$(pwd)"
MANIFEST="${REPO_ROOT}/data/processed/lr_differential/manifests/pairs_manifest.csv"
OUTPUTS_ROOT="${REPO_ROOT}/data/processed/lr_differential/outputs_by_model"
LEDGER="${REPO_ROOT}/data/processed/lr_differential/manifests/run_ledger_differential_${MODEL_ID}.csv"
LOG_DIR="${REPO_ROOT}/data/processed/lr_differential/manifests/logs/${MODEL_ID}"

mkdir -p "$LOG_DIR"

if [[ ! -f "$LEDGER" ]]; then
  echo "scenario_id,status,start_utc,end_utc,exit_code,log_path" > "$LEDGER"
fi

SCENARIOS_RAW="$(uv run --group notebooks python - <<PY
import pandas as pd

df = pd.read_csv(r"${MANIFEST}")
for sid in sorted(df['scenario_id'].dropna().unique()):
    print(sid)
PY
)"

SCENARIO_COUNT="$(printf "%s\n" "$SCENARIOS_RAW" | sed '/^$/d' | wc -l | tr -d ' ')"
echo "Model: $MODEL_ID"
echo "Reasoning effort: $REASONING_EFFORT"
echo "Scenarios: $SCENARIO_COUNT"

printf "%s\n" "$SCENARIOS_RAW" | while IFS= read -r SID; do
  if [[ -z "$SID" ]]; then
    continue
  fi

  if grep -q "^${SID},success," "$LEDGER"; then
    echo "Skip (already success): $SID"
    continue
  fi

  START_UTC="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  LOG_FILE="${LOG_DIR}/${SID}_$(date -u +"%Y%m%dT%H%M%SZ").log"

  echo "Running scenario: $SID"
  DX_MODEL_ID="$MODEL_ID" \
  DX_API_BACKEND="responses" \
  DX_REASONING_EFFORT="$REASONING_EFFORT" \
  DX_VERBOSITY="low" \
  DX_RESUME_MODE="skip_passing" \
  DX_SCENARIO_FILTER="$SID" \
  DX_MANIFEST_PATH="$MANIFEST" \
  DX_OUTPUTS_BY_MODEL_ROOT="$OUTPUTS_ROOT" \
  uv run --group notebooks python scripts/run_differential_batch.py --repo-root "$REPO_ROOT" \
    2>&1 | tee "$LOG_FILE"
  EXIT_CODE=${PIPESTATUS[0]}
  END_UTC="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

  if [[ $EXIT_CODE -eq 0 ]]; then
    echo "${SID},success,${START_UTC},${END_UTC},${EXIT_CODE},${LOG_FILE}" >> "$LEDGER"
    echo "Completed: $SID"
  else
    echo "${SID},failed,${START_UTC},${END_UTC},${EXIT_CODE},${LOG_FILE}" >> "$LEDGER"
    echo "Failed: $SID (exit ${EXIT_CODE}). Stopping for resumable retry."
    exit $EXIT_CODE
  fi
done

FINAL_STATUS=$?
if [[ $FINAL_STATUS -ne 0 ]]; then
  exit $FINAL_STATUS
fi

echo "All scenarios completed."
