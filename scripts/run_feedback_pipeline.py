from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

DEFAULT_CONFIG = Path("config/feedback_generation.yaml")
DEFAULT_RUNS_ROOT = Path("artifacts/feedback_sheets/runs")
LATEST_SMOKE_FILENAME = "latest_smoke.json"


def find_repo_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise FileNotFoundError("Could not locate repository root (missing pyproject.toml)")


def _repo_path(repo_root: Path, value: Path) -> Path:
    return value.resolve() if value.is_absolute() else (repo_root / value).resolve()


def _safe_run_id(value: str) -> str:
    if not value or Path(value).name != value or value in {".", ".."}:
        raise ValueError("run_id must be a non-empty single path component")
    return value


def _summary_dict(summary: object) -> dict[str, object]:
    if hasattr(summary, "to_dict"):
        value = summary.to_dict()  # type: ignore[attr-defined]
    elif dataclasses.is_dataclass(summary):
        value = dataclasses.asdict(summary)
    elif isinstance(summary, Mapping):
        value = dict(summary)
    else:
        value = {"result": str(summary)}
    if not isinstance(value, dict):
        raise TypeError("Pipeline summary must serialize to a JSON object")
    return value


def _print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str))


def _add_config_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    parser.add_argument(
        "--category-mode",
        choices=("only_overall", "all"),
        default=None,
        help="Default combined category (110 requests) or all six categories (660 requests).",
    )
    parser.add_argument("--model-profile", default=None)


def _add_run_selector(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run-id")
    group.add_argument("--latest-smoke", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Restartable, manifest-first feedback-generation pipeline."
    )
    parser.add_argument("--repo-root", type=Path, default=None)
    subparsers = parser.add_subparsers(dest="command", required=True)

    manifest = subparsers.add_parser(
        "manifest", help="Create or validate a deterministic request manifest (no network)."
    )
    _add_config_arguments(manifest)

    run = subparsers.add_parser("run", help="Execute or resume provider requests.")
    _add_config_arguments(run)
    run.add_argument("--run-id", default=None)
    run.add_argument(
        "--resume-mode",
        choices=("skip_passing", "repair_invalid", "recompute"),
        default="skip_passing",
    )
    run.add_argument("--max-workers", type=int, default=None)
    run.add_argument("--max-attempts", type=int, default=None)
    run.add_argument("--request-timeout-seconds", type=float, default=None)
    run.add_argument("--surface", action="append", dest="surfaces")
    run.add_argument("--category", action="append", dest="categories")
    run.add_argument("--diagnosis", action="append", dest="diagnoses")
    run.add_argument("--request-id", action="append", dest="request_ids")
    run.add_argument("--max-requests", type=int, default=None)
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan and reconcile selection without creating a provider client.",
    )

    materialize = subparsers.add_parser(
        "materialize", help="Build deterministic workbooks from stored validated responses."
    )
    _add_run_selector(materialize)
    materialize.add_argument("--allow-partial", action="store_true")

    audit = subparsers.add_parser("audit", help="Audit a run without network access.")
    _add_run_selector(audit)

    smoke = subparsers.add_parser(
        "smoke", help="Run deterministic fake-provider concurrency and resume checks."
    )
    _add_config_arguments(smoke)
    smoke.add_argument("--latency-seconds", type=float, default=0.01)

    return parser


def _load_modules(repo_root: Path) -> dict[str, Any]:
    src_path = repo_root / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))

    from dx_chat_entropy.feedback.audit import audit_feedback_run
    from dx_chat_entropy.feedback.config import load_feedback_config
    from dx_chat_entropy.feedback.manifest import build_or_load_manifest
    from dx_chat_entropy.feedback.runtime import (
        FakeProviderAdapter,
        OpenAIProviderAdapter,
        execute_feedback_run,
    )
    from dx_chat_entropy.feedback.storage import atomic_write_json, create_recompute_run
    from dx_chat_entropy.feedback.workbooks import materialize_workbooks

    return {
        "audit_feedback_run": audit_feedback_run,
        "load_feedback_config": load_feedback_config,
        "build_or_load_manifest": build_or_load_manifest,
        "FakeProviderAdapter": FakeProviderAdapter,
        "OpenAIProviderAdapter": OpenAIProviderAdapter,
        "execute_feedback_run": execute_feedback_run,
        "atomic_write_json": atomic_write_json,
        "create_recompute_run": create_recompute_run,
        "materialize_workbooks": materialize_workbooks,
    }


def _resolve_run_dir(runs_root: Path, *, run_id: str | None, latest_smoke: bool) -> Path:
    if latest_smoke:
        pointer_path = runs_root / LATEST_SMOKE_FILENAME
        try:
            pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise FileNotFoundError(f"Latest-smoke pointer does not exist: {pointer_path}") from exc
        if not isinstance(pointer, Mapping) or not isinstance(pointer.get("run_id"), str):
            raise ValueError(f"Invalid latest-smoke pointer: {pointer_path}")
        run_id = str(pointer["run_id"])
    if run_id is None:
        raise ValueError("Select a run with --run-id or --latest-smoke")
    run_dir = runs_root / _safe_run_id(run_id)
    if not run_dir.is_dir():
        raise FileNotFoundError(f"Feedback run directory does not exist: {run_dir}")
    return run_dir.resolve()


