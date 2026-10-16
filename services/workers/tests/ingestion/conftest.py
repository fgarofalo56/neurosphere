"""Fixtures backed by a small deterministic sandbox bundle with no injected defects."""

from __future__ import annotations

import pytest

from .support import Doc, Harness, rich_telemetry, sandbox_bundle


@pytest.fixture(scope="session")
def sandbox_telemetry() -> list[Doc]:
    return sandbox_bundle()[0]


@pytest.fixture(scope="session")
def sandbox_cost() -> list[Doc]:
    return sandbox_bundle()[1]


@pytest.fixture
def template() -> Doc:
    """A valid telemetry doc with many optional fields filled in."""
    return rich_telemetry()


@pytest.fixture
def harness() -> Harness:
    return Harness()
