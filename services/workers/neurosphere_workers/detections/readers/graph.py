"""Resource Graph reader for AI accounts (PRP-61 item 3).

Microsoft Learn, "Resources - Resources" (Azure Resource Graph REST): ``POST
{management host}/providers/Microsoft.ResourceGraph/resources?api-version=2024-04-01`` with body
``{"subscriptions": [...], "query": "...", "options": {"$top": n, "resultFormat":
"objectArray", "$skipToken": "..."}}`` answers ``{"data": [...], "$skipToken": "..."}``.
Observed 2026-11-16 (same request shape as the API deployment scan, which cannot be imported
here: it is consent-bound and workers must not import ``neurosphere_api``). NOT verified against
a live tenant (OPEN, PRP-64).

The query is the fixed constant :data:`AI_ACCOUNT_QUERY` (no string-built KQL) and only the
columns in :data:`ALLOWED_COLUMNS` are read; tag *values* are never projected, only tag keys.
The AI-account filter (``kind in~ ('OpenAI', 'AIServices')`` over
``microsoft.cognitiveservices/accounts``) is pinned against the API scan's query by a test.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, Final

import httpx
from neurosphere_core.cloud import CloudProfile
from neurosphere_core.detections import CROSS_CLOUD_REASON, AccountRead, AiAccount

from neurosphere_workers.detections.readers.common import GUID, ReadError, TokenSource, send

__all__ = [
    "AI_ACCOUNT_QUERY",
    "ALLOWED_COLUMNS",
    "ARG_API_VERSION",
    "ARG_PATH",
    "ResourceGraphAccountReader",
]

logger = logging.getLogger(__name__)

ARG_PATH: Final = "providers/Microsoft.ResourceGraph/resources"
ARG_API_VERSION: Final = "2024-04-01"
ALLOWED_COLUMNS: Final = ("id", "name", "location", "subscriptionId", "tagKeys")
AI_ACCOUNT_QUERY: Final = (
    "Resources "
    "| where type =~ 'microsoft.cognitiveservices/accounts' "
    "| where kind in~ ('OpenAI', 'AIServices') "
    "| project id, name, location, subscriptionId, tagKeys = bag_keys(tags)"
)
_BATCH: Final = 1000
_MAX_TAG_KEYS: Final = 20
_FIELD_MAX: Final = 512


class ResourceGraphAccountReader:
    """``subscriptions`` are ``(cloud, subscription_id)`` pairs; a pair of another cloud refuses."""

    def __init__(
        self,
        subscriptions: Sequence[tuple[str, str]],
        credential: TokenSource,
        profile: CloudProfile,
        *,
        client: httpx.AsyncClient,
        max_items: int = 500,
        max_pages: int = 10,
        page_size: int = 500,
        capability_unavailable: bool = False,
    ) -> None:
        self._subscriptions = tuple(subscriptions)
        self._credential = credential
        self._profile = profile
        self._client = client
        self._max_items = max_items
        self._max_pages = max_pages
        self._page_size = min(page_size, max_items)
        self._capability_unavailable = capability_unavailable

    async def read(self) -> AccountRead:
        cloud = self._profile.cloud.value
        if any(c != cloud for c, _ in self._subscriptions):
            return AccountRead(status="cross_cloud", reason=CROSS_CLOUD_REASON)
        if any(not GUID.fullmatch(s) for _, s in self._subscriptions):
            return AccountRead(status="unreadable", reason="subscription_invalid")
        if self._capability_unavailable:
            return AccountRead(status="capability_unavailable", reason="capability_unavailable")
        subs = list(dict.fromkeys(s.lower() for _, s in self._subscriptions))
        if not subs:
            return AccountRead()
        url = f"{self._profile.management_url}{ARG_PATH}?api-version={ARG_API_VERSION}"
        scope = f"{self._profile.management_url}.default"
        found: list[AiAccount] = []
        truncated = False
        try:
            for start in range(0, len(subs), _BATCH):
                batch = subs[start : start + _BATCH]
                skip: str | None = None
                pages = 0
                while not truncated:
                    if pages >= self._max_pages:
                        truncated = True
                        break
                    pages += 1
                    options: dict[str, Any] = {
                        "$top": self._page_size,
                        "resultFormat": "objectArray",
                    }
                    if skip:
                        options["$skipToken"] = skip
                    body = await send(
                        self._client,
                        self._credential,
                        scope,
                        "POST",
                        url,
                        {"subscriptions": batch, "query": AI_ACCOUNT_QUERY, "options": options},
                    )
                    data: Any = body.get("data", [])
                    if not isinstance(data, list):
                        raise ReadError("invalid_body")
                    for row in data:  # pyright: ignore[reportUnknownVariableType]
                        account = _extract(row)
                        if account is None:
                            continue
                        if len(found) >= self._max_items:
                            truncated = True
                            break
                        found.append(account)
                    token = body.get("$skipToken")
                    skip = token if isinstance(token, str) and token else None
                    if skip is None:
                        break
                if truncated:
                    break
        except ReadError as failure:
            logger.warning(
                "resource graph read unreadable",
                extra={"event": "worker.detections_arg_unreadable", "reason": failure.reason},
            )
            return AccountRead(status=failure.status, reason=failure.reason)
        return AccountRead(accounts=tuple(found), truncated=truncated)


def _extract(row: Any) -> AiAccount | None:
    if not isinstance(row, dict):
        return None
    values: dict[str, Any] = {k: row.get(k) for k in ALLOWED_COLUMNS}  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    name, rid = values["name"], values["id"]
    location, sub = values["location"], values["subscriptionId"]
    if not all(isinstance(v, str) and v for v in (name, rid, location, sub)):
        return None
    keys: Any = values["tagKeys"]
    tag_keys = (
        tuple(k[:64] for k in keys if isinstance(k, str) and k)[:_MAX_TAG_KEYS]  # pyright: ignore[reportUnknownVariableType]
        if isinstance(keys, list)
        else ()
    )
    return AiAccount(
        name=name[:_FIELD_MAX],
        resource_id=rid[:_FIELD_MAX],
        location=location[:64],
        subscription_id=sub[:64],
        tag_keys=tag_keys,
    )
