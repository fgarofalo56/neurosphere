"""Test-only composition for item 8: a stub data builder plus in-memory plane backends.

The data builder (item 7) is replaced by :func:`stub_data_builder`, which publishes fakes under
exactly the keys the planes builder consumes (``AUDIT_REPOSITORY``, ``HITL_SERVICE``,
``AGGREGATE_READER``, ``CATALOG_REPOSITORY``) and installs the read ports on ``app.state``. Every
other builder is the REAL one (authz, planes, copilot, mcp, edge). Token validators trust the
PRP-06 in-memory test issuer and enter ONLY through ``CompositionOverrides``; no network, no
emulator, no model endpoint.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

_API_TESTS = Path(__file__).resolve().parents[1]
for _path in (_API_TESTS / "actions_api", _API_TESTS / "copilot_api", _API_TESTS / "mcp_api"):
    if str(_path) not in sys.path:
        sys.path.append(str(_path))

import authz.authz_helpers as authz_helpers  # noqa: E402  # pyright: ignore[reportMissingImports]
import conftest_server as cs  # noqa: E402  # pyright: ignore[reportMissingImports]
import copilot_api_harness as ch  # noqa: E402  # pyright: ignore[reportMissingImports]
import pytest  # noqa: E402
from authz.authz_helpers import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    POLICY_VERSION,
    FakeClock,
    dev_issuer,
    make_validator,
    role,
)
from neurosphere_api.copilot import InMemoryConversationStore  # noqa: E402
from neurosphere_api.hitl import RecheckerReviewerAuthorizer  # noqa: E402
from neurosphere_api.reports import InMemoryReportStore  # noqa: E402
from neurosphere_api.runtime import CompositionOverrides  # noqa: E402
from neurosphere_api.runtime.builders import (  # noqa: E402
    AGGREGATE_READER,
    AUDIT_REPOSITORY,
    CATALOG_REPOSITORY,
    HITL_SERVICE,
    POLICY_REPOSITORY,
    REVOCATION_CHECKER,
    SCOPE_DERIVER,
    BuildContext,
    BuilderSpec,
)
from neurosphere_api.runtime.builders import authz as authz_builder  # noqa: E402
from neurosphere_api.runtime.builders import copilot as copilot_builder  # noqa: E402
from neurosphere_api.runtime.builders import data as data_builder  # noqa: E402
from neurosphere_api.runtime.builders import edge as edge_builder  # noqa: E402
from neurosphere_api.runtime.builders import mcp as mcp_builder  # noqa: E402
from neurosphere_api.runtime.builders import planes as planes_builder  # noqa: E402
from neurosphere_core.actions import InMemoryExecutionControl, InMemoryIntentStore  # noqa: E402
from neurosphere_core.actions.recheck import PolicyPermissionRechecker  # noqa: E402
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore  # noqa: E402
from neurosphere_core.auth.revocation import InMemoryRevocationStore  # noqa: E402
from neurosphere_core.auth.scope import (  # noqa: E402
    InMemoryPolicyRepository,
    PolicyHead,
    PrincipalPolicy,
    Role,
    principal_document_id,
)
from neurosphere_core.hitl import (  # noqa: E402
    DecisionLog,
    HitlService,
    InMemoryDecisionStore,
    InMemoryHitlStore,
    ReviewPolicyRegistry,
)
from neurosphere_core.mcp import InMemoryMcpServerStore  # noqa: E402
from runtime_api import runtime_helpers  # noqa: E402  # pyright: ignore[reportMissingImports]
from runtime_api.runtime_helpers import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    Composed,
    compose,
)

__all__ = [
    "ALICE",
    "BOB",
    "CAROL",
    "CUSTOMER",
    "FINANCE",
    "MCP_ENV",
    "OPERATIONS",
    "DataFakes",
    "Planes",
    "builders",
    "ch",
    "compose_planes",
    "composed_principal_id",
    "configure_auth_env",
    "cs",
    "mcp_token",
    "plane_backends",
    "policy_repository",
    "stub_data_builder",
]

ALICE: Final = "6c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5"  # steward on FINANCE (the maker)
BOB: Final = "7d2e3f4a-5b6c-4d7e-8f90-a1b2c3d4e5f6"  # steward on FINANCE (a checker)
CAROL: Final = "8e3f4a5b-6c7d-4e8f-90a1-b2c3d4e5f6a7"  # viewer on FINANCE
#: ``NS_MCP_*`` for the item 1 MCP test resource (audience distinct from the REST one).
MCP_ENV: Final[Mapping[str, str]] = {
    "NS_MCP_RESOURCE_SERVER_URL": cs.MCP_RESOURCE,
    "NS_MCP_AUDIENCES": f'["{cs.MCP_AUDIENCE}"]',
}
MCP_LIFETIME: Final = 20 * 365 * 86_400  # the SDK also checks exp against the wall clock
CUSTOMER: Final[str] = authz_helpers.CUSTOMER
FINANCE: Final[str] = authz_helpers.FINANCE
OPERATIONS: Final[str] = authz_helpers.OPERATIONS


def configure_auth_env(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    """Item 1's ``NS_AUTH_*`` settings for the PRP-06 test tenant."""
    runtime_helpers.configure_auth_env(monkeypatch, **values)


