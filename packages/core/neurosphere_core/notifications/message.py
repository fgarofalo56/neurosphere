"""Closed-field notification message, built from the outbox row only.

The message holds exactly: ``event_class``, ``notification_id``, the subject ids
(``canonical_id`` and ``entity_type``), ``title``, ``domain_id``, ``severity``, ``link`` and
``timestamp``. The builder reads the stored ``NotificationDelivery`` and nothing else: no source
record, prompt, response, tool argument, query text or secret can reach it because none is ever
handed to it. The title is free text supplied by the publisher, so it passes through the
repository's redaction helpers (secret/PII shapes and credential phrasing) and a 160-character
cap before it is stored, and again here as a backstop.
"""

from __future__ import annotations

import json
import re
from typing import Final

from pydantic import BaseModel, ConfigDict

from neurosphere_core.copilot.models.redaction import redact_text as redact_pii_text
from neurosphere_core.notifications.models import NotificationDelivery
from neurosphere_core.observability.redaction import redact_text as redact_secret_text

__all__ = [
    "MAX_TITLE_LENGTH",
    "MessageSubject",
    "NotificationMessage",
    "build_message",
    "safe_title",
]

MAX_TITLE_LENGTH: Final = 160
_CONTROL: Final = re.compile(r"[\u0000-\u001f\u007f]+")
_FALLBACK_TITLE: Final = "Notification"
#: A content-bearing label ("prompt: ...") drops everything after it, not one word: a title is
#: a headline, never a place for model input, output or tool arguments.
_CONTENT_FIELD: Final = re.compile(
    r"(?is)\b(prompt|response|completion|messages?|arguments?|query|content)\b[\"']?\s*[:=].*"
)


def safe_title(text: str) -> str:
    """Redacted, control-character-free, 160-capped title (never empty)."""
    cleaned = _CONTENT_FIELD.sub(lambda m: f"{m.group(1)}: [redacted]", text)
    cleaned = redact_pii_text(redact_secret_text(cleaned))
    cleaned = _CONTROL.sub(" ", cleaned).strip()
    cleaned = cleaned[:MAX_TITLE_LENGTH].strip()
    return cleaned or _FALLBACK_TITLE


class MessageSubject(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    canonical_id: str
    entity_type: str


class NotificationMessage(BaseModel):
    """The only payload a sender transmits. ``extra="forbid"``: the field set is closed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_class: str
    notification_id: str
    subject: MessageSubject
    title: str
    domain_id: str
    severity: str
    link: str
    timestamp: str

    def as_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json")

    def to_json_bytes(self) -> bytes:
        """Canonical compact JSON (sorted keys): the bytes a sender signs and posts."""
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")


def build_message(row: NotificationDelivery) -> NotificationMessage:
    """Message for one outbox row, from the row alone."""
    return NotificationMessage(
        event_class=row.event_class.root,
        notification_id=row.notification_id.root,
        subject=MessageSubject(
            canonical_id=row.subject.canonical_id, entity_type=row.subject.entity_type
        ),
        title=safe_title(row.title),
        domain_id=row.domain_id.root,
        severity=row.severity.root,
        link=row.link,
        timestamp=row.created_at.root,
    )
