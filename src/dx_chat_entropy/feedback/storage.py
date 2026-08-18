from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
import shutil
import tempfile
import threading
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from .manifest import (
    LEDGER_COLUMNS,
    LEDGER_FILENAME,
    MANIFEST_FILENAME,
    METADATA_FILENAME,
    SUMMARY_FILENAME,
    read_manifest,
)
from .models import FeedbackRequest, canonical_json, validate_response_payload

RESPONSE_RECORD_SCHEMA_VERSION = "feedback-response-record-v1"
VALID_LEDGER_STATUSES = frozenset(
    {
        "pending",
        "running",
        "success",
        "invalid",
        "transient_failure",
        "permanent_failure",
        "skipped_existing",
    }
)
VALID_ATTEMPT_STATUSES = frozenset(
    {
        "success",
        "invalid",
        "transient_failure",
        "permanent_failure",
    }
)
VALID_FAILURE_CLASSES = frozenset(
    {
        "",
        "transient_provider",
        "invalid_response",
        "permanent_provider",
        "stale_running",
        "invalid_stored_response",
        "attempt_cap",
        "interrupted",
    }
)
ATTEMPT_RECORD_FIELDS = (
    "request_id",
    "attempt",
    "status",
    "failure_class",
    "http_status",
    "retry_after_seconds",
    "started_at",
    "finished_at",
    "latency_seconds",
)
RESPONSE_RECORD_FIELDS = (
    "schema_version",
    "request_id",
    "run_id",
    "prompt_sha256",
    "config_schema_version",
    "prompt_schema_version",
    "response_schema_version",
    "model_profile",
    "model_id",
    "model_settings",
    "parsed_payload",
    "response_payload_sha256",
    "provider_response_id",
    "attempt_count",
    "started_at",
    "finished_at",
    "latency_seconds",
    "token_usage",
    "safe_finish_status",
)
_SAFE_PROVIDER_ID_PREFIXES = ("chatcmpl-", "resp_", "response_")
_TOKEN_COUNT_FIELDS = frozenset(
    {
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "input_tokens",
        "output_tokens",
        "cached_tokens",
        "reasoning_tokens",
    }
)
_SAFE_FINISH_VALUES = frozenset(
    {
        "stop",
        "length",
        "content_filter",
        "tool_calls",
        "function_call",
        "completed",
        "incomplete",
        "failed",
        "cancelled",
        "unknown",
    }
)
_MAX_RETRY_AFTER_SECONDS = 3600.0
_MAX_ATTEMPT_NUMBER = 9999


def sha256_json(value: object) -> str:
    """Return the SHA-256 of the repository's canonical JSON representation."""

    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


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


