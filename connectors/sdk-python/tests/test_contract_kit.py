"""The contract kit fails broken connectors and passes conforming ones."""

from __future__ import annotations

from typing import Any

import pytest
from neurosphere_connector import BaseConnector, build_manifest, check_connector_contract
from neurosphere_connector.contract_kit import check_write_connector_contract
from neurosphere_connector.testing import ConnectorContractSuite
from neurosphere_contracts.connectors.v1.connector_manifest import ConnectorManifest, Granularity


def _manifest() -> ConnectorManifest:
    return build_manifest(
        name="demo",
        version="0.1.0",
        capabilities=["telemetry_ingest", "health_reporting"],
        supported_clouds=["commercial"],
        granularity=Granularity(time_grain="event", subject_level="request"),
    )


class Conforming(BaseConnector):
    @property
    def manifest(self) -> ConnectorManifest:
        return _manifest()


class NoHealth:
    manifest = _manifest()

    async def coverage(self) -> Any:
        return None


class NoManifest:
    pass


class NoCoverage:
    manifest = _manifest()

    async def health(self) -> Any:
        return await Conforming().health()


class BadManifest(Conforming):
    @property
    def manifest(self) -> ConnectorManifest:
        # Bypass validation to simulate a connector shipping an inconsistent manifest.
        return _manifest().model_copy(update={"advisory": False})


async def _codes(connector: Any) -> set[str]:
    return {v.code for v in await check_connector_contract(connector)}


async def test_conforming_connector_passes() -> None:
    assert await check_connector_contract(Conforming()) == []


async def test_missing_health_fails() -> None:
    assert "health_missing" in await _codes(NoHealth())


async def test_missing_manifest_fails() -> None:
    assert "manifest_missing" in await _codes(NoManifest())


async def test_missing_coverage_fails() -> None:
    assert "coverage_missing" in await _codes(NoCoverage())


async def test_invalid_manifest_fails() -> None:
    assert "manifest_invalid" in await _codes(BadManifest())


async def test_wrong_report_type_fails() -> None:
    class Wrong(Conforming):
        async def health(self) -> Any:
            return {"state": "healthy"}

    assert "health_type" in await _codes(Wrong())


class TestConformingViaSuite(ConnectorContractSuite):
    @pytest.fixture
    def connector(self) -> Conforming:
        return Conforming()


# -- write profile -------------------------------------------------------------------------


def _write_manifest(*, advisory_override: bool = False) -> ConnectorManifest:
    manifest = build_manifest(
        name="demo-writer",
        version="0.1.0",
        capabilities=["health_reporting"],
        supported_clouds=["commercial"],
        granularity=Granularity(time_grain="event", subject_level="request"),
        write_actions=["agent_disable"],
    )
    return manifest.model_copy(update={"advisory": True}) if advisory_override else manifest


class Writer:
    """Minimal conforming write connector (no coverage or freshness, which is allowed)."""

    advisory = False

    def __init__(self, manifest: ConnectorManifest | None = None) -> None:
        self._manifest = manifest or _write_manifest()

    @property
    def manifest(self) -> ConnectorManifest:
        return self._manifest

    async def health(self) -> Any:
        return await Conforming().health()

    async def dry_run(self, request: Any) -> Any: ...
    async def apply(self, request: Any) -> Any: ...
    async def verify(self, request: Any) -> Any: ...
    async def rollback(self, applied: Any) -> Any: ...


async def _wcodes(connector: Any) -> set[str]:
    return {v.code for v in await check_write_connector_contract(connector)}


async def test_write_profile_passes_a_conforming_writer() -> None:
    assert await check_write_connector_contract(Writer()) == []


async def test_write_profile_requires_health() -> None:
    class NoWriterHealth(Writer):
        health = None  # type: ignore[assignment]

    assert "health_missing" in await _wcodes(NoWriterHealth())


async def test_write_profile_rejects_wrong_health_type() -> None:
    class Wrong(Writer):
        async def health(self) -> Any:
            return {"state": "healthy"}

    assert "health_type" in await _wcodes(Wrong())


async def test_write_profile_rejects_raising_health() -> None:
    class Raising(Writer):
        async def health(self) -> Any:
            raise RuntimeError("boom")

    assert "health_raised" in await _wcodes(Raising())


async def test_write_profile_rejects_a_read_connector() -> None:
    assert "write_protocol_missing" in await _wcodes(Conforming())


async def test_write_profile_rejects_sync_write_methods() -> None:
    class SyncApply(Writer):
        def apply(self, request: Any) -> Any:  # type: ignore[override]
            return None

    assert "write_protocol_missing" in await _wcodes(SyncApply())


async def test_write_profile_rejects_an_advisory_manifest() -> None:
    codes = await _wcodes(Writer(_write_manifest(advisory_override=True)))
    assert "manifest_advisory" in codes


async def test_write_profile_requires_write_actions() -> None:
    assert "write_actions_missing" in await _wcodes(Writer(_manifest()))


async def test_write_profile_rejects_a_missing_manifest() -> None:
    assert "manifest_missing" in await _wcodes(NoManifest())


async def test_read_profile_is_unchanged_for_a_writer() -> None:
    # Coverage and freshness stay read-only requirements.
    codes = await _codes(Writer())
    assert {"coverage_missing", "freshness_missing"} <= codes
