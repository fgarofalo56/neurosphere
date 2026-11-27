"""Generic signed webhook sender (PRP-107 item 4).

Headers: ``X-NeuroSphere-Notification-Id``, ``X-NeuroSphere-Timestamp`` (unix seconds) and
``X-NeuroSphere-Signature: sha256=<hex>`` where the digest is HMAC-SHA256 over
``timestamp + "." + body`` keyed with the ``hmac_credential`` secret. A receiver recomputes it
with :func:`verify_signature` (reject a stale timestamp to stop replays).
"""

from __future__ import annotations

import hashlib
import hmac

from neurosphere_contracts.notifications.v1.notification_channel import NotificationChannel

from neurosphere_core.notifications.message import NotificationMessage
from neurosphere_core.notifications.ports import SendOutcome
from neurosphere_core.notifications.senders.base import SenderBase

__all__ = ["WebhookSender", "sign", "verify_signature"]

SIGNATURE_PREFIX = "sha256="


def sign(secret: str, timestamp: str, body: bytes) -> str:
    mac = hmac.new(secret.encode("utf-8"), timestamp.encode("ascii") + b"." + body, hashlib.sha256)
    return SIGNATURE_PREFIX + mac.hexdigest()


def verify_signature(secret: str, timestamp: str, body: bytes, header: str) -> bool:
    """Constant-time check of an ``X-NeuroSphere-Signature`` header value."""
    return hmac.compare_digest(sign(secret, timestamp, body), header)


class WebhookSender(SenderBase):
    async def send(
        self, channel: NotificationChannel, message: NotificationMessage, *, notification_id: str
    ) -> SendOutcome:
        local = bool(channel.local_sink)
        if local:
            if channel.local_sink_url is None:
                return self._refused("local_sink_not_permitted")
            url: str | None = channel.local_sink_url.root
        else:
            if channel.hmac_credential is None:
                return self._refused("hmac_credential_missing")
            if channel.endpoint_credential is None:
                return self._refused("endpoint_credential_missing")
            url = await self._secret(channel.endpoint_credential)
        key: str | None = None
        if channel.hmac_credential is not None:
            key = await self._secret(channel.hmac_credential)
            if key is None:
                return self._unavailable()
        if url is None:
            return self._unavailable()
        body = message.to_json_bytes()
        timestamp = str(int(self._clock().timestamp()))
        headers = {
            "Content-Type": "application/json",
            "X-NeuroSphere-Notification-Id": notification_id,
            "X-NeuroSphere-Timestamp": timestamp,
        }
        if key is not None:
            headers["X-NeuroSphere-Signature"] = sign(key, timestamp, body)
        return await self._post(channel, url, body, headers)
