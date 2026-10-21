"""ARM endpoints and documented api-versions for the Foundry deployment swap.

All values come from Microsoft Learn (verified 2026-10-20):

- Deployments - Create Or Update / Get, api-version ``2024-10-01`` (Azure AI Services account
  management; the how-to also lists ``2025-06-01``, this connector pins ``2024-10-01``):
  ``/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.CognitiveServices/accounts/
  {account}/deployments/{name}``.
- Models - List, api-version ``2024-10-01``:
  ``/subscriptions/{sub}/providers/Microsoft.CognitiveServices/locations/{location}/models``.
- Permissions - List For Resource, api-version ``2022-04-01`` (Microsoft.Authorization).

The Government ARM host is listed so a Government target is recognised and refused; the
capability matrix keeps ``foundry.deployment_write`` disabled there (G01), and the connector
never substitutes the Commercial host.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from neurosphere_core.cloud.profile import CloudName

__all__ = [
    "ARM_ENDPOINTS",
    "DEPLOYMENTS_API_VERSION",
    "MODELS_API_VERSION",
    "PERMISSIONS_API_VERSION",
    "AccountRef",
    "ArmEndpoints",
    "validate_name",
]

DEPLOYMENTS_API_VERSION = "2024-10-01"
MODELS_API_VERSION = "2024-10-01"
PERMISSIONS_API_VERSION = "2022-04-01"

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._()-]{0,89}$")
_GUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_LOCATION_RE = re.compile(r"^[a-z][a-z0-9]{2,39}$")


@dataclass(frozen=True)
class ArmEndpoints:
    """Frozen ARM host and token scope for one cloud."""

    host: str
    token_scope: str


ARM_ENDPOINTS: dict[CloudName, ArmEndpoints] = {
    CloudName.COMMERCIAL: ArmEndpoints(
        host="management.azure.com",
        token_scope="https://management.azure.com/.default",  # noqa: S106  # public scope
    ),
    CloudName.GOVERNMENT: ArmEndpoints(
        host="management.usgovcloudapi.net",
        token_scope="https://management.usgovcloudapi.net/.default",  # noqa: S106  # public scope
    ),
}


def validate_name(label: str, value: str) -> str:
    """Reject anything that could alter an ARM path segment."""
    if not _NAME_RE.fullmatch(value):
        raise ValueError(f"invalid {label}")
    return value


@dataclass(frozen=True)
class AccountRef:
    """One Azure AI Services account (the Foundry resource) and where it lives."""

    cloud: CloudName
    subscription_id: str
    resource_group: str
    account: str
    location: str

    def __post_init__(self) -> None:
        if not _GUID_RE.fullmatch(self.subscription_id):
            raise ValueError("invalid subscription_id")
        validate_name("resource_group", self.resource_group)
        validate_name("account", self.account)
        if not _LOCATION_RE.fullmatch(self.location):
            raise ValueError("invalid location")

    @property
    def host(self) -> str:
        return ARM_ENDPOINTS[self.cloud].host

    @property
    def token_scope(self) -> str:
        return ARM_ENDPOINTS[self.cloud].token_scope

    @property
    def _account_path(self) -> str:
        return (
            f"/subscriptions/{self.subscription_id}/resourceGroups/{self.resource_group}"
            f"/providers/Microsoft.CognitiveServices/accounts/{self.account}"
        )

    def deployment_url(self, deployment: str) -> str:
        validate_name("deployment", deployment)
        return (
            f"https://{self.host}{self._account_path}/deployments/{deployment}"
            f"?api-version={DEPLOYMENTS_API_VERSION}"
        )

    def models_url(self) -> str:
        return (
            f"https://{self.host}/subscriptions/{self.subscription_id}"
            f"/providers/Microsoft.CognitiveServices/locations/{self.location}/models"
            f"?api-version={MODELS_API_VERSION}"
        )

    def permissions_url(self) -> str:
        return (
            f"https://{self.host}/subscriptions/{self.subscription_id}"
            f"/resourcegroups/{self.resource_group}/providers/Microsoft.CognitiveServices"
            f"/accounts/{self.account}/providers/Microsoft.Authorization/permissions"
            f"?api-version={PERMISSIONS_API_VERSION}"
        )
