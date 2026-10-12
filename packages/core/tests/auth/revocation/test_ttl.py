"""Revocation takes effect within the configured TTL (C12), measured with a fake clock.

The denial is item 2's contract: ``ScopeDeriver`` raises ``forbidden`` (HTTP 403) with reason
``principal_revoked`` when the checker answers ``True``. No ``time.sleep`` anywhere.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from neurosphere_core.auth import revocation as revocation_pkg
from neurosphere_core.auth.revocation import (
    DEFAULT_REVOCATION_TTL_SECONDS,
    CachedRevocationChecker,
    InMemoryRevocationStore,
    RevocationEntry,
    RevocationSettings,
    load_revocation_settings,
)
from neurosphere_core.auth.revocation import model as revocation_model
from neurosphere_core.errors import ForbiddenError
from pydantic import ValidationError

from .revocation_helpers import (
    OBJECT_ID,
    T0,
    FakeClock,
    admin_scope,
    entry_for,
    make_claims,
    make_deriver,
    policy_repo,
    principal_id_for,
    service_for,
)

TARGET = principal_id_for(OBJECT_ID)

# ------------------------------------------------------------------ documented default


def test_default_ttl_is_stated_in_code_and_docs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NS_REVOCATION_TTL_SECONDS", raising=False)
    assert DEFAULT_REVOCATION_TTL_SECONDS == 60
    assert load_revocation_settings().ttl_seconds == DEFAULT_REVOCATION_TTL_SECONDS
    for doc in (revocation_model.__doc__, revocation_pkg.__doc__):
        assert doc is not None
        assert "NS_REVOCATION_TTL_SECONDS" in doc
        assert "not instant" in doc.lower()
        assert "60" in doc


def test_ttl_is_configured_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_REVOCATION_TTL_SECONDS", "15")
    settings = load_revocation_settings()
    assert settings.ttl_seconds == 15
    checker = CachedRevocationChecker.from_settings(InMemoryRevocationStore(), settings)
    assert checker.ttl_seconds == 15


@pytest.mark.parametrize("value", ["0", "-1", "100000", "soon"])
def test_invalid_ttl_fails_at_startup(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("NS_REVOCATION_TTL_SECONDS", value)
    with pytest.raises(ValidationError):
        load_revocation_settings()


def test_retention_cannot_undercut_longest_token_lifetime() -> None:
    with pytest.raises(ValidationError):
        RevocationSettings(retention_seconds=3600)


# ------------------------------------------------------------------ TTL boundary on a replica


@pytest.mark.parametrize("ttl", [5, DEFAULT_REVOCATION_TTL_SECONDS, 300])
async def test_other_replica_denies_no_later_than_ttl(ttl: int) -> None:
    clock = FakeClock()
    store = InMemoryRevocationStore(clock=clock)
    checker = CachedRevocationChecker(store, ttl_seconds=ttl, clock=clock)
    deriver = make_deriver(
        policy_repo(), clock=clock, revocation_checker=checker, policy_cache_ttl_seconds=300
    )
    claims = make_claims(lifetime_seconds=3600)

    # Replica B caches "not revoked" at the same instant the revocation is written elsewhere.
    await deriver.from_verified_claims(claims)
    await store.put(entry_for(TARGET, clock.datetime()))

    clock.now = T0 + ttl - 0.001  # just before the TTL: still allowed (bounded, not instant)
    await deriver.from_verified_claims(claims)

    clock.now = T0 + ttl  # exactly TTL after revocation: denied with 403
    with pytest.raises(ForbiddenError) as info:
        await deriver.from_verified_claims(claims)
    assert info.value.reason == "principal_revoked"
    assert info.value.status == 403

    clock.now = T0 + ttl + 1  # and it stays denied
    with pytest.raises(ForbiddenError):
        await deriver.from_verified_claims(claims)


async def test_cache_age_counts_from_read_start_so_slow_reads_do_not_extend_ttl() -> None:
    clock = FakeClock()
    inner = InMemoryRevocationStore(clock=clock)

    class SlowStore:
        """The first read takes 7 s and the revocation is written while it is in flight."""

        def __init__(self) -> None:
            self.reads = 0

        async def get(self, principal_id: str) -> RevocationEntry | None:
            self.reads += 1
            answer = await inner.get(principal_id)
            if self.reads == 1:
                clock.advance(7)
                await inner.put(entry_for(TARGET, clock.datetime()))
            return answer

        async def put(self, entry: RevocationEntry) -> RevocationEntry:
            return await inner.put(entry)

    issued = clock.datetime() - timedelta(minutes=5)
    checker = CachedRevocationChecker(SlowStore(), ttl_seconds=10, clock=clock)
    assert await checker.is_revoked(TARGET, issued) is False  # read started T0, ended T0+7
    clock.now = T0 + 10 - 0.001
    assert await checker.is_revoked(TARGET, issued) is False  # cached, 10 s from read START
    clock.now = T0 + 10
    assert await checker.is_revoked(TARGET, issued) is True  # expired, re-read, denied


async def test_revoking_replica_denies_immediately() -> None:
    clock = FakeClock()
    store = InMemoryRevocationStore(clock=clock)
    checker = CachedRevocationChecker(store, ttl_seconds=300, clock=clock)
    deriver = make_deriver(policy_repo(), clock=clock, revocation_checker=checker)
    claims = make_claims()
    await deriver.from_verified_claims(claims)  # cached "not revoked" for 300 s

    service, _, _ = service_for(store, clock, checker=checker, deriver=deriver)
    outcome = await service.revoke(await admin_scope(clock), TARGET, reason="compromised")
    assert outcome.propagation_bound_seconds == 60

    with pytest.raises(ForbiddenError) as info:
        await deriver.from_verified_claims(claims)  # same instant, no clock advance
    assert info.value.reason == "principal_revoked"


# ------------------------------------------------------------------ issued-at semantics


async def test_only_tokens_issued_before_revocation_plus_skew_are_revoked() -> None:
    clock = FakeClock()
    store = InMemoryRevocationStore(clock=clock)
    revoked_at = clock.datetime()
    await store.put(entry_for(TARGET, revoked_at))
    checker = CachedRevocationChecker(store, clock_skew_seconds=60, clock=clock)

    assert await checker.is_revoked(TARGET, revoked_at - timedelta(hours=1)) is True
    assert await checker.is_revoked(TARGET, revoked_at) is True
    assert await checker.is_revoked(TARGET, revoked_at + timedelta(seconds=60)) is True
    assert await checker.is_revoked(TARGET, revoked_at + timedelta(seconds=61)) is False
    bystander = principal_id_for("00000000-0000-4000-8000-000000000000")
    assert await checker.is_revoked(bystander, revoked_at) is False


async def test_new_sign_in_after_revocation_is_accepted() -> None:
    clock = FakeClock()
    store = InMemoryRevocationStore(clock=clock)
    await store.put(entry_for(TARGET, clock.datetime()))
    checker = CachedRevocationChecker(store, clock_skew_seconds=0, clock=clock)
    clock.advance(600)
    deriver = make_deriver(policy_repo(), clock=clock, revocation_checker=checker)
    with pytest.raises(ForbiddenError):
        await deriver.from_verified_claims(make_claims())  # iat = T0-60, before revocation
    fresh = make_claims(issued_at=clock.datetime(), not_before=clock.datetime())
    scope = await deriver.from_verified_claims(fresh)
    assert scope.allowed_domains


async def test_naive_issued_at_is_rejected() -> None:
    checker = CachedRevocationChecker(InMemoryRevocationStore())
    with pytest.raises(ValueError, match="timezone-aware"):
        await checker.is_revoked(TARGET, FakeClock().datetime().replace(tzinfo=None))


async def test_entry_retention_matches_cosmos_item_ttl() -> None:
    clock = FakeClock()
    store = InMemoryRevocationStore(retention_seconds=100_800, clock=clock)
    revoked_at = clock.datetime()
    await store.put(entry_for(TARGET, revoked_at))
    clock.advance(100_800 - 1)
    assert await store.get(TARGET) is not None
    clock.advance(1)
    assert await store.get(TARGET) is None
