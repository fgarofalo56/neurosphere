"""PRP-44 item 1: budget rules."""

from __future__ import annotations

import pytest
from neurosphere_contracts.admin.v1.budget import SpendBudget
from neurosphere_contracts.admin.v1.domain_definition import DomainDefinition
from neurosphere_core.admin import InMemoryAdminConfigRepository
from neurosphere_core.admin.platform import BudgetAdmin, DomainAdmin, DomainRegistry
from neurosphere_core.errors import InvalidSchemaError
from pydantic import ValidationError

from .platform_helpers import ACTOR, CUSTOMER, budget_body, domain_body


async def _world() -> BudgetAdmin:
    repo = InMemoryAdminConfigRepository(cloud="commercial")
    await DomainAdmin(repo, cloud="commercial").create(
        CUSTOMER, DomainDefinition.model_validate(domain_body()), updated_by=ACTOR
    )
    return BudgetAdmin(repo, DomainRegistry(repo))


def _budget(**over: object) -> SpendBudget:
    return SpendBudget.model_validate(budget_body(**over))  # type: ignore[arg-type]


async def test_budget_is_stored_listed_replaced_and_retired() -> None:
    admin = await _world()
    created = await admin.create(CUSTOMER, _budget(), updated_by=ACTOR)
    assert created.version.root == 1
    assert [d.id.root for d in await admin.list(CUSTOMER)] == ["fin-monthly"]
    replaced = await admin.replace(
        CUSTOMER,
        "fin-monthly",
        _budget(amount="2000"),
        if_match=created.etag.root,
        updated_by=ACTOR,
    )
    assert replaced.version.root == 2
    retired = await admin.retire(
        CUSTOMER, "fin-monthly", if_match=replaced.etag.root, updated_by=ACTOR
    )
    assert retired.status == "retired"
    assert await admin.list(CUSTOMER) == []
    assert await admin.get(CUSTOMER, "fin-monthly") is not None


async def test_unknown_domain_is_refused() -> None:
    admin = await _world()
    other = "commercial:contoso:neurosphere:domain:ops"
    with pytest.raises(InvalidSchemaError) as caught:
        await admin.create(CUSTOMER, _budget(domain_id=other), updated_by=ACTOR)
    assert caught.value.reason == "domain_not_registered"


async def test_float_amount_is_refused_by_the_contract() -> None:
    with pytest.raises(ValidationError):
        _budget(amount=1500.5)


async def test_duplicate_or_descending_thresholds_are_refused() -> None:
    admin = await _world()
    for thresholds in ([50, 50], [80, 50]):
        with pytest.raises(InvalidSchemaError):
            await admin.create(CUSTOMER, _budget(thresholds_percent=thresholds), updated_by=ACTOR)


async def test_threshold_above_200_percent_is_refused() -> None:
    admin = await _world()
    with pytest.raises(InvalidSchemaError) as caught:
        await admin.create(CUSTOMER, _budget(thresholds_percent=[100, 201]), updated_by=ACTOR)
    assert caught.value.reason == "budget_threshold_out_of_range"


async def test_replace_body_must_match_the_path() -> None:
    admin = await _world()
    created = await admin.create(CUSTOMER, _budget(), updated_by=ACTOR)
    with pytest.raises(InvalidSchemaError) as caught:
        await admin.replace(
            CUSTOMER,
            "other",
            _budget(),
            if_match=created.etag.root,
            updated_by=ACTOR,
        )
    assert caught.value.reason == "budget_id_mismatch"
