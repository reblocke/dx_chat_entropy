from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import yaml


def find_repo_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise FileNotFoundError("Could not locate repository root (missing pyproject.toml).")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build normalized one-vs-rest input workbooks from raw LR matrices. "
            "Each schema-defining header row becomes a separate sheet."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/lr_differential_scenarios.yaml"),
        help="Scenario config YAML path (repo-relative or absolute).",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("data/processed/lr_one_vs_rest"),
        help="Output root for normalized inputs and manifests.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Optional explicit repo root. Defaults to auto-detection.",
    )
    return parser.parse_args()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _path_for_manifest(path: Path, *, repo_root: Path) -> str:
    try:
        return str(path.relative_to(repo_root))
    except ValueError:
        return str(path)


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root()

    config_path = args.config
    if not config_path.is_absolute():
        config_path = repo_root / config_path
    if not config_path.exists():
        raise FileNotFoundError(f"Config does not exist: {config_path}")

    output_root = args.output_root
    if not output_root.is_absolute():
        output_root = repo_root / output_root

    inputs_dir = output_root / "inputs"
    manifests_dir = output_root / "manifests"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    manifests_dir.mkdir(parents=True, exist_ok=True)

    allow_category_count_mismatch = os.getenv("ALLOW_CATEGORY_COUNT_MISMATCH", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    import sys

    src_path = repo_root / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))

    from dx_chat_entropy.lr_one_vs_rest_inputs import (
        build_one_vs_rest_sheet,
        discover_schema_rows,
        extract_findings,
        extract_schema_priors,
        sha256_file,
        sheet_name_for_schema,
    )

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    scenarios = raw.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError("Config must define a non-empty `scenarios` list.")

    manifest_rows: list[dict[str, object]] = []
    priors_rows: list[dict[str, object]] = []
    warnings: list[str] = []
    generated_files: dict[str, str] = {}
    source_files: dict[str, str] = {}

    for scenario in scenarios:
        scenario_id = str(scenario["scenario_id"])
        source_workbook_rel = Path(str(scenario["source_workbook"]))
        source_workbook = source_workbook_rel
        if not source_workbook.is_absolute():
            source_workbook = repo_root / source_workbook
        sheet_name = str(scenario["sheet_name"])
        key_feature_token = str(scenario.get("key_feature_token", r"^key feature"))
        expected_category_count = scenario.get("expected_category_count")

        if not source_workbook.exists():
            raise FileNotFoundError(f"Source workbook missing for {scenario_id}: {source_workbook}")
        source_files[_path_for_manifest(source_workbook, repo_root=repo_root)] = sha256_file(
            source_workbook
        )

        df_raw = pd.read_excel(source_workbook, sheet_name=sheet_name, header=None)

        key_feature_row_idx, schema_rows, scenario_warnings = discover_schema_rows(
            df_raw,
            key_feature_pattern=key_feature_token,
            expected_category_count=(
                int(expected_category_count) if expected_category_count is not None else None
            ),
            allow_category_count_mismatch=allow_category_count_mismatch,
        )
        findings = extract_findings(df_raw, key_feature_row_idx=key_feature_row_idx)

        normalized_abs = inputs_dir / f"{scenario_id}_inputs.xlsx"
        normalized_rel = _path_for_manifest(normalized_abs, repo_root=repo_root)

        with pd.ExcelWriter(normalized_abs, engine="openpyxl") as writer:
            for schema in schema_rows:
                sname = sheet_name_for_schema(
                    order=schema.order,
                    row_idx=schema.row_idx,
                    n_categories=len(schema.labels),
                )
                df_sheet = build_one_vs_rest_sheet(
                    categories=schema.labels,
                    findings=findings,
                )
                df_sheet.to_excel(writer, sheet_name=sname, index=False, header=False)

                warning = schema.warning or ""
                manifest_rows.append(
                    {
                        "scenario_id": scenario_id,
                        "source_workbook": str(source_workbook_rel),
                        "source_sheet": sheet_name,
                        "schema_order": schema.order,
                        "schema_row_idx": schema.row_idx,
                        "schema_sheet_name": sname,
                        "categories_count": len(schema.labels),
                        "findings_count": len(findings),
                        "normalized_input_workbook": normalized_rel,
                        "warnings": warning,
                    }
                )

                schema_priors = extract_schema_priors(
                    df_raw,
                    schema_row_idx=schema.row_idx,
                    key_feature_row_idx=key_feature_row_idx,
                )
                for order_idx, span in enumerate(schema_priors.spans, start=1):
                    priors_rows.append(
                        {
                            "scenario_id": scenario_id,
                            "source_workbook": str(source_workbook_rel),
                            "source_sheet": sheet_name,
                            "schema_order": schema.order,
                            "schema_row_idx": schema.row_idx,
                            "schema_sheet_name": sname,
                            "prior_row_idx": schema_priors.prior_row_idx,
                            "category_order": order_idx,
                            "category": span.label,
                            "prior_raw": schema_priors.priors_raw[order_idx - 1],
                            "prior_normalized": schema_priors.priors_normalized[order_idx - 1],
                            "prior_vector_sum_raw": schema_priors.prior_vector_sum_raw,
                        }
                    )

        generated_files[normalized_rel] = sha256_file(normalized_abs)

        for warning in scenario_warnings:
            warnings.append(f"scenario={scenario_id}: {warning}")

        print(
            f"Built {scenario_id}: schemas={len(schema_rows)} findings={len(findings)} "
            f"workbook={normalized_rel}"
        )

    manifest_df = pd.DataFrame(manifest_rows).sort_values(["scenario_id", "schema_order"])

    inputs_manifest_path = manifests_dir / "inputs_manifest.csv"
    schema_priors_path = manifests_dir / "schema_priors.csv"
    run_manifest_path = manifests_dir / "run_manifest.json"

    manifest_df.to_csv(inputs_manifest_path, index=False)
    priors_df = pd.DataFrame(priors_rows)
    if not priors_df.empty:
        priors_df = priors_df.sort_values(["scenario_id", "schema_order", "category_order"])
    else:
        priors_df = pd.DataFrame(
            columns=[
                "scenario_id",
                "source_workbook",
                "source_sheet",
                "schema_order",
                "schema_row_idx",
                "schema_sheet_name",
                "prior_row_idx",
                "category_order",
                "category",
                "prior_raw",
                "prior_normalized",
                "prior_vector_sum_raw",
            ]
        )
    priors_df.to_csv(schema_priors_path, index=False)

    config_text = config_path.read_text(encoding="utf-8")
    run_manifest = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "config_path": _path_for_manifest(config_path, repo_root=repo_root),
        "config_sha256": _sha256_text(config_text),
        "source_workbooks": source_files,
        "generated_input_workbooks": generated_files,
        "inputs_manifest": _path_for_manifest(inputs_manifest_path, repo_root=repo_root),
        "schema_priors_manifest": _path_for_manifest(schema_priors_path, repo_root=repo_root),
        "schema_row_count": int(len(manifest_df)),
        "scenario_count": int(manifest_df["scenario_id"].nunique()) if len(manifest_df) else 0,
        "warnings": warnings,
    }
    run_manifest_path.write_text(json.dumps(run_manifest, indent=2), encoding="utf-8")

    print(
        {
            "schema_rows": int(len(manifest_df)),
            "scenario_count": int(manifest_df["scenario_id"].nunique()) if len(manifest_df) else 0,
            "warnings": len(warnings),
            "inputs_manifest": str(inputs_manifest_path),
            "schema_priors": str(schema_priors_path),
            "run_manifest": str(run_manifest_path),
        }
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
