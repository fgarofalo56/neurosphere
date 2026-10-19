"""Test support: generate sandbox data, load it into the in-memory catalog, build scopes.

Writing into the in-memory repository happens HERE (test setup) only; the package under test
never holds a write handle. No network, no wall clock for the data (fixed seed and epoch).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from neurosphere_contracts.recommendations.v1.recommendation import (
    Recommendation,
    TimeRange,
)
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.catalog.graph import RepositoryGraphQuery
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.catalog.repo.documents import EDGE_MODELS, ENTITY_MODELS
from neurosphere_core.scope import IdentityScope

from sandbox.config import PROFILES, BadEventRates, GenerateConfig
from sandbox.generate import generate

REPO_ROOT = Path(__file__).resolve().parents[6]
SEED = 7
PROFILE_NAME = "custom (agents=400, domains=8, days=3, traces/agent/day=0.1, duplicate_pairs=8)"
ENTITY_FILES = (
    "domains.ndjson",
    "owners.ndjson",
    "model_deployments.ndjson",
    "grounding_sources.ndjson",
    "tools.ndjson",
    "agents.ndjson",
)
CREATED_AT = "2026-10-19T12:00:00Z"


class NoSearch:
    """``GraphQuery.neighbors`` never searches; the job must not either."""

    async def search(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("the duplicate job must not use search")


def generate_sandbox(out: Path, *, seed: int = SEED) -> None:
    profile = replace(
        PROFILES["custom"],
        agents=400,
        domains=8,
        days=3,
        traces_per_agent_day=0.1,
        duplicate_pairs=8,
        cost_spikes=1,
        latency_regressions=1,
        unused_agents=2,
    )
    profile.validate()
    cfg = GenerateConfig(seed=seed, profile=profile, cloud="commercial", rates=BadEventRates())
    generate(cfg, out)


def read_ndjson(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def make_scope(
    domains: list[str], *, customer: str = "synthco", cloud: str = "commercial"
) -> IdentityScope:
    payload: dict[str, Any] = {
        "schema_version": "1.0.0",
        "cloud": cloud,
        "customer_id": customer,
        "principal": {
            "principal_id": f"{cloud}:{customer}:idp:person:p1",
            "principal_pseudonym": "p-0001",
            "principal_kind": "user",
        },
        "roles": [{"role": "viewer", "domain_ids": domains}],
        "allowed_domains": domains,
        "allowed_resources": [],
        "policy_version": "v1",
        "derived_at": "2026-01-01T00:00:00Z",
        "scope_hash": "sha256:" + hashlib.sha256(b"x").hexdigest(),
    }
    return IdentityScope._from_verified_contract(ContractScope.model_validate(payload))


class ReadOnlyGraph:
    """Exposes ``neighbors`` ONLY (anything else is an AttributeError) and records requests."""

    def __init__(self, inner: RepositoryGraphQuery) -> None:
        self._inner = inner
        self.requests: list[Any] = []

    async def neighbors(self, scope: IdentityScope, request: Any) -> Any:
        self.requests.append(request)
        return await self._inner.neighbors(scope, request)


class ReadOnlyLister:
    """Exposes ``list_entities`` ONLY and records the filters it was asked with."""

    def __init__(self, inner: InMemoryCatalogRepository) -> None:
        self._inner = inner
        self.filters: list[Any] = []

    async def list_entities(self, scope: IdentityScope, flt: Any, page: Any) -> Any:
        self.filters.append(flt)
        return await self._inner.list_entities(scope, flt, page)


def snapshot(repo: InMemoryCatalogRepository) -> str:
    """Stable text of every stored document (used to prove a run wrote nothing)."""
    docs = repo._backend._docs  # type: ignore[attr-defined]
    return json.dumps(
        sorted(((repr(k), v) for k, v in docs.items()), key=lambda kv: kv[0]), default=str
    )


def pair_of(rec: Recommendation) -> frozenset[str]:
    return frozenset(s.root for s in rec.subject_ids)


@dataclass
class Estate:
    repo: InMemoryCatalogRepository
    graph: RepositoryGraphQuery
    domain_ids: list[str]
    anomalies: list[dict[str, Any]]
    window: TimeRange
    source_dir: Path

    @property
    def duplicate_pairs(self) -> set[frozenset[str]]:
        return {
            frozenset(a["affected_ids"])
            for a in self.anomalies
            if a["type"] == "duplicate_agent_candidates"
        }


async def load_estate(data_dir: Path, *, edge_filter: Any = None) -> Estate:
    """Load sandbox output into a fresh in-memory catalog (entities first, then relations)."""
    domains = read_ndjson(data_dir / "domains.ndjson")
    domain_ids = sorted(d["id"] for d in domains)
    loader = make_scope(domain_ids)
    repo = InMemoryCatalogRepository()
    for name in ENTITY_FILES:
        for doc in read_ndjson(data_dir / name):
            model = ENTITY_MODELS[doc["entity_type"]].model_validate(doc)
            await repo.create_entity(loader, model)  # type: ignore[arg-type]
    for doc in read_ndjson(data_dir / "relations.ndjson"):
        if edge_filter is not None and not edge_filter(doc):
            continue
        edge = EDGE_MODELS[doc["relation_type"]].model_validate(doc)
        await repo.put_edge(loader, edge, None)  # type: ignore[arg-type]
    manifest = json.loads((data_dir / "anomaly-manifest.json").read_text(encoding="utf-8"))
    dup = next(a for a in manifest["anomalies"] if a["type"] == "duplicate_agent_candidates")
    window = TimeRange.model_validate(
        {"start": dup["window"]["start"], "end": dup["window"]["end"]}
    )
    return Estate(
        repo=repo,
        graph=RepositoryGraphQuery(repo, NoSearch()),  # type: ignore[arg-type]
        domain_ids=domain_ids,
        anomalies=manifest["anomalies"],
        window=window,
        source_dir=data_dir,
    )
