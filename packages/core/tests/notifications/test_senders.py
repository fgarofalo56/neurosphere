"""Notification senders: signature, Teams envelope, size cap, credential failures, kind table."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest
from neurosphere_contracts.admin.v1.credential_reference import CredentialReference
from neurosphere_contracts.admin.v1.system_setting import NotificationsSetting
from neurosphere_contracts.notifications.v1.notification_channel import NotificationChannel
from neurosphere_core.notifications.egress import EgressGuard, EgressResponse
from neurosphere_core.notifications.message import MessageSubject, NotificationMessage
from neurosphere_core.notifications.senders import (
    KIND_STATUS,
    KindNotBuildableError,
    TeamsWorkflowSender,
    WebhookSender,
    build_sender,
    kind_status,
    require_buildable,
    verify_signature,
)
from neurosphere_core.notifications.senders.teams import MAX_TEAMS_BODY_BYTES
from pydantic import SecretStr

NOW = datetime(2026, 11, 26, 12, 0, 0, tzinfo=UTC)
# Credential-shaped values are assembled at runtime so no scanner flags the source.
KEY_VALUE = "hm" + "ac-key-" + "x7" * 8
HOOK_URL = (
    "https://" + "hooks.example.com" + "/workflows/" + "tok" + "en-" + "abc123" + "?sig=" + "zz9"
)
HMAC_REF = "https://vault-a.vault.azure.net/secrets/hmac-key"
URL_REF = "https://vault-a.vault.azure.net/secrets/hook-url"


def clock() -> datetime:
    return NOW


def ref(uri: str) -> dict[str, Any]:
    return {"kind": "key_vault_secret", "secret_uri": uri}


def channel(**overrides: Any) -> NotificationChannel:
    doc: dict[str, Any] = {
        "schema_version": "1.0.0",
        "channel_id": "ops-hook",
        "cloud": "commercial",
        "customer_id": "acme",
        "domain_id": "commercial:acme:core:domain:team-a",
        "display_name": "Ops hook",
        "kind": "webhook",
        "allowed_host": "hooks.example.com",
        "endpoint_credential": ref(URL_REF),
        "hmac_credential": ref(HMAC_REF),
        "local_sink": False,
        "enabled": True,
    }
    doc.update(overrides)
    return NotificationChannel.model_validate(doc)


def message(
    title: str = "Review item assigned", link: str = "/review/item-1"
) -> NotificationMessage:
    return NotificationMessage(
        event_class="hitl_item_assigned",
        notification_id="n-1",
        subject=MessageSubject(
            canonical_id="commercial:acme:core:review_item:item-1", entity_type="review_item"
        ),
        title=title,
        domain_id="commercial:acme:core:domain:team-a",
        severity="high",
        link=link,
        timestamp="2026-11-26T12:00:00Z",
    )


class FakeSecrets:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    async def read(self, reference: CredentialReference) -> SecretStr:
        if self.fail:
            raise RuntimeError("vault said: " + HOOK_URL)
        uri = reference.secret_uri or ""
        return SecretStr(HOOK_URL if uri == URL_REF else KEY_VALUE)


class RecordingGuard(EgressGuard):
    def __init__(self, response: EgressResponse | None = None) -> None:
        super().__init__()
        self.response = response or EgressResponse(status_code=200, reason_code=None)
        self.calls: list[tuple[str, bytes, dict[str, str]]] = []

    async def post(  # type: ignore[override]
        self,
        channel: NotificationChannel,
        url: str,
        body: bytes,
        headers: Mapping[str, str],
        **_: Any,
    ) -> EgressResponse:
        self.calls.append((url, body, dict(headers)))
        return self.response


def sender(cls: type, guard: EgressGuard, secrets: FakeSecrets | None = None) -> Any:
    return cls(
        guard,
        secrets or FakeSecrets(),
        setting=NotificationsSetting.model_validate({"egress_allowed_hosts": ["example.com"]}),
        deployment_cloud="commercial",
        ns_env="prod",
        clock=clock,
    )


async def test_signature_verifies_and_detects_tampering() -> None:
    guard = RecordingGuard()
    outcome = await sender(WebhookSender, guard).send(channel(), message(), notification_id="n-1")
    assert outcome.delivered and outcome.reason_code is None
    url, body, headers = guard.calls[0]
    assert url == HOOK_URL
    assert headers["X-NeuroSphere-Notification-Id"] == "n-1"
    assert headers["Content-Type"] == "application/json"
    ts = headers["X-NeuroSphere-Timestamp"]
    assert ts == str(int(NOW.timestamp()))
    sig = headers["X-NeuroSphere-Signature"]
    assert sig.startswith("sha256=")
    assert verify_signature(KEY_VALUE, ts, body, sig)
    assert not verify_signature(KEY_VALUE, ts, body + b" ", sig)
    assert not verify_signature(KEY_VALUE, str(int(ts) + 1), body, sig)
    assert not verify_signature(KEY_VALUE + "x", ts, body, sig)
    assert json.loads(body)["notification_id"] == "n-1"


async def test_webhook_without_hmac_is_refused_unless_local_sink() -> None:
    guard = RecordingGuard()
    s = sender(WebhookSender, guard)
    out = await s.send(channel(hmac_credential=None), message(), notification_id="n-1")
    assert (out.reason_code, out.retryable, guard.calls) == ("hmac_credential_missing", False, [])
    local = channel(
        hmac_credential=None,
        endpoint_credential=None,
        local_sink=True,
        local_sink_url="http://127.0.0.1:9000/hook",
    )
    out = await s.send(local, message(), notification_id="n-1")
    assert out.delivered
    url, _, headers = guard.calls[0]
    assert url == "http://127.0.0.1:9000/hook"
    assert "X-NeuroSphere-Signature" not in headers


async def test_credential_read_failure_is_retryable_and_leaks_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    guard = RecordingGuard()
    with caplog.at_level(logging.DEBUG):
        out = await sender(WebhookSender, guard, FakeSecrets(fail=True)).send(
            channel(), message(), notification_id="n-1"
        )
    assert (out.status_code, out.reason_code, out.retryable) == (
        None,
        "credential_unavailable",
        True,
    )
    assert guard.calls == []
    assert "vault said" not in caplog.text and "token-abc123" not in repr(out)


async def test_egress_outcome_mapping() -> None:
    server_error = RecordingGuard(EgressResponse(500, "http_status"))
    out = await sender(WebhookSender, server_error).send(channel(), message(), notification_id="n")
    assert (out.status_code, out.reason_code, out.retryable) == (500, "http_status", True)
    bad = RecordingGuard(EgressResponse(400, "http_status"))
    out = await sender(WebhookSender, bad).send(channel(), message(), notification_id="n")
    assert (out.status_code, out.retryable) == (400, False)


async def test_teams_envelope_shape_and_no_hmac() -> None:
    guard = RecordingGuard()
    ch = channel(kind="teams_webhook", hmac_credential=None)
    out = await sender(TeamsWorkflowSender, guard).send(ch, message(), notification_id="n-1")
    assert out.delivered
    url, body, headers = guard.calls[0]
    assert url == HOOK_URL
    assert not any(k.startswith("X-NeuroSphere") for k in headers)
    doc = json.loads(body)
    assert set(doc) == {"type", "attachments"} and doc["type"] == "message"
    (attachment,) = doc["attachments"]
    assert attachment["contentType"] == "application/vnd.microsoft.card.adaptive"
    assert attachment["contentUrl"] is None
    card = attachment["content"]
    assert card["type"] == "AdaptiveCard" and card["version"] == "1.2"
    assert card["$schema"] == "http://adaptivecards.io/schemas/adaptive-card.json"
    assert card["body"] and all(b["type"] == "TextBlock" for b in card["body"])
    text = " ".join(b["text"] for b in card["body"])
    assert "Review item assigned" in text and "n-1" in text and "/review/item-1" in text


async def test_teams_body_over_28kb_is_refused_before_sending() -> None:
    guard = RecordingGuard()
    ch = channel(kind="teams_webhook", hmac_credential=None)
    big = message(link="/" + "a" * MAX_TEAMS_BODY_BYTES)
    out = await sender(TeamsWorkflowSender, guard).send(ch, big, notification_id="n-1")
    assert (out.reason_code, out.retryable, guard.calls) == ("body_too_large", False, [])


def test_kind_status_table() -> None:
    assert KIND_STATUS["webhook"] == ("buildable", None)
    assert KIND_STATUS["teams_webhook"] == ("degraded", "teams_workflows_commercial_and_gcc_only")
    assert KIND_STATUS["email"] == ("not_built", "email_transport_not_built")
    assert kind_status("carrier-pigeon") == ("not_built", "unknown_channel_kind")
    assert require_buildable("webhook")[0] == "buildable"
    assert require_buildable("teams_webhook")[0] == "degraded"
    with pytest.raises(KindNotBuildableError) as exc:
        require_buildable("email")
    assert exc.value.reason == "email_transport_not_built"
    with pytest.raises(KindNotBuildableError):
        build_sender(
            "email",
            EgressGuard(),
            FakeSecrets(),
            setting=NotificationsSetting.model_validate({"egress_allowed_hosts": ["example.com"]}),
            deployment_cloud="commercial",
            ns_env="prod",
            clock=clock,
        )


async def test_logs_never_carry_secret_or_url(caplog: pytest.LogCaptureFixture) -> None:
    # Real guard, real refusal path (host not on the allow-list): nothing but codes is logged.
    ch = channel(allowed_host="elsewhere.example.net")
    with caplog.at_level(logging.DEBUG):
        out = await sender(WebhookSender, EgressGuard()).send(ch, message(), notification_id="n")
    assert out.reason_code == "host_not_allowed"
    assert KEY_VALUE not in caplog.text
    for fragment in ("token-abc123", "sig=zz9", "/workflows/"):
        assert fragment not in caplog.text
        assert fragment not in repr(out)
