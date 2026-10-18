"""Capability-gated adapter factory (PRP-11 clarification 4, 5; ADR-0007).

``create_adapter`` resolves the requested backend through the capability matrix
(``validate_profile``) BEFORE importing anything vendor-specific. A disabled backend raises
``CapabilityUnavailableError`` carrying the matrix reason; nothing is routed to another cloud.
Vendor factories are named by lazy module path strings, so ``base`` never imports a vendor
package and adding a vendor adds nothing here.

Vendor contract (Items 2-4): the module ``neurosphere_core.analytics.<name>`` exposes::

    def create_adapter(
        *, cloud: str, region: str, config: Mapping[str, Any], executor: SqlExecutor | None
    ) -> AnalyticsAdapter

``executor`` is a test/stub injection point (None = build the real client from ``config``,
which must validate that the endpoint host matches ``cloud``). The returned adapter's
``cloud`` must equal the requested cloud. ``fixture`` is not matrix-gated: it is sandbox-only.
"""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from neurosphere_core.analytics.base.protocols import AnalyticsAdapter
from neurosphere_core.capabilities.validate import (
    CapabilityResult,
    DeploymentProfile,
    validate_profile,
)
from neurosphere_core.errors import CapabilityUnavailableError, InvalidSchemaError

VENDOR_FACTORIES: Final[dict[str, str]] = {
    "fabric": "neurosphere_core.analytics.fabric:create_adapter",
    "synapse": "neurosphere_core.analytics.synapse:create_adapter",
    "databricks": "neurosphere_core.analytics.databricks:create_adapter",
}
FIXTURE_FACTORY: Final = "neurosphere_core.analytics.fixture:create_adapter"
BACKENDS: Final = tuple(VENDOR_FACTORIES)


class BackendStatus(BaseModel):
    """One backend for a cloud/region, for a UI that shows disabled options with a reason."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    status: Literal["supported", "disabled"]
    reason: str | None = None
    reason_code: str | None = None
    row_id: str | None = None
    warnings: tuple[str, ...] = ()


def _capability(name: str, cloud: str, region: str) -> CapabilityResult:
    try:
        profile = DeploymentProfile.model_validate(
            # hosting is irrelevant to the analytics row; only the analytics result is read.
            {"cloud": cloud, "regions": (region,), "hosting": "aks", "analytics": name}
        )
    except ValidationError:
        raise InvalidSchemaError(
            "cloud, region or backend name is invalid", reason="analytics_profile"
        ) from None
    for result in validate_profile(profile).results:
        if result.kind == "analytics":
            return result
    raise AssertionError("validate_profile returned no analytics result")  # pragma: no cover


def list_backends(*, cloud: str, region: str) -> tuple[BackendStatus, ...]:
    """All three vendor backends with supported/disabled status and the matrix reason."""
    out: list[BackendStatus] = []
    for name in BACKENDS:
        result = _capability(name, cloud, region)
        out.append(
            BackendStatus(
                name=name,
                status=result.status,
                reason=result.reason,
                reason_code=result.reason_code,
                row_id=result.row_id,
                warnings=result.warnings,
            )
        )
    return tuple(out)


def _load(path: str) -> Any:
    module_name, _, attr = path.partition(":")
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        parent = module_name.rsplit(".", 1)[0]
        if exc.name in (module_name, parent):
            raise CapabilityUnavailableError(
                "adapter_not_installed", f"adapter module {module_name} is not installed"
            ) from None
        raise
    return getattr(module, attr)


def create_adapter(
    name: str,
    *,
    cloud: str,
    region: str,
    config: Mapping[str, Any] | None = None,
    executor: object | None = None,
    sandbox: bool = False,
) -> AnalyticsAdapter:
    """Build the named adapter if, and only if, the matrix supports it for ``cloud``/``region``.

    ``name`` is ``fabric``, ``synapse``, ``databricks`` or ``fixture`` (sandbox only)."""
    if name == "fixture":
        factory = _load(FIXTURE_FACTORY)
        return factory(
            cloud=cloud, region=region, config=dict(config or {}), executor=None, sandbox=sandbox
        )
    if name not in VENDOR_FACTORIES:
        raise InvalidSchemaError(f"unknown analytics backend {name!r}", reason="analytics_backend")
    capability = _capability(name, cloud, region)
    if capability.status != "supported":
        raise CapabilityUnavailableError(
            capability.reason_code or "not_verified",
            capability.reason or f"{name} is not available in {cloud} {region}",
        )
    factory = _load(VENDOR_FACTORIES[name])
    adapter: AnalyticsAdapter = factory(
        cloud=cloud, region=region, config=dict(config or {}), executor=executor
    )
    if adapter.cloud != cloud:  # defence in depth: never serve one cloud from another
        raise CapabilityUnavailableError(
            "cloud_mismatch", f"adapter cloud {adapter.cloud} differs from requested {cloud}"
        )
    return adapter
