"""Contract test kit core: ``check_connector_contract`` returns violations, raises nothing.

Duck-typed on purpose: a connector that lacks ``health`` or ``coverage`` entirely must be
reported as a violation, not crash the checker. Run it directly or through the pytest suite in
``neurosphere_connector.testing``. It makes no network calls.
"""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from typing import Any

from neurosphere_contracts.connectors.v1.connector_manifest import ConnectorManifest
from neurosphere_core.errors import CapabilityUnavailableError

from neurosphere_connector.health import CoverageReport, FreshnessReport, HealthReport
from neurosphere_connector.manifest import manifest_issues
from neurosphere_connector.write.write_registry import check_capable

__all__ = ["Violation", "check_connector_contract", "check_write_connector_contract"]


@dataclass(frozen=True)
class Violation:
    """One contract failure. ``code`` is stable; ``message`` never contains secret values."""

    code: str
    message: str


async def _call(connector: Any, method: str) -> tuple[Any, Violation | None]:
    fn = getattr(connector, method, None)
    if not callable(fn):
        return None, Violation(f"{method}_missing", f"connector has no async {method}()")
    try:
        result = fn()
        if inspect.isawaitable(result):
            result = await result
    except Exception as exc:
        return None, Violation(f"{method}_raised", f"{method}() raised {type(exc).__name__}")
    return result, None


def _check_manifest(manifest: Any) -> list[Violation]:
    if manifest is None:
        return [Violation("manifest_missing", "connector exposes no manifest")]
    if not isinstance(manifest, ConnectorManifest):
        return [Violation("manifest_type", "manifest must be a ConnectorManifest")]
    return [
        Violation("manifest_invalid", f"{issue.pointer or '/'}: {issue.detail}")
        for issue in manifest_issues(manifest.model_dump(mode="json"))
    ]


async def _check_health(connector: Any) -> list[Violation]:
    health, bad = await _call(connector, "health")
    if bad:
        return [bad]
    if not isinstance(health, HealthReport):
        return [Violation("health_type", "health() must return HealthReport")]
    if health.rate_limit.limited and health.state.value != "rate_limited":
        return [Violation("health_rate_limit", "limited but state is not rate_limited")]
    return []


def _check_serializable(manifest: Any) -> list[Violation]:
    if not isinstance(manifest, ConnectorManifest):
        return []
    try:
        json.dumps(manifest.model_dump(mode="json"))
    except (TypeError, ValueError):
        return [Violation("manifest_not_serializable", "manifest is not JSON-serializable")]
    return []


# Reasons raised by the write registry's capability check -> kit violation codes.
_WRITE_REASONS = {
    "write_protocol_not_implemented": "write_protocol_missing",
    "write_support_absent": "write_actions_missing",
    "connector_advisory": "manifest_advisory",
}


def _check_write_shape(connector: Any) -> list[Violation]:
    """Reuse the write registry's capability check; map its refusal to a kit violation."""
    try:
        check_capable(connector)
    except CapabilityUnavailableError as exc:
        code = _WRITE_REASONS.get(exc.reason or "", "write_protocol_missing")
        return [Violation(code, str(exc.detail))]
    except AttributeError as exc:  # a member read outside check_capable's own guard
        return [
            Violation("write_protocol_missing", f"connector lacks WriteConnector member {exc.name}")
        ]
    return []


async def check_connector_contract(connector: Any) -> list[Violation]:
    """Check manifest, health, rate-limit, coverage and freshness reporting (read profile)."""
    manifest = getattr(connector, "manifest", None)
    out = _check_manifest(manifest)
    out.extend(await _check_health(connector))

    coverage, bad = await _call(connector, "coverage")
    if bad:
        out.append(bad)
    elif not isinstance(coverage, CoverageReport):
        out.append(Violation("coverage_type", "coverage() must return CoverageReport"))

    freshness, bad = await _call(connector, "freshness")
    if bad:
        out.append(bad)
    elif not isinstance(freshness, FreshnessReport):
        out.append(Violation("freshness_type", "freshness() must return FreshnessReport"))
    elif freshness.lag_ms == 0 and freshness.watermark is None and freshness.observed_at is None:
        out.append(Violation("freshness_unknown_as_zero", "lag_ms=0 with no observation"))

    out.extend(_check_serializable(manifest))
    return out


async def check_write_connector_contract(connector: Any) -> list[Violation]:
    """Write profile: valid non-advisory manifest with write actions, the ``WriteConnector``
    protocol (as the write registry checks it) and a non-raising ``health()``.

    Coverage and freshness are read-only requirements and are not checked here.
    """
    manifest = getattr(connector, "manifest", None)
    out = _check_manifest(manifest)
    out.extend(_check_write_shape(connector))
    out.extend(await _check_health(connector))
    out.extend(_check_serializable(manifest))
    return out
