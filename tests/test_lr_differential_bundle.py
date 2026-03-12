from __future__ import annotations

import json
from pathlib import Path

from dx_chat_entropy.lr_differential_bundle import validate_bundle


def _write_notebook_with_import(path: Path, module: str) -> None:
    payload = {
        "cells": [
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [f"import {module}\n"],
            }
        ],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _create_minimal_bundle_layout(bundle_root: Path, *, include_paths_module: bool = True) -> None:
    (bundle_root / "pyproject.toml").write_text("[project]\nname='x'\nversion='0.1.0'\n")
    (bundle_root / "uv.lock").write_text("version = 1\n", encoding="utf-8")

    src_pkg = bundle_root / "code" / "src" / "dx_chat_entropy"
    src_pkg.mkdir(parents=True, exist_ok=True)
    (src_pkg / "__init__.py").write_text("", encoding="utf-8")
    if include_paths_module:
        (src_pkg / "paths.py").write_text("def get_paths():\n    return None\n", encoding="utf-8")

    (bundle_root / "code" / "config").mkdir(parents=True, exist_ok=True)
    (bundle_root / "code" / "config" / "lr_differential_scenarios.yaml").write_text(
        "scenarios: []\n",
        encoding="utf-8",
    )

    _write_notebook_with_import(
        bundle_root / "code" / "notebooks" / "21_differential_estimate_lrs.ipynb",
        "dx_chat_entropy.paths",
    )

    manifests_dir = bundle_root / "data" / "processed" / "lr_differential" / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    (manifests_dir / "invalid_rows.csv").write_text("model_id\n", encoding="utf-8")

    logs_dir = manifests_dir / "logs" / "gpt-test"
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / "scenario.log").write_text("ok\n", encoding="utf-8")
    (manifests_dir / "run_ledger_differential_gpt-test.csv").write_text(
        "scenario_id,status,start_utc,end_utc,exit_code,log_path\n",
        encoding="utf-8",
    )


def test_validate_bundle_passes_for_minimal_consistent_bundle(tmp_path: Path) -> None:
    bundle_root = tmp_path / "bundle"
    bundle_root.mkdir(parents=True, exist_ok=True)
    _create_minimal_bundle_layout(bundle_root)

    result = validate_bundle(bundle_root=bundle_root, model_id="gpt-test")
    assert result.ok
    assert not result.errors


def test_validate_bundle_flags_missing_imported_local_module(tmp_path: Path) -> None:
    bundle_root = tmp_path / "bundle"
    bundle_root.mkdir(parents=True, exist_ok=True)
    _create_minimal_bundle_layout(bundle_root, include_paths_module=False)

    result = validate_bundle(bundle_root=bundle_root, model_id="gpt-test")
    assert not result.ok
    assert any("Imported local module missing from bundle" in err for err in result.errors)


def test_validate_bundle_flags_stale_missing_manifest_artifact(tmp_path: Path) -> None:
    bundle_root = tmp_path / "bundle"
    bundle_root.mkdir(parents=True, exist_ok=True)
    _create_minimal_bundle_layout(bundle_root)

    manifests_dir = bundle_root / "data" / "processed" / "lr_differential" / "manifests"
    (manifests_dir / "pairs_manifest_missing_gpt-test.csv").write_text("x\n", encoding="utf-8")

    result = validate_bundle(bundle_root=bundle_root, model_id="gpt-test")
    assert not result.ok
    assert any("Stale missing-output manifests must not be shipped" in err for err in result.errors)


def test_validate_bundle_flags_missing_repair_target(tmp_path: Path) -> None:
    bundle_root = tmp_path / "bundle"
    bundle_root.mkdir(parents=True, exist_ok=True)
    _create_minimal_bundle_layout(bundle_root)

    manifests_dir = bundle_root / "data" / "processed" / "lr_differential" / "manifests"
    (manifests_dir / "invalid_rows.csv").unlink()

    result = validate_bundle(bundle_root=bundle_root, model_id="gpt-test")
    assert not result.ok
    assert any("Repair target file missing" in err for err in result.errors)


def test_validate_bundle_flags_logs_without_ledger(tmp_path: Path) -> None:
    bundle_root = tmp_path / "bundle"
    bundle_root.mkdir(parents=True, exist_ok=True)
    _create_minimal_bundle_layout(bundle_root)

    manifests_dir = bundle_root / "data" / "processed" / "lr_differential" / "manifests"
    (manifests_dir / "run_ledger_differential_gpt-test.csv").unlink()

    result = validate_bundle(bundle_root=bundle_root, model_id="gpt-test")
    assert not result.ok
    assert any("Run logs exist but run ledger is missing" in err for err in result.errors)
