from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

REQUIRED_BUNDLE_FIELDS = {
    "bundle_type",
    "bundle_version",
    "pipeline",
    "created_at_utc",
    "model_ids",
    "supported_commands",
    "unsupported_commands",
    "included_paths",
    "omitted_paths",
    "notes",
}


def _python_imports(source: str) -> set[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def _python_file_imports(py_path: Path) -> set[str]:
    return _python_imports(py_path.read_text(encoding="utf-8"))


def _notebook_imports(nb_path: Path) -> set[str]:
    payload = json.loads(nb_path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for cell in payload.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        source = "".join(cell.get("source", []))
        imported.update(_python_imports(source))
    return imported


def _module_candidates(module_name: str) -> list[Path]:
    parts = module_name.split(".")
    if parts == ["dx_chat_entropy"]:
        return [Path("dx_chat_entropy/__init__.py")]

    subparts = parts[1:]
    return [
        Path("dx_chat_entropy") / Path(*subparts).with_suffix(".py"),
        Path("dx_chat_entropy") / Path(*subparts) / "__init__.py",
    ]


def _read_bundle_manifest(bundle_root: Path) -> dict[str, Any]:
    manifest_path = bundle_root / "bundle_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing bundle manifest: {manifest_path}")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("bundle_manifest.json must contain a top-level object.")
    return payload


def _extract_command_script_paths(command: str) -> list[Path]:
    matches = re.findall(r"(scripts/[A-Za-z0-9_.-]+\.py)", command)
    return [Path(item) for item in matches]


def _readme_referenced_file_paths(readme_path: Path) -> set[Path]:
    text = readme_path.read_text(encoding="utf-8")
    # Match common relative file references written in inline code.
    matches = re.findall(
        r"`([A-Za-z0-9_./-]+\.(?:ipynb|py|csv|json|xlsx|yaml|yml|md))`",
        text,
    )
    refs: set[Path] = set()
    for item in matches:
        if item.startswith("http://") or item.startswith("https://"):
            continue
        refs.add(Path(item))
    return refs


@dataclass(frozen=True)
class BundleValidationResult:
    errors: list[str]
    warnings: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_bundle(*, bundle_root: Path, model_id: str | None = None) -> BundleValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    try:
        manifest = _read_bundle_manifest(bundle_root)
    except Exception as exc:
        return BundleValidationResult(errors=[str(exc)], warnings=[])

    missing_manifest_fields = sorted(REQUIRED_BUNDLE_FIELDS - set(manifest.keys()))
    if missing_manifest_fields:
        errors.append(f"bundle_manifest.json missing required fields: {missing_manifest_fields}")

    bundle_type = manifest.get("bundle_type")
    if bundle_type != "ovr_review_bundle":
        errors.append(f"Unexpected bundle_type={bundle_type!r}; expected 'ovr_review_bundle'.")

    pipeline = manifest.get("pipeline")
    if pipeline != "lr_one_vs_rest":
        errors.append(f"Unexpected pipeline={pipeline!r}; expected 'lr_one_vs_rest'.")

    # Required files for review-bundle profile.
    required_paths = [
        bundle_root / "README.md",
        bundle_root / "bundle_manifest.json",
        bundle_root / "scripts" / "project_one_vs_rest_coherent_lrs.py",
        bundle_root / "scripts" / "audit_one_vs_rest_outputs.py",
        bundle_root / "scripts" / "build_one_vs_rest_inputs.py",
        bundle_root / "src" / "dx_chat_entropy" / "__init__.py",
        bundle_root / "src" / "dx_chat_entropy" / "paths.py",
        bundle_root / "src" / "dx_chat_entropy" / "lr_one_vs_rest_audit.py",
        bundle_root / "data" / "processed" / "lr_one_vs_rest" / "manifests" / "inputs_manifest.csv",
        bundle_root / "data" / "processed" / "lr_one_vs_rest" / "manifests" / "schema_priors.csv",
        bundle_root / "data" / "processed" / "lr_one_vs_rest" / "manifests" / "run_manifest.json",
    ]
    for path in required_paths:
        if not path.exists():
            errors.append(f"Missing required file: {path}")

    # Ensure declared included paths exist.
    included_paths = manifest.get("included_paths", [])
    if isinstance(included_paths, list):
        for rel in included_paths:
            rel_path = Path(str(rel))
            if not (bundle_root / rel_path).exists():
                errors.append(f"bundle_manifest included_paths entry missing on disk: {rel_path}")
    else:
        errors.append("bundle_manifest field `included_paths` must be a list.")

    # Validate supported command scripts exist and gather imports from those scripts.
    supported_commands = manifest.get("supported_commands", [])
    if not isinstance(supported_commands, list):
        errors.append("bundle_manifest field `supported_commands` must be a list.")
        supported_commands = []

    supported_scripts: set[Path] = set()
    for command in supported_commands:
        for rel_script in _extract_command_script_paths(str(command)):
            script_path = bundle_root / rel_script
            if not script_path.exists():
                errors.append(
                    f"Supported command references missing script: {rel_script} ({command})"
                )
            else:
                supported_scripts.add(script_path)

    # Import resolution for shipped scripts and supported command scripts.
    import_targets: set[Path] = set(bundle_root.glob("scripts/*.py"))
    import_targets.update(supported_scripts)
    imported_local_modules: set[str] = set()
    for path in sorted(import_targets):
        imported_local_modules.update(_python_file_imports(path))

    # README file references must exist.
    readme_path = bundle_root / "README.md"
    if readme_path.exists():
        for rel_path in sorted(_readme_referenced_file_paths(readme_path)):
            if not (bundle_root / rel_path).exists():
                errors.append(f"README references missing file: {rel_path}")

    # Notebook references in README must exist.
    if readme_path.exists():
        text = readme_path.read_text(encoding="utf-8")
        notebook_refs = set(re.findall(r"([A-Za-z0-9_./-]+\.ipynb)", text))
        for rel in sorted(notebook_refs):
            rel_path = Path(rel)
            if not (bundle_root / rel_path).exists():
                errors.append(f"README references missing notebook: {rel_path}")
            else:
                imported_local_modules.update(_notebook_imports(bundle_root / rel_path))

    imported_local_modules = {
        name
        for name in imported_local_modules
        if name == "dx_chat_entropy" or name.startswith("dx_chat_entropy.")
    }

    src_root = bundle_root / "src"
    for module_name in sorted(imported_local_modules):
        if not any(
            (src_root / candidate).exists() for candidate in _module_candidates(module_name)
        ):
            errors.append(f"Imported local module missing from bundle src/: {module_name}")

    # Coherent outputs require schema priors.
    coherent_root = (
        bundle_root / "data" / "processed" / "lr_one_vs_rest" / "coherent_outputs_by_model"
    )
    priors_manifest = (
        bundle_root / "data" / "processed" / "lr_one_vs_rest" / "manifests" / "schema_priors.csv"
    )
    if (
        coherent_root.exists()
        and any(coherent_root.rglob("*.xlsx"))
        and not priors_manifest.exists()
    ):
        errors.append(
            "Coherent outputs are present but schema_priors.csv is missing from bundle manifests."
        )

    # If model_id is provided, ensure model-specific coherent/raw roots exist.
    if model_id:
        raw_model_root = (
            bundle_root / "data" / "processed" / "lr_one_vs_rest" / "outputs_by_model" / model_id
        )
        coherent_model_root = (
            bundle_root
            / "data"
            / "processed"
            / "lr_one_vs_rest"
            / "coherent_outputs_by_model"
            / model_id
        )
        if not raw_model_root.exists():
            errors.append(f"Missing model raw output root: {raw_model_root}")
        if not coherent_model_root.exists():
            errors.append(f"Missing model coherent output root: {coherent_model_root}")

    # Inputs manifest should reference normalized input workbooks that are present.
    inputs_manifest = (
        bundle_root / "data" / "processed" / "lr_one_vs_rest" / "manifests" / "inputs_manifest.csv"
    )
    if inputs_manifest.exists():
        try:
            df_inputs = pd.read_csv(inputs_manifest)
        except Exception as exc:
            errors.append(f"Unable to read inputs_manifest.csv: {exc}")
        else:
            if "normalized_input_workbook" not in df_inputs.columns:
                errors.append(
                    "inputs_manifest.csv missing required column `normalized_input_workbook`."
                )
            else:
                for rel in sorted(
                    df_inputs["normalized_input_workbook"].dropna().astype(str).unique()
                ):
                    rel_path = Path(rel)
                    if not (bundle_root / rel_path).exists():
                        errors.append(
                            "inputs_manifest references missing normalized input workbook: "
                            f"{rel_path}"
                        )

    return BundleValidationResult(errors=errors, warnings=warnings)
