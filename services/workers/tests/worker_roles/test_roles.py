"""NS_WORKER_ROLES parsing and the role registry."""

import pytest
from neurosphere_workers.runtime import ROLE_NAMES, UnknownRoleError, parse_roles
from neurosphere_workers.runtime.factories import BUILDERS

WIRE_CONTRACT_ROLES = (
    "ingestion",
    "projections",
    "aggregates",
    "actions",
    "hitl_timers",
    "lifecycle",
    "recommendations",
    "evaluation",
)


def test_all_expands_to_the_wire_contract_list() -> None:
    assert ROLE_NAMES == WIRE_CONTRACT_ROLES
    assert parse_roles("all") == WIRE_CONTRACT_ROLES
    assert parse_roles("ALL") == WIRE_CONTRACT_ROLES
    assert parse_roles("ingestion, all") == WIRE_CONTRACT_ROLES


@pytest.mark.parametrize("raw", [None, "", "   ", " , "])
def test_unset_or_blank_means_idle(raw: str | None) -> None:
    assert parse_roles(raw) == ()


def test_subset_is_canonical_order_and_deduplicated() -> None:
    assert parse_roles("aggregates,ingestion,projections,ingestion") == (
        "ingestion",
        "projections",
        "aggregates",
    )


@pytest.mark.parametrize("raw", ["nope", "ingestion,nope", "all,bogus", "Ingestion;actions"])
def test_unknown_role_refuses_start(raw: str) -> None:
    with pytest.raises(UnknownRoleError) as caught:
        parse_roles(raw)
    assert caught.value.unknown


def test_every_role_has_exactly_one_builder() -> None:
    assert tuple(BUILDERS) == ROLE_NAMES
