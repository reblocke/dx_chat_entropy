from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import combinations

import pandas as pd

DEFAULT_KEY_FEATURE_PATTERN = r"^key feature"
PARENTHETICAL_RE = re.compile(r"\(([^)]*)\)")
EG_PREFIX_RE = re.compile(r"^\s*(e\.?\s*g\.?|eg)\.?\s*:?\s*", re.IGNORECASE)
INTERNAL_WS_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class CategoryBlock:
    label: str
    start_col: int
    end_col: int


@dataclass(frozen=True)
class ParsedMatrix:
    category_row_idx: int
    key_feature_row_idx: int
    findings_start_row_idx: int
    categories: list[str]
    category_blocks: list[CategoryBlock]
    findings: list[str]
    warnings: list[str]


def collapse_internal_whitespace(text: str) -> str:
    return INTERNAL_WS_RE.sub(" ", text).strip()


def normalize_cell(value: object, *, collapse_internal: bool = False) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if not text:
        return ""
    if collapse_internal:
        return collapse_internal_whitespace(text)
    return text


def extract_parenthetical_exemplars(category_label: str) -> list[str]:
    match = PARENTHETICAL_RE.search(category_label)
    if not match:
        return []

    inner = EG_PREFIX_RE.sub("", match.group(1)).strip()
    if not inner:
        return []

    exemplars = [part.strip() for part in re.split(r"[;,]", inner)]
    return [item for item in exemplars if item]


def exemplars_for_category(
    category_label: str,
    *,
    strategy: str,
    max_exemplars: int,
) -> list[str]:
    if max_exemplars < 1:
        raise ValueError("max_exemplars must be >= 1")

    values: list[str]
    if strategy == "parse_parenthetical":
        values = extract_parenthetical_exemplars(category_label)
    else:
        raise ValueError(f"Unsupported exemplar strategy: {strategy}")

    if not values:
        values = [category_label]

    values = values[:max_exemplars]
    if len(values) < max_exemplars:
        values.extend([""] * (max_exemplars - len(values)))
    return values


def find_key_feature_row(df: pd.DataFrame, key_feature_pattern: str) -> int:
    regex = re.compile(key_feature_pattern, flags=re.IGNORECASE)
    for row_idx, raw in enumerate(df.iloc[:, 0].tolist()):
        if regex.search(normalize_cell(raw)):
            return row_idx
    raise ValueError(
        f"Could not find key-feature row in column 0 using pattern {key_feature_pattern!r}."
    )


def _row_categories(df: pd.DataFrame, row_idx: int) -> list[str]:
    row = df.iloc[row_idx].ffill()
    labels: list[str] = []
    for col_idx in range(1, len(row)):
        label = normalize_cell(row.iloc[col_idx], collapse_internal=True)
        if label and label not in labels:
            labels.append(label)
    return labels


def find_category_row(df: pd.DataFrame, *, key_feature_row_idx: int, parser_profile: str) -> int:
    if parser_profile == "matrix_simple":
        return 0

    if parser_profile == "matrix_with_preamble":
        best_row: int | None = None
        best_score = 0

        for row_idx in range(0, key_feature_row_idx):
            labels = _row_categories(df, row_idx)
            if len(labels) < 2:
                continue
            if all(label.lower().startswith("tier ") for label in labels):
                continue

            score = len(labels)
            if score > best_score:
                best_score = score
                best_row = row_idx

        if best_row is None:
            raise ValueError(
                "Could not infer category row for parser_profile='matrix_with_preamble'."
            )
        return best_row

    raise ValueError(f"Unsupported parser_profile: {parser_profile}")


