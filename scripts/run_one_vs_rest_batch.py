from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field

try:
    from dx_chat_entropy.lr_differential_inputs import normalize_cell as shared_normalize_cell
except Exception:  # pragma: no cover - fallback path for non-package execution contexts.

    def shared_normalize_cell(value: object) -> str:
        if pd.isna(value):
            return ""
        return str(value).strip()


class LRResponse(BaseModel):
    value: float = Field(gt=0)


LR_PROMPT_TEMPLATE = """You are an expert in medical diagnosis whose task is
to estimate a likelihood ratio (LR) for a finding with respect to a category of conditions.

You will receive:
Condition: <category of interest>
Finding: <piece of information>

Return your best estimate of the likelihood ratio as a floating point number.
The LR must be > 0.

Return JSON only with this schema:
{ "value": <float > 0> }
"""


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
        description="Run one-vs-rest LR estimation over normalized schema-sheet manifests."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/processed/lr_one_vs_rest/manifests/inputs_manifest.csv"),
        help="Path to normalization inputs manifest CSV.",
    )
    parser.add_argument(
        "--model-id",
        type=str,
        default="gpt-4o-mini",
        help="OpenAI model ID.",
    )
    parser.add_argument(
        "--reasoning-effort",
        type=str,
        default="low",
        choices=["minimal", "low", "medium", "high"],
        help="Reasoning effort for reasoning-capable models (o-series and GPT-5 chat aliases).",
    )
    parser.add_argument(
        "--outputs-root",
        type=Path,
        default=Path("data/processed/lr_one_vs_rest/outputs_by_model"),
        help="Root output directory for model-scoped workbooks.",
    )
    parser.add_argument(
        "--scenario-filter",
        action="append",
        default=None,
        help="Optional scenario_id filter (may be specified multiple times).",
    )
    parser.add_argument(
        "--max-scenarios",
        type=int,
        default=None,
        help="Optional cap for number of scenarios to run.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=2,
        help="Retries per cell on API/parse failure (default 2 => 3 total attempts).",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Optional explicit repo root. Defaults to auto-detection.",
    )
    parser.add_argument(
        "--request-timeout-seconds",
        type=float,
        default=120.0,
        help="Per-request OpenAI timeout in seconds.",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=100,
        help="Emit a progress line every N cell estimates (default 100).",
    )
    return parser.parse_args()


def estimate_lr(
    *,
    condition: str,
    finding: str,
    client: OpenAI,
    model_id: str,
    reasoning_effort: str,
    max_retries: int,
    request_timeout_seconds: float,
) -> float | str:
    sys_msgs = [{"role": "system", "content": LR_PROMPT_TEMPLATE}]
    user_msg = {
        "role": "user",
        "content": f"Condition: {condition}\nFinding: {finding}",
    }

    kwargs: dict[str, object] = {}
    model_id_lower = model_id.lower()
    if model_id_lower.startswith("o") or model_id_lower.startswith("gpt-5"):
        kwargs["reasoning_effort"] = reasoning_effort

    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            completion = client.beta.chat.completions.parse(
                model=model_id,
                messages=[*sys_msgs, user_msg],
                response_format=LRResponse,
                timeout=float(request_timeout_seconds),
                **kwargs,
            )
            value = float(completion.choices[0].message.parsed.value)
            if value <= 0:
                raise ValueError(f"Parsed non-positive LR: {value}")
            return value
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                time.sleep(min(2**attempt, 5))

    print(
        f"LLM error: model={model_id} condition={condition!r} finding={finding!r} error={last_exc}"
    )
    return "ERROR"


def fill_matrix(
    df: pd.DataFrame,
    *,
    client: OpenAI,
    model_id: str,
    reasoning_effort: str,
    max_retries: int,
    request_timeout_seconds: float,
    progress_every: int,
    scenario_id: str,
    sheet_name: str,
) -> pd.DataFrame:
    # Ensure cells are writable for mixed string/float assignments.
    out = df.copy().astype("object")

    targets: list[tuple[int, str]] = []
    for col in range(1, out.shape[1]):
        target = shared_normalize_cell(out.iat[0, col])
        if target and not target.lower().startswith("for examples:"):
            targets.append((col, target))

    finding_rows: list[tuple[int, str]] = []
    for row in range(1, out.shape[0]):
        finding = shared_normalize_cell(out.iat[row, 0])
        if finding:
            finding_rows.append((row, finding))

    total_cells = len(finding_rows) * len(targets)
    done_cells = 0
    progress_step = max(1, int(progress_every))

    for row_idx, finding in finding_rows:
        for col_idx, condition in targets:
            out.iat[row_idx, col_idx] = estimate_lr(
                condition=condition,
                finding=finding,
                client=client,
                model_id=model_id,
                reasoning_effort=reasoning_effort,
                max_retries=max_retries,
                request_timeout_seconds=request_timeout_seconds,
            )
            done_cells += 1
            if done_cells % progress_step == 0 or done_cells == total_cells:
                print(
                    f"progress scenario={scenario_id} sheet={sheet_name} {done_cells}/{total_cells}"
                )

    return out


