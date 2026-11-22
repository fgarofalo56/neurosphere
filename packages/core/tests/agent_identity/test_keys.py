"""Alias key, derived id and owned-agent check."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from neurosphere_core.agent_identity import (
    agent_alias_key,
    derive_agent_id,
    is_owned_agent,
)

_PATH = Path(__file__).resolve().parents[4] / "tests" / "contracts" / "validators.py"
_SPEC = importlib.util.spec_from_file_location("ns_contract_validators_prp137", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MOD
sys.path.insert(0, str(_PATH.parent))  # validators imports its sibling contract_support
try:
    _SPEC.loader.exec_module(_MOD)
finally:
    sys.path.remove(str(_PATH.parent))
validate_canonical_id_grammar = _MOD.validate_canonical_id_grammar


def _valid(value: str) -> bool:
    return validate_canonical_id_grammar({"canonical_agent_id": value}) == []


def test_alias_key_uses_slugged_source_and_raw_value() -> None:
    key = agent_alias_key("Foundry East/US", "asst_Abc123")
    assert key.alias_source_id == "foundry-east-us"
    assert key.alias_kind == "external_id"
    assert key.alias_value == "asst_Abc123"


def test_derived_plain_id_has_no_suffix() -> None:
    assert derive_agent_id("commercial", "acme", "foundry", "support-bot") == (
        "commercial:acme:foundry:agent:support-bot"
    )


def test_derived_is_stable_and_grammar_valid() -> None:
    a = derive_agent_id("commercial", "acme", "foundry", "Asst_ABC 123")
    assert a == derive_agent_id("commercial", "acme", "foundry", "Asst_ABC 123")
    assert _valid(a)


def test_ids_that_slug_alike_stay_distinct() -> None:
    a = derive_agent_id("commercial", "acme", "foundry", "Support Bot")
    b = derive_agent_id("commercial", "acme", "foundry", "support-bot!")
    c = derive_agent_id("commercial", "acme", "foundry", "support-bot")
    assert len({a, b, c}) == 3
    assert c.endswith(":support-bot")
    assert _valid(a) and _valid(b)


@pytest.mark.parametrize("external", ["", "!!!", "é中文", "-._", "x" * 900])
def test_derived_handles_degenerate_ids(external: str) -> None:
    value = derive_agent_id("government", "acme", "ÄÖ source", external)
    assert _valid(value)
    assert len(value) <= 512
    assert value.startswith("government:acme:source:agent:") or ":trace:agent:" in value


def test_non_ascii_ids_do_not_collide() -> None:
    a = derive_agent_id("commercial", "acme", "foundry", "中文")
    b = derive_agent_id("commercial", "acme", "foundry", "éè")
    assert a != b


def test_owned_agent_check() -> None:
    ok = "commercial:acme:foundry:agent:a1"
    assert is_owned_agent(ok, "commercial", "acme")
    assert not is_owned_agent(ok, "government", "acme")
    assert not is_owned_agent(ok, "commercial", "other")
    assert not is_owned_agent("commercial:acme:foundry:tool:a1", "commercial", "acme")
    assert not is_owned_agent("not-canonical", "commercial", "acme")
    assert not is_owned_agent(None, "commercial", "acme")
