from __future__ import annotations

import pandas as pd
import pytest

from dx_chat_entropy.lr_differential_inputs import (
    build_pair_sheet,
    collapse_internal_whitespace,
    exemplars_for_category,
    find_category_row,
    iter_category_pairs,
    normalize_cell,
    parse_matrix_sheet,
)


def test_exemplar_parsing_from_parenthetical_examples() -> None:
    category = "Cardiac ischemic (e.g. ACS, stable angina, coronary vasospasm)"
    exemplars = exemplars_for_category(
        category,
        strategy="parse_parenthetical",
        max_exemplars=4,
    )
    assert exemplars == ["ACS", "stable angina", "coronary vasospasm", ""]


def test_exemplar_fallback_to_category_label() -> None:
    category = "Shingles"
    exemplars = exemplars_for_category(
        category,
        strategy="parse_parenthetical",
        max_exemplars=3,
    )
    assert exemplars == ["Shingles", "", ""]


def test_parse_matrix_simple_profile() -> None:
    df = pd.DataFrame(
        [
            [None, "Cat A (e.g. A1, A2)", None, "Cat B (e.g. B1, B2)", None],
            [None, 0.4, None, 0.6, None],
            ["Key feature", None, None, None, None],
            ["Finding 1", None, None, None, None],
            ["", None, None, None, None],
            ["Finding 2", None, None, None, None],
        ]
    )

    parsed = parse_matrix_sheet(
        df,
        parser_profile="matrix_simple",
        key_feature_pattern=r"^key feature",
        expected_category_count=2,
    )

    assert parsed.category_row_idx == 0
    assert parsed.key_feature_row_idx == 2
    assert parsed.findings_start_row_idx == 3
    assert parsed.categories == ["Cat A (e.g. A1, A2)", "Cat B (e.g. B1, B2)"]
    assert parsed.findings == ["Finding 1", "Finding 2"]
    assert parsed.warnings == []


def test_parse_matrix_with_preamble_profile_detects_deep_category_row() -> None:
    df = pd.DataFrame(
        [
            [None, "Tier 1", None, "Tier 1", None, "Tier 1", None],
            [None, "Tier 2", None, "Tier 2", None, "Tier 2", None],
            [None, "Cat A", None, "Cat B", None, "Cat C", None],
            [None, 0.3, None, 0.4, None, 0.3, None],
            ["Key feature", None, None, None, None, None, None],
            ["Finding 1", None, None, None, None, None, None],
        ]
    )

    category_row_idx = find_category_row(
        df,
        key_feature_row_idx=4,
        parser_profile="matrix_with_preamble",
    )
    assert category_row_idx == 2


def test_parse_matrix_fails_for_category_mismatch_by_default() -> None:
    df = pd.DataFrame(
        [
            [None, "Cat A", None, "Cat B", None, "Cat C"],
            [None, 0.3, None, 0.3, None, 0.4],
            ["Key feature", None, None, None, None, None],
            ["Finding 1", None, None, None, None, None],
        ]
    )
    with pytest.raises(ValueError, match="expected=2, observed=3"):
        parse_matrix_sheet(
            df,
            parser_profile="matrix_simple",
            expected_category_count=2,
        )


def test_parse_matrix_can_override_category_mismatch_failure() -> None:
    df = pd.DataFrame(
        [
            [None, "Cat A", None, "Cat B", None, "Cat C"],
            [None, 0.3, None, 0.3, None, 0.4],
            ["Key feature", None, None, None, None, None],
            ["Finding 1", None, None, None, None, None],
        ]
    )
    parsed = parse_matrix_sheet(
        df,
        parser_profile="matrix_simple",
        expected_category_count=2,
        allow_category_count_mismatch=True,
    )
    assert len(parsed.categories) == 3
    assert parsed.warnings


def test_normalize_cell_and_whitespace_helpers() -> None:
    assert normalize_cell(float("nan")) == ""
    assert normalize_cell("  acute   coronary  syndrome  ", collapse_internal=True) == (
        "acute coronary syndrome"
    )
    assert collapse_internal_whitespace("a \t  b\nc") == "a b c"


def test_pair_sheet_schema_and_pair_count() -> None:
    pairs = iter_category_pairs(["Cat A", "Cat B", "Cat C"], pair_scope="all")
    assert pairs == [("Cat A", "Cat B"), ("Cat A", "Cat C"), ("Cat B", "Cat C")]

    df = build_pair_sheet(
        left_category="Cat A",
        right_category="Cat B",
        left_exemplars=["A1", "A2", "", ""],
        right_exemplars=["B1", "B2", "", ""],
        findings=["Finding 1", "Finding 2"],
        width_per_category=4,
    )

    row0 = df.iloc[0].ffill()
    assert sorted(pd.unique(row0.dropna()).tolist()) == ["Cat A", "Cat B"]
    assert df.iat[1, 0] == "A1"
    assert df.iat[1, 4] == "B1"
    assert df.iat[2, 0] == "Finding 1"
    assert df.iat[3, 0] == "Finding 2"