def main() -> int:
    args = parse_args()
    repo_root, require_bundle_capability = _resolve_repo_root_and_paths(args.repo_root)
    require_bundle_capability(repo_root, "estimate_raw_outputs")

    load_dotenv(dotenv_path=repo_root / ".env")
    if not os.getenv("OPENAI_API_KEY"):
        raise OSError("OPENAI_API_KEY is not set in environment/.env")

    manifest_path = args.manifest
    if not manifest_path.is_absolute():
        manifest_path = repo_root / manifest_path
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest does not exist: {manifest_path}")

    outputs_root = args.outputs_root
    if not outputs_root.is_absolute():
        outputs_root = repo_root / outputs_root

    df_manifest = pd.read_csv(manifest_path)
    required_cols = {
        "scenario_id",
        "schema_order",
        "schema_sheet_name",
        "normalized_input_workbook",
    }
    missing = sorted(required_cols - set(df_manifest.columns))
    if missing:
        raise ValueError(f"Manifest missing required columns: {missing}")

    selected = df_manifest.sort_values(["scenario_id", "schema_order"]).copy()

    if args.scenario_filter:
        allowed = {str(item) for item in args.scenario_filter}
        selected = selected[selected["scenario_id"].isin(allowed)]

    scenario_ids = list(dict.fromkeys(selected["scenario_id"].tolist()))
    if args.max_scenarios is not None:
        scenario_ids = scenario_ids[: args.max_scenarios]
        selected = selected[selected["scenario_id"].isin(set(scenario_ids))]

    if selected.empty:
        raise ValueError("No scenarios selected for one-vs-rest run.")

    client = OpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        timeout=float(args.request_timeout_seconds),
    )

    total_cells = 0
    scenario_groups = selected.groupby(["scenario_id", "normalized_input_workbook"], sort=True)

    for (scenario_id, input_workbook_rel), group_idx in scenario_groups.groups.items():
        group = selected.loc[group_idx].sort_values("schema_order")

        input_workbook = repo_root / str(input_workbook_rel)
        if not input_workbook.exists():
            raise FileNotFoundError(f"Normalized input workbook missing: {input_workbook}")

        output_workbook = outputs_root / args.model_id / f"{scenario_id}_filled.xlsx"
        output_workbook.parent.mkdir(parents=True, exist_ok=True)

        with pd.ExcelWriter(output_workbook, engine="openpyxl") as writer:
            for row in group.itertuples(index=False):
                schema_sheet_name = str(row.schema_sheet_name)
                df_in = pd.read_excel(input_workbook, sheet_name=schema_sheet_name, header=None)

                category_cols = [
                    c for c in range(1, df_in.shape[1]) if shared_normalize_cell(df_in.iat[0, c])
                ]
                finding_rows = [
                    r for r in range(1, df_in.shape[0]) if shared_normalize_cell(df_in.iat[r, 0])
                ]
                total_cells += len(category_cols) * len(finding_rows)

                print(
                    f"scenario={scenario_id} sheet={schema_sheet_name} "
                    f"targets={len(category_cols)} findings={len(finding_rows)}"
                )

                df_out = fill_matrix(
                    df_in,
                    client=client,
                    model_id=args.model_id,
                    reasoning_effort=args.reasoning_effort,
                    max_retries=args.max_retries,
                    request_timeout_seconds=float(args.request_timeout_seconds),
                    progress_every=int(args.progress_every),
                    scenario_id=str(scenario_id),
                    sheet_name=schema_sheet_name,
                )
                df_out.to_excel(writer, sheet_name=schema_sheet_name, index=False, header=False)

        print(f"Saved scenario workbook -> {output_workbook}")

    print(
        {
            "scenarios": int(selected["scenario_id"].nunique()),
            "schema_sheets": int(len(selected)),
            "model_id": args.model_id,
            "estimated_cells": int(total_cells),
            "outputs_root": str((outputs_root / args.model_id).resolve()),
        }
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
