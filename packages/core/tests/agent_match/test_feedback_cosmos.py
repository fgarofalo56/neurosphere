"""CosmosFeedbackStore on the compose emulator (``pytest -m integration``, 127.0.0.1:8081).

Skipped by default (the python CI job deselects ``integration``). The key is a dummy built at
runtime; the emulator ignores it.
"""

from __future__ import annotations

import base64
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from azure.cosmos.aio import DatabaseProxy
from neurosphere_core.clients import ClientLifetime, create_cosmos_client
from neurosphere_core.cloud import Settings
from neurosphere_core.recommendations.matching.cosmos_store import (
    DEFAULT_FEEDBACK_CONTAINER,
    FEEDBACK_PARTITION_KEY_PATHS,
    CosmosFeedbackStore,
    create_feedback_container,
)
from neurosphere_core.recommendations.matching.feedback import (
    CandidateNotInMatchError,
    MatchCandidateRecord,
    MatchNotFoundError,
    MatchRecord,
    feedback_signal,
)
from neurosphere_core.stores.containers import container_spec

pytestmark = pytest.mark.integration

CUSTOMER = "contoso"
DOMAIN = "commercial:contoso:catalog:domain:finance"
AGENT_A = "commercial:contoso:catalog:agent:a"
AGENT_B = "commercial:contoso:catalog:agent:b"
TOKENS = ("summarize", "support", "ticket")


def _now() -> datetime:
    return datetime.now(UTC)


@pytest_asyncio.fixture
async def database(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[DatabaseProxy]:
    monkeypatch.setenv("NS_ENV", "local")
    monkeypatch.setenv("NS_COSMOS_ENDPOINT", "http://127.0.0.1:8081")
    monkeypatch.setenv("NS_COSMOS_KEY", base64.b64encode(b"emulator-ignores-this").decode())
    async with ClientLifetime() as lifetime:
        client = create_cosmos_client(Settings(env="local"), lifetime=lifetime)
        db = await client.create_database_if_not_exists(f"ns_feedback_{uuid.uuid4().hex[:12]}")
        try:
            yield db
        finally:
            await client.delete_database(db.id)


def make_match(match_id: str, principal: str) -> MatchRecord:
    created = _now()
    return MatchRecord(
        match_id=match_id,
        customer_id=CUSTOMER,
        domain_id=DOMAIN,
        principal=principal,
        task_tokens=TOKENS,
        candidates=(MatchCandidateRecord(AGENT_A, 1, 0.9), MatchCandidateRecord(AGENT_B, 2, 0.4)),
        created_at=created,
        expires_at=created + timedelta(days=180),
    )


def test_constants_match_the_registry() -> None:
    spec = container_spec(DEFAULT_FEEDBACK_CONTAINER)
    assert spec.partition_key_paths == tuple(FEEDBACK_PARTITION_KEY_PATHS)
    assert spec.kind == "MultiHash"


async def test_round_trip_replace_refusals_prior_and_metrics(database: DatabaseProxy) -> None:
    container = await create_feedback_container(database)
    store = CosmosFeedbackStore(container)
    for principal in ("p-1", "p-2", "p-3"):
        await store.record_match(make_match(f"m/{principal}", principal))
        await store.record_feedback(
            customer_id=CUSTOMER,
            domain_id=DOMAIN,
            match_id=f"m/{principal}",
            principal=principal,
            entity_id=AGENT_A,
            decision="rejected",
        )
    # A later decision replaces the earlier one.
    await store.record_feedback(
        customer_id=CUSTOMER,
        domain_id=DOMAIN,
        match_id="m/p-1",
        principal="p-1",
        entity_id=AGENT_A,
        decision="accepted",
        reason_code="other",
    )
    found = await store.list_feedback(
        customer_id=CUSTOMER, domain_ids=[DOMAIN], entity_ids=[AGENT_A]
    )
    assert len(found) == 3
    assert sorted(r.decision for r in found) == ["accepted", "rejected", "rejected"]
    assert found[0].task_tokens == TOKENS

    with pytest.raises(MatchNotFoundError):
        await store.record_feedback(
            customer_id=CUSTOMER,
            domain_id=DOMAIN,
            match_id="missing",
            principal="p-1",
            entity_id=AGENT_A,
            decision="accepted",
        )
    with pytest.raises(MatchNotFoundError):
        await store.record_feedback(
            customer_id=CUSTOMER,
            domain_id=DOMAIN,
            match_id="m/p-1",
            principal="p-2",
            entity_id=AGENT_A,
            decision="accepted",
        )
    with pytest.raises(CandidateNotInMatchError):
        await store.record_feedback(
            customer_id=CUSTOMER,
            domain_id=DOMAIN,
            match_id="m/p-1",
            principal="p-1",
            entity_id="commercial:contoso:catalog:agent:zzz",
            decision="accepted",
        )

    signal = feedback_signal(found, candidate_id=AGENT_A, task_tokens=TOKENS)
    assert signal.principals == 3
    assert -0.15 <= signal.prior <= 0.15

    metrics = await store.metrics(
        customer_id=CUSTOMER,
        domain_ids=[DOMAIN],
        since=_now() - timedelta(hours=1),
        until=_now() + timedelta(hours=1),
    )
    assert (metrics.matches, metrics.matches_with_feedback) == (3, 3)
    assert (metrics.accepts, metrics.rejects) == (1, 2)
    assert metrics.acceptance_rate == pytest.approx(1 / 3)

    # Stored documents carry the per-item ttl and no text or clear identifiers beyond ids.
    rows = [row async for row in container.query_items("SELECT * FROM c")]
    assert len(rows) == 6
    assert all(isinstance(row["ttl"], int) and row["ttl"] > 0 for row in rows)
    assert not any("task_text" in row for row in rows)


async def test_metrics_rate_is_none_without_feedback(database: DatabaseProxy) -> None:
    store = CosmosFeedbackStore(await create_feedback_container(database))
    await store.record_match(make_match("m-1", "p-1"))
    metrics = await store.metrics(
        customer_id=CUSTOMER,
        domain_ids=[DOMAIN],
        since=_now() - timedelta(hours=1),
        until=_now() + timedelta(hours=1),
    )
    assert (metrics.matches, metrics.accepts, metrics.acceptance_rate) == (1, 0, None)
