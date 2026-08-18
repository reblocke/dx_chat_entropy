from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode
from yaml.resolver import BaseResolver

VALID_SURFACES = (
    "overall/general",
    "overall/specific",
    "differential/general",
    "differential/specific",
)
VALID_CATEGORY_MODES = ("only_overall", "all")
_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "prompt_schema_version",
        "response_schema_version",
        "correct_diagnosis",
        "diagnoses",
        "categories",
        "default_category_mode",
        "enabled_surfaces",
        "default_model_profile",
        "model_profiles",
        "output_root",
        "runtime_defaults",
    }
)
_RUNTIME_FIELDS = frozenset(
    {
        "max_workers",
        "request_timeout_seconds",
        "max_attempts",
        "retry_initial_delay_seconds",
        "retry_max_delay_seconds",
        "retry_jitter_fraction",
    }
)


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that fails instead of silently replacing duplicate keys."""


def _construct_unique_mapping(
    loader: _UniqueKeyLoader, node: MappingNode, deep: bool = False
) -> dict[object, object]:
    loader.flatten_mapping(node)
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable mapping key",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping)


@dataclass(frozen=True)
class FindingSpec:
    finding: str
    status: str


@dataclass(frozen=True)
class CategorySpec:
    key: str
    description: str
    order: int
    details: tuple[FindingSpec, ...]
    detail_sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModelProfile:
    name: str
    model_id: str
    settings: dict[str, object]


@dataclass(frozen=True)
class RuntimeDefaults:
    max_workers: int
    request_timeout_seconds: float
    max_attempts: int
    retry_initial_delay_seconds: float
    retry_max_delay_seconds: float
    retry_jitter_fraction: float


@dataclass(frozen=True)
class FeedbackConfig:
    schema_version: str
    prompt_schema_version: str
    response_schema_version: str
    correct_diagnosis: str
    diagnoses: tuple[str, ...]
    categories: tuple[CategorySpec, ...]
    default_category_mode: str
    enabled_surfaces: tuple[str, ...]
    default_model_profile: str
    model_profiles: tuple[ModelProfile, ...]
    output_root: Path
    runtime_defaults: RuntimeDefaults

    @property
    def differential_diagnoses(self) -> tuple[str, ...]:
        """Notebook-compatible name; includes the correct diagnosis first."""

        return self.diagnoses

    @property
    def alternatives(self) -> tuple[str, ...]:
        return tuple(
            diagnosis for diagnosis in self.diagnoses if diagnosis != self.correct_diagnosis
        )

    @property
    def only_overall(self) -> bool:
        return self.default_category_mode == "only_overall"

    @property
    def categories_by_key(self) -> dict[str, CategorySpec]:
        return {category.key: category for category in self.categories}

    def category(self, key: str) -> CategorySpec:
        try:
            return self.categories_by_key[key]
        except KeyError as exc:
            raise ValueError(f"Unknown feedback category: {key!r}") from exc

    def categories_for_mode(
        self, category_mode: str | bool | None = None
    ) -> tuple[CategorySpec, ...]:
        mode = normalize_category_mode(
            self.default_category_mode if category_mode is None else category_mode
        )
        if mode == "only_overall":
            return (self.category("subjective-and-historical"),)
        return self.categories

    def model(self, profile_name: str | None = None) -> ModelProfile:
        selected = profile_name or self.default_model_profile
        for profile in self.model_profiles:
            if profile.name == selected:
                return profile
        raise ValueError(f"Unknown feedback model profile: {selected!r}")


def normalize_category_mode(value: str | bool) -> str:
    if isinstance(value, bool):
        return "only_overall" if value else "all"
    normalized = value.strip().lower().replace("-", "_")
    aliases = {
        "default": "only_overall",
        "combined": "only_overall",
        "subjective_and_historical": "only_overall",
        "all_categories": "all",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in VALID_CATEGORY_MODES:
        raise ValueError(
            f"Unsupported category mode {value!r}; expected one of {VALID_CATEGORY_MODES}"
        )
    return normalized


def _object(value: object, *, path: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise ValueError(f"{path} keys must be strings")
    return dict(value)


def _reject_unknown_fields(
    value: Mapping[str, object], *, allowed: frozenset[str], path: str
) -> None:
    unexpected = sorted(set(value) - allowed)
    if unexpected:
        raise ValueError(f"{path} contains unsupported field(s): {unexpected}")


def _sequence(value: object, *, path: str) -> list[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{path} must be an array")
    return list(value)


def _nonempty_string(value: object, *, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{path} must be a non-empty string")
    return value


def _unique_strings(value: object, *, path: str) -> tuple[str, ...]:
    items = tuple(
        _nonempty_string(item, path=f"{path}[{index}]")
        for index, item in enumerate(_sequence(value, path=path))
    )
    if len(items) != len(set(items)):
        raise ValueError(f"{path} contains duplicates")
    return items


def _load_raw_config(path: Path) -> dict[str, Any]:
    try:
        parsed = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except FileNotFoundError:
        raise
    except yaml.YAMLError as exc:
        raise ValueError(f"{path} must contain valid YAML: {exc}") from exc
    return _object(parsed, path=str(path))


def _parse_categories(value: object) -> tuple[CategorySpec, ...]:
    raw_categories = _sequence(value, path="categories")
    if not raw_categories:
        raise ValueError("categories must not be empty")

    partial: list[tuple[str, str, tuple[FindingSpec, ...], tuple[str, ...]]] = []
    keys: list[str] = []
    for index, raw_value in enumerate(raw_categories):
        path = f"categories[{index}]"
        raw = _object(raw_value, path=path)
        _reject_unknown_fields(
            raw,
            allowed=frozenset({"key", "description", "details", "detail_sources"}),
            path=path,
        )
        key = _nonempty_string(raw.get("key"), path=f"{path}.key")
        description = _nonempty_string(raw.get("description"), path=f"{path}.description")
        detail_sources = tuple(
            _nonempty_string(source, path=f"{path}.detail_sources")
            for source in _sequence(raw.get("detail_sources", []), path=f"{path}.detail_sources")
        )
        if len(detail_sources) != len(set(detail_sources)):
            raise ValueError(f"{path}.detail_sources contains duplicates")

        details: list[FindingSpec] = []
        for detail_index, raw_detail_value in enumerate(
            _sequence(raw.get("details", []), path=f"{path}.details")
        ):
            detail_path = f"{path}.details[{detail_index}]"
            raw_detail = _object(raw_detail_value, path=detail_path)
            _reject_unknown_fields(
                raw_detail,
                allowed=frozenset({"finding", "status"}),
                path=detail_path,
            )
            finding = _nonempty_string(raw_detail.get("finding"), path=f"{detail_path}.finding")
            status = _nonempty_string(raw_detail.get("status"), path=f"{detail_path}.status")
            if status not in {"present", "absent"}:
                raise ValueError(f"{detail_path}.status must be 'present' or 'absent'")
            details.append(FindingSpec(finding=finding, status=status))

        finding_names = [detail.finding for detail in details]
        if len(finding_names) != len(set(finding_names)):
            raise ValueError(f"{path}.details contains duplicate findings")

        if bool(details) == bool(detail_sources):
            raise ValueError(f"{path} must define exactly one of details or detail_sources")
        keys.append(key)
        partial.append((key, description, tuple(details), detail_sources))

    if len(keys) != len(set(keys)):
        raise ValueError("categories contains duplicate keys")

    raw_by_key = {key: (details, sources) for key, _, details, sources in partial}
    resolved: dict[str, tuple[FindingSpec, ...]] = {}

    def resolve(key: str, trail: tuple[str, ...] = ()) -> tuple[FindingSpec, ...]:
        if key in resolved:
            return resolved[key]
        if key not in raw_by_key:
            raise ValueError(f"Unknown category detail source: {key!r}")
        if key in trail:
            raise ValueError(f"Cyclic category detail_sources: {[*trail, key]}")
        details, sources = raw_by_key[key]
        if sources:
            details = tuple(
                detail for source in sources for detail in resolve(source, (*trail, key))
            )
        finding_names = [detail.finding for detail in details]
        if len(finding_names) != len(set(finding_names)):
            raise ValueError(f"Category {key!r} resolves to duplicate findings")
        resolved[key] = details
        return details

    return tuple(
        CategorySpec(
            key=key,
            description=description,
            order=index,
            details=resolve(key),
            detail_sources=sources,
        )
        for index, (key, description, _, sources) in enumerate(partial, start=1)
    )


def _parse_model_profiles(value: object) -> tuple[ModelProfile, ...]:
    raw_profiles = _object(value, path="model_profiles")
    if not raw_profiles:
        raise ValueError("model_profiles must not be empty")
    profiles: list[ModelProfile] = []
    for name, raw_value in raw_profiles.items():
        profile_name = _nonempty_string(name, path="model_profiles key")
        raw = _object(raw_value, path=f"model_profiles.{profile_name}")
        _reject_unknown_fields(
            raw,
            allowed=frozenset({"model_id", "settings"}),
            path=f"model_profiles.{profile_name}",
        )
        model_id = _nonempty_string(
            raw.get("model_id"), path=f"model_profiles.{profile_name}.model_id"
        )
        settings = _object(raw.get("settings", {}), path=f"model_profiles.{profile_name}.settings")
        try:
            json.dumps(settings, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"model_profiles.{profile_name}.settings must contain JSON values"
            ) from exc
        model_lower = model_id.lower()
        reasoning_model = model_lower.startswith(("o3", "o4", "gpt-5"))
        supported_settings = {"reasoning_effort"} if reasoning_model else {"temperature"}
        unsupported_settings = sorted(set(settings) - supported_settings)
        if unsupported_settings:
            raise ValueError(
                f"model_profiles.{profile_name}.settings contains unsupported setting(s): "
                f"{unsupported_settings}"
            )
        if reasoning_model:
            reasoning_effort = settings.get("reasoning_effort")
            if reasoning_effort not in {"low", "medium", "high"}:
                raise ValueError(
                    f"model_profiles.{profile_name}.settings.reasoning_effort must be "
                    "'low', 'medium', or 'high'"
                )
        else:
            temperature = settings.get("temperature")
            if (
                isinstance(temperature, bool)
                or not isinstance(temperature, (int, float))
                or not 0 <= float(temperature) <= 2
            ):
                raise ValueError(
                    f"model_profiles.{profile_name}.settings.temperature must be a number "
                    "between 0 and 2"
                )
        profiles.append(ModelProfile(name=profile_name, model_id=model_id, settings=settings))
    return tuple(profiles)


def _positive_int(value: object, *, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{path} must be a positive integer")
    return value


def _nonnegative_number(value: object, *, path: str, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{path} must be finite")
    if (positive and number <= 0) or (not positive and number < 0):
        qualifier = "positive" if positive else "non-negative"
        raise ValueError(f"{path} must be {qualifier}")
    return number


def load_feedback_config(path: str | Path) -> FeedbackConfig:
    """Load and validate the versioned YAML feedback specification."""

    config_path = Path(path)
    raw = _load_raw_config(config_path)
    _reject_unknown_fields(raw, allowed=_TOP_LEVEL_FIELDS, path="feedback configuration")
    schema_version = _nonempty_string(raw.get("schema_version"), path="schema_version")
    prompt_schema_version = _nonempty_string(
        raw.get("prompt_schema_version"), path="prompt_schema_version"
    )
    response_schema_version = _nonempty_string(
        raw.get("response_schema_version"), path="response_schema_version"
    )
    correct_diagnosis = _nonempty_string(raw.get("correct_diagnosis"), path="correct_diagnosis")
    diagnoses = _unique_strings(raw.get("diagnoses"), path="diagnoses")
    if not diagnoses or diagnoses[0] != correct_diagnosis:
        raise ValueError("diagnoses must contain correct_diagnosis as its first entry")

    categories = _parse_categories(raw.get("categories"))
    category_keys = tuple(category.key for category in categories)
    if "subjective-and-historical" not in category_keys:
        raise ValueError("categories must define 'subjective-and-historical'")

    default_category_mode = normalize_category_mode(
        _nonempty_string(raw.get("default_category_mode"), path="default_category_mode")
    )
    enabled_surfaces = _unique_strings(raw.get("enabled_surfaces"), path="enabled_surfaces")
    if not enabled_surfaces:
        raise ValueError("enabled_surfaces must not be empty")
    unknown_surfaces = sorted(set(enabled_surfaces) - set(VALID_SURFACES))
    if unknown_surfaces:
        raise ValueError(f"enabled_surfaces contains unsupported values: {unknown_surfaces}")

    model_profiles = _parse_model_profiles(raw.get("model_profiles"))
    default_model_profile = _nonempty_string(
        raw.get("default_model_profile"), path="default_model_profile"
    )
    if default_model_profile not in {profile.name for profile in model_profiles}:
        raise ValueError("default_model_profile does not name a configured model profile")

    output_root = Path(_nonempty_string(raw.get("output_root"), path="output_root"))
    if output_root.is_absolute() or ".." in output_root.parts:
        raise ValueError("output_root must be a safe repository-relative path")

    runtime = _object(raw.get("runtime_defaults"), path="runtime_defaults")
    _reject_unknown_fields(runtime, allowed=_RUNTIME_FIELDS, path="runtime_defaults")
    runtime_defaults = RuntimeDefaults(
        max_workers=_positive_int(runtime.get("max_workers"), path="runtime_defaults.max_workers"),
        request_timeout_seconds=_nonnegative_number(
            runtime.get("request_timeout_seconds"),
            path="runtime_defaults.request_timeout_seconds",
            positive=True,
        ),
        max_attempts=_positive_int(
            runtime.get("max_attempts"), path="runtime_defaults.max_attempts"
        ),
        retry_initial_delay_seconds=_nonnegative_number(
            runtime.get("retry_initial_delay_seconds"),
            path="runtime_defaults.retry_initial_delay_seconds",
            positive=True,
        ),
        retry_max_delay_seconds=_nonnegative_number(
            runtime.get("retry_max_delay_seconds"),
            path="runtime_defaults.retry_max_delay_seconds",
            positive=True,
        ),
        retry_jitter_fraction=_nonnegative_number(
            runtime.get("retry_jitter_fraction"),
            path="runtime_defaults.retry_jitter_fraction",
        ),
    )
    if runtime_defaults.retry_max_delay_seconds < runtime_defaults.retry_initial_delay_seconds:
        raise ValueError("retry_max_delay_seconds must be >= retry_initial_delay_seconds")
    if runtime_defaults.retry_jitter_fraction > 0.25:
        raise ValueError("retry_jitter_fraction must be between 0 and 0.25")

    return FeedbackConfig(
        schema_version=schema_version,
        prompt_schema_version=prompt_schema_version,
        response_schema_version=response_schema_version,
        correct_diagnosis=correct_diagnosis,
        diagnoses=diagnoses,
        categories=categories,
        default_category_mode=default_category_mode,
        enabled_surfaces=enabled_surfaces,
        default_model_profile=default_model_profile,
        model_profiles=model_profiles,
        output_root=output_root,
        runtime_defaults=runtime_defaults,
    )
