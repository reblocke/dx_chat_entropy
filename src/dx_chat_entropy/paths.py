from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def find_repo_root(start: Path | None = None) -> Path:
    """Find repository root by searching upward for `pyproject.toml`."""

    start = (start or Path.cwd()).resolve()
    for candidate in [start, *start.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise FileNotFoundError(
        f"Could not find repo root from {start}. Expected pyproject.toml in an ancestor."
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
