from __future__ import annotations

from pathlib import Path

from dx_chat_entropy.paths import find_repo_root, get_paths


def test_find_repo_root_has_pyproject() -> None:
    root = find_repo_root(Path(__file__).resolve())
    assert (root / "pyproject.toml").exists()


def test_get_paths_points_to_expected_dirs() -> None:
    paths = get_paths(Path(__file__).resolve())
    assert paths.data == paths.root / "data"
    assert paths.raw == paths.root / "data" / "raw"
    assert paths.processed == paths.root / "data" / "processed"
