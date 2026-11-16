"""The ARM services a deploy apply may create (PRP-55 item 3, decision 2).

Core holds only the table (service key to provider type, api-version, name rule and minimal
create body) and the tag set. The HTTP transport and the provisioner that use it live in the
workers package (``neurosphere_workers.actions.deploy_http`` / ``deploy_arm``) because ``httpx``
calls are a worker concern.

Allowlist (decision 2, ASSUMPTION): ``storage``, ``event_hubs`` and ``monitoring`` (Log
Analytics) only, with the api-versions already pinned by ``infra/scripts/uninstall.py``. Every
other service key (``key_vault``, ``cosmos_db``, ``ai_search``, ``container_registry``,
``api_management``, ``model_endpoint``, hosting) has no entry and stays
``capability_unavailable``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final
from urllib.parse import quote

from neurosphere_core.deploy.register.models import CREATED_BY_NEUROSPHERE
from neurosphere_core.errors import InvalidSchemaError

__all__ = [
    "ARM_SERVICES",
    "CREATED_BY_TAG",
    "DEPLOYMENT_TAG",
    "PLAN_TAG",
    "RESOURCE_GROUP_API_VERSION",
    "ArmServiceType",
    "arm_resource_name",
    "arm_service",
    "creation_tags",
    "resource_group_id",
]

#: Tag every created resource carries; its value is the register's ``created_by`` marker.
CREATED_BY_TAG: Final = "neurosphere:created-by"
DEPLOYMENT_TAG: Final = "neurosphere:deployment-id"
PLAN_TAG: Final = "neurosphere:plan-id"
RESOURCE_GROUP_API_VERSION: Final = "2022-09-01"

_GUID: Final = re.compile(r"^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
_RG: Final = re.compile(r"^[\w.()-]{1,90}$")
_GENERIC_NAME_LIMIT: Final = 63


@dataclass(frozen=True, slots=True)
class ArmServiceType:
    """One allowlisted service: where it lives in ARM and the smallest safe create body."""

    service: str
    provider_type: str
    api_version: str
    name_rule: re.Pattern[str]
    prefix: str
    max_name: int
    alnum_only: bool
    body: Mapping[str, Any]

    def name_for(self, deployment_id: str) -> str:
        token = deployment_id.lower()
        if self.alnum_only:
            name = (self.prefix + re.sub(r"[^a-z0-9]", "", token))[: self.max_name]
        else:
            name = (self.prefix + re.sub(r"[^a-z0-9-]", "", token))[: self.max_name].rstrip("-")
        return name

    def check_name(self, name: str) -> None:
        if not self.name_rule.fullmatch(name):
            raise InvalidSchemaError(
                f"invalid {self.service} resource name", reason="invalid_resource_spec"
            )

    def resource_id(self, subscription_id: str, resource_group: str, name: str) -> str:
        self.check_name(name)
        return (
            f"{resource_group_id(subscription_id, resource_group)}"
            f"/providers/{self.provider_type}/{name}"
        )

    def create_body(self, region: str, tags: Mapping[str, str]) -> dict[str, Any]:
        return {**_deep_copy(self.body), "location": region, "tags": dict(tags)}


def _deep_copy(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: _deep_copy(v) for k, v in value.items()}  # pyright: ignore[reportUnknownVariableType]
    if isinstance(value, list | tuple):
        return [_deep_copy(v) for v in value]  # pyright: ignore[reportUnknownVariableType]
    return value


def _frozen(body: dict[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(body)


ARM_SERVICES: Final[Mapping[str, ArmServiceType]] = MappingProxyType(
    {
        "storage": ArmServiceType(
            service="storage",
            provider_type="Microsoft.Storage/storageAccounts",
            api_version="2023-05-01",
            name_rule=re.compile(r"^[a-z0-9]{3,24}$"),
            prefix="nsst",
            max_name=24,
            alnum_only=True,
            body=_frozen(
                {
                    "sku": {"name": "Standard_LRS"},
                    "kind": "StorageV2",
                    "properties": {
                        "minimumTlsVersion": "TLS1_2",
                        "allowBlobPublicAccess": False,
                        "supportsHttpsTrafficOnly": True,
                    },
                }
            ),
        ),
        "event_hubs": ArmServiceType(
            service="event_hubs",
            provider_type="Microsoft.EventHub/namespaces",
            api_version="2024-01-01",
            name_rule=re.compile(r"^[a-zA-Z][a-zA-Z0-9-]{4,48}[a-zA-Z0-9]$"),
            prefix="ns-eh-",
            max_name=50,
            alnum_only=False,
            body=_frozen(
                {
                    "sku": {"name": "Standard", "tier": "Standard", "capacity": 1},
                    "properties": {"minimumTlsVersion": "1.2"},
                }
            ),
        ),
        "monitoring": ArmServiceType(
            service="monitoring",
            provider_type="Microsoft.OperationalInsights/workspaces",
            api_version="2023-09-01",
            name_rule=re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9-]{2,61}[a-zA-Z0-9]$"),
            prefix="ns-log-",
            max_name=63,
            alnum_only=False,
            body=_frozen({"properties": {"sku": {"name": "PerGB2018"}, "retentionInDays": 30}}),
        ),
    }
)


def arm_service(service: str) -> ArmServiceType | None:
    """The allowlisted entry for ``service``, or ``None`` (``capability_unavailable``)."""
    return ARM_SERVICES.get(service)


def arm_resource_name(service: str, deployment_id: str) -> str:
    """Deterministic resource name of ``service`` for one deployment (fits the ARM name rule
    for allowlisted services; other services keep ``<service>-<deployment>``)."""
    entry = arm_service(service)
    if entry is not None:
        return entry.name_for(deployment_id)
    return f"{service}-{deployment_id}"[:_GENERIC_NAME_LIMIT]


def creation_tags(deployment_id: str, plan_id: str) -> dict[str, str]:
    """Tags stamped on every created resource (identifiers only, never a secret)."""
    return {
        CREATED_BY_TAG: CREATED_BY_NEUROSPHERE,
        DEPLOYMENT_TAG: deployment_id,
        PLAN_TAG: plan_id,
    }


def resource_group_id(subscription_id: str, resource_group: str) -> str:
    if not _GUID.fullmatch(subscription_id) or not _RG.fullmatch(resource_group):
        raise InvalidSchemaError(
            "a subscription id and a valid resource group are required",
            reason="invalid_resource_spec",
        )
    return f"/subscriptions/{subscription_id}/resourceGroups/{quote(resource_group)}"
