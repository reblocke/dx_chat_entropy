from __future__ import annotations

import json
import math
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

from .lr_differential_audit import classify_lr_cell
from .lr_differential_inputs import normalize_cell
from .paths import ProjectPaths

CANONICAL_OUTPUTS_ROOT = Path("data/processed/lr_differential/outputs")
VALID_RESUME_MODES = {"recompute", "skip_passing", "repair_invalid"}

SYSTEM_CORE = """You are a Bayesian diagnostic assistant.
Estimate a numeric differential likelihood ratio (LR)
for a finding comparing Condition A vs Condition B.
Assume the patient has exactly one of the two candidate conditions.
Return structured output only with a positive numeric LR value.
"""

DEFINITION_TEMPLATE = """Definition:
Differential LR = P(finding | Condition A) / P(finding | Condition B)
Condition A = {dx_cat_1}
Condition B = {dx_cat_2}
"""

BANDS_TEMPLATE = """Reference evidence bands (Condition A vs Condition B):
>10 strong for A; 5-10 moderate for A; 2-5 weak for A;
0.5-2 negligible;
0.2-0.5 weak for B; 0.1-0.2 moderate for B; <=0.1 strong for B.
"""

FEW_SHOT_RICH = [
    ("acute pulmonary embolism", "costochondritis", "pleuritic chest pain", 2.4),
    ("acute pulmonary embolism", "costochondritis", "reproducible chest wall tenderness", 0.22),
    ("acute appendicitis", "gastroenteritis", "migration of pain to right lower quadrant", 3.8),
    ("acute appendicitis", "gastroenteritis", "watery diarrhea predominant", 0.35),
    ("bacterial pneumonia", "acute bronchitis", "focal lobar consolidation on chest x-ray", 9.0),
    ("bacterial pneumonia", "acute bronchitis", "normal chest x-ray", 0.12),
    ("acute pyelonephritis", "cystitis", "costovertebral angle tenderness", 3.2),
    ("acute pyelonephritis", "cystitis", "isolated dysuria without fever", 0.5),
]

FEW_SHOT_MIN = [
    ("acute pulmonary embolism", "costochondritis", "reproducible chest wall tenderness", 0.22),
    ("bacterial pneumonia", "acute bronchitis", "focal lobar consolidation on chest x-ray", 9.0),
]


@dataclass(frozen=True)
class DifferentialRuntimeConfig:
    model_id: str
    api_backend: str
    reasoning_effort: str
    verbosity: str
    non_reasoning_temperature: float
    max_retries_per_finding: int
    retry_backoff_seconds: float

    manifest_path: Path
    scenario_filter: list[str] | None
    max_pairs: int | None
    max_findings: int | None
    outputs_by_model_root: Path

    resume_mode: str
    invalid_rows_path: Path
    repair_scenario_filter: list[str] | None
    repair_max_rows: int | None

    manual_workbooks: list[tuple[Path, Path]]


def _env_optional_int(name: str, *, environ: Mapping[str, str]) -> int | None:
    raw = environ.get(name)
    if raw is None or not raw.strip():
        return None
    return int(raw)


def _env_list(name: str, *, environ: Mapping[str, str]) -> list[str] | None:
    raw = environ.get(name)
    if raw is None or not raw.strip():
        return None
    return [item.strip() for item in raw.split(",") if item.strip()]


def _env_bool(name: str, *, environ: Mapping[str, str]) -> bool:
    return environ.get(name, "false").lower() in {"1", "true", "yes", "on"}


def normalize_resume_mode(mode: str, *, legacy_repair_mode: bool = False) -> str:
    normalized = (mode or "recompute").strip().lower()
    if legacy_repair_mode and normalized == "recompute":
        normalized = "repair_invalid"
    if normalized not in VALID_RESUME_MODES:
        raise ValueError(
            f"Unsupported DX_RESUME_MODE: {mode!r}. Allowed values: {sorted(VALID_RESUME_MODES)}"
        )
    return normalized


