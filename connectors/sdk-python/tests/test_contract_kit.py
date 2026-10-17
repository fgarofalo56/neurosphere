"""The contract kit fails broken connectors and passes conforming ones."""

from __future__ import annotations

from typing import Any

import pytest
from neurosphere_connector import BaseConnector, build_manifest, check_connector_contract
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
