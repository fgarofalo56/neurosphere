"""A real lifecycle engine over item 4's in-memory interaction backends (synthetic data only)."""

from __future__ import annotations

import hashlib
import itertools
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from neurosphere_contracts.interactions.v1.interaction_record import InteractionRecord
from neurosphere_contracts.interactions.v1.redacted_content import RedactedContent
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.audit import AuditContext, AuditRepository, InMemoryAuditStore
from neurosphere_core.crypto import KeyWrapper, LocalFileKeyWrapper, WrappedKey
from neurosphere_core.interactions import (
    EncryptedInteractionStore,
    InMemoryInteractionContent,
    InMemoryInteractionIndex,
)
from neurosphere_core.interactions.lifecycle_delete import (
    InteractionLifecycleBackend,
    InteractionTarget,
    interaction_record_id,
    interaction_target,
)
from neurosphere_core.lifecycle import LifecycleEngine, PolicyState, TargetRegistry, load_policy
from neurosphere_core.lifecycle.engine import Mode
from neurosphere_core.lifecycle.memory import (
    InMemoryHoldRegistry,
    InMemoryMappingStore,
    InMemoryRequestQueue,
)
from neurosphere_core.scope import IdentityScope

CUSTOMER = "acme"
DOMAIN = "commercial:acme:neurosphere:domain:support"
SLASH_DOMAIN = "commercial:acme:neurosphere:domain:sales/emea"
KEK_URI = "https://acme-kv.vault.azure.net/keys/ns-content-kek"
CONTAINER = "interaction_index"
CHAIN = "lifecycle.acme"
CAPTURED_AT = "2026-11-20T10:15:01Z"
CAPTURED = datetime(2026, 11, 20, 10, 15, 1, tzinfo=UTC)
#: Past the 90-day interaction rule: every seeded record is expired.
EXPIRED_NOW = CAPTURED + timedelta(days=100)
#: Inside the rule: nothing is due.
FRESH_NOW = CAPTURED + timedelta(days=10)


def principal(tag: str) -> str:
    return "commercial:acme:entra:principal:p-" + hashlib.sha256(tag.encode()).hexdigest()


def policy(*, max_days: int = 90) -> PolicyState:
    return load_policy(
        {
            "policy_version": "v1",
            "retain_prompt_response_bodies": True,
            "rules": [
                {
                    "data_class": "interaction_content",
                    "min_retention_days": 0,
                    "max_retention_days": max_days,
                }
            ],
        }
    )


def make_record(
    interaction_id: str, *, domain_id: str, principal_id: str | None
) -> InteractionRecord:
    return InteractionRecord.model_validate(
        {
            "schema_version": "1.2.0",
            "interaction_id": interaction_id,
            "cloud": "commercial",
            "customer_id": CUSTOMER,
            "domain_id": domain_id,
            "source_id": "otel-gateway",
            "event_id": "evt-" + interaction_id[:8],
            "correlation_id": "corr-" + interaction_id[:8],
            "capture_source": "edge_push",
            "occurred_at": "2026-11-20T10:15:00Z",
            "captured_at": CAPTURED_AT,
            "agent_id": "commercial:acme:neurosphere:agent:support-bot",
            "principal_id": principal_id,
            "capture_policy_id": "support-capture",
            "capture_policy_version": 2,
            "detector_set_version": "detectors-1.0",
            "redaction_state": "redacted",
            "parts": [{"part": "prompt", "char_count": 40, "truncated": False}],
            "content_ref": None,
            "findings_summary": [{"category": "email_address", "count": 1, "action": "replaced"}],
            "sensitivity_categories": ["pii"],
            "data_asset_ids": [],
            "expires_at": "2027-02-18T10:15:01Z",
        }
    )


def make_content(interaction_id: str, text: str) -> RedactedContent:
    return RedactedContent.model_validate(
        {
            "schema_version": "1.0.0",
            "interaction_id": interaction_id,
            "redaction_state": "redacted",
            "detector_set_version": "detectors-1.0",
            "parts": [{"part": "prompt", "text": text, "truncated": False, "findings": []}],
        }
    )


def canary() -> str:
    return "NSCANARY" + uuid.uuid4().hex.upper()


