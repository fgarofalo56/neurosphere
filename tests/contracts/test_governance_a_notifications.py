"""Notifications area contracts (PRP-99 item 4, acceptance criterion 9).

NotificationChannel, NotificationSubscription and NotificationDelivery. The if/then rules the
generated Pydantic models drop are pinned here against the JSON Schema itself. Properties are
asserted directly; nothing here diffs against the v1 baseline snapshot.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlsplit

import pytest
from contract_support import SCHEMA_ROOT, load_json, load_schema, schema_errors
from neurosphere_core.audit.content_guard import FORBIDDEN_KEYS
from neurosphere_core.payload.guard import is_body_field
from test_admin_no_credential_values import credential_findings

CHANNEL = "notifications/v1/notification-channel.schema.json"
SUBSCRIPTION = "notifications/v1/notification-subscription.schema.json"
DELIVERY = "notifications/v1/notification.schema.json"
ALL_SCHEMAS = (CHANNEL, SUBSCRIPTION, DELIVERY)
VALID = SCHEMA_ROOT / "notifications" / "v1" / "examples" / "valid"

# Names that would let a record carry a recipient address or a message body.
RECIPIENT_OR_BODY_NAMES = frozenset(
    {
        "recipient",
        "recipients",
        "to",
        "cc",
        "bcc",
        "address",
        "addresses",
        "email",
        "emails",
        "phone",
        "phone_number",
        "mobile",
        "upn",
        "user",
        "users",
        "body",
        "message",
        "content",
        "text",
        "html",
        "payload",
        "url",
        "webhook_url",
        "endpoint",
    }
)


def _walk(node: Any) -> Iterator[dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def _property_names(rel: str) -> set[str]:
    names: set[str] = set()
    for node in _walk(load_schema(rel)):
        props = node.get("properties")
        if isinstance(props, dict):
            names |= set(props)
    return names


def _doc(name: str) -> dict[str, Any]:
    return copy.deepcopy(load_json(VALID / name))


def _webhook() -> dict[str, Any]:
    return _doc("notification-channel.webhook-hmac.json")


def _teams() -> dict[str, Any]:
    return _doc("notification-channel.teams.json")


def _sink() -> dict[str, Any]:
    return _doc("notification-channel.local-sink.json")


def _delivery() -> dict[str, Any]:
    return _doc("notification.delivered.json")


def _subscription() -> dict[str, Any]:
    return _doc("notification-subscription.by-role.json")


def _ok(rel: str, doc: dict[str, Any]) -> bool:
    return not list(schema_errors(rel, doc))


# ------------------------------------------------------------------ examples and titles


def test_valid_examples_validate() -> None:
    assert _ok(CHANNEL, _webhook())
    assert _ok(CHANNEL, _teams())
    assert _ok(CHANNEL, _sink())
    assert _ok(SUBSCRIPTION, _subscription())
    assert _ok(DELIVERY, _delivery())


def test_titles() -> None:
    assert load_schema(CHANNEL)["title"] == "NotificationChannel"
    assert load_schema(SUBSCRIPTION)["title"] == "NotificationSubscription"
    assert load_schema(SUBSCRIPTION)["$defs"]["event_class"]["title"] == "NotificationEventClass"
    assert load_schema(DELIVERY)["title"] == "NotificationDelivery"


def test_event_classes_are_the_sixteen() -> None:
    values = load_schema(SUBSCRIPTION)["$defs"]["event_class"]["enum"]
    assert len(values) == 16
    assert "channel_delivery_failed" in values
    assert "policy_violation_opened" in values


def test_subscription_bounds_and_default() -> None:
    props = load_schema(SUBSCRIPTION)["properties"]
    assert props["event_classes"]["minItems"] == 1
    assert props["event_classes"]["maxItems"] == 16
    assert props["audience_roles"]["minItems"] == 1
    assert props["audience_roles"]["maxItems"] == 6
    assert props["min_severity"]["default"] == "medium"
    doc = _subscription()
    doc["audience_roles"] = []
    assert not _ok(SUBSCRIPTION, doc)
    doc = _subscription()
    doc["audience_roles"] = ["root"]
    assert not _ok(SUBSCRIPTION, doc)


# ------------------------------------------------------------------ criterion 9: delivery


@pytest.mark.parametrize("rel", ALL_SCHEMAS)
def test_no_recipient_or_body_property_anywhere(rel: str) -> None:
    names = _property_names(rel)
    assert not names & RECIPIENT_OR_BODY_NAMES
    assert not {n for n in names if is_body_field(n)}
    assert not {n.lower() for n in names} & FORBIDDEN_KEYS
    assert not {n for n in names if re.search(r"(recipient|address|e?mail|phone)", n)}


def test_channel_has_no_url_property_but_the_local_sink() -> None:
    names = _property_names(CHANNEL)
    assert {n for n in names if re.search(r"(url|endpoint|address)", n)} == {
        "local_sink_url",
        "endpoint_credential",
    }


@pytest.mark.parametrize("rel", ALL_SCHEMAS)
def test_every_object_is_closed(rel: str) -> None:
    for node in _walk(load_schema(rel)):
        if node.get("type") == "object" and "properties" in node:
            assert node.get("additionalProperties") is False
            assert not ({"key", "value"} <= set(node["properties"]))


def test_delivery_rejects_recipient_and_body_fields() -> None:
    for name in ("recipient", "email", "body", "address"):
        doc = _delivery()
        doc[name] = "x"
        assert not _ok(DELIVERY, doc), name


def test_title_bounds() -> None:
    doc = _delivery()
    doc["title"] = "T" * 160
    assert _ok(DELIVERY, doc)
    doc["title"] = "T" * 161
    assert not _ok(DELIVERY, doc)
    doc["title"] = ""
    assert not _ok(DELIVERY, doc)


@pytest.mark.parametrize("char", ["\n", "\t", "\x00", "\x1b", "\x7f"])
def test_title_rejects_control_characters(char: str) -> None:
    doc = _delivery()
    doc["title"] = "Policy" + char + "violation"
    assert not _ok(DELIVERY, doc)


def test_link_is_application_relative() -> None:
    doc = _delivery()
    for good in ("/", "/governance/violations/abc?tab=evidence"):
        doc["link"] = good
        assert _ok(DELIVERY, doc), good
    absolute = "https" + "://example.com/governance"
    for bad in (absolute, "governance/violations", "javascript:alert(1)", "/" + "a" * 512):
        doc["link"] = bad
        assert not _ok(DELIVERY, doc), bad


def test_delivery_other_bounds() -> None:
    doc = _delivery()
    doc["attempts"] = 21
    assert not _ok(DELIVERY, doc)
    doc = _delivery()
    doc["dedup_key"] = "a" * 64
    assert not _ok(DELIVERY, doc)
    doc = _delivery()
    doc["last_error_code"] = "Timeout!"
    assert not _ok(DELIVERY, doc)
    doc["last_error_code"] = "http_timeout"
    assert _ok(DELIVERY, doc)
    doc = _delivery()
    doc["status"] = "lost"
    assert not _ok(DELIVERY, doc)


# ------------------------------------------------------------------ criterion 9: channel


def test_endpoint_is_only_a_key_vault_secret_reference() -> None:
    doc = _webhook()
    doc["endpoint_credential"] = {
        "kind": "managed_identity",
        "managed_identity_client_id": "00000000-0000-4000-8000-000000000001",
    }
    assert not _ok(CHANNEL, doc)
    doc = _webhook()
    doc["endpoint_credential"] = "https" + "://hooks.example.com/abc"
    assert not _ok(CHANNEL, doc)
    doc = _webhook()
    doc["endpoint_credential"]["extra"] = "x"
    assert not _ok(CHANNEL, doc)


def test_channel_rejects_a_url_property() -> None:
    for name in ("url", "webhook_url", "endpoint", "address"):
        doc = _webhook()
        doc[name] = "https" + "://hooks.example.com/abc"
        assert not _ok(CHANNEL, doc), name


@pytest.mark.parametrize(
    "host",
    ["https://x", "x:443", "Hooks.Example.com", "x/path", "-x.com", "x..com", "", "a" * 254],
)
def test_allowed_host_rejects(host: str) -> None:
    doc = _webhook()
    doc["allowed_host"] = host
    assert not _ok(CHANNEL, doc)


@pytest.mark.parametrize("host", ["x", "hooks.example.com", "notify-sink", "a" * 63])
def test_allowed_host_accepts(host: str) -> None:
    doc = _webhook()
    doc["allowed_host"] = host
    assert _ok(CHANNEL, doc)


def test_local_sink_requires_url() -> None:
    doc = _sink()
    del doc["local_sink_url"]
    assert not _ok(CHANNEL, doc)
    doc["local_sink_url"] = None
    assert not _ok(CHANNEL, doc)


def test_local_sink_url_requires_local_sink() -> None:
    doc = _webhook()
    doc["local_sink_url"] = "http://127.0.0.1:8080/hook"
    assert not _ok(CHANNEL, doc)
    doc["local_sink"] = True
    assert _ok(CHANNEL, doc)


def test_endpoint_credential_null_only_with_local_sink() -> None:
    doc = _webhook()
    doc["endpoint_credential"] = None
    assert not _ok(CHANNEL, doc)
    del doc["endpoint_credential"]
    assert not _ok(CHANNEL, doc)
    assert _ok(CHANNEL, _sink())
    sink = _sink()
    sink["endpoint_credential"] = _webhook()["endpoint_credential"]
    assert _ok(CHANNEL, sink)


def test_webhook_needs_hmac_unless_local_sink() -> None:
    doc = _webhook()
    doc["hmac_credential"] = None
    assert not _ok(CHANNEL, doc)
    del doc["hmac_credential"]
    assert not _ok(CHANNEL, doc)
    # Teams and email channels do not sign; a local sink webhook is exempt.
    assert _ok(CHANNEL, _teams())
    assert _ok(CHANNEL, _sink())
    doc = _teams()
    doc["kind"] = "email"
    assert _ok(CHANNEL, doc)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8080/hook",
        "http://localhost/hook",
        "http://localhost:9000",
        "http://notify-sink/hook",
        "http://notify-sink:8080/a/b/",
    ],
)
def test_local_sink_url_accepts(url: str) -> None:
    doc = _sink()
    doc["local_sink_url"] = url
    assert _ok(CHANNEL, doc)
    assert urlsplit(url).scheme == "http"


def test_local_sink_url_rejects() -> None:
    userinfo = "http" + "://" + "u" + ":" + "p" + "@" + "localhost/hook"
    cases = [
        "https" + "://localhost/hook",
        "http://localhost/hook?x=1",
        "http://localhost/hook#frag",
        userinfo,
        "http://example.com/hook",
        "http://10.0.0.5/hook",
        "ftp://localhost/hook",
        "http://notify-sink/" + "a" * 129,
    ]
    for url in cases:
        doc = _sink()
        doc["local_sink_url"] = url
        assert not _ok(CHANNEL, doc), url


# ------------------------------------------------------------------ credential walker


# PRP-37 walker flags "key" as a name segment. dedup_key is a sha256 digest identifier (the same
# name policy-violation uses), not a credential: it is allowed only while pattern-bound to a digest.
DIGEST_PATTERN = "^sha256:[a-f0-9]{64}$"


@pytest.mark.parametrize("rel", ALL_SCHEMAS)
def test_credential_walker_finds_nothing(rel: str) -> None:
    schema = load_schema(rel)
    findings = []
    for finding in credential_findings(rel):
        if finding.endswith("/properties/dedup_key"):
            assert schema["properties"]["dedup_key"]["pattern"] == DIGEST_PATTERN
            continue
        findings.append(finding)
    assert findings == []
