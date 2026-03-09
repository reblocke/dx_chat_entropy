from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

CANONICAL_OUTPUTS_ROOT = Path("data/processed/lr_differential/outputs")


@dataclass(frozen=True)
class LrCellClassification:
    status: str
    numeric_value: float | None


def normalize_text(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def finding_row_indexes(df_input: pd.DataFrame) -> list[int]:
    rows: list[int] = []
    for row_idx in range(2, df_input.shape[0]):
        finding = normalize_text(df_input.iat[row_idx, 0])
        if finding:
            rows.append(row_idx)
    return rows


def classify_lr_cell(value: object) -> LrCellClassification:
    text = normalize_text(value)
    if not text:
        return LrCellClassification(status="missing", numeric_value=None)

    try:
        lr_value = float(text)
    except (TypeError, ValueError):
        return LrCellClassification(status="non_numeric", numeric_value=None)

    if not math.isfinite(lr_value):
        return LrCellClassification(status="non_numeric", numeric_value=None)

    if lr_value <= 0:
        return LrCellClassification(status="non_positive", numeric_value=lr_value)

    return LrCellClassification(status="valid", numeric_value=lr_value)


def output_relative_path(output_workbook: str, scenario_id: str) -> Path:
    path = Path(output_workbook)

    if path.parts[: len(CANONICAL_OUTPUTS_ROOT.parts)] == CANONICAL_OUTPUTS_ROOT.parts:
        return Path(*path.parts[len(CANONICAL_OUTPUTS_ROOT.parts) :])

    # Fallback for absolute paths that still contain lr_differential/outputs.
    parts = path.parts
    for idx in range(len(parts) - 1):
        if parts[idx] == "lr_differential" and parts[idx + 1] == "outputs":
            if idx + 2 < len(parts):
                return Path(*parts[idx + 2 :])

    return Path(scenario_id) / path.name


def discover_model_ids(outputs_root: Path) -> list[str]:
    if not outputs_root.exists():
        raise FileNotFoundError(f"Outputs root does not exist: {outputs_root}")

    model_ids = sorted(
        p.name for p in outputs_root.iterdir() if p.is_dir() and not p.name.startswith(".")
    )
    if not model_ids:
        raise ValueError(
            "Could not discover model directories under outputs root. "
            "Expected layout: <outputs_root>/<model_id>/<scenario_id>/*.xlsx"
        )
    return model_ids


def audit_outputs(
    manifest_df: pd.DataFrame,
    *,
    repo_root: Path,
    outputs_root: Path,
    model_ids: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    required_cols = {
        "scenario_id",
        "pair_index",
        "input_workbook",
        "output_workbook",
    }
    missing_cols = sorted(required_cols - set(manifest_df.columns))
    if missing_cols:
        raise ValueError(f"Manifest missing required columns: {missing_cols}")

    active_models = model_ids or discover_model_ids(outputs_root)

    input_cache: dict[Path, tuple[list[int], dict[int, str]]] = {}
    summary_rows: list[dict[str, object]] = []
    invalid_rows: list[dict[str, object]] = []

    for model_id in active_models:
        for row in manifest_df.sort_values(["scenario_id", "pair_index"]).itertuples(index=False):
            scenario_id = str(row.scenario_id)
            pair_index = int(row.pair_index)

            input_path = repo_root / str(row.input_workbook)
            output_rel = output_relative_path(str(row.output_workbook), scenario_id)
            output_path = outputs_root / model_id / output_rel

            if input_path not in input_cache:
                if not input_path.exists():
                    raise FileNotFoundError(f"Input workbook does not exist: {input_path}")
                df_input = pd.read_excel(input_path, sheet_name=0, header=None)
                finding_rows = finding_row_indexes(df_input)
                finding_texts = {
                    row_idx: normalize_text(df_input.iat[row_idx, 0]) for row_idx in finding_rows
                }
                input_cache[input_path] = (finding_rows, finding_texts)

            finding_rows, finding_texts = input_cache[input_path]
            expected_findings = len(finding_rows)
            valid_count = 0
            missing_count = 0
            non_positive_count = 0
            non_numeric_count = 0

            if output_path.exists():
                df_output = pd.read_excel(output_path, sheet_name=0, header=None)
                result_col = df_output.shape[1] - 1
            else:
                df_output = None
                result_col = None

            for row_idx in finding_rows:
                finding = finding_texts[row_idx]
                raw_value: object | None

                if df_output is None or result_col is None or row_idx >= df_output.shape[0]:
                    classification = LrCellClassification(status="missing", numeric_value=None)
                    raw_value = ""
                else:
                    raw_value = df_output.iat[row_idx, result_col]
                    classification = classify_lr_cell(raw_value)

                status = classification.status
                if status == "valid":
                    valid_count += 1
                    continue

                if status == "missing":
                    missing_count += 1
                elif status == "non_positive":
                    non_positive_count += 1
                elif status == "non_numeric":
                    non_numeric_count += 1
                else:
                    raise ValueError(f"Unexpected status: {status}")

                invalid_rows.append(
                    {
                        "model_id": model_id,
                        "scenario_id": scenario_id,
                        "pair_index": pair_index,
                        "input_workbook": str(input_path.relative_to(repo_root)),
                        "output_workbook": str(output_path.relative_to(repo_root)),
                        "row_index": row_idx,
                        "finding": finding,
                        "status": status,
                        "raw_value": "" if pd.isna(raw_value) else str(raw_value),
                    }
                )

            total_invalid = missing_count + non_positive_count + non_numeric_count
            summary_rows.append(
                {
                    "model_id": model_id,
                    "scenario_id": scenario_id,
                    "pair_index": pair_index,
                    "input_workbook": str(input_path.relative_to(repo_root)),
                    "output_workbook": str(output_path.relative_to(repo_root)),
                    "expected_findings": expected_findings,
                    "valid_positive_lrs": valid_count,
                    "missing_rows": missing_count,
                    "non_positive_rows": non_positive_count,
                    "non_numeric_rows": non_numeric_count,
                    "total_invalid_rows": total_invalid,
                    "output_exists": bool(output_path.exists()),
                    "passes": total_invalid == 0 and valid_count == expected_findings,
                }
            )

    summary_df = pd.DataFrame(summary_rows)
    invalid_df = pd.DataFrame(invalid_rows)
    if not invalid_df.empty:
        invalid_df = invalid_df.sort_values(
            ["model_id", "scenario_id", "pair_index", "row_index"]
        ).reset_index(drop=True)
    return summary_df, invalid_df
