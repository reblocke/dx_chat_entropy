from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _copy_rel(repo_root: Path, bundle_root: Path, rel_path: str) -> None:
    src = repo_root / rel_path
    dst = bundle_root / rel_path
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")


def _write_bundle_fixture(bundle_root: Path, model_id: str) -> None:
    scenario_id = "demo_case"
    sheet_name = "s01_r00_2cat"

    # Minimal normalized input workbook (used by audit script).
    inputs_wb = bundle_root / "data/processed/lr_one_vs_rest/inputs" / f"{scenario_id}_inputs.xlsx"
    inputs_wb.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(inputs_wb, engine="openpyxl") as writer:
        pd.DataFrame(
            [
                ["Diagnosis:", "Cat A", "Cat B"],
                ["Finding 1", "", ""],
            ]
        ).to_excel(writer, sheet_name=sheet_name, index=False, header=False)

    # Raw one-vs-rest workbook.
    raw_wb = (
        bundle_root
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

    # Pre-seeded coherent workbook (projection will overwrite in test).
    coherent_wb = (
        bundle_root
        / "data/processed/lr_one_vs_rest/coherent_outputs_by_model"
        / model_id
        / f"{scenario_id}_coherent.xlsx"
    )
    coherent_wb.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(coherent_wb, engine="openpyxl") as writer:
        pd.DataFrame(
            [
                ["Diagnosis:", "Cat A", "Cat B"],
                ["Finding 1", 1.5, 0.9],
            ]
        ).to_excel(writer, sheet_name=sheet_name, index=False, header=False)

    manifests_dir = bundle_root / "data/processed/lr_one_vs_rest/manifests"
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
                "categories_count": 2,
                "findings_count": 1,
                "normalized_input_workbook": str(
                    Path("data/processed/lr_one_vs_rest/inputs") / f"{scenario_id}_inputs.xlsx"
                ),
                "warnings": "",
            }
        ]
    ).to_csv(manifests_dir / "inputs_manifest.csv", index=False)
    pd.DataFrame(
        [
            {
                "scenario_id": scenario_id,
                "source_workbook": "data/raw/lr_matrices/demo.xlsx",
                "source_sheet": "Tier 1",
                "schema_order": 1,
                "schema_row_idx": 0,
                "schema_sheet_name": sheet_name,
                "prior_row_idx": 1,
                "category_order": 1,
                "category": "Cat A",
                "prior_raw": 0.6,
                "prior_normalized": 0.6,
                "prior_vector_sum_raw": 1.0,
            },
            {
                "scenario_id": scenario_id,
                "source_workbook": "data/raw/lr_matrices/demo.xlsx",
                "source_sheet": "Tier 1",
                "schema_order": 1,
                "schema_row_idx": 0,
                "schema_sheet_name": sheet_name,
                "prior_row_idx": 1,
                "category_order": 2,
                "category": "Cat B",
                "prior_raw": 0.4,
                "prior_normalized": 0.4,
                "prior_vector_sum_raw": 1.0,
            },
        ]
    ).to_csv(manifests_dir / "schema_priors.csv", index=False)
    (manifests_dir / "run_manifest.json").write_text(
        json.dumps({"generated_at_utc": "2026-03-12T00:00:00Z"}),
        encoding="utf-8",
    )
    (manifests_dir / f"coherence_projection_failures_{model_id}.csv").write_text(
        "model_id,scenario_id,schema_sheet_name,row_index,finding,reason\n",
        encoding="utf-8",
    )

    # README and notebook references used by checker.
    (bundle_root / "notebooks").mkdir(parents=True, exist_ok=True)
    (bundle_root / "notebooks/32_one_vs_rest_project_coherent_lrs.ipynb").write_text(
        json.dumps({"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}),
        encoding="utf-8",
    )
    (bundle_root / "README.md").write_text(
        "\n".join(
            [
                "# Demo OVR Review Bundle",
                "`scripts/project_one_vs_rest_coherent_lrs.py`",
                "`scripts/audit_one_vs_rest_outputs.py`",
                "`scripts/build_one_vs_rest_inputs.py`",
                "`notebooks/32_one_vs_rest_project_coherent_lrs.ipynb`",
                "`data/processed/lr_one_vs_rest/manifests/inputs_manifest.csv`",
            ]
        ),
        encoding="utf-8",
    )

    manifest_payload = {
        "bundle_type": "ovr_review_bundle",
        "bundle_version": "1.0.0",
        "pipeline": "lr_one_vs_rest",
        "created_at_utc": "2026-03-12T00:00:00Z",
        "model_ids": [model_id],
        "capabilities": ["project_coherent", "audit_outputs", "validate_bundle"],
        "supported_commands": [
            f"python scripts/project_one_vs_rest_coherent_lrs.py --model-id {model_id}",
            (f"python scripts/audit_one_vs_rest_outputs.py --model-id {model_id} --coherence-mode"),
        ],
        "unsupported_commands": [
            "python scripts/build_one_vs_rest_inputs.py",
            f"python scripts/run_one_vs_rest_batch.py --model-id {model_id}",
        ],
        "included_paths": [
            "bundle_manifest.json",
            "README.md",
            "scripts",
            "src",
            "notebooks/32_one_vs_rest_project_coherent_lrs.ipynb",
            f"data/processed/lr_one_vs_rest/outputs_by_model/{model_id}",
            f"data/processed/lr_one_vs_rest/coherent_outputs_by_model/{model_id}",
            "data/processed/lr_one_vs_rest/manifests",
        ],
        "omitted_paths": ["data/raw/lr_matrices"],
        "notes": "fixture bundle",
    }
    (bundle_root / "bundle_manifest.json").write_text(
        json.dumps(manifest_payload, indent=2),
        encoding="utf-8",
    )


def _build_bundle_fixture(tmp_path: Path) -> tuple[Path, str]:
    repo_root = _repo_root()
    model_id = "gpt-test"
    bundle_root = tmp_path / "bundle"

    copy_files = [
        "scripts/project_one_vs_rest_coherent_lrs.py",
        "scripts/audit_one_vs_rest_outputs.py",
        "scripts/build_one_vs_rest_inputs.py",
        "scripts/check_one_vs_rest_bundle.py",
        "src/dx_chat_entropy/__init__.py",
        "src/dx_chat_entropy/paths.py",
        "src/dx_chat_entropy/lr_differential_inputs.py",
        "src/dx_chat_entropy/lr_one_vs_rest_audit.py",
        "src/dx_chat_entropy/lr_one_vs_rest_bundle.py",
        "src/dx_chat_entropy/lr_one_vs_rest_coherence.py",
        "src/dx_chat_entropy/lr_one_vs_rest_inputs.py",
    ]
    for rel in copy_files:
        _copy_rel(repo_root, bundle_root, rel)

    _write_bundle_fixture(bundle_root, model_id)
    return bundle_root, model_id


def test_review_bundle_projection_audit_and_checker(tmp_path: Path) -> None:
    bundle_root, model_id = _build_bundle_fixture(tmp_path)

    # Projection runs from bundle root.
    proj = subprocess.run(
        [
            sys.executable,
            "scripts/project_one_vs_rest_coherent_lrs.py",
            "--model-id",
            model_id,
            "--overwrite",
        ],
        cwd=bundle_root,
        capture_output=True,
        text=True,
    )
    assert proj.returncode == 0, proj.stdout + proj.stderr

    # Audit runs from bundle root in coherence mode.
    audit = subprocess.run(
        [
            sys.executable,
            "scripts/audit_one_vs_rest_outputs.py",
            "--model-id",
            model_id,
            "--coherence-mode",
        ],
        cwd=bundle_root,
        capture_output=True,
        text=True,
    )
    assert audit.returncode == 0, audit.stdout + audit.stderr

    # Build fails intentionally in review bundle profile.
    build = subprocess.run(
        [sys.executable, "scripts/build_one_vs_rest_inputs.py"],
        cwd=bundle_root,
        capture_output=True,
        text=True,
    )
    assert build.returncode != 0
    assert "Raw LR source matrices are not packaged in this review bundle" in (
        build.stdout + build.stderr
    )

    # Checker passes for this fixture.
    check = subprocess.run(
        [
            sys.executable,
            "scripts/check_one_vs_rest_bundle.py",
            "--bundle-root",
            ".",
            "--model-id",
            model_id,
            "--repo-root",
            ".",
        ],
        cwd=bundle_root,
        capture_output=True,
        text=True,
    )
    assert check.returncode == 0, check.stdout + check.stderr
