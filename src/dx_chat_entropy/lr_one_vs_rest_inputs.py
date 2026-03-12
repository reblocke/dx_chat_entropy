from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .lr_differential_inputs import (
    DEFAULT_KEY_FEATURE_PATTERN,
    CategoryBlock,
    extract_category_blocks,
    find_key_feature_row,
    normalize_cell,
)


@dataclass(frozen=True)
class SchemaRow:
    order: int
    row_idx: int
    labels: list[str]
    blocks: list[CategoryBlock]
    warning: str | None


@dataclass(frozen=True)
class CategorySpan:
    category_order: int
    label: str
    start_col: int
    end_col: int  # exclusive


@dataclass(frozen=True)
class SchemaPriors:
    prior_row_idx: int
    prior_vector_sum_raw: float
    spans: list[CategorySpan]
    priors_raw: list[float]
    priors_normalized: list[float]


def is_numeric_label(label: str) -> bool:
    cleaned = label.strip().replace(",", "")
    if cleaned.endswith("%"):
        cleaned = cleaned[:-1]
    if not cleaned:
        return False

    try:
        float(cleaned)
        return True
    except ValueError:
        return False


def discover_schema_rows(
    df: pd.DataFrame,
    *,
    key_feature_pattern: str = DEFAULT_KEY_FEATURE_PATTERN,
    expected_category_count: int | None = None,
    allow_category_count_mismatch: bool = False,
) -> tuple[int, list[SchemaRow], list[str]]:
    key_feature_row_idx = find_key_feature_row(df, key_feature_pattern)

    rows: list[SchemaRow] = []
    warnings: list[str] = []
    seen_signatures: set[tuple[str, ...]] = set()

    for row_idx in range(0, key_feature_row_idx):
        try:
            blocks = extract_category_blocks(df, category_row_idx=row_idx)
        except ValueError:
            continue

        labels = [block.label for block in blocks]
        if len(labels) < 2:
            continue
        if all(is_numeric_label(label) for label in labels):
            continue

        signature = tuple(labels)
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)

        row_warning: str | None = None
        if expected_category_count is not None and len(labels) != expected_category_count:
            message = (
                "Detected category count does not match expected count: "
                f"expected={expected_category_count}, observed={len(labels)}"
            )
            if allow_category_count_mismatch:
                row_warning = message
                warnings.append(f"schema_row={row_idx}: {row_warning}")
            else:
                raise ValueError(
                    f"schema_row={row_idx}: {message}. "
                    "Set allow_category_count_mismatch=True to override."
                )

        rows.append(
            SchemaRow(
                order=len(rows) + 1,
                row_idx=row_idx,
                labels=labels,
                blocks=blocks,
                warning=row_warning,
            )
        )

    if not rows:
        raise ValueError(
            "Could not detect any schema-defining category rows above key-feature row."
        )

    return key_feature_row_idx, rows, warnings


def extract_findings(df: pd.DataFrame, *, key_feature_row_idx: int) -> list[str]:
    findings: list[str] = []
    for row_idx in range(key_feature_row_idx + 1, df.shape[0]):
        finding = normalize_cell(df.iat[row_idx, 0])
        if finding:
            findings.append(finding)

    if not findings:
        raise ValueError("No findings detected below key-feature row in column 0.")

    return findings


def _coerce_numeric(value: object) -> float | None:
    text = normalize_cell(value)
    if not text:
        return None
    try:
        out = float(text)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return out


def category_spans_from_label_row(
    df: pd.DataFrame,
    *,
    category_row_idx: int,
) -> list[CategorySpan]:
    row = df.iloc[category_row_idx]
    starts: list[int] = []
    labels: list[str] = []
    for col_idx in range(1, df.shape[1]):
        label = normalize_cell(row.iloc[col_idx], collapse_internal=True)
        if not label:
            continue
        starts.append(col_idx)
        labels.append(label)

    if len(starts) < 2:
        raise ValueError("Need at least two category labels in schema row to infer category spans.")

    # Use next label start for all interior spans.
    # For the terminal span, use the immediately previous width to avoid allowing
    # the last category to absorb trailing workbook totals.
    spans: list[CategorySpan] = []
    for idx, (start_col, label) in enumerate(zip(starts, labels, strict=True)):
        if idx + 1 < len(starts):
            end_col = starts[idx + 1]
        else:
            if len(starts) >= 2:
                prev_width = starts[-1] - starts[-2]
            else:
                prev_width = 1
            if prev_width <= 0:
                prev_width = 1
            end_col = min(df.shape[1], start_col + prev_width)
        if end_col <= start_col:
            end_col = min(df.shape[1], start_col + 1)

        spans.append(
            CategorySpan(
                category_order=idx + 1,
                label=label,
                start_col=start_col,
                end_col=end_col,
            )
        )

    return spans