def composed_principal_id(object_id: str) -> str:
    """Principal id under the composed (local dev) pseudonym key."""
    return str(runtime_helpers.composed_principal_id(object_id))


def _policy(object_id: str, *roles: Any) -> PrincipalPolicy:
    pid = composed_principal_id(object_id)
    return PrincipalPolicy(
        id=principal_document_id(pid),
        customer_id=CUSTOMER,
        principal_id=pid,
        domain_memberships=(FINANCE, OPERATIONS),
        role_assignments=roles,
    )


def policy_repository() -> InMemoryPolicyRepository:
    repo = InMemoryPolicyRepository()
    repo.put_head(PolicyHead(customer_id=CUSTOMER, policy_version=POLICY_VERSION))
    repo.put_principal(_policy(ALICE, role(Role.DOMAIN_STEWARD, FINANCE)))
    repo.put_principal(_policy(BOB, role(Role.DOMAIN_STEWARD, FINANCE)))
    repo.put_principal(_policy(CAROL, role(Role.VIEWER, FINANCE)))
    return repo


@dataclass
class DataFakes:
    """What the stub data builder publishes; ``hitl`` is built at composition time."""

    world: Any = field(default_factory=lambda: cs.default_world())
    audit: AuditRepository = field(default_factory=lambda: AuditRepository(InMemoryAuditStore()))
    hitl_store: InMemoryHitlStore = field(default_factory=InMemoryHitlStore)
    hitl: HitlService | None = None


def stub_data_builder(fakes: DataFakes, *, skip: Iterable[str] = ()) -> BuilderSpec:
    """Item 7's slot: publishes fakes for the four shared keys (minus ``skip``) and reports ok."""
    skipped = frozenset(skip)

    def build(ctx: BuildContext) -> None:
        state = ctx.app.state
        state.catalog_repository = fakes.world.catalog
        state.aggregate_reader = fakes.world.metrics
        state.recommendation_store = fakes.world.recs
        state.audit_repository = fakes.audit
        deriver = ctx.shared(SCOPE_DERIVER)
        reviewer_check = PolicyPermissionRechecker(
            cloud=deriver.config.cloud,
            policy_repository=ctx.shared(POLICY_REPOSITORY),
            revocation_checker=ctx.shared(REVOCATION_CHECKER),
        )
        fakes.hitl = HitlService(
            fakes.hitl_store,
            DecisionLog(fakes.audit, InMemoryDecisionStore()),
            fakes.audit,
            ReviewPolicyRegistry(),
            RecheckerReviewerAuthorizer(reviewer_check),
        )
        if "audit" not in skipped:
            ctx.publish(AUDIT_REPOSITORY, fakes.audit)
        if "hitl" not in skipped:
            ctx.publish(HITL_SERVICE, fakes.hitl)
        if "aggregates" not in skipped:
            ctx.publish(AGGREGATE_READER, fakes.world.metrics)
        if "catalog" not in skipped:
            ctx.publish(CATALOG_REPOSITORY, fakes.world.catalog)
        for name in data_builder.COMPONENTS:
            ctx.ok(name)

    return BuilderSpec("stub-data", data_builder.COMPONENTS, build)


