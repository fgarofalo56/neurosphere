"""PRP-09 r2 item 13: the Python contract kit run against every reference connector.

Each connector is built with fakes (fake token provider, fake reader, scripted transport, in-memory
ARM) and no network; a socket guard makes any real connection attempt fail the test. A deliberately
broken connector proves the kit can fail, so the suite cannot pass vacuously.
"""

from __future__ import annotations

import importlib.util
import ipaddress
import socket
import sys
from collections.abc import AsyncIterator, Callable, Mapping
from pathlib import Path
from types import TracebackType
from typing import Any

import httpx
import pytest
from neurosphere_connector import CredentialBroker, StaticCredentialResolver
from neurosphere_connector.contract_kit import (
    Violation,
    check_connector_contract,
    check_write_connector_contract,
)
from neurosphere_connector_apim_gateway import ApimGatewayConnector, InMemoryApplyRecordStore
from neurosphere_connector_azure_billing import AzureBillingConnector
from neurosphere_connector_azure_monitor import AzureMonitorConnector
from neurosphere_connector_foundry import FoundryDiscoveryConnector, project_endpoint
from neurosphere_connector_foundry_actions import (
    ArmClient,
    FoundryModelSwapConnector,
)
from neurosphere_connector_otel_generic import DEFAULT_CREDENTIAL_REF, OtelGenericConnector
from neurosphere_core.cloud.profile import CloudName

REPO = Path(__file__).resolve().parents[3]
REF = REPO / "connectors" / "reference"


def _load(name: str, path: Path) -> Any:
    """Import a connector package's shared test-support module by file path (not a package)."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refuse any non-loopback connect. Loopback stays open: the Windows event loop builds its
    self-pipe with a loopback socketpair."""
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


class _FakeSource:
    async def read_manifest(self) -> bytes:
        return b"{}"

    async def read_blob(self, name: str) -> bytes:
        return b""


class _FakeReader:
    async def list_agents(self, *, page_size: int) -> AsyncIterator[Mapping[str, Any]]:
        for item in ():
            yield item

    async def list_deployments(self) -> AsyncIterator[Mapping[str, Any]]:
        for item in ():
            yield item

    async def close(self) -> None:
        return None


class _FakeCredential:
    async def get_token(self, *scopes: str, **_: Any) -> Any:
        raise AssertionError("not called by the kit")

    async def close(self) -> None:
        return None

    async def __aenter__(self) -> _FakeCredential:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        return None


async def _token(scope: str) -> str:
    return "fake-token-for-tests"