def atomic_write_bytes(path: str | Path, content: bytes) -> Path:
    """Write bytes beside the destination, fsync, then atomically replace it."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        _fsync_directory(destination.parent)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def atomic_write_text(path: str | Path, content: str) -> Path:
    return atomic_write_bytes(path, content.encode("utf-8"))


def atomic_write_json(path: str | Path, payload: object) -> Path:
    content = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    )
    return atomic_write_text(path, f"{content}\n")


def atomic_write_csv(
    path: str | Path,
    fieldnames: Sequence[str],
    rows: Sequence[Mapping[str, object]],
) -> Path:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(fieldnames), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field, "") for field in fieldnames})
    return atomic_write_text(path, buffer.getvalue())


def load_json_object(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON record: {source}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"JSON record must contain an object: {source}")
    return payload


def resolve_run_path(run_dir: str | Path, relative_path: str | Path) -> Path:
    """Resolve a manifest path while preventing absolute or parent traversal."""

    root = Path(run_dir).resolve()
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"Run artifact path must be safe and relative: {relative_path!s}")
    destination = (root / relative).resolve()
    try:
        destination.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Run artifact path escapes the run directory: {relative_path!s}") from exc
    return destination


def response_path_for_request(run_dir: str | Path, request: FeedbackRequest) -> Path:
    return resolve_run_path(run_dir, request.response_path)


def _require_string(record: Mapping[str, object], field: str, *, allow_empty: bool = False) -> str:
    value = record.get(field)
    if not isinstance(value, str) or (not allow_empty and not value):
        raise ValueError(f"Response record field {field!r} must be a string")
    return value


def _require_nonnegative_number(record: Mapping[str, object], field: str) -> float:
    value = record.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Response record field {field!r} must be numeric")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"Response record field {field!r} must be finite and non-negative")
    return number


def _validate_timestamp(value: object, field: str, *, allow_empty: bool = False) -> str:
    if allow_empty and value == "":
        return ""
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty timestamp string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a UTC offset")
    return value


def _validate_http_status(value: object, *, allow_empty: bool = False) -> int | None:
    if value is None or (allow_empty and value == ""):
        return None
    if isinstance(value, bool):
        raise ValueError("http_status must be an integer from 100 through 599 or empty")
    if isinstance(value, str):
        if not allow_empty or not value.isascii() or not value.isdecimal():
            raise ValueError("http_status must be an integer from 100 through 599 or empty")
        value = int(value)
    if not isinstance(value, int) or not 100 <= value <= 599:
        raise ValueError("http_status must be an integer from 100 through 599 or empty")
    return value


def _validate_retry_after(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("retry_after_seconds must be numeric or empty")
    seconds = float(value)
    if not math.isfinite(seconds) or not 0 <= seconds <= _MAX_RETRY_AFTER_SECONDS:
        raise ValueError("retry_after_seconds must be finite and between 0 and 3600")
    return seconds


def _validate_failure_class(value: object) -> str:
    if not isinstance(value, str) or value not in VALID_FAILURE_CLASSES:
        # Do not interpolate provider-derived text into an error that could reach logs.
        raise ValueError("failure_class is not allowlisted")
    return value


def _validate_status(value: object, allowed: frozenset[str], *, field: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        # Do not interpolate an untrusted status value into the exception text.
        raise ValueError(f"{field} is not allowlisted")
    return value


def _validate_time_window(
    started_at: object,
    finished_at: object,
    latency_seconds: object,
) -> tuple[str, str, float]:
    started = _validate_timestamp(started_at, "started_at")
    finished = _validate_timestamp(finished_at, "finished_at")
    started_value = datetime.fromisoformat(started.replace("Z", "+00:00"))
    finished_value = datetime.fromisoformat(finished.replace("Z", "+00:00"))
    if finished_value < started_value:
        raise ValueError("finished_at must not precede started_at")
    latency = _require_nonnegative_number({"latency_seconds": latency_seconds}, "latency_seconds")
    return started, finished, latency


def sanitize_provider_response_id(value: object) -> str | None:
    if not isinstance(value, str) or not value.startswith(_SAFE_PROVIDER_ID_PREFIXES):
        return None
    if len(value) > 200 or re.fullmatch(r"[A-Za-z0-9_.:-]+", value) is None:
        return None
    return value


def sanitize_token_usage(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    counts: dict[str, int] = {}
    for key in sorted(_TOKEN_COUNT_FIELDS):
        raw = value.get(key)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            continue
        numeric = float(raw)
        if math.isfinite(numeric) and numeric >= 0 and numeric.is_integer():
            counts[key] = int(numeric)
    return counts


def sanitize_finish_status(value: object) -> dict[str, str]:
    if isinstance(value, str):
        value = {"finish_reason": value}
    if not isinstance(value, Mapping):
        return {}
    safe: dict[str, str] = {}
    for key in ("finish_reason", "status"):
        raw = value.get(key)
        if isinstance(raw, str) and raw.strip().lower() in _SAFE_FINISH_VALUES:
            safe[key] = raw.strip().lower()
    return safe


def validate_response_record(
    request: FeedbackRequest,
    path: str | Path,
) -> dict[str, Any]:
    """Validate a stored response against every output-affecting request identity field."""

    record = load_json_object(path)
    missing = [field for field in RESPONSE_RECORD_FIELDS if field not in record]
    if missing:
        raise ValueError(f"Response record is missing required fields: {missing}")
    if set(record) != set(RESPONSE_RECORD_FIELDS):
        # Field names can themselves contain sensitive provider text; keep this generic.
        raise ValueError("Response record contains unexpected fields")

    identity = {
        "schema_version": RESPONSE_RECORD_SCHEMA_VERSION,
        "request_id": request.request_id,
        "run_id": request.run_id,
        "prompt_sha256": request.prompt_sha256,
        "config_schema_version": request.config_schema_version,
        "prompt_schema_version": request.prompt_schema_version,
        "response_schema_version": request.response_schema_version,
        "model_profile": request.model_profile,
        "model_id": request.model_id,
        "model_settings": request.model_settings,
    }
    for field, expected in identity.items():
        if record.get(field) != expected:
            raise ValueError(f"Response record identity mismatch for field {field!r}")

    normalized_payload = validate_response_payload(
        request.expected_response_type,
        record["parsed_payload"],
    )
    payload_hash = _require_string(record, "response_payload_sha256")
    if payload_hash != sha256_json(normalized_payload):
        raise ValueError("Response payload hash mismatch")

    provider_response_id = record["provider_response_id"]
    if provider_response_id != sanitize_provider_response_id(provider_response_id):
        raise ValueError("provider_response_id is not an allowlisted safe provider identifier")
    attempt_count = record["attempt_count"]
    if isinstance(attempt_count, bool) or not isinstance(attempt_count, int) or attempt_count < 1:
        raise ValueError("attempt_count must be a positive integer")
    started_at, finished_at, latency_seconds = _validate_time_window(
        record["started_at"], record["finished_at"], record["latency_seconds"]
    )
    token_usage = record["token_usage"]
    if token_usage != sanitize_token_usage(token_usage):
        raise ValueError("token_usage must contain only allowlisted non-negative token counts")
    safe_finish_status = record["safe_finish_status"]
    if safe_finish_status != sanitize_finish_status(safe_finish_status):
        raise ValueError("safe_finish_status contains a non-allowlisted value")

    normalized = dict(record)
    normalized["parsed_payload"] = normalized_payload
    normalized["started_at"] = started_at
    normalized["finished_at"] = finished_at
    normalized["latency_seconds"] = latency_seconds
    normalized["token_usage"] = dict(token_usage)
    normalized["safe_finish_status"] = dict(safe_finish_status)
    return normalized


def write_response_record(
    run_dir: str | Path,
    request: FeedbackRequest,
    record: Mapping[str, object],
) -> Path:
    """Validate and atomically commit a successful per-request response."""

    path = response_path_for_request(run_dir, request)
    if set(record) - set(RESPONSE_RECORD_FIELDS):
        # Reject before creating a validation temp file so extra values never reach disk.
        raise ValueError("Response record contains unexpected fields")
    candidate = dict(record)
    normalized_payload = validate_response_payload(
        request.expected_response_type,
        candidate.get("parsed_payload"),
    )
    candidate["parsed_payload"] = normalized_payload
    candidate["response_payload_sha256"] = sha256_json(normalized_payload)
    candidate["config_schema_version"] = request.config_schema_version
    candidate["prompt_schema_version"] = request.prompt_schema_version
    candidate["provider_response_id"] = sanitize_provider_response_id(
        candidate.get("provider_response_id")
    )
    candidate["token_usage"] = sanitize_token_usage(candidate.get("token_usage"))
    candidate["safe_finish_status"] = sanitize_finish_status(candidate.get("safe_finish_status"))

    # Validate using an adjacent temporary record before it can look complete.
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.validate.", suffix=".tmp", dir=path.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        atomic_write_json(temporary, candidate)
        normalized = validate_response_record(request, temporary)
        atomic_write_json(path, normalized)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def attempt_record_path(run_dir: str | Path, request_id: str, attempt: int) -> Path:
    if not request_id or Path(request_id).name != request_id:
        raise ValueError("request_id must be a safe path component")
    attempt = _validate_attempt_number(attempt)
    return resolve_run_path(run_dir, Path("attempts") / request_id / f"{attempt:04d}.json")


def _validate_attempt_number(value: object) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= _MAX_ATTEMPT_NUMBER
    ):
        raise ValueError("attempt must be an integer from 1 through 9999")
    return value


def _normalize_attempt_record(record: Mapping[str, object]) -> dict[str, object]:
    if set(record) - set(ATTEMPT_RECORD_FIELDS):
        raise ValueError("Attempt record contains unexpected fields")
    missing = [field for field in ATTEMPT_RECORD_FIELDS if field not in record]
    if missing:
        raise ValueError(f"Attempt record is missing required fields: {missing}")
    request_id = record["request_id"]
    if not isinstance(request_id, str):
        raise ValueError("Attempt record request_id must be a string")
    attempt = _validate_attempt_number(record["attempt"])
    status = _validate_status(record["status"], VALID_ATTEMPT_STATUSES, field="Attempt status")
    failure_class = _validate_failure_class(record["failure_class"])
    http_status = _validate_http_status(record["http_status"])
    retry_after_seconds = _validate_retry_after(record["retry_after_seconds"])
    started_at, finished_at, latency_seconds = _validate_time_window(
        record["started_at"], record["finished_at"], record["latency_seconds"]
    )
    if status == "success" and failure_class:
        raise ValueError("A successful attempt cannot have a failure_class")
    if status == "success" and (http_status is not None or retry_after_seconds is not None):
        raise ValueError("A successful attempt cannot have failure metadata")
    if status != "success" and not failure_class:
        raise ValueError("A failed attempt must have an allowlisted failure_class")
    if retry_after_seconds is not None and status != "transient_failure":
        raise ValueError("retry_after_seconds is only valid for a transient failure")
    return {
        "request_id": request_id,
        "attempt": attempt,
        "status": status,
        "failure_class": failure_class,
        "http_status": http_status,
        "retry_after_seconds": retry_after_seconds,
        "started_at": started_at,
        "finished_at": finished_at,
        "latency_seconds": latency_seconds,
    }


def validate_attempt_record(
    path: str | Path,
    *,
    expected_request_id: str | None = None,
    expected_attempt: int | None = None,
) -> dict[str, object]:
    """Load and strictly validate one safe attempt record and optional path identity."""

    if expected_attempt is not None:
        expected_attempt = _validate_attempt_number(expected_attempt)
    normalized = _normalize_attempt_record(load_json_object(path))
    if expected_request_id is not None and normalized["request_id"] != expected_request_id:
        raise ValueError("Attempt record request_id does not match its expected path")
    if expected_attempt is not None and normalized["attempt"] != expected_attempt:
        raise ValueError("Attempt record attempt does not match its expected path")
    return normalized


def write_attempt_record(
    run_dir: str | Path,
    record: Mapping[str, object],
) -> Path:
    """Persist only the allowlisted, non-sensitive attempt metadata."""

    safe_record = _normalize_attempt_record(record)
    request_id = str(safe_record["request_id"])
    attempt = int(safe_record["attempt"])
    path = attempt_record_path(run_dir, request_id, attempt)
    return atomic_write_json(path, safe_record)


def _initial_ledger_rows(requests: Sequence[FeedbackRequest]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for request in requests:
        status = _validate_status(
            request.initial_status, VALID_LEDGER_STATUSES, field="Ledger status"
        )
        rows.append(
            {
                "request_order": request.request_order,
                "request_id": request.request_id,
                "status": status,
                "attempt_count": 0,
                "updated_at": "",
                "failure_class": "",
                "http_status": "",
                "response_path": request.response_path,
            }
        )
    return rows


def initialize_ledger(
    run_dir: str | Path,
    requests: Sequence[FeedbackRequest],
    *,
    overwrite: bool = False,
) -> Path:
    path = Path(run_dir) / LEDGER_FILENAME
    if path.exists() and not overwrite:
        raise FileExistsError(f"Run ledger already exists: {path}")
    return atomic_write_csv(path, LEDGER_COLUMNS, _initial_ledger_rows(requests))


def _read_ledger_rows(
    path: Path,
    requests: Sequence[FeedbackRequest],
) -> list[dict[str, object]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != LEDGER_COLUMNS:
            raise ValueError("Run ledger columns do not match the required contract")
        raw_rows = list(reader)

    if len(raw_rows) != len(requests):
        raise ValueError("Run ledger row count does not match the immutable manifest")
    rows: list[dict[str, object]] = []
    for raw, request in zip(raw_rows, requests, strict=True):
        if raw["request_id"] != request.request_id:
            raise ValueError("Run ledger request order does not match the immutable manifest")
        if int(raw["request_order"]) != request.request_order:
            raise ValueError("Run ledger request_order does not match the immutable manifest")
        if raw["response_path"] != request.response_path:
            raise ValueError("Run ledger response_path does not match the immutable manifest")
        status = _validate_status(raw["status"], VALID_LEDGER_STATUSES, field="Ledger status")
        attempt_count = int(raw["attempt_count"] or 0)
        if attempt_count < 0:
            raise ValueError("Ledger attempt_count must be non-negative")
        updated_at = _validate_timestamp(raw["updated_at"], "updated_at", allow_empty=True)
        failure_class = _validate_failure_class(raw["failure_class"])
        http_status = _validate_http_status(raw["http_status"], allow_empty=True)
        if status in {"pending", "running", "success", "skipped_existing"} and failure_class:
            raise ValueError("A non-failure ledger state cannot have a failure_class")
        rows.append(
            {
                "request_order": request.request_order,
                "request_id": request.request_id,
                "status": status,
                "attempt_count": attempt_count,
                "updated_at": updated_at,
                "failure_class": failure_class,
                "http_status": "" if http_status is None else http_status,
                "response_path": request.response_path,
            }
        )
    return rows


class LedgerStore:
    """Thread-safe in-memory ledger with an atomic full-file checkpoint per update."""

    def __init__(self, run_dir: str | Path, requests: Sequence[FeedbackRequest]) -> None:
        self.run_dir = Path(run_dir)
        self.path = self.run_dir / LEDGER_FILENAME
        self.requests = tuple(sorted(requests, key=lambda item: item.request_order))
        self._lock = threading.RLock()
        if not self.path.exists():
            initialize_ledger(self.run_dir, self.requests)
        rows = _read_ledger_rows(self.path, self.requests)
        self._rows = {str(row["request_id"]): row for row in rows}

    def snapshot(self) -> dict[str, dict[str, object]]:
        with self._lock:
            return {request_id: dict(row) for request_id, row in self._rows.items()}

    def row(self, request_id: str) -> dict[str, object]:
        with self._lock:
            try:
                return dict(self._rows[request_id])
            except KeyError as exc:
                raise KeyError(f"Unknown request_id in run ledger: {request_id}") from exc

    def update(
        self,
        request_id: str,
        *,
        status: str,
        attempt_count: int | None = None,
        updated_at: str,
        failure_class: str | None = None,
        http_status: int | None = None,
    ) -> dict[str, object]:
        status = _validate_status(status, VALID_LEDGER_STATUSES, field="Ledger status")
        updated_at = _validate_timestamp(updated_at, "updated_at")
        failure_class = _validate_failure_class(failure_class or "")
        http_status = _validate_http_status(http_status)
        if status in {"pending", "running", "success", "skipped_existing"} and failure_class:
            raise ValueError("A non-failure ledger state cannot have a failure_class")
        with self._lock:
            if request_id not in self._rows:
                raise KeyError(f"Unknown request_id in run ledger: {request_id}")
            current = self._rows[request_id]
            if attempt_count is not None and (
                isinstance(attempt_count, bool) or not isinstance(attempt_count, int)
            ):
                raise ValueError("Ledger attempt_count must be an integer")
            next_attempt_count = (
                int(current["attempt_count"]) if attempt_count is None else attempt_count
            )
            if next_attempt_count < int(current["attempt_count"]):
                raise ValueError("Ledger attempt_count cannot decrease")
            candidate = dict(current)
            candidate.update(
                {
                    "status": status,
                    "attempt_count": next_attempt_count,
                    "updated_at": updated_at,
                    "failure_class": failure_class,
                    "http_status": "" if http_status is None else http_status,
                }
            )
            candidate_rows = dict(self._rows)
            candidate_rows[request_id] = candidate
            ordered = [candidate_rows[request.request_id] for request in self.requests]
            atomic_write_csv(self.path, LEDGER_COLUMNS, ordered)
            self._rows = candidate_rows
            return dict(candidate)


_RECOMPUTE_SUFFIX_RE = re.compile(r"^(?P<base>.+?)(?:_r(?P<number>\d{3}))?$")


def _run_fingerprint(requests: Sequence[FeedbackRequest], category_mode: str) -> str:
    payload = {
        "config_schema_version": requests[0].config_schema_version,
        "prompt_schema_version": requests[0].prompt_schema_version,
        "response_schema_version": requests[0].response_schema_version,
        "category_mode": category_mode,
        "ordered_request_ids": [request.request_id for request in requests],
    }
    return sha256_json(payload)


def _validated_recompute_inputs(
    source: Path, requests: Sequence[FeedbackRequest]
) -> tuple[dict[str, Any], dict[str, Any]]:
    summary_path = source / SUMMARY_FILENAME
    metadata_path = source / METADATA_FILENAME
    if not summary_path.is_file() or not metadata_path.is_file():
        raise FileNotFoundError("Recompute source is missing immutable summary or metadata")
    summary = load_json_object(summary_path)
    metadata = load_json_object(metadata_path)

    category_keys = {request.category_key for request in requests}
    category_mode = "only_overall" if category_keys == {"subjective-and-historical"} else "all"
    run_ids = {request.run_id for request in requests}
    model_profiles = {request.model_profile for request in requests}
    model_ids = {request.model_id for request in requests}
    model_settings = {canonical_json(request.model_settings) for request in requests}
    schema_versions = {
        "config_schema_version": {request.config_schema_version for request in requests},
        "prompt_schema_version": {request.prompt_schema_version for request in requests},
        "response_schema_version": {request.response_schema_version for request in requests},
    }
    if (
        len(run_ids) != 1
        or len(model_profiles) != 1
        or len(model_ids) != 1
        or len(model_settings) != 1
        or any(len(values) != 1 for values in schema_versions.values())
    ):
        raise ValueError("Recompute source manifest has inconsistent identity fields")

    fingerprint = _run_fingerprint(requests, category_mode)
    manifest_hash = hashlib.sha256((source / MANIFEST_FILENAME).read_bytes()).hexdigest()
    expected_summary = {
        "schema_version": "feedback-manifest-summary-v1",
        "run_id": requests[0].run_id,
        "run_fingerprint": fingerprint,
        "category_mode": category_mode,
        "total_requests": len(requests),
        "counts_by_surface": dict(Counter(request.surface for request in requests)),
        "counts_by_category": dict(Counter(request.category_key for request in requests)),
    }
    expected_metadata = {
        "schema_version": "feedback-run-metadata-v1",
        "run_id": requests[0].run_id,
        "run_fingerprint": fingerprint,
        **{field: next(iter(values)) for field, values in schema_versions.items()},
        "category_mode": category_mode,
        "model_profile": requests[0].model_profile,
        "model_id": requests[0].model_id,
        "model_settings": requests[0].model_settings,
        "request_count": len(requests),
        "ordered_request_ids": [request.request_id for request in requests],
        "manifest_sha256": manifest_hash,
        "manifest_path": MANIFEST_FILENAME,
        "summary_path": SUMMARY_FILENAME,
        "ledger_path": LEDGER_FILENAME,
    }
    if summary != expected_summary or metadata != expected_metadata:
        raise ValueError("Recompute source summary or metadata identity mismatch")

    # Loading the ledger validates its schema, ordered inventory, states, and allowlisted metadata.
    _read_ledger_rows(source / LEDGER_FILENAME, requests)
    base_run_id = f"fb_{fingerprint[:24]}"
    if re.fullmatch(rf"{re.escape(base_run_id)}(?:_r[0-9]{{3}})?", source.name) is None:
        raise ValueError("Recompute source directory does not match its run fingerprint")
    return summary, metadata


def create_recompute_run(run_dir: str | Path) -> Path:
    """Clone immutable run inputs into the next ``_rNNN`` execution directory."""

    source = Path(run_dir).resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"Feedback run directory does not exist: {source}")
    source_requests = read_manifest(source / MANIFEST_FILENAME)
    summary, metadata = _validated_recompute_inputs(source, source_requests)

    match = _RECOMPUTE_SUFFIX_RE.fullmatch(source.name)
    if match is None:  # pragma: no cover - every non-empty name matches.
        raise ValueError(f"Invalid source run directory name: {source.name!r}")
    base_name = str(match.group("base"))
    used_numbers: set[int] = set()
    for sibling in source.parent.iterdir():
        sibling_match = _RECOMPUTE_SUFFIX_RE.fullmatch(sibling.name)
        if sibling_match and sibling_match.group("base") == base_name:
            suffix = sibling_match.group("number")
            if suffix is not None:
                used_numbers.add(int(suffix))

    next_number = max(used_numbers, default=0) + 1
    while True:
        run_id = f"{base_name}_r{next_number:03d}"
        destination = source.parent / run_id
        if not destination.exists():
            break
        next_number += 1

    requests = tuple(
        replace(request, run_id=run_id, initial_status="pending") for request in source_requests
    )
    summary["run_id"] = run_id
    metadata["run_id"] = run_id

    temporary = Path(tempfile.mkdtemp(prefix=f".{run_id}.", dir=source.parent))
    try:
        for name in ("responses", "attempts", "workbooks"):
            (temporary / name).mkdir()
        atomic_write_csv(
            temporary / MANIFEST_FILENAME,
            tuple(requests[0].to_manifest_row().keys()),
            [request.to_manifest_row() for request in requests],
        )
        manifest_bytes = (temporary / MANIFEST_FILENAME).read_bytes()
        metadata["manifest_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
        atomic_write_json(temporary / SUMMARY_FILENAME, summary)
        atomic_write_json(temporary / METADATA_FILENAME, metadata)
        initialize_ledger(temporary, requests)
        try:
            temporary.rename(destination)
        except FileExistsError:
            # A concurrent recompute chose this suffix. Retry with the now-visible next suffix.
            shutil.rmtree(temporary)
            return create_recompute_run(source)
        _fsync_directory(source.parent)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return destination
