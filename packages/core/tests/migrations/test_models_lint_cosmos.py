"""Models, lint rules, snapshot hashing, protocol conformance and Cosmos error mapping."""

from __future__ import annotations

from typing import Any

import pytest
from azure.cosmos.exceptions import CosmosHttpResponseError
from neurosphere_core.errors import DependencyTransientError, StaleVersionError
from neurosphere_core.migrations import (
    AnalyticsSchemaStore,
    AppliedStep,
    DocumentStore,
    InMemoryAnalyticsSchemaStore,
    InMemoryDocumentStore,
    InMemoryLedgerStore,
    Lease,
    LedgerStore,
    MigrationLedger,
    MigrationStep,
    MigrationTarget,
    canonical_json,
    lint_migrations,
    snapshot_hash,
)
from neurosphere_core.migrations.cosmos import _translate
from neurosphere_core.migrations.sample_steps import sample_steps
from pydantic import ValidationError


def step(**overrides: Any) -> MigrationStep:
    base: dict[str, Any] = {
        "id": "s1",
        "version": 1,
        "target": MigrationTarget.COSMOS_DOCUMENTS,
        "name": "c",
        "description": "d",
        "release": "0.2.0",
        "up": lambda d: d,
        "down": lambda d: d,
    }
    return MigrationStep(**{**base, **overrides})


def rules(steps: list[MigrationStep]) -> set[str]:
    return {v.rule for v in lint_migrations(steps)}


def test_models_reject_extra_fields() -> None:
    with pytest.raises(ValidationError):
        step(bogus=1)
    with pytest.raises(ValidationError):
        MigrationLedger.model_validate(
            {"id": "x", "target": "cosmos_documents", "name": "c", "bogus": 1}
        )
    with pytest.raises(ValidationError):
        Lease.model_validate({"owner": "o", "expires_at": "2030-01-01T00:00:00Z", "bogus": 1})
    with pytest.raises(ValidationError):
        AppliedStep.model_validate(
            {"step_id": "s", "version": 1, "applied_at": "2030-01-01T00:00:00Z", "bogus": 1}
        )


def test_sample_steps_are_clean() -> None:
    assert lint_migrations(sample_steps("c")) == []


def test_same_release_remove_fails_later_release_passes() -> None:
    deprecate = step(id="a", version=1, deprecates=["old"])
    same = step(id="b", version=2, release="0.2.0", removes=["old"])
    later = step(id="b", version=2, release="0.3.0", removes=["old"])
    assert "remove_not_after_deprecate" in rules([deprecate, same])
    assert rules([deprecate, later]) == set()


def test_remove_in_same_step_that_deprecates_fails() -> None:
    assert "remove_not_after_deprecate" in rules([step(deprecates=["f"], removes=["f"])])


def test_remove_without_prior_deprecation_fails() -> None:
    assert "remove_without_deprecate" in rules([step(removes=["f"])])


def test_missing_down_duplicate_and_noncontiguous_versions() -> None:
    assert "missing_down" in rules([step(down=None)])
    assert "duplicate_version" in rules([step(id="a"), step(id="b")])
    assert "duplicate_id" in rules([step(id="a"), step(id="a", version=2)])
    assert "non_contiguous_versions" in rules([step(id="a", version=2)])
    assert "bad_release" in rules([step(release="next")])


def test_versions_are_per_scope() -> None:
    other = step(id="o", name="other")
    assert lint_migrations([step(id="a"), other]) == []


def test_canonical_hash_ignores_system_fields_and_key_order() -> None:
    a = {"id": "1", "x": 1, "y": [1, 2], "_etag": "e1", "_ts": 1, "_rid": "r"}
    b = {"y": [1, 2], "x": 1, "id": "1", "_etag": "e2", "_self": "s", "_attachments": "a"}
    assert snapshot_hash([a]) == snapshot_hash([b])
    assert snapshot_hash([a]) != snapshot_hash([{**b, "x": 2}])
    assert canonical_json([{"id": "2"}, {"id": "1"}]).startswith('[{"id":"1"}')


def test_in_memory_stores_satisfy_protocols() -> None:
    assert isinstance(InMemoryDocumentStore(), DocumentStore)
    assert isinstance(InMemoryLedgerStore(), LedgerStore)
    assert isinstance(InMemoryAnalyticsSchemaStore(), AnalyticsSchemaStore)


async def test_ledger_cas_semantics() -> None:
    store = InMemoryLedgerStore()
    ledger = MigrationLedger(id="l", target=MigrationTarget.COSMOS_DOCUMENTS, name="c")
    saved = await store.write(ledger, expected_etag=None)
    with pytest.raises(StaleVersionError):
        await store.write(ledger, expected_etag=None)
    with pytest.raises(StaleVersionError):
        await store.write(saved, expected_etag="stale")
    await store.write(saved, expected_etag=saved.etag)


def _http_error(status: int) -> CosmosHttpResponseError:
    exc = CosmosHttpResponseError(message="x")
    exc.status_code = status
    return exc


def test_cosmos_error_mapping() -> None:
    assert isinstance(_translate(_http_error(412)), StaleVersionError)
    for status in (408, 429, 500, 503):
        mapped = _translate(_http_error(status))
        assert isinstance(mapped, DependencyTransientError)
        assert mapped.code == "dependency_transient"
    unmapped = _http_error(400)
    assert _translate(unmapped) is unmapped