def _otel() -> Any:
    resolver = StaticCredentialResolver({DEFAULT_CREDENTIAL_REF.vault_ref: "synthetic"})

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    return OtelGenericConnector(
        ingest_url="http://edge.invalid/v1/ingest",
        credentials=CredentialBroker(resolver, [DEFAULT_CREDENTIAL_REF]),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def _azure_monitor() -> Any:
    return AzureMonitorConnector(token_provider=_token)


def _foundry() -> Any:
    return FoundryDiscoveryConnector(
        reader=_FakeReader(),
        cloud=CloudName.COMMERCIAL,
        project_endpoint=project_endpoint(CloudName.COMMERCIAL, "res-one", "proj-one"),
    )


def _azure_billing() -> Any:
    return AzureBillingConnector(source=_FakeSource(), basis="actual")


def _apim_gateway() -> Any:
    support = _load(
        "apim_write_support_conformance", REF / "apim-gateway/tests/apim_write_support.py"
    )
    apim = support.InMemoryApim(service_etag=support.SERVICE_ETAG)
    return ApimGatewayConnector(
        support.GATEWAY,
        apim,
        records=InMemoryApplyRecordStore(),
        mode=support.mode_handler(apim),
    )


def _foundry_actions() -> Any:
    support = _load(
        "foundry_swap_fakes_conformance", REF / "foundry-actions/tests/foundry_swap_fakes.py"
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    return FoundryModelSwapConnector(
        support.ACCOUNT, ArmClient(support.ACCOUNT, _FakeCredential(), client=client)
    )


# Read connectors run the read profile; write connectors (WriteConnector protocol, not
# BaseConnector) run the write profile. Both assert no violations, so a construction error fails.
_READ_CASES: list[Any] = [
    pytest.param(_otel, id="otel-generic"),
    pytest.param(_azure_monitor, id="azure-monitor"),
    pytest.param(_foundry, id="foundry"),
    pytest.param(_azure_billing, id="azure-billing"),
]
_WRITE_CASES: list[Any] = [
    pytest.param(_apim_gateway, id="apim-gateway"),
    pytest.param(_foundry_actions, id="foundry-actions"),
]
_CASES: list[Any] = [*_READ_CASES, *_WRITE_CASES]


@pytest.mark.parametrize("factory", _READ_CASES)
async def test_read_connector_passes_the_read_profile(factory: Callable[[], Any]) -> None:
    violations = await check_connector_contract(factory())
    assert violations == [], [(v.code, v.message) for v in violations]


@pytest.mark.parametrize("factory", _WRITE_CASES)
async def test_write_connector_passes_the_write_profile(factory: Callable[[], Any]) -> None:
    connector = factory()
    violations = await check_write_connector_contract(connector)
    assert violations == [], [(v.code, v.message) for v in violations]
    health = await connector.health()
    assert health.state.value == "unknown"


def _without_health(factory: Callable[[], Any]) -> Any:
    """A real write connector with its health() removed."""
    connector = factory()
    cls = type("NoHealth", (type(connector),), {"health": None})
    connector.__class__ = cls
    return connector


@pytest.mark.parametrize("factory", _WRITE_CASES)
async def test_write_profile_fails_a_write_connector_without_health(
    factory: Callable[[], Any],
) -> None:
    codes = {v.code for v in await check_write_connector_contract(_without_health(factory))}
    assert "health_missing" in codes


@pytest.mark.parametrize("factory", _READ_CASES)
async def test_write_profile_fails_a_read_connector(factory: Callable[[], Any]) -> None:
    codes = {v.code for v in await check_write_connector_contract(factory())}
    assert "write_protocol_missing" in codes


async def test_write_profile_fails_an_advisory_write_connector() -> None:
    connector = _apim_gateway()
    advisory = connector.manifest.model_copy(update={"advisory": True})
    connector.__class__ = type(
        "AdvisoryManifest", (type(connector),), {"manifest": property(lambda _self: advisory)}
    )
    codes = {v.code for v in await check_write_connector_contract(connector)}
    assert "manifest_advisory" in codes


def test_all_six_reference_connectors_are_covered() -> None:
    ids = {p.id for p in _CASES}
    on_disk = {p.name for p in REF.iterdir() if (p / "pyproject.toml").is_file()}
    assert ids == on_disk


class _Broken:
    """Valid manifest but no health, coverage or freshness at all."""

    @property
    def manifest(self) -> Any:
        return _azure_billing().manifest


class _RaisingHealth:
    manifest = None

    async def health(self) -> Any:
        raise RuntimeError("boom")


async def test_kit_fails_a_connector_without_health_coverage_freshness() -> None:
    violations = await check_connector_contract(_Broken())
    codes = {v.code for v in violations}
    assert {"health_missing", "coverage_missing", "freshness_missing"} <= codes
    assert all(isinstance(v, Violation) for v in violations)


async def test_kit_fails_a_broken_subclass_of_a_reference_connector() -> None:
    class NoHealth(AzureBillingConnector):
        health = None  # type: ignore[assignment]

    violations = await check_connector_contract(NoHealth(source=_FakeSource(), basis="actual"))
    assert "health_missing" in {v.code for v in violations}


async def test_kit_reports_missing_manifest_and_raising_health() -> None:
    codes = {v.code for v in await check_connector_contract(_RaisingHealth())}
    assert {"manifest_missing", "health_raised"} <= codes
