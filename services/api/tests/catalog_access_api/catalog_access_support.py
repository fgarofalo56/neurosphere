"""A two-domain world for the catalog access route tests (synthetic ``contoso`` ids only).

FINANCE holds assets ``customers`` (pii, westeurope), ``claims`` (phi, eastus) and ``mystery``
(every sensitivity field null). OPERATIONS holds asset ``ledger`` (pii, northeurope). Edges:
fin-a1 writes customers, fin-a2 reads customers, ops-b1 reads customers (accessor in OPERATIONS),
fin-a1 reads claims, fin-a2 writes mystery, ops-b1 writes ledger. VIEWER reads FINANCE only.
"""

from __future__ import annotations

from typing import Any

from authz.authz_helpers import FINANCE, OPERATIONS  # pyright: ignore[reportMissingImports]
from neurosphere_contracts.catalog.v1.reads import ReadsRelation
from neurosphere_contracts.catalog.v1.writes import WritesRelation
from neurosphere_core.catalog.protocol import CatalogEdge
from ui_adapters_api.adapter_support import (  # pyright: ignore[reportMissingImports]
    World,
    agent_doc,
    agent_id,
    example,
    make_world,
)

__all__ = [
    "ACCESS",
    "DEPENDENTS",
    "REGION_GROUPS",
    "asset_doc",
    "asset_id",
    "build_world",
    "edge",
]

ACCESS = "/api/v1/catalog/access/query"
DEPENDENTS = "/api/v1/catalog/access/dependents"
REGION_GROUPS = "/api/v1/catalog/access/region-groups"
NS = "commercial:contoso"


def asset_id(name: str) -> str:
    return f"{NS}:foundry:grounding_source:{name}"


def asset_doc(name: str, domain: str, **patch: Any) -> dict[str, Any]:
    raw = example("grounding_source.sensitivity-residency.json")
    raw.update(
        id=asset_id(name),
        domain_id=domain,
        display_name=f"Asset {name}",
        version=1,
        etag="caller-etag",
        tags=[],
        environment="unknown",
    )
    raw.update(patch)
    return raw


def edge(name: str, relation: str, who: str, what: str, domain: str, **patch: Any) -> CatalogEdge:
    raw = example(f"{relation}.inferred.json")
    raw.update(
        id=f"{NS}:neurosphere:{relation}:{name}",
        source_id=agent_id(who),
        target_id=asset_id(what),
        domain_id=domain,
        version=1,
        etag="caller-etag",
    )
    raw.update(patch)
    return (ReadsRelation if relation == "reads" else WritesRelation).model_validate(raw)


def build_world() -> World:
    world = make_world()
    world.seed(
        agent_doc("fin-a1", FINANCE),
        agent_doc("fin-a2", FINANCE),
        agent_doc("ops-b1", OPERATIONS),
        asset_doc(
            "customers",
            FINANCE,
            contains_personal_data=True,
            sensitivity_categories=["pii"],
            residency_region="westeurope",
            classification="restricted",
        ),
        asset_doc(
            "claims",
            FINANCE,
            contains_personal_data=True,
            sensitivity_categories=["phi"],
            residency_region="eastus",
            classification="confidential",
        ),
        asset_doc(
            "mystery",
            FINANCE,
            contains_personal_data=None,
            sensitivity_categories=None,
            residency_region=None,
            classification="unknown",
        ),
        asset_doc(
            "ledger",
            OPERATIONS,
            contains_personal_data=True,
            sensitivity_categories=["pii"],
            residency_region="northeurope",
            classification="restricted",
        ),
    )
    world.seed_edges(
        edge("w-a1-customers", "writes", "fin-a1", "customers", FINANCE),
        edge("r-a2-customers", "reads", "fin-a2", "customers", FINANCE),
        edge("r-b1-customers", "reads", "ops-b1", "customers", FINANCE),
        edge("r-a1-claims", "reads", "fin-a1", "claims", FINANCE),
        edge("w-a2-mystery", "writes", "fin-a2", "mystery", FINANCE),
        edge("w-b1-ledger", "writes", "ops-b1", "ledger", OPERATIONS),
    )
    return world
