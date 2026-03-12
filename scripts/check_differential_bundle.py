from __future__ import annotations

import argparse
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate structural completeness/consistency of a staged differential review bundle."
        )
    )
    parser.add_argument("--bundle-root", required=True, type=Path)
    parser.add_argument("--model-id", required=True, type=str)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Optional explicit repo root for import resolution. Defaults to auto from CWD.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    bundle_root = args.bundle_root.resolve()
    repo_root = args.repo_root.resolve() if args.repo_root else Path.cwd().resolve()

    import sys

    src_path = repo_root / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))

    from dx_chat_entropy.lr_differential_bundle import validate_bundle

    result = validate_bundle(bundle_root=bundle_root, model_id=args.model_id)
    if result.warnings:
        for warning in result.warnings:
            print(f"[bundle-warning] {warning}")
    if result.errors:
        for error in result.errors:
            print(f"[bundle-error] {error}")
        return 1

    print({"bundle_root": str(bundle_root), "model_id": args.model_id, "status": "ok"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
