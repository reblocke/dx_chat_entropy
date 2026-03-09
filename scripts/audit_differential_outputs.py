from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def find_repo_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise FileNotFoundError("Could not locate repository root (missing pyproject.toml).")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit differential-LR outputs against manifest expectations. "
            "Writes workbook-level quality summary and row-level invalid details."
        )
    )
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--outputs-root", required=True, type=Path)
    parser.add_argument("--summary-out", required=True, type=Path)
    parser.add_argument("--invalid-out", required=True, type=Path)
    parser.add_argument(
        "--model-id",
        action="append",
        dest="model_ids",
        help="Optional model_id filter; may be passed multiple times.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Optional explicit repo root. Defaults to auto-detection via pyproject.toml.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root()

    manifest_path = (repo_root / args.manifest).resolve()
    outputs_root = (repo_root / args.outputs_root).resolve()
    summary_out = (repo_root / args.summary_out).resolve()
    invalid_out = (repo_root / args.invalid_out).resolve()

    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest does not exist: {manifest_path}")

    df_manifest = pd.read_csv(manifest_path)

    # Late import keeps CLI startup simple and avoids path issues before repo_root is known.
    import sys

    src_path = repo_root / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))

    from dx_chat_entropy.lr_differential_audit import audit_outputs

    summary_df, invalid_df = audit_outputs(
        df_manifest,
        repo_root=repo_root,
        outputs_root=outputs_root,
        model_ids=args.model_ids,
    )

    summary_out.parent.mkdir(parents=True, exist_ok=True)
    invalid_out.parent.mkdir(parents=True, exist_ok=True)
    summary_df.sort_values(["model_id", "scenario_id", "pair_index"]).to_csv(
        summary_out, index=False
    )

    if invalid_df.empty:
        pd.DataFrame(
            columns=[
                "model_id",
                "scenario_id",
                "pair_index",
                "input_workbook",
                "output_workbook",
                "row_index",
                "finding",
                "status",
                "raw_value",
            ]
        ).to_csv(invalid_out, index=False)
    else:
        invalid_df.to_csv(invalid_out, index=False)

    workbook_count = len(summary_df)
    expected_total = int(summary_df["expected_findings"].sum())
    valid_total = int(summary_df["valid_positive_lrs"].sum())
    invalid_total = int(summary_df["total_invalid_rows"].sum())
    failed_workbooks = int((~summary_df["passes"]).sum())

    print(
        {
            "workbook_rows": workbook_count,
            "expected_findings": expected_total,
            "valid_positive_lrs": valid_total,
            "invalid_rows": invalid_total,
            "failed_workbooks": failed_workbooks,
            "summary_out": str(summary_out),
            "invalid_out": str(invalid_out),
        }
    )

    return 0 if invalid_total == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
