from __future__ import annotations

import json
from pathlib import Path

import pytest

from dx_chat_entropy.paths import (
    find_repo_root,
    get_paths,
    is_review_bundle,
    require_bundle_capability,
)


def test_find_repo_root_has_pyproject() -> None:
    root = find_repo_root(Path(__file__).resolve())
    assert (root / "pyproject.toml").exists()


def test_get_paths_points_to_expected_dirs() -> None:
    paths = get_paths(Path(__file__).resolve())
    assert paths.data == paths.root / "data"
    assert paths.raw == paths.root / "data" / "raw"
    assert paths.processed == paths.root / "data" / "processed"


def test_find_repo_root_with_bundle_manifest_marker(tmp_path: Path) -> None:
    root = tmp_path / "bundle_root"
    (root / "nested" / "x").mkdir(parents=True)
    (root / "bundle_manifest.json").write_text(
        json.dumps({"bundle_type": "ovr_review_bundle"}),
        encoding="utf-8",
    )

    found = find_repo_root(root / "nested" / "x")
    assert found == root


def test_find_repo_root_with_layout_markers(tmp_path: Path) -> None:
    root = tmp_path / "layout_root"
    (root / "scripts").mkdir(parents=True)
    (root / "src").mkdir(parents=True)
    (root / "README.md").write_text("x", encoding="utf-8")
    (root / "scripts" / "tool.py").write_text("print('x')", encoding="utf-8")
    child = root / "src" / "pkg"
    child.mkdir(parents=True)

    found = find_repo_root(child)
    assert found == root


def test_require_bundle_capability_enforced_for_review_bundle(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "bundle_manifest.json").write_text(
        json.dumps(
            {
                "bundle_type": "ovr_review_bundle",
                "supported_commands": [
                    "python scripts/project_one_vs_rest_coherent_lrs.py --model-id gpt-test"
                ],
            }
        ),
        encoding="utf-8",
    )

    assert is_review_bundle(root)
    require_bundle_capability(root, "project_coherent")
    with pytest.raises(RuntimeError):
        require_bundle_capability(root, "build_inputs")
