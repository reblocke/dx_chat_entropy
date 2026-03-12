from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import pandas as pd


def _resolve_repo_root_and_paths(repo_root_arg: Path | None) -> tuple[Path, object]:
    # Scripts are always rooted one directory under repo/bundle root.
    script_root = Path(__file__).resolve().parents[1]
    src_path = script_root / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))

    from dx_chat_entropy.paths import find_repo_root, require_bundle_capability

    if repo_root_arg is not None:
        repo_root = find_repo_root(repo_root_arg.resolve())
    else:
        repo_root = find_repo_root(Path.cwd())

    resolved_src = repo_root / "src"
    if str(resolved_src) not in sys.path:
        sys.path.insert(0, str(resolved_src))

    return repo_root, require_bundle_capability


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Project raw one-vs-rest LRs to Bayes-coherent multiclass OVR LRs "
            "using schema priors and the coherence solver."
        )
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/processed/lr_one_vs_rest/manifests/inputs_manifest.csv"),
    )
    parser.add_argument(
        "--priors-manifest",
        type=Path,
        default=Path("data/processed/lr_one_vs_rest/manifests/schema_priors.csv"),
    )
    parser.add_argument(
        "--outputs-root",
        type=Path,
        default=Path("data/processed/lr_one_vs_rest/outputs_by_model"),
    )
    parser.add_argument(
        "--coherent-outputs-root",
        type=Path,
        default=Path("data/processed/lr_one_vs_rest/coherent_outputs_by_model"),
    )
    parser.add_argument("--model-id", type=str, required=True)
    parser.add_argument("--scenario-filter", action="append", default=None)
    parser.add_argument("--max-schemas", type=int, default=None)
    parser.add_argument("--max-findings", type=int, default=None)
    parser.add_argument("--reg", type=float, default=1e-6)
    parser.add_argument("--fail-on-missing-priors", action="store_true")
    parser.add_argument(
        "--derive-priors-if-missing",
        action="store_true",
        help="If schema_priors.csv is missing, derive and write it from source sheets.",
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--allow-partial-write",
        action="store_true",
        help=(
            "Allow writing coherent workbooks when partial selectors "
            "(`--max-schemas`/`--max-findings`) are used."
        ),
    )
    parser.add_argument("--write-posterior-debug", action="store_true")
    parser.add_argument("--repo-root", type=Path, default=None)
    return parser.parse_args()


def _resolve_path(repo_root: Path, path: Path) -> Path:
    return path if path.is_absolute() else repo_root / path


def _coerce_positive_float(value: object) -> float | None:
    text = value
    if pd.isna(text):
        return None
    text = str(text).strip()
    if not text:
        return None
    try:
        out = float(text)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out) or out <= 0:
        return None
    return out


def _ensure_priors_manifest(
    *,
    repo_root: Path,
    manifest_df: pd.DataFrame,
    priors_manifest_path: Path,
) -> pd.DataFrame:
    import sys

    src_path = repo_root / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))

    from dx_chat_entropy.lr_differential_inputs import (
        DEFAULT_KEY_FEATURE_PATTERN,
        find_key_feature_row,
    )
    from dx_chat_entropy.lr_one_vs_rest_inputs import extract_schema_priors

    source_cache: dict[tuple[str, str], pd.DataFrame] = {}
    priors_rows: list[dict[str, object]] = []
    for row in manifest_df.itertuples(index=False):
        source_workbook = repo_root / str(row.source_workbook)
        source_sheet = str(row.source_sheet)
        key = (str(source_workbook), source_sheet)
        if key not in source_cache:
            source_cache[key] = pd.read_excel(source_workbook, sheet_name=source_sheet, header=None)
        df_src = source_cache[key]

        key_feature_row_idx = find_key_feature_row(df_src, DEFAULT_KEY_FEATURE_PATTERN)
        priors = extract_schema_priors(
            df_src,
            schema_row_idx=int(row.schema_row_idx),
            key_feature_row_idx=key_feature_row_idx,
        )
        for span in priors.spans:
            idx = span.category_order - 1
            priors_rows.append(
                {
                    "scenario_id": str(row.scenario_id),
                    "source_workbook": str(row.source_workbook),
                    "source_sheet": source_sheet,
                    "schema_order": int(row.schema_order),
                    "schema_row_idx": int(row.schema_row_idx),
                    "schema_sheet_name": str(row.schema_sheet_name),
                    "prior_row_idx": priors.prior_row_idx,
                    "category_order": span.category_order,
                    "category": span.label,
                    "prior_raw": priors.priors_raw[idx],
                    "prior_normalized": priors.priors_normalized[idx],
                    "prior_vector_sum_raw": priors.prior_vector_sum_raw,
                }
            )

    priors_df = pd.DataFrame(priors_rows).sort_values(
        ["scenario_id", "schema_order", "category_order"]
    )
    priors_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    priors_df.to_csv(priors_manifest_path, index=False)
    return priors_df


