"""World builders for the PRP-74 item 4 tests: the PRP-06 authz harness, the in-memory catalog
repository and catalog documents (agents, model deployments, invokes edges).

Import it with ``sys.path`` pointing at this directory (each test file does that), so it works
with or without an ``__init__.py`` here and from ``services/api/tests/realtime``.
"""

import json
import sys
from pathlib import Path
from typing import Any

_API_TESTS = Path(__file__).resolve().parents[1]
if str(_API_TESTS) not in sys.path:
    sys.path.insert(0, str(_API_TESTS))

from authz.authz_helpers import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    ALICE,
    BOB,
    FINANCE,
    NOBODY,
    OPERATIONS,
    Harness,
    harness,
    policy,
    role,
)
from neurosphere_contracts.catalog.v1.invokes import InvokesRelation  # noqa: E402
from neurosphere_core.auth.scope import PrincipalPolicy, Role  # noqa: E402
from neurosphere_core.catalog.repo import InMemoryCatalogRepository  # noqa: E402
from neurosphere_core.catalog.repo.documents import dump, parse_entity  # noqa: E402
from neurosphere_core.scope import IdentityScope  # noqa: E402

__all__ = [
    "ALICE",
    "BOB",
    "FINANCE",
    "NS",
    "OPERATIONS",
    "STEWARD",
    "agent_doc",
    "agent_id",
    "harness",
    "make_edge",
    "model_doc",
    "policies",
    "retag",
    "retire",
    "scope_of",
    "seed",
    "seed_edges",
]

NS = "commercial:contoso"
STEWARD = NOBODY
_EXAMPLES = Path(__file__).resolve().parents[4] / "packages/contracts/schemas/catalog/v1/examples"


def policies() -> tuple[PrincipalPolicy, ...]:
    """Alice reads Finance and Operations, Bob only Finance, the steward writes both."""
    return (
        policy(ALICE, role(Role.VIEWER, FINANCE, OPERATIONS)),
        policy(BOB, role(Role.VIEWER, FINANCE)),
        policy(STEWARD, role(Role.DOMAIN_STEWARD, FINANCE, OPERATIONS)),
    )


def _example(name: str) -> dict[str, Any]:
    return json.loads((_EXAMPLES / "valid" / name).read_text(encoding="utf-8"))


def agent_id(name: str) -> str:
    return f"{NS}:foundry:agent:{name}"


def agent_doc(name: str, domain: str = FINANCE) -> dict[str, Any]:
    raw = _example("agent.minimal-and-typical.json")
    raw.update(
        id=agent_id(name),
        domain_id=domain,
        current_version_id=None,
        external_agent_id=None,
        display_name=f"Agent {name}",
        attributes=None,
    )
    return raw


def model_doc(
    name: str,
    domain: str = FINANCE,
    *,
    provider: str = "azure_openai",
    model_name: str = "gpt-4o",
) -> dict[str, Any]:
    raw = _example("model_deployment.minimal-and-typical.json")
    raw.update(
        id=f"{NS}:foundry:model_deployment:{name}",
        domain_id=domain,
        deployment_name=name,
        provider=provider,
        model_name=model_name,
    )
    return raw


def make_edge(name: str, source: str, target: str, domain: str = FINANCE) -> InvokesRelation:
    raw = _example("invokes.inferred.json")
    raw.update(
        id=f"{NS}:neurosphere:invokes:{name}",
        source_id=source,
        target_id=target,
        domain_id=domain,
        version=1,
        etag="caller-etag",
    )
    return InvokesRelation.model_validate(raw)


async def scope_of(h: Harness, who: str) -> IdentityScope:
    claims = await h.validator.authenticate(h.auth(who)["Authorization"])
    return (await h.deriver.derive(claims)).scope


async def seed(
    repo: InMemoryCatalogRepository, scope: IdentityScope, *docs: dict[str, Any]
) -> None:
    for doc in docs:
        await repo.create_entity(scope, parse_entity(doc))


async def seed_edges(
    repo: InMemoryCatalogRepository, scope: IdentityScope, *edges: InvokesRelation
) -> None:
    for edge in edges:
        await repo.put_edge(scope, edge, None)


async def retag(
    repo: InMemoryCatalogRepository, scope: IdentityScope, entity_id: str, tag: str
) -> None:
    """Rewrite an entity with one more tag: the repository bumps ``version`` by one."""
    current = await repo.get_entity(scope, entity_id)
    assert current is not None
    doc = dump(current)
    doc["tags"] = [*(doc.get("tags") or []), tag]
    await repo.update_entity(scope, parse_entity(doc), current.etag.root)


async def retire(repo: InMemoryCatalogRepository, scope: IdentityScope, entity_id: str) -> None:
    """Retired entities leave the viewport scan: the node (and its edges) disappear."""
    current = await repo.get_entity(scope, entity_id)
    assert current is not None
    doc = dump(current)
    doc["lifecycle_status"] = "retired"
    await repo.update_entity(scope, parse_entity(doc), current.etag.root)
