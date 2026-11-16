"""Reusable fakes for deploy tests: an authorized app harness and a fake async credential.

Generic on purpose (Item 4's ``test_plan.py`` mounts its own router with ``mount``); nothing here
knows about the scan beyond the ``ADMIN``/``VIEWER`` principals.
"""

from __future__ import annotations

from collections.abc import Callable
from types import TracebackType

import pytest

# Sibling test package (pytest rootdir import mode); pyright cannot see that path.
from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    ALICE,
    BOB,
    CUSTOMER,
    FINANCE,
    HR,
    OPERATIONS,
    Harness,
    harness,
    policy,
    role,
)
from azure.core.credentials import AccessToken
from fastapi import APIRouter
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.auth.scope import Role, customer_control_domain_id

#: Holds ``config.manage`` (admin role), including on the control domain (deployment-scoped).
ADMIN = BOB
#: The customer's reserved control domain (PRP-65 / PRP-48 deployment-scoped admin).
CONTROL = customer_control_domain_id("commercial", CUSTOMER)
#: Read-only role: no ``config.manage``.
VIEWER = ALICE


class FakeCredential:
    def __init__(self) -> None:
        self.scopes: list[str] = []

    async def get_token(self, *scopes: str, **_: object) -> AccessToken:
        self.scopes.extend(scopes)
        return AccessToken("fake-token", 4_000_000_000)

    async def close(self) -> None:
        return None

    async def __aenter__(self) -> FakeCredential:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        return None


@pytest.fixture
def mount() -> Callable[[dict[str, APIRouter]], Harness]:
    """Build an authz-configured app with an admin and a viewer, mounting ``routers``."""

    def build(routers: dict[str, APIRouter]) -> Harness:
        h = harness(
            # Deploy scan and plan need the deployment-scoped admin (PRP-48 item 3, #114):
            # config.manage on the customer's reserved control domain.
            policy(
                ADMIN,
                role(Role.ADMIN, FINANCE, CONTROL),
                memberships=(FINANCE, OPERATIONS, HR, CONTROL),
            ),
            policy(VIEWER, role(Role.VIEWER, FINANCE)),
            routers=routers,
        )
        h.app.state.audit_repository = AuditRepository(InMemoryAuditStore())
        return h

    return build


@pytest.fixture
def credential() -> FakeCredential:
    return FakeCredential()
