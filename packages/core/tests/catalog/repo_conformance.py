"""Shared conformance checks for every ``CatalogRepository`` implementation.

``test_repo.py`` runs them on the in-memory repository, ``tests/integration/catalog/
test_repo_cosmos.py`` on the Cosmos emulator. Each check takes ``(repo, ns)``: ``ns`` is a
unique customer segment so checks never see each other's documents in a shared container.
This module deliberately imports nothing from pytest fixtures; it is loaded by file path from
the integration suite.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
from neurosphere_contracts.catalog.v1.agent import Agent
from neurosphere_contracts.catalog.v1.alias import Alias
from neurosphere_contracts.catalog.v1.domain import Domain
from neurosphere_contracts.catalog.v1.edge_override import EdgeOverride
from neurosphere_contracts.catalog.v1.invokes import InvokesRelation
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.catalog import AliasKey, CatalogRepository
from neurosphere_core.catalog.protocol import (
    EdgeFilter,
    EdgeObservation,
    EntityFilter,
)
from neurosphere_core.catalog.repo.documents import is_canonical_id
from neurosphere_core.errors.taxonomy import ForbiddenError, InvalidSchemaError, StaleVersionError
from neurosphere_core.paging import PageRequest
from neurosphere_core.scope import IdentityScope

_SCHEMAS = Path(__file__).resolve().parents[3] / "contracts/schemas/catalog/v1"
_VALID = _SCHEMAS / "examples/valid"
ACTOR = "commercial:contoso:entra:person:psn_0123456789abcdef"

Check = Callable[[CatalogRepository, str], Awaitable[None]]


# --------------------------------------------------------------------------- builders


def dom(ns: str, name: str) -> str:
    return f"commercial:{ns}:neurosphere:domain:{name}"


def make_scope(
    ns: str,
    domains: list[str],
    *,
    customer: str | None = None,
    cloud: str = "commercial",
    auditor_for: list[str] | None = None,
    auditor_expires: str = "2099-01-01T00:00:00Z",
) -> IdentityScope:
    customer = customer or ns
    roles: list[dict[str, Any]] = [{"role": "viewer", "domain_ids": domains or [dom(ns, "x")]}]
    if auditor_for:
        roles.append(
            {"role": "security_auditor", "domain_ids": auditor_for, "expires_at": auditor_expires}
        )
    payload: dict[str, Any] = {
        "schema_version": "1.0.0",
        "cloud": cloud,
        "customer_id": customer,
        "principal": {
            "principal_id": f"{cloud}:{customer}:idp:person:p1",
            "principal_pseudonym": "p-0001",
            "principal_kind": "user",
        },
        "roles": roles,
        "allowed_domains": domains,
        "allowed_resources": [],
        "policy_version": "v1",
        "derived_at": "2026-01-01T00:00:00Z",
        "scope_hash": "sha256:" + hashlib.sha256(b"x").hexdigest(),
    }
    return IdentityScope._from_verified_contract(ContractScope.model_validate(payload))


def example(name: str) -> dict[str, Any]:
    return json.loads((_VALID / name).read_text(encoding="utf-8"))


def agent(ns: str, name: str, domain: str, **patch: Any) -> Agent:
    raw = example("agent.minimal-and-typical.json")
    raw.update(
        id=f"commercial:{ns}:foundry:agent:{name}",
        customer_id=ns,
        domain_id=dom(ns, domain),
        current_version_id=None,
        external_agent_id=None,
        version=1,
        etag="caller-etag",
        display_name=f"Agent {name}",
    )
    raw.update(patch)
    return Agent.model_validate(raw)


def domain_entity(ns: str, name: str) -> Domain:
    raw = example("domain.minimal-and-typical.json")
    raw.update(id=dom(ns, name), customer_id=ns, version=1, etag="caller-etag")
    return Domain.model_validate(raw)


def edge(ns: str, name: str, src: str, dst: str, domain: str, **patch: Any) -> InvokesRelation:
    raw = example("invokes.inferred.json")
    raw.update(
        id=f"commercial:{ns}:neurosphere:invokes:{name}",
        source_id=f"commercial:{ns}:foundry:agent:{src}",
        target_id=f"commercial:{ns}:foundry:agent:{dst}",
        customer_id=ns,
        domain_id=dom(ns, domain),
        version=1,
        etag="caller-etag",
    )
    raw.update(patch)
    return InvokesRelation.model_validate(raw)


def edge_id(ns: str, name: str) -> str:
    return f"commercial:{ns}:neurosphere:invokes:{name}"


def alias(ns: str, name: str, target: str, value: str, **patch: Any) -> Alias:
    raw = example("alias.external-id.json")
    raw.update(
        id=f"commercial:{ns}:neurosphere:alias:{name}",
        customer_id=ns,
        alias_value=value,
        canonical_id=f"commercial:{ns}:foundry:agent:{target}",
        etag="caller-etag",
    )
    raw.update(patch)
    return Alias.model_validate(raw)


def override(
    ns: str,
    name: str,
    edge_name: str,
    domain: str,
    *,
    decided_at: str,
    etag: str,
    version: int = 1,
    reason: str = "steward decision",
) -> EdgeOverride:
    raw = example("edge_override.reject.json")
    raw.update(
        id=f"commercial:{ns}:neurosphere:edge_override:{name}",
        edge_id=edge_id(ns, edge_name),
        relation_type="invokes",
        expected_edge_version=version,
        expected_edge_etag=etag,
        customer_id=ns,
        domain_id=dom(ns, domain),
        decided_at=decided_at,
        reason=reason,
        set_confidence=None,
    )
    return EdgeOverride.model_validate(raw)


def observation(
    ns: str, name: str, edge_name: str, domain: str, observed_at: str
) -> EdgeObservation:
    return EdgeObservation.model_validate(
        {
            "id": f"obs:{ns}-{name}",
            "edge_id": edge_id(ns, edge_name),
            "relation_type": "invokes",
            "cloud": "commercial",
            "customer_id": ns,
            "domain_id": dom(ns, domain),
            "observed_at": observed_at,
            "confidence": 0.5,
            "validity": {"valid_from": observed_at},
            "provenance": {
                "method": "trace_observation",
                "source_id": "appinsights",
                "recorded_at": observed_at,
            },
            "evidence_ids": [f"trace:{name}"],
            "security_evidence_ids": [],
        }
    )


def _ids(items: Any) -> list[str]:
    return [i.id for i in items]


# --------------------------------------------------------------------------- checks


async def check_entity_create_get_update(repo: CatalogRepository, ns: str) -> None:
    sa = make_scope(ns, [dom(ns, "a")])
    created = await repo.create_entity(sa, agent(ns, "c1", "a"))
    assert created.version.root == 1
    assert created.etag.root != "caller-etag"
    got = await repo.get_entity(sa, created.id)
    assert got is not None
    assert got == created
    with pytest.raises(InvalidSchemaError):
        await repo.create_entity(sa, agent(ns, "c1", "a"))

    updated = await repo.update_entity(
        sa, agent(ns, "c1", "a", display_name="Renamed"), created.etag.root
    )
    assert updated.version.root == 2
    assert updated.etag.root != created.etag.root
    assert updated.created_at == created.created_at
    with pytest.raises(InvalidSchemaError):
        await repo.update_entity(sa, agent(ns, "ghost", "a"), "whatever")
    sab = make_scope(ns, [dom(ns, "a"), dom(ns, "b")])
    with pytest.raises(InvalidSchemaError):  # domain_id is immutable
        await repo.update_entity(sab, agent(ns, "c1", "b"), updated.etag.root)

    deprecated = await repo.deprecate_entity(sa, created.id, (await _etag(repo, sa, created.id)))
    assert deprecated.lifecycle_status.root == "deprecated"
    assert (await repo.get_entity(sa, created.id)) is not None  # not deleted


async def _etag(repo: CatalogRepository, scope: IdentityScope, entity_id: str) -> str:
    got = await repo.get_entity(scope, entity_id)
    assert got is not None
    return got.etag.root


async def check_stale_etag(repo: CatalogRepository, ns: str) -> None:
    sa = make_scope(ns, [dom(ns, "a")])
    created = await repo.create_entity(sa, agent(ns, "s1", "a"))
    etag = created.etag.root
    first = await repo.update_entity(sa, agent(ns, "s1", "a", display_name="One"), etag)
    with pytest.raises(StaleVersionError) as stale:
        await repo.update_entity(sa, agent(ns, "s1", "a", display_name="Two"), etag)
    assert stale.value.code == "stale_version"
    with pytest.raises(StaleVersionError):
        await repo.deprecate_entity(sa, created.id, etag)
    current = await repo.get_entity(sa, created.id)
    assert current is not None
    assert isinstance(current, Agent)
    assert current.display_name.root == "One"
    assert current.etag == first.etag

    # Two truly concurrent edits that both read the same ETag: exactly one wins.
    base = (await repo.get_entity(sa, created.id)).etag.root  # type: ignore[union-attr]
    results = await asyncio.gather(
        repo.update_entity(sa, agent(ns, "s1", "a", display_name="A"), base),
        repo.update_entity(sa, agent(ns, "s1", "a", display_name="B"), base),
        return_exceptions=True,
    )
    wins = [r for r in results if not isinstance(r, BaseException)]
    losses = [r for r in results if isinstance(r, StaleVersionError)]
    assert len(wins) == 1
    assert len(losses) == 1


async def check_entity_scope_isolation(repo: CatalogRepository, ns: str) -> None:
    sa = make_scope(ns, [dom(ns, "a")])
    sb = make_scope(ns, [dom(ns, "b")])
    sab = make_scope(ns, [dom(ns, "a"), dom(ns, "b")])
    ent_a = await repo.create_entity(sa, agent(ns, "ia", "a"))
    ent_b = await repo.create_entity(sb, agent(ns, "ib", "b"))
    with pytest.raises(ForbiddenError):
        await repo.create_entity(sa, agent(ns, "bad", "b"))
    with pytest.raises(ForbiddenError):
        await repo.update_entity(sa, agent(ns, "ib", "b"), ent_b.etag.root)

    # cross-domain: out-of-scope reads look like missing ones
    assert await repo.get_entity(sb, ent_a.id) is None
    assert await repo.get_entity(sa, ent_b.id) is None
    page = await repo.list_entities(sa, EntityFilter(), PageRequest())
    assert _ids(page.items) == [ent_a.id]
    # a filter can narrow the scope, never widen it
    widened = await repo.list_entities(sa, EntityFilter(domain_ids=[dom(ns, "b")]), PageRequest())
    assert widened.items == ()
    both = await repo.list_entities(sab, EntityFilter(), PageRequest())
    assert sorted(_ids(both.items)) == sorted([ent_a.id, ent_b.id])
    with pytest.raises(InvalidSchemaError):
        await repo.deprecate_entity(sb, ent_a.id, ent_a.etag.root)

    # cross-customer: a scope for another customer that names this domain still sees nothing
    other = make_scope(ns, [dom(ns, "a")], customer=f"{ns}x")
    assert await repo.get_entity(other, ent_a.id) is None
    assert (await repo.list_entities(other, EntityFilter(), PageRequest())).items == ()
    # cross-cloud
    gov = make_scope(ns, [dom(ns, "a")], cloud="government")
    assert await repo.get_entity(gov, ent_a.id) is None
    # no domains at all
    nobody = make_scope(ns, [])
    assert await repo.get_entity(nobody, ent_a.id) is None
    assert (await repo.list_entities(nobody, EntityFilter(), PageRequest())).items == ()


async def check_list_entities_paging_and_filters(repo: CatalogRepository, ns: str) -> None:
    sa = make_scope(ns, [dom(ns, "a")])
    await repo.create_entity(sa, domain_entity(ns, "a"))
    for i in range(5):
        await repo.create_entity(sa, agent(ns, f"p{i}", "a"))
    first = await repo.list_entities(
        sa, EntityFilter(entity_types=["agent"]), PageRequest(page_size=2)
    )
    assert len(first.items) == 2
    assert first.next_cursor is not None
    second = await repo.list_entities(
        sa, EntityFilter(entity_types=["agent"]), PageRequest(page_size=2, cursor=first.next_cursor)
    )
    third = await repo.list_entities(
        sa,
        EntityFilter(entity_types=["agent"]),
        PageRequest(page_size=2, cursor=second.next_cursor),
    )
    assert third.next_cursor is None
    seen = _ids(first.items) + _ids(second.items) + _ids(third.items)
    assert seen == sorted(seen)
    assert len(set(seen)) == 5
    only_domains = await repo.list_entities(
        sa, EntityFilter(entity_types=["domain"]), PageRequest()
    )
    assert [e.entity_type for e in only_domains.items] == ["domain"]
    none_active = await repo.list_entities(
        sa, EntityFilter(lifecycle_statuses=["retired"]), PageRequest()
    )
    assert none_active.items == ()
    with pytest.raises(InvalidSchemaError):
        await repo.list_entities(sa, EntityFilter(), PageRequest(cursor="__4="))


async def check_alias_resolution(repo: CatalogRepository, ns: str) -> None:
    sa = make_scope(ns, [dom(ns, "a")])
    sb = make_scope(ns, [dom(ns, "b")])
    one = await repo.create_entity(sa, agent(ns, "al1", "a"))
    two = await repo.create_entity(sa, agent(ns, "al2", "a"))
    key = AliasKey(alias_source_id="foundry-eastus", alias_kind="external_id", alias_value="asst-1")

    stored = await repo.put_alias(sa, alias(ns, "x1", "al1", "asst-1"))
    assert stored.version.root == 1
    assert await repo.resolve_alias(sa, key) == one.id
    # idempotent for the same mapping (even under another alias document ID)
    again = await repo.put_alias(sa, alias(ns, "x1b", "al1", "asst-1"))
    assert again.canonical_id == one.id
    # a second canonical target for the same key is rejected
    with pytest.raises(InvalidSchemaError):
        await repo.put_alias(sa, alias(ns, "x2", "al2", "asst-1"))
    assert await repo.resolve_alias(sa, key) == one.id
    # missing key, and out of scope, resolve to None
    assert (
        await repo.resolve_alias(
            sa,
            AliasKey(
                alias_source_id="foundry-eastus", alias_kind="external_id", alias_value="nope"
            ),
        )
        is None
    )
    assert await repo.resolve_alias(sb, key) is None
    assert await repo.resolve_alias(make_scope(ns, [dom(ns, "a")], customer=f"{ns}x"), key) is None
    # targets that are out of scope or missing are not available to the writer
    with pytest.raises(ForbiddenError):
        await repo.put_alias(sb, alias(ns, "x3", "al1", "other"))
    with pytest.raises(ForbiddenError):
        await repo.put_alias(sa, alias(ns, "x4", "ghost", "other"))
    with pytest.raises(ForbiddenError):
        await repo.put_alias(
            make_scope(ns, [dom(ns, "a")], customer=f"{ns}x"), alias(ns, "x5", "al1", "o")
        )
    # entity_type must agree with the canonical ID's type segment
    with pytest.raises(InvalidSchemaError):
        await repo.put_alias(sa, alias(ns, "x6", "al1", "o2", entity_type="tool"))

    # retiring frees the key; the alias then resolves to the new target only
    with pytest.raises(StaleVersionError):
        await repo.put_alias(sa, alias(ns, "x1", "al1", "asst-1", status="retired"))
    retired = await repo.put_alias(
        sa, alias(ns, "x1", "al1", "asst-1", status="retired", etag=stored.etag.root)
    )
    assert retired.version.root == 2
    assert await repo.resolve_alias(sa, key) is None
    await repo.put_alias(sa, alias(ns, "x2", "al2", "asst-1"))
    assert await repo.resolve_alias(sa, key) == two.id


async def check_edges(repo: CatalogRepository, ns: str) -> None:
    sa = make_scope(ns, [dom(ns, "a")])
    sb = make_scope(ns, [dom(ns, "b")])
    for name in ("n1", "n2", "n3"):
        await repo.create_entity(sa, agent(ns, name, "a"))
    await repo.create_entity(sb, agent(ns, "nb", "b"))
    e12 = await repo.put_edge(sa, edge(ns, "e12", "n1", "n2", "a"), None)
    await repo.put_edge(sa, edge(ns, "e13", "n1", "n3", "a", status="asserted"), None)
    await repo.put_edge(sa, edge(ns, "e31", "n3", "n1", "a"), None)
    # a cross-domain edge (domain b) touching an in-scope node
    await repo.put_edge(sb, edge(ns, "eb", "nb", "n1", "b"), None)

    assert e12.version.root == 1
    assert await repo.get_edge(sa, e12.id) == e12
    assert await repo.get_edge(sb, e12.id) is None  # cross-domain
    assert await repo.get_edge(make_scope(ns, [dom(ns, "a")], customer=f"{ns}x"), e12.id) is None
    n1 = f"commercial:{ns}:foundry:agent:n1"
    out = await repo.list_edges_by_node(sa, n1, "out", EdgeFilter(), PageRequest())
    assert _ids(out.items) == [edge_id(ns, "e12"), edge_id(ns, "e13")]
    inn = await repo.list_edges_by_node(sa, n1, "in", EdgeFilter(), PageRequest())
    assert _ids(inn.items) == [edge_id(ns, "e31")]  # the domain-b edge is excluded
    both = await repo.list_edges_by_node(sa, n1, "both", EdgeFilter(), PageRequest())
    assert len(both.items) == 3
    asserted = await repo.list_edges_by_node(
        sa, n1, "out", EdgeFilter(statuses=["asserted"]), PageRequest()
    )
    assert _ids(asserted.items) == [edge_id(ns, "e13")]
    typed = await repo.list_edges_by_node(
        sa, n1, "both", EdgeFilter(relation_types=["reads"]), PageRequest()
    )
    assert typed.items == ()
    small = await repo.list_edges_by_node(sa, n1, "both", EdgeFilter(), PageRequest(page_size=2))
    assert len(small.items) == 2
    assert small.next_cursor is not None
    # node outside the scope: empty page, whatever edges exist
    assert (await repo.list_edges_by_node(sb, n1, "both", EdgeFilter(), PageRequest())).items == ()

    # ETag rules
    with pytest.raises(StaleVersionError):
        await repo.put_edge(sa, edge(ns, "e12", "n1", "n2", "a"), None)  # create existing
    with pytest.raises(StaleVersionError):
        await repo.put_edge(sa, edge(ns, "e12", "n1", "n2", "a"), "stale")
    with pytest.raises(InvalidSchemaError):
        await repo.put_edge(sa, edge(ns, "ghost", "n1", "n2", "a"), "x")
    with pytest.raises(ForbiddenError):
        await repo.put_edge(sa, edge(ns, "ef", "n1", "n2", "b"), None)

    # evidence is append-only; an inferred edge needs evidence
    grown = edge(
        ns,
        "e12",
        "n1",
        "n2",
        "a",
        evidence_ids=["trace:4bf92f3577b34da6a3ce929d0e0e4736", "audit:sec-0042", "trace:new"],
    )
    v2 = await repo.put_edge(sa, grown, e12.etag.root)
    assert v2.version.root == 2
    assert len(v2.evidence_ids) == 3
    with pytest.raises(InvalidSchemaError):
        await repo.put_edge(
            sa,
            edge(ns, "e12", "n1", "n2", "a", evidence_ids=["trace:new"], security_evidence_ids=[]),
            v2.etag.root,
        )
    with pytest.raises(InvalidSchemaError):
        await repo.put_edge(
            sa, edge(ns, "bare", "n1", "n2", "a", evidence_ids=[], security_evidence_ids=[]), None
        )
    with pytest.raises(InvalidSchemaError):
        await repo.get_edge(sa, "commercial:contoso:foundry:agent:abc\n")


async def check_observations(repo: CatalogRepository, ns: str) -> None:
    sa = make_scope(ns, [dom(ns, "a")])
    sab = make_scope(ns, [dom(ns, "a"), dom(ns, "b")], auditor_for=[dom(ns, "b")])
    auditor = make_scope(ns, [dom(ns, "a")], auditor_for=[dom(ns, "a")])
    expired = make_scope(
        ns, [dom(ns, "a")], auditor_for=[dom(ns, "a")], auditor_expires="2020-01-01T00:00:00Z"
    )
    for name in ("o1", "o2"):
        await repo.create_entity(sa, agent(ns, name, "a"))
    await repo.put_edge(sa, edge(ns, "eo", "o1", "o2", "a"), None)
    times = {
        "t1": "2026-10-01T00:00:00Z",
        "t2": "2026-10-05T00:00:00.5Z",
        "t3": "2026-10-05T00:00:00Z",
        "t4": "2026-10-09T12:00:00Z",
    }
    for name, at in times.items():
        assert await repo.record_observation(sa, observation(ns, name, "eo", "a", at)) is True
    assert await repo.record_observation(sa, observation(ns, "t1", "eo", "a", times["t1"])) is False
    with pytest.raises(ForbiddenError):
        await repo.record_observation(
            make_scope(ns, [dom(ns, "b")]), observation(ns, "zz", "eo", "a", times["t1"])
        )

    eid = edge_id(ns, "eo")
    for denied in (sa, sab, expired):
        with pytest.raises(ForbiddenError):
            await repo.list_observations(denied, eid, PageRequest())
    newest_first = await repo.list_observations(auditor, eid, PageRequest())
    assert [o.id for o in newest_first.items] == [
        f"obs:{ns}-t4",
        f"obs:{ns}-t2",
        f"obs:{ns}-t3",
        f"obs:{ns}-t1",
    ]
    paged = await repo.list_observations(auditor, eid, PageRequest(page_size=3))
    assert len(paged.items) == 3
    assert paged.next_cursor is not None
    rest = await repo.list_observations(
        auditor, eid, PageRequest(page_size=3, cursor=paged.next_cursor)
    )
    assert [o.id for o in rest.items] == [f"obs:{ns}-t1"]
    other_customer = make_scope(ns, [dom(ns, "a")], customer=f"{ns}x", auditor_for=[dom(ns, "a")])
    assert (await repo.list_observations(other_customer, eid, PageRequest())).items == ()
    # raw telemetry is never stored: the observation carries evidence IDs only
    assert set(EdgeObservation.model_fields) >= {"evidence_ids"}
    assert not {"payload", "body", "prompt", "completion"} & set(EdgeObservation.model_fields)


async def check_overrides(repo: CatalogRepository, ns: str) -> None:
    sa = make_scope(ns, [dom(ns, "a")])
    sb = make_scope(ns, [dom(ns, "b")])
    for name in ("v1", "v2", "v3"):
        await repo.create_entity(sa, agent(ns, name, "a"))
    e1 = await repo.put_edge(sa, edge(ns, "ov1", "v1", "v2", "a"), None)
    e2 = await repo.put_edge(sa, edge(ns, "ov2", "v2", "v3", "a"), None)
    etag = e1.etag.root

    late = override(ns, "late", "ov1", "a", decided_at="2026-10-09T00:00:00Z", etag=etag)
    early = override(ns, "early", "ov1", "a", decided_at="2026-10-02T00:00:00Z", etag=etag)
    await repo.put_override(sa, late)
    await repo.put_override(sa, early)
    assert (await repo.put_override(sa, late)) == late  # idempotent
    with pytest.raises(InvalidSchemaError):  # immutable: same ID, different decision
        await repo.put_override(
            sa,
            override(
                ns,
                "late",
                "ov1",
                "a",
                decided_at="2026-10-09T00:00:00Z",
                etag=etag,
                reason="rewritten",
            ),
        )
    with pytest.raises(StaleVersionError):
        await repo.put_override(
            sa, override(ns, "stale", "ov1", "a", decided_at="2026-10-03T00:00:00Z", etag="old")
        )
    with pytest.raises(StaleVersionError):
        await repo.put_override(
            sa,
            override(
                ns, "stale2", "ov1", "a", decided_at="2026-10-03T00:00:00Z", etag=etag, version=9
            ),
        )
    with pytest.raises(ForbiddenError):
        await repo.put_override(
            sb, override(ns, "fb", "ov1", "a", decided_at="2026-10-03T00:00:00Z", etag=etag)
        )
    with pytest.raises(InvalidSchemaError):
        await repo.put_override(
            sa, override(ns, "none", "ghost", "a", decided_at="2026-10-03T00:00:00Z", etag=etag)
        )

    eid = edge_id(ns, "ov1")
    listed = await repo.list_overrides(sa, eid)
    assert [o.id for o in listed] == [early.id, late.id]  # decision order
    assert await repo.list_overrides(sb, eid) == ()
    batch = await repo.list_overrides_for_edges(sa, [eid, edge_id(ns, "ov2"), edge_id(ns, "nope")])
    assert set(batch) == {eid, e2.id}
    assert [o.id for o in batch[eid]] == [early.id, late.id]
    assert batch[e2.id] == ()
    assert await repo.list_overrides_for_edges(sb, [eid]) == {}
    too_many = [edge_id(ns, f"x{i}") for i in range(501)]
    with pytest.raises(InvalidSchemaError):
        await repo.list_overrides_for_edges(sa, too_many)


async def check_scope_required(repo: CatalogRepository, ns: str) -> None:
    sa = make_scope(ns, [dom(ns, "a")])
    ent = agent(ns, "r1", "a")
    key = AliasKey(alias_source_id="s", alias_kind="external_id", alias_value="v")
    eid = edge_id(ns, "r")
    contract_scope = sa.to_contract()  # the output-only contract model is not a scope holder
    bads: list[Any] = [None, object(), contract_scope, "scope"]
    for bad in bads:
        calls = [
            repo.get_entity(bad, ent.id),  # type: ignore[arg-type]
            repo.create_entity(bad, ent),  # type: ignore[arg-type]
            repo.update_entity(bad, ent, "e"),  # type: ignore[arg-type]
            repo.deprecate_entity(bad, ent.id, "e"),  # type: ignore[arg-type]
            repo.list_entities(bad, EntityFilter(), PageRequest()),  # type: ignore[arg-type]
            repo.put_alias(bad, alias(ns, "r", "r1", "v")),  # type: ignore[arg-type]
            repo.resolve_alias(bad, key),  # type: ignore[arg-type]
            repo.get_edge(bad, eid),  # type: ignore[arg-type]
            repo.put_edge(bad, edge(ns, "r", "r1", "r2", "a"), None),  # type: ignore[arg-type]
            repo.list_edges_by_node(bad, ent.id, "both", EdgeFilter(), PageRequest()),  # type: ignore[arg-type]
            repo.record_observation(bad, observation(ns, "r", "r", "a", "2026-10-01T00:00:00Z")),  # type: ignore[arg-type]
            repo.list_observations(bad, eid, PageRequest()),  # type: ignore[arg-type]
            repo.put_override(  # type: ignore[arg-type]
                bad, override(ns, "r", "r", "a", decided_at="2026-10-01T00:00:00Z", etag="e")
            ),
            repo.list_overrides(bad, eid),  # type: ignore[arg-type]
            repo.list_overrides_for_edges(bad, [eid]),  # type: ignore[arg-type]
        ]
        for call in calls:
            with pytest.raises(TypeError):
                await call


async def check_id_grammar(repo: CatalogRepository, ns: str) -> None:
    corpus = json.loads((_SCHEMAS / "id-corpus.json").read_text(encoding="utf-8"))
    for value in corpus["valid"]:
        assert is_canonical_id(value), value
    for entry in corpus["invalid"]:
        assert not is_canonical_id(entry["value"]), entry["reason"]
    sa = make_scope(ns, [dom(ns, "a")])
    for entry in corpus["invalid"]:
        with pytest.raises(InvalidSchemaError):
            await repo.get_entity(sa, entry["value"])
    # an entity whose ID disagrees with its own cloud or customer is refused
    with pytest.raises(InvalidSchemaError):
        await repo.create_entity(sa, agent(ns, "t1", "a", id=f"government:{ns}:foundry:agent:t1"))
    with pytest.raises(InvalidSchemaError):
        await repo.create_entity(
            sa, agent(ns, "t2", "a", id="commercial:someone-else:foundry:agent:t2")
        )
    # an ID with a slash (legal in the grammar) round-trips
    slashy = agent(ns, "t3/v1", "a")
    created = await repo.create_entity(sa, slashy)
    assert (await repo.get_entity(sa, created.id)) == created


CHECKS: dict[str, Check] = {
    "entity_create_get_update": check_entity_create_get_update,
    "stale_etag": check_stale_etag,
    "entity_scope_isolation": check_entity_scope_isolation,
    "list_entities_paging_and_filters": check_list_entities_paging_and_filters,
    "alias_resolution": check_alias_resolution,
    "edges": check_edges,
    "observations": check_observations,
    "overrides": check_overrides,
    "scope_required": check_scope_required,
    "id_grammar": check_id_grammar,
}
