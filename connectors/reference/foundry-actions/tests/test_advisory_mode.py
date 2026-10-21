"""Read-only credentials and unsupported clouds yield an advisory connector with zero writes."""

from __future__ import annotations

import pytest
from foundry_swap_fakes import (
    ACCOUNT,
    READ_PERMS,
    SUB,
    FakeArm,
    FakeCredential,
    swap_request,
)
from neurosphere_connector.write import ApplyResult, WriteConnector, WriteTargetRegistry
from neurosphere_connector_foundry_actions import (
    ADVISORY_CONNECTOR_NAME,
    AccountRef,
    FoundryModelSwapAdvisoryConnector,
    FoundryModelSwapConnector,
    create_swap_connector,
)
from neurosphere_connector_foundry_actions.logic import can_write_deployments
from neurosphere_core.cloud.profile import CloudName
from neurosphere_core.errors import CapabilityUnavailableError

ACTION = "Microsoft.CognitiveServices/accounts/deployments/write"


async def _advisory(arm: FakeArm) -> FoundryModelSwapAdvisoryConnector:
    conn = await create_swap_connector(ACCOUNT, FakeCredential(), client=arm.client())
    assert isinstance(conn, FoundryModelSwapAdvisoryConnector)
    return conn


async def test_read_only_permissions_give_advisory_connector() -> None:
    conn = await _advisory(FakeArm(permissions=READ_PERMS))
    assert conn.advisory is True
    assert conn.manifest.advisory is True
    assert conn.manifest.name == ADVISORY_CONNECTOR_NAME
    assert conn.manifest.write_support.supported is False
    assert isinstance(conn, WriteConnector)


async def test_every_write_method_raises_and_no_put_is_sent() -> None:
    arm = FakeArm(permissions=READ_PERMS)
    conn = await _advisory(arm)
    request = swap_request()
    applied = ApplyResult(
        target=request.target,
        version_before="etag-1",
        applied_diff=request.proposed_diff,
        rollback_token='{"format":"OpenAI","name":"gpt-4o","version":"2024-08-06"}',  # noqa: S106
    )
    for call in (
        conn.dry_run(request),
        conn.apply(request),
        conn.verify(request),
        conn.rollback(applied),
    ):
        with pytest.raises(CapabilityUnavailableError) as err:
            await call
        assert err.value.code == "capability_unavailable"
    assert arm.puts == []
    # Only the permissions read happened; nothing but GET ever left the process.
    assert {r.method for r in arm.requests} == {"GET"}
    assert len(arm.requests) == 1


async def test_registry_rejects_advisory_connector() -> None:
    conn = await _advisory(FakeArm(permissions=READ_PERMS))
    with pytest.raises(CapabilityUnavailableError):
        WriteTargetRegistry().register(conn)


async def test_not_actions_subtract_the_write_permission() -> None:
    perms = {"value": [{"actions": ["*"], "notActions": [ACTION]}]}
    conn = await _advisory(FakeArm(permissions=perms))
    assert conn.reason.startswith(ACTION)


async def test_government_account_is_advisory_without_any_request() -> None:
    gov = AccountRef(
        cloud=CloudName.GOVERNMENT,
        subscription_id=SUB,
        resource_group="rg-ai",
        account="acct1",
        location="usgovvirginia",
    )
    arm = FakeArm()
    conn = await create_swap_connector(gov, FakeCredential(), client=arm.client())
    assert isinstance(conn, FoundryModelSwapAdvisoryConnector)
    assert arm.requests == []


async def test_unreadable_permissions_do_not_grant_write() -> None:
    class Denied(FakeArm):
        def _handle(self, request):  # type: ignore[no-untyped-def]
            import httpx

            self.requests.append(request)
            return httpx.Response(403, json={"error": {"code": "AuthorizationFailed"}})

    arm = Denied()
    conn = await create_swap_connector(ACCOUNT, FakeCredential(), client=arm.client())
    assert isinstance(conn, FoundryModelSwapAdvisoryConnector)
    assert arm.puts == []


def test_permission_matching_rules() -> None:
    assert can_write_deployments([{"actions": ["*"], "notActions": []}])
    assert can_write_deployments([{"actions": ["microsoft.cognitiveservices/accounts/*"]}])
    assert can_write_deployments(
        [{"actions": ["Microsoft.CognitiveServices/accounts/deployments/write"]}]
    )
    assert not can_write_deployments([{"actions": ["Microsoft.CognitiveServices/*/read"]}])
    assert not can_write_deployments([{"actions": ["*"], "notActions": ["*/write"]}])
    assert not can_write_deployments([])
    # Unions across permission objects: a deny in one object does not cancel a grant in another.
    assert can_write_deployments(
        [{"actions": ["*"], "notActions": ["*/write"]}, {"actions": [ACTION]}]
    )


async def test_write_connector_is_returned_when_granted() -> None:
    conn = await create_swap_connector(ACCOUNT, FakeCredential(), client=FakeArm().client())
    assert isinstance(conn, FoundryModelSwapConnector)
