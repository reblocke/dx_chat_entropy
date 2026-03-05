from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from dx_chat_entropy.lr_differential_inputs import (
    build_pair_sheet,
    exemplars_for_category,
    iter_category_pairs,
    pair_filename,
    parse_matrix_sheet,
)
from dx_chat_entropy.paths import find_repo_root


@dataclass(frozen=True)
class ScenarioConfig:
    scenario_id: str
    source_workbook: str
    sheet_name: str
    parser_profile: str
    key_feature_token: str
    pair_scope: str
    expected_category_count: int | None
    exclude_categories: list[str]
    exemplar_strategy: str
    max_exemplars_per_category: int


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1_048_576)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def load_config(config_path: Path) -> list[ScenarioConfig]:
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    scenarios = raw.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError("Config must define a non-empty `scenarios` list.")

    configs: list[ScenarioConfig] = []
    for item in scenarios:
        if not isinstance(item, dict):
            raise ValueError("Each scenario entry must be a mapping.")
        configs.append(
            ScenarioConfig(
                scenario_id=str(item["scenario_id"]),
                source_workbook=str(item["source_workbook"]),
                sheet_name=str(item["sheet_name"]),
                parser_profile=str(item.get("parser_profile", "matrix_simple")),
                key_feature_token=str(item.get("key_feature_token", r"^key feature")),
                pair_scope=str(item.get("pair_scope", "all")),
                expected_category_count=(
                    int(item["expected_category_count"])
                    if item.get("expected_category_count") is not None
                    else None
                ),
                exclude_categories=[str(x) for x in item.get("exclude_categories", [])],
                exemplar_strategy=str(item.get("exemplar_strategy", "parse_parenthetical")),
                max_exemplars_per_category=int(item.get("max_exemplars_per_category", 4)),
            )
        )
    return configs


