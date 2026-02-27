from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ABSOLUTE_PATTERNS = [re.compile(r"/Users/"), re.compile(r"Box Sync")]
SECRET_PATTERNS = [re.compile(r"sk-proj-[A-Za-z0-9_-]{20,}")]


def tracked_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True
    )
    files = [root / x for x in result.stdout.splitlines() if x.strip()]
    return [p for p in files if p.exists()]


def test_no_absolute_local_paths_or_secrets_in_notebook_sources() -> None:
    root = Path(__file__).resolve().parents[1]
    notebooks = [p for p in tracked_files(root) if p.suffix.lower() == ".ipynb"]

    for nb_path in notebooks:
        nb = json.loads(nb_path.read_text(encoding="utf-8"))
        for cell in nb.get("cells", []):
            source = "".join(cell.get("source", []))
            for pattern in ABSOLUTE_PATTERNS + SECRET_PATTERNS:
                assert not pattern.search(source), (
                    f"{nb_path} contains `{pattern.pattern}` in source"
                )
            assert not cell.get("outputs"), f"{nb_path} contains retained outputs"


def test_no_absolute_local_paths_or_secrets_in_docs() -> None:
    root = Path(__file__).resolve().parents[1]
    doc_files = [
        p for p in tracked_files(root) if p.suffix.lower() in {".md", ".txt", ".yaml", ".yml"}
    ]

    for path in doc_files:
        content = path.read_text(encoding="utf-8")
        for pattern in ABSOLUTE_PATTERNS + SECRET_PATTERNS:
            assert not pattern.search(content), f"{path} contains `{pattern.pattern}`"
