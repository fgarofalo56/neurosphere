"""Azure Monitor bounded polling connector (PRP-09 item 4). See README.md for cited APIs."""

from neurosphere_connector_azure_monitor.auth import ManagedIdentityTokenProvider, TokenProvider
from neurosphere_connector_azure_monitor.connector import (
    AzureMonitorConnector,
    PollBounds,
    PollResult,
)
from neurosphere_connector_azure_monitor.endpoints import ENDPOINTS, MonitorEndpoints, endpoints_for
from neurosphere_connector_azure_monitor.queries import MonitorSource, SourceKind

__all__ = [
    "ENDPOINTS",
    "AzureMonitorConnector",
    "ManagedIdentityTokenProvider",
    "MonitorEndpoints",
    "MonitorSource",
    "PollBounds",
    "PollResult",
    "SourceKind",
    "TokenProvider",
    "endpoints_for",
]
