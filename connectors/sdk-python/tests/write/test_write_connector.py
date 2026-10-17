"""Write path: advisory connectors, verify vs requested diff, registry, lifecycle, no Azure."""

from __future__ import annotations

import subprocess
import sys
from typing import Any

import pytest
from neurosphere_connector import BaseConnector, build_manifest
from neurosphere_connector.write import (
    AdvisoryWriteMixin,
    ApplyResult,
    DryRunResult,
    RollbackResult,
    VerifyResult,
    WriteConnector,
    WriteRequest,
    WriteTargetRegistry,
    build_verify_result,
    register_write_target,
)
from neurosphere_contracts.actions.v1.action_intent import PatchOperation, ProposedDiff
from neurosphere_contracts.actions.v1.target_ref import TargetRef
from neurosphere_contracts.connectors.v1.connector_manifest import ConnectorManifest, Granularity
from neurosphere_core.errors import CapabilityUnavailableError

_GRAIN = Granularity(time_grain="event", subject_level="request")
_TARGET = TargetRef(
    canonical_id="commercial:acme:foundry:model_deployment:dep1", entity_type="model_deployment"
)


def _request() -> WriteRequest:
    return WriteRequest(
        target=_TARGET,
        target_version="v1",
        proposed_diff=ProposedDiff(
            format="json_patch",
            operations=[PatchOperation(op="replace", path="/model", value="gpt-b")],
        ),
    )


class ReadOnly(AdvisoryWriteMixin, BaseConnector):
    @property
    def manifest(self) -> ConnectorManifest:
        return build_manifest(
            name="ro",
            version="0.1.0",
            capabilities=["telemetry_ingest"],
            supported_clouds=["commercial"],
            granularity=_GRAIN,
        )


class FakeWriter(BaseConnector):
    """Real target state lives in ``state``; ``pretend`` edits only metadata."""

    def __init__(self, *, pretend: bool = False) -> None:
        super().__init__()
        self.state: dict[str, Any] = {"model": "gpt-a"}
        self.metadata: dict[str, Any] = {"model": "gpt-a"}
        self.pretend = pretend

    @property
    def manifest(self) -> ConnectorManifest:
        return build_manifest(
            name="writer",
            version="0.1.0",
            capabilities=["action_execution"],
            supported_clouds=["commercial"],
            granularity=_GRAIN,
            write_actions=["model_deployment_swap"],
        )

    @property
    def advisory(self) -> bool:
        return False

    async def dry_run(self, request: WriteRequest) -> DryRunResult:
        return DryRunResult(
            target=request.target,
            target_version=request.target_version,
            planned_diff=request.proposed_diff,
            would_change=self.state.get("model") != "gpt-b",
        )

    async def apply(self, request: WriteRequest) -> ApplyResult:
        self.metadata["model"] = "gpt-b"
        if not self.pretend:
            self.state["model"] = "gpt-b"
        return ApplyResult(
            target=request.target,
            version_before=request.target_version,
            version_after="v2",
            applied_diff=request.proposed_diff,
            rollback_token="tok",  # noqa: S106
        )

    async def verify(self, request: WriteRequest) -> VerifyResult:
        return build_verify_result(request, dict(self.state), observed_version="v2")

    async def rollback(self, applied: ApplyResult) -> RollbackResult:
        self.state["model"] = "gpt-a"
        return RollbackResult(target=applied.target, status="rolled_back", version_after="v3")


async def test_read_only_is_advisory_and_writes_raise() -> None:
    c = ReadOnly()
    assert c.advisory is True
    with pytest.raises(CapabilityUnavailableError) as ei:
        await c.apply(_request())
    assert ei.value.code == "capability_unavailable"
    with pytest.raises(CapabilityUnavailableError):
        await c.rollback(
            ApplyResult(target=_TARGET, version_before="v1", applied_diff=_request().proposed_diff)
        )


async def test_verify_separates_observed_state_from_requested_diff() -> None:
    c = FakeWriter()
    req = _request()
    await c.apply(req)
    result = await c.verify(req)
    assert result.requested_diff == req.proposed_diff
    assert result.observed_state == {"model": "gpt-b"}
    assert result.matched is True
    assert result.mismatched_paths == ()


async def test_verify_flags_pretend_change() -> None:
    c = FakeWriter(pretend=True)
    req = _request()
    await c.apply(req)
    assert c.metadata["model"] == "gpt-b"
    result = await c.verify(req)
    assert result.observed_state == {"model": "gpt-a"}
    assert result.matched is False
    assert result.mismatched_paths == ("/model",)


async def test_verify_remove_move_copy_checks() -> None:
    diff = ProposedDiff(
        format="json_patch",
        operations=[
            PatchOperation(op="remove", path="/gone"),
            PatchOperation.model_validate({"op": "move", "from": "/a", "path": "/b"}),
            PatchOperation.model_validate({"op": "copy", "from": "/b", "path": "/c"}),
        ],
    )
    req = WriteRequest(target=_TARGET, target_version="v1", proposed_diff=diff)
    ok = build_verify_result(req, {"b": 1, "c": 1})
    assert ok.matched is True
    bad = build_verify_result(req, {"gone": 1, "a": 1, "b": 1, "c": 2})
    assert bad.mismatched_paths == ("/gone", "/b", "/c")


def test_registry_rejects_non_write_connectors() -> None:
    reg = WriteTargetRegistry()
    for bad in (ReadOnly(), object()):
        with pytest.raises(CapabilityUnavailableError):
            register_write_target(reg, bad)
    assert reg.names() == ()
    with pytest.raises(CapabilityUnavailableError):
        reg.get("ro")


def test_registry_rejects_advisory_flag_even_with_write_manifest() -> None:
    class Lying(FakeWriter):
        @property
        def advisory(self) -> bool:
            return True

    with pytest.raises(CapabilityUnavailableError):
        WriteTargetRegistry().register(Lying())


def test_registry_accepts_conforming_connector() -> None:
    reg = WriteTargetRegistry()
    c = FakeWriter()
    assert isinstance(c, WriteConnector)
    assert register_write_target(reg, c) is c
    assert reg.get("writer") is c
    assert reg.supports("writer", "model_deployment_swap")
    assert not reg.supports("writer", "policy_update")


async def test_happy_path_typed_results() -> None:
    c = FakeWriter()
    req = _request()
    plan = await c.dry_run(req)
    assert isinstance(plan, DryRunResult)
    assert plan.would_change and plan.target_version == "v1"
    assert c.state["model"] == "gpt-a"  # dry run wrote nothing
    applied = await c.apply(req)
    assert isinstance(applied, ApplyResult) and applied.version_after == "v2"
    assert (await c.verify(req)).matched
    rolled = await c.rollback(applied)
    assert isinstance(rolled, RollbackResult) and rolled.status == "rolled_back"
    assert c.state["model"] == "gpt-a"
    assert (await c.verify(req)).matched is False


def test_results_forbid_extra_fields() -> None:
    with pytest.raises(ValueError):
        RollbackResult.model_validate({"target": _TARGET, "status": "rolled_back", "x": 1})


def test_import_pulls_in_no_azure_modules() -> None:
    code = (
        "import sys, neurosphere_connector.write;"
        "bad = sorted(m for m in sys.modules if m == 'azure' or m.startswith('azure.'));"
        "print(bad); sys.exit(1 if bad else 0)"
    )
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
