"""Harness for the gateway registry API tests (offline: fake ARM over ``MockTransport``).

People (customer ``contoso``): ADMIN holds ``config.manage`` + ``data.read`` on FINANCE only;
VIEWER holds ``data.read`` on FINANCE; STEWARD (domain steward) has no ``config.manage``.

This directory has no ``__init__.py``: import by module name.
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import authz.authz_helpers as helpers  # pyright: ignore[reportMissingImports]
import httpx
from neurosphere_api.gateway import GatewayPlane, GatewaySettings, configure_gateway_plane
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.auth.scope import Role
from neurosphere_core.clients import arm_client
from neurosphere_core.cloud import CloudProfile
from neurosphere_core.gateway import InMemoryGatewayStore

_FAKE = Path(__file__).resolve().parents[4] / "packages/core/tests/gateway_core/fake_arm.py"


def _load_fake() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gateway_fake_arm", _FAKE)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


fake_arm = _load_fake()
FakeArm = fake_arm.FakeArm
RID: str = fake_arm.RID
SECRET_MARKER: str = fake_arm.SECRET_MARKER
XML_MARKER: str = fake_arm.XML_MARKER

ADMIN = "9f4a5b6c-7d8e-4f90-a1b2-c3d4e5f6a7b8"
VIEWER = helpers.CAROL
STEWARD = helpers.ALICE
FINANCE: str = helpers.FINANCE
OPERATIONS: str = helpers.OPERATIONS
PREFIX = "/api/v1/gateways"


def people() -> tuple[object, ...]:
    return (
        helpers.policy(ADMIN, helpers.role(Role.ADMIN, FINANCE)),
        helpers.policy(VIEWER, helpers.role(Role.VIEWER, FINANCE)),
        helpers.policy(STEWARD, helpers.role(Role.DOMAIN_STEWARD, FINANCE)),
    )


@dataclass
class Env:
    auth: helpers.Harness
    store: InMemoryGatewayStore
    audit: AuditRepository
    arm: object

    def call(self, method: str, who: str | None, path: str, **kwargs: object) -> httpx.Response:
        headers = {} if who is None else self.auth.auth(who)
        return self.auth.client.request(method, f"{PREFIX}{path}", headers=headers, **kwargs)  # type: ignore[arg-type]

    def register(self, domain: str = FINANCE, **body: object) -> httpx.Response:
        payload = {"arm_resource_id": RID, **body}
        return self.call("POST", ADMIN, f"/domains/{domain}/gateways", json=payload)


def make_env(arm: object | None = None, *, configure: bool = True) -> Env:
    fake = arm if arm is not None else FakeArm()
    auth = helpers.harness(*people())  # type: ignore[arg-type]
    store = InMemoryGatewayStore()
    audit = AuditRepository(InMemoryAuditStore())

    def factory(profile: CloudProfile) -> httpx.AsyncClient:
        return arm_client(profile, fake_arm.FakeCredential(), transport=fake.transport())  # type: ignore[attr-defined,arg-type]

    if configure:
        configure_gateway_plane(
            auth.app,
            GatewayPlane(store=store, audit=audit, arm_factory=factory, settings=GatewaySettings()),
        )
    return Env(auth=auth, store=store, audit=audit, arm=fake)
