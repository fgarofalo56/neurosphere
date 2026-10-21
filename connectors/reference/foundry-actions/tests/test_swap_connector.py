"""Foundry model swap connector against a scripted ARM (httpx.MockTransport; no network)."""

from __future__ import annotations

import json

import pytest
from foundry_swap_fakes import (
    ACCOUNT,
    DEFAULT_MODELS,
    TODAY,
    TOKEN,
    FakeArm,
    FakeCredential,
    Sleeper,
    deployment,
    model_entry,
    request_for,
    swap_request,
)
from neurosphere_connector.write import WriteConnector, WriteTargetRegistry
from neurosphere_connector_foundry_actions import (
    CONNECTOR_NAME,
    AccountRef,
    ArmClient,
    FoundryModelSwapConnector,
    create_swap_connector,
)
from neurosphere_core.cloud.profile import CloudName
from neurosphere_core.errors import (
    CapabilityUnavailableError,
    DependencyTransientError,
    InvalidSchemaError,
    StaleVersionError,
)

PRIOR = '{"format":"OpenAI","name":"gpt-4o","version":"2024-08-06"}'


def _connector(
    arm: FakeArm, sleeper: Sleeper | None = None, account: AccountRef = ACCOUNT
) -> FoundryModelSwapConnector:
    s = sleeper or Sleeper()
    return FoundryModelSwapConnector(
        account,
        ArmClient(account, FakeCredential(), client=arm.client()),
        sleep=s.sleep,
        clock=s.clock,
        today=lambda: TODAY,
    )


async def test_registers_as_write_target_with_swap_action() -> None:
    conn = _connector(FakeArm())
    assert isinstance(conn, WriteConnector)
    assert conn.advisory is False
    assert conn.manifest.name == CONNECTOR_NAME
    assert conn.manifest.write_support.actions == ["model_deployment_swap"]
    registry = WriteTargetRegistry()
    registry.register(conn)
    assert registry.supports(CONNECTOR_NAME, "model_deployment_swap")


async def test_dry_run_writes_nothing_and_uses_documented_api_versions() -> None:
    arm = FakeArm()
    result = await _connector(arm).dry_run(swap_request())
    assert result.would_change is True
    assert arm.puts == []
    versions = {r.url.params["api-version"] for r in arm.requests}
    assert versions == {"2024-10-01"}
    assert all(r.url.host == "management.azure.com" for r in arm.requests)
    assert all(TOKEN not in str(r.url) for r in arm.requests)


async def test_dry_run_same_model_would_not_change() -> None:
    arm = FakeArm()
    req = request_for(("replace", "/properties/model/name", "gpt-4o"))
    assert (await _connector(arm).dry_run(req)).would_change is False


async def test_apply_polls_to_succeeded_and_returns_rollback_token() -> None:
    arm = FakeArm(post_put_states=["Creating", "Creating", "Succeeded"])
    sleeper = Sleeper()
    result = await _connector(arm, sleeper).apply(swap_request())
    assert len(arm.puts) == 1
    assert arm.puts[0].url.params["api-version"] == "2024-10-01"
    assert result.version_before == "etag-1"
    assert result.version_after == "etag-2"
    assert result.rollback_token == PRIOR
    assert len(sleeper.sleeps) == 3


async def test_put_body_preserves_everything_but_the_model() -> None:
    arm = FakeArm(put_state="Succeeded")
    await _connector(arm).apply(swap_request())
    body = arm.put_bodies[0]
    assert body == {
        "sku": {"name": "Standard", "capacity": 3},
        "tags": {"team": "ai"},
        "properties": {
            "model": {"format": "OpenAI", "name": "gpt-4.1", "version": "2025-04-14"},
            "versionUpgradeOption": "NoAutoUpgrade",
            "raiPolicyName": "Microsoft.Default",
        },
    }


async def test_apply_rereads_etag_immediately_before_put() -> None:
    arm = FakeArm()
    gets = {"n": 0}

    def drift(a: FakeArm) -> None:
        gets["n"] += 1
        if gets["n"] == 2:  # the re-GET right before the PUT
            a.state["etag"] = "etag-other"

    arm.on_get = drift
    with pytest.raises(StaleVersionError) as err:
        await _connector(arm).apply(swap_request())
    assert err.value.reason == "target_version_changed"
    assert arm.puts == []


