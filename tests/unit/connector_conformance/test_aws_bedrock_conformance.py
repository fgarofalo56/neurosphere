"""PRP-62 item 5: the read-profile contract kit against the AWS Bedrock connector.

Built with a fake reader and no network; a socket guard makes any real connection attempt fail the
test. A deliberately broken variant proves the kit can reject this connector's shape, so the suite
cannot pass vacuously.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from neurosphere_connector.contract_kit import Violation, check_connector_contract
from neurosphere_connector_aws_bedrock import connector as connector_module
from neurosphere_connector_aws_bedrock.connector import AwsBedrockConnector
from neurosphere_connector_aws_bedrock.models import CostWindow, UsageWindow
from neurosphere_connector_aws_bedrock.reader import READER_OPERATIONS, BedrockReader, ReaderPage
from neurosphere_core.cloud.profile import CloudName

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refuse any non-loopback connect (loopback stays open for the event loop's self-pipe)."""
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def _check(address: Any) -> None:
        host = address[0] if isinstance(address, tuple) else address
        if not (isinstance(host, str) and ipaddress.ip_address(host).is_loopback):
            raise AssertionError(f"contract-kit conformance must not open a socket: {host!r}")

    def connect(self: socket.socket, address: Any) -> None:
        _check(address)
        real_connect(self, address)

    def connect_ex(self: socket.socket, address: Any) -> int:
        _check(address)
        return real_connect_ex(self, address)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)


class _FakeReader:
    async def list_foundation_models(self, *, limit: int) -> ReaderPage:
        return ReaderPage(items=())

    list_custom_models = list_provisioned_throughput = list_guardrails = list_agents = (
        list_foundation_models
    )

    async def get_usage(
        self, *, model_ids: Sequence[str], window: UsageWindow, limit: int
    ) -> ReaderPage:
        return ReaderPage(items=())

    async def get_cost(
        self, *, window: CostWindow, services: Sequence[str], limit: int
    ) -> ReaderPage:
        return ReaderPage(items=())

    async def get_invocation_logging(self) -> Mapping[str, Any]:
        return {"cloudwatch": False, "s3": False}

    async def close(self) -> None:
        return None


def _connector() -> AwsBedrockConnector:
    return AwsBedrockConnector(reader=_FakeReader(), cloud=CloudName.COMMERCIAL, region="us-east-1")


def test_fake_reader_satisfies_the_protocol() -> None:
    assert isinstance(_FakeReader(), BedrockReader)
    assert {n for n in vars(_FakeReader) if not n.startswith("_")} == set(READER_OPERATIONS)


async def test_aws_bedrock_passes_the_read_profile() -> None:
    violations = await check_connector_contract(_connector())
    assert violations == [], [(v.code, v.message) for v in violations]


async def test_aws_bedrock_still_passes_after_a_real_call() -> None:
    connector = _connector()
    await connector.inventory()
    assert await check_connector_contract(connector) == []
    assert (await connector.health()).state.value == "healthy"


async def test_kit_fails_a_broken_subclass_without_health() -> None:
    class NoHealth(AwsBedrockConnector):
        health = None  # type: ignore[assignment]

    violations = await check_connector_contract(
        NoHealth(reader=_FakeReader(), cloud=CloudName.COMMERCIAL, region="us-east-1")
    )
    assert "health_missing" in {v.code for v in violations}
    assert all(isinstance(v, Violation) for v in violations)


async def test_kit_fails_a_variant_with_an_invalid_manifest() -> None:
    class BadManifest(AwsBedrockConnector):
        @property
        def manifest(self) -> Any:
            return _connector().manifest.model_copy(update={"advisory": False})

    codes = {
        v.code
        for v in await check_connector_contract(
            BadManifest(reader=_FakeReader(), cloud=CloudName.COMMERCIAL, region="us-east-1")
        )
    }
    assert "manifest_invalid" in codes


def test_the_connector_is_a_workspace_member_in_all_five_images() -> None:
    """Every image that runs ``uv sync --frozen`` copies the member (PRP-62 images criterion)."""
    for dockerfile in (
        "services/api/Dockerfile",
        "services/api/Dockerfile.dev",
        "services/workers/Dockerfile",
        "services/workers/Dockerfile.dev",
        "scripts/sandbox/Dockerfile.seed",
    ):
        text = (REPO / dockerfile).read_text(encoding="utf-8")
        assert "COPY connectors/reference/aws-bedrock " in text, dockerfile


def test_module_under_test_is_the_one_on_disk() -> None:
    assert "aws-bedrock" in Path(connector_module.__file__).as_posix()
