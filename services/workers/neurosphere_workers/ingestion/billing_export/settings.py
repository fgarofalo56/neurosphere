"""Settings for the ``billing_export`` role (``NS_BILLING_EXPORT_*`` plus ``NS_API_BASE_URL``).

Storage access is the workload's managed identity (no account key, no SAS). The ingest producer
secret is read from ``NS_BILLING_EXPORT_PRODUCER_SECRET`` (a vault reference in production) and
held as a ``SecretStr`` so it never prints in a repr or a log line.
"""

from __future__ import annotations

import re
from typing import Any, Final, Literal
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["DEFAULT_PRODUCER_ID", "DEFAULT_SOURCE_ID", "BillingExportSettings"]

DEFAULT_PRODUCER_ID: Final = "azure-billing-export"
#: The ``source_id`` stamped on every record; it must be a key of the producer's ``sources`` and
#: that source must be registered with kind ``billing`` (see ``producers.example.json``).
DEFAULT_SOURCE_ID: Final = "azure-billing-export"
_DOMAIN_ID = re.compile(r"(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:domain:[a-z0-9._/=-]+")
#: DNS-label suffix of a Commercial blob endpoint. Compared as labels, never as a substring.
_COMMERCIAL_BLOB_LABELS: Final = ("blob", "core", "windows", "net")


class BillingExportSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NS_BILLING_EXPORT_", frozen=True, extra="ignore", populate_by_name=True
    )

    #: Blob endpoint of the storage account the export lands in (``https://<acct>.blob.core...``).
    storage_account_url: str | None = None
    container: str | None = None
    #: Full blob path of the export run's ``manifest.json`` (rootFolderPath/exportName/run).
    manifest_blob: str | None = None
    #: Canonical domain id the billing records are attributed to.
    domain_id: str | None = None
    #: Cost basis of the configured export dataset. Only one basis is posted so actual and
    #: amortized spend of the same usage are never both counted.
    basis: Literal["actual", "amortized"] = "actual"
    #: Seconds between reads. Billing exports complete at most daily, so sub-hourly is refused.
    interval_seconds: float = Field(default=21600.0, ge=3600.0, le=86400.0)
    producer_id: str = Field(default=DEFAULT_PRODUCER_ID, min_length=1, max_length=128)
    source_id: str = Field(default=DEFAULT_SOURCE_ID, min_length=1, max_length=128)
    producer_secret: SecretStr | None = None
    api_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("NS_API_BASE_URL", "NS_BILLING_EXPORT_API_BASE_URL"),
    )
    #: Records per ingest request.
    batch_size: int = Field(default=100, ge=1, le=500)

    @field_validator(
        "storage_account_url",
        "container",
        "manifest_blob",
        "domain_id",
        "api_base_url",
        mode="before",
    )
    @classmethod
    def _blank(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @property
    def unconfigured(self) -> bool:
        """True when none of the export location, domain or producer secret is set.

        The role is part of ``all``: with no billing export configured it idles. Any partial
        configuration is an operator error and is refused by the factory.
        """
        return (
            self.storage_account_url is None
            and self.container is None
            and self.manifest_blob is None
            and self.domain_id is None
            and self.producer_secret is None
        )

    @property
    def domain_id_valid(self) -> bool:
        return self.domain_id is not None and _DOMAIN_ID.fullmatch(self.domain_id) is not None

    @property
    def storage_url_valid(self) -> bool:
        """An https Commercial blob endpoint: the connector is Commercial-only (G04 open)."""
        if self.storage_account_url is None:
            return False
        parts = urlsplit(self.storage_account_url)
        host = (parts.hostname or "").lower()
        labels = tuple(host.split("."))
        return (
            parts.scheme == "https"
            and len(labels) == len(_COMMERCIAL_BLOB_LABELS) + 1
            and labels[1:] == _COMMERCIAL_BLOB_LABELS
            and bool(labels[0])
        )