async def test_stale_etag_rejected_in_dry_run_and_apply() -> None:
    arm = FakeArm()
    conn = _connector(arm)
    for call in (conn.dry_run, conn.apply):
        with pytest.raises(StaleVersionError) as err:
            await call(swap_request(etag="old-etag"))
        assert err.value.reason == "target_version_changed"
    assert arm.puts == []


@pytest.mark.parametrize(
    ("op", "path"),
    [
        ("replace", "/sku/capacity"),
        ("replace", "/properties/raiPolicyName"),
        ("replace", "/properties/model/format"),
        ("remove", "/properties/model/name"),
        ("add", "/properties/model/name"),
    ],
)
async def test_unsupported_diff_path_or_op(op: str, path: str) -> None:
    arm = FakeArm()
    with pytest.raises(InvalidSchemaError) as err:
        await _connector(arm).dry_run(request_for((op, path, "x")))
    assert err.value.reason == "unsupported_diff_path"
    assert arm.puts == []


async def test_failing_test_op_is_stale() -> None:
    arm = FakeArm()
    req = request_for(("test", "/properties/model/name", "not-current"))
    with pytest.raises(StaleVersionError) as err:
        await _connector(arm).dry_run(req)
    assert err.value.reason == "diff_test_failed"


@pytest.mark.parametrize(
    ("models", "failed"),
    [
        ([DEFAULT_MODELS[0]], "target_model_exists"),
        (
            [DEFAULT_MODELS[0], model_entry("gpt-4.1", "2025-04-14", lifecycle="Deprecated")],
            "lifecycle_not_deprecated",
        ),
        (
            [DEFAULT_MODELS[0], model_entry("gpt-4.1", "2025-04-14", deprecation="2026-10-20")],
            "inference_not_retired",
        ),
        (
            [DEFAULT_MODELS[0], model_entry("gpt-4.1", "2025-04-14", skus=("GlobalStandard",))],
            "sku_supported",
        ),
        (
            [DEFAULT_MODELS[0], model_entry("gpt-4.1", "2025-04-14", caps={"other": "true"})],
            "capability_keys_preserved",
        ),
        (
            [DEFAULT_MODELS[0], model_entry("gpt-4.1", "2025-04-14", fmt="Other")],
            "target_model_exists",
        ),
    ],
)
async def test_compatibility_failures_block_dry_run_and_apply(
    models: list[dict], failed: str
) -> None:
    arm = FakeArm(models=models)
    conn = _connector(arm)
    for call in (conn.dry_run, conn.apply):
        with pytest.raises(InvalidSchemaError) as err:
            await call(swap_request())
        assert err.value.reason == "compatibility_failed"
        assert failed in str(err.value)
    assert arm.puts == []


async def test_future_deprecation_passes_and_unknowns_are_warnings_not_passes() -> None:
    models = [DEFAULT_MODELS[0], model_entry("gpt-4.1", "2025-04-14", deprecation="2027-01-01")]
    arm = FakeArm(models=models)
    checks = {c.check_id: c for c in await _connector(arm).check_compatibility(swap_request())}
    assert checks["inference_not_retired"].status == "passed"
    assert checks["context_window"].status == "unknown"
    assert checks["tool_support"].status == "unknown"
    assert not any(c.status == "failed" for c in checks.values())


async def test_apply_failed_provisioning_is_an_error() -> None:
    arm = FakeArm(post_put_states=["Creating", "Failed"])
    with pytest.raises(CapabilityUnavailableError) as err:
        await _connector(arm).apply(swap_request())
    assert err.value.reason == "provisioning_failed"


async def test_apply_canceled_provisioning_is_an_error() -> None:
    arm = FakeArm(put_state="Canceled")
    with pytest.raises(CapabilityUnavailableError):
        await _connector(arm).apply(swap_request())


async def test_polling_is_bounded() -> None:
    arm = FakeArm(post_put_states=["Creating"] * 500)
    sleeper = Sleeper()
    with pytest.raises(DependencyTransientError) as err:
        await _connector(arm, sleeper).apply(swap_request())
    assert err.value.reason == "poll_timeout"
    assert len(sleeper.sleeps) <= 61


async def test_verify_reads_observed_state_after_apply() -> None:
    arm = FakeArm(put_state="Succeeded")
    conn = _connector(arm)
    req = swap_request()
    await conn.apply(req)
    result = await conn.verify(req.model_copy(update={"target_version": "etag-2"}))
    assert result.matched is True
    assert result.observed_version == "etag-2"
    assert result.observed_state["properties"]["model"]["name"] == "gpt-4.1"