def extract_category_blocks(df: pd.DataFrame, *, category_row_idx: int) -> list[CategoryBlock]:
    categories_row = df.iloc[category_row_idx].ffill()
    blocks: list[CategoryBlock] = []

    current_label: str | None = None
    start_col: int | None = None
    for col_idx in range(1, len(categories_row)):
        label = normalize_cell(categories_row.iloc[col_idx], collapse_internal=True)
        if not label:
            continue
        if current_label is None:
            current_label = label
            start_col = col_idx
            continue
        if label != current_label:
            assert start_col is not None
            blocks.append(CategoryBlock(label=current_label, start_col=start_col, end_col=col_idx))
            current_label = label
            start_col = col_idx

    if current_label is not None and start_col is not None:
        blocks.append(
            CategoryBlock(
                label=current_label,
                start_col=start_col,
                end_col=len(categories_row),
            )
        )

    if not blocks:
        raise ValueError("No category blocks detected in category row.")
    return blocks


def parse_matrix_sheet(
    df: pd.DataFrame,
    *,
    parser_profile: str,
    key_feature_pattern: str = DEFAULT_KEY_FEATURE_PATTERN,
    expected_category_count: int | None = None,
    allow_category_count_mismatch: bool = False,
) -> ParsedMatrix:
    key_feature_row_idx = find_key_feature_row(df, key_feature_pattern)
    category_row_idx = find_category_row(
        df, key_feature_row_idx=key_feature_row_idx, parser_profile=parser_profile
    )
    findings_start_row_idx = key_feature_row_idx + 1

    category_blocks = extract_category_blocks(df, category_row_idx=category_row_idx)
    categories = [block.label for block in category_blocks]

    findings: list[str] = []
    for row_idx in range(findings_start_row_idx, df.shape[0]):
        finding = normalize_cell(df.iat[row_idx, 0])
        if finding:
            findings.append(finding)

    warnings: list[str] = []
    if expected_category_count is not None and len(categories) != expected_category_count:
        message = (
            "Detected category count does not match expected count: "
            f"expected={expected_category_count}, observed={len(categories)}"
        )
        if allow_category_count_mismatch:
            warnings.append(message)
        else:
            raise ValueError(f"{message}. Set allow_category_count_mismatch=True to override.")

    return ParsedMatrix(
        category_row_idx=category_row_idx,
        key_feature_row_idx=key_feature_row_idx,
        findings_start_row_idx=findings_start_row_idx,
        categories=categories,
        category_blocks=category_blocks,
        findings=findings,
        warnings=warnings,
    )


def build_pair_sheet(
    *,
    left_category: str,
    right_category: str,
    left_exemplars: list[str],
    right_exemplars: list[str],
    findings: list[str],
    width_per_category: int,
) -> pd.DataFrame:
    if width_per_category < 1:
        raise ValueError("width_per_category must be >= 1")

    total_cols = width_per_category * 2
    total_rows = len(findings) + 2
    rows: list[list[object]] = [[None] * total_cols for _ in range(total_rows)]

    rows[0][0] = left_category
    rows[0][width_per_category] = right_category

    for idx, item in enumerate(left_exemplars[:width_per_category]):
        rows[1][idx] = item
    for idx, item in enumerate(right_exemplars[:width_per_category]):
        rows[1][width_per_category + idx] = item

    for idx, finding in enumerate(findings, start=2):
        rows[idx][0] = finding

    return pd.DataFrame(rows)


def iter_category_pairs(
    categories: Iterable[str],
    *,
    pair_scope: str,
) -> list[tuple[str, str]]:
    unique = list(dict.fromkeys(categories))
    if pair_scope != "all":
        raise ValueError(f"Unsupported pair_scope: {pair_scope}")
    return list(combinations(unique, 2))


def slugify(text: str, max_len: int = 48) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    slug = re.sub(r"_+", "_", slug)
    slug = slug[:max_len].strip("_")
    return slug or "category"


def pair_filename(pair_index: int, left_category: str, right_category: str) -> str:
    left_slug = slugify(left_category)
    right_slug = slugify(right_category)
    return f"{pair_index:03d}__{left_slug}__vs__{right_slug}.xlsx"
