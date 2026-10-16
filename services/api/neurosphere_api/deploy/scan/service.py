"""Consented, read-only scan. Visibility is the intersection of requested, consented, readable."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from neurosphere_core.errors import ForbiddenError

from neurosphere_api.deploy.scan.graph import SCAN_QUERY, TYPE_CATEGORY, ResourceGraphReader
from neurosphere_api.deploy.scan.models import (
    ConsentRecord,
    DiscoveredResource,
    ScanRequest,
    ScanResponse,
    SubscriptionScan,
)
from neurosphere_api.deploy.scan.settings import ScanSettings

_NOT_VISIBLE_NOTE = "Not readable by the calling identity; nothing was scanned."


def _resource(row: dict[str, Any]) -> DiscoveredResource | None:
    rtype = str(row.get("type", "")).lower()
    category = TYPE_CATEGORY.get(rtype)
    sub = row.get("subscriptionId")
    if category is None or not isinstance(sub, str) or not row.get("id") or not row.get("name"):
        return None
    raw_tags = row.get("tags")
    tags = {str(k): str(v) for k, v in raw_tags.items()} if isinstance(raw_tags, dict) else {}
    return DiscoveredResource.model_validate(
        {
            "category": category,
            "type": rtype,
            "id": str(row["id"]),
            "name": str(row["name"]),
            "location": row.get("location") or None,
            "sku": row.get("sku") or None,
            "subscription_id": sub.lower(),
            "tags": tags,
        }
    )


def _check_consent(request: ScanRequest) -> ConsentRecord:
    consent = request.consent
    if consent is None or not consent.consent_id.strip() or not consent.consented_by.strip():
        raise ForbiddenError("a consent record is required to scan", reason="consent_missing")
    if set(request.subscription_ids) - set(consent.consented_subscriptions):
        raise ForbiddenError(
            "consent does not cover every requested subscription", reason="consent_not_covering"
        )
    return consent


class ScanService:
    def __init__(
        self,
        reader: ResourceGraphReader,
        settings: ScanSettings | None = None,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._reader = reader
        self._settings = settings or ScanSettings()
        self._clock = clock

    async def scan(self, request: ScanRequest) -> ScanResponse:
        consent = _check_consent(request)
        requested = list(dict.fromkeys(request.subscription_ids))
        if len(requested) > self._settings.max_subscriptions:
            raise ForbiddenError(
                "too many subscriptions requested", reason="too_many_subscriptions"
            )
        readable = await self._reader.list_readable_subscriptions()
        visible = [s for s in requested if s in readable]
        grouped: dict[str, list[DiscoveredResource]] = defaultdict(list)
        if visible:
            allowed = set(visible)
            for row in await self._reader.query(visible, SCAN_QUERY):
                found = _resource(row)
                if found is not None and found.subscription_id in allowed:
                    grouped[found.subscription_id].append(found)
        entries = [
            SubscriptionScan(subscription_id=s, status="visible", resources=grouped.get(s, []))
            if s in readable
            else SubscriptionScan(subscription_id=s, status="not_visible", note=_NOT_VISIBLE_NOTE)
            for s in requested
        ]
        return ScanResponse(
            consent_id=consent.consent_id, scanned_at=self._clock(), subscriptions=entries
        )
