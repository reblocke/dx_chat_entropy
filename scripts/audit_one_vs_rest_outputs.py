from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
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
            "Audit one-vs-rest outputs against normalized input manifest. "
            "Writes schema-sheet quality summary and invalid-cell details."
        )
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/processed/lr_one_vs_rest/manifests/inputs_manifest.csv"),
    )
    parser.add_argument(
        "--outputs-root",
        type=Path,
        default=Path("data/processed/lr_one_vs_rest/outputs_by_model"),
    )
    parser.add_argument(
        "--output-filename-suffix",
        type=str,
        default=None,
        help=(
            "Workbook filename suffix under outputs root. "
            "Defaults to `_filled.xlsx`, or `_coherent.xlsx` in coherence mode."
        ),
    )
    parser.add_argument(
        "--summary-out",
        type=Path,
        default=Path("data/processed/lr_one_vs_rest/manifests/quality_summary.csv"),
    )
    parser.add_argument(
        "--invalid-out",
        type=Path,
        default=Path("data/processed/lr_one_vs_rest/manifests/invalid_cells.csv"),
    )
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
    parser.add_argument(
        "--coherence-mode",
        action="store_true",
        help=(
            "Enable additional coherent-output checks and scenario-level coherence metrics. "
            "Requires schema priors manifest."
        ),
    )
    parser.add_argument(
        "--priors-manifest",
        type=Path,
        default=Path("data/processed/lr_one_vs_rest/manifests/schema_priors.csv"),
        help="Schema priors manifest path (required in coherence mode).",
    )
    parser.add_argument(
        "--raw-outputs-root",
        type=Path,
        default=Path("data/processed/lr_one_vs_rest/outputs_by_model"),
        help="Raw model output root for before/after coherence-gap and adjustment metrics.",
    )
    parser.add_argument(
        "--raw-output-filename-suffix",
        type=str,
        default="_filled.xlsx",
        help="Workbook filename suffix for raw outputs root (used in coherence-mode comparisons).",
    )
    parser.add_argument(
        "--coherence-summary-out",
        type=Path,
        default=Path("data/processed/lr_one_vs_rest/manifests/coherence_quality_summary.csv"),
        help="Scenario-level coherence summary CSV output path.",
    )
    parser.add_argument(
        "--coherence-invalid-out",
        type=Path,
        default=Path("data/processed/lr_one_vs_rest/manifests/coherence_invalid_rows.csv"),
        help="Row-level coherence-invalid CSV output path.",
    )
    parser.add_argument(
        "--coherence-tol",
        type=float,
        default=1e-6,
        help="Tolerance for posterior-sum-to-1 coherence check.",
    )
    parser.add_argument(
        "--projection-failures",
        type=Path,
        default=None,
        help=(
            "Optional projection failures CSV from scripts/project_one_vs_rest_coherent_lrs.py. "
            "If omitted, script will look for a model-scoped file under manifests."
        ),
    )
    return parser.parse_args()


def _resolve_path(repo_root: Path, path: Path) -> Path:
    return path if path.is_absolute() else repo_root / path


def _coerce_positive_float(value: object) -> float | None:
    if pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        out = float(text)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out) or out <= 0:
        return None
    return out


