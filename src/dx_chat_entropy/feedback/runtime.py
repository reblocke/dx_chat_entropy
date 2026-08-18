from __future__ import annotations

import math
import random
import threading
import time
from collections import Counter, deque
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from functools import lru_cache
from pathlib import Path
from typing import Protocol, runtime_checkable

from .manifest import MANIFEST_FILENAME, read_manifest
from .models import FeedbackRequest, ProviderResult, validate_response_payload
from .storage import (
    RESPONSE_RECORD_SCHEMA_VERSION,
    LedgerStore,
    attempt_record_path,
    create_recompute_run,
    response_path_for_request,
    sanitize_finish_status,
    sanitize_provider_response_id,
    sanitize_token_usage,
    sha256_json,
    validate_attempt_record,
    validate_response_record,
    write_attempt_record,
    write_response_record,
)

VALID_RESUME_MODES = frozenset({"recompute", "skip_passing", "repair_invalid"})
REPAIRABLE_STATUSES = frozenset({"invalid", "transient_failure", "permanent_failure", "running"})
TRANSIENT_HTTP_STATUSES = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


@runtime_checkable
class ProviderAdapter(Protocol):
    def execute(self, request: FeedbackRequest) -> ProviderResult:
        """Execute one request and return already-parsed provider-independent data."""


@dataclass(frozen=True)
class FailureInfo:
    failure_class: str
    transient: bool
    invalid: bool
    http_status: int | None = None
    retry_after_seconds: float | None = None


@dataclass(frozen=True)
class ExecutionSummary:
    run_dir: Path
    resume_mode: str
    selected_count: int
    success_count: int
    skipped_count: int
    invalid_count: int
    transient_failure_count: int
    permanent_failure_count: int
    pending_count: int
    provider_calls: int
    dry_run: bool
    interrupted: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "run_dir": str(self.run_dir),
            "run_id": self.run_dir.name,
            "resume_mode": self.resume_mode,
            **self.counts,
            "failure_count": self.failure_count,
            "dry_run": self.dry_run,
            "interrupted": self.interrupted,
            "exit_code": self.exit_code,
        }

    @property
    def failure_count(self) -> int:
        return self.invalid_count + self.transient_failure_count + self.permanent_failure_count

    @property
    def exit_code(self) -> int:
        return 0 if self.failure_count == 0 and not self.interrupted else 1

    @property
    def counts(self) -> dict[str, int]:
        return {
            "selected": self.selected_count,
            "success": self.success_count,
            "skipped_existing": self.skipped_count,
            "invalid": self.invalid_count,
            "transient_failure": self.transient_failure_count,
            "permanent_failure": self.permanent_failure_count,
            "pending": self.pending_count,
            "provider_calls": self.provider_calls,
        }


def _valid_fake_payload(request: FeedbackRequest) -> dict[str, object]:
    def evidence(prefix: str) -> list[dict[str, object]]:
        return [
            {
                "finding": f"{prefix} finding {index}",
                "explanation": f"Deterministic fake explanation {index}",
                "abbreviation_expansion": {},
            }
            for index in range(1, 6)
        ]

    if request.expected_response_type in {"overall", "overall_response"}:
        return {
            "for_diagnosis_strongest_evidence": evidence("supporting"),
            "against_diagnosis_strongest_evidence": evidence("opposing"),
            "summary": f"Deterministic fake response for {request.request_id}.",
        }
    return {
        "diagnosisA_strongest_evidence": evidence("diagnosis A"),
        "diagnosisB_strongest_evidence": evidence("diagnosis B"),
        "summary": f"Deterministic fake response for {request.request_id}.",
    }


