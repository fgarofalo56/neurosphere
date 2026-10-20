"""Append-only in-memory registry of datasets, rubrics and judge configs (PRP-16 item 1).

Registering an existing ``(id, version)`` with identical content is an idempotent no-op; with
different content it raises ``VersionConflictError``. Nothing is ever mutated or removed: a
revision is a new version and every older version stays retrievable. A durable (Cosmos)
implementation is OPEN; this one is the contract and the test double.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from neurosphere_core.errors import StaleVersionError
from neurosphere_core.evaluation.registry.models import (
    DatasetItem,
    DatasetVersion,
    JudgeConfig,
    RubricVersion,
    compute_content_hash,
)

__all__ = [
    "EvaluationRegistry",
    "EvaluationRegistryProtocol",
    "VersionConflictError",
    "VersionedRegistry",
]


class VersionConflictError(StaleVersionError):
    """An existing (id, version) was re-registered with different content."""

    def __init__(self, kind: str, ident: str, version: str) -> None:
        super().__init__(
            f"{kind} {ident!r} version {version!r} already exists with different content",
            reason="version_content_conflict",
        )


class VersionedRegistry[T]:
    """Append-only store of immutable versioned values of one kind."""

    def __init__(
        self,
        kind: str,
        id_of: Callable[[T], str],
        version_of: Callable[[T], str],
        content_of: Callable[[T], Any],
    ) -> None:
        self._kind = kind
        self._id_of = id_of
        self._version_of = version_of
        self._content_of = content_of
        self._by_id: dict[str, dict[str, T]] = {}

    def register(self, value: T) -> T:
        """Add a version. Identical re-registration returns the stored value (no-op)."""
        ident, version = self._id_of(value), self._version_of(value)
        versions = self._by_id.setdefault(ident, {})
        existing = versions.get(version)
        if existing is None:
            versions[version] = value
            return value
        if self._content_of(existing) != self._content_of(value):
            raise VersionConflictError(self._kind, ident, version)
        return existing

    def get(self, ident: str, version: str) -> T | None:
        return self._by_id.get(ident, {}).get(version)

    def versions(self, ident: str) -> tuple[T, ...]:
        """All versions of ``ident`` in registration order (oldest first)."""
        return tuple(self._by_id.get(ident, {}).values())

    def latest(self, ident: str) -> T | None:
        found = self.versions(ident)
        return found[-1] if found else None

    def ids(self) -> tuple[str, ...]:
        return tuple(self._by_id)


@runtime_checkable
class EvaluationRegistryProtocol(Protocol):
    datasets: VersionedRegistry[DatasetVersion]
    rubrics: VersionedRegistry[RubricVersion]
    judge_configs: VersionedRegistry[JudgeConfig]


class EvaluationRegistry:
    """Datasets, rubrics and judge configs, each append-only and versioned."""

    def __init__(self) -> None:
        self.datasets: VersionedRegistry[DatasetVersion] = VersionedRegistry(
            "dataset",
            lambda d: d.dataset_id,
            lambda d: d.version,
            # created_at is bookkeeping; identical content means identical items and metadata.
            lambda d: d.model_dump(mode="json", exclude={"created_at"}),
        )
        self.rubrics: VersionedRegistry[RubricVersion] = VersionedRegistry(
            "rubric",
            lambda r: r.rubric_id,
            lambda r: r.version,
            lambda r: r.model_dump(mode="json"),
        )
        self.judge_configs: VersionedRegistry[JudgeConfig] = VersionedRegistry(
            "judge_config",
            lambda j: j.judge_config_id,
            lambda j: j.version,
            lambda j: j.model_dump(mode="json"),
        )

    def revise_dataset(self, dataset_id: str, new_version: str, **changes: Any) -> DatasetVersion:
        """Register ``new_version`` derived from the latest version with ``changes`` applied."""
        base = self._latest_or_raise(self.datasets, dataset_id)
        fields: dict[str, Any] = {**base.model_dump(), **changes, "version": new_version}
        items = tuple(
            i if isinstance(i, DatasetItem) else DatasetItem.model_validate(i)
            for i in fields["items"]
        )
        fields["items"] = items
        fields["content_hash"] = compute_content_hash(
            fields["kind"], tuple(fields["dimensions"]), items
        )
        revised = DatasetVersion.model_validate(fields)
        return self.datasets.register(revised)

    def revise_rubric(self, rubric_id: str, new_version: str, **changes: Any) -> RubricVersion:
        base = self._latest_or_raise(self.rubrics, rubric_id)
        revised = RubricVersion.model_validate(
            {**base.model_dump(), **changes, "version": new_version}
        )
        return self.rubrics.register(revised)

    def revise_judge_config(
        self, judge_config_id: str, new_version: str, **changes: Any
    ) -> JudgeConfig:
        base = self._latest_or_raise(self.judge_configs, judge_config_id)
        revised = JudgeConfig.model_validate(
            {**base.model_dump(), **changes, "version": new_version}
        )
        return self.judge_configs.register(revised)

    @staticmethod
    def _latest_or_raise[T](registry: VersionedRegistry[T], ident: str) -> T:
        base = registry.latest(ident)
        if base is None:
            raise KeyError(f"unknown id {ident!r}; register a first version before revising")
        return base