def default_invalid_rows_path(processed_root: Path, model_id: str) -> Path:
    manifests_dir = processed_root / "lr_differential" / "manifests"
    model_scoped = manifests_dir / f"invalid_rows_{model_id}.csv"
    generic = manifests_dir / "invalid_rows.csv"
    if model_scoped.exists():
        return model_scoped
    return generic


def resolve_invalid_rows_path(
    processed_root: Path,
    model_id: str,
    explicit_path: str | None,
) -> Path:
    if explicit_path and explicit_path.strip():
        return Path(explicit_path)
    return default_invalid_rows_path(processed_root, model_id)


def build_runtime_config(
    *,
    repo_root: Path,
    paths: ProjectPaths,
    environ: Mapping[str, str] | None = None,
) -> DifferentialRuntimeConfig:
    env = environ or os.environ

    model_id = env.get("DX_MODEL_ID", "gpt-4.1-nano-2025-04-14")
    legacy_repair_mode = _env_bool("DX_REPAIR_MODE", environ=env)
    resume_mode = normalize_resume_mode(
        env.get("DX_RESUME_MODE", "recompute"),
        legacy_repair_mode=legacy_repair_mode,
    )

    dysphagia_input_name = (
        "LRs for 87 features within GI ddx - dysphagia vs esophageal pain without dysphagia.xlsx"
    )
    dysphagia_output_name = (
        "LRs for 87 features within GI ddx - "
        "dysphagia vs esophageal pain without dysphagia_filled.xlsx"
    )

    manual_workbooks = [
        (
            paths.raw / "lr_matrices" / "dysphagia" / dysphagia_input_name,
            paths.processed / "lr_differential" / "outputs" / "dysphagia" / dysphagia_output_name,
        )
    ]

    return DifferentialRuntimeConfig(
        model_id=model_id,
        api_backend=env.get("DX_API_BACKEND", "responses"),
        reasoning_effort=env.get("DX_REASONING_EFFORT", "low"),
        verbosity=env.get("DX_VERBOSITY", "low"),
        non_reasoning_temperature=float(env.get("DX_TEMPERATURE", "0.2")),
        max_retries_per_finding=int(env.get("DX_MAX_RETRIES_PER_FINDING", "2")),
        retry_backoff_seconds=float(env.get("DX_RETRY_BACKOFF_SECONDS", "1.0")),
        manifest_path=Path(
            env.get(
                "DX_MANIFEST_PATH",
                str(paths.processed / "lr_differential" / "manifests" / "pairs_manifest.csv"),
            )
        ),
        scenario_filter=_env_list("DX_SCENARIO_FILTER", environ=env),
        max_pairs=_env_optional_int("DX_MAX_PAIRS", environ=env),
        max_findings=_env_optional_int("DX_MAX_FINDINGS", environ=env),
        outputs_by_model_root=Path(
            env.get(
                "DX_OUTPUTS_BY_MODEL_ROOT",
                str(paths.processed / "lr_differential" / "outputs_by_model"),
            )
        ),
        resume_mode=resume_mode,
        invalid_rows_path=resolve_invalid_rows_path(
            paths.processed,
            model_id,
            env.get("DX_INVALID_ROWS_PATH"),
        ),
        repair_scenario_filter=_env_list("DX_REPAIR_SCENARIO_FILTER", environ=env),
        repair_max_rows=_env_optional_int("DX_REPAIR_MAX_ROWS", environ=env),
        manual_workbooks=manual_workbooks,
    )


def _model_capabilities(model_id: str) -> dict[str, bool]:
    m = model_id.lower()
    if m.startswith("gpt-5"):
        return {"reasoning": True, "verbosity": True, "allow_temp": False}
    if m.startswith("o3") or m.startswith("o4"):
        return {"reasoning": True, "verbosity": False, "allow_temp": False}
    if m.startswith("gpt-4.1") or m.startswith("gpt-4o"):
        return {"reasoning": False, "verbosity": False, "allow_temp": True}
    return {"reasoning": False, "verbosity": False, "allow_temp": True}


