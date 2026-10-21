"""Stub notifiers only RECORD a send in the audit chain; no network, no delivery status."""

from __future__ import annotations

import ast
import contextlib
import json
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any, get_args

import pytest
from neurosphere_core import hitl as hitl_pkg
from neurosphere_core.hitl import (
    EmailNotifierStub,
    Notification,
    NotificationReceipt,
    Notifier,
    TeamsNotifierStub,
)

from .hitl_helpers import (
    CHAIN,
    CHECKER,
    CHECKER_ID,
    DOMAIN,
    SCOPE_HASH,
    T0,
    build,
    open_maker_checker,
)

_NETWORK_ROOTS = {
    "socket",
    "ssl",
    "http",
    "urllib",
    "urllib3",
    "smtplib",
    "email",
    "httpx",
    "aiohttp",
    "requests",
    "azure",
    "msgraph",
}
_PKG = Path(hitl_pkg.__file__).resolve().parent


def _notification(**overrides: object) -> Notification:
    data: dict[str, object] = {
        "notification_id": "55555555-5555-4555-8555-555555555555",
        "event": "review_escalated",
        "review_item_id": "66666666-6666-4666-8666-666666666666",
        "cloud": "commercial",
        "customer_id": "contoso",
        "domain_id": DOMAIN,
        "recipient_ref": "escalation.level-1",
        "escalation_level": 1,
        "correlation_id": "corr-notify-1",
    }
    data.update(overrides)
    return Notification.model_validate(data)


@contextlib.contextmanager
def no_network() -> Iterator[list[str]]:
    """Make socket creation and resolution raise for the block; yields the attempts seen.

    Entered inside the (async) test body: the event loop's own self-pipe socketpair is created
    before the test runs and is not network access.
    """
    attempts: list[str] = []

    def refuse(name: str) -> Any:
        def _refuse(*args: Any, **kwargs: Any) -> Any:
            attempts.append(name)
            raise AssertionError(f"network access attempted: {name}")

        return _refuse

    with pytest.MonkeyPatch.context() as patch:
        for name in ("socket", "create_connection", "getaddrinfo"):
            patch.setattr(socket, name, refuse(name))
        yield attempts


def test_hitl_package_imports_no_network_library() -> None:
    offenders: dict[str, list[str]] = {}
    for path in sorted(_PKG.rglob("*.py")):
        roots: set[str] = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                roots.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
        if roots & _NETWORK_ROOTS:
            offenders[path.name] = sorted(roots & _NETWORK_ROOTS)
    assert not offenders, offenders


def test_receipt_status_can_only_be_recorded() -> None:
    annotation = NotificationReceipt.model_fields["status"].annotation
    assert get_args(annotation) == ("recorded",)


@pytest.mark.parametrize(
    ("stub_type", "channel"), [(EmailNotifierStub, "email"), (TeamsNotifierStub, "teams")]
)
async def test_stub_records_send_to_audit_and_returns_recorded(
    stub_type: type[EmailNotifierStub | TeamsNotifierStub], channel: str
) -> None:
    harness = build()
    stub = stub_type(harness.audit, clock=lambda: T0)
    assert isinstance(stub, Notifier)
    with no_network() as attempts:
        receipt = await stub.send(_notification())
    assert attempts == []
    assert receipt.status == "recorded"
    assert receipt.channel == channel
    records = await harness.audit.read_range(CHAIN, start=0, limit=10)
    assert len(records) == 1
    record = records[0]
    assert record.audit_id.root == receipt.audit_id
    assert record.operation == f"hitl.notify.{channel}"
    assert record.outcome is not None
    assert record.outcome.verified is False  # recorded, never claimed delivered
    assert record.outcome.detail == f"notify.{channel}.review_escalated=recorded"
    # The recipient appears only inside the digest, never as a field value.
    assert "escalation.level-1" not in json.dumps(record.model_dump(mode="json"))


def test_notification_refuses_an_address_as_recipient() -> None:
    with pytest.raises(ValueError, match="recipient_ref"):
        _notification(recipient_ref="reviewer@contoso.com")


def test_network_guard_actually_trips() -> None:
    with no_network() as attempts, pytest.raises(AssertionError, match="network access"):
        socket.create_connection(("example.invalid", 443))
    assert attempts == ["create_connection"]


async def test_assignment_notifies_through_every_stub() -> None:
    harness = build(notifiers=lambda audit: [EmailNotifierStub(audit), TeamsNotifierStub(audit)])
    item = await open_maker_checker(harness)
    with no_network() as attempts:
        await harness.service.assign(
            item.item_id,
            None,
            CHECKER_ID,
            T0,
            by=CHECKER,
            scope_hash=SCOPE_HASH,
            correlation_id="corr-assign-1",
        )
    assert attempts == []
    records = await harness.audit.read_range(CHAIN, start=0, limit=50)
    sent = [r.operation for r in records if r.operation.startswith("hitl.notify.")]
    assert sent == ["hitl.notify.email", "hitl.notify.teams"]
    assert (await harness.audit.verify(CHAIN)).ok
