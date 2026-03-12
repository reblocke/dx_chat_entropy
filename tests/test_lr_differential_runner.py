from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from dx_chat_entropy.lr_differential_runner import (
    build_runtime_config,
    default_invalid_rows_path,
    load_invalid_rows_for_repair,
    normalize_resume_mode,
    workbook_passes_existing_output,
)
from dx_chat_entropy.paths import ProjectPaths


def _write_pair_input(path: Path) -> None:
    df = pd.DataFrame(
        [
            ["Dx A", "", "Dx B", ""],
            ["Example A1", "Example A2", "Example B1", "Example B2"],
            ["Finding 1", "", "", ""],
            ["", "", "", ""],
            ["Finding 2", "", "", ""],
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(path, index=False, header=False)


def _write_pair_output(path: Path, lr_row_2: object, lr_row_4: object) -> None:
    df = pd.DataFrame(
        [
            ["Dx A", "", "Dx B", "", "Differential LR (test)"],
            ["Example A1", "Example A2", "Example B1", "Example B2", ""],
            ["Finding 1", "", "", "", lr_row_2],
            ["", "", "", "", ""],
            ["Finding 2", "", "", "", lr_row_4],
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(path, index=False, header=False)


def test_normalize_resume_mode_and_legacy_mapping() -> None:
    assert normalize_resume_mode("recompute") == "recompute"
    assert normalize_resume_mode("skip_passing") == "skip_passing"
    assert normalize_resume_mode("repair_invalid") == "repair_invalid"
    assert normalize_resume_mode("recompute", legacy_repair_mode=True) == "repair_invalid"

    with pytest.raises(ValueError, match="Unsupported DX_RESUME_MODE"):
        normalize_resume_mode("bogus")


def test_default_invalid_rows_path_prefers_model_scoped_file(tmp_path: Path) -> None:
    manifests = tmp_path / "lr_differential" / "manifests"
    manifests.mkdir(parents=True)
    model_path = manifests / "invalid_rows_model-x.csv"
    generic_path = manifests / "invalid_rows.csv"

    generic_path.write_text("x\n", encoding="utf-8")
    model_path.write_text("x\n", encoding="utf-8")
    assert default_invalid_rows_path(tmp_path, "model-x") == model_path

    model_path.unlink()
    assert default_invalid_rows_path(tmp_path, "model-x") == generic_path


def test_build_runtime_config_resolves_invalid_rows_path_and_resume_mode(tmp_path: Path) -> None:
    repo_root = tmp_path
    processed = repo_root / "data" / "processed" / "lr_differential" / "manifests"
    processed.mkdir(parents=True, exist_ok=True)

    model_path = processed / "invalid_rows_gpt-test.csv"
    model_path.write_text("model_id\n", encoding="utf-8")

    config = build_runtime_config(
        repo_root=repo_root,
        paths=ProjectPaths(root=repo_root),
        environ={
            "DX_MODEL_ID": "gpt-test",
            "DX_RESUME_MODE": "skip_passing",
        },
    )
    assert config.resume_mode == "skip_passing"
    assert config.invalid_rows_path == model_path

    legacy_cfg = build_runtime_config(
        repo_root=repo_root,
        paths=ProjectPaths(root=repo_root),
        environ={
            "DX_MODEL_ID": "gpt-test",
            "DX_REPAIR_MODE": "true",
        },
    )
    assert legacy_cfg.resume_mode == "repair_invalid"


def test_workbook_passes_existing_output_checks_all_finding_rows(tmp_path: Path) -> None:
    input_path = tmp_path / "input.xlsx"
    output_path = tmp_path / "output.xlsx"
    _write_pair_input(input_path)

    df_in = pd.read_excel(input_path, header=None)

    _write_pair_output(output_path, 2.5, 0.7)
    assert workbook_passes_existing_output(
        df_in=df_in,
        output_path=output_path,
        max_findings=None,
    )

    _write_pair_output(output_path, 2.5, 0.0)
    assert not workbook_passes_existing_output(
        df_in=df_in,
        output_path=output_path,
        max_findings=None,
    )


def test_load_invalid_rows_for_repair_filters_model_and_scenario(tmp_path: Path) -> None:
    invalid_rows_path = tmp_path / "invalid_rows.csv"
    pd.DataFrame(
        [
            {
                "model_id": "m1",
                "scenario_id": "s1",
                "pair_index": 1,
                "input_workbook": "in1.xlsx",
                "output_workbook": "out1.xlsx",
                "row_index": 2,
            },
            {
                "model_id": "m1",
                "scenario_id": "s2",
                "pair_index": 2,
                "input_workbook": "in2.xlsx",
                "output_workbook": "out2.xlsx",
                "row_index": 3,
            },
            {
                "model_id": "m2",
                "scenario_id": "s1",
                "pair_index": 1,
                "input_workbook": "in3.xlsx",
                "output_workbook": "out3.xlsx",
                "row_index": 4,
            },
        ]
    ).to_csv(invalid_rows_path, index=False)

    selected = load_invalid_rows_for_repair(
        invalid_rows_path=invalid_rows_path,
        model_id="m1",
        scenario_filter=["s2"],
        max_rows=1,
    )
    assert len(selected) == 1
    row = selected.iloc[0]
    assert row["model_id"] == "m1"
    assert row["scenario_id"] == "s2"
