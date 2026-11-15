"""Shared harness for the lifecycle API tests: PRP-06 authz harness, real router, in-memory stores.

``ADMIN`` holds the admin role on the customer control domain (so ``lifecycle.manage`` at
customer level); ``DOMAIN_ADMIN`` is an admin on one ordinary domain only (not customer level);
``VIEWER`` holds no lifecycle permission.
"""

import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_TESTS = Path(__file__).resolve().parents[1]
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

import authz.authz_helpers as helpers  # noqa: E402  # pyright: ignore[reportMissingImports]
from neurosphere_api.actions.customer_control import customer_control_domain  # noqa: E402
from neurosphere_api.lifecycle import PREFIX, LifecycleApiState, build_router  # noqa: E402
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore  # noqa: E402
from neurosphere_core.auth.scope import Role  # noqa: E402
from neurosphere_core.lifecycle.jobs import InMemoryJobStore  # noqa: E402
from neurosphere_core.lifecycle.memory import (  # noqa: E402
    InMemoryHoldRegistry,
    InMemoryRequestQueue,
)
from neurosphere_core.lifecycle.policy import UNSET, PolicyState  # noqa: E402

CUSTOMER: str = helpers.CUSTOMER
ADMIN: str = helpers.ALICE
DOMAIN_ADMIN: str = helpers.BOB
VIEWER: str = helpers.CAROL
FINANCE: str = helpers.FINANCE
CONTROL: str = customer_control_domain("commercial", CUSTOMER)
CHAIN = f"lifecycle.{CUSTOMER}"
NOW = datetime(2026, 11, 15, 12, 0, 0, tzinfo=UTC)


@dataclass
class Env:
    h: Any
    state: LifecycleApiState
    audit: AuditRepository

    def call(self, who: str | None, method: str, path: str, **kwargs: Any) -> Any:
        headers = self.h.auth(who) if who else {}
        return self.h.client.request(method, f"{PREFIX}{path}", headers=headers, **kwargs)

    async def audit_rows(self) -> list[Any]:
        return list(await self.audit.read_range(CHAIN, limit=500))


def make_env(*, mode: str = "dry_run", policy: PolicyState = UNSET, configure: bool = True) -> Env:
    h = helpers.harness(
        helpers.policy(
            ADMIN,
            helpers.role(Role.ADMIN, CONTROL),
            memberships=(FINANCE, CONTROL),
        ),
        helpers.policy(DOMAIN_ADMIN, helpers.role(Role.ADMIN, FINANCE)),
        helpers.policy(VIEWER, helpers.role(Role.VIEWER, FINANCE)),
        routers={PREFIX: build_router()},
    )
    audit = AuditRepository(InMemoryAuditStore())
    state = LifecycleApiState(
        jobs=InMemoryJobStore(),
        holds=InMemoryHoldRegistry(),
        queue=InMemoryRequestQueue(),
        audit=audit,
        mode=mode,
        policy=policy,
        clock=lambda: NOW,
    )
    if configure:
        h.app.state.lifecycle = state
    return Env(h=h, state=state, audit=audit)
