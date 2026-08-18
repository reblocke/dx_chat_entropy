from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import shutil
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .config import FeedbackConfig, ModelProfile, normalize_category_mode
from .models import MANIFEST_COLUMNS, FeedbackRequest, canonical_json
from .prompts import build_messages

MANIFEST_FILENAME = "manifest.csv"
SUMMARY_FILENAME = "manifest_summary.json"
METADATA_FILENAME = "run_metadata.json"
LEDGER_FILENAME = "run_ledger.csv"

LEDGER_COLUMNS = (
    "request_order",
    "request_id",
    "status",
    "attempt_count",
    "updated_at",
    "failure_class",
    "http_status",
    "response_path",
)

_SURFACE_DESTINATIONS = {
    "overall/general": ("overall_gen", "gen_overall", "overall"),
    "overall/specific": ("overall_spec", "spec_overall", "overall"),
    "differential/general": ("diff_gen", None, "differential"),
    "differential/specific": ("diff_spec", None, "differential"),
}


@dataclass(frozen=True)
class ManifestBuild:
    run_dir: Path
    requests: tuple[FeedbackRequest, ...]
    metadata: dict[str, object]

    @property
    def manifest_path(self) -> Path:
        return self.run_dir / MANIFEST_FILENAME

    def __iter__(self):
        """Allow convenient ``run_dir, requests, metadata = result`` unpacking."""

        yield self.run_dir
        yield self.requests
        yield self.metadata


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _normalized_messages(messages: Sequence[Mapping[str, str]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for index, message in enumerate(messages):
        if set(message) != {"role", "content"}:
            raise ValueError(f"messages[{index}] must contain only role and content")
        role = message["role"]
        content = message["content"]
        if not isinstance(role, str) or not isinstance(content, str):
            raise ValueError(f"messages[{index}] role and content must be strings")
        normalized.append(
            {"role": _normalize_newlines(role), "content": _normalize_newlines(content)}
        )
    if not normalized:
        raise ValueError("messages must not be empty")
    return normalized


def prompt_sha256(messages: Sequence[Mapping[str, str]]) -> str:
    """Hash ordered messages after newline-only normalization."""

    return _sha256_text(canonical_json(_normalized_messages(messages)))


def _request_identity_payload(
    *,
    surface: str,
    correct_diagnosis: str,
    target_diagnosis: str,
    comparison_diagnosis: str | None,
    diagnosis_order: int,
    category_key: str,
    category_order: int,
    config_schema_version: str,
    prompt_sha: str,
    prompt_schema_version: str,
    response_schema_version: str,
    expected_response_type: str,
    model_profile: str,
    model_id: str,
    model_settings: Mapping[str, object],
    workbook_path: str,
    sheet_name: str,
) -> dict[str, object]:
    return {
        "surface": surface,
        "correct_diagnosis": correct_diagnosis,
        "target_diagnosis": target_diagnosis,
        "comparison_diagnosis": comparison_diagnosis,
        "diagnosis_order": diagnosis_order,
        "category_key": category_key,
        "category_order": category_order,
        "config_schema_version": config_schema_version,
        "prompt_sha256": prompt_sha,
        "prompt_schema_version": prompt_schema_version,
        "response_schema_version": response_schema_version,
        "expected_response_type": expected_response_type,
        "model_profile": model_profile,
        "model_id": model_id,
        "model_settings": dict(model_settings),
        "workbook_path": workbook_path,
        "sheet_name": sheet_name,
    }


def _request_id(**identity: object) -> str:
    return f"fr_{_sha256_text(canonical_json(identity))[:32]}"


def _run_identity(
    config: FeedbackConfig,
    *,
    category_mode: str,
    request_ids: Sequence[str],
) -> tuple[str, str]:
    payload = {
        "config_schema_version": config.schema_version,
        "prompt_schema_version": config.prompt_schema_version,
        "response_schema_version": config.response_schema_version,
        "category_mode": category_mode,
        "ordered_request_ids": list(request_ids),
    }
    fingerprint = _sha256_text(canonical_json(payload))
    return fingerprint, f"fb_{fingerprint[:24]}"


def _workbook_path(
    *,
    surface: str,
    correct_diagnosis: str,
    target_diagnosis: str,
    comparison_diagnosis: str | None,
) -> str:
    directory, overall_suffix, _ = _SURFACE_DESTINATIONS[surface]
    if overall_suffix is not None:
        filename = f"{target_diagnosis}_{overall_suffix}.xlsx"
    else:
        if comparison_diagnosis is None:
            raise ValueError("Differential workbook destination requires comparison_diagnosis")
        filename = f"{correct_diagnosis}_vs_{comparison_diagnosis}.xlsx"
    return (Path("workbooks") / directory / filename).as_posix()


def _request_specs(
    config: FeedbackConfig,
    *,
    category_mode: str,
    model: ModelProfile,
) -> list[dict[str, Any]]:
    categories = config.categories_for_mode(category_mode)
    specs: list[dict[str, Any]] = []

    for surface in config.enabled_surfaces:
        if surface not in _SURFACE_DESTINATIONS:
            raise ValueError(f"Unsupported enabled surface: {surface!r}")
        is_differential = surface.startswith("differential/")
        diagnosis_entries = (
            (
                (
                    config.correct_diagnosis,
                    alternative,
                    config.diagnoses.index(alternative) + 1,
                )
                for alternative in config.alternatives
            )
            if is_differential
            else ((diagnosis, None, order) for order, diagnosis in enumerate(config.diagnoses, 1))
        )
        for target_diagnosis, comparison_diagnosis, diagnosis_order in diagnosis_entries:
            for category in categories:
                messages = build_messages(
                    surface,
                    correct_diagnosis=config.correct_diagnosis,
                    target_diagnosis=target_diagnosis,
                    comparison_diagnosis=comparison_diagnosis,
                    category=category,
                )
                messages = _normalized_messages(messages)
                prompt_hash = prompt_sha256(messages)
                expected_response_type = _SURFACE_DESTINATIONS[surface][2]
                workbook_path = _workbook_path(
                    surface=surface,
                    correct_diagnosis=config.correct_diagnosis,
                    target_diagnosis=target_diagnosis,
                    comparison_diagnosis=comparison_diagnosis,
                )
                sheet_name = category.key[:31]
                identity = _request_identity_payload(
                    surface=surface,
                    correct_diagnosis=config.correct_diagnosis,
                    target_diagnosis=target_diagnosis,
                    comparison_diagnosis=comparison_diagnosis,
                    diagnosis_order=diagnosis_order,
                    category_key=category.key,
                    category_order=category.order,
                    config_schema_version=config.schema_version,
                    prompt_sha=prompt_hash,
                    prompt_schema_version=config.prompt_schema_version,
                    response_schema_version=config.response_schema_version,
                    expected_response_type=expected_response_type,
                    model_profile=model.name,
                    model_id=model.model_id,
                    model_settings=model.settings,
                    workbook_path=workbook_path,
                    sheet_name=sheet_name,
                )
                request_id = _request_id(**identity)
                specs.append(
                    {
                        **identity,
                        "request_id": request_id,
                        "messages": messages,
                        "response_path": f"responses/{request_id}.json",
                        "workbook_path": workbook_path,
                        "sheet_name": sheet_name,
                    }
                )
    return specs


def _build_feedback_inventory(
    config: FeedbackConfig,
    *,
    category_mode: str | bool | None = None,
    model_profile: str | None = None,
    run_id: str | None = None,
) -> tuple[tuple[FeedbackRequest, ...], str, str]:

    mode = normalize_category_mode(
        config.default_category_mode if category_mode is None else category_mode
    )
    model = config.model(model_profile)
    specs = _request_specs(config, category_mode=mode, model=model)
    request_ids = [str(spec["request_id"]) for spec in specs]
    if len(request_ids) != len(set(request_ids)):
        raise ValueError("Generated duplicate feedback request IDs")
    run_fingerprint, base_run_id = _run_identity(
        config, category_mode=mode, request_ids=request_ids
    )
    selected_run_id = run_id or base_run_id
    if not selected_run_id or Path(selected_run_id).name != selected_run_id:
        raise ValueError("run_id must be a non-empty single path component")

    requests = tuple(
        FeedbackRequest(
            request_order=request_order,
            request_id=str(spec["request_id"]),
            run_id=selected_run_id,
            surface=str(spec["surface"]),
            correct_diagnosis=str(spec["correct_diagnosis"]),
            target_diagnosis=str(spec["target_diagnosis"]),
            comparison_diagnosis=(
                None if spec["comparison_diagnosis"] is None else str(spec["comparison_diagnosis"])
            ),
            diagnosis_order=int(spec["diagnosis_order"]),
            category_key=str(spec["category_key"]),
            category_order=int(spec["category_order"]),
            config_schema_version=str(spec["config_schema_version"]),
            prompt_schema_version=str(spec["prompt_schema_version"]),
            response_schema_version=str(spec["response_schema_version"]),
            model_profile=str(spec["model_profile"]),
            model_id=str(spec["model_id"]),
            model_settings=dict(spec["model_settings"]),
            messages=list(spec["messages"]),
            prompt_sha256=str(spec["prompt_sha256"]),
            expected_response_type=str(spec["expected_response_type"]),
            response_path=str(spec["response_path"]),
            workbook_path=str(spec["workbook_path"]),
            sheet_name=str(spec["sheet_name"]),
        )
        for request_order, spec in enumerate(specs, start=1)
    )
    return requests, run_fingerprint, base_run_id


def build_feedback_requests(
    config: FeedbackConfig,
    *,
    category_mode: str | bool | None = None,
    model_profile: str | None = None,
    run_id: str | None = None,
) -> tuple[FeedbackRequest, ...]:
    """Materialize the complete deterministic request inventory without I/O."""

    requests, _, _ = _build_feedback_inventory(
        config,
        category_mode=category_mode,
        model_profile=model_profile,
        run_id=run_id,
    )
    return requests


def _render_csv(columns: Sequence[str], rows: Sequence[Mapping[str, object]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(columns), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in columns})
    return buffer.getvalue().encode("utf-8")


def _render_json(payload: Mapping[str, object]) -> bytes:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return rendered.encode("utf-8")


def _manifest_bytes(requests: Sequence[FeedbackRequest]) -> bytes:
    return _render_csv(MANIFEST_COLUMNS, [request.to_manifest_row() for request in requests])


def _summary_payload(
    *,
    run_id: str,
    run_fingerprint: str,
    category_mode: str,
    requests: Sequence[FeedbackRequest],
) -> dict[str, object]:
    return {
        "schema_version": "feedback-manifest-summary-v1",
        "run_id": run_id,
        "run_fingerprint": run_fingerprint,
        "category_mode": category_mode,
        "total_requests": len(requests),
        "counts_by_surface": dict(Counter(request.surface for request in requests)),
        "counts_by_category": dict(Counter(request.category_key for request in requests)),
    }


def _metadata_payload(
    config: FeedbackConfig,
    *,
    run_id: str,
    run_fingerprint: str,
    category_mode: str,
    model: ModelProfile,
    requests: Sequence[FeedbackRequest],
    manifest_bytes: bytes,
) -> dict[str, object]:
    return {
        "schema_version": "feedback-run-metadata-v1",
        "run_id": run_id,
        "run_fingerprint": run_fingerprint,
        "config_schema_version": config.schema_version,
        "prompt_schema_version": config.prompt_schema_version,
        "response_schema_version": config.response_schema_version,
        "category_mode": category_mode,
        "model_profile": model.name,
        "model_id": model.model_id,
        "model_settings": dict(model.settings),
        "request_count": len(requests),
        "ordered_request_ids": [request.request_id for request in requests],
        "manifest_sha256": _sha256_bytes(manifest_bytes),
        "manifest_path": MANIFEST_FILENAME,
        "summary_path": SUMMARY_FILENAME,
        "ledger_path": LEDGER_FILENAME,
    }


def _ledger_bytes(requests: Sequence[FeedbackRequest]) -> bytes:
    return _render_csv(
        LEDGER_COLUMNS,
        [
            {
                "request_order": request.request_order,
                "request_id": request.request_id,
                "status": request.initial_status,
                "attempt_count": 0,
                "updated_at": "",
                "failure_class": "",
                "http_status": "",
                "response_path": request.response_path,
            }
            for request in requests
        ],
    )


def _write_file(path: Path, content: bytes) -> None:
    path.write_bytes(content)
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _fsync_directory(directory: Path) -> None:
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:  # pragma: no cover - unsupported filesystems/platforms.
        return
    try:
        os.fsync(descriptor)
    except OSError:  # pragma: no cover - unsupported filesystems/platforms.
        pass
    finally:
        os.close(descriptor)


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def read_manifest(path: str | Path) -> tuple[FeedbackRequest, ...]:
    """Read and fully validate a feedback request manifest."""

    manifest_path = Path(path)
    with manifest_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != MANIFEST_COLUMNS:
            raise ValueError(
                f"Manifest columns do not match the required contract: {reader.fieldnames}"
            )
        requests = tuple(FeedbackRequest.from_manifest_row(row) for row in reader)

    if not requests:
        raise ValueError("Manifest must contain at least one request")

    expected_orders = list(range(1, len(requests) + 1))
    actual_orders = [request.request_order for request in requests]
    if actual_orders != expected_orders:
        raise ValueError("Manifest request_order must be contiguous and one-based")
    request_ids = [request.request_id for request in requests]
    if len(request_ids) != len(set(request_ids)):
        raise ValueError("Manifest contains duplicate request IDs")
    run_ids = {request.run_id for request in requests}
    if len(run_ids) > 1:
        raise ValueError("Manifest contains more than one run_id")

    for request in requests:
        actual_prompt_hash = prompt_sha256(request.messages)
        if request.prompt_sha256 != actual_prompt_hash:
            raise ValueError(f"Prompt hash mismatch for request {request.request_id}")
        identity = _request_identity_payload(
            surface=request.surface,
            correct_diagnosis=request.correct_diagnosis,
            target_diagnosis=request.target_diagnosis,
            comparison_diagnosis=request.comparison_diagnosis,
            diagnosis_order=request.diagnosis_order,
            category_key=request.category_key,
            category_order=request.category_order,
            config_schema_version=request.config_schema_version,
            prompt_sha=request.prompt_sha256,
            prompt_schema_version=request.prompt_schema_version,
            response_schema_version=request.response_schema_version,
            expected_response_type=request.expected_response_type,
            model_profile=request.model_profile,
            model_id=request.model_id,
            model_settings=request.model_settings,
            workbook_path=request.workbook_path,
            sheet_name=request.sheet_name,
        )
        if request.request_id != _request_id(**identity):
            raise ValueError(f"Request identity mismatch for {request.request_id}")
    return requests


def _validate_existing_run(
    run_dir: Path,
    *,
    expected_manifest: bytes,
    expected_summary: bytes,
    expected_metadata: Mapping[str, object],
) -> tuple[FeedbackRequest, ...]:
    required_paths = [
        run_dir / MANIFEST_FILENAME,
        run_dir / SUMMARY_FILENAME,
        run_dir / METADATA_FILENAME,
        run_dir / LEDGER_FILENAME,
    ]
    missing = [path.name for path in required_paths if not path.is_file()]
    if missing:
        raise FileExistsError(f"Existing run is incomplete; missing: {missing}")
    required_directories = [run_dir / name for name in ("attempts", "responses", "workbooks")]
    missing_directories = [path.name for path in required_directories if not path.is_dir()]
    if missing_directories:
        raise FileExistsError(
            f"Existing run is incomplete; missing directories: {missing_directories}"
        )

    actual_manifest = (run_dir / MANIFEST_FILENAME).read_bytes()
    if actual_manifest != expected_manifest:
        raise FileExistsError("Existing manifest bytes do not match the requested base run")
    actual_summary = (run_dir / SUMMARY_FILENAME).read_bytes()
    if actual_summary != expected_summary:
        raise FileExistsError("Existing manifest summary does not match the requested base run")
    actual_metadata = _load_json_object(run_dir / METADATA_FILENAME)
    if actual_metadata.get("run_fingerprint") != expected_metadata["run_fingerprint"]:
        raise FileExistsError("Existing run metadata fingerprint does not match")
    if actual_metadata != dict(expected_metadata):
        raise FileExistsError("Existing run metadata does not match the requested base run")

    requests = read_manifest(run_dir / MANIFEST_FILENAME)
    if _sha256_bytes(actual_manifest) != actual_metadata.get("manifest_sha256"):
        raise FileExistsError("Existing run metadata manifest hash does not match")

    with (run_dir / LEDGER_FILENAME).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != LEDGER_COLUMNS:
            raise FileExistsError("Existing run ledger columns do not match the required contract")
        ledger_rows = list(reader)
    if [row["request_id"] for row in ledger_rows] != [request.request_id for request in requests]:
        raise FileExistsError("Existing run ledger request inventory does not match the manifest")
    return requests


def build_or_load_manifest(
    config: FeedbackConfig,
    *,
    output_root: str | Path | None = None,
    category_mode: str | bool | None = None,
    model_profile: str | None = None,
) -> ManifestBuild:
    """Create a complete base-run manifest or validate and reuse the exact existing one.

    This function never invents recompute suffixes. Higher-level runtime code owns
    selection of any ``rNNN`` run identity.
    """

    mode = normalize_category_mode(
        config.default_category_mode if category_mode is None else category_mode
    )
    model = config.model(model_profile)
    requests, run_fingerprint, run_id = _build_feedback_inventory(
        config,
        category_mode=mode,
        model_profile=model.name,
    )
    if {request.run_id for request in requests} != {run_id}:
        requests = tuple(replace(request, run_id=run_id) for request in requests)

    root = Path(output_root) if output_root is not None else config.output_root
    run_dir = root / run_id
    manifest_content = _manifest_bytes(requests)
    summary = _summary_payload(
        run_id=run_id,
        run_fingerprint=run_fingerprint,
        category_mode=mode,
        requests=requests,
    )
    metadata = _metadata_payload(
        config,
        run_id=run_id,
        run_fingerprint=run_fingerprint,
        category_mode=mode,
        model=model,
        requests=requests,
        manifest_bytes=manifest_content,
    )
    summary_content = _render_json(summary)

    if run_dir.exists():
        existing_requests = _validate_existing_run(
            run_dir,
            expected_manifest=manifest_content,
            expected_summary=summary_content,
            expected_metadata=metadata,
        )
        return ManifestBuild(run_dir=run_dir, requests=existing_requests, metadata=metadata)

    root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{run_id}.", dir=root))
    try:
        (temporary / "responses").mkdir()
        (temporary / "attempts").mkdir()
        (temporary / "workbooks").mkdir()
        _write_file(temporary / MANIFEST_FILENAME, manifest_content)
        _write_file(temporary / SUMMARY_FILENAME, summary_content)
        _write_file(temporary / METADATA_FILENAME, _render_json(metadata))
        _write_file(temporary / LEDGER_FILENAME, _ledger_bytes(requests))
        _fsync_directory(temporary)
        try:
            temporary.rename(run_dir)
        except FileExistsError:
            existing_requests = _validate_existing_run(
                run_dir,
                expected_manifest=manifest_content,
                expected_summary=summary_content,
                expected_metadata=metadata,
            )
            return ManifestBuild(run_dir=run_dir, requests=existing_requests, metadata=metadata)
        _fsync_directory(root)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)

    return ManifestBuild(run_dir=run_dir, requests=requests, metadata=metadata)
