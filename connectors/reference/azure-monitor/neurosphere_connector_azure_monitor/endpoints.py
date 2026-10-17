"""Per-cloud Azure Monitor query hosts and token scopes (the core cloud profile has none).

Commercial values are taken from Microsoft Learn (see the package README for URLs and the date
observed). Azure Government:

* Log Analytics: ``api.loganalytics.us`` is listed on the Azure Government endpoint table; the
  token scope is the same pattern as Commercial and is UNVERIFIED.
* Application Insights query API (``api.applicationinsights.io``): no Government host was found
  in the documentation, so it is disabled (``app_insights_base`` is None), not guessed.

Government is configuration only: nothing here is live-tested, and a Government deployment must
opt in with ``allow_unverified_government=True``. Government never falls back to Commercial.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from neurosphere_core.cloud.profile import CloudName
from neurosphere_core.errors import CapabilityUnavailableError

__all__ = ["ENDPOINTS", "MonitorEndpoints", "endpoints_for"]


@dataclass(frozen=True)
class MonitorEndpoints:
    cloud: CloudName
    log_analytics_base: str
    log_analytics_scope: str
    app_insights_base: str | None
    app_insights_scope: str | None
    verified: bool


ENDPOINTS: Final = MappingProxyType(
    {
        CloudName.COMMERCIAL: MonitorEndpoints(
            cloud=CloudName.COMMERCIAL,
            log_analytics_base="https://api.loganalytics.azure.com",
            log_analytics_scope="https://api.loganalytics.io/.default",
            app_insights_base="https://api.applicationinsights.io",
            app_insights_scope="https://api.applicationinsights.io/.default",
            verified=True,
        ),
        CloudName.GOVERNMENT: MonitorEndpoints(
            cloud=CloudName.GOVERNMENT,
            log_analytics_base="https://api.loganalytics.us",
            log_analytics_scope="https://api.loganalytics.us/.default",
            app_insights_base=None,
            app_insights_scope=None,
            verified=False,
        ),
    }
)


def endpoints_for(
    cloud: CloudName, *, allow_unverified_government: bool = False
) -> MonitorEndpoints:
    """Return the endpoints for exactly ``cloud``; unverified clouds need an explicit opt-in."""
    endpoints = ENDPOINTS[cloud]
    if not endpoints.verified and not allow_unverified_government:
        raise CapabilityUnavailableError(
            "azure_monitor_government_unverified",
            "Azure Monitor query hosts for this cloud are unverified; explicit opt-in required",
        )
    return endpoints
