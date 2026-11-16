"""Shared fixtures for the compliance library tests: scope, clock, in-memory stores and fakes."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from neurosphere_contracts.evaluation.v1.evaluation_result import EvaluationResult
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.audit import (
    AuditContext,
    AuditRepository,
    InMemoryAuditStore,
    build_allowed,
    domain_audit_chain_id,
    make_subject,
)
from neurosphere_core.compliance import SourceRequest
from neurosphere_core.evaluation.store import InMemoryEvaluationStore
from neurosphere_core.hitl.models import ReviewItem
from neurosphere_core.hitl.store import InMemoryHitlStore
from neurosphere_core.paging import Page
from neurosphere_core.scope import IdentityScope

REPO_ROOT = Path(__file__).resolve().parents[4]
CONTRACTS = REPO_ROOT / "packages/contracts/schemas"
DOMAIN = "commercial:contoso:catalog:domain:finance"
OTHER_DOMAIN = "commercial:contoso:catalog:domain:operations"
NOW = datetime(2026, 11, 16, 12, 0, 0, tzinfo=UTC)
START = NOW - timedelta(days=30)
SCOPE_HASH = "sha256:" + hashlib.sha256(b"scope").hexdigest()


def make_scope(domains: tuple[str, ...] = (DOMAIN,)) -> IdentityScope:
    contract = ContractScope.model_validate(
        {
            "schema_version": "1.0.0",
            "cloud": "commercial",
            "customer_id": "contoso",
            "principal": {
                "principal_id": "commercial:contoso:entra:person:psn_0123456789abcdef",
                "principal_pseudonym": "p-7f3a9c21",
                "principal_kind": "user",
            },
            "roles": [{"role": "security_auditor", "domain_ids": list(domains)}],
            "allowed_domains": list(domains),
            "allowed_resources": [],
            "policy_version": "v1",
            "derived_at": "2026-10-10T00:00:00Z",
            "scope_hash": SCOPE_HASH,
        }
    )
    return IdentityScope._from_verified_contract(contract)  # pyright: ignore[reportPrivateUsage]


def make_request(cap: int = 2000, domain: str = DOMAIN) -> SourceRequest:
    return SourceRequest(
        scope=make_scope(), domain_id=domain, window_start=START, window_end=NOW, cap=cap
    )


# -- audit ---------------------------------------------------------------------------------


async def audit_repo_with(records: int, domain: str = DOMAIN) -> AuditRepository:
    repo = AuditRepository(InMemoryAuditStore(), clock=lambda: NOW - timedelta(days=1))
    ctx = AuditContext.from_scope(
        make_scope(), correlation_id="corr-1", operation="catalog.search", channel="rest"
    )
    subject = make_subject(domain, "domain", state={"n": 1})
    chain = domain_audit_chain_id("contoso", domain)
    for _ in range(records):
        await repo.append(chain, build_allowed(ctx, subject))
    return repo


# -- hitl ----------------------------------------------------------------------------------


def review_item(n: int, *, decided: bool, state: str = "approved") -> ReviewItem:
    created = NOW - timedelta(days=5)
    data: dict[str, Any] = {
        "item_id": f"33333333-3333-4333-8333-{n:012d}",
        "kind": "relationship",
        "state": "pending",
        "cloud": "commercial",
        "customer_id": "contoso",
        "domain_id": DOMAIN,
        "subject_ref": "commercial:contoso:catalog:agent:a-1",
        "created_at": created,
        "sla_due_at": created + timedelta(hours=24),
        "expires_at": created + timedelta(days=30),
        "policy_version": "v1",
    }
    if decided:
        data.update(
            state=state,
            decision_id=f"44444444-4444-4444-8444-{n:012d}",
            decided_at=NOW - timedelta(days=2),
        )
    return ReviewItem.model_validate(data)


async def hitl_store_with(items: list[ReviewItem]) -> InMemoryHitlStore:
    store = InMemoryHitlStore()
    for item in items:
        await store.create(item)
    return store


# -- evaluation ----------------------------------------------------------------------------


def evaluation_store_with(count: int, *, completed_at: str = "2026-11-10T01:42:00Z") -> Any:
    path = CONTRACTS / "evaluation/v1/examples/valid/evaluation-result.offline-llm-judge.json"
    results = []
    for n in range(count):
        doc = json.loads(path.read_text("utf-8"))
        doc["evaluation_id"] = f"eval:r-{n:04d}"
        doc["completed_at"] = completed_at
        doc["domain_id"] = DOMAIN
        results.append(EvaluationResult.model_validate(doc))
    return InMemoryEvaluationStore(results)


# -- catalog and ledger fakes ---------------------------------------------------------------


class FakeOwner:
    def __init__(self, body: dict[str, Any]) -> None:
        self._body = body

    def model_dump(self, mode: str = "python") -> dict[str, Any]:
        return dict(self._body)


class FakeCatalog:
    """Returns owners in pages of ``page_size``; satisfies the one method the source calls."""

    def __init__(self, owners: list[dict[str, Any]], page_size: int = 100) -> None:
        self._owners = owners
        self._page = page_size
        self.fail = False

    async def list_entities(self, scope: Any, flt: Any, page: Any) -> Page[Any]:
        if self.fail:
            raise RuntimeError("down")
        start = int(page.cursor) if page.cursor else 0
        size = min(page.page_size, self._page)
        chunk = self._owners[start : start + size]
        more = start + size < len(self._owners)
        return Page[Any](
            items=tuple(FakeOwner(o) for o in chunk),
            next_cursor=str(start + size) if more else None,
        )


def owner(n: int, *, by: str | None, at: str | None) -> dict[str, Any]:
    return {
        "id": f"commercial:contoso:catalog:owner:team-{n}",
        "entity_type": "owner",
        "display_name": f"Secret Team {n}",
        "recertify_by": by,
        "recertified_at": at,
    }


class FakeLedger:
    def __init__(self, entries: list[Any]) -> None:
        self._entries = entries
        self.fail = False

    async def list_entries(self, customer_id: str, window: Any) -> list[Any]:
        if self.fail:
            raise RuntimeError("down")
        return list(self._entries)


def ledger_entry(domain: str | None, cost_center: str | None, *, has_attr: bool = True) -> Any:
    fields: dict[str, Any] = {"domain_id": domain, "observed_at": NOW - timedelta(days=1)}
    if has_attr:
        fields["cost_center"] = cost_center
    return SimpleNamespace(**fields)
