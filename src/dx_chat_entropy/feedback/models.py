from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

MANIFEST_COLUMNS = (
    "request_order",
    "request_id",
    "run_id",
    "surface",
    "correct_diagnosis",
    "target_diagnosis",
    "comparison_diagnosis",
    "diagnosis_order",
    "category_key",
    "category_order",
    "config_schema_version",
    "prompt_schema_version",
    "response_schema_version",
    "model_profile",
    "model_id",
    "model_settings",
    "messages",
    "prompt_sha256",
    "expected_response_type",
    "response_path",
    "workbook_path",
    "sheet_name",
    "initial_status",
)


def canonical_json(value: object) -> str:
    """Serialize an identity-bearing value deterministically."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _parse_json_object(value: object, *, field_name: str) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{field_name} is not valid JSON: {exc}") from exc
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a JSON object")
    return dict(value)


def _parse_messages(value: object) -> list[dict[str, str]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"messages is not valid JSON: {exc}") from exc
    if not isinstance(value, list):
        raise ValueError("messages must be a JSON array")

    messages: list[dict[str, str]] = []
    for index, message in enumerate(value):
        if not isinstance(message, Mapping):
            raise ValueError(f"messages[{index}] must be an object")
        if set(message) != {"role", "content"}:
            raise ValueError(f"messages[{index}] must contain only role and content")
        role = message["role"]
        content = message["content"]
        if not isinstance(role, str) or not isinstance(content, str):
            raise ValueError(f"messages[{index}] role and content must be strings")
        messages.append({"role": role, "content": content})
    if not messages:
        raise ValueError("messages must not be empty")
    return messages


@dataclass(frozen=True)
class FeedbackRequest:
    request_order: int
    request_id: str
    run_id: str
    surface: str
    correct_diagnosis: str
    target_diagnosis: str
    comparison_diagnosis: str | None
    diagnosis_order: int
    category_key: str
    category_order: int
    config_schema_version: str
    prompt_schema_version: str
    response_schema_version: str
    model_profile: str
    model_id: str
    model_settings: dict[str, object]
    messages: list[dict[str, str]]
    prompt_sha256: str
    expected_response_type: str
    response_path: str
    workbook_path: str
    sheet_name: str
    initial_status: str = "pending"

    def to_manifest_row(self) -> dict[str, object]:
        """Return the exact CSV representation used by the durable manifest."""

        return {
            "request_order": self.request_order,
            "request_id": self.request_id,
            "run_id": self.run_id,
            "surface": self.surface,
            "correct_diagnosis": self.correct_diagnosis,
            "target_diagnosis": self.target_diagnosis,
            "comparison_diagnosis": self.comparison_diagnosis or "",
            "diagnosis_order": self.diagnosis_order,
            "category_key": self.category_key,
            "category_order": self.category_order,
            "config_schema_version": self.config_schema_version,
            "prompt_schema_version": self.prompt_schema_version,
            "response_schema_version": self.response_schema_version,
            "model_profile": self.model_profile,
            "model_id": self.model_id,
            "model_settings": canonical_json(self.model_settings),
            "messages": canonical_json(self.messages),
            "prompt_sha256": self.prompt_sha256,
            "expected_response_type": self.expected_response_type,
            "response_path": self.response_path,
            "workbook_path": self.workbook_path,
            "sheet_name": self.sheet_name,
            "initial_status": self.initial_status,
        }

    @classmethod
    def from_manifest_row(cls, row: Mapping[str, object]) -> FeedbackRequest:
        missing = [column for column in MANIFEST_COLUMNS if column not in row]
        if missing:
            raise ValueError(f"Manifest row is missing required columns: {missing}")

        comparison = str(row["comparison_diagnosis"] or "").strip()
        return cls(
            request_order=int(row["request_order"]),
            request_id=str(row["request_id"]),
            run_id=str(row["run_id"]),
            surface=str(row["surface"]),
            correct_diagnosis=str(row["correct_diagnosis"]),
            target_diagnosis=str(row["target_diagnosis"]),
            comparison_diagnosis=comparison or None,
            diagnosis_order=int(row["diagnosis_order"]),
            category_key=str(row["category_key"]),
            category_order=int(row["category_order"]),
            config_schema_version=str(row["config_schema_version"]),
            prompt_schema_version=str(row["prompt_schema_version"]),
            response_schema_version=str(row["response_schema_version"]),
            model_profile=str(row["model_profile"]),
            model_id=str(row["model_id"]),
            model_settings=_parse_json_object(row["model_settings"], field_name="model_settings"),
            messages=_parse_messages(row["messages"]),
            prompt_sha256=str(row["prompt_sha256"]),
            expected_response_type=str(row["expected_response_type"]),
            response_path=str(row["response_path"]),
            workbook_path=str(row["workbook_path"]),
            sheet_name=str(row["sheet_name"]),
            initial_status=str(row["initial_status"]),
        )


@dataclass(frozen=True)
class ProviderResult:
    """Provider-independent successful response returned to the executor."""

    payload: dict[str, object]
    provider_response_id: str | None = None
    token_usage: dict[str, object] | None = None
    finish_reason: str | None = None
    status_metadata: dict[str, object] | None = None

    @property
    def parsed_payload(self) -> dict[str, Any]:
        """Compatibility alias emphasizing that ``payload`` is already parsed."""

        return self.payload

    @property
    def usage(self) -> dict[str, object] | None:
        return self.token_usage

    @property
    def safe_metadata(self) -> dict[str, object] | None:
        return self.status_metadata


@dataclass(frozen=True)
class EvidenceItem:
    """One required ranked evidence item in a validated provider response."""

    finding: str
    explanation: str
    abbreviation_expansion: dict[str, str]


@dataclass(frozen=True)
class OverallFeedbackResponse:
    """Validated overall-feedback response with exactly five items per direction."""

    for_diagnosis_strongest_evidence: tuple[EvidenceItem, ...]
    against_diagnosis_strongest_evidence: tuple[EvidenceItem, ...]
    summary: str

    @classmethod
    def validate(cls, payload: object) -> OverallFeedbackResponse:
        normalized = validate_response_payload("overall", payload)
        return cls(
            for_diagnosis_strongest_evidence=_items_from_normalized(
                normalized["for_diagnosis_strongest_evidence"]
            ),
            against_diagnosis_strongest_evidence=_items_from_normalized(
                normalized["against_diagnosis_strongest_evidence"]
            ),
            summary=str(normalized["summary"]),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "for_diagnosis_strongest_evidence": _items_to_dict(
                self.for_diagnosis_strongest_evidence
            ),
            "against_diagnosis_strongest_evidence": _items_to_dict(
                self.against_diagnosis_strongest_evidence
            ),
            "summary": self.summary,
        }


@dataclass(frozen=True)
class DifferentialFeedbackResponse:
    """Validated pairwise-feedback response with exactly five items per diagnosis."""

    diagnosisA_strongest_evidence: tuple[EvidenceItem, ...]
    diagnosisB_strongest_evidence: tuple[EvidenceItem, ...]
    summary: str

    @classmethod
    def validate(cls, payload: object) -> DifferentialFeedbackResponse:
        normalized = validate_response_payload("differential", payload)
        return cls(
            diagnosisA_strongest_evidence=_items_from_normalized(
                normalized["diagnosisA_strongest_evidence"]
            ),
            diagnosisB_strongest_evidence=_items_from_normalized(
                normalized["diagnosisB_strongest_evidence"]
            ),
            summary=str(normalized["summary"]),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "diagnosisA_strongest_evidence": _items_to_dict(self.diagnosisA_strongest_evidence),
            "diagnosisB_strongest_evidence": _items_to_dict(self.diagnosisB_strongest_evidence),
            "summary": self.summary,
        }


_RESPONSE_LIST_KEYS = {
    "overall": (
        "for_diagnosis_strongest_evidence",
        "against_diagnosis_strongest_evidence",
    ),
    "differential": (
        "diagnosisA_strongest_evidence",
        "diagnosisB_strongest_evidence",
    ),
}


def _validate_evidence_items(value: object, *, path: str) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{path} must be an array")
    if len(value) != 5:
        raise ValueError(f"{path} must contain exactly 5 items")

    normalized: list[dict[str, object]] = []
    for index, item in enumerate(value):
        item_path = f"{path}[{index}]"
        if not isinstance(item, Mapping):
            raise ValueError(f"{item_path} must be an object")
        required = {"finding", "explanation", "abbreviation_expansion"}
        missing = sorted(required - set(item))
        if missing:
            raise ValueError(f"{item_path} is missing required fields: {missing}")
        finding = item["finding"]
        explanation = item["explanation"]
        abbreviation_expansion = item["abbreviation_expansion"]
        if not isinstance(finding, str) or not finding.strip():
            raise ValueError(f"{item_path}.finding must be a non-empty string")
        if not isinstance(explanation, str) or not explanation.strip():
            raise ValueError(f"{item_path}.explanation must be a non-empty string")
        if not isinstance(abbreviation_expansion, Mapping):
            raise ValueError(f"{item_path}.abbreviation_expansion must be an object")
        if set(item) != required:
            raise ValueError(f"{item_path} must contain exactly the required fields")
        normalized_abbreviations: dict[str, str] = {}
        for abbreviation, expansion in abbreviation_expansion.items():
            if not isinstance(abbreviation, str) or not isinstance(expansion, str):
                raise ValueError(
                    f"{item_path}.abbreviation_expansion keys and values must be strings"
                )
            normalized_abbreviations[abbreviation] = expansion
        normalized.append(
            {
                "finding": finding,
                "explanation": explanation,
                "abbreviation_expansion": normalized_abbreviations,
            }
        )
    return normalized


def _items_from_normalized(value: object) -> tuple[EvidenceItem, ...]:
    if not isinstance(value, list):  # pragma: no cover - internal invariant.
        raise TypeError("Normalized evidence must be a list")
    return tuple(
        EvidenceItem(
            finding=str(item["finding"]),
            explanation=str(item["explanation"]),
            abbreviation_expansion=dict(item["abbreviation_expansion"]),
        )
        for item in value
    )


def _items_to_dict(items: Sequence[EvidenceItem]) -> list[dict[str, object]]:
    return [
        {
            "finding": item.finding,
            "explanation": item.explanation,
            "abbreviation_expansion": dict(item.abbreviation_expansion),
        }
        for item in items
    ]


def validate_response_payload(
    expected_response_type: str,
    payload: object,
) -> dict[str, Any]:
    """Validate and normalize the notebook's two structured response shapes.

    Validation intentionally requires the fields declared by the notebook prompt,
    including the otherwise-unused summary and abbreviation mapping. Extra top-level
    or evidence-item fields are ignored when the normalized record is returned.
    """

    response_type = expected_response_type.strip().lower()
    response_type = {
        "overall_response": "overall",
        "differential_response": "differential",
    }.get(response_type, response_type)
    if response_type not in _RESPONSE_LIST_KEYS:
        raise ValueError(f"Unsupported expected response type: {expected_response_type!r}")
    if not isinstance(payload, Mapping):
        raise ValueError("Response payload must be a JSON object")

    first_key, second_key = _RESPONSE_LIST_KEYS[response_type]
    required_top_level = {first_key, second_key, "summary"}
    missing = [key for key in (first_key, second_key, "summary") if key not in payload]
    if missing:
        raise ValueError(f"Response payload is missing required fields: {missing}")
    if set(payload) != required_top_level:
        raise ValueError("Response payload must contain exactly the required fields")
    summary = payload["summary"]
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("summary must be a non-empty string")

    return {
        first_key: _validate_evidence_items(payload[first_key], path=first_key),
        second_key: _validate_evidence_items(payload[second_key], path=second_key),
        "summary": summary,
    }