def _manifest_command(args: argparse.Namespace, repo_root: Path, modules: Mapping[str, Any]) -> int:
    config_path = _repo_path(repo_root, args.config)
    runs_root = _repo_path(repo_root, args.runs_root)
    config = modules["load_feedback_config"](config_path)
    build = modules["build_or_load_manifest"](
        config,
        output_root=runs_root,
        category_mode=args.category_mode,
        model_profile=args.model_profile,
    )
    _print_json(
        {
            "run_id": build.run_dir.name,
            "run_dir": str(build.run_dir),
            "request_count": len(build.requests),
            "manifest_sha256": build.metadata["manifest_sha256"],
            "run_fingerprint": build.metadata["run_fingerprint"],
        }
    )
    return 0


def _run_command(args: argparse.Namespace, repo_root: Path, modules: Mapping[str, Any]) -> int:
    config_path = _repo_path(repo_root, args.config)
    runs_root = _repo_path(repo_root, args.runs_root)
    config = modules["load_feedback_config"](config_path)
    if args.run_id:
        run_dir = _resolve_run_dir(runs_root, run_id=args.run_id, latest_smoke=False)
    else:
        build = modules["build_or_load_manifest"](
            config,
            output_root=runs_root,
            category_mode=args.category_mode,
            model_profile=args.model_profile,
        )
        run_dir = build.run_dir

    defaults = config.runtime_defaults
    timeout = (
        defaults.request_timeout_seconds
        if args.request_timeout_seconds is None
        else args.request_timeout_seconds
    )
    adapter = None
    if not args.dry_run:
        if os.environ.get("CONFIRM_PAID_RUN") != "1":
            raise RuntimeError(
                "Refusing paid run: set CONFIRM_PAID_RUN=1 after reviewing the request manifest"
            )
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY must be set for a real feedback run")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "The OpenAI SDK is required; run `uv sync --group notebooks`."
            ) from exc
        client = OpenAI(api_key=api_key, timeout=timeout, max_retries=0)
        adapter = modules["OpenAIProviderAdapter"](
            client=client,
            timeout_seconds=timeout,
        )

    summary = modules["execute_feedback_run"](
        run_dir,
        adapter,
        resume_mode=args.resume_mode,
        max_workers=defaults.max_workers if args.max_workers is None else args.max_workers,
        max_attempts=defaults.max_attempts if args.max_attempts is None else args.max_attempts,
        request_timeout_seconds=timeout,
        surfaces=args.surfaces,
        categories=args.categories,
        diagnoses=args.diagnoses,
        request_ids=args.request_ids,
        max_requests=args.max_requests,
        dry_run=args.dry_run,
        retry_initial_delay_seconds=defaults.retry_initial_delay_seconds,
        retry_max_delay_seconds=defaults.retry_max_delay_seconds,
        retry_jitter_fraction=defaults.retry_jitter_fraction,
    )
    value = _summary_dict(summary)
    _print_json(value)
    return int(getattr(summary, "exit_code", 0))


def _materialize_command(
    args: argparse.Namespace, repo_root: Path, modules: Mapping[str, Any]
) -> int:
    runs_root = _repo_path(repo_root, args.runs_root)
    run_dir = _resolve_run_dir(runs_root, run_id=args.run_id, latest_smoke=bool(args.latest_smoke))
    manifest = modules["materialize_workbooks"](
        run_dir,
        allow_partial=bool(args.allow_partial),
    )
    _print_json(
        {
            "run_id": manifest["run_id"],
            "partial": manifest["partial"],
            "workbook_count": len(manifest["workbooks"]),
            "workbook_manifest": str(run_dir / "workbook_manifest.json"),
        }
    )
    return 0


def _audit_command(args: argparse.Namespace, repo_root: Path, modules: Mapping[str, Any]) -> int:
    runs_root = _repo_path(repo_root, args.runs_root)
    run_dir = _resolve_run_dir(runs_root, run_id=args.run_id, latest_smoke=bool(args.latest_smoke))
    result = modules["audit_feedback_run"](run_dir)
    _print_json(result.to_dict())
    return 0 if result.passes else 1


