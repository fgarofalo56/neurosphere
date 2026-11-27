"""Teams Workflows webhook sender (PRP-107 item 4).

Body shape is exactly the Adaptive Card envelope in
docs/connectors/verification/notifications-teams.md: TextBlock elements only, plain text, under
28 KB, no HMAC header (Teams does not verify one).
"""

from __future__ import annotations

import json
from typing import Any, Final

from neurosphere_contracts.notifications.v1.notification_channel import NotificationChannel

from neurosphere_core.notifications.message import NotificationMessage
from neurosphere_core.notifications.ports import SendOutcome
from neurosphere_core.notifications.senders.base import SenderBase

__all__ = ["MAX_TEAMS_BODY_BYTES", "TeamsWorkflowSender", "build_card_body"]

MAX_TEAMS_BODY_BYTES: Final = 28 * 1024


def _block(text: str, **extra: Any) -> dict[str, Any]:
    return {"type": "TextBlock", "text": text, "wrap": True, **extra}


def build_card_body(message: NotificationMessage) -> bytes:
    card = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.2",
        "body": [
            _block(message.title, weight="Bolder", size="Medium"),
            _block(f"Event: {message.event_class}"),
            _block(f"Severity: {message.severity}"),
            _block(f"Domain: {message.domain_id}"),
            _block(f"Subject: {message.subject.entity_type} {message.subject.canonical_id}"),
            _block(f"Link: {message.link}"),
            _block(f"Notification: {message.notification_id}"),
            _block(f"Time: {message.timestamp}"),
        ],
    }
    envelope = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": card,
            }
        ],
    }
    return json.dumps(envelope, separators=(",", ":")).encode("utf-8")


class TeamsWorkflowSender(SenderBase):
    async def send(
        self, channel: NotificationChannel, message: NotificationMessage, *, notification_id: str
    ) -> SendOutcome:
        body = build_card_body(message)
        if len(body) > MAX_TEAMS_BODY_BYTES:
            return self._refused("body_too_large")
        if channel.local_sink:
            if channel.local_sink_url is None:
                return self._refused("local_sink_not_permitted")
            url: str | None = channel.local_sink_url.root
        elif channel.endpoint_credential is None:
            return self._refused("endpoint_credential_missing")
        else:
            url = await self._secret(channel.endpoint_credential)
        if url is None:
            return self._unavailable()
        return await self._post(channel, url, body, {"Content-Type": "application/json"})
