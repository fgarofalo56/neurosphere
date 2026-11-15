"""Reserved customer-level chain names and the chain customer-id rule (PRP-48 item 5, #206)."""

from __future__ import annotations

import pytest
from neurosphere_core.admin.chains import ADMIN_CONFIG_CHAIN_SUFFIX, admin_config_chain_id
from neurosphere_core.analytics.fixture.data import DOMAINS as ANALYTICS_FIXTURE_DOMAINS
from neurosphere_core.audit import (
    RESERVED_CHAIN_NAMES,
    domain_audit_chain_id,
    domain_from_audit_chain,
    is_chain_customer_id,
    is_reserved_chain_name,
)
from neurosphere_core.errors import InvalidSchemaError

CUSTOMER = "contoso"


def test_reserved_set_is_exact() -> None:
    assert (
        frozenset(
            {
                "authz-denials",
                "gateway",
                "execution-control",
                "deploy",
                "mcp-admin",
                "admin-config",
                "identity-admin",
                "read-audit",
            }
        )
        == RESERVED_CHAIN_NAMES
    )


def test_core_admin_config_chain_is_reserved() -> None:
    assert ADMIN_CONFIG_CHAIN_SUFFIX in RESERVED_CHAIN_NAMES
    assert admin_config_chain_id(CUSTOMER) == f"{CUSTOMER}.{ADMIN_CONFIG_CHAIN_SUFFIX}"


@pytest.mark.parametrize("name", sorted(RESERVED_CHAIN_NAMES))
def test_catalog_domain_with_a_reserved_name_is_refused(name: str) -> None:
    assert is_reserved_chain_name(name)
    with pytest.raises(InvalidSchemaError) as caught:
        domain_audit_chain_id(CUSTOMER, f"commercial:{CUSTOMER}:catalog:domain:{name}")
    assert caught.value.reason == "invalid_chain_id"


@pytest.mark.parametrize("name", sorted(RESERVED_CHAIN_NAMES))
def test_customer_level_chain_never_decodes_to_a_domain(name: str) -> None:
    assert domain_from_audit_chain("commercial", CUSTOMER, f"{CUSTOMER}.{name}") is None


@pytest.mark.parametrize("name", sorted(RESERVED_CHAIN_NAMES))
def test_source_qualified_domain_with_a_reserved_name_is_fine(name: str) -> None:
    """The ``_<len>.`` marker form cannot collide, so only the catalog form is reserved."""
    domain = f"commercial:{CUSTOMER}:sandbox:domain:{name}"
    chain = domain_audit_chain_id(CUSTOMER, domain)
    assert chain == f"{CUSTOMER}._7.sandbox.{name}"
    assert domain_from_audit_chain("commercial", CUSTOMER, chain) == domain


@pytest.mark.parametrize("name", ["finance", "gateways", "deploy-ops", "my-gateway", "audit"])
def test_near_names_are_not_reserved(name: str) -> None:
    assert not is_reserved_chain_name(name)
    domain_audit_chain_id(CUSTOMER, f"commercial:{CUSTOMER}:catalog:domain:{name}")


@pytest.mark.parametrize(
    ("customer", "ok"),
    [
        ("contoso", True),
        ("synthco", True),
        ("a-b_c9", True),
        ("contoso.eu", False),
        ("Contoso", False),
        ("-x", False),
        ("", False),
    ],
)
def test_chain_customer_id_rule(customer: str, ok: bool) -> None:
    assert is_chain_customer_id(customer) is ok


def test_no_seed_or_fixture_domain_uses_a_reserved_name() -> None:
    """Migration note: no data is rewritten, so no shipped seed may already use a reserved name."""
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[4]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from sandbox.config import PROFILES, GenerateConfig  # pyright: ignore[reportMissingImports]
    from sandbox.world import World  # pyright: ignore[reportMissingImports]

    assert not set(ANALYTICS_FIXTURE_DOMAINS) & RESERVED_CHAIN_NAMES
    for profile in PROFILES.values():
        world = World(GenerateConfig(seed=1, profile=profile, cloud="commercial", customer="x"))
        names = {world.domain_id(i).rsplit(":", 1)[-1] for i in range(len(world.domains))}
        assert not names & RESERVED_CHAIN_NAMES, profile.name