def _format_examples(ex_list: list[str]) -> str:
    return ", ".join(ex_list) if ex_list else "-"


def build_messages(
    dx_cat_1: str,
    dx_cat_2: str,
    dx_cat_1_examples: list[str],
    dx_cat_2_examples: list[str],
    finding: str,
    *,
    reasoning: bool,
) -> list[dict[str, str]]:
    ex1 = _format_examples(dx_cat_1_examples)
    ex2 = _format_examples(dx_cat_2_examples)

    messages: list[dict[str, str]] = [
        {"role": "system", "content": SYSTEM_CORE.strip()},
        {
            "role": "system",
            "content": DEFINITION_TEMPLATE.format(dx_cat_1=dx_cat_1, dx_cat_2=dx_cat_2).strip(),
        },
        {"role": "system", "content": BANDS_TEMPLATE.strip()},
        {
            "role": "system",
            "content": (
                "Category examples for context:\n"
                f"- Condition A ({dx_cat_1}): {ex1}\n"
                f"- Condition B ({dx_cat_2}): {ex2}"
            ),
        },
    ]

    examples = FEW_SHOT_MIN if reasoning else FEW_SHOT_RICH
    for cond_a, cond_b, finding_ex, lr_ex in examples:
        messages.append(
            {
                "role": "user",
                "content": f"Condition A: {cond_a}\nCondition B: {cond_b}\nFinding: {finding_ex}",
            }
        )
        messages.append({"role": "assistant", "content": f'{{"lr": {float(lr_ex)}}}'})

    messages.append(
        {
            "role": "user",
            "content": f"Condition A: {dx_cat_1}\nCondition B: {dx_cat_2}\nFinding: {finding}",
        }
    )
    return messages


def load_dx_categories(path: Path) -> tuple[str, str, list[str], list[str]]:
    df_raw = pd.read_excel(path, header=None)
    cats = df_raw.iloc[0].ffill().map(lambda value: normalize_cell(value, collapse_internal=True))
    ex_row = df_raw.iloc[1]

    unique_cats = [label for label in pd.unique(cats) if normalize_cell(label)]
    if len(unique_cats) != 2:
        raise ValueError("Expected exactly two category labels in row 0.")

    dx_cat_1, dx_cat_2 = unique_cats

    def _clean_examples(series: pd.Series) -> list[str]:
        cleaned: list[str] = []
        for raw in series.tolist():
            value = normalize_cell(raw)
            if value:
                cleaned.append(value)
        return cleaned

    ex1 = _clean_examples(ex_row[cats == dx_cat_1])
    ex2 = _clean_examples(ex_row[cats == dx_cat_2])
    return dx_cat_1, dx_cat_2, ex1, ex2


def _normalize_scenario_filter(value: list[str] | None) -> set[str] | None:
    if value is None:
        return None
    return {str(item) for item in value}


def _resolve_model_output_path(
    *,
    outputs_by_model_root: Path,
    model_id: str,
    manifest_output_path: Path,
    scenario_id: str,
) -> Path:
    try:
        rel = manifest_output_path.relative_to(CANONICAL_OUTPUTS_ROOT)
    except ValueError:
        rel = Path(scenario_id) / manifest_output_path.name
    return outputs_by_model_root / model_id / rel


def _collect_finding_rows(df_in: pd.DataFrame, *, max_findings: int | None) -> list[int]:
    rows: list[int] = []
    for row_idx in range(2, df_in.shape[0]):
        if normalize_cell(df_in.iat[row_idx, 0]):
            rows.append(row_idx)

    if max_findings is not None:
        rows = rows[: int(max_findings)]
    return rows


def workbook_passes_existing_output(
    *,
    df_in: pd.DataFrame,
    output_path: Path,
    max_findings: int | None,
) -> bool:
    if not output_path.exists():
        return False

    df_out = pd.read_excel(output_path, sheet_name=0, header=None)
    if df_out.shape[1] < 1:
        return False
    result_col = df_out.shape[1] - 1

    for row_idx in _collect_finding_rows(df_in, max_findings=max_findings):
        if row_idx >= df_out.shape[0]:
            return False
        classification = classify_lr_cell(df_out.iat[row_idx, result_col])
        if classification.status != "valid":
            return False
    return True