class FakeProviderAdapter:
    """Thread-safe deterministic adapter for smoke tests and concurrency assertions."""

    def __init__(
        self,
        results: Mapping[str, ProviderResult | Mapping[str, object]] | None = None,
        *,
        failures: Mapping[str, Sequence[BaseException]] | None = None,
        result_factory: (
            Callable[[FeedbackRequest], ProviderResult | Mapping[str, object]] | None
        ) = None,
        delay_seconds: float = 0.0,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if delay_seconds < 0:
            raise ValueError("delay_seconds must be non-negative")
        self.results = dict(results or {})
        self.failures = {key: deque(value) for key, value in (failures or {}).items()}
        self.result_factory = result_factory
        self.delay_seconds = float(delay_seconds)
        self.sleeper = sleeper
        self._lock = threading.Lock()
        self._active = 0
        self._calls: list[str] = []
        self._attempts: Counter[str] = Counter()
        self.max_active = 0

    @property
    def calls(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._calls)

    @property
    def call_count(self) -> int:
        with self._lock:
            return len(self._calls)

    @property
    def attempts_by_request(self) -> dict[str, int]:
        with self._lock:
            return dict(self._attempts)

    def execute(self, request: FeedbackRequest) -> ProviderResult:
        with self._lock:
            self._calls.append(request.request_id)
            self._attempts[request.request_id] += 1
            self._active += 1
            self.max_active = max(self.max_active, self._active)
            failure = (
                self.failures[request.request_id].popleft()
                if self.failures.get(request.request_id)
                else None
            )
        try:
            if failure is not None and not isinstance(failure, Exception):
                raise failure
            if self.delay_seconds:
                self.sleeper(self.delay_seconds)
            if failure is not None:
                raise failure
            value: ProviderResult | Mapping[str, object]
            if request.request_id in self.results:
                value = self.results[request.request_id]
            elif self.result_factory is not None:
                value = self.result_factory(request)
            else:
                value = ProviderResult(payload=_valid_fake_payload(request), finish_reason="stop")
            return _coerce_provider_result(value)
        finally:
            with self._lock:
                self._active -= 1


@lru_cache(maxsize=1)
def _provider_response_models() -> dict[str, type]:
    from pydantic import ConfigDict, Field, create_model

    strict = ConfigDict(extra="forbid")
    evidence = create_model(
        "FeedbackEvidenceItem",
        finding=(str, ...),
        explanation=(str, ...),
        abbreviation_expansion=(dict[str, str], ...),
        __config__=strict,
    )
    five_items = Field(min_length=5, max_length=5)
    overall = create_model(
        "FeedbackOverallResponse",
        for_diagnosis_strongest_evidence=(list[evidence], five_items),
        against_diagnosis_strongest_evidence=(list[evidence], five_items),
        summary=(str, ...),
        __config__=strict,
    )
    differential = create_model(
        "FeedbackDifferentialResponse",
        diagnosisA_strongest_evidence=(list[evidence], five_items),
        diagnosisB_strongest_evidence=(list[evidence], five_items),
        summary=(str, ...),
        __config__=strict,
    )
    return {
        "overall": overall,
        "overall_response": overall,
        "differential": differential,
        "differential_response": differential,
    }


class OpenAIProviderAdapter:
    """Narrow structured-output adapter owning exactly one OpenAI client."""

    def __init__(
        self,
        client: object,
        *,
        timeout_seconds: float = 120.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.client = client
        self.timeout_seconds = float(timeout_seconds)

    def execute(self, request: FeedbackRequest) -> ProviderResult:
        try:
            response_format = _provider_response_models()[request.expected_response_type]
        except KeyError as exc:
            raise ValueError(
                f"Unsupported expected_response_type: {request.expected_response_type!r}"
            ) from exc
        completion = self.client.chat.completions.parse(
            model=request.model_id,
            messages=request.messages,
            response_format=response_format,
            **request.model_settings,
        )
        choice = completion.choices[0]
        parsed = choice.message.parsed
        if parsed is None:
            raise ValueError("Provider returned no parsed structured payload")
        payload = parsed.model_dump() if hasattr(parsed, "model_dump") else dict(parsed)
        usage = getattr(completion, "usage", None)
        if usage is not None and hasattr(usage, "model_dump"):
            usage = usage.model_dump()
        return ProviderResult(
            payload=payload,
            provider_response_id=getattr(completion, "id", None),
            token_usage=dict(usage) if isinstance(usage, Mapping) else {},
            finish_reason=getattr(choice, "finish_reason", None),
            status_metadata={},
        )


def _coerce_provider_result(
    value: ProviderResult | Mapping[str, object],
) -> ProviderResult:
    if isinstance(value, ProviderResult):
        return value
    if not isinstance(value, Mapping):
        raise TypeError("Provider adapter must return ProviderResult or a payload mapping")
    if "payload" in value and isinstance(value["payload"], Mapping):
        return ProviderResult(
            payload=dict(value["payload"]),
            provider_response_id=(
                str(value["provider_response_id"])
                if value.get("provider_response_id") is not None
                else None
            ),
            token_usage=(
                dict(value["token_usage"]) if isinstance(value.get("token_usage"), Mapping) else {}
            ),
            finish_reason=(
                str(value["finish_reason"]) if value.get("finish_reason") is not None else None
            ),
            status_metadata=(
                dict(value["status_metadata"])
                if isinstance(value.get("status_metadata"), Mapping)
                else {}
            ),
        )
    return ProviderResult(payload=dict(value), finish_reason="stop")


def _http_status(exc: BaseException) -> int | None:
    candidates = (
        getattr(exc, "status_code", None),
        getattr(getattr(exc, "response", None), "status_code", None),
    )
    for candidate in candidates:
        if (
            isinstance(candidate, int)
            and not isinstance(candidate, bool)
            and 100 <= candidate <= 599
        ):
            return candidate
    return None


def _retry_after(exc: BaseException) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if not isinstance(headers, Mapping):
        return None
    raw = headers.get("retry-after") or headers.get("Retry-After")
    if raw is None:
        return None
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        try:
            retry_at = parsedate_to_datetime(str(raw))
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=UTC)
            seconds = (retry_at - datetime.now(UTC)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return None
    seconds = float(seconds)
    if not math.isfinite(seconds):
        return None
    return max(0.0, min(seconds, 3600.0))


@lru_cache(maxsize=1)
def _openai_transient_exception_types() -> tuple[type[Exception], ...]:
    """Load only the SDK's documented typed transient failures, when installed."""

    try:
        from openai import APIConnectionError, APITimeoutError, RateLimitError
    except ImportError:
        return ()
    return (APIConnectionError, APITimeoutError, RateLimitError)


def classify_provider_failure(exc: BaseException) -> FailureInfo:
    if not isinstance(exc, Exception):
        return FailureInfo("interrupted", transient=True, invalid=False)
    status = _http_status(exc)
    retry_after = _retry_after(exc)
    if isinstance(exc, (TimeoutError, ConnectionError, *_openai_transient_exception_types())):
        return FailureInfo("transient_provider", True, False, status, retry_after)
    if status in TRANSIENT_HTTP_STATUSES:
        return FailureInfo("transient_provider", True, False, status, retry_after)
    if isinstance(exc, (ValueError, TypeError)):
        return FailureInfo("invalid_response", False, True, status, None)
    if status is not None:
        return FailureInfo("permanent_provider", False, False, status, None)
    return FailureInfo("permanent_provider", False, False, None, None)


def select_requests(
    requests: Sequence[FeedbackRequest],
    *,
    surfaces: Sequence[str] | None = None,
    categories: Sequence[str] | None = None,
    diagnoses: Sequence[str] | None = None,
    request_ids: Sequence[str] | None = None,
    max_requests: int | None = None,
) -> list[FeedbackRequest]:
    """Apply stable manifest-order filters to a request inventory."""

    if max_requests is not None and max_requests < 0:
        raise ValueError("max_requests must be non-negative")
    if max_requests == 0:
        return []
    allowed_surfaces = set(surfaces) if surfaces is not None else None
    allowed_categories = set(categories) if categories is not None else None
    allowed_diagnoses = set(diagnoses) if diagnoses is not None else None
    allowed_request_ids = set(request_ids) if request_ids is not None else None
    selected: list[FeedbackRequest] = []
    for request in sorted(requests, key=lambda item: item.request_order):
        if allowed_surfaces is not None and request.surface not in allowed_surfaces:
            continue
        if allowed_categories is not None and request.category_key not in allowed_categories:
            continue
        if allowed_request_ids is not None and request.request_id not in allowed_request_ids:
            continue
        if allowed_diagnoses is not None:
            request_diagnoses = {request.target_diagnosis}
            if request.comparison_diagnosis is not None:
                request_diagnoses.add(request.comparison_diagnosis)
            if request_diagnoses.isdisjoint(allowed_diagnoses):
                continue
        selected.append(request)
        if max_requests is not None and len(selected) >= max_requests:
            break
    return selected


def _timestamp(now: Callable[[], object] | None) -> str:
    value = now() if now is not None else datetime.now(UTC)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat()
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("now must return an ISO 8601 timestamp") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("now timestamps must include a UTC offset")
        return parsed.astimezone(UTC).isoformat()
    raise ValueError("now must return a datetime or non-empty ISO 8601 timestamp string")


def _reconcile_request(
    run_dir: Path,
    request: FeedbackRequest,
    ledger: LedgerStore,
    *,
    now: Callable[[], object] | None,
) -> bool:
    row = ledger.row(request.request_id)
    path = response_path_for_request(run_dir, request)
    try:
        record = validate_response_record(request, path)
    except (FileNotFoundError, OSError, ValueError, TypeError):
        if path.exists() or row["status"] in {"success", "skipped_existing"}:
            ledger.update(
                request.request_id,
                status="invalid",
                updated_at=_timestamp(now),
                failure_class="invalid_stored_response",
            )
        elif row["status"] == "running":
            reconciled_at = _timestamp(now)
            attempt = int(row["attempt_count"])
            checkpoint_path = (
                attempt_record_path(run_dir, request.request_id, attempt) if attempt else None
            )
            if checkpoint_path is None or not checkpoint_path.exists():
                if attempt == 0:
                    ledger.update(
                        request.request_id,
                        status="transient_failure",
                        updated_at=reconciled_at,
                        failure_class="stale_running",
                    )
                    return False
                write_attempt_record(
                    run_dir,
                    {
                        "request_id": request.request_id,
                        "attempt": attempt,
                        "status": "transient_failure",
                        "failure_class": "interrupted",
                        "http_status": None,
                        "retry_after_seconds": None,
                        "started_at": reconciled_at,
                        "finished_at": reconciled_at,
                        "latency_seconds": 0.0,
                    },
                )
                ledger.update(
                    request.request_id,
                    status="transient_failure",
                    updated_at=reconciled_at,
                    failure_class="stale_running",
                )
            else:
                try:
                    checkpoint = validate_attempt_record(
                        checkpoint_path,
                        expected_request_id=request.request_id,
                        expected_attempt=attempt,
                    )
                except (OSError, ValueError, TypeError):
                    ledger.update(
                        request.request_id,
                        status="invalid",
                        updated_at=reconciled_at,
                        failure_class="invalid_stored_response",
                    )
                else:
                    checkpoint_status = str(checkpoint["status"])
                    if checkpoint_status == "success":
                        ledger.update(
                            request.request_id,
                            status="invalid",
                            updated_at=reconciled_at,
                            failure_class="invalid_stored_response",
                        )
                    else:
                        ledger.update(
                            request.request_id,
                            status=checkpoint_status,
                            attempt_count=attempt,
                            updated_at=reconciled_at,
                            failure_class=str(checkpoint["failure_class"]),
                            http_status=(
                                int(checkpoint["http_status"])
                                if checkpoint["http_status"] is not None
                                else None
                            ),
                        )
        return False

    response_attempt = int(record["attempt_count"])
    if int(row["attempt_count"]) != response_attempt:
        ledger.update(
            request.request_id,
            status="invalid",
            updated_at=_timestamp(now),
            failure_class="invalid_stored_response",
        )
        return False
    checkpoint_path = attempt_record_path(run_dir, request.request_id, response_attempt)
    if checkpoint_path.exists():
        try:
            checkpoint = validate_attempt_record(
                checkpoint_path,
                expected_request_id=request.request_id,
                expected_attempt=response_attempt,
            )
        except (OSError, ValueError, TypeError):
            ledger.update(
                request.request_id,
                status="invalid",
                updated_at=_timestamp(now),
                failure_class="invalid_stored_response",
            )
            return False
        if checkpoint["status"] != "success":
            ledger.update(
                request.request_id,
                status="invalid",
                updated_at=_timestamp(now),
                failure_class="invalid_stored_response",
            )
            return False
    else:
        write_attempt_record(
            run_dir,
            {
                "request_id": request.request_id,
                "attempt": response_attempt,
                "status": "success",
                "failure_class": "",
                "http_status": None,
                "retry_after_seconds": None,
                "started_at": record["started_at"],
                "finished_at": record["finished_at"],
                "latency_seconds": record["latency_seconds"],
            },
        )
    ledger.update(
        request.request_id,
        status="skipped_existing",
        attempt_count=response_attempt,
        updated_at=_timestamp(now),
    )
    return True


def _attempt_delay(
    attempt_index: int,
    *,
    initial: float,
    maximum: float,
    jitter_fraction: float,
    retry_after: float | None,
    rng: random.Random,
    rng_lock: threading.Lock,
) -> float:
    base = min(maximum, initial * (2**attempt_index))
    with rng_lock:
        jitter = base * rng.uniform(0.0, jitter_fraction)
    calculated = min(maximum, base + jitter)
    return max(calculated, retry_after or 0.0)


def _execute_request(
    run_dir: Path,
    request: FeedbackRequest,
    adapter: ProviderAdapter,
    ledger: LedgerStore,
    *,
    max_attempts: int,
    retry_initial_delay_seconds: float,
    retry_max_delay_seconds: float,
    retry_jitter_fraction: float,
    sleep: Callable[[float], None],
    rng: random.Random,
    rng_lock: threading.Lock,
    now: Callable[[], object] | None,
    increment_call: Callable[[], None],
    stop_event: threading.Event,
) -> str:
    starting_row = ledger.row(request.request_id)
    starting_attempt_count = int(starting_row["attempt_count"])
    attempts_remaining = max(0, max_attempts - starting_attempt_count)
    if attempts_remaining == 0:
        status = str(starting_row["status"])
        if status not in {"invalid", "transient_failure", "permanent_failure"}:
            status = "permanent_failure"
            ledger.update(
                request.request_id,
                status=status,
                attempt_count=starting_attempt_count,
                updated_at=_timestamp(now),
                failure_class="attempt_cap",
            )
        return status

    for attempt_index in range(attempts_remaining):
        attempt = starting_attempt_count + attempt_index + 1
        started_at = _timestamp(now)
        started_monotonic = time.monotonic()
        ledger.update(
            request.request_id,
            status="running",
            attempt_count=attempt,
            updated_at=started_at,
        )
        try:
            increment_call()
            result = _coerce_provider_result(adapter.execute(request))
            payload = validate_response_payload(request.expected_response_type, result.payload)
        except BaseException as exc:
            if not isinstance(exc, Exception):
                stop_event.set()
            failure = classify_provider_failure(exc)
            finished_at = _timestamp(now)
            latency = max(0.0, time.monotonic() - started_monotonic)
            final_status = (
                "invalid"
                if failure.invalid
                else "transient_failure"
                if failure.transient
                else "permanent_failure"
            )
            write_attempt_record(
                run_dir,
                {
                    "request_id": request.request_id,
                    "attempt": attempt,
                    "status": final_status,
                    "failure_class": failure.failure_class,
                    "http_status": failure.http_status,
                    "retry_after_seconds": failure.retry_after_seconds,
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "latency_seconds": latency,
                },
            )
            has_retry = attempt_index + 1 < attempts_remaining
            if (
                failure.transient
                and isinstance(exc, Exception)
                and has_retry
                and not stop_event.is_set()
            ):
                ledger.update(
                    request.request_id,
                    status="transient_failure",
                    attempt_count=attempt,
                    updated_at=finished_at,
                    failure_class=failure.failure_class,
                    http_status=failure.http_status,
                )
                delay = _attempt_delay(
                    attempt_index,
                    initial=retry_initial_delay_seconds,
                    maximum=retry_max_delay_seconds,
                    jitter_fraction=retry_jitter_fraction,
                    retry_after=failure.retry_after_seconds,
                    rng=rng,
                    rng_lock=rng_lock,
                )
                sleep(delay)
                continue
            ledger.update(
                request.request_id,
                status=final_status,
                attempt_count=attempt,
                updated_at=finished_at,
                failure_class=failure.failure_class,
                http_status=failure.http_status,
            )
            if not isinstance(exc, Exception):
                raise
            return final_status

        # Once the provider result has passed schema validation, checkpoint failures
        # are local persistence failures, not provider failures. Let them propagate so
        # the outer interruption path can reconcile the durable response/attempt
        # prefix without overwriting a successful attempt or charging another call.
        finished_at = _timestamp(now)
        latency = max(0.0, time.monotonic() - started_monotonic)
        finish_status: dict[str, object] = {"finish_reason": result.finish_reason}
        if isinstance(result.status_metadata, Mapping):
            finish_status["status"] = result.status_metadata.get("status")
        record = {
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
            "parsed_payload": payload,
            "response_payload_sha256": sha256_json(payload),
            "provider_response_id": sanitize_provider_response_id(result.provider_response_id),
            "attempt_count": attempt,
            "started_at": started_at,
            "finished_at": finished_at,
            "latency_seconds": latency,
            "token_usage": sanitize_token_usage(result.token_usage),
            "safe_finish_status": sanitize_finish_status(finish_status),
        }
        write_response_record(run_dir, request, record)
        write_attempt_record(
            run_dir,
            {
                "request_id": request.request_id,
                "attempt": attempt,
                "status": "success",
                "failure_class": "",
                "http_status": None,
                "retry_after_seconds": None,
                "started_at": started_at,
                "finished_at": finished_at,
                "latency_seconds": latency,
            },
        )
        ledger.update(
            request.request_id,
            status="success",
            attempt_count=attempt,
            updated_at=finished_at,
        )
        return "success"
    raise AssertionError("unreachable")


def execute_feedback_run(
    run_dir: str | Path,
    adapter: ProviderAdapter | None,
    *,
    resume_mode: str = "skip_passing",
    max_workers: int = 4,
    max_attempts: int = 3,
    request_timeout_seconds: float = 120.0,
    surfaces: Sequence[str] | None = None,
    categories: Sequence[str] | None = None,
    diagnoses: Sequence[str] | None = None,
    request_ids: Sequence[str] | None = None,
    max_requests: int | None = None,
    dry_run: bool = False,
    retry_initial_delay_seconds: float = 1.0,
    retry_max_delay_seconds: float = 30.0,
    retry_jitter_fraction: float = 0.25,
    sleep: Callable[[float], None] = time.sleep,
    rng: random.Random | None = None,
    now: Callable[[], object] | None = None,
) -> ExecutionSummary:
    """Execute a manifest with hash-aware resume and bounded sliding-window concurrency."""

    mode = resume_mode.strip().lower()
    if mode not in VALID_RESUME_MODES:
        raise ValueError(f"Unsupported resume_mode {resume_mode!r}")
    if max_workers < 1 or max_attempts < 1 or request_timeout_seconds <= 0:
        raise ValueError("max_workers/max_attempts must be positive and timeout must be > 0")
    if retry_initial_delay_seconds < 0 or retry_max_delay_seconds < 0:
        raise ValueError("Retry delays must be non-negative")
    if retry_max_delay_seconds < retry_initial_delay_seconds:
        raise ValueError("retry_max_delay_seconds must be >= retry_initial_delay_seconds")
    if not 0 <= retry_jitter_fraction <= 0.25:
        raise ValueError("retry_jitter_fraction must be between 0 and 0.25")

    active_run_dir = Path(run_dir).resolve()
    if mode == "recompute":
        if dry_run:
            raise ValueError("recompute cannot be combined with dry_run")
        active_run_dir = create_recompute_run(active_run_dir)
    requests = read_manifest(active_run_dir / MANIFEST_FILENAME)
    ledger = LedgerStore(active_run_dir, requests)

    if mode == "repair_invalid":
        repairable: list[FeedbackRequest] = []
        for request in requests:
            response_path = response_path_for_request(active_run_dir, request)
            try:
                validate_response_record(request, response_path)
            except (FileNotFoundError, OSError, ValueError, TypeError):
                status = str(ledger.row(request.request_id)["status"])
                if (
                    status in REPAIRABLE_STATUSES
                    or status in {"success", "skipped_existing"}
                    or response_path.exists()
                ):
                    repairable.append(request)
            if not dry_run:
                _reconcile_request(active_run_dir, request, ledger, now=now)
        if not dry_run:
            repairable = [
                request
                for request in repairable
                if str(ledger.row(request.request_id)["status"]) in REPAIRABLE_STATUSES
            ]
        selected = select_requests(
            repairable,
            surfaces=surfaces,
            categories=categories,
            diagnoses=diagnoses,
            request_ids=request_ids,
            max_requests=max_requests,
        )
    else:
        selected = select_requests(
            requests,
            surfaces=surfaces,
            categories=categories,
            diagnoses=diagnoses,
            request_ids=request_ids,
            max_requests=max_requests,
        )

    if dry_run:
        runnable_count = 0
        skipped_count = 0
        for request in selected:
            try:
                validate_response_record(
                    request,
                    response_path_for_request(active_run_dir, request),
                )
            except (FileNotFoundError, OSError, ValueError, TypeError):
                runnable_count += 1
            else:
                skipped_count += 1
        return ExecutionSummary(
            run_dir=active_run_dir,
            resume_mode=mode,
            selected_count=len(selected),
            success_count=0,
            skipped_count=skipped_count,
            invalid_count=0,
            transient_failure_count=0,
            permanent_failure_count=0,
            pending_count=runnable_count,
            provider_calls=0,
            dry_run=True,
        )

    runnable: list[FeedbackRequest] = []
    skipped = 0
    for request in selected:
        if mode != "repair_invalid" and _reconcile_request(
            active_run_dir, request, ledger, now=now
        ):
            skipped += 1
            continue
        runnable.append(request)

    if runnable and adapter is None:
        raise ValueError("adapter is required unless --dry-run selects no provider work")

    outcomes: Counter[str] = Counter()
    provider_calls = 0
    counter_lock = threading.Lock()
    rng = rng or random.Random()
    rng_lock = threading.Lock()
    stop_event = threading.Event()

    def increment_call() -> None:
        nonlocal provider_calls
        with counter_lock:
            provider_calls += 1

    executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="feedback")
    futures: dict[Future[str], FeedbackRequest] = {}
    iterator = iter(runnable)

    def submit_one() -> bool:
        if stop_event.is_set():
            return False
        try:
            request = next(iterator)
        except StopIteration:
            return False
        future = executor.submit(
            _execute_request,
            active_run_dir,
            request,
            adapter,
            ledger,
            max_attempts=max_attempts,
            retry_initial_delay_seconds=retry_initial_delay_seconds,
            retry_max_delay_seconds=retry_max_delay_seconds,
            retry_jitter_fraction=retry_jitter_fraction,
            sleep=sleep,
            rng=rng,
            rng_lock=rng_lock,
            now=now,
            increment_call=increment_call,
            stop_event=stop_event,
        )
        futures[future] = request
        return True

    try:
        for _ in range(min(max_workers, len(runnable))):
            submit_one()
        while futures:
            done, _ = wait(tuple(futures), return_when=FIRST_COMPLETED)
            for future in sorted(done, key=lambda item: futures[item].request_order):
                futures.pop(future)
                outcomes[future.result()] += 1
                submit_one()
    except BaseException:
        stop_event.set()
        for future in futures:
            future.cancel()
        executor.shutdown(wait=True, cancel_futures=True)
        # Workers normally checkpoint their own failure. Reconcile any remaining
        # running row through the same response/attempt-first recovery path used on
        # resume. Never clear `running` unless its attempt checkpoint is durable:
        # leaving it stale is what lets the next invocation repair an interrupted
        # checkpoint write without creating an attempt-number gap.
        for request in runnable:
            row = ledger.row(request.request_id)
            if row["status"] == "running":
                try:
                    _reconcile_request(active_run_dir, request, ledger, now=now)
                except Exception:
                    pass
        raise
    else:
        executor.shutdown(wait=True)

    return ExecutionSummary(
        run_dir=active_run_dir,
        resume_mode=mode,
        selected_count=len(selected),
        success_count=outcomes["success"],
        skipped_count=skipped,
        invalid_count=outcomes["invalid"],
        transient_failure_count=outcomes["transient_failure"],
        permanent_failure_count=outcomes["permanent_failure"],
        pending_count=max(0, len(selected) - skipped - sum(outcomes.values())),
        provider_calls=provider_calls,
        dry_run=False,
    )
