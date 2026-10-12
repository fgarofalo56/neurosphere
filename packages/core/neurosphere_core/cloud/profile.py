"""Frozen per-cloud endpoint tables. Hosts are profile facts, never built from user input."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator


class CloudName(StrEnum):
    COMMERCIAL = "commercial"
    GOVERNMENT = "government"


_ACCOUNT_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,48}[a-z0-9]$")

_HOST_FIELDS = (
    "login_host",
    "management_host",
    "cosmos_suffix",
    "eventhubs_suffix",
    "search_suffix",
)


def _table(cloud: CloudName) -> dict[str, str]:
    if cloud is CloudName.GOVERNMENT:
        return {
            "login_host": "login.microsoftonline.us",
            "management_host": "management.usgovcloudapi.net",
            "cosmos_suffix": ".documents.azure.us",
            "eventhubs_suffix": ".servicebus.usgovcloudapi.net",
            "search_suffix": ".search.azure.us",
        }
    return {
        "login_host": "login.microsoftonline.com",
        "management_host": "management.azure.com",
        "cosmos_suffix": ".documents.azure.com",
        "eventhubs_suffix": ".servicebus.windows.net",
        "search_suffix": ".search.windows.net",
    }


class CloudProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cloud: CloudName
    login_host: str
    management_host: str
    cosmos_suffix: str
    eventhubs_suffix: str
    search_suffix: str

    @model_validator(mode="after")
    def _hosts_belong_to_cloud(self) -> Self:
        expected = _table(self.cloud)
        for name in _HOST_FIELDS:
            if getattr(self, name) != expected[name]:
                raise ValueError(f"{name} is not in the {self.cloud.value} suffix set")
        return self

    @staticmethod
    def _check_account(name: str) -> str:
        if not _ACCOUNT_RE.fullmatch(name):
            raise ValueError("invalid account name (2-50 chars, lowercase letters, digits, '-')")
        return name

    def cosmos_endpoint(self, account: str) -> str:
        return f"https://{self._check_account(account)}{self.cosmos_suffix}/"

    def eventhubs_fqdn(self, namespace: str) -> str:
        return f"{self._check_account(namespace)}{self.eventhubs_suffix}"

    def search_endpoint(self, service: str) -> str:
        return f"https://{self._check_account(service)}{self.search_suffix}/"

    @property
    def authority_url(self) -> str:
        return f"https://{self.login_host}/"

    @property
    def management_url(self) -> str:
        return f"https://{self.management_host}/"


def profile_for(cloud: CloudName) -> CloudProfile:
    """Return the canonical frozen profile for ``cloud``."""
    return CloudProfile(cloud=cloud, **_table(cloud))
