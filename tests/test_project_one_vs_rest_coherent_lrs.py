from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


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
        "--allow-partial-write",
        "--coherent-outputs-root",
        str(tmp_path / "coherent"),
    ]
    proc = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "[partial-write-warning]" in (proc.stdout + proc.stderr)