def load_workbooks_from_manifest(
    *,
    repo_root: Path,
    manifest_path: Path,
    scenario_filter: list[str] | None,
    max_pairs: int | None,
) -> list[dict[str, Any]]:
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    df_manifest = pd.read_csv(manifest_path)
    required = {"input_workbook", "output_workbook"}
    missing = sorted(required - set(df_manifest.columns))
    if missing:
        raise ValueError(f"Manifest missing required columns: {missing}")

    if "scenario_id" not in df_manifest.columns:
        df_manifest["scenario_id"] = "unknown"
    if "pair_index" not in df_manifest.columns:
        df_manifest["pair_index"] = range(1, len(df_manifest) + 1)

    selected = df_manifest.sort_values(["scenario_id", "pair_index"]).copy()
    allowed = _normalize_scenario_filter(scenario_filter)
    if allowed is not None:
        selected = selected[selected["scenario_id"].isin(allowed)]

    if max_pairs is not None:
        selected = selected.head(int(max_pairs))

    records = []
    for row in selected.itertuples(index=False):
        records.append(
            {
                "input_workbook": repo_root / str(row.input_workbook),
                "manifest_output_workbook": repo_root / str(row.output_workbook),
                "scenario_id": str(row.scenario_id),
                "pair_index": int(row.pair_index),
            }
        )
    return records


def load_invalid_rows_for_repair(
    *,
    invalid_rows_path: Path,
    model_id: str,
    scenario_filter: list[str] | None,
    max_rows: int | None,
) -> pd.DataFrame:
    if not invalid_rows_path.exists():
        raise FileNotFoundError(f"Invalid-rows CSV not found: {invalid_rows_path}")

    df_invalid = pd.read_csv(invalid_rows_path)
    required = {
        "model_id",
        "scenario_id",
        "pair_index",
        "input_workbook",
        "output_workbook",
        "row_index",
    }
    missing = sorted(required - set(df_invalid.columns))
    if missing:
        raise ValueError(f"Invalid-rows CSV missing required columns: {missing}")

    selected = df_invalid[df_invalid["model_id"] == model_id].copy()
    allowed = _normalize_scenario_filter(scenario_filter)
    if allowed is not None:
        selected = selected[selected["scenario_id"].isin(allowed)]

    selected = selected.sort_values(["scenario_id", "pair_index", "row_index"])
    if max_rows is not None:
        selected = selected.head(int(max_rows))
    return selected


@lru_cache(maxsize=1)
def _diff_lr_model() -> type:
    from pydantic import BaseModel, Field

    class DiffLR(BaseModel):
        lr: float = Field(gt=0)
        strength: str | None = None
        rationale: str | None = None

    return DiffLR


def _dedupe_dicts(dicts: list[dict[str, object]]) -> list[dict[str, object]]:
    seen: set[str] = set()
    out: list[dict[str, object]] = []
    for item in dicts:
        key = json.dumps(item, sort_keys=True)
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _validate_positive_lr(value: object) -> float:
    try:
        lr_val = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"LR is not numeric: {value!r}") from exc

    if not math.isfinite(lr_val):
        raise ValueError(f"LR must be finite, got {lr_val!r}")
    if lr_val <= 0:
        raise ValueError(f"LR must be > 0, got {lr_val}")
    return lr_val


def _is_transient_error(exc: Exception) -> bool:
    text = str(exc).lower()
    markers = [
        "rate limit",
        "timeout",
        "temporar",
        "connection",
        "connection reset",
        "service unavailable",
        "502",
        "503",
        "504",
        "429",
    ]
    return any(marker in text for marker in markers)


