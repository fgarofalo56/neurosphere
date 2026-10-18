"""Sandbox-only in-process analytics adapter over deterministic synthetic data (PRP-11)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from neurosphere_core.analytics.base.models import Cloud
from neurosphere_core.analytics.fixture.adapter import FixtureAnalytics
from neurosphere_core.analytics.fixture.data import DEFAULT_SIZE, build_dataset, domain_id


def create_adapter(
    *,
    cloud: str,
    region: str,
    config: Mapping[str, Any] | None = None,
    executor: object | None = None,
    sandbox: bool = False,
) -> FixtureAnalytics:
    """Registry entry point (``neurosphere_core.analytics.fixture:create_adapter``).

    ``region`` is accepted for signature parity and unused. ``config['size']`` sets the
    dataset size. Refused unless ``sandbox=True`` or ``NS_ENV=local``."""
    cfg = config or {}
    typed = cast(Cloud, cloud)
    return FixtureAnalytics(
        build_dataset(typed, int(cfg.get("size", DEFAULT_SIZE))), cloud=typed, sandbox=sandbox
    )


__all__ = ["FixtureAnalytics", "build_dataset", "create_adapter", "domain_id"]
