"""Apply, verify and rollback against the in-memory APIM double."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import pytest
from apim_write_support import (  # pyright: ignore[reportMissingImports]
    EXPECTED_ORDER,
    PUBLICATION,
    make,
    publication_ops,
    remove,
    request,
    reviewed,
    upsert,
)
from neurosphere_connector_apim_gateway import (
    InMemoryApim,
    RollbackFailedError,
    StepOwnership,
)
from neurosphere_connector_apim_gateway.arm import map_status
from neurosphere_connector_apim_gateway.inmemory import ArmCall
from neurosphere_connector_apim_gateway.policies import fragment_payload, render_deny_fragment
from neurosphere_core.errors import (
    CapabilityUnavailableError,
    DependencyTransientError,
    InvalidSchemaError,
    StaleVersionError,
)


async def test_apply_requires_the_reviewed_plan_digest() -> None:
    conn, apim, _ = make()
    with pytest.raises(InvalidSchemaError) as err:
        await conn.apply(request(*publication_ops()))
    assert err.value.reason == "plan_digest_required"
    assert apim.writes() == []


async def test_apply_creates_in_order_and_records_ownership() -> None:
    conn, apim, records = make()
    req = await reviewed(conn, request(*publication_ops()))
    result = await conn.apply(req)

    puts = [c for c in apim.writes() if c.method == "PUT"]
    assert [c.path for c in puts] == EXPECTED_ORDER
    assert all(c.if_match is None for c in puts)  # creates carry no If-Match
    # Existence re-read immediately before every write.
    for put in puts:
        i = apim.calls.index(put)
        assert apim.calls[i - 1].method == "GET" and apim.calls[i - 1].path == put.path

    assert result.rollback_token == "apply-1"  # noqa: S105
    assert result.version_before == req.target_version
    record = await records.latest("apply-1")
    assert record is not None and record.status == "succeeded"
    assert [s.name for s in record.steps] == EXPECTED_ORDER
    assert {s.ownership for s in record.steps} == {StepOwnership.CREATED}
    assert all(s.etag_after == apim.etag_of(s.name) for s in record.steps)
    # Ownership is appended at write time: one version per step plus open and close.
    assert len(records.history("apply-1")) == len(EXPECTED_ORDER) + 2
    assert StepOwnership.CREATED.to_register().value == "created"
    assert StepOwnership.FOUND.to_register().value == "reused"


async def test_apply_refuses_when_gateway_changed_since_review() -> None:
    conn, apim, _ = make()
    req = await reviewed(conn, request(*publication_ops()))
    apim.seed("products/ns-grant-g1", {"displayName": "someone else"})
    with pytest.raises(StaleVersionError) as err:
        await conn.apply(req)
    assert err.value.reason == "plan_digest_mismatch"
    assert apim.writes() == []


async def test_refuses_to_overwrite_a_resource_it_expected_to_create() -> None:
    conn, apim, records = make()
    req = await reviewed(conn, request(*publication_ops()))
    foreign = {"displayName": "owned by someone else"}

    def appear(method: str, path: str) -> None:
        # GETs of this path: 1 dry_run plan, 2 apply re-plan, 3 the applier's pre-write re-read.
        # It appears after the re-plan, just before the pre-write read.
        if method == "GET" and path == "products/ns-grant-g1":
            if sum(1 for c in apim.calls if c.path == path) == 3:
                apim.seed(path, foreign)

    apim.before = appear
    with pytest.raises(StaleVersionError) as err:
        await conn.apply(req)
    assert err.value.reason == "resource_appeared"
    # The foreign resource is untouched; everything this run created is gone.
    assert apim.snapshot() == {"products/ns-grant-g1": foreign}
    deletes = [c.path for c in apim.writes() if c.method == "DELETE"]
    assert deletes == list(reversed(EXPECTED_ORDER[:6]))
    record = await records.latest("apply-1")
    assert record is not None and record.status == "rolled_back" and record.orphans == ()


async def test_found_resource_is_updated_with_if_match_and_restored_never_deleted() -> None:
    conn, apim, records = make()
    prior = {"url": "https://old.openai.azure.com/openai", "protocol": "http"}
    etag = apim.seed("backends/foundry", prior)
    new = {"url": "https://new.openai.azure.com/openai", "protocol": "http"}
    req = await reviewed(
        conn, request(upsert("backends/foundry", new), upsert("apis/llm", PUBLICATION["apis/llm"]))
    )
    applied = await conn.apply(req)

    put = next(c for c in apim.writes() if c.path == "backends/foundry")
    assert put.if_match == etag
    record = await records.latest("apply-1")
    assert record is not None
    step = record.steps[0]
    assert (step.ownership, step.wrote, step.prior) == (StepOwnership.FOUND, True, prior)

    rolled = await conn.rollback(applied)
    assert rolled.status == "rolled_back"
    assert apim.snapshot() == {"backends/foundry": prior}  # restored, not deleted
    again = await conn.rollback(applied)
    assert again.status == "not_needed"


async def test_412_on_update_surfaces_stale_version_and_reverses() -> None:
    conn, apim, records = make()
    apim.seed("apis/llm", {"path": "old"})
    req = await reviewed(
        conn,
        request(
            upsert("backends/foundry", {"url": "https://x"}), upsert("apis/llm", {"path": "llm"})
        ),
    )
    apim.fail("PUT", "apis/llm", map_status(412))
    with pytest.raises(StaleVersionError) as err:
        await conn.apply(req)
    assert err.value.reason == "etag_mismatch"
    assert apim.snapshot() == {"apis/llm": {"path": "old"}}
    record = await records.latest("apply-1")
    assert record is not None and record.status == "rolled_back"


async def test_arm_429_maps_to_dependency_transient_with_retry_after() -> None:
    conn, apim, _ = make()
    req = await reviewed(conn, request(*publication_ops()))
    apim.fail("PUT", "apis/llm", map_status(429, retry_after=17))
    with pytest.raises(DependencyTransientError) as err:
        await conn.apply(req)
    assert err.value.reason == "arm_rate_limited"
    assert err.value.retry_after_seconds == 17
    assert apim.snapshot() == {}


async def test_failed_reversal_reports_rollback_failed_with_orphans() -> None:
    conn, apim, records = make()
    req = await reviewed(conn, request(*publication_ops()))
    apim.fail("PUT", "apis/llm/operations/chat", DependencyTransientError())
    apim.fail("DELETE", "backends/foundry", DependencyTransientError())
    with pytest.raises(RollbackFailedError) as err:
        await conn.apply(req)
    assert isinstance(err.value, CapabilityUnavailableError)
    assert err.value.reason == "rollback_failed"
    assert err.value.orphans == ("backends/foundry",)
    assert "backends/foundry" in str(err.value.detail)
    record = await records.latest("apply-1")
    assert record is not None
    assert record.status == "rollback_failed" and record.orphans == ("backends/foundry",)
    assert set(apim.snapshot()) == {"backends/foundry"}


@dataclass
class _LostResponseApim(InMemoryApim):
    """The first write matching ``lost`` reaches ARM but its response is lost.

    With ``fail_restore`` every later PUT of that path fails before reaching ARM.
    """

    lost: tuple[str, str] = ("PUT", "apis/llm")
    fail_restore: bool = False
    _landed: bool = field(default=False)

    def _after_write(self, method: str, path: str) -> None:
        if (method, path) == self.lost and not self._landed:
            self._landed = True
            raise DependencyTransientError(reason="arm_unreachable")

    async def put(self, path: str, properties: Mapping[str, Any], *, if_match: str | None) -> None:
        if self.fail_restore and self._landed and path == self.lost[1]:
            self.calls.append(ArmCall("PUT", path, if_match))
            raise DependencyTransientError(reason="arm_unreachable")
        await super().put(path, properties, if_match=if_match)
        self._after_write("PUT", path)

    async def delete(self, path: str, *, if_match: str) -> bool:
        deleted = await super().delete(path, if_match=if_match)
        self._after_write("DELETE", path)
        return deleted


async def test_lost_create_response_is_reported_as_orphan_not_deleted() -> None:
    conn, apim, _ = make(_LostResponseApim(service_etag='"svc-1"'))
    req = await reviewed(conn, request(*publication_ops()))
    with pytest.raises(RollbackFailedError) as err:
        await conn.apply(req)
    assert err.value.orphans == ("apis/llm",)
    assert set(apim.snapshot()) == {"apis/llm"}  # ownership unknown: left, reported


_OLD_BACKEND = {"url": "https://old.openai.azure.com/openai", "protocol": "http"}
_NEW_BACKEND = {"url": "https://new.openai.azure.com/openai", "protocol": "http"}
_LINK = "products/ns-grant-g1/apiLinks/llm"


async def test_lost_update_response_restores_the_found_resource() -> None:
    apim = _LostResponseApim(lost=("PUT", "backends/foundry"))
    seeded = apim.seed("backends/foundry", _OLD_BACKEND)
    conn, apim, records = make(apim)
    req = await reviewed(conn, request(upsert("backends/foundry", _NEW_BACKEND)))
    with pytest.raises(DependencyTransientError):
        await conn.apply(req)
    assert apim.snapshot() == {"backends/foundry": _OLD_BACKEND}  # prior put back, not deleted
    puts = [c for c in apim.writes() if c.path == "backends/foundry"]
    assert [c.method for c in puts] == ["PUT", "PUT"]
    assert puts[0].if_match == seeded
    assert puts[1].if_match not in (None, seeded)  # guarded by the ETag our lost write minted
    record = await records.latest("apply-1")
    assert record is not None and record.status == "rolled_back" and record.orphans == ()


async def test_lost_update_response_with_failed_restore_is_rollback_failed() -> None:
    apim = _LostResponseApim(lost=("PUT", "backends/foundry"), fail_restore=True)
    apim.seed("backends/foundry", _OLD_BACKEND)
    conn, apim, records = make(apim)
    req = await reviewed(conn, request(upsert("backends/foundry", _NEW_BACKEND)))
    with pytest.raises(RollbackFailedError) as err:
        await conn.apply(req)
    assert err.value.orphans == ("backends/foundry",)
    assert apim.snapshot() == {"backends/foundry": _NEW_BACKEND}
    record = await records.latest("apply-1")
    assert record is not None
    assert record.status == "rollback_failed" and record.orphans == ("backends/foundry",)


async def test_lost_delete_response_recreates_the_found_resource() -> None:
    apim = _LostResponseApim(lost=("DELETE", _LINK))
    apim.seed(_LINK, PUBLICATION[_LINK])
    conn, apim, records = make(apim)
    req = await reviewed(conn, request(remove(_LINK)))
    with pytest.raises(DependencyTransientError):
        await conn.apply(req)
    assert apim.snapshot() == {_LINK: PUBLICATION[_LINK]}
    restore = apim.writes()[-1]
    assert (restore.method, restore.if_match) == ("PUT", None)  # absent: no If-Match
    record = await records.latest("apply-1")
    assert record is not None and record.status == "rolled_back" and record.orphans == ()


async def test_lost_delete_response_with_failed_restore_is_rollback_failed() -> None:
    apim = _LostResponseApim(lost=("DELETE", _LINK), fail_restore=True)
    apim.seed(_LINK, PUBLICATION[_LINK])
    conn, apim, records = make(apim)
    req = await reviewed(conn, request(remove(_LINK)))
    with pytest.raises(RollbackFailedError) as err:
        await conn.apply(req)
    assert err.value.orphans == (_LINK,)
    assert apim.snapshot() == {}
    record = await records.latest("apply-1")
    assert record is not None
    assert record.status == "rollback_failed" and record.orphans == (_LINK,)


async def test_failed_update_that_did_not_land_needs_no_restore() -> None:
    conn, apim, records = make()
    apim.seed("backends/foundry", _OLD_BACKEND)
    req = await reviewed(conn, request(upsert("backends/foundry", _NEW_BACKEND)))
    apim.fail("PUT", "backends/foundry", DependencyTransientError(reason="arm_unreachable"))
    with pytest.raises(DependencyTransientError):
        await conn.apply(req)
    assert [c.method for c in apim.writes()] == ["PUT"]  # the failed write only, no restore
    assert apim.snapshot() == {"backends/foundry": _OLD_BACKEND}
    record = await records.latest("apply-1")
    assert record is not None and record.status == "rolled_back"


async def test_verify_reads_every_resource_back() -> None:
    conn, apim, _ = make()
    apim.reformat_policies = True
    req = await reviewed(conn, request(*publication_ops()))
    await conn.apply(req)
    gets_before = len([c for c in apim.calls if c.method == "GET"])
    result = await conn.verify(req)
    assert result.matched is True
    read = {c.path for c in apim.calls[gets_before:] if c.method == "GET"}
    assert set(EXPECTED_ORDER) <= read
    # Observed state is booleans only: no policy XML, no named-value references.
    flat = repr(result.observed_state)
    assert "<" not in flat and "{{" not in flat

    props, etag = apim.resources["apis/llm"]
    apim.resources["apis/llm"] = ({**props, "path": "tampered"}, etag)
    tampered = await conn.verify(req)
    assert tampered.matched is False
    assert tampered.mismatched_paths == ("/resources/apis~1llm/matched",)


async def test_rollback_of_succeeded_apply_returns_gateway_to_prior_inventory() -> None:
    conn, apim, records = make()
    apim.seed("apis/other", {"path": "other"})
    before = apim.snapshot()
    applied = await conn.apply(await reviewed(conn, request(*publication_ops())))
    result = await conn.rollback(applied)
    assert result.status == "rolled_back"
    assert apim.snapshot() == before
    deletes = [c.path for c in apim.writes() if c.method == "DELETE"]
    assert deletes == list(reversed(EXPECTED_ORDER))
    record = await records.latest("apply-1")
    assert record is not None and record.status == "rolled_back"


async def test_rollback_leaves_a_created_resource_someone_changed_and_reports_it() -> None:
    conn, apim, _ = make()
    applied = await conn.apply(await reviewed(conn, request(*publication_ops())))
    props, _ = apim.resources["products/ns-grant-g1"]
    apim.seed("products/ns-grant-g1", {**props, "description": "edited by owner"})
    with pytest.raises(RollbackFailedError) as err:
        await conn.rollback(applied)
    assert err.value.orphans == ("products/ns-grant-g1",)
    assert "products/ns-grant-g1" in apim.resources


async def test_rollback_with_unknown_token_is_refused() -> None:
    conn, _, _ = make()
    applied = await conn.apply(await reviewed(conn, request(*publication_ops())))
    bogus = applied.model_copy(update={"rollback_token": "apply-999"})
    with pytest.raises(InvalidSchemaError) as err:
        await conn.rollback(bogus)
    assert err.value.reason == "bad_rollback_token"


async def test_unpublish_writes_deny_first_then_deletes_and_rollback_recreates() -> None:
    conn, apim, _ = make()
    for name, props in PUBLICATION.items():
        apim.seed(name, props)
    before = apim.snapshot()
    deny = fragment_payload(render_deny_fragment())
    req = await reviewed(
        conn,
        request(
            remove("subscriptions/ns-grant-g1-team"),
            remove("products/ns-grant-g1/apiLinks/llm"),
            upsert("policyFragments/ns-grant-g1", deny),
        ),
    )
    applied = await conn.apply(req)
    writes = [(c.method, c.path) for c in apim.writes()]
    assert writes == [
        ("PUT", "policyFragments/ns-grant-g1"),
        ("DELETE", "subscriptions/ns-grant-g1-team"),
        ("DELETE", "products/ns-grant-g1/apiLinks/llm"),
    ]
    assert all(c.if_match for c in apim.writes())  # every write to a found resource is guarded
    assert (await conn.verify(req)).matched is True

    await conn.rollback(applied)
    after = apim.snapshot()
    # Subscription keys are regenerated by APIM on re-create; everything else is restored.
    for snap in (before, after):
        snap["subscriptions/ns-grant-g1-team"].pop("primaryKey", None)
        snap["subscriptions/ns-grant-g1-team"].pop("secondaryKey", None)
    assert after == before


async def test_never_lists_secrets_and_never_surfaces_keys() -> None:
    conn, apim, records = make()
    applied = await conn.apply(await reviewed(conn, request(*publication_ops())))
    assert {c.method for c in apim.calls} <= {"GET", "PUT", "DELETE"}
    assert not any("list" in c.path.lower() for c in apim.calls)
    # The double stored generated keys; no read path returns them.
    sub = await apim.get("subscriptions/ns-grant-g1-team")
    assert sub is not None and "primaryKey" not in sub.properties
    assert "pk-generated-secret" not in repr(applied)
    assert "pk-generated-secret" not in repr(records.history("apply-1"))


async def test_logs_never_carry_policy_xml_or_named_value_references(
    caplog: pytest.LogCaptureFixture,
) -> None:
    conn, apim, _ = make()
    caplog.set_level(logging.DEBUG)
    req = await reviewed(conn, request(*publication_ops()))
    applied = await conn.apply(req)
    await conn.verify(req)
    await conn.rollback(applied)
    apim.fail("PUT", "apis/llm", DependencyTransientError())
    with pytest.raises(DependencyTransientError):
        await conn.apply(await reviewed(conn, request(*publication_ops())))
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert caplog.records  # the applier does log step outcomes
    assert "{{" not in text and "<" not in text and "foundry-key" not in text