def main() -> int:
    args = parse_args()
    repo_root, require_bundle_capability = _resolve_repo_root_and_paths(args.repo_root)
    require_bundle_capability(repo_root, "project_coherent")

    partial_requested = args.max_schemas is not None or args.max_findings is not None
    if partial_requested and not args.allow_partial_write:
        raise ValueError(
            "Partial projection requested (`--max-schemas` and/or `--max-findings`). "
            "Refusing canonical write by default. Re-run with --allow-partial-write "
            "to explicitly opt in."
        )
    if partial_requested and args.allow_partial_write:
        print(
            "[partial-write-warning] Writing partial coherent outputs because "
            "--allow-partial-write is enabled."
        )

    manifest_path = _resolve_path(repo_root, args.manifest)
    priors_manifest_path = _resolve_path(repo_root, args.priors_manifest)
    outputs_root = _resolve_path(repo_root, args.outputs_root)
    coherent_outputs_root = _resolve_path(repo_root, args.coherent_outputs_root)

    if not manifest_path.exists():
        raise FileNotFoundError(f"Inputs manifest not found: {manifest_path}")
    manifest_df = pd.read_csv(manifest_path)

    required_manifest_cols = {
        "scenario_id",
        "source_workbook",
        "source_sheet",
        "schema_order",
        "schema_row_idx",
        "schema_sheet_name",
        "normalized_input_workbook",
    }
    missing_cols = sorted(required_manifest_cols - set(manifest_df.columns))
    if missing_cols:
        raise ValueError(f"Inputs manifest missing required columns: {missing_cols}")

    if priors_manifest_path.exists():
        priors_df = pd.read_csv(priors_manifest_path)
    elif args.derive_priors_if_missing:
        print(f"schema_priors.csv missing, deriving now -> {priors_manifest_path}")
        priors_df = _ensure_priors_manifest(
            repo_root=repo_root,
            manifest_df=manifest_df,
            priors_manifest_path=priors_manifest_path,
        )
    else:
        raise FileNotFoundError(
            "schema_priors.csv missing. Run scripts/build_one_vs_rest_inputs.py "
            "or pass --derive-priors-if-missing."
        )

    required_prior_cols = {
        "scenario_id",
        "schema_order",
        "schema_sheet_name",
        "category_order",
        "category",
        "prior_normalized",
    }
    missing_prior_cols = sorted(required_prior_cols - set(priors_df.columns))
    if missing_prior_cols:
        raise ValueError(f"Priors manifest missing required columns: {missing_prior_cols}")

    selected = manifest_df.sort_values(["scenario_id", "schema_order"]).copy()
    if args.scenario_filter:
        allowed = {str(item) for item in args.scenario_filter}
        selected = selected[selected["scenario_id"].isin(allowed)]
    if args.max_schemas is not None:
        selected = selected.head(int(args.max_schemas))
    if selected.empty:
        raise ValueError("No schema rows selected for projection.")

    src_path = repo_root / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))

    from dx_chat_entropy.lr_differential_inputs import normalize_cell
    from dx_chat_entropy.lr_one_vs_rest_coherence import (
        is_sign_impossible,
        ovr_project_posterior,
    )

    priors_key_cols = ["scenario_id", "schema_order", "schema_sheet_name"]
    priors_lookup: dict[tuple[str, int, str], pd.DataFrame] = {}
    for key, group in priors_df.groupby(priors_key_cols):
        priors_lookup[(str(key[0]), int(key[1]), str(key[2]))] = group.sort_values("category_order")

    row_metrics: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    summary_rows: list[dict[str, object]] = []
    written_workbooks = 0

    grouped = selected.groupby("scenario_id", sort=True)
    for scenario_id, scenario_rows in grouped:
        scenario_rows = scenario_rows.sort_values("schema_order")
        raw_workbook = outputs_root / args.model_id / f"{scenario_id}_filled.xlsx"
        coherent_workbook = coherent_outputs_root / args.model_id / f"{scenario_id}_coherent.xlsx"
        coherent_workbook.parent.mkdir(parents=True, exist_ok=True)

        if coherent_workbook.exists() and not args.overwrite:
            print(f"Skip existing coherent workbook (use --overwrite): {coherent_workbook}")
            continue

        if not raw_workbook.exists():
            message = f"Raw OVR workbook missing: {raw_workbook}"
            failures.append(
                {
                    "model_id": args.model_id,
                    "scenario_id": scenario_id,
                    "schema_sheet_name": "",
                    "row_index": "",
                    "finding": "",
                    "reason": message,
                }
            )
            if args.fail_on_missing_priors:
                raise FileNotFoundError(message)
            print(message)
            continue

        projected_sheets: list[tuple[str, pd.DataFrame]] = []
        for row in scenario_rows.itertuples(index=False):
            schema_order = int(row.schema_order)
            schema_sheet = str(row.schema_sheet_name)
            key = (str(scenario_id), schema_order, schema_sheet)
            prior_block = priors_lookup.get(key)
            if prior_block is None or prior_block.empty:
                msg = f"Missing priors for key={key}"
                if args.fail_on_missing_priors:
                    raise ValueError(msg)
                failures.append(
                    {
                        "model_id": args.model_id,
                        "scenario_id": scenario_id,
                        "schema_sheet_name": schema_sheet,
                        "row_index": "",
                        "finding": "",
                        "reason": msg,
                    }
                )
                continue

            priors = prior_block["prior_normalized"].astype(float).to_numpy()
            categories = prior_block["category"].astype(str).tolist()

            try:
                df_raw = pd.read_excel(raw_workbook, sheet_name=schema_sheet, header=None)
            except Exception as exc:  # pragma: no cover - external workbook corruption
                msg = f"Unable to read raw workbook sheet {schema_sheet}: {exc}"
                if args.fail_on_missing_priors:
                    raise RuntimeError(msg) from exc
                failures.append(
                    {
                        "model_id": args.model_id,
                        "scenario_id": scenario_id,
                        "schema_sheet_name": schema_sheet,
                        "row_index": "",
                        "finding": "",
                        "reason": msg,
                    }
                )
                continue

            df_out = df_raw.copy().astype("object")
            category_cols = [
                col_idx
                for col_idx in range(1, df_raw.shape[1])
                if normalize_cell(df_raw.iat[0, col_idx], collapse_internal=True)
            ]
            if len(category_cols) != len(priors):
                msg = (
                    f"Category count mismatch for {scenario_id}/{schema_sheet}: "
                    f"sheet={len(category_cols)} priors={len(priors)}"
                )
                if args.fail_on_missing_priors:
                    raise ValueError(msg)
                failures.append(
                    {
                        "model_id": args.model_id,
                        "scenario_id": scenario_id,
                        "schema_sheet_name": schema_sheet,
                        "row_index": "",
                        "finding": "",
                        "reason": msg,
                    }
                )
                continue

            finding_rows = [
                row_idx
                for row_idx in range(1, df_raw.shape[0])
                if normalize_cell(df_raw.iat[row_idx, 0])
            ]
            if args.max_findings is not None:
                finding_rows = finding_rows[: int(args.max_findings)]

            sheet_row_count = 0
            sheet_success = 0
            sheet_failures = 0
            sign_before = 0
            sign_after = 0
            gap_values: list[float] = []
            adjust_values: list[float] = []

            for row_idx in finding_rows:
                sheet_row_count += 1
                finding = normalize_cell(df_raw.iat[row_idx, 0])
                raw_vals: list[float] = []
                valid = True
                for col_idx in category_cols:
                    value = _coerce_positive_float(df_raw.iat[row_idx, col_idx])
                    if value is None:
                        valid = False
                        break
                    raw_vals.append(value)

                if not valid:
                    sheet_failures += 1
                    failures.append(
                        {
                            "model_id": args.model_id,
                            "scenario_id": scenario_id,
                            "schema_sheet_name": schema_sheet,
                            "row_index": row_idx,
                            "finding": finding,
                            "reason": "raw row contains missing/non-positive/non-numeric LR",
                        }
                    )
                    continue

                result = ovr_project_posterior(priors=priors, ovr_lr=raw_vals, reg=float(args.reg))
                if not result.success:
                    sheet_failures += 1
                    failures.append(
                        {
                            "model_id": args.model_id,
                            "scenario_id": scenario_id,
                            "schema_sheet_name": schema_sheet,
                            "row_index": row_idx,
                            "finding": finding,
                            "reason": result.message,
                        }
                    )
                    continue

                fitted = result.fitted_ovr_lr
                sheet_success += 1
                if is_sign_impossible(raw_vals):
                    sign_before += 1
                if is_sign_impossible(fitted):
                    sign_after += 1

                sum_q_raw = float(result.diagnostics.get("sum_q_init", float("nan")))
                gap_values.append(abs(sum_q_raw - 1.0))
                for col_idx, value in zip(category_cols, fitted, strict=True):
                    df_out.iat[row_idx, col_idx] = float(value)

                for category, prior, raw_lr, fitted_lr, posterior in zip(
                    categories,
                    priors,
                    raw_vals,
                    fitted.tolist(),
                    result.posterior.tolist(),
                    strict=True,
                ):
                    if raw_lr > 0 and fitted_lr > 0:
                        abs_log_change = abs(math.log(fitted_lr) - math.log(raw_lr))
                        mult_change = fitted_lr / raw_lr
                    else:
                        abs_log_change = float("nan")
                        mult_change = float("nan")
                    adjust_values.append(abs_log_change)
                    row_metrics.append(
                        {
                            "model_id": args.model_id,
                            "scenario_id": scenario_id,
                            "schema_sheet_name": schema_sheet,
                            "row_index": row_idx,
                            "finding": finding,
                            "category": category,
                            "prior": float(prior),
                            "raw_ovr_lr": float(raw_lr),
                            "fitted_ovr_lr": float(fitted_lr),
                            "mult_change": float(mult_change),
                            "abs_log_change": float(abs_log_change),
                            "posterior_fitted": float(posterior),
                            "sum_q_init": float(sum_q_raw),
                            "rmse_logLR": float(result.rmse_logLR),
                        }
                    )

            projected_sheets.append((schema_sheet, df_out))
            summary_rows.append(
                {
                    "model_id": args.model_id,
                    "scenario_id": scenario_id,
                    "schema_order": schema_order,
                    "schema_sheet_name": schema_sheet,
                    "rows_total": sheet_row_count,
                    "rows_projected": sheet_success,
                    "rows_failed": sheet_failures,
                    "median_sum_q_init_gap": float(pd.Series(gap_values).median())
                    if gap_values
                    else float("nan"),
                    "p90_sum_q_init_gap": float(pd.Series(gap_values).quantile(0.9))
                    if gap_values
                    else float("nan"),
                    "median_abs_log_change": float(pd.Series(adjust_values).median())
                    if adjust_values
                    else float("nan"),
                    "p90_abs_log_change": float(pd.Series(adjust_values).quantile(0.9))
                    if adjust_values
                    else float("nan"),
                    "sign_impossible_rows_before": int(sign_before),
                    "sign_impossible_rows_after": int(sign_after),
                }
            )

        if projected_sheets:
            with pd.ExcelWriter(coherent_workbook, engine="openpyxl") as writer:
                for sheet_name, df_out in projected_sheets:
                    df_out.to_excel(writer, sheet_name=sheet_name, index=False, header=False)
            written_workbooks += 1
            print(f"Projected coherent workbook -> {coherent_workbook}")
        else:
            print(
                f"No sheets projected for scenario={scenario_id}; skipping coherent workbook write."
            )

    manifests_dir = repo_root / "data" / "processed" / "lr_one_vs_rest" / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    summary_out = manifests_dir / f"coherence_projection_summary_{args.model_id}.csv"
    top_rows_out = manifests_dir / f"coherence_projection_top_rows_{args.model_id}.csv"
    failures_out = manifests_dir / f"coherence_projection_failures_{args.model_id}.csv"

    summary_df = pd.DataFrame(summary_rows)
    if not summary_df.empty:
        summary_df = summary_df.sort_values(["scenario_id", "schema_order", "schema_sheet_name"])
    else:
        summary_df = pd.DataFrame(
            columns=[
                "model_id",
                "scenario_id",
                "schema_order",
                "schema_sheet_name",
                "rows_total",
                "rows_projected",
                "rows_failed",
                "median_sum_q_init_gap",
                "p90_sum_q_init_gap",
                "median_abs_log_change",
                "p90_abs_log_change",
                "sign_impossible_rows_before",
                "sign_impossible_rows_after",
            ]
        )
    summary_df.to_csv(summary_out, index=False)

    metrics_df = pd.DataFrame(row_metrics)
    if metrics_df.empty:
        metrics_df = pd.DataFrame(
            columns=[
                "model_id",
                "scenario_id",
                "schema_sheet_name",
                "row_index",
                "finding",
                "category",
                "prior",
                "raw_ovr_lr",
                "fitted_ovr_lr",
                "mult_change",
                "abs_log_change",
                "posterior_fitted",
                "sum_q_init",
                "rmse_logLR",
            ]
        )
    top_df = metrics_df.sort_values("abs_log_change", ascending=False).head(500)
    top_df.to_csv(top_rows_out, index=False)

    failures_df = pd.DataFrame(failures)
    if failures_df.empty:
        failures_df = pd.DataFrame(
            columns=[
                "model_id",
                "scenario_id",
                "schema_sheet_name",
                "row_index",
                "finding",
                "reason",
            ]
        )
    failures_df.to_csv(failures_out, index=False)

    if args.write_posterior_debug:
        debug_out = manifests_dir / f"coherence_projection_rows_{args.model_id}.csv"
        metrics_df.to_csv(debug_out, index=False)
    else:
        debug_out = None

    print(
        {
            "model_id": args.model_id,
            "workbooks_written": written_workbooks,
            "schemas": int(len(summary_df)),
            "projected_rows": int(summary_df["rows_projected"].sum()) if len(summary_df) else 0,
            "failed_rows": int(summary_df["rows_failed"].sum()) if len(summary_df) else 0,
            "summary_out": str(summary_out),
            "top_rows_out": str(top_rows_out),
            "failures_out": str(failures_out),
            "debug_rows_out": str(debug_out) if debug_out else "",
            "coherent_outputs_root": str((coherent_outputs_root / args.model_id).resolve()),
        }
    )
    return 0 if failures_df.empty else 1


if __name__ == "__main__":
    raise SystemExit(main())
