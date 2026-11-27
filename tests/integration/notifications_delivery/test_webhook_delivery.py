"""Webhook delivery to a REAL local HTTP receiver through the real egress guard (PRP-107 item 4).

Deliberately not marked ``integration``: it needs no emulator, only a stdlib server on loopback,
so the default ``-m "not integration and not live"`` selection of the CI python job runs it.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest
from neurosphere_contracts.admin.v1.credential_reference import CredentialReference
from neurosphere_contracts.admin.v1.system_setting import NotificationsSetting
from neurosphere_contracts.notifications.v1.notification_channel import NotificationChannel
from neurosphere_core.notifications.egress import EgressGuard
from neurosphere_core.notifications.message import MessageSubject, NotificationMessage
from neurosphere_core.notifications.senders import WebhookSender, verify_signature
from pydantic import SecretStr

HMAC_KEY = "hm" + "ac-key-" + "q4" * 8
HMAC_REF = "https://vault-a.vault.azure.net/secrets/hmac-key"
NOW = datetime(2026, 11, 26, 12, 0, 0, tzinfo=UTC)


class Receiver:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.status = 200
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                receiver.requests.append(
                    {
                        "path": self.path,
                        "headers": {k.lower(): v for k, v in self.headers.items()},
                        "body": self.rfile.read(length),
                    }
                )
                self.send_response(receiver.status)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, format: str, *args: Any) -> None:
                return

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/hook"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> Receiver:
        self.thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


@pytest.fixture
def receiver() -> Iterator[Receiver]:
    with Receiver() as r:
        yield r


class Secrets:
    async def read(self, reference: CredentialReference) -> SecretStr:
        return SecretStr(HMAC_KEY)


def channel(url: str, *, signed: bool = True) -> NotificationChannel:
    return NotificationChannel.model_validate(
        {
            "schema_version": "1.0.0",
            "channel_id": "local-hook",
            "cloud": "commercial",
            "customer_id": "acme",
            "domain_id": "commercial:acme:core:domain:team-a",
            "display_name": "Local hook",
            "kind": "webhook",
            "allowed_host": "localhost",
            "endpoint_credential": None,
            "hmac_credential": (
                {"kind": "key_vault_secret", "secret_uri": HMAC_REF} if signed else None
            ),
            "local_sink": True,
            "local_sink_url": url,
            "enabled": True,
        }
    )


def make_sender(ns_env: str = "local") -> WebhookSender:
    return WebhookSender(
        EgressGuard(),
        Secrets(),
        setting=NotificationsSetting.model_validate({"egress_allowed_hosts": ["localhost"]}),
        deployment_cloud="commercial",
        ns_env=ns_env,
        clock=lambda: NOW,
    )


def message() -> NotificationMessage:
    return NotificationMessage(
        event_class="hitl_item_assigned",
        notification_id="n-42",
        subject=MessageSubject(
            canonical_id="commercial:acme:core:review_item:item-1", entity_type="review_item"
        ),
        title="Review item assigned",
        domain_id="commercial:acme:core:domain:team-a",
        severity="high",
        link="/review/item-1",
        timestamp="2026-11-26T12:00:00Z",
    )


async def test_receiver_gets_one_signed_post(receiver: Receiver) -> None:
    out = await make_sender().send(channel(receiver.url), message(), notification_id="n-42")
    assert out.delivered and out.status_code == 200 and out.reason_code is None
    assert len(receiver.requests) == 1
    got = receiver.requests[0]
    assert got["path"] == "/hook"
    doc = json.loads(got["body"])
    assert doc["notification_id"] == "n-42"
    assert set(doc) == {
        "event_class",
        "notification_id",
        "subject",
        "title",
        "domain_id",
        "severity",
        "link",
        "timestamp",
    }
    headers = got["headers"]
    assert headers["content-type"] == "application/json"
    assert headers["x-neurosphere-notification-id"] == "n-42"
    assert verify_signature(
        HMAC_KEY,
        headers["x-neurosphere-timestamp"],
        got["body"],
        headers["x-neurosphere-signature"],
    )
    assert not verify_signature(
        HMAC_KEY,
        headers["x-neurosphere-timestamp"],
        got["body"] + b"!",
        headers["x-neurosphere-signature"],
    )


async def test_server_error_is_retryable(receiver: Receiver) -> None:
    receiver.status = 500
    out = await make_sender().send(channel(receiver.url), message(), notification_id="n-42")
    assert out.status_code == 500 and out.retryable and not out.delivered
    assert out.reason_code == "http_status"
    assert len(receiver.requests) == 1


async def test_client_error_is_final(receiver: Receiver) -> None:
    receiver.status = 404
    out = await make_sender().send(channel(receiver.url), message(), notification_id="n-42")
    assert out.status_code == 404 and not out.retryable


async def test_unsigned_local_sink(receiver: Receiver) -> None:
    out = await make_sender().send(
        channel(receiver.url, signed=False), message(), notification_id="n-42"
    )
    assert out.delivered
    assert "x-neurosphere-signature" not in receiver.requests[0]["headers"]


async def test_not_local_env_is_refused_with_no_request(receiver: Receiver) -> None:
    out = await make_sender(ns_env="prod").send(
        channel(receiver.url), message(), notification_id="n-42"
    )
    assert out.reason_code == "local_sink_not_permitted" and not out.retryable
    assert receiver.requests == []


async def test_url_other_than_the_configured_sink_is_refused(receiver: Receiver) -> None:
    guard = EgressGuard()
    setting = NotificationsSetting.model_validate({"egress_allowed_hosts": ["localhost"]})
    response = await guard.post(
        channel(receiver.url),
        "http://127.0.0.1:1/elsewhere",
        b"{}",
        {},
        setting=setting,
        deployment_cloud="commercial",
        ns_env="local",
    )
    assert response.reason_code == "local_sink_not_permitted"
    assert receiver.requests == []