class DifferentialEstimator:
    def __init__(self, *, config: DifferentialRuntimeConfig) -> None:
        from openai import OpenAI

        self.config = config
        self.client = OpenAI()
        self.model_caps = _model_capabilities(config.model_id)

    def _responses_parse_diff_lr(self, messages: list[dict[str, str]]) -> float:
        full: dict[str, object] = {}
        if self.model_caps["reasoning"] and self.config.reasoning_effort:
            full["reasoning"] = {"effort": self.config.reasoning_effort}
        if self.model_caps["allow_temp"]:
            full["temperature"] = self.config.non_reasoning_temperature
        if self.model_caps["verbosity"] and self.config.verbosity:
            full["text"] = {"verbosity": self.config.verbosity}

        candidates = [
            full,
            {k: v for k, v in full.items() if k != "text"},
            {k: v for k, v in full.items() if k != "reasoning"},
            {k: v for k, v in full.items() if k != "temperature"},
            {},
        ]

        last_exc: Exception | None = None
        for extra in _dedupe_dicts(candidates):
            try:
                resp = self.client.responses.parse(
                    model=self.config.model_id,
                    input=messages,
                    text_format=_diff_lr_model(),
                    **extra,
                )
                return _validate_positive_lr(resp.output_parsed.lr)
            except Exception as exc:  # pragma: no cover - backend behavior
                last_exc = exc

        raise RuntimeError(f"Responses API parse failed after fallbacks: {last_exc}")

    def _chat_parse_diff_lr(self, messages: list[dict[str, str]]) -> float:
        extra: dict[str, object] = {}
        model_lower = self.config.model_id.lower()
        if self.config.reasoning_effort and (
            model_lower.startswith("o") or model_lower.startswith("gpt-5")
        ):
            extra["reasoning_effort"] = self.config.reasoning_effort
        if self.model_caps["allow_temp"]:
            extra["temperature"] = self.config.non_reasoning_temperature

        resp = self.client.beta.chat.completions.parse(
            model=self.config.model_id,
            messages=messages,
            response_format=_diff_lr_model(),
            **extra,
        )
        return _validate_positive_lr(resp.choices[0].message.parsed.lr)

    def _estimate_once(self, messages: list[dict[str, str]]) -> float:
        backend = self.config.api_backend.lower().strip()
        if backend == "responses":
            return self._responses_parse_diff_lr(messages)
        if backend == "chat":
            return self._chat_parse_diff_lr(messages)
        if backend == "auto":
            responses_exc: Exception | None = None
            chat_exc: Exception | None = None
            try:
                return self._responses_parse_diff_lr(messages)
            except Exception as exc:  # pragma: no cover - backend behavior
                responses_exc = exc
            try:
                return self._chat_parse_diff_lr(messages)
            except Exception as exc:  # pragma: no cover - backend behavior
                chat_exc = exc
            raise RuntimeError(
                "Auto backend failed on both responses and chat paths: "
                f"responses={responses_exc} | chat={chat_exc}"
            )
        raise ValueError(f"Unsupported API_BACKEND: {self.config.api_backend}")

    def estimate_diff_lr(
        self,
        *,
        finding: str,
        dx_cat_1: str,
        dx_cat_2: str,
        ex1: list[str],
        ex2: list[str],
    ) -> float:
        base_messages = build_messages(
            dx_cat_1,
            dx_cat_2,
            ex1,
            ex2,
            finding,
            reasoning=self.model_caps["reasoning"],
        )

        failures: list[str] = []
        max_attempts = self.config.max_retries_per_finding + 1

        for attempt in range(max_attempts):
            messages = list(base_messages)
            if attempt > 0:
                messages = messages + [
                    {
                        "role": "user",
                        "content": (
                            "Output constraint reminder: return structured output with a single "
                            "numeric field `lr`, and ensure lr is a finite float "
                            "strictly greater than 0."
                        ),
                    }
                ]
            try:
                return self._estimate_once(messages)
            except Exception as exc:
                failures.append(f"attempt={attempt + 1}: {exc}")
                if attempt < max_attempts - 1 and _is_transient_error(exc):
                    sleep_seconds = self.config.retry_backoff_seconds * (2**attempt)
                    time.sleep(sleep_seconds)

        failure_summary = " | ".join(failures)
        raise RuntimeError(
            "Failed to estimate a valid differential LR after "
            f"{max_attempts} attempt(s): {failure_summary}"
        )