class SpyWrapper:
    """Delegates to a real key wrapper and counts unwraps (proof that nothing decrypts)."""

    def __init__(self, inner: KeyWrapper) -> None:
        self._inner = inner
        self.unwrap_calls = 0

    @property
    def key_id(self) -> str:
        return self._inner.key_id

    async def wrap(self, data_key: bytes) -> WrappedKey:
        return await self._inner.wrap(data_key)

    async def unwrap(self, wrapped: WrappedKey) -> bytes:
        self.unwrap_calls += 1
        return await self._inner.unwrap(wrapped)


def make_scope() -> IdentityScope:
    contract = ContractScope.model_validate(
        {
            "schema_version": "1.0.0",
            "cloud": "commercial",
            "customer_id": CUSTOMER,
            "principal": {
                "principal_id": "commercial:acme:entra:person:psn_0123456789abcdef",
                "principal_pseudonym": "p-7f3a9c21",
                "principal_kind": "user",
            },
            "roles": [],
            "allowed_domains": [DOMAIN, SLASH_DOMAIN],
            "allowed_resources": [],
            "policy_version": "v1",
            "derived_at": "2026-10-10T00:00:00Z",
            "scope_hash": "sha256:" + hashlib.sha256(b"scope").hexdigest(),
        }
    )
    return IdentityScope._from_verified_contract(contract)  # pyright: ignore[reportPrivateUsage]


def make_ctx() -> AuditContext:
    return AuditContext.from_scope(
        make_scope(), correlation_id="corr-102i5", operation="lifecycle.run", channel="worker"
    )


@dataclass
class Rig:
    index: InMemoryInteractionIndex
    content: InMemoryInteractionContent
    wrapper: SpyWrapper
    store: EncryptedInteractionStore
    target: InteractionTarget
    holds: InMemoryHoldRegistry
    queue: InMemoryRequestQueue
    engine: LifecycleEngine
    audit: AuditRepository
    seeded: dict[str, InteractionRecord] = field(default_factory=dict)

    async def seed(
        self, *, domain_id: str = DOMAIN, principal_id: str | None = None, text: str | None = None
    ) -> str:
        """Store one interaction through the real store; returns its lifecycle record id."""
        interaction_id = str(uuid.uuid4())
        stored = await self.store.put(
            make_record(interaction_id, domain_id=domain_id, principal_id=principal_id),
            make_content(interaction_id, text or "hello [[ns-redacted:email_address]]"),
            capture_retention_days=90,
        )
        record_id = interaction_record_id(interaction_id, domain_id)
        self.seeded[record_id] = stored
        return record_id

    def blob_name(self, record_id: str) -> str:
        ref = self.seeded[record_id].content_ref
        assert ref is not None
        return ref.pointer

    def has_index(self, record_id: str) -> bool:
        stored = self.seeded[record_id]
        key = (CUSTOMER, stored.domain_id.root, stored.interaction_id.root)
        return key in self.index.documents

    def has_blob(self, record_id: str) -> bool:
        return self.blob_name(record_id) in self.content.blobs


def make_rig(tmp_path: Path, *, mode: Mode = "execute", now: datetime = EXPIRED_NOW) -> Rig:
    index = InMemoryInteractionIndex()
    content = InMemoryInteractionContent()
    wrapper = SpyWrapper(LocalFileKeyWrapper(tmp_path / "interaction-kek.bin"))
    state = policy()
    store = EncryptedInteractionStore(index, content, wrapper, kek_uri=KEK_URI, policy=state)
    target = interaction_target(
        CONTAINER, InteractionLifecycleBackend(index, content, customer_id=CUSTOMER)
    )
    registry = TargetRegistry()
    registry.register(target)
    counter = itertools.count(1)
    audit = AuditRepository(
        InMemoryAuditStore(),
        clock=lambda: now,
        id_factory=lambda: f"00000000-0000-4000-8000-{next(counter):012d}",
    )
    holds = InMemoryHoldRegistry()
    queue = InMemoryRequestQueue()
    engine = LifecycleEngine(
        policy=state,
        targets=registry,
        holds=holds,
        queue=queue,
        audit=audit,
        audit_chain_id=CHAIN,
        cloud="commercial",
        customer_id=CUSTOMER,
        mappings=InMemoryMappingStore(set()),
        clock=lambda: now,
        mode=mode,
    )
    return Rig(index, content, wrapper, store, target, holds, queue, engine, audit)
