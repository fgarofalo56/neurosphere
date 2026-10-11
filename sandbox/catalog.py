"""Catalog documents (entities and relations) built from the PRP-01 contract models.

Every record is validated by constructing the generated Pydantic model (``extra="forbid"``,
strict types, patterns) and is then dumped; there are no ad hoc dicts on the output path.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from typing import Any

from neurosphere_contracts.catalog.v1 import (
    agent,
    agent_version,
    delegates_to,
    domain,
    grounded_by,
    grounding_source,
    invokes,
    model_deployment,
    owned_by,
    owner,
    person,
    tool,
    uses_model,
)

from sandbox.config import PRICE_EFFECTIVE_DATE, PRICE_VERSION, REGIONS, SCHEMA_VERSION
from sandbox.ids import digest_int, fmt_ts_s, pseudonym
from sandbox.traces import trace_hex
from sandbox.world import DAY_MS, World

Doc = dict[str, Any]

_ENTITY_STATUSES = ("active", "active", "active", "active", "deprecated")


def _dump(model: Any) -> Doc:
    result: Doc = model.model_dump(mode="json", exclude_none=True)
    return result


def _created(world: World, label: str) -> str:
    back_days = 30 + digest_int(f"{world.seed}:created:{label}") % 270
    return fmt_ts_s(world.epoch_ms - back_days * DAY_MS)


def _etag(label: str) -> str:
    return '"sbx-' + hashlib.sha256(label.encode("utf-8")).hexdigest()[:16] + '"'


def _common(world: World, ident: str, entity_type: str, status: str = "active") -> Doc:
    created = _created(world, ident)
    return {
        "schema_version": SCHEMA_VERSION,
        "id": ident,
        "entity_type": entity_type,
        "version": 1,
        "etag": _etag(ident),
        "lifecycle_status": status,
        "created_at": created,
        "updated_at": created,
        "cloud": world.cloud,
        "customer_id": world.customer,
    }


def iter_domains(world: World) -> Iterator[Doc]:
    for d in world.domains:
        doc = _common(world, world.domain_id(d.idx), "domain")
        doc.update(display_name=d.name, classification="internal")
        yield _dump(domain.Domain.model_validate(doc))


def iter_persons(world: World) -> Iterator[Doc]:
    for n in range(world.person_count):
        psn = pseudonym(world.seed, n)
        ident = world.cid("person", psn)
        doc = _common(world, ident, "person")
        doc.pop("lifecycle_status")
        doc.update(
            lifecycle_status="active",
            principal_pseudonym=psn,
            pseudonym_scheme="blake2b-seeded.v1",
            principal_kind="human",
            domain_id=world.domain_id(n % len(world.domains)),
        )
        yield _dump(person.Person.model_validate(doc))


def iter_owners(world: World) -> Iterator[Doc]:
    for o in world.owners:
        doc = _common(world, world.owner_id(o.idx), "owner")
        doc.update(domain_id=world.domain_id(o.domain), owner_kind=o.kind)
        if o.kind == "person" and o.person is not None:
            # A person-kind owner carries no display name; it points at a pseudonymous Person.
            doc["principal_id"] = world.cid("person", pseudonym(world.seed, o.person))
        else:
            dom = world.domains[o.domain].name
            label = {"team": "Team", "group": "Group", "service_principal": "Service Principal"}
            doc["display_name"] = f"{dom} {label[o.kind]} {o.idx + 1:03d}"
        yield _dump(owner.Owner.model_validate(doc))


def iter_models(world: World) -> Iterator[Doc]:
    region = REGIONS[world.cloud]
    # Estate-wide shared deployments belong to the first domain.
    for i, m in enumerate(world.models):
        doc = _common(world, world.model_id(i), "model_deployment")
        doc.update(
            domain_id=world.domain_id(0),
            provider=m.provider,
            model_name=m.model_name,
            model_version=m.model_version,
            deployment_name=f"{m.slug}-sbx",
            modalities=list(m.modalities),
            context_window_tokens=128_000,
            max_output_tokens=8_192,
            supports_tool_calling="embedding" not in m.modalities,
            region=region,
            sku="Standard",
            price_reference={
                "price_version": PRICE_VERSION,
                "price_effective_date": PRICE_EFFECTIVE_DATE,
            },
        )
        yield _dump(model_deployment.ModelDeployment.model_validate(doc))


def iter_sources(world: World) -> Iterator[Doc]:
    for s in world.sources:
        dom = max(s.domain, 0)
        doc = _common(world, world.source_id(s.idx), "grounding_source")
        label = "Shared" if s.domain < 0 else world.domains[s.domain].name
        doc.update(
            domain_id=world.domain_id(dom),
            display_name=f"{label} source {s.idx + 1:04d}",
            asset_kind=s.kind,
            source_id=f"sandbox-{s.kind.replace('_', '-')}",
            contains_personal_data=s.has_personal_data,
        )
        yield _dump(grounding_source.GroundingSource.model_validate(doc))


def iter_tools(world: World) -> Iterator[Doc]:
    for t in world.tools:
        doc = _common(world, world.tool_id(t.idx), "tool")
        doc.update(
            domain_id=world.domain_id(t.domain),
            display_name=f"{world.domains[t.domain].name} tool {t.idx + 1:04d}",
            tool_kind=t.kind,
            side_effects=t.side_effects,
            source_id="sandbox-registry",
        )
        yield _dump(tool.Tool.model_validate(doc))


def iter_agents(world: World) -> Iterator[Doc]:
    for a in world.agents:
        status = (
            "active" if a.unused else _ENTITY_STATUSES[digest_int(f"{world.seed}:st:{a.idx}") % 5]
        )
        doc = _common(world, world.agent_id(a.idx), "agent", status)
        doc.update(
            domain_id=world.domain_id(a.domain),
            display_name=a.name,
            agent_kind=a.kind,
            platform="foundry",
            source_id="sandbox-foundry",
            external_agent_id=f"ext-a-{a.idx:06d}",
            current_version_id=world.agent_version_id(a.idx, a.versions),
            residency_region=REGIONS[world.cloud],
        )
        yield _dump(agent.Agent.model_validate(doc))


def iter_agent_versions(world: World) -> Iterator[Doc]:
    for a in world.agents:
        for v in range(1, a.versions + 1):
            ident = world.agent_version_id(a.idx, v)
            doc = _common(world, ident, "agent_version", "active" if v == a.versions else "retired")
            doc.update(
                domain_id=world.domain_id(a.domain),
                agent_id=world.agent_id(a.idx),
                version_label=f"{v}.0.0",
                released_at=_created(world, ident),
                config_hash="sha256:" + hashlib.sha256(ident.encode("utf-8")).hexdigest(),
            )
            yield _dump(agent_version.AgentVersion.model_validate(doc))


class _EdgeIds:
    def __init__(self, world: World) -> None:
        self.world = world
        self.n = 0

    def next(self, relation: str) -> str:
        self.n += 1
        return self.world.cid(relation, f"e-{self.n:07d}")


def _edge(
    world: World,
    ids: _EdgeIds,
    relation: str,
    source: str,
    target: str,
    domain_idx: int,
    *,
    evidence: str | None,
    confidence: float,
) -> Doc:
    inferred = evidence is not None
    start = fmt_ts_s(world.epoch_ms)
    end = fmt_ts_s(world.end_ms())
    provenance: Doc = {
        "method": "trace_observation" if inferred else "declared",
        "source_id": "sandbox-gateway" if inferred else "sandbox-foundry",
        "recorded_at": start,
    }
    if inferred:
        provenance["inference_version"] = "rules-1.0"
    ident = ids.next(relation)
    return {
        "schema_version": SCHEMA_VERSION,
        "id": ident,
        "relation_type": relation,
        "version": 1,
        "etag": _etag(ident),
        "source_id": source,
        "target_id": target,
        "cloud": world.cloud,
        "customer_id": world.customer,
        "domain_id": world.domain_id(domain_idx),
        "provenance": provenance,
        "evidence_ids": [f"trace:{evidence}"] if inferred else [],
        "security_evidence_ids": [],
        "confidence": float(confidence),
        "first_observed": start,
        "last_observed": end,
        "validity": {"valid_from": start},
        "status": "inferred" if inferred else "asserted",
        "lock": {"locked": False},
        "created_at": start,
        "updated_at": end,
    }


_RELATION_MODELS: dict[str, Any] = {
    "invokes": invokes.InvokesRelation,
    "delegates_to": delegates_to.DelegatesToRelation,
    "uses_model": uses_model.UsesModelRelation,
    "grounded_by": grounded_by.GroundedByRelation,
    "owned_by": owned_by.OwnedByRelation,
}


def iter_relations(world: World) -> Iterator[Doc]:
    """Declared (asserted) and inferred (trace-observed) relations, one stream.

    Inferred edges cite the first trace of the agent (day 0, index 0), which the trace
    generator forces to exercise every undeclared tool, source and delegation.
    """
    ids = _EdgeIds(world)

    def emit(relation: str, doc: Doc) -> Doc:
        return _dump(_RELATION_MODELS[relation].model_validate(doc))

    for a in world.agents:
        src = world.agent_id(a.idx)
        evidence = trace_hex(world.seed, a.idx, 0, 0)
        yield emit(
            "owned_by",
            _edge(
                world,
                ids,
                "owned_by",
                src,
                world.owner_id(a.owner),
                a.domain,
                evidence=None,
                confidence=1.0,
            ),
        )
        yield emit(
            "uses_model",
            _edge(
                world,
                ids,
                "uses_model",
                src,
                world.model_id(a.model),
                a.domain,
                evidence=None,
                confidence=1.0,
            ),
        )
        for t in a.tools:
            yield emit(
                "invokes",
                _edge(
                    world,
                    ids,
                    "invokes",
                    src,
                    world.tool_id(t),
                    a.domain,
                    evidence=None,
                    confidence=1.0,
                ),
            )
        for s in a.sources:
            yield emit(
                "grounded_by",
                _edge(
                    world,
                    ids,
                    "grounded_by",
                    src,
                    world.source_id(s),
                    a.domain,
                    evidence=None,
                    confidence=1.0,
                ),
            )
        for c in a.declared_children:
            yield emit(
                "delegates_to",
                _edge(
                    world,
                    ids,
                    "delegates_to",
                    src,
                    world.agent_id(c),
                    a.domain,
                    evidence=None,
                    confidence=1.0,
                ),
            )
        if a.unused:
            continue  # nothing is observed for an unused agent, so nothing is inferred
        conf = 0.6 + (digest_int(f"{world.seed}:conf:{a.idx}") % 35) / 100
        if a.extra_tool is not None:
            yield emit(
                "invokes",
                _edge(
                    world,
                    ids,
                    "invokes",
                    src,
                    world.tool_id(a.extra_tool),
                    a.domain,
                    evidence=evidence,
                    confidence=conf,
                ),
            )
        if a.extra_source is not None:
            yield emit(
                "grounded_by",
                _edge(
                    world,
                    ids,
                    "grounded_by",
                    src,
                    world.source_id(a.extra_source),
                    a.domain,
                    evidence=evidence,
                    confidence=conf,
                ),
            )
        for c in a.children:
            if c not in a.declared_children:
                yield emit(
                    "delegates_to",
                    _edge(
                        world,
                        ids,
                        "delegates_to",
                        src,
                        world.agent_id(c),
                        a.domain,
                        evidence=evidence,
                        confidence=conf,
                    ),
                )
