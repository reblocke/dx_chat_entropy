from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path


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


def _notebook_imports(nb_path: Path) -> set[str]:
    nb = json.loads(nb_path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        source = "".join(cell.get("source", []))
        imported.update(_python_imports(source))
    return imported


def _python_file_imports(py_path: Path) -> set[str]:
    return _python_imports(py_path.read_text(encoding="utf-8"))


def discover_local_imports(bundle_root: Path) -> set[str]:
    code_root = bundle_root / "code"
    imported: set[str] = set()

    for nb_path in sorted((code_root / "notebooks").glob("*.ipynb")):
        imported.update(_notebook_imports(nb_path))
    for py_path in sorted((code_root / "scripts").glob("*.py")):
        imported.update(_python_file_imports(py_path))

    return {
        name
        for name in imported
        if name == "dx_chat_entropy" or name.startswith("dx_chat_entropy.")
    }


def _module_candidates(module_name: str) -> list[Path]:
    parts = module_name.split(".")
    if parts == ["dx_chat_entropy"]:
        return [Path("dx_chat_entropy/__init__.py")]

    subparts = parts[1:]
    return [
        Path("dx_chat_entropy") / Path(*subparts).with_suffix(".py"),
        Path("dx_chat_entropy") / Path(*subparts) / "__init__.py",
    ]


def missing_local_modules(bundle_root: Path, module_names: set[str]) -> list[str]:
    src_root = bundle_root / "code" / "src"
    missing: list[str] = []
    for module_name in sorted(module_names):
        candidates = _module_candidates(module_name)
        if not any((src_root / candidate).exists() for candidate in candidates):
            missing.append(module_name)
    return missing


@dataclass(frozen=True)
class BundleValidationResult:
    errors: list[str]
    warnings: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_bundle(*, bundle_root: Path, model_id: str) -> BundleValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    required_paths = [
        bundle_root / "pyproject.toml",
        bundle_root / "uv.lock",
        bundle_root / "code" / "src" / "dx_chat_entropy" / "__init__.py",
        bundle_root / "code" / "src" / "dx_chat_entropy" / "paths.py",
        bundle_root / "code" / "config" / "lr_differential_scenarios.yaml",
    ]
    for path in required_paths:
        if not path.exists():
            errors.append(f"Missing required file: {path}")

    imported_local_modules = discover_local_imports(bundle_root)
    missing_modules = missing_local_modules(bundle_root, imported_local_modules)
    for module_name in missing_modules:
        errors.append(f"Imported local module missing from bundle: {module_name}")

    manifests_dir = bundle_root / "data" / "processed" / "lr_differential" / "manifests"
    if manifests_dir.exists():
        stale_missing = sorted(manifests_dir.glob("pairs_manifest_missing*.csv"))
        if stale_missing:
            errors.append(
                "Stale missing-output manifests must not be shipped: "
                + ", ".join(str(path) for path in stale_missing)
            )

        model_invalid = manifests_dir / f"invalid_rows_{model_id}.csv"
        generic_invalid = manifests_dir / "invalid_rows.csv"
        if not model_invalid.exists() and not generic_invalid.exists():
            errors.append(
                "Repair target file missing: expected invalid_rows.csv or "
                f"invalid_rows_{model_id}.csv in manifests."
            )

        model_logs = manifests_dir / "logs" / model_id
        model_ledger = manifests_dir / f"run_ledger_differential_{model_id}.csv"
        if model_logs.exists():
            log_count = len(list(model_logs.glob("*.log")))
            if log_count > 0 and not model_ledger.exists():
                errors.append(
                    f"Run logs exist but run ledger is missing: {model_logs} vs {model_ledger}"
                )
            elif log_count == 0:
                warnings.append(f"Model log directory exists with no log files: {model_logs}")

    return BundleValidationResult(errors=errors, warnings=warnings)
