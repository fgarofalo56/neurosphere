"""Settings for the ``detections`` role (``NS_WORKER_DETECT_*``, PRP-61).

No secret settings: ARM and Resource Graph calls authenticate with the workload's managed
identity. Every list is operator-declared; there is no built-in claim about which content-filter
policy or policy fragment is adequate (clarification 2).

List formats (comma separated):

- ``FOUNDRY_ACCOUNTS``: ``[cloud:]subscription_id/resource_group/account/location``
- ``SUBSCRIPTIONS``: ``[cloud:]subscription_id``
- ``ACCEPTABLE_RAI_POLICIES`` and ``REQUIRED_APIM_FRAGMENTS``: plain names
"""

from __future__ import annotations

import re
from typing import Any, Final

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["DetectionSettings", "SubscriptionRef"]

#: ``(cloud, subscription_id)``; the cloud defaults to the deployment's own.
SubscriptionRef = tuple[str | None, str]

_DOMAIN_ID: Final = re.compile(
    r"(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:domain:[a-z0-9._/=-]+"
)
_POLICY_NAME: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._ ()-]{0,127}")
_FRAGMENT_NAME: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}")
_CLOUDS: Final = ("commercial", "government")
_MAX_LIST: Final = 50


def _split(raw: str | None) -> tuple[str, ...]:
    return tuple(dict.fromkeys(p.strip() for p in (raw or "").split(",") if p.strip()))


def _cloud_prefix(item: str) -> tuple[str | None, str]:
    head, sep, rest = item.partition(":")
    if sep and head.lower() in _CLOUDS:
        return head.lower(), rest
    return None, item


class DetectionSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NS_WORKER_DETECT_", frozen=True, extra="ignore", populate_by_name=True
    )

    enabled: bool = False
    #: Domain the findings are attributed to when the subject has no catalog domain.
    domain_id: str | None = None
    interval_seconds: float = Field(default=3600.0, ge=60.0, le=86400.0)
    foundry_accounts: str | None = None
    acceptable_rai_policies: str | None = None
    required_apim_fragments: str | None = None
    subscriptions: str | None = None
    #: Per-list cap on deployments, accounts and gateways per tick.
    max_items: int = Field(default=500, ge=1, le=5000)

    @field_validator(
        "domain_id",
        "foundry_accounts",
        "acceptable_rai_policies",
        "required_apim_fragments",
        "subscriptions",
        mode="before",
    )
    @classmethod
    def _blank(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @property
    def unconfigured(self) -> bool:
        """True when nothing is enabled: the role idles."""
        return not self.enabled

    @property
    def domain_id_valid(self) -> bool:
        return self.domain_id is not None and _DOMAIN_ID.fullmatch(self.domain_id) is not None

    def account_entries(self) -> tuple[tuple[str | None, str], ...]:
        """``(cloud, "sub/rg/account/location")`` entries, cloud ``None`` = deployment's own."""
        return tuple(_cloud_prefix(i) for i in _split(self.foundry_accounts))

    def subscription_refs(self) -> tuple[SubscriptionRef, ...]:
        return tuple(_cloud_prefix(i) for i in _split(self.subscriptions))

    def acceptable_policies(self) -> tuple[str, ...]:
        """Acceptable content-filter policy names; ``ValueError`` on a malformed entry."""
        names = _split(self.acceptable_rai_policies)
        if len(names) > _MAX_LIST or any(not _POLICY_NAME.fullmatch(n) for n in names):
            raise ValueError("invalid policy names")
        return names

    def required_fragments(self) -> tuple[str, ...]:
        """Required APIM policy-fragment names; ``ValueError`` on a malformed entry."""
        names = _split(self.required_apim_fragments)
        if len(names) > _MAX_LIST or any(not _FRAGMENT_NAME.fullmatch(n) for n in names):
            raise ValueError("invalid fragment names")
        return names
