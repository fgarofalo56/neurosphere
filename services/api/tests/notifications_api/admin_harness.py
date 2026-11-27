"""Harness for the notification admin API tests (PRP-107 item 7).

Composes the REAL authz builder, a stub data builder (in-memory audit) and the REAL
``notifications`` builder over in-memory ``admin_config`` and outbox stores. Principals:

* ``CUSTOMER_ADMIN``: ``admin`` on FINANCE and the customer-control domain (customer-level
  ``config.manage``).
* ``DOMAIN_ADMIN``: ``admin`` on FINANCE only (``config.manage`` in a domain, not customer-wide).
* ``ANALYST``: analyst in FINANCE (no ``config.manage``).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest
from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    CUSTOMER,
    FINANCE,
    POLICY_VERSION,
    FakeClock,
    RecordingDenials,
    make_validator,
    role,
)
from neurosphere_api.notifications.router import HOOKS_ATTRIBUTE
from neurosphere_api.notifications.service import AdminHooks
from neurosphere_api.runtime import CompositionOverrides
from neurosphere_api.runtime.builders import AUDIT_REPOSITORY, BuildContext, BuilderSpec
from neurosphere_api.runtime.builders import authz as authz_builder
from neurosphere_api.runtime.builders import notifications as builder
from neurosphere_core.admin import InMemoryAdminConfigRepository
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.auth.revocation import InMemoryRevocationStore
from neurosphere_core.auth.scope import (
    InMemoryPolicyRepository,
    PolicyHead,
    PrincipalPolicy,
    Role,
    customer_control_domain_id,
    principal_document_id,
)
from neurosphere_core.notifications import InMemoryOutboxStore
from pydantic import SecretStr
from runtime_api import runtime_helpers  # pyright: ignore[reportMissingImports]
from runtime_api.runtime_helpers import (  # pyright: ignore[reportMissingImports]
    Composed,
    compose,
)

__all__ = [
    "ANALYST",
    "BASE",
    "CUSTOMER",
    "CUSTOMER_ADMIN",
    "DOMAIN",
    "DOMAIN_ADMIN",
    "SIGNING_SECRET",
    "FakeSecrets",
    "Receiver",
    "World",
    "channel_body",
    "configure_env",
    "subscription_body",
]

CUSTOMER_ADMIN = "2b3c4d5e-6f7a-4b8c-9d0e-1f2a3b4c5d6e"
DOMAIN_ADMIN = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
ANALYST = "3c4d5e6f-7a8b-4c9d-8e1f-2a3b4c5d6e7f"
BASE = "/api/v1/admin/notifications"
DOMAIN = "commercial:contoso:neurosphere:domain:finance"
CONTROL = customer_control_domain_id("commercial", CUSTOMER)
ENDPOINT_URI = "https://ns-kv.vault.azure.net/secrets/ops-hook-endpoint"
HMAC_URI = "https://ns-kv.vault.azure.net/secrets/ops-hook-signing"
#: A synthetic value the fake reader returns; the tests assert it never leaves the process.
SIGNING_SECRET = "synthetic-signing-material-0001"  # noqa: S105


def configure_env(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime_helpers.configure_auth_env(monkeypatch)


def pid(object_id: str) -> str:
    return str(runtime_helpers.composed_principal_id(object_id))


def channel_body(channel_id: str = "ops-hook", **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema_version": "1.0.0",
        "channel_id": channel_id,
        "cloud": "commercial",
        "customer_id": CUSTOMER,
        "domain_id": DOMAIN,
        "display_name": "Ops hook",
        "kind": "webhook",
        "allowed_host": "hooks.example.org",
        "endpoint_credential": {"kind": "key_vault_secret", "secret_uri": ENDPOINT_URI},
        "hmac_credential": {"kind": "key_vault_secret", "secret_uri": HMAC_URI},
        "local_sink": False,
        "local_sink_url": None,
        "enabled": True,
    }
    body.update(over)
    return body


def subscription_body(
    subscription_id: str = "ops-sub", channel_id: str = "ops-hook", **over: Any
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema_version": "1.0.0",
        "subscription_id": subscription_id,
        "cloud": "commercial",
        "customer_id": CUSTOMER,
        "domain_id": DOMAIN,
        "channel_id": channel_id,
        "event_classes": ["hitl_item_assigned"],
        "audience_roles": ["domain_steward"],
        "min_severity": "medium",
        "enabled": True,
    }
    body.update(over)
    return body


def _doc(object_id: str, memberships: tuple[str, ...], *domains: str, who: Role) -> PrincipalPolicy:
    principal = pid(object_id)
    return PrincipalPolicy(
        id=principal_document_id(principal),
        customer_id=CUSTOMER,
        principal_id=principal,
        domain_memberships=memberships,
        role_assignments=(role(who, *domains),),
    )


def seeded_policies() -> InMemoryPolicyRepository:
    repo = InMemoryPolicyRepository()
    repo.put_head(PolicyHead(customer_id=CUSTOMER, policy_version=POLICY_VERSION))
    repo.put_principal(_doc(CUSTOMER_ADMIN, (FINANCE, CONTROL), FINANCE, CONTROL, who=Role.ADMIN))
    repo.put_principal(_doc(DOMAIN_ADMIN, (FINANCE,), FINANCE, who=Role.ADMIN))
    repo.put_principal(_doc(ANALYST, (FINANCE,), FINANCE, who=Role.ANALYST))
    return repo


class FakeSecrets:
    """A ``SecretReader`` returning one synthetic value; records how often it was read."""

    def __init__(self, value: str = SIGNING_SECRET) -> None:
        self._value = value
        self.reads = 0

    async def read(self, reference: Any) -> SecretStr:
        self.reads += 1
        return SecretStr(self._value)


class Receiver:
    """A real local HTTP receiver (loopback, ephemeral port) that records what it is sent."""

    def __init__(self, status: int = 200) -> None:
        self.requests: list[dict[str, Any]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                outer.requests.append(
                    {
                        "path": self.path,
                        "headers": {k.lower(): v for k, v in self.headers.items()},
                        "body": self.rfile.read(length),
                    }
                )
                self.send_response(status)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:
                return

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}/hook"

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


@dataclass
class World:
    composed: Composed
    repository: InMemoryAdminConfigRepository
    outbox: InMemoryOutboxStore
    audit_store: InMemoryAuditStore
    denials: RecordingDenials
    secrets: FakeSecrets = field(default_factory=FakeSecrets)

    def auth(self, object_id: str) -> dict[str, str]:
        return self.composed.auth(object_id)

    def client(self) -> Any:
        return self.composed.client()

    def records(self) -> list[dict[str, Any]]:
        chains = {chain for (chain, _doc) in self.audit_store._docs}  # pyright: ignore[reportPrivateUsage]
        out: list[dict[str, Any]] = []
        for chain in sorted(chains):
            out.extend(sorted(self.audit_store.raw_documents(chain), key=lambda d: d["sequence"]))
        return out

    async def configure(self, *hosts: str) -> None:
        """Store the ``notifications`` system setting with ``hosts`` on the egress allow-list."""
        await self.repository.create(
            CUSTOMER,
            "system_setting",
            "notifications",
            {
                "schema_version": "1.0.0",
                "setting_key": "notifications",
                "enabled": True,
                "notifications": {"egress_allowed_hosts": list(hosts)},
            },
            updated_by=pid(CUSTOMER_ADMIN),
        )

    @classmethod
    def build(cls, settings: Any = None) -> World:
        clock = FakeClock()
        repository = InMemoryAdminConfigRepository(cloud="commercial")
        outbox = InMemoryOutboxStore()
        store = InMemoryAuditStore()
        audit = AuditRepository(store)
        denials = RecordingDenials()
        secrets = FakeSecrets()

        def build_data(ctx: BuildContext) -> None:
            ctx.publish(AUDIT_REPOSITORY, audit)
            ctx.app.state.audit_repository = audit
            ctx.ok("audit")

        overrides = CompositionOverrides(
            authenticator=make_validator(clock),
            policy_repository=seeded_policies(),
            revocation_store=InMemoryRevocationStore(clock=clock),
            clock=clock,
            denial_recorder=denials,
            backends={
                "admin_config_repository": repository,
                "notification_outbox_store": outbox,
            },
        )
        chain = (
            authz_builder.BUILDER,
            BuilderSpec("stub-data", ("audit",), build_data),
            builder.BUILDER,
        )
        composed = compose(overrides, builders=chain, clock=clock, settings=settings)
        setattr(composed.app.state, HOOKS_ATTRIBUTE, AdminHooks(secrets=secrets))
        return cls(composed, repository, outbox, store, denials, secrets)
