from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ABSOLUTE_PATTERNS = [re.compile(r"/Users/"), re.compile(r"Box Sync")]
SECRET_PATTERNS = [re.compile(r"sk-proj-[A-Za-z0-9_-]{20,}")]
STALE_TEXT_PATTERNS = [
    re.compile(r"github\.com/<org>/dx_chat_entropy"),
    re.compile(r"LLM and Repository Readiness Notes"),
    re.compile(r"No publication DOI is assigned to this repository"),
    re.compile(r"Repository license status: MIT"),
    re.compile(r"\b(accepted|published)\s+(in|by|at)\s+Scientific Reports\b", re.I),
]
FORBIDDEN_TRACKED_PARTS = [
    ".DS_Store",
    "src/dx_chat_entropy.egg-info/",
    "archive/legacy_external/",
    "archive/local_state/",
    "notebooks/data/",
    "notebooks/new-dataset.jsonl",
    "docs/references/ChatBot Team Members & Roles.md",
]
FORBIDDEN_REFERENCE_SUFFIXES = {".pdf", ".doc", ".docx", ".ppt", ".pptx"}


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
        p
        for p in tracked_files(root)
        if p.suffix.lower() in {".md", ".txt", ".yaml", ".yml", ".cff"}
    ]

    for path in doc_files:
        content = path.read_text(encoding="utf-8")
        for pattern in ABSOLUTE_PATTERNS + SECRET_PATTERNS + STALE_TEXT_PATTERNS:
            assert not pattern.search(content), f"{path} contains `{pattern.pattern}`"


def test_no_forbidden_tracked_public_artifacts() -> None:
    root = Path(__file__).resolve().parents[1]

    for path in tracked_files(root):
        relative = path.relative_to(root).as_posix()
        for forbidden in FORBIDDEN_TRACKED_PARTS:
            assert not (relative == forbidden.rstrip("/") or relative.startswith(forbidden)), (
                f"{relative} is a forbidden tracked artifact"
            )
        assert not (
            relative.startswith("docs/references/")
            and path.suffix.lower() in FORBIDDEN_REFERENCE_SUFFIXES
        ), f"{relative} should be cited or stored privately"
