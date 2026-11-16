"""PRP-54 item 1: additive ``target_key`` on ``WriteTargetRegistry``."""

from __future__ import annotations

import pytest
from neurosphere_connector import BaseConnector, build_manifest
from neurosphere_connector.write import (
    ApplyResult,
    DryRunResult,
    RollbackResult,
    VerifyResult,
    WriteRequest,
    WriteTargetRegistry,
)
from neurosphere_contracts.connectors.v1.connector_manifest import ConnectorManifest, Granularity
from neurosphere_core.errors import CapabilityUnavailableError

_GRAIN = Granularity(time_grain="event", subject_level="request")


class Writer(BaseConnector):
    def __init__(self, label: str, *, name: str = "writer") -> None:
        super().__init__()
        self.label = label
        self._name = name

    @property
    def manifest(self) -> ConnectorManifest:
        return build_manifest(
            name=self._name,
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
        raise NotImplementedError

    async def apply(self, request: WriteRequest) -> ApplyResult:
        raise NotImplementedError

    async def verify(self, request: WriteRequest) -> VerifyResult:
        raise NotImplementedError

    async def rollback(self, applied: ApplyResult) -> RollbackResult:
        raise NotImplementedError


def test_unkeyed_single_target_is_unchanged() -> None:
    reg = WriteTargetRegistry()
    one = Writer("one")
    reg.register(one)
    assert reg.get("writer") is one
    assert reg.supports("writer", "model_deployment_swap")
    assert reg.names() == ("writer",)
    assert reg.target_keys("writer") == ()


def test_two_keys_select_by_key_and_names_lists_once() -> None:
    reg = WriteTargetRegistry()
    a, b = Writer("a"), Writer("b")
    reg.register(a, target_key="dom-a")
    reg.register(b, target_key="dom-b")
    assert reg.get("writer", target_key="dom-a") is a
    assert reg.get("writer", target_key="dom-b") is b
    assert reg.names() == ("writer",)
    assert reg.target_keys("writer") == ("dom-a", "dom-b")


def test_get_without_key_is_ambiguous_when_several() -> None:
    reg = WriteTargetRegistry()
    reg.register(Writer("a"), target_key="dom-a")
    reg.register(Writer("b"), target_key="dom-b")
    with pytest.raises(CapabilityUnavailableError) as ei:
        reg.get("writer")
    assert ei.value.reason == "target_ambiguous"
    assert reg.supports("writer", "model_deployment_swap") is False


def test_single_keyed_target_answers_an_unkeyed_get() -> None:
    reg = WriteTargetRegistry()
    a = Writer("a")
    reg.register(a, target_key="dom-a")
    assert reg.get("writer") is a


def test_unknown_key_without_default_has_no_target() -> None:
    reg = WriteTargetRegistry()
    reg.register(Writer("a"), target_key="dom-a")
    assert reg.supports("writer", "model_deployment_swap", target_key="dom-x") is False
    with pytest.raises(CapabilityUnavailableError) as ei:
        reg.get("writer", target_key="dom-x")
    assert ei.value.reason == "not_a_write_target"


def test_keyless_registration_is_the_default_for_other_keys() -> None:
    reg = WriteTargetRegistry()
    default, own = Writer("default"), Writer("own")
    reg.register(default)
    reg.register(own, target_key="dom-a")
    assert reg.get("writer", target_key="dom-a") is own
    assert reg.get("writer", target_key="dom-z") is default


def test_other_manifest_names_are_independent() -> None:
    reg = WriteTargetRegistry()
    reg.register(Writer("a"), target_key="dom-a")
    reg.register(Writer("o", name="other"))
    assert reg.names() == ("other", "writer")
    assert reg.get("other").label == "o"  # type: ignore[attr-defined]