def run_full_estimation(
    *,
    config: DifferentialRuntimeConfig,
    records: list[dict[str, Any]],
    estimator: DifferentialEstimator,
) -> None:
    if not records:
        raise ValueError(
            "No workbooks selected. Check MANIFEST_PATH, SCENARIO_FILTER, and MAX_PAIRS."
        )

    print(f"Selected {len(records)} workbook pair(s) for full estimation.")
    print(
        "Model="
        f"{config.model_id} | backend={config.api_backend} | "
        f"reasoning_effort={config.reasoning_effort} "
        f"| verbosity={config.verbosity} | resume_mode={config.resume_mode}"
    )

    for record in records:
        wb_in = Path(record["input_workbook"])
        wb_manifest_out = Path(record["manifest_output_workbook"])
        scenario_id = str(record["scenario_id"])
        pair_index = int(record["pair_index"])
        wb_out = _resolve_model_output_path(
            outputs_by_model_root=config.outputs_by_model_root,
            model_id=config.model_id,
            manifest_output_path=wb_manifest_out,
            scenario_id=scenario_id,
        )

        print(f"\n{'=' * 80}")
        print(f"Scenario: {scenario_id} | Pair: {pair_index}")
        print(f"Input:  {wb_in}")
        print(f"Output: {wb_out}")
        print(f"{'=' * 80}")

        if not wb_in.exists():
            raise FileNotFoundError(f"Missing input workbook: {wb_in}")

        df_in = pd.read_excel(wb_in, sheet_name=0, header=None)
        if config.resume_mode == "skip_passing" and workbook_passes_existing_output(
            df_in=df_in,
            output_path=wb_out,
            max_findings=config.max_findings,
        ):
            print("Skipping workbook (existing output already passes structural audit checks).")
            continue

        dx_cat_1, dx_cat_2, ex1, ex2 = load_dx_categories(wb_in)
        df_out = df_in.copy()

        result_col = df_out.shape[1]
        df_out[result_col] = pd.Series([None] * len(df_out), dtype="object")

        header_label = f"Differential LR ({config.model_id} for '{dx_cat_1}' vs. '{dx_cat_2}')"
        df_out.iat[0, result_col] = header_label
        if len(df_out) > 1:
            df_out.iat[1, result_col] = ""

        finding_rows = _collect_finding_rows(df_in, max_findings=config.max_findings)
        print(f"Rows with findings: {len(finding_rows)}")

        for idx, row_idx in enumerate(finding_rows, start=1):
            finding = normalize_cell(df_in.iat[row_idx, 0])
            print(
                f"[{idx}/{len(finding_rows)}] "
                f"scenario={scenario_id} | comparator={dx_cat_1} vs {dx_cat_2} | "
                f"finding={finding[:80]}"
            )

            try:
                lr_val = estimator.estimate_diff_lr(
                    finding=finding,
                    dx_cat_1=dx_cat_1,
                    dx_cat_2=dx_cat_2,
                    ex1=ex1,
                    ex2=ex2,
                )
            except Exception as exc:
                raise RuntimeError(
                    "Row estimation failed after retry: "
                    f"scenario={scenario_id}, pair={pair_index}, row={row_idx}, finding={finding!r}"
                ) from exc

            df_out.iat[row_idx, result_col] = lr_val

        wb_out.parent.mkdir(parents=True, exist_ok=True)
        df_out.to_excel(wb_out, index=False, header=False)
        print(f"Saved -> {wb_out}")


