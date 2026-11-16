"""PRP-44 item 6: identity writes reject an unregistered domain once a registry exists."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "admin_identity_api"))

from identity_harness import (  # pyright: ignore[reportMissingImports]
    CUSTOMER,
    CUSTOMER_ADMIN,
    FINANCE,
    OPERATIONS,
    TARGET,
    IdentityWorld,
    configure_env,
    pid,
)
from neurosphere_api.runtime.builders import admin_platform
from neurosphere_contracts.admin.v1.domain_definition import DomainDefinition
from neurosphere_core.admin import InMemoryAdminConfigRepository
from neurosphere_core.admin.platform import DomainAdmin
from neurosphere_core.pricing import InMemoryPriceSnapshotStore

BASE = "/api/v1/admin/identity"
ACTOR = "commercial:contoso:entra:person:p-" + "0c" * 32


@pytest.fixture(autouse=True)
def _auth(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_env(monkeypatch)


def _world() -> tuple[IdentityWorld, InMemoryAdminConfigRepository]:
    repository = InMemoryAdminConfigRepository(cloud="commercial")
    world = IdentityWorld.build(
        extra_builders=(admin_platform.BUILDER,),
        admin_config_repository=repository,
        price_snapshot_store=InMemoryPriceSnapshotStore(),
    )
    return world, repository


async def _register(repository: InMemoryAdminConfigRepository, domain_id: str) -> None:
    await DomainAdmin(repository, cloud="commercial").create(
        CUSTOMER,
        DomainDefinition.model_validate(
            {
                "schema_version": "1.0.0",
                "domain_id": domain_id,
                "display_name": "D",
                "classification": "internal",
                "residency_region": "eastus2",
                "status": "active",
                "is_control_domain": False,
            }
        ),
        updated_by=ACTOR,
    )


def _membership(domain_id: str, op: str = "add") -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "op": op,
        "principal_id": pid(TARGET),
        "domain_id": domain_id,
        "reason": "onboarding",
    }


def _put(world: IdentityWorld, domain_id: str, op: str = "add") -> Any:
    with world.composed.client() as client:
        etag = client.get(f"{BASE}/principals/{pid(TARGET)}", headers=world.auth(CUSTOMER_ADMIN))
        path = f"{BASE}/principals/{pid(TARGET)}/domain-memberships/{domain_id}"
        headers = world.auth(CUSTOMER_ADMIN, **{"If-Match": etag.headers["ETag"]})
        if op == "remove":
            return client.delete(path, headers=headers)
        return client.put(path, json=_membership(domain_id, op), headers=headers)


def _role(domain_id: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "op": "assign",
        "principal_id": pid(TARGET),
        "assignment_id": "ra-viewer",
        "role": "viewer",
        "domain_ids": [domain_id],
        "reason": "access_request",
    }


def test_with_no_registered_domain_behaviour_is_unchanged() -> None:
    world, _ = _world()
    assert _put(world, OPERATIONS).status_code == 200


async def test_an_add_naming_an_unregistered_domain_is_422_once_a_domain_exists() -> None:
    world, repository = _world()
    await _register(repository, FINANCE)
    response = _put(world, OPERATIONS)
    assert response.status_code == 422, response.text
    assert response.json()["reason"] == "domain_not_registered"


async def test_a_registered_domain_is_accepted() -> None:
    world, repository = _world()
    await _register(repository, FINANCE)
    await _register(repository, OPERATIONS)
    assert _put(world, OPERATIONS).status_code == 200


async def test_role_assignment_naming_an_unregistered_domain_is_422() -> None:
    world, repository = _world()
    await _register(repository, FINANCE)
    with world.composed.client() as client:
        etag = client.get(f"{BASE}/principals/{pid(TARGET)}", headers=world.auth(CUSTOMER_ADMIN))
        response = client.put(
            f"{BASE}/principals/{pid(TARGET)}/role-assignments/ra-viewer",
            json=_role(OPERATIONS),
            headers=world.auth(CUSTOMER_ADMIN, **{"If-Match": etag.headers["ETag"]}),
        )
    assert response.status_code == 422 and response.json()["reason"] == "domain_not_registered"


async def test_removal_of_an_unregistered_domain_is_still_allowed() -> None:
    world, repository = _world()
    await _register(repository, FINANCE)
    # TARGET is seeded as a member of OPERATIONS, which is not registered: cleanup must work.
    assert _put(world, OPERATIONS, op="remove").status_code == 200
