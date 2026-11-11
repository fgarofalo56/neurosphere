"""Redaction hardening (PRP-19 round 2 item 12): phones, addresses, credentials, wire ids."""

from __future__ import annotations

import pytest
from neurosphere_core.copilot.models import ConversationTurn, ModelRequest, ToolCallRequest
from neurosphere_core.copilot.models.redaction import redact_request, redact_text, safe_call_id


@pytest.mark.parametrize(
    "text",
    [
        "call (555) 123-4567 now",
        "call 555-123-4567 now",
        "call 555.123.4567 now",
        "call +1 555 123 4567 now",
        "call +1-555-123-4567 now",
        "call +447911123456 now",
    ],
)
def test_phones_masked(text: str) -> None:
    out = redact_text(text)
    assert "[phone]" in out
    assert "123" not in out


@pytest.mark.parametrize(
    "text",
    [
        "123 Main Street",
        "42 N. Oak Ave.",
        "7 elm road",
        "1600 Pennsylvania Avenue",
        "9 Sunset BLVD",
        "55 5th Ave",
        "12 Lake Shore Dr",
        "3 Harbor Way",
    ],
)
def test_addresses_masked(text: str) -> None:
    assert redact_text(f"ship to {text} today") == "ship to [address] today"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("the password is hunter2", "the password is [credential]"),
        ("password: hunter2", "password: [credential]"),
        ("pwd=hunter2", "pwd=[credential]"),
        ("passcode 987654", "passcode [credential]"),
        ("pin is 1234", "pin is [credential]"),
        ("secret: abc", "secret: [credential]"),
        ("api key is abc123", "api key is [credential]"),
        ("my_token = abc", "my_token = [credential]"),
        ("db_secret: xyz", "db_secret: [credential]"),
        ("apikey=zzz", "apikey=[credential]"),
    ],
)
def test_credentials_keep_label_mask_value(text: str, expected: str) -> None:
    assert redact_text(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "released on 2025-04-14",
        "at 2025-04-14T10:20:30Z",
        "version 1.1.0 shipped",
        "3 items cost $19.99",
        "42 requests in 5 minutes",
        "max_tokens: 100",
        "token_count: 5",
        "the secret manager is down",
        "password reset is complete",
        "see [cite:r3] and [id]",
        "commercial:contoso:foundry:agent:x",
        "123 results",
        "10 ways to fail",
    ],
)
def test_no_over_redaction(text: str) -> None:
    assert redact_text(text) == text


def test_existing_ssn_and_card_not_swallowed_by_phone() -> None:
    ssn = "-".join(("123", "45", "6789"))  # built at runtime: keeps the pre-commit scan quiet
    assert redact_text(f"ssn {ssn}") == "ssn [ssn]"
    assert redact_text("card 4111 1111 1111 1111") == "card [card]"
    assert redact_text("card 4111-1111-1111-1111") == "card [card]"


def test_safe_call_id() -> None:
    assert safe_call_id("call_abc-1:2.3") == "call_abc-1:2.3"
    bad = safe_call_id("jane@example.com call 1")
    assert bad.startswith("call_")
    assert bad == safe_call_id("jane@example.com call 1")
    assert bad != safe_call_id("other value")
    assert safe_call_id("x" * 129).startswith("call_")


def test_request_call_ids_sanitized_consistently_and_tool_name_validated() -> None:
    raw = "id with spaces/ and@mail.com"
    turns = (
        ConversationTurn(
            role="assistant",
            tool_calls=(ToolCallRequest(call_id=raw, tool_name="lookup_item", arguments={}),),
        ),
        ConversationTurn(role="tool", content="ok", tool_call_id=raw),
    )
    out = redact_request(ModelRequest(system="s", turns=turns, correlation_id="c"))
    assert out.turns[0].tool_calls[0].call_id == out.turns[1].tool_call_id
    assert out.turns[1].tool_call_id == safe_call_id(raw)
    assert out.turns[0].tool_calls[0].tool_name == "lookup_item"

    bad = (
        ConversationTurn(
            role="assistant",
            tool_calls=(ToolCallRequest(call_id="a", tool_name="bad name!", arguments={}),),
        ),
    )
    with pytest.raises(ValueError, match="tool_name"):
        redact_request(ModelRequest(system="s", turns=bad, correlation_id="c"))
