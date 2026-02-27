from __future__ import annotations

import ast
import json
import re
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_DIR = REPO_ROOT / "notebooks"
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"

IMPORT_TO_PACKAGE = {
    "IPython": "ipython",
    "anthropic": "anthropic",
    "arviz": "arviz",
    "bambi": "bambi",
    "bs4": "beautifulsoup4",
    "dotenv": "python-dotenv",
    "huggingface_hub": "huggingface-hub",
    "ipywidgets": "ipywidgets",
    "llm": "llm",
    "markitdown": "markitdown",
    "matplotlib": "matplotlib",
    "mostlyai": "mostlyai",
    "numpy": "numpy",
    "openai": "openai",
    "pandas": "pandas",
    "peft": "peft",
    "pingouin": "pingouin",
    "pydantic": "pydantic",
    "pypdf": "pypdf",
    "pystata": "pystata",
    "requests": "requests",
    "safetensors": "safetensors",
    "scienceplots": "scienceplots",
    "scipy": "scipy",
    "sentence_transformers": "sentence-transformers",
    "skimpy": "skimpy",
    "srsly": "srsly",
    "statadict": "statadict",
    "statsmodels": "statsmodels",
    "tabulate": "tabulate",
    "tiktoken": "tiktoken",
    "torch": "torch",
    "transformers": "transformers",
}

LOCAL_MODULES = {"dx_chat_entropy"}
STDLIB_MODULES = set(sys.stdlib_module_names) | {"__future__"}
REQUIREMENT_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+")


def _requirement_name(requirement: str) -> str:
    match = REQUIREMENT_NAME_RE.match(requirement.strip())
    assert match, f"Unable to parse requirement name from: {requirement}"
    return match.group(0).lower().replace("_", "-")


def _notebook_imports(nb_path: Path) -> set[str]:
    nb = json.loads(nb_path.read_text(encoding="utf-8"))
    imported: set[str] = set()

    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        source = "".join(cell.get("source", []))
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])

    return {
        module
        for module in imported
        if module not in STDLIB_MODULES and module not in LOCAL_MODULES
    }


def _declared_runtime_packages() -> tuple[set[str], set[str]]:
    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    project_deps = {
        _requirement_name(requirement)
        for requirement in pyproject.get("project", {}).get("dependencies", [])
    }
    notebook_deps = {
        _requirement_name(requirement)
        for requirement in pyproject.get("dependency-groups", {}).get("notebooks", [])
    }
    return project_deps | notebook_deps, notebook_deps


def test_notebook_dependency_group_exists() -> None:
    _all_runtime, notebook_deps = _declared_runtime_packages()
    assert notebook_deps, "Expected a `dependency-groups.notebooks` section in pyproject.toml"


def test_notebook_imports_are_declared() -> None:
    runtime_packages, _notebook_deps = _declared_runtime_packages()
    notebook_paths = sorted(NOTEBOOK_DIR.glob("*.ipynb"))
    imports = set().union(*(_notebook_imports(path) for path in notebook_paths))

    unknown_imports = sorted(module for module in imports if module not in IMPORT_TO_PACKAGE)
    assert not unknown_imports, (
        "Notebook imports missing package mapping in test_notebook_dependencies.py: "
        f"{unknown_imports}"
    )

    required_packages = {IMPORT_TO_PACKAGE[module] for module in imports}
    missing_packages = sorted(
        package for package in required_packages if package not in runtime_packages
    )
    assert not missing_packages, (
        "Notebook imports not declared in pyproject runtime+notebooks dependencies: "
        f"{missing_packages}"
    )


def test_notebook_io_engine_dependencies_are_declared() -> None:
    runtime_packages, _notebook_deps = _declared_runtime_packages()
    notebook_text = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(NOTEBOOK_DIR.glob("*.ipynb"))
    )

    if "read_excel(" in notebook_text or ".to_excel(" in notebook_text:
        assert "openpyxl" in runtime_packages
    if "read_parquet(" in notebook_text or ".to_parquet(" in notebook_text:
        assert "pyarrow" in runtime_packages
