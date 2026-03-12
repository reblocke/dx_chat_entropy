from __future__ import annotations

from pathlib import Path

import pandas as pd

from dx_chat_entropy.lr_one_vs_rest_audit import audit_outputs, classify_lr_cell


def _write_input_workbook(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df = pd.DataFrame(
            [
                ["Diagnosis:", "Cat A", "Cat B"],
                ["Finding 1", "", ""],
                ["Finding 2", "", ""],
            ]
        )
        df.to_excel(writer, sheet_name="s01_r00_2cat", index=False, header=False)


def _write_output_workbook(path: Path, values: list[list[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df = pd.DataFrame(
            [
                ["Diagnosis:", "Cat A", "Cat B"],
                ["Finding 1", values[0][0], values[0][1]],
                ["Finding 2", values[1][0], values[1][1]],
            ]
        )
        df.to_excel(writer, sheet_name="s01_r00_2cat", index=False, header=False)


def test_classify_lr_cell() -> None:
    assert classify_lr_cell("1.2").status == "valid"
    assert classify_lr_cell(0).status == "non_positive"
    assert classify_lr_cell("abc").status == "non_numeric"
    assert classify_lr_cell("").status == "missing"


def test_audit_outputs_detects_non_positive_cell(tmp_path: Path) -> None:
    repo_root = tmp_path
    input_rel = Path("data/processed/lr_one_vs_rest/inputs/scenario_a_inputs.xlsx")
    input_abs = repo_root / input_rel
    _write_input_workbook(input_abs)

    output_abs = (
        repo_root / "data/processed/lr_one_vs_rest/outputs_by_model/gpt-test/scenario_a_filled.xlsx"
    )
    _write_output_workbook(output_abs, [[1.5, 2.5], [0.0, 1.2]])

    manifest_df = pd.DataFrame(
        [
            {
                "scenario_id": "scenario_a",
                "source_workbook": "data/raw/demo.xlsx",
                "source_sheet": "Sheet1",
                "schema_order": 1,
                "schema_row_idx": 0,
                "schema_sheet_name": "s01_r00_2cat",
                "categories_count": 2,
                "findings_count": 2,
                "normalized_input_workbook": str(input_rel),
                "warnings": "",
            }
        ]
    )

    summary_df, invalid_df = audit_outputs(
        manifest_df,
        repo_root=repo_root,
        outputs_root=repo_root / "data/processed/lr_one_vs_rest/outputs_by_model",
        model_ids=["gpt-test"],
    )

    assert len(summary_df) == 1
    row = summary_df.iloc[0]
    assert row["expected_cells_manifest"] == 4
    assert row["valid_positive_cells"] == 3
    assert row["non_positive_cells"] == 1
    assert row["total_invalid_cells"] == 1
    assert not row["passes"]

    assert len(invalid_df) == 1
    invalid = invalid_df.iloc[0]
    assert invalid["status"] == "non_positive"
    assert invalid["row_index"] == 2
    assert invalid["col_index"] == 1
