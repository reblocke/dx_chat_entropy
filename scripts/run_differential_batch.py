from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv


def find_repo_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise FileNotFoundError("Could not locate repository root (missing pyproject.toml).")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Script-first differential LR runner. "
            "Uses environment variable configuration shared with "
            "21_differential_estimate_lrs.ipynb."
        )
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Optional explicit repo root. Defaults to auto-detection.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root()

    import sys

    src_path = repo_root / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))

    from dx_chat_entropy.lr_differential_runner import build_runtime_config, run_differential
    from dx_chat_entropy.paths import get_paths

    load_dotenv()

    paths = get_paths(repo_root)
    config = build_runtime_config(
        repo_root=repo_root,
        paths=paths,
        environ=os.environ,
    )
    run_differential(config=config, repo_root=repo_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
