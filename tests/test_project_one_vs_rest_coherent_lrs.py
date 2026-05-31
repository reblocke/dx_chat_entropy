from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pandas as pd


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _write_projection_fixture(repo_root: Path, model_id: str) -> None:
    scenario_id = "chest_pain_carter_8"
    sheet_name = "s01_r00_2cat"
    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "pyproject.toml").write_text(
        '[project]\nname = "projection-fixture"\n',
        encoding="utf-8",
    )

    inputs_wb = repo_root / "data/processed/lr_one_vs_rest/inputs" / f"{scenario_id}_inputs.xlsx"
    inputs_wb.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(inputs_wb, engine="openpyxl") as writer:
        pd.DataFrame(
            [
                ["Diagnosis:", "Cat A", "Cat B"],
                ["Finding 1", "", ""],
            ]
        ).to_excel(writer, sheet_name=sheet_name, index=False, header=False)

    raw_wb = (
        repo_root
        / "data/processed/lr_one_vs_rest/outputs_by_model"
        / model_id
        / f"{scenario_id}_filled.xlsx"
    )
    raw_wb.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(raw_wb, engine="openpyxl") as writer:
        pd.DataFrame(
            [
                ["Diagnosis:", "Cat A", "Cat B"],
                ["Finding 1", 2.0, 0.8],
            ]
        ).to_excel(writer, sheet_name=sheet_name, index=False, header=False)

    manifests_dir = repo_root / "data/processed/lr_one_vs_rest/manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "scenario_id": scenario_id,
                "source_workbook": "data/raw/lr_matrices/demo.xlsx",
                "source_sheet": "Tier 1",
                "schema_order": 1,
                "schema_row_idx": 0,
                "schema_sheet_name": sheet_name,
                "normalized_input_workbook": str(
                    Path("data/processed/lr_one_vs_rest/inputs") / f"{scenario_id}_inputs.xlsx"
                ),
            }
        ]
    ).to_csv(manifests_dir / "inputs_manifest.csv", index=False)
    pd.DataFrame(
        [
            {
                "scenario_id": scenario_id,
                "schema_order": 1,
                "schema_sheet_name": sheet_name,
                "category_order": 1,
                "category": "Cat A",
                "prior_normalized": 0.6,
            },
            {
                "scenario_id": scenario_id,
                "schema_order": 1,
                "schema_sheet_name": sheet_name,
                "category_order": 2,
                "category": "Cat B",
                "prior_normalized": 0.4,
            },
        ]
    ).to_csv(manifests_dir / "schema_priors.csv", index=False)


def test_partial_projection_requires_opt_in(tmp_path: Path) -> None:
    repo_root = _repo_root()
    cmd = [
        sys.executable,
        "scripts/project_one_vs_rest_coherent_lrs.py",
        "--model-id",
        "gpt-5.3-chat-latest",
        "--scenario-filter",
        "chest_pain_carter_8",
        "--max-schemas",
        "1",
        "--max-findings",
        "1",
        "--overwrite",
        "--coherent-outputs-root",
        str(tmp_path / "coherent"),
    ]
    proc = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True)
    assert proc.returncode != 0
    assert "Refusing canonical write by default" in (proc.stdout + proc.stderr)


def test_partial_projection_runs_with_opt_in(tmp_path: Path) -> None:
    fixture_root = tmp_path / "projection-fixture"
    model_id = "gpt-5.3-chat-latest"
    _write_projection_fixture(fixture_root, model_id)
    repo_root = _repo_root()
    cmd = [
        sys.executable,
        "scripts/project_one_vs_rest_coherent_lrs.py",
        "--model-id",
        model_id,
        "--scenario-filter",
        "chest_pain_carter_8",
        "--max-schemas",
        "1",
        "--max-findings",
        "1",
        "--overwrite",
        "--allow-partial-write",
        "--repo-root",
        str(fixture_root),
        "--coherent-outputs-root",
        str(tmp_path / "coherent"),
    ]
    proc = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "[partial-write-warning]" in (proc.stdout + proc.stderr)
