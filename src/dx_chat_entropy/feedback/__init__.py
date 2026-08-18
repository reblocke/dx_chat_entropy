"""Restartable, manifest-first feedback-generation pipeline."""

from .audit import AuditFinding, AuditResult, audit_feedback_run
from .config import FeedbackConfig, load_feedback_config
from .manifest import (
    ManifestBuild,
    build_feedback_requests,
    build_or_load_manifest,
    prompt_sha256,
    read_manifest,
)
from .models import (
    DifferentialFeedbackResponse,
    EvidenceItem,
    FeedbackRequest,
    OverallFeedbackResponse,
    ProviderResult,
    validate_response_payload,
)
from .runtime import (
    ExecutionSummary,
    FakeProviderAdapter,
    OpenAIProviderAdapter,
    ProviderAdapter,
    execute_feedback_run,
    select_requests,
)
from .workbooks import WorkbookMaterializationError, materialize_workbooks

__all__ = [
    "AuditFinding",
    "AuditResult",
    "DifferentialFeedbackResponse",
    "EvidenceItem",
    "ExecutionSummary",
    "FakeProviderAdapter",
    "FeedbackConfig",
    "FeedbackRequest",
    "ManifestBuild",
    "OpenAIProviderAdapter",
    "OverallFeedbackResponse",
    "ProviderAdapter",
    "ProviderResult",
    "WorkbookMaterializationError",
    "audit_feedback_run",
    "build_feedback_requests",
    "build_or_load_manifest",
    "execute_feedback_run",
    "load_feedback_config",
    "materialize_workbooks",
    "prompt_sha256",
    "read_manifest",
    "select_requests",
    "validate_response_payload",
]