async def test_verify_detects_unchanged_state() -> None:
    """A swap that never happened (state still on the old model) must not verify."""
    result = await _connector(FakeArm()).verify(swap_request())
    assert result.matched is False
    assert "/properties/model/name" in result.mismatched_paths


async def test_verify_requires_succeeded_provisioning() -> None:
    state = deployment("gpt-4.1", "2025-04-14")
    state["properties"]["provisioningState"] = "Creating"
    result = await _connector(FakeArm(state)).verify(
        request_for(("replace", "/properties/model/name", "gpt-4.1"))
    )
    assert result.matched is False
    assert "/properties/provisioningState" in result.mismatched_paths


async def test_rollback_restores_prior_model_from_stored_result_alone() -> None:
    arm = FakeArm(put_state="Succeeded")
    conn = _connector(arm)
    applied = await conn.apply(swap_request())
    # A fresh connector (as after a worker crash) rolls back from the persisted ApplyResult.
    fresh = _connector(arm)
    result = await fresh.rollback(applied)
    assert result.status == "rolled_back"
    assert result.version_after == "etag-3"
    assert arm.state["properties"]["model"] == {
        "format": "OpenAI",
        "name": "gpt-4o",
        "version": "2024-08-06",
    }
    assert arm.put_bodies[-1]["sku"] == {"name": "Standard", "capacity": 3}


async def test_rollback_when_already_on_prior_model_is_not_needed() -> None:
    arm = FakeArm()
    conn = _connector(arm)
    applied = (await _applied(arm)).model_copy(update={"version_after": "etag-1"})
    result = await conn.rollback(applied)
    assert result.status == "not_needed"
    assert arm.puts == []


async def _applied(arm: FakeArm):
    return await _connector(FakeArm(put_state="Succeeded")).apply(swap_request())


async def test_rollback_refuses_when_target_changed_since_apply() -> None:
    arm = FakeArm(put_state="Succeeded")
    conn = _connector(arm)
    applied = await conn.apply(swap_request())
    arm.state["etag"] = "someone-else"
    with pytest.raises(StaleVersionError):
        await conn.rollback(applied)


async def test_rollback_rejects_garbage_token() -> None:
    applied = (await _applied(FakeArm())).model_copy(update={"rollback_token": "{not json"})
    with pytest.raises(InvalidSchemaError) as err:
        await _connector(FakeArm(put_state="Succeeded")).rollback(applied)
    assert err.value.reason == "bad_rollback_token"


async def test_government_target_is_refused_without_any_request() -> None:
    gov = AccountRef(
        cloud=CloudName.GOVERNMENT,
        subscription_id=ACCOUNT.subscription_id,
        resource_group="rg-ai",
        account="acct1",
        location="usgovvirginia",
    )
    arm = FakeArm()
    conn = _connector(arm, account=gov)
    req = swap_request()
    for call in (conn.dry_run, conn.apply, conn.verify):
        with pytest.raises(CapabilityUnavailableError) as err:
            await call(req)
        assert err.value.reason == "deployment_write_unavailable"
    assert arm.requests == []


async def test_cloud_mismatch_between_target_and_connector() -> None:
    arm = FakeArm()
    with pytest.raises(InvalidSchemaError) as err:
        await _connector(arm).dry_run(
            request_for(("replace", "/properties/model/name", "gpt-4.1"), cloud="government")
        )
    assert err.value.reason == "cloud_mismatch"
    assert arm.requests == []


async def test_factory_returns_write_connector_with_write_permission() -> None:
    arm = FakeArm()
    cred = FakeCredential()
    conn = await create_swap_connector(ACCOUNT, cred, client=arm.client())
    assert isinstance(conn, FoundryModelSwapConnector)
    assert [r.method for r in arm.requests] == ["GET"]
    assert cred.scopes == [("https://management.azure.com/.default",)]


async def test_token_never_appears_in_errors() -> None:
    arm = FakeArm(models=[])
    with pytest.raises(InvalidSchemaError) as err:
        await _connector(arm).dry_run(swap_request())
    assert TOKEN not in str(err.value)
    assert TOKEN not in json.dumps(err.value.reason)