def run_repair_mode(
    *,
    config: DifferentialRuntimeConfig,
    invalid_rows_df: pd.DataFrame,
    estimator: DifferentialEstimator,
    repo_root: Path,
) -> None:
    if invalid_rows_df.empty:
        raise ValueError(f"No invalid rows found for model {config.model_id!r}.")

    print(f"Repair rows selected: {len(invalid_rows_df)} for model={config.model_id}")

    grouped = invalid_rows_df.groupby(["scenario_id", "input_workbook", "output_workbook"])
    for (scenario_id, input_workbook, output_workbook), group in grouped:
        wb_in = repo_root / str(input_workbook)
        wb_out = repo_root / str(output_workbook)

        print(f"\n{'=' * 80}")
        print(f"Repair scenario: {scenario_id}")
        print(f"Input:  {wb_in}")
        print(f"Output: {wb_out}")
        print(f"Rows to patch: {len(group)}")
        print(f"{'=' * 80}")

        if not wb_in.exists():
            raise FileNotFoundError(f"Missing input workbook for repair: {wb_in}")
        if not wb_out.exists():
            raise FileNotFoundError(f"Missing output workbook for repair: {wb_out}")

        dx_cat_1, dx_cat_2, ex1, ex2 = load_dx_categories(wb_in)
        df_in = pd.read_excel(wb_in, sheet_name=0, header=None)
        df_out = pd.read_excel(wb_out, sheet_name=0, header=None)
        result_col = df_out.shape[1] - 1

        ordered = group.sort_values(["pair_index", "row_index"])
        for idx, row in enumerate(ordered.itertuples(index=False), start=1):
            row_idx = int(row.row_index)
            if row_idx < 2 or row_idx >= df_in.shape[0]:
                raise IndexError(
                    f"Repair row_index out of range for {wb_in.name}: row_index={row_idx}"
                )

            finding = normalize_cell(df_in.iat[row_idx, 0])
            if not finding:
                raise ValueError(
                    "Repair row has empty finding text: "
                    f"scenario={scenario_id}, row_index={row_idx}"
                )

            print(
                f"[repair {idx}/{len(ordered)}] "
                f"scenario={scenario_id} | comparator={dx_cat_1} vs {dx_cat_2} | "
                f"finding={finding[:80]}"
            )

            try:
                lr_val = estimator.estimate_diff_lr(
                    finding=finding,
                    dx_cat_1=dx_cat_1,
                    dx_cat_2=dx_cat_2,
                    ex1=ex1,
                    ex2=ex2,
                )
            except Exception as exc:
                raise RuntimeError(
                    "Repair failed after retry: "
                    f"scenario={scenario_id}, row={row_idx}, finding={finding!r}"
                ) from exc

            df_out.iat[row_idx, result_col] = lr_val

        wb_out.parent.mkdir(parents=True, exist_ok=True)
        df_out.to_excel(wb_out, index=False, header=False)
        print(f"Repaired -> {wb_out}")


def run_differential(
    *,
    config: DifferentialRuntimeConfig,
    repo_root: Path,
) -> None:
    estimator = DifferentialEstimator(config=config)

    if config.resume_mode == "repair_invalid":
        invalid_rows_df = load_invalid_rows_for_repair(
            invalid_rows_path=config.invalid_rows_path,
            model_id=config.model_id,
            scenario_filter=config.repair_scenario_filter,
            max_rows=config.repair_max_rows,
        )
        run_repair_mode(
            config=config,
            invalid_rows_df=invalid_rows_df,
            estimator=estimator,
            repo_root=repo_root,
        )
        return

    if config.manifest_path.exists():
        records = load_workbooks_from_manifest(
            repo_root=repo_root,
            manifest_path=config.manifest_path,
            scenario_filter=config.scenario_filter,
            max_pairs=config.max_pairs,
        )
    else:
        records = []
        for idx, (wb_in, wb_out) in enumerate(config.manual_workbooks, start=1):
            records.append(
                {
                    "input_workbook": Path(wb_in),
                    "manifest_output_workbook": Path(wb_out),
                    "scenario_id": "manual",
                    "pair_index": idx,
                }
            )

    run_full_estimation(
        config=config,
        records=records,
        estimator=estimator,
    )