def infer_prior_row_idx(
    df: pd.DataFrame,
    *,
    schema_row_idx: int,
    key_feature_row_idx: int,
    min_numeric_cells: int = 2,
) -> int:
    if key_feature_row_idx <= schema_row_idx + 1:
        raise ValueError(
            "No rows exist between schema row and key-feature row for prior extraction."
        )

    for row_idx in range(key_feature_row_idx - 1, schema_row_idx, -1):
        numeric_count = 0
        for col_idx in range(1, df.shape[1]):
            if _coerce_numeric(df.iat[row_idx, col_idx]) is not None:
                numeric_count += 1
        if numeric_count >= min_numeric_cells:
            return row_idx

    raise ValueError(
        "Could not infer prior row: no numeric-dense row detected between "
        "schema row and key-feature row."
    )


def extract_schema_priors(
    df: pd.DataFrame,
    *,
    schema_row_idx: int,
    key_feature_row_idx: int,
    min_numeric_cells: int = 2,
) -> SchemaPriors:
    spans = category_spans_from_label_row(df, category_row_idx=schema_row_idx)
    prior_row_idx = infer_prior_row_idx(
        df,
        schema_row_idx=schema_row_idx,
        key_feature_row_idx=key_feature_row_idx,
        min_numeric_cells=max(min_numeric_cells, min(2, len(spans))),
    )

    # Last-span guardrail: if the prior row has numeric values in unlabeled cells
    # to the right of the final category start, treat those as trailing totals and
    # clip the last category span before the first such column.
    if spans:
        last = spans[-1]
        clipped_end = last.end_col
        for col_idx in range(last.start_col + 1, last.end_col):
            has_label = normalize_cell(df.iat[schema_row_idx, col_idx], collapse_internal=True)
            has_numeric = _coerce_numeric(df.iat[prior_row_idx, col_idx]) is not None
            if not has_label and has_numeric:
                clipped_end = col_idx
                break
        if clipped_end <= last.start_col:
            clipped_end = min(df.shape[1], last.start_col + 1)
        spans = [
            *spans[:-1],
            CategorySpan(
                category_order=last.category_order,
                label=last.label,
                start_col=last.start_col,
                end_col=clipped_end,
            ),
        ]

    priors_raw: list[float] = []
    for span in spans:
        values: list[float] = []
        for col_idx in range(span.start_col, span.end_col):
            numeric = _coerce_numeric(df.iat[prior_row_idx, col_idx])
            if numeric is None:
                continue
            values.append(numeric)
        priors_raw.append(float(sum(values)))

    prior_vector_sum_raw = float(sum(priors_raw))
    if not math.isfinite(prior_vector_sum_raw) or prior_vector_sum_raw <= 0:
        raise ValueError(
            "Prior vector sum must be positive and finite, got "
            f"{prior_vector_sum_raw!r} at row {prior_row_idx}."
        )

    priors_normalized = [float(value / prior_vector_sum_raw) for value in priors_raw]
    return SchemaPriors(
        prior_row_idx=prior_row_idx,
        prior_vector_sum_raw=prior_vector_sum_raw,
        spans=spans,
        priors_raw=priors_raw,
        priors_normalized=priors_normalized,
    )


def sheet_name_for_schema(*, order: int, row_idx: int, n_categories: int) -> str:
    name = f"s{order:02d}_r{row_idx:02d}_{n_categories}cat"
    return name[:31]


def build_one_vs_rest_sheet(*, categories: list[str], findings: list[str]) -> pd.DataFrame:
    if len(categories) < 2:
        raise ValueError("At least two categories are required for one-vs-rest sheet generation.")
    if not findings:
        raise ValueError("At least one finding is required for one-vs-rest sheet generation.")

    df = pd.DataFrame(
        "",
        index=range(len(findings) + 1),
        columns=range(len(categories) + 1),
        dtype="object",
    )

    df.iat[0, 0] = "Diagnosis:"
    for col_idx, label in enumerate(categories, start=1):
        df.iat[0, col_idx] = label

    for row_idx, finding in enumerate(findings, start=1):
        df.iat[row_idx, 0] = finding

    return df


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()