def _safe_quantile(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    return float(np.quantile(np.asarray(values, dtype=float), q))


def _coherence_audit(
    *,
    manifest_df: pd.DataFrame,
    priors_df: pd.DataFrame,
    repo_root: Path,
    outputs_root: Path,
    raw_outputs_root: Path,
    model_ids: list[str],
    coherent_output_suffix: str,
    raw_output_suffix: str,
    tolerance: float,
    projection_failures_df: pd.DataFrame | None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    import sys

    src_path = repo_root / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))

    from dx_chat_entropy.lr_differential_inputs import normalize_cell
    from dx_chat_entropy.lr_one_vs_rest_coherence import (
        independent_ovr_posteriors,
        is_sign_impossible,
        sum_q_init,
    )

    priors_required = {
        "scenario_id",
        "schema_order",
        "schema_sheet_name",
        "category_order",
        "category",
        "prior_normalized",
    }
    missing_prior_cols = sorted(priors_required - set(priors_df.columns))
    if missing_prior_cols:
        raise ValueError(f"Priors manifest missing required columns: {missing_prior_cols}")

    priors_lookup: dict[tuple[str, int, str], tuple[list[str], np.ndarray]] = {}
    for key, group in priors_df.groupby(["scenario_id", "schema_order", "schema_sheet_name"]):
        ordered = group.sort_values("category_order")
        priors_lookup[(str(key[0]), int(key[1]), str(key[2]))] = (
            ordered["category"].astype(str).tolist(),
            ordered["prior_normalized"].astype(float).to_numpy(),
        )

    solver_failures_by_scenario: dict[tuple[str, str], int] = {}
    if projection_failures_df is not None and not projection_failures_df.empty:
        pf = projection_failures_df.copy()
        required_pf = {"model_id", "scenario_id"}
        if required_pf.issubset(pf.columns):
            grouped = pf.groupby(["model_id", "scenario_id"]).size()
            solver_failures_by_scenario = {
                (str(model_id), str(scenario_id)): int(count)
                for (model_id, scenario_id), count in grouped.items()
            }

    scenario_rows: list[dict[str, object]] = []
    invalid_rows: list[dict[str, object]] = []

    selected = manifest_df.sort_values(["scenario_id", "schema_order"])
    for model_id in model_ids:
        scenario_ids = selected["scenario_id"].dropna().astype(str).unique()
        for scenario_id in scenario_ids:
            rows = selected[selected["scenario_id"] == scenario_id].sort_values("schema_order")
            coherent_path = outputs_root / model_id / f"{scenario_id}{coherent_output_suffix}"
            raw_path = raw_outputs_root / model_id / f"{scenario_id}{raw_output_suffix}"

            raw_gap_values: list[float] = []
            after_gap_values: list[float] = []
            adjustment_values: list[float] = []
            sign_before = 0
            sign_after = 0
            rows_checked = 0
            local_invalid = 0

            if not coherent_path.exists():
                scenario_rows.append(
                    {
                        "model_id": model_id,
                        "scenario_id": scenario_id,
                        "rows_checked": 0,
                        "median_raw_gap": float("nan"),
                        "p90_raw_gap": float("nan"),
                        "median_after_gap": float("nan"),
                        "p90_after_gap": float("nan"),
                        "median_adjustment_mult": float("nan"),
                        "p90_adjustment_mult": float("nan"),
                        "sign_impossible_rows_before": 0,
                        "sign_impossible_rows_after": 0,
                        "coherence_invalid_rows": 0,
                        "solver_failures": solver_failures_by_scenario.get(
                            (model_id, scenario_id), 0
                        ),
                        "missing_coherent_workbook": True,
                    }
                )
                continue

            for row in rows.itertuples(index=False):
                schema_order = int(row.schema_order)
                schema_sheet = str(row.schema_sheet_name)
                key = (scenario_id, schema_order, schema_sheet)
                priors_entry = priors_lookup.get(key)
                if priors_entry is None:
                    invalid_rows.append(
                        {
                            "model_id": model_id,
                            "scenario_id": scenario_id,
                            "schema_sheet_name": schema_sheet,
                            "row_index": "",
                            "finding": "",
                            "status": "missing_priors",
                            "detail": f"priors missing for key={key}",
                        }
                    )
                    local_invalid += 1
                    continue

                prior_categories, priors = priors_entry
                df_coherent = pd.read_excel(coherent_path, sheet_name=schema_sheet, header=None)
                df_raw = (
                    pd.read_excel(raw_path, sheet_name=schema_sheet, header=None)
                    if raw_path.exists()
                    else None
                )

                category_cols = [
                    col_idx
                    for col_idx in range(1, df_coherent.shape[1])
                    if normalize_cell(df_coherent.iat[0, col_idx], collapse_internal=True)
                ]
                if len(category_cols) != len(priors):
                    invalid_rows.append(
                        {
                            "model_id": model_id,
                            "scenario_id": scenario_id,
                            "schema_sheet_name": schema_sheet,
                            "row_index": "",
                            "finding": "",
                            "status": "category_count_mismatch",
                            "detail": (
                                f"sheet categories={len(category_cols)} "
                                f"priors categories={len(priors)}"
                            ),
                        }
                    )
                    local_invalid += 1
                    continue

                finding_rows = [
                    row_idx
                    for row_idx in range(1, df_coherent.shape[0])
                    if normalize_cell(df_coherent.iat[row_idx, 0])
                ]
                for row_idx in finding_rows:
                    finding = normalize_cell(df_coherent.iat[row_idx, 0])
                    coherent_vals: list[float] = []
                    coherent_ok = True
                    for col_idx in category_cols:
                        value = _coerce_positive_float(df_coherent.iat[row_idx, col_idx])
                        if value is None:
                            coherent_ok = False
                            break
                        coherent_vals.append(value)
                    if not coherent_ok:
                        continue

                    rows_checked += 1
                    sum_after = float(np.sum(independent_ovr_posteriors(priors, coherent_vals)))
                    after_gap = abs(sum_after - 1.0)
                    after_gap_values.append(after_gap)
                    if is_sign_impossible(coherent_vals):
                        sign_after += 1

                    if after_gap > tolerance:
                        invalid_rows.append(
                            {
                                "model_id": model_id,
                                "scenario_id": scenario_id,
                                "schema_sheet_name": schema_sheet,
                                "row_index": row_idx,
                                "finding": finding,
                                "status": "posterior_sum_mismatch",
                                "detail": f"sum_q_after={sum_after}",
                            }
                        )
                        local_invalid += 1
                    if is_sign_impossible(coherent_vals):
                        invalid_rows.append(
                            {
                                "model_id": model_id,
                                "scenario_id": scenario_id,
                                "schema_sheet_name": schema_sheet,
                                "row_index": row_idx,
                                "finding": finding,
                                "status": "sign_impossible_after",
                                "detail": "all coherent LRs are >1 or all <1",
                            }
                        )
                        local_invalid += 1

                    if df_raw is not None and row_idx < df_raw.shape[0]:
                        raw_vals: list[float] = []
                        raw_ok = True
                        for col_idx in category_cols:
                            value = _coerce_positive_float(df_raw.iat[row_idx, col_idx])
                            if value is None:
                                raw_ok = False
                                break
                            raw_vals.append(value)
                        if raw_ok:
                            raw_gap = abs(sum_q_init(priors, raw_vals) - 1.0)
                            raw_gap_values.append(raw_gap)
                            if is_sign_impossible(raw_vals):
                                sign_before += 1
                            for raw_lr, coherent_lr in zip(raw_vals, coherent_vals, strict=True):
                                if raw_lr > 0 and coherent_lr > 0:
                                    adjustment_values.append(
                                        float(np.exp(abs(np.log(coherent_lr) - np.log(raw_lr))))
                                    )

            scenario_rows.append(
                {
                    "model_id": model_id,
                    "scenario_id": scenario_id,
                    "rows_checked": rows_checked,
                    "median_raw_gap": _safe_quantile(raw_gap_values, 0.5),
                    "p90_raw_gap": _safe_quantile(raw_gap_values, 0.9),
                    "median_after_gap": _safe_quantile(after_gap_values, 0.5),
                    "p90_after_gap": _safe_quantile(after_gap_values, 0.9),
                    "median_adjustment_mult": _safe_quantile(adjustment_values, 0.5),
                    "p90_adjustment_mult": _safe_quantile(adjustment_values, 0.9),
                    "sign_impossible_rows_before": sign_before,
                    "sign_impossible_rows_after": sign_after,
                    "coherence_invalid_rows": local_invalid,
                    "solver_failures": solver_failures_by_scenario.get((model_id, scenario_id), 0),
                    "missing_coherent_workbook": False,
                }
            )

    return pd.DataFrame(scenario_rows), pd.DataFrame(invalid_rows)


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root()

    manifest_path = _resolve_path(repo_root, args.manifest)
    outputs_root = _resolve_path(repo_root, args.outputs_root)
    summary_out = _resolve_path(repo_root, args.summary_out)
    invalid_out = _resolve_path(repo_root, args.invalid_out)
    priors_manifest_path = _resolve_path(repo_root, args.priors_manifest)
    raw_outputs_root = _resolve_path(repo_root, args.raw_outputs_root)
    coherence_summary_out = _resolve_path(repo_root, args.coherence_summary_out)
    coherence_invalid_out = _resolve_path(repo_root, args.coherence_invalid_out)
    output_suffix = args.output_filename_suffix
    if output_suffix is None:
        output_suffix = "_coherent.xlsx" if args.coherence_mode else "_filled.xlsx"

    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest does not exist: {manifest_path}")

    manifest_df = pd.read_csv(manifest_path)

    import sys

    src_path = repo_root / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))

    from dx_chat_entropy.lr_one_vs_rest_audit import audit_outputs

    summary_df, invalid_df = audit_outputs(
        manifest_df,
        repo_root=repo_root,
        outputs_root=outputs_root,
        output_filename_suffix=output_suffix,
        model_ids=args.model_ids,
    )

    summary_out.parent.mkdir(parents=True, exist_ok=True)
    invalid_out.parent.mkdir(parents=True, exist_ok=True)

    summary_df.sort_values(["model_id", "scenario_id", "schema_order"]).to_csv(
        summary_out, index=False
    )

    if invalid_df.empty:
        pd.DataFrame(
            columns=[
                "model_id",
                "scenario_id",
                "schema_order",
                "schema_sheet_name",
                "input_workbook",
                "output_workbook",
                "row_index",
                "col_index",
                "finding",
                "category",
                "status",
                "raw_value",
            ]
        ).to_csv(invalid_out, index=False)
    else:
        invalid_df.to_csv(invalid_out, index=False)

    sheet_rows = len(summary_df)
    expected_cells = int(summary_df["expected_cells_manifest"].sum())
    valid_cells = int(summary_df["valid_positive_cells"].sum())
    invalid_cells = int(summary_df["total_invalid_cells"].sum())
    failed_sheets = int((~summary_df["passes"]).sum())
    coherence_failed_rows = 0

    output_payload: dict[str, object] = {
        "sheet_rows": sheet_rows,
        "expected_cells": expected_cells,
        "valid_positive_cells": valid_cells,
        "invalid_cells": invalid_cells,
        "failed_sheets": failed_sheets,
        "summary_out": str(summary_out),
        "invalid_out": str(invalid_out),
    }

    if args.coherence_mode:
        if not priors_manifest_path.exists():
            raise FileNotFoundError(
                f"Coherence mode requires priors manifest: {priors_manifest_path}"
            )
        priors_df = pd.read_csv(priors_manifest_path)

        projection_failures_path = args.projection_failures
        if projection_failures_path is not None:
            projection_failures_path = _resolve_path(repo_root, projection_failures_path)
        projection_failures_df = None
        if projection_failures_path is not None and projection_failures_path.exists():
            projection_failures_df = pd.read_csv(projection_failures_path)
        elif args.model_ids and len(args.model_ids) == 1:
            auto_path = (
                repo_root
                / "data"
                / "processed"
                / "lr_one_vs_rest"
                / "manifests"
                / f"coherence_projection_failures_{args.model_ids[0]}.csv"
            )
            if auto_path.exists():
                projection_failures_df = pd.read_csv(auto_path)

        model_ids = args.model_ids or sorted(summary_df["model_id"].dropna().unique().tolist())
        coherence_summary_df, coherence_invalid_df = _coherence_audit(
            manifest_df=manifest_df,
            priors_df=priors_df,
            repo_root=repo_root,
            outputs_root=outputs_root,
            raw_outputs_root=raw_outputs_root,
            model_ids=model_ids,
            coherent_output_suffix=output_suffix,
            raw_output_suffix=str(args.raw_output_filename_suffix),
            tolerance=float(args.coherence_tol),
            projection_failures_df=projection_failures_df,
        )

        coherence_summary_out.parent.mkdir(parents=True, exist_ok=True)
        coherence_invalid_out.parent.mkdir(parents=True, exist_ok=True)
        coherence_summary_df.sort_values(["model_id", "scenario_id"]).to_csv(
            coherence_summary_out, index=False
        )
        if coherence_invalid_df.empty:
            pd.DataFrame(
                columns=[
                    "model_id",
                    "scenario_id",
                    "schema_sheet_name",
                    "row_index",
                    "finding",
                    "status",
                    "detail",
                ]
            ).to_csv(coherence_invalid_out, index=False)
        else:
            coherence_invalid_df.to_csv(coherence_invalid_out, index=False)

        coherence_failed_rows = int(len(coherence_invalid_df))
        output_payload["coherence_summary_out"] = str(coherence_summary_out)
        output_payload["coherence_invalid_out"] = str(coherence_invalid_out)
        output_payload["coherence_invalid_rows"] = coherence_failed_rows

    print(output_payload)
    return 0 if (failed_sheets == 0 and coherence_failed_rows == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
