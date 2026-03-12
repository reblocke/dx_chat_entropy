from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create a one-vs-rest review bundle with explicit bundle contract, "
            "run checker, and zip only if validation passes."
        )
    )
    parser.add_argument("--model-id", required=True, type=str)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/packages"),
        help="Directory where staged folder + zip are created.",
    )
    parser.add_argument(
        "--bundle-version",
        type=str,
        default="1.0.0",
        help="Semantic bundle contract version string.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Optional explicit repo root. Defaults to auto-detection.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow replacing an existing staged folder/zip with same timestamped name.",
    )
    return parser.parse_args()


def _resolve_repo_root(repo_root_arg: Path | None) -> Path:
    script_root = Path(__file__).resolve().parents[1]
    src_path = script_root / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))

    from dx_chat_entropy.paths import find_repo_root

    if repo_root_arg is not None:
        return find_repo_root(repo_root_arg.resolve())
    return find_repo_root(Path.cwd())


def _copy_file(repo_root: Path, stage_root: Path, rel_path: str) -> None:
    src = repo_root / rel_path
    if not src.exists():
        raise FileNotFoundError(f"Required file missing for bundle: {src}")
    dst = stage_root / rel_path
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _copy_dir(repo_root: Path, stage_root: Path, rel_path: str) -> None:
    src = repo_root / rel_path
    if not src.exists():
        raise FileNotFoundError(f"Required directory missing for bundle: {src}")
    dst = stage_root / rel_path
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def _write_bundle_readme(stage_root: Path, model_id: str) -> None:
    readme = f"""# One-vs-Rest Review Bundle

This package is an **OVR review bundle** (not a full repository snapshot).

## Supported Commands
- `python scripts/project_one_vs_rest_coherent_lrs.py --model-id {model_id}`
- `python scripts/audit_one_vs_rest_outputs.py --model-id {model_id} --coherence-mode`
- `python scripts/check_one_vs_rest_bundle.py --bundle-root . --model-id {model_id}`

## Unsupported Commands In This Bundle
- `python scripts/build_one_vs_rest_inputs.py`
- `python scripts/run_one_vs_rest_batch.py --model-id {model_id}`

Why unsupported:
- raw LR source matrices are intentionally omitted from review bundles
- this bundle is intended for inspection/projection/audit of already-generated outputs

## Included Paths
- `bundle_manifest.json`
- `scripts/`
- `src/dx_chat_entropy/`
- `notebooks/30_one_vs_rest_estimate_lrs.ipynb`
- `notebooks/31_one_vs_rest_compare_lr_estimates.ipynb`
- `notebooks/32_one_vs_rest_project_coherent_lrs.ipynb`
- `data/processed/lr_one_vs_rest/inputs/`
- `data/processed/lr_one_vs_rest/outputs_by_model/{model_id}/`
- `data/processed/lr_one_vs_rest/coherent_outputs_by_model/{model_id}/`
- `data/processed/lr_one_vs_rest/manifests/`

## Omitted Paths
- `data/raw/lr_matrices/`
- full dependency lock/runtime files for end-to-end rebuilding from raw
"""
    (stage_root / "README.md").write_text(readme, encoding="utf-8")


