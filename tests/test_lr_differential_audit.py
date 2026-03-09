from __future__ import annotations

from pathlib import Path

import pandas as pd

from dx_chat_entropy.lr_differential_audit import (
    audit_outputs,
    classify_lr_cell,
    output_relative_path,
)


def _write_pair_input(path: Path) -> None:
    df = pd.DataFrame(
        [
            ["Dx A", "", "Dx B", ""],
            ["Example A", "", "Example B", ""],
            ["Finding 1", "", "", ""],
            ["Finding 2", "", "", ""],
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(path, index=False, header=False)


def _write_pair_output(path: Path, values: list[object]) -> None:
    df = pd.DataFrame(
        [
            ["Dx A", "", "Dx B", "", "Differential LR (test)"],
            ["Example A", "", "Example B", "", ""],
            ["Finding 1", "", "", "", values[0]],
            ["Finding 2", "", "", "", values[1]],
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(path, index=False, header=False)


def test_classify_lr_cell_rules() -> None:
    assert classify_lr_cell("2.5").status == "valid"
    assert classify_lr_cell(0).status == "non_positive"
    assert classify_lr_cell("-0.1").status == "non_positive"
    assert classify_lr_cell("abc").status == "non_numeric"
    assert classify_lr_cell(float("nan")).status == "missing"


def test_output_relative_path_from_canonical_manifest_path() -> None:
    rel = output_relative_path(
        "data/processed/lr_differential/outputs/scenario_a/001_pair_filled.xlsx",
        "scenario_a",
    )
    assert rel == Path("scenario_a/001_pair_filled.xlsx")


def test_audit_outputs_detects_non_positive_rows(tmp_path: Path) -> None:
    repo_root = tmp_path
    input_rel = Path("data/processed/lr_differential/inputs/scenario_a/001_pair.xlsx")
    output_rel = Path("data/processed/lr_differential/outputs/scenario_a/001_pair_filled.xlsx")

    input_path = repo_root / input_rel
    model_output_path = (
        repo_root
        / "data/processed/lr_differential/outputs_by_model/gpt-test/scenario_a/001_pair_filled.xlsx"
    )

    _write_pair_input(input_path)
    _write_pair_output(model_output_path, [3.0, -1.0])

    manifest_df = pd.DataFrame(
        [
            {
                "scenario_id": "scenario_a",
                "pair_index": 1,
                "input_workbook": str(input_rel),
                "output_workbook": str(output_rel),
            }
        ]
    )

    summary_df, invalid_df = audit_outputs(
        manifest_df,
        repo_root=repo_root,
        outputs_root=repo_root / "data/processed/lr_differential/outputs_by_model",
        model_ids=["gpt-test"],
    )

    assert len(summary_df) == 1
    row = summary_df.iloc[0]
    assert row["expected_findings"] == 2
    assert row["valid_positive_lrs"] == 1
    assert row["non_positive_rows"] == 1
    assert row["total_invalid_rows"] == 1
    assert not row["passes"]

    assert len(invalid_df) == 1
    invalid = invalid_df.iloc[0]
    assert invalid["row_index"] == 3
    assert invalid["finding"] == "Finding 2"
    assert invalid["status"] == "non_positive"
