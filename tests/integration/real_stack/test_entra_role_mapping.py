"""PRP-138 item 7: the first admin comes from the Entra role mapping on the real stack.

Needs the compose emulators (Cosmos on 127.0.0.1:8081); never starts or stops compose. The app is
the production composition (``create_app`` + ``compose_app``, default builders, Cosmos policy
store, domain registry and audit store on the emulator) with ``NS_AUTH_ROLE_MAPPINGS`` set; only
the token validator is the stand-in from ``conftest.py`` (the local test issuer, accepted for
mapping because ``NS_ENV=local``).

Empty policy store: the run uses a fresh customer id, so its partition of the policy container has
no policy head and no principal document, and its domain registry is empty. Nothing from other
suites is assumed and nothing is left active: the domain the test creates is retired at the end.

Run: ``MSYS_NO_PATHCONV=1 uv run pytest -q -m integration
tests/integration/real_stack/test_entra_role_mapping.py``.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Callable
from typing import Final

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from neurosphere_api.app import create_app
from neurosphere_api.runtime import CompositionOverrides, compose_app
from neurosphere_api.runtime.pseudonym import local_dev_pseudonym_key
from neurosphere_api.runtime.settings import StoreSettings
from neurosphere_core.auth.jwt import JwtValidator
from neurosphere_core.auth.scope import (
    DEFAULT_POLICY_CONTAINER,
    CosmosPolicyRepository,
    PrincipalPseudonymizer,
)
from neurosphere_core.clients import ClientLifetime, create_cosmos_client
from neurosphere_core.cloud import CloudName, Settings

from .conftest import real_stack_audience, real_stack_tenant

pytestmark = pytest.mark.integration

LOOPBACK: Final = "http://127.0.0.1:8081"
SCP: Final = "access_as_user"
STATUS: Final = "/api/v1/admin/system/status"
DOMAINS: Final = "/api/v1/admin/platform/domains"
ME_DOMAINS: Final = "/api/v1/me/domains"
ME_ACCESS: Final = "/api/v1/me/access"


def _mapping() -> str:
    return json.dumps(
        {
            "tenant_id": real_stack_tenant(),
            "audience": real_stack_audience(),
            "entries": [
                {
                    "id": "ns-admins",
                    "claim": "roles",
                    "value": "admin",
                    "role": "admin",
                    "domains": "all",
                    "customer_control": True,
                }
            ],
        }
    )


def _wait_for_containers(client: TestClient, timeout_seconds: float = 90.0) -> None:
    """Block until the background container bootstrap of this composition has finished.

    The API creates its Cosmos containers in the background after startup; until then the domain
    registry's container may not exist and a mapped ``all`` entry correctly denies with 503
    ``domain_directory_unavailable`` (it never grants a partial scope).
    """
    deadline = time.monotonic() + timeout_seconds
    pending: list[str] = []
    while time.monotonic() < deadline:
        deps = client.get("/readyz").json().get("dependencies", {})
        pending = sorted(k for k in deps if k.startswith("composition.cosmos_containers."))
        if not pending:
            return
        time.sleep(0.5)
    raise AssertionError(f"container bootstrap did not finish: {pending}")


def _compose(validator: JwtValidator) -> FastAPI:
    settings = Settings()
    app = create_app(settings)
    compose_app(app, settings, CompositionOverrides(authenticator=validator))
    return app


async def _policy_state(customer: str, principal_id: str) -> tuple[bool, bool]:
    """(policy head exists, principal document exists) for ``customer`` on the emulator."""
    settings = Settings()
    async with ClientLifetime() as lifetime:
        client = create_cosmos_client(settings, lifetime=lifetime)
        repo = CosmosPolicyRepository(
            client, database=StoreSettings().database, container=DEFAULT_POLICY_CONTAINER
        )
        head = await repo.get_policy_head(customer)
        document = await repo.get_principal_policy(customer, principal_id)
    return head is not None, document is not None


def test_mapped_entra_role_is_the_first_admin(
    monkeypatch: pytest.MonkeyPatch,
    emulator_env: None,
    stand_in_validator: JwtValidator,
    stand_in_token: Callable[..., dict[str, str]],
) -> None:
    monkeypatch.setenv("NS_COSMOS_ENDPOINT", LOOPBACK)
    customer = f"prp138-{uuid.uuid4().hex[:12]}"
    monkeypatch.setenv("NS_AUTH_CUSTOMER_ID", customer)
    monkeypatch.setenv("NS_AUTH_ROLE_MAPPINGS", _mapping())
    oid = str(uuid.uuid4())
    principal = PrincipalPseudonymizer(local_dev_pseudonym_key()).principal_id(
        cloud=CloudName.COMMERCIAL,
        customer_id=customer,
        tenant_id=real_stack_tenant(),
        object_id=oid,
        kind="user",
    )
    assert asyncio.run(_policy_state(customer, principal)) == (False, False)  # empty store
    headers = stand_in_token(oid, roles=["admin"], scp=SCP)
    domain = f"commercial:{customer}:catalog:domain:prp138-finance"

    with TestClient(_compose(stand_in_validator), raise_server_exceptions=False) as client:
        _wait_for_containers(client)
        status = client.get(STATUS, headers=headers)
        assert status.status_code == 200, status.text
        # Without the role the same deployment grants nothing.
        assert client.get(STATUS, headers=stand_in_token(oid, scp=SCP)).status_code == 403
        listed = client.get(DOMAINS, headers=headers)
        assert listed.status_code == 200, listed.text
        assert listed.json()["items"] == []  # empty registry for this customer
        created = client.post(
            DOMAINS,
            headers=headers,
            json={
                "schema_version": "1.0.0",
                "domain_id": domain,
                "display_name": "PRP-138 Finance",
                "classification": "internal",
                "residency_region": "eastus2",
                "status": "active",
                "is_control_domain": False,
            },
        )
        assert created.status_code == 201, created.text
        etag = created.headers["ETag"]

    # A fresh composition (no directory cache from the first app) sees the new domain at once.
    with TestClient(_compose(stand_in_validator), raise_server_exceptions=False) as fresh:
        try:
            _wait_for_containers(fresh)
            mine = fresh.get(ME_DOMAINS, headers=headers)
            assert mine.status_code == 200, mine.text
            assert domain in {item["domain_id"] for item in mine.json()["items"]}
            access = fresh.get(ME_ACCESS, headers=headers)
            assert access.status_code == 200, access.text
            assert [(r["role"], r["source"]) for r in access.json()["roles"]] == [
                ("admin", "entra_app_role")
            ]
        finally:
            # Cleanup. The emulator stores unquoted ETags while the API answers them quoted, and
            # the quoted form is refused as stale here; send the stored (unquoted) value.
            retired = fresh.post(
                f"{DOMAINS}/{domain}/retire", headers={**headers, "If-Match": etag.strip('"')}
            )
            assert retired.status_code == 200, retired.text

    # No script ran and nothing was written to the policy store.
    assert asyncio.run(_policy_state(customer, principal)) == (False, False)