def _as_repo_relative(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def build_outputs(
    *,
    repo_root: Path,
    config_path: Path,
    dry_run: bool,
) -> tuple[int, list[str]]:
    configs = load_config(config_path)

    processed_root = repo_root / "data" / "processed" / "lr_differential"
    manifests_dir = processed_root / "manifests"
    inputs_root = processed_root / "inputs"
    outputs_root = processed_root / "outputs"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    inputs_root.mkdir(parents=True, exist_ok=True)
    outputs_root.mkdir(parents=True, exist_ok=True)

    all_rows: list[dict[str, Any]] = []
    all_warnings: list[str] = []
    scenario_manifest: list[dict[str, Any]] = []

    for scenario in configs:
        source_path = (repo_root / scenario.source_workbook).resolve()
        if not source_path.exists():
            raise FileNotFoundError(
                f"Scenario {scenario.scenario_id}: source workbook missing: {source_path}"
            )

        sheet_df = pd.read_excel(source_path, sheet_name=scenario.sheet_name, header=None)
        parsed = parse_matrix_sheet(
            sheet_df,
            parser_profile=scenario.parser_profile,
            key_feature_pattern=scenario.key_feature_token,
            expected_category_count=scenario.expected_category_count,
        )

        categories = [c for c in parsed.categories if c not in set(scenario.exclude_categories)]
        missing_exclusions = sorted(set(scenario.exclude_categories) - set(parsed.categories))
        scenario_warnings = [*parsed.warnings]
        for missing in missing_exclusions:
            scenario_warnings.append(
                "Scenario "
                f"{scenario.scenario_id}: exclude_categories contains unknown label: {missing}"
            )

        pairs = iter_category_pairs(categories, pair_scope=scenario.pair_scope)
        scenario_input_dir = inputs_root / scenario.scenario_id
        scenario_output_dir = outputs_root / scenario.scenario_id
        scenario_input_dir.mkdir(parents=True, exist_ok=True)
        scenario_output_dir.mkdir(parents=True, exist_ok=True)

        for pair_idx, (left, right) in enumerate(pairs, start=1):
            filename = pair_filename(pair_idx, left, right)
            input_path = scenario_input_dir / filename
            output_path = scenario_output_dir / filename.replace(".xlsx", "_filled.xlsx")

            left_examples = exemplars_for_category(
                left,
                strategy=scenario.exemplar_strategy,
                max_exemplars=scenario.max_exemplars_per_category,
            )
            right_examples = exemplars_for_category(
                right,
                strategy=scenario.exemplar_strategy,
                max_exemplars=scenario.max_exemplars_per_category,
            )

            pair_df = build_pair_sheet(
                left_category=left,
                right_category=right,
                left_exemplars=left_examples,
                right_exemplars=right_examples,
                findings=parsed.findings,
                width_per_category=scenario.max_exemplars_per_category,
            )
            if not dry_run:
                pair_df.to_excel(input_path, index=False, header=False)

            all_rows.append(
                {
                    "scenario_id": scenario.scenario_id,
                    "pair_index": pair_idx,
                    "source_workbook": _as_repo_relative(source_path, repo_root),
                    "source_sheet": scenario.sheet_name,
                    "parser_profile": scenario.parser_profile,
                    "category_left": left,
                    "category_right": right,
                    "findings_count": len(parsed.findings),
                    "input_workbook": _as_repo_relative(input_path, repo_root),
                    "output_workbook": _as_repo_relative(output_path, repo_root),
                }
            )

        for warning in scenario_warnings:
            message = f"WARNING: {scenario.scenario_id}: {warning}"
            all_warnings.append(message)
            print(message)

        scenario_manifest.append(
            {
                "scenario_id": scenario.scenario_id,
                "source_workbook": _as_repo_relative(source_path, repo_root),
                "source_sheet": scenario.sheet_name,
                "source_sha256": sha256_file(source_path),
                "category_row_idx": parsed.category_row_idx,
                "key_feature_row_idx": parsed.key_feature_row_idx,
                "findings_count": len(parsed.findings),
                "observed_category_count": len(parsed.categories),
                "expected_category_count": scenario.expected_category_count,
                "pair_count": len(pairs),
                "warnings": scenario_warnings,
            }
        )

    pairs_manifest_path = manifests_dir / "pairs_manifest.csv"
    pairs_df = pd.DataFrame(all_rows)
    if not pairs_df.empty:
        pairs_df = pairs_df.sort_values(["scenario_id", "pair_index"]).reset_index(drop=True)
    if not dry_run:
        pairs_df.to_csv(pairs_manifest_path, index=False)
    pairs_manifest_hash = (
        sha256_file(pairs_manifest_path) if not dry_run and pairs_manifest_path.exists() else None
    )

    run_manifest = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "config_path": _as_repo_relative(config_path.resolve(), repo_root),
        "config_sha256": sha256_file(config_path),
        "pairs_manifest_path": _as_repo_relative(pairs_manifest_path, repo_root),
        "pairs_manifest_sha256": pairs_manifest_hash,
        "scenario_count": len(configs),
        "pair_count": len(all_rows),
        "dry_run": dry_run,
        "scenarios": scenario_manifest,
        "warnings": all_warnings,
    }

    run_manifest_path = manifests_dir / "run_manifest.json"
    if not dry_run:
        run_manifest_path.write_text(
            json.dumps(run_manifest, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    print(f"Scenarios processed: {len(configs)}")
    print(f"Pairs generated: {len(all_rows)}")
    print(f"Pairs manifest: {pairs_manifest_path}")
    print(f"Run manifest: {run_manifest_path}")
    return len(all_rows), all_warnings


def main() -> int:
    repo_root = find_repo_root(Path(__file__).resolve())
    parser = argparse.ArgumentParser(
        description=(
            "Build pairwise differential-LR input workbooks from canonical LR-matrix sources."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=repo_root / "config" / "lr_differential_scenarios.yaml",
        help="YAML config path.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and plan outputs without writing generated workbooks/manifests.",
    )
    args = parser.parse_args()

    config_path = args.config.resolve()
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    build_outputs(repo_root=repo_root, config_path=config_path, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
