from __future__ import annotations

import pandas as pd
import pytest

from dx_chat_entropy.lr_one_vs_rest_inputs import (
    build_one_vs_rest_sheet,
    category_spans_from_label_row,
    discover_schema_rows,
    extract_findings,
    extract_schema_priors,
    infer_prior_row_idx,
    sheet_name_for_schema,
)


def test_discover_schema_rows_excludes_numeric_and_dedupes() -> None:
    df = pd.DataFrame(
        [
            [None, "Tier A", None, "Tier B", None],
            [None, "Cat A", None, "Cat B", None],
            [None, "Cat A", None, "Cat B", None],
            [None, 0.4, None, 0.6, None],
            ["Key feature", None, None, None, None],
            ["Finding 1", None, None, None, None],
            ["Finding 2", None, None, None, None],
        ]
    )

    key_idx, schema_rows, warnings = discover_schema_rows(
        df,
        key_feature_pattern=r"^key feature",
        expected_category_count=2,
    )

    assert key_idx == 4
    assert [row.row_idx for row in schema_rows] == [0, 1]
    assert [row.labels for row in schema_rows] == [["Tier A", "Tier B"], ["Cat A", "Cat B"]]
    assert warnings == []


def test_discover_schema_rows_fails_for_mismatch_by_default() -> None:
    df = pd.DataFrame(
        [
            [None, "Cat A", None, "Cat B", None, "Cat C"],
            ["Key feature", None, None, None, None, None],
            ["Finding 1", None, None, None, None, None],
        ]
    )

    with pytest.raises(ValueError, match="expected=2, observed=3"):
        discover_schema_rows(
            df,
            key_feature_pattern=r"^key feature",
            expected_category_count=2,
        )


def test_discover_schema_rows_can_override_mismatch_failure() -> None:
    df = pd.DataFrame(
        [
            [None, "Cat A", None, "Cat B", None, "Cat C"],
            ["Key feature", None, None, None, None, None],
            ["Finding 1", None, None, None, None, None],
        ]
    )

    _key_idx, schema_rows, warnings = discover_schema_rows(
        df,
        key_feature_pattern=r"^key feature",
        expected_category_count=2,
        allow_category_count_mismatch=True,
    )

    assert len(schema_rows) == 1
    assert schema_rows[0].labels == ["Cat A", "Cat B", "Cat C"]
    assert warnings


def test_extract_findings_and_sheet_schema_contract() -> None:
    df = pd.DataFrame(
        [
            [None, "Cat A", None, "Cat B", None],
            [None, 0.5, None, 0.5, None],
            ["Key feature", None, None, None, None],
            ["Finding 1", None, None, None, None],
            ["", None, None, None, None],
            ["Finding 2", None, None, None, None],
        ]
    )

    key_idx, schema_rows, _warnings = discover_schema_rows(df, expected_category_count=2)
    assert key_idx == 2

    findings = extract_findings(df, key_feature_row_idx=key_idx)
    assert findings == ["Finding 1", "Finding 2"]

    sheet = build_one_vs_rest_sheet(categories=schema_rows[0].labels, findings=findings)
    assert sheet.iat[0, 0] == "Diagnosis:"
    assert sheet.iat[0, 1] == "Cat A"
    assert sheet.iat[0, 2] == "Cat B"
    assert sheet.iat[1, 0] == "Finding 1"
    assert sheet.iat[2, 0] == "Finding 2"


def test_sheet_name_for_schema_is_stable() -> None:
    assert sheet_name_for_schema(order=1, row_idx=0, n_categories=8) == "s01_r00_8cat"


def test_extract_schema_priors_ignores_trailing_total_column() -> None:
    df = pd.DataFrame(
        [
            [None, "Cat A", "Cat B", "Cat C", None],
            [None, 0.5, 0.3, 0.2, 1.0],
            ["Key feature", None, None, None, None],
            ["Finding 1", None, None, None, None],
        ]
    )

    priors = extract_schema_priors(
        df,
        schema_row_idx=0,
        key_feature_row_idx=2,
    )

    assert priors.prior_row_idx == 1
    assert [span.label for span in priors.spans] == ["Cat A", "Cat B", "Cat C"]
    assert priors.priors_raw == [0.5, 0.3, 0.2]
    assert pytest.approx(sum(priors.priors_normalized), rel=0, abs=1e-12) == 1.0
    assert pytest.approx(priors.prior_vector_sum_raw, rel=0, abs=1e-12) == 1.0


def test_extract_schema_priors_preserves_order_and_normalizes_raw_sum() -> None:
    df = pd.DataFrame(
        [
            [None, "Dx 1", "Dx 2", "Dx 3", None],
            [None, 0.2, 0.25, 0.545, 0.995],
            ["Key feature", None, None, None, None],
            ["Finding 1", None, None, None, None],
        ]
    )

    priors = extract_schema_priors(
        df,
        schema_row_idx=0,
        key_feature_row_idx=2,
    )

    assert [span.label for span in priors.spans] == ["Dx 1", "Dx 2", "Dx 3"]
    assert priors.priors_raw == [0.2, 0.25, 0.545]
    assert pytest.approx(priors.prior_vector_sum_raw, rel=0, abs=1e-12) == 0.995
    assert pytest.approx(sum(priors.priors_normalized), rel=0, abs=1e-12) == 1.0
    assert priors.priors_normalized[0] < priors.priors_normalized[1] < priors.priors_normalized[2]


def test_infer_prior_row_idx_uses_last_numeric_dense_row() -> None:
    df = pd.DataFrame(
        [
            [None, "Cat A", "Cat B", None],
            [None, 0.4, 0.6, None],
            [None, 0.45, 0.55, None],
            ["Key feature", None, None, None],
        ]
    )

    prior_row = infer_prior_row_idx(df, schema_row_idx=0, key_feature_row_idx=3)
    assert prior_row == 2


def test_category_spans_from_label_row_uses_true_label_starts() -> None:
    df = pd.DataFrame(
        [
            [None, "A", None, None, "B", None, "C", None],
            [None, 0.3, None, None, 0.4, None, 0.3, 1.0],
            ["Key feature", None, None, None, None, None, None, None],
        ]
    )

    spans = category_spans_from_label_row(df, category_row_idx=0)
    assert [(s.label, s.start_col, s.end_col) for s in spans] == [
        ("A", 1, 4),
        ("B", 4, 6),
        ("C", 6, 8),
    ]


def test_extract_schema_priors_clips_terminal_unlabeled_numeric_total() -> None:
    df = pd.DataFrame(
        [
            [None, "A", None, None, "B", None, "C", None],
            [None, 0.3, None, None, 0.4, None, 0.3, 1.0],
            ["Key feature", None, None, None, None, None, None, None],
            ["Finding 1", None, None, None, None, None, None, None],
        ]
    )

    priors = extract_schema_priors(
        df,
        schema_row_idx=0,
        key_feature_row_idx=2,
    )
    assert priors.priors_raw == [0.3, 0.4, 0.3]
    assert pytest.approx(sum(priors.priors_normalized), rel=0, abs=1e-12) == 1.0
