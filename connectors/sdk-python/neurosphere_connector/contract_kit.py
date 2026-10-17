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

from neurosphere_connector.health import CoverageReport, FreshnessReport, HealthReport
from neurosphere_connector.manifest import manifest_issues

__all__ = ["Violation", "check_connector_contract"]


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


async def check_connector_contract(connector: Any) -> list[Violation]:
    """Check manifest, health, rate-limit, coverage and freshness reporting."""
    out: list[Violation] = []

    manifest = getattr(connector, "manifest", None)
    if manifest is None:
        out.append(Violation("manifest_missing", "connector exposes no manifest"))
    elif not isinstance(manifest, ConnectorManifest):
        out.append(Violation("manifest_type", "manifest must be a ConnectorManifest"))
    else:
        for issue in manifest_issues(manifest.model_dump(mode="json")):
            out.append(Violation("manifest_invalid", f"{issue.pointer or '/'}: {issue.detail}"))

    health, bad = await _call(connector, "health")
    if bad:
        out.append(bad)
    elif not isinstance(health, HealthReport):
        out.append(Violation("health_type", "health() must return HealthReport"))
    elif health.rate_limit.limited and health.state.value != "rate_limited":
        out.append(Violation("health_rate_limit", "limited but state is not rate_limited"))

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
    elif freshness.lag_ms is None and freshness.watermark is not None:
        pass  # watermark without lag is allowed; lag is simply unknown
    elif freshness.lag_ms == 0 and freshness.watermark is None and freshness.observed_at is None:
        out.append(Violation("freshness_unknown_as_zero", "lag_ms=0 with no observation"))

    if isinstance(manifest, ConnectorManifest):
        try:
            json.dumps(manifest.model_dump(mode="json"))
        except (TypeError, ValueError):
            out.append(Violation("manifest_not_serializable", "manifest is not JSON-serializable"))
    return out
