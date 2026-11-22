"""GenAI query set (PRP-141 item 1): fixed text, allowlists, no denylisted name."""

from __future__ import annotations

import re

import pytest
from neurosphere_connector_azure_monitor import (
    CONTENT_DENYLIST,
    GENAI_ATTRIBUTE_KEYS,
    GENAI_COLUMNS,
    SourceKind,
)
from neurosphere_connector_azure_monitor.queries import (
    APP_INSIGHTS_KINDS,
    MAX_ROWS,
    TEMPLATES,
)

KINDS = (SourceKind.APP_GENAI_DEPENDENCIES, SourceKind.APP_GENAI_REQUESTS)
# A KQL identifier, optionally dotted (attribute keys such as gen_ai.input.messages).
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
# Bracket-quoted column names and string literals: ['x'] and "x".
_QUOTED = re.compile(r"\['([^']*)'\]|\"([^\"]*)\"")


def _names(text: str) -> set[str]:
    found: set[str] = set()
    for match in _QUOTED.finditer(text):
        found.add(match.group(1) or match.group(2))
    found.update(_IDENT.findall(_QUOTED.sub(" ", text)))
    return found


def test_kinds_use_the_workspace_query_api() -> None:
    for kind in KINDS:
        assert kind not in APP_INSIGHTS_KINDS


def test_templates_are_registered_with_the_right_table() -> None:
    assert TEMPLATES[SourceKind.APP_GENAI_DEPENDENCIES].startswith("AppDependencies |")
    assert TEMPLATES[SourceKind.APP_GENAI_REQUESTS].startswith("AppRequests |")


@pytest.mark.parametrize("kind", KINDS)
def test_no_format_placeholders_and_no_interpolated_window(kind: SourceKind) -> None:
    text = TEMPLATES[kind]
    assert "{" not in text
    assert "}" not in text
    assert "ago(" not in text
    assert "datetime(" not in text
    assert f"take {MAX_ROWS}" in text
    assert "order by TimeGenerated asc" in text


@pytest.mark.parametrize("kind", KINDS)
def test_no_denylisted_name_appears_as_a_whole_identifier(kind: SourceKind) -> None:
    text = TEMPLATES[kind]
    names = _names(text)
    # The attribute bag may only be indexed per allowlisted key, never named bare.
    for name in CONTENT_DENYLIST - {"Properties"}:
        assert name not in names, (kind, name)
        assert name not in text.replace("AppRoleName", ""), (kind, name)


@pytest.mark.parametrize("kind", KINDS)
def test_properties_is_only_indexed_by_an_allowlisted_key(kind: SourceKind) -> None:
    text = TEMPLATES[kind]
    uses = re.findall(r'Properties(.)(?:"([^"]*)")?', text)
    assert uses
    for follow, key in uses:
        assert follow == "[", "Properties must never appear bare"
        assert key in GENAI_ATTRIBUTE_KEYS
    project = text.split(" | project ", 1)[1].split(" | order by", 1)[0]
    assert "Properties" not in project


@pytest.mark.parametrize("kind", KINDS)
def test_every_projected_column_is_allowlisted(kind: SourceKind) -> None:
    text = TEMPLATES[kind]
    project = text.split(" | project ", 1)[1].split(" | order by", 1)[0]
    projected = [part.strip() for part in project.split(", ")]
    expected = [*GENAI_COLUMNS, *(f"['{key}']" for key in GENAI_ATTRIBUTE_KEYS)]
    assert projected == expected
    for part in projected:
        match = _QUOTED.fullmatch(part)
        name = match.group(1) if match else part
        assert name in GENAI_COLUMNS or name in GENAI_ATTRIBUTE_KEYS


def test_allowlists_hold_nothing_denied_and_nothing_extra() -> None:
    assert not set(GENAI_COLUMNS) & CONTENT_DENYLIST
    assert not set(GENAI_ATTRIBUTE_KEYS) & CONTENT_DENYLIST
    assert set(GENAI_COLUMNS) == {
        "TimeGenerated",
        "Id",
        "OperationId",
        "ParentId",
        "Success",
        "DurationMs",
        "ItemCount",
        "AppRoleName",
    }
    assert "gen_ai.operation.name" in GENAI_ATTRIBUTE_KEYS
    assert "gen_ai.agent.id" in GENAI_ATTRIBUTE_KEYS
    assert "gen_ai.agent.name" not in GENAI_ATTRIBUTE_KEYS
    assert "gen_ai.tool.name" not in GENAI_ATTRIBUTE_KEYS
    assert len(set(GENAI_ATTRIBUTE_KEYS)) == len(GENAI_ATTRIBUTE_KEYS)


def test_denylist_covers_the_verified_content_and_personal_data_names() -> None:
    required = {
        "gen_ai.input.messages",
        "gen_ai.output.messages",
        "gen_ai.system_instructions",
        "gen_ai.tool.definitions",
        "gen_ai.tool.call.arguments",
        "gen_ai.tool.call.result",
        "gen_ai.evaluation.explanation",
        "gen_ai.conversation.id",
        "user.id",
        "client.address",
        "Status.message",
        "Properties",
        "Measurements",
        "AppTraces",
        "AppExceptions",
        "AppEvents",
    }
    assert required <= CONTENT_DENYLIST
