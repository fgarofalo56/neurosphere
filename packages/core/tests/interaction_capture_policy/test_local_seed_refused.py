"""seed_local_capture_policy: refused unless NS_ENV=local is set explicitly; audited when run."""

from __future__ import annotations

import pytest
from neurosphere_core.audit import domain_audit_chain_id
from neurosphere_core.errors import CapabilityUnavailableError, InvalidSchemaError
from neurosphere_core.interactions.policy import CaptureMatcher
from neurosphere_core.interactions.policy_store import (
    InMemoryCapturePolicyStore,
    read_back_capture_policy,
    seed_local_capture_policy,
)

from .policy_helpers import (
    CUSTOMER,
    DOMAIN,
    NOW,
    POLICY_ID,
    SOURCE,
    audit_repo,
    make_ctx,
    policy_doc,
    retention,
)

CHAIN = domain_audit_chain_id(CUSTOMER, DOMAIN)


@pytest.mark.parametrize(
    "environ",
    [{}, {"NS_ENV": "dev"}, {"NS_ENV": "prod"}, {"NS_ENV": "test"}, {"NS_ENV": "LOCAL "}],
)
async def test_refused_outside_local(environ: dict[str, str]) -> None:
    store = InMemoryCapturePolicyStore()
    audit = audit_repo()
    with pytest.raises(CapabilityUnavailableError) as info:
        await seed_local_capture_policy(
            store, policy_doc(state="active"), audit=audit, ctx=make_ctx(), environ=environ
        )
    assert info.value.reason == "capture_seed_local_only"
    assert await store.list() == []
    assert await audit.tail(CHAIN) is None  # nothing written anywhere


async def test_refused_when_process_env_is_not_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_ENV", "staging")
    with pytest.raises(CapabilityUnavailableError):
        await seed_local_capture_policy(
            InMemoryCapturePolicyStore(), policy_doc(), audit=audit_repo(), ctx=make_ctx()
        )


async def test_local_seed_active_policy_points_at_its_audit_record() -> None:
    store = InMemoryCapturePolicyStore()
    audit = audit_repo()
    seeded = await seed_local_capture_policy(
        store,
        policy_doc(state="active"),
        audit=audit,
        ctx=make_ctx(),
        environ={"NS_ENV": "local"},
        clock=lambda: NOW,
    )
    assert seeded.state == "active"
    assert seeded.version == 1
    assert await read_back_capture_policy(store, POLICY_ID) == seeded

    records = await audit.read_range(CHAIN, start=0, limit=10)
    assert [(r.kind, r.operation) for r in records] == [
        ("before", "capture_policy.seed_local"),
        ("after", "capture_policy.seed_local"),
    ]
    assert seeded.approved_audit_id is not None
    assert seeded.approved_audit_id.root == records[0].audit_id.root
    assert seeded.approved_intent_id is not None
    assert records[0].intent_id is not None
    assert seeded.approved_intent_id.root == records[0].intent_id.root
    assert records[1].outcome is not None
    assert records[1].outcome.verified is True

    matcher = await CaptureMatcher.from_store(store, setting_enabled=True, retention=retention())
    assert matcher.match(SOURCE, DOMAIN, "e") is not None

    again = await seed_local_capture_policy(
        store,
        policy_doc(state="suspended"),
        audit=audit,
        ctx=make_ctx(),
        environ={"NS_ENV": "local"},
    )
    assert again.version == 2
    assert again.previous_version == 1
    assert again.state == "suspended"


async def test_local_seed_validates_before_auditing() -> None:
    store = InMemoryCapturePolicyStore()
    audit = audit_repo()
    with pytest.raises(InvalidSchemaError):
        await seed_local_capture_policy(
            store,
            policy_doc(kept_categories=["bearer_token"]),
            audit=audit,
            ctx=make_ctx(),
            environ={"NS_ENV": "local"},
        )
    assert await audit.tail(CHAIN) is None
    assert await store.list() == []