def _write_bundle_manifest(
    stage_root: Path,
    *,
    model_id: str,
    bundle_version: str,
    created_at_utc: str,
) -> None:
    payload = {
        "bundle_type": "ovr_review_bundle",
        "bundle_version": bundle_version,
        "pipeline": "lr_one_vs_rest",
        "created_at_utc": created_at_utc,
        "model_ids": [model_id],
        "capabilities": [
            "inspect_outputs",
            "project_coherent",
            "audit_outputs",
            "validate_bundle",
        ],
        "supported_commands": [
            f"python scripts/project_one_vs_rest_coherent_lrs.py --model-id {model_id}",
            (f"python scripts/audit_one_vs_rest_outputs.py --model-id {model_id} --coherence-mode"),
            f"python scripts/check_one_vs_rest_bundle.py --bundle-root . --model-id {model_id}",
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
            "notebooks/30_one_vs_rest_estimate_lrs.ipynb",
            "notebooks/31_one_vs_rest_compare_lr_estimates.ipynb",
            "notebooks/32_one_vs_rest_project_coherent_lrs.ipynb",
            "data/processed/lr_one_vs_rest/inputs",
            f"data/processed/lr_one_vs_rest/outputs_by_model/{model_id}",
            f"data/processed/lr_one_vs_rest/coherent_outputs_by_model/{model_id}",
            "data/processed/lr_one_vs_rest/manifests",
            "config/lr_differential_scenarios.yaml",
        ],
        "omitted_paths": [
            "data/raw/lr_matrices",
            "archive",
            "pyproject.toml",
            "uv.lock",
        ],
        "notes": (
            "This is a review bundle intended for inspecting existing OVR outputs, "
            "coherence projection, and audit. It is not a full rerunnable repo snapshot."
        ),
    }
    (stage_root / "bundle_manifest.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    repo_root = _resolve_repo_root(args.repo_root)

    created_at_utc = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    model_token = args.model_id.replace("/", "_")
    bundle_name = f"ovr_review_bundle_{model_token}_{created_at_utc}"

    output_dir = args.output_dir if args.output_dir.is_absolute() else repo_root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    stage_root = output_dir / bundle_name
    zip_path = output_dir / f"{bundle_name}.zip"

    if stage_root.exists() and not args.overwrite:
        raise FileExistsError(f"Staged bundle path already exists: {stage_root}")
    if zip_path.exists() and not args.overwrite:
        raise FileExistsError(f"Bundle zip already exists: {zip_path}")

    if stage_root.exists():
        shutil.rmtree(stage_root)
    if zip_path.exists():
        zip_path.unlink()

    # Core scripts required for review-bundle runtime and checking.
    script_files = [
        "scripts/project_one_vs_rest_coherent_lrs.py",
        "scripts/audit_one_vs_rest_outputs.py",
        "scripts/build_one_vs_rest_inputs.py",
        "scripts/check_one_vs_rest_bundle.py",
    ]
    for rel in script_files:
        _copy_file(repo_root, stage_root, rel)

    # src modules required by bundled scripts.
    src_files = [
        "src/dx_chat_entropy/__init__.py",
        "src/dx_chat_entropy/paths.py",
        "src/dx_chat_entropy/lr_differential_inputs.py",
        "src/dx_chat_entropy/lr_one_vs_rest_inputs.py",
        "src/dx_chat_entropy/lr_one_vs_rest_coherence.py",
        "src/dx_chat_entropy/lr_one_vs_rest_audit.py",
        "src/dx_chat_entropy/lr_one_vs_rest_bundle.py",
    ]
    for rel in src_files:
        _copy_file(repo_root, stage_root, rel)

    # Notebook references documented for this review profile.
    notebook_files = [
        "notebooks/30_one_vs_rest_estimate_lrs.ipynb",
        "notebooks/31_one_vs_rest_compare_lr_estimates.ipynb",
        "notebooks/32_one_vs_rest_project_coherent_lrs.ipynb",
    ]
    for rel in notebook_files:
        _copy_file(repo_root, stage_root, rel)

    _copy_file(repo_root, stage_root, "config/lr_differential_scenarios.yaml")

    # Normalized one-vs-rest inputs (required by audit expectations).
    _copy_dir(
        repo_root,
        stage_root,
        "data/processed/lr_one_vs_rest/inputs",
    )

    # Model outputs.
    _copy_dir(
        repo_root,
        stage_root,
        f"data/processed/lr_one_vs_rest/outputs_by_model/{args.model_id}",
    )
    _copy_dir(
        repo_root,
        stage_root,
        f"data/processed/lr_one_vs_rest/coherent_outputs_by_model/{args.model_id}",
    )

    # Required manifests.
    manifest_files = [
        "data/processed/lr_one_vs_rest/manifests/inputs_manifest.csv",
        "data/processed/lr_one_vs_rest/manifests/schema_priors.csv",
        "data/processed/lr_one_vs_rest/manifests/run_manifest.json",
        f"data/processed/lr_one_vs_rest/manifests/quality_summary_{args.model_id}.csv",
        f"data/processed/lr_one_vs_rest/manifests/invalid_cells_{args.model_id}.csv",
        f"data/processed/lr_one_vs_rest/manifests/coherent_quality_summary_{args.model_id}.csv",
        f"data/processed/lr_one_vs_rest/manifests/coherent_invalid_cells_{args.model_id}.csv",
        f"data/processed/lr_one_vs_rest/manifests/coherence_quality_summary_{args.model_id}.csv",
        f"data/processed/lr_one_vs_rest/manifests/coherence_invalid_rows_{args.model_id}.csv",
        f"data/processed/lr_one_vs_rest/manifests/coherence_projection_summary_{args.model_id}.csv",
        f"data/processed/lr_one_vs_rest/manifests/coherence_projection_top_rows_{args.model_id}.csv",
        f"data/processed/lr_one_vs_rest/manifests/coherence_projection_failures_{args.model_id}.csv",
    ]
    for rel in manifest_files:
        _copy_file(repo_root, stage_root, rel)

    _write_bundle_readme(stage_root, args.model_id)
    _write_bundle_manifest(
        stage_root,
        model_id=args.model_id,
        bundle_version=args.bundle_version,
        created_at_utc=datetime.now(UTC).isoformat(),
    )

    checker_cmd = [
        sys.executable,
        str(stage_root / "scripts" / "check_one_vs_rest_bundle.py"),
        "--bundle-root",
        str(stage_root),
        "--model-id",
        args.model_id,
        "--repo-root",
        str(stage_root),
    ]
    subprocess.run(checker_cmd, check=True, cwd=stage_root)

    shutil.make_archive(
        str(zip_path.with_suffix("")),
        "zip",
        root_dir=output_dir,
        base_dir=bundle_name,
    )

    print(
        {
            "bundle_root": str(stage_root),
            "zip_path": str(zip_path),
            "model_id": args.model_id,
            "bundle_version": args.bundle_version,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
