"""Importable pytest suite for the connector contract test kit.

Subclass and override the ``connector`` fixture; pytest then collects the inherited tests::

    class TestMyConnector(ConnectorContractSuite):
        @pytest.fixture
        def connector(self):
            return MyConnector(...)

There is deliberately no auto-loaded pytest plugin (``pytest_plugins`` is not allowed in
non-root conftest files). For ad-hoc use call ``check_connector_contract`` directly.
"""

from __future__ import annotations

from typing import Any

import pytest

from neurosphere_connector.contract_kit import Violation, check_connector_contract

__all__ = ["ConnectorContractSuite", "Violation", "check_connector_contract"]


class ConnectorContractSuite:
    """Contract checks every connector must pass. Not collected itself (no ``Test`` prefix)."""

    @pytest.fixture
    def connector(self) -> Any:
        raise NotImplementedError("override the `connector` fixture in your subclass")

    async def _codes(self, connector: Any, prefix: str) -> list[str]:
        return [
            v.code for v in await check_connector_contract(connector) if v.code.startswith(prefix)
        ]

    async def test_contract_has_no_violations(self, connector: Any) -> None:
        violations = await check_connector_contract(connector)
        assert violations == [], [f"{v.code}: {v.message}" for v in violations]

    async def test_manifest_valid(self, connector: Any) -> None:
        assert await self._codes(connector, "manifest") == []

    async def test_health_reported(self, connector: Any) -> None:
        assert await self._codes(connector, "health") == []

    async def test_coverage_reported(self, connector: Any) -> None:
        assert await self._codes(connector, "coverage") == []

    async def test_freshness_reported(self, connector: Any) -> None:
        assert await self._codes(connector, "freshness") == []
