from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .lr_differential_inputs import normalize_cell


@dataclass(frozen=True)
class LrCellClassification:
    status: str
    numeric_value: float | None


def normalize_text(value: object) -> str:
    # Keep a compatibility wrapper name while routing all normalization through
    # the shared utility used by differential parsing/runtime code.
    return normalize_cell(value)


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


def one_vs_rest_positions(df_input: pd.DataFrame) -> tuple[list[int], list[int]]:
    category_cols: list[int] = []
    for col_idx in range(1, df_input.shape[1]):
        header = normalize_text(df_input.iat[0, col_idx])
        if not header:
            continue
        if header.lower().startswith("for examples:"):
            continue
        category_cols.append(col_idx)

    finding_rows: list[int] = []
    for row_idx in range(1, df_input.shape[0]):
        finding = normalize_text(df_input.iat[row_idx, 0])
        if finding:
            finding_rows.append(row_idx)

    return category_cols, finding_rows


def discover_model_ids(outputs_root: Path) -> list[str]:
    if not outputs_root.exists():
        raise FileNotFoundError(f"Outputs root does not exist: {outputs_root}")

    model_ids = sorted(
        p.name for p in outputs_root.iterdir() if p.is_dir() and not p.name.startswith(".")
    )
    if not model_ids:
        raise ValueError(
            "Could not discover model directories under outputs root. "
            "Expected layout: <outputs_root>/<model_id>/<scenario_id>_filled.xlsx"
        )
    return model_ids


def audit_outputs(
    manifest_df: pd.DataFrame,
    *,
    repo_root: Path,
    outputs_root: Path,
    output_filename_suffix: str = "_filled.xlsx",
    model_ids: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    required_cols = {
        "scenario_id",
        "schema_order",
        "schema_sheet_name",
        "categories_count",
        "findings_count",
        "normalized_input_workbook",
    }
    missing_cols = sorted(required_cols - set(manifest_df.columns))
    if missing_cols:
        raise ValueError(f"Manifest missing required columns: {missing_cols}")

    active_models = model_ids or discover_model_ids(outputs_root)

    summary_rows: list[dict[str, object]] = []
    invalid_rows: list[dict[str, object]] = []

    for model_id in active_models:
        sorted_rows = manifest_df.sort_values(["scenario_id", "schema_order"]).itertuples(
            index=False
        )
        for row in sorted_rows:
            scenario_id = str(row.scenario_id)
            schema_order = int(row.schema_order)
            schema_sheet_name = str(row.schema_sheet_name)
            categories_count = int(row.categories_count)
            findings_count = int(row.findings_count)

            input_workbook = repo_root / str(row.normalized_input_workbook)
            output_workbook = outputs_root / model_id / f"{scenario_id}{output_filename_suffix}"

            if not input_workbook.exists():
                raise FileNotFoundError(
                    f"Normalized input workbook does not exist: {input_workbook}"
                )

            df_input = pd.read_excel(input_workbook, sheet_name=schema_sheet_name, header=None)
            category_cols, finding_rows = one_vs_rest_positions(df_input)
            expected_cells_derived = len(category_cols) * len(finding_rows)
            expected_cells_manifest = categories_count * findings_count
            schema_shape_matches_manifest = expected_cells_derived == expected_cells_manifest

            finding_texts = {
                row_idx: normalize_text(df_input.iat[row_idx, 0]) for row_idx in finding_rows
            }
            category_labels = {
                col_idx: normalize_text(df_input.iat[0, col_idx]) for col_idx in category_cols
            }

            workbook_exists = output_workbook.exists()
            sheet_exists = False
            if workbook_exists:
                try:
                    df_output = pd.read_excel(
                        output_workbook, sheet_name=schema_sheet_name, header=None
                    )
                    sheet_exists = True
                except ValueError:
                    df_output = None
            else:
                df_output = None

            valid_count = 0
            missing_count = 0
            non_numeric_count = 0
            non_positive_count = 0

            for row_idx in finding_rows:
                for col_idx in category_cols:
                    finding = finding_texts[row_idx]
                    category = category_labels[col_idx]

                    if df_output is None:
                        classification = LrCellClassification(status="missing", numeric_value=None)
                        raw_value = ""
                    elif row_idx >= df_output.shape[0] or col_idx >= df_output.shape[1]:
                        classification = LrCellClassification(status="missing", numeric_value=None)
                        raw_value = ""
                    else:
                        raw_value = df_output.iat[row_idx, col_idx]
                        classification = classify_lr_cell(raw_value)

                    status = classification.status
                    if status == "valid":
                        valid_count += 1
                        continue

                    if status == "missing":
                        missing_count += 1
                    elif status == "non_numeric":
                        non_numeric_count += 1
                    elif status == "non_positive":
                        non_positive_count += 1
                    else:
                        raise ValueError(f"Unexpected status: {status}")

                    invalid_rows.append(
                        {
                            "model_id": model_id,
                            "scenario_id": scenario_id,
                            "schema_order": schema_order,
                            "schema_sheet_name": schema_sheet_name,
                            "input_workbook": str(input_workbook.relative_to(repo_root)),
                            "output_workbook": str(output_workbook.relative_to(repo_root)),
                            "row_index": row_idx,
                            "col_index": col_idx,
                            "finding": finding,
                            "category": category,
                            "status": status,
                            "raw_value": "" if pd.isna(raw_value) else str(raw_value),
                        }
                    )

            total_invalid = missing_count + non_numeric_count + non_positive_count
            summary_rows.append(
                {
                    "model_id": model_id,
                    "scenario_id": scenario_id,
                    "schema_order": schema_order,
                    "schema_sheet_name": schema_sheet_name,
                    "input_workbook": str(input_workbook.relative_to(repo_root)),
                    "output_workbook": str(output_workbook.relative_to(repo_root)),
                    "expected_cells_manifest": expected_cells_manifest,
                    "expected_cells_derived": expected_cells_derived,
                    "schema_shape_matches_manifest": schema_shape_matches_manifest,
                    "valid_positive_cells": valid_count,
                    "missing_cells": missing_count,
                    "non_numeric_cells": non_numeric_count,
                    "non_positive_cells": non_positive_count,
                    "total_invalid_cells": total_invalid,
                    "output_exists": workbook_exists,
                    "sheet_exists": sheet_exists,
                    "passes": (
                        total_invalid == 0
                        and valid_count == expected_cells_manifest
                        and schema_shape_matches_manifest
                    ),
                }
            )

    summary_df = pd.DataFrame(summary_rows)
    invalid_df = pd.DataFrame(invalid_rows)
    if not invalid_df.empty:
        invalid_df = invalid_df.sort_values(
            ["model_id", "scenario_id", "schema_order", "row_index", "col_index"]
        ).reset_index(drop=True)

    return summary_df, invalid_df
