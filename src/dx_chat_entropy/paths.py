from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BUNDLE_MANIFEST_NAME = "bundle_manifest.json"


def _looks_like_repo_layout(candidate: Path) -> bool:
    return (
        (candidate / "README.md").exists()
        and (candidate / "scripts").is_dir()
        and (candidate / "src").is_dir()
    )


def _bundle_manifest_path(root: Path) -> Path:
    return root / BUNDLE_MANIFEST_NAME


def find_repo_root(start: Path | None = None) -> Path:
    """Find repo/bundle root by scanning upward for known structural markers."""

    start = (start or Path.cwd()).resolve()
    for candidate in [start, *start.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
        if _bundle_manifest_path(candidate).exists():
            return candidate
        if _looks_like_repo_layout(candidate):
            return candidate
    raise FileNotFoundError(
        f"Could not locate repo/bundle root from {start}. "
        "Expected one of: pyproject.toml, bundle_manifest.json, or "
        "README.md + scripts/ + src/."
    )


def load_bundle_manifest(root: Path) -> dict[str, Any] | None:
    manifest_path = _bundle_manifest_path(root)
    if not manifest_path.exists():
        return None
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid {BUNDLE_MANIFEST_NAME}: expected top-level object.")
    return payload


def is_review_bundle(root: Path) -> bool:
    payload = load_bundle_manifest(root)
    if payload is None:
        return False
    bundle_type = payload.get("bundle_type")
    return isinstance(bundle_type, str) and bundle_type.endswith("_review_bundle")


def _supported_capabilities_from_manifest(payload: dict[str, Any]) -> set[str]:
    explicit = payload.get("capabilities")
    if isinstance(explicit, list):
        return {str(item) for item in explicit}

    inferred: set[str] = set()
    commands = payload.get("supported_commands")
    if isinstance(commands, list):
        for command in commands:
            text = str(command)
            if "build_one_vs_rest_inputs.py" in text:
                inferred.add("build_inputs")
            if "project_one_vs_rest_coherent_lrs.py" in text:
                inferred.add("project_coherent")
            if "audit_one_vs_rest_outputs.py" in text:
                inferred.add("audit_outputs")
            if "run_one_vs_rest_batch.py" in text:
                inferred.add("estimate_raw_outputs")
    return inferred


def require_bundle_capability(root: Path, capability: str) -> None:
    """Enforce capability contracts only when running inside review bundles."""

    payload = load_bundle_manifest(root)
    if payload is None:
        return

    if not is_review_bundle(root):
        return

    supported = _supported_capabilities_from_manifest(payload)
    if capability in supported:
        return

    bundle_type = str(payload.get("bundle_type", "review_bundle"))
    raise RuntimeError(
        f"Capability '{capability}' is not available in this {bundle_type}. "
        f"Supported capabilities: {sorted(supported)}."
    )


@dataclass(frozen=True)
class ProjectPaths:
    root: Path

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def raw(self) -> Path:
        return self.data / "raw"

    @property
    def external(self) -> Path:
        return self.data / "external"

    @property
    def processed(self) -> Path:
        return self.data / "processed"

    @property
    def derived(self) -> Path:
        return self.data / "derived"

    @property
    def artifacts(self) -> Path:
        return self.root / "artifacts"

    @property
    def reports(self) -> Path:
        return self.root / "reports"

    @property
    def notebooks(self) -> Path:
        return self.root / "notebooks"

    @property
    def archive(self) -> Path:
        return self.root / "archive"


def get_paths(start: Path | None = None) -> ProjectPaths:
    return ProjectPaths(root=find_repo_root(start=start))