def _smoke_command(args: argparse.Namespace, repo_root: Path, modules: Mapping[str, Any]) -> int:
    if args.latency_seconds <= 0:
        raise ValueError("--latency-seconds must be positive")
    config_path = _repo_path(repo_root, args.config)
    runs_root = _repo_path(repo_root, args.runs_root)
    config = modules["load_feedback_config"](config_path)
    base = modules["build_or_load_manifest"](
        config,
        output_root=runs_root,
        category_mode=args.category_mode,
        model_profile=args.model_profile,
    )
    defaults = config.runtime_defaults

    serial_dir = modules["create_recompute_run"](base.run_dir)
    serial_adapter = modules["FakeProviderAdapter"](delay_seconds=args.latency_seconds)
    serial_started = time.perf_counter()
    serial_result = modules["execute_feedback_run"](
        serial_dir,
        serial_adapter,
        resume_mode="skip_passing",
        max_workers=1,
        max_attempts=1,
        request_timeout_seconds=defaults.request_timeout_seconds,
        retry_initial_delay_seconds=defaults.retry_initial_delay_seconds,
        retry_max_delay_seconds=defaults.retry_max_delay_seconds,
        retry_jitter_fraction=defaults.retry_jitter_fraction,
    )
    serial_seconds = time.perf_counter() - serial_started

    concurrent_dir = modules["create_recompute_run"](base.run_dir)
    concurrent_requests = tuple(
        request
        for request in modules["build_or_load_manifest"](
            config,
            output_root=runs_root,
            category_mode=args.category_mode,
            model_profile=args.model_profile,
        ).requests
    )
    midpoint = concurrent_requests[len(concurrent_requests) // 2]
    concurrent_adapter = modules["FakeProviderAdapter"](
        failures={midpoint.request_id: [ValueError("synthetic_midpoint_failure")]},
        delay_seconds=args.latency_seconds,
    )
    concurrent_started = time.perf_counter()
    first_pass = modules["execute_feedback_run"](
        concurrent_dir,
        concurrent_adapter,
        resume_mode="skip_passing",
        max_workers=4,
        max_attempts=1,
        request_timeout_seconds=defaults.request_timeout_seconds,
        retry_initial_delay_seconds=defaults.retry_initial_delay_seconds,
        retry_max_delay_seconds=defaults.retry_max_delay_seconds,
        retry_jitter_fraction=defaults.retry_jitter_fraction,
    )
    repair_adapter = modules["FakeProviderAdapter"](delay_seconds=args.latency_seconds)
    repaired = modules["execute_feedback_run"](
        concurrent_dir,
        repair_adapter,
        resume_mode="repair_invalid",
        max_workers=4,
        max_attempts=defaults.max_attempts,
        request_timeout_seconds=defaults.request_timeout_seconds,
        retry_initial_delay_seconds=defaults.retry_initial_delay_seconds,
        retry_max_delay_seconds=defaults.retry_max_delay_seconds,
        retry_jitter_fraction=defaults.retry_jitter_fraction,
    )
    four_worker_seconds = time.perf_counter() - concurrent_started

    serial_value = _summary_dict(serial_result)
    first_pass_value = _summary_dict(first_pass)
    repaired_value = _summary_dict(repaired)
    bounded_concurrency_proved = (
        serial_adapter.max_active == 1 and 1 < concurrent_adapter.max_active <= 4
    )
    midpoint_resume_proved = (
        first_pass_value.get("failure_count") == 1
        and repaired_value.get("selected") == 1
        and repaired_value.get("provider_calls") == 1
        and repaired_value.get("success") == 1
        and repaired_value.get("failure_count") == 0
    )
    smoke_summary: dict[str, object] = {
        "schema_version": "feedback-smoke-summary-v1",
        "run_id": concurrent_dir.name,
        "serial_run_id": serial_dir.name,
        "request_count": len(concurrent_requests),
        "serial_seconds": serial_seconds,
        "four_worker_seconds": four_worker_seconds,
        "timing_speedup": serial_seconds / four_worker_seconds,
        "serial_peak_concurrency": serial_adapter.max_active,
        "four_worker_peak_concurrency": concurrent_adapter.max_active,
        "bounded_concurrency_proved": bounded_concurrency_proved,
        "midpoint_resume_proved": midpoint_resume_proved,
        "midpoint_request_id": midpoint.request_id,
        "midpoint_failure_first_pass": first_pass_value,
        "midpoint_repair": repaired_value,
        "serial_result": serial_value,
    }
    modules["atomic_write_json"](concurrent_dir / "smoke_summary.json", smoke_summary)
    pointer = {
        "schema_version": "feedback-latest-smoke-pointer-v1",
        "run_id": concurrent_dir.name,
        "smoke_summary": f"{concurrent_dir.name}/smoke_summary.json",
    }
    modules["atomic_write_json"](runs_root / LATEST_SMOKE_FILENAME, pointer)
    _print_json(smoke_summary)

    return 0 if bounded_concurrency_proved and midpoint_resume_proved else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve() if args.repo_root else find_repo_root()
    modules = _load_modules(repo_root)

    try:
        if args.command == "manifest":
            return _manifest_command(args, repo_root, modules)
        if args.command == "run":
            return _run_command(args, repo_root, modules)
        if args.command == "materialize":
            return _materialize_command(args, repo_root, modules)
        if args.command == "audit":
            return _audit_command(args, repo_root, modules)
        if args.command == "smoke":
            return _smoke_command(args, repo_root, modules)
    except (FileNotFoundError, FileExistsError, RuntimeError, TypeError, ValueError) as exc:
        print(f"feedback pipeline error: {exc}", file=sys.stderr)
        return 2
    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
