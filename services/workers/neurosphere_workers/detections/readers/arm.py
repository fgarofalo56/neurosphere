"""ARM deployment lister: content-filter policy names per Foundry deployment (PRP-61 item 3).

Microsoft Learn, "Deployments - List" (Azure AI Services account management): ``GET
/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.CognitiveServices/accounts/{account}
/deployments?api-version=2024-10-01`` returns ``value[]`` deployments with ``name`` and
``properties.raiPolicyName`` (the content-filter policy; absent when none is attached). The same
property is preserved by the Foundry connector's PUT (``connectors/reference/foundry-actions``
``logic.py``). Observed 2026-11-16 from the connector's own documented contract; NOT verified
against a live account (OPEN, PRP-64).

Only ``name`` and ``raiPolicyName`` are copied out; every other member of the payload (model,
sku, tags, rate limits, anything else) is dropped here.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, Final

import httpx
from neurosphere_connector_foundry_actions.endpoints import (
    DEPLOYMENTS_API_VERSION,
    AccountRef,
    validate_name,
)
from neurosphere_core.cloud import CloudProfile
from neurosphere_core.detections import (
    CROSS_CLOUD_REASON,
    DeploymentConfig,
    DeploymentConfigRead,
)

from neurosphere_workers.detections.readers.common import ReadError, TokenSource, send

__all__ = ["ArmDeploymentReader"]

logger = logging.getLogger(__name__)

_NAME_MAX: Final = 128


class ArmDeploymentReader:
    def __init__(
        self,
        accounts: Sequence[AccountRef],
        credential: TokenSource,
        profile: CloudProfile,
        *,
        client: httpx.AsyncClient,
        max_items: int = 500,
        max_pages: int = 10,
        capability_unavailable: bool = False,
    ) -> None:
        self._accounts = tuple(accounts)
        self._credential = credential
        self._profile = profile
        self._client = client
        self._max_items = max_items
        self._max_pages = max_pages
        self._capability_unavailable = capability_unavailable

    def _url(self, ref: AccountRef) -> str:
        validate_name("account", ref.account)
        return (
            f"https://{self._profile.management_host}/subscriptions/{ref.subscription_id}"
            f"/resourceGroups/{ref.resource_group}/providers/Microsoft.CognitiveServices"
            f"/accounts/{ref.account}/deployments?api-version={DEPLOYMENTS_API_VERSION}"
        )

    async def read(self) -> list[DeploymentConfigRead]:
        return [await self._one(ref) for ref in self._accounts]

    async def _one(self, ref: AccountRef) -> DeploymentConfigRead:
        if ref.cloud.value != self._profile.cloud.value:
            # Never route another cloud's account through this cloud's ARM host.
            return DeploymentConfigRead(
                account=ref.account, status="cross_cloud", reason=CROSS_CLOUD_REASON
            )
        if self._capability_unavailable:
            return DeploymentConfigRead(
                account=ref.account,
                status="capability_unavailable",
                reason="capability_unavailable",
            )
        host_prefix = f"https://{self._profile.management_host}/"
        scope = f"{self._profile.management_url}.default"
        url: str | None = self._url(ref)
        found: list[DeploymentConfig] = []
        truncated = False
        try:
            pages = 0
            while url is not None and not truncated:
                if pages >= self._max_pages:
                    truncated = True  # more pages exist than the budget allows
                    break
                pages += 1
                body = await send(self._client, self._credential, scope, "GET", url)
                value: Any = body.get("value", [])
                if not isinstance(value, list):
                    raise ReadError("invalid_body")
                for row in value:  # pyright: ignore[reportUnknownVariableType]
                    item = _extract(ref.account, row)
                    if item is None:
                        continue
                    if len(found) >= self._max_items:
                        truncated = True
                        break
                    found.append(item)
                link = body.get("nextLink")
                # Only follow a continuation that stays on this cloud's management host.
                url = link if isinstance(link, str) and link.startswith(host_prefix) else None
        except ReadError as failure:
            logger.warning(
                "deployment list unreadable",
                extra={"event": "worker.detections_arm_unreadable", "reason": failure.reason},
            )
            return DeploymentConfigRead(
                account=ref.account, status=failure.status, reason=failure.reason
            )
        return DeploymentConfigRead(
            account=ref.account, deployments=tuple(found), truncated=truncated
        )


def _extract(account: str, row: Any) -> DeploymentConfig | None:
    if not isinstance(row, dict):
        return None
    name = row.get("name")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    if not isinstance(name, str) or not name or len(name) > _NAME_MAX:
        return None
    props = row.get("properties")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    policy: Any = props.get("raiPolicyName") if isinstance(props, dict) else None  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    rai = policy[:_NAME_MAX] if isinstance(policy, str) and policy.strip() else None
    return DeploymentConfig(account=account, name=name, rai_policy=rai)
