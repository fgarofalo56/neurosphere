"""Catalog projection of published policies (PRP-105 item 3, acceptance criterion 9)."""

from __future__ import annotations

from typing import Any

import pytest
from neurosphere_core.catalog.protocol import CatalogEntity
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.errors import DependencyTransientError
from neurosphere_core.governance.policy import (
    ENFORCEMENT_BY_MODE,
    LifecycleAuditContext,
    PolicyLifecycle,
    deprecate_policy_entity,
    policy_entity,
    project_policy,
    validate_policy,
)
from neurosphere_core.scope import IdentityScope

from .engine_helpers import (
    CUSTOMER,
    DOMAIN_A,
    INTENT,
    WORKER_SCOPE,
    Engine,
    build_engine,
    policy_draft,
    rule,
)
from .rules.rules_helpers import NOW, SCOPE
from .rules.rules_helpers import make_scope as viewer_scope

ENTITY_ID = "commercial:acme:neurosphere:policy:pii-guard"


def _published(**overrides: Any) -> Any:
    body = policy_draft()
    body.update(
        {
            "status": "published",
            "published_at": "2026-10-17T12:00:00Z",
            "published_intent_id": INTENT,
            "published_audit_id": INTENT,
        }
    )
    body.update(overrides)
    return validate_policy(body, stamp_digest=True)


def _doc(entity: CatalogEntity | None) -> dict[str, Any]:
    assert entity is not None
    return entity.model_dump(mode="json")


async def test_a_published_policy_is_projected_as_an_advisory_catalog_policy() -> None:
    repo = InMemoryCatalogRepository()

    result = await project_policy(repo, SCOPE, _published(), now=NOW)

    assert result.ok
    assert result.action == "created"
    assert result.entity_id == ENTITY_ID
    doc = _doc(await repo.get_entity(SCOPE, ENTITY_ID))
    assert doc["entity_type"] == "policy"
    assert doc["domain_id"] == DOMAIN_A
    assert doc["enforcement"] == "advisory"
    assert doc["policy_version"] == "1"
    assert doc["policy_kind"] == "data_handling"
    assert doc["lifecycle_status"] == "active"
    assert doc["effective_from"] == "2026-10-17T12:00:00Z"
    assert doc["document_ref"] == "commercial:acme:neurosphere:governance_policy:pii-guard"


@pytest.mark.parametrize(
    ("mode", "enforcement"), [("off", "disabled"), ("audit", "advisory"), ("enforce", "enforced")]
)
def test_mode_maps_to_catalog_enforcement(mode: str, enforcement: str) -> None:
    assert ENFORCEMENT_BY_MODE[mode] == enforcement
    entity = policy_entity(_published(mode=mode), now=NOW)
    assert entity.enforcement == enforcement


def test_mixed_rule_families_project_as_other() -> None:
    owner = rule("owner", "required_owner", {"min_owners": 1, "require_active_owner": True})
    entity = policy_entity(_published(rules=[rule(), owner]), now=NOW)
    assert entity.policy_kind == "other"


async def test_projection_is_idempotent_and_follows_new_versions() -> None:
    repo = InMemoryCatalogRepository()
    await project_policy(repo, SCOPE, _published(), now=NOW)

    again = await project_policy(repo, SCOPE, _published(), now=NOW)
    assert again.action == "unchanged"

    v2 = _published(policy_version=2, previous_version=1, mode="off")
    updated = await project_policy(repo, SCOPE, v2, now=NOW)
    assert updated.action == "updated"
    doc = _doc(await repo.get_entity(SCOPE, ENTITY_ID))
    assert doc["policy_version"] == "2"
    assert doc["enforcement"] == "disabled"
    assert doc["version"] == 2


async def test_retire_deprecates_and_a_missing_entity_is_created_deprecated() -> None:
    repo = InMemoryCatalogRepository()
    missing = await deprecate_policy_entity(repo, SCOPE, _published(), now=NOW)
    assert missing.action == "deprecated"
    created = await repo.get_entity(SCOPE, ENTITY_ID)
    assert _doc(created)["lifecycle_status"] == "deprecated"
    again = await deprecate_policy_entity(repo, SCOPE, _published(), now=NOW)
    assert again.action == "unchanged"

    other = InMemoryCatalogRepository()
    await project_policy(other, SCOPE, _published(), now=NOW)
    retired = await deprecate_policy_entity(other, SCOPE, _published(), now=NOW)
    assert retired.action == "deprecated"
    deprecated = await other.get_entity(SCOPE, ENTITY_ID)
    assert _doc(deprecated)["lifecycle_status"] == "deprecated"


async def test_projection_writes_only_under_the_callers_scope() -> None:
    repo = InMemoryCatalogRepository()
    elsewhere = viewer_scope("b")

    result = await project_policy(repo, elsewhere, _published(), now=NOW)

    assert not result.ok
    assert result.reason_code == "projection_out_of_scope"
    absent = await repo.get_entity(SCOPE, ENTITY_ID)
    assert absent is None


class FlakyCatalog:
    """Delegates to an in-memory repository; entity writes fail while ``down``."""

    def __init__(self, repo: InMemoryCatalogRepository) -> None:
        self._repo = repo
        self.down = True

    def __getattr__(self, name: str) -> Any:
        return getattr(self._repo, name)

    async def create_entity(self, scope: IdentityScope, entity: CatalogEntity) -> CatalogEntity:
        if self.down:
            raise DependencyTransientError("catalog down", reason="catalog_unavailable")
        return await self._repo.create_entity(scope, entity)


async def test_a_projection_failure_leaves_the_policy_published_and_the_next_tick_retries() -> None:
    engine: Engine = await build_engine()
    flaky = FlakyCatalog(engine.catalog)
    publisher = PolicyLifecycle(
        engine.policies,
        engine.bindings,
        engine.audit,
        engine.registry,
        flaky,  # type: ignore[arg-type]
        clock=engine.clock,
    )
    created = await engine.create(policy_draft())
    outcome = await publisher.publish(
        "pii-guard",
        1,
        expected_etag=created.etag,
        audit_ctx=LifecycleAuditContext(
            scope=WORKER_SCOPE, correlation_id="corr-flaky", intent_id=INTENT
        ),
    )

    assert outcome.stored.policy.status == "published"
    assert outcome.projection.action == "failed"
    assert outcome.projection.reason_code == "projection_store_unavailable"
    after = [r for r in await engine.records() if r.operation == "govpolicy.publish"][-1]
    assert after.outcome is not None
    assert after.outcome.detail is not None
    assert "projection=projection_store_unavailable" in after.outcome.detail
    absent = await engine.catalog.get_entity(SCOPE, ENTITY_ID)
    assert absent is None
    still = await engine.policies.get(CUSTOMER, "pii-guard")
    assert still is not None
    assert still.policy.status == "published"

    run = await engine.tick()

    (reconciled,) = run.reconciled
    assert reconciled.projection.action == "created"
    projected = await engine.catalog.get_entity(SCOPE, ENTITY_ID)
    assert _doc(projected)["enforcement"] == "advisory"