def builders(
    data: BuilderSpec, *, probe: Callable[[BuildContext], None] | None = None
) -> tuple[BuilderSpec, ...]:
    """The production order with only the data builder swapped for ``data``.

    ``probe`` runs as the LAST builder (before the real edge build it wraps), so a test can read
    what earlier builders published.
    """
    last = edge_builder.BUILDER
    if probe is not None:
        observe = probe

        def edge_with_probe(ctx: BuildContext) -> None:
            observe(ctx)
            edge_builder.build(ctx)

        last = BuilderSpec("edge-probe", edge_builder.COMPONENTS, edge_with_probe)
    return (
        authz_builder.BUILDER,
        data,
        planes_builder.BUILDER,
        copilot_builder.BUILDER,
        mcp_builder.BUILDER,
        last,
    )


def plane_backends(**extra: object) -> dict[str, object]:
    """In-memory replacements for every Cosmos store the plane, copilot and MCP builders own."""
    return {
        "intent_store": InMemoryIntentStore(),
        "execution_control": InMemoryExecutionControl(),
        "report_store": InMemoryReportStore(),
        "mcp_server_store": InMemoryMcpServerStore(),
        "copilot_conversation_store": InMemoryConversationStore(),
        **extra,
    }


@dataclass
class Planes:
    composed: Composed
    fakes: DataFakes
    backends: dict[str, object]
    repo: InMemoryPolicyRepository

    @property
    def app(self) -> Any:
        return self.composed.app

    @property
    def registry(self) -> Any:
        return self.composed.registry

    @property
    def clock(self) -> FakeClock:
        return self.composed.clock

    def now(self) -> datetime:
        return datetime.fromtimestamp(self.clock(), UTC)

    def auth(self, object_id: str = ALICE) -> dict[str, str]:
        return self.composed.auth(object_id)


def compose_planes(
    *,
    backends: dict[str, object] | None = None,
    model_adapter: Any | None = None,
    skip: Iterable[str] = (),
    mcp_validator: bool = False,
    probe: Callable[[BuildContext], None] | None = None,
) -> Planes:
    """Compose with the stub data builder; the auth env must already be set by the test."""
    clock = FakeClock()
    fakes = DataFakes()
    resolved = plane_backends() if backends is None else backends
    if mcp_validator:
        resolved = {**resolved, "mcp_validator": cs.make_mcp_validator(clock)}
    repo = policy_repository()
    overrides = CompositionOverrides(
        authenticator=make_validator(clock),
        policy_repository=repo,
        revocation_store=InMemoryRevocationStore(),
        clock=clock,
        model_adapter=model_adapter,
        backends=resolved,
    )
    chain = builders(stub_data_builder(fakes, skip=skip), probe=probe)
    composed = compose(overrides, builders=chain, clock=clock)
    return Planes(composed=composed, fakes=fakes, backends=resolved, repo=repo)


def mcp_token(planes: Planes, object_id: str = ALICE) -> str:
    """An MCP-audience token from the test issuer (scope ``mcp.invoke``)."""
    return dev_issuer().mint(
        audience=cs.MCP_AUDIENCE,
        object_id=object_id,
        now=planes.clock.now,
        lifetime_seconds=MCP_LIFETIME,
        scopes=("mcp.invoke",),
    )
