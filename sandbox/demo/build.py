"""Build the curated demo world (PRP-71 item 1) as contract-valid catalog documents.

The entities and the per-agent relationship lists live in ``sandbox/demo/data/*.json`` (hand
written, readable, reviewable). Nothing here is random: ids come from the curated slugs and
timestamps from a fixed digest, so two builds of the same (cloud, customer, epoch) are
byte-identical. Documents are validated by constructing the generated contract models.

Public API:

* :func:`build_demo_world` - returns a :class:`DemoWorld` (documents, ids, telemetry-only agents,
  the designated outage service and its downstream agents).
* :func:`write_demo_world` - writes the world in the generator NDJSON layout (plus
  ``services.ndjson`` and ``mcp_servers.ndjson``) using :mod:`sandbox.output`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from neurosphere_contracts.catalog.v1 import (
    agent,
    agent_version,
    delegates_to,
    depends_on,
    domain,
    grounded_by,
    grounding_source,
    invokes,
    mcp_server,
    model_deployment,
    owned_by,
    owner,
    reads,
    service,
    tool,
    uses_model,
    writes,
)

from sandbox.config import (
    CATALOG_SOURCE,
    DEFAULT_CUSTOMER,
    DEFAULT_EPOCH,
    PRICE_EFFECTIVE_DATE,
    PRICE_VERSION,
    REGIONS,
    SCHEMA_VERSION,
    parse_epoch,
)
from sandbox.ids import canonical_id, digest_int, fmt_ts_s
from sandbox.output import NdjsonWriter, write_json
from sandbox.world import DAY_MS

Doc = dict[str, Any]

DATA_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_DAYS = 7

# File name -> attribute on DemoWorld, in load order (domains, owners, models/sources/tools, ...).
OUTPUT_FILES: tuple[tuple[str, str], ...] = (
    ("domains.ndjson", "domains"),
    ("owners.ndjson", "owners"),
    ("persons.ndjson", "persons"),
    ("model_deployments.ndjson", "models"),
    ("grounding_sources.ndjson", "sources"),
    ("services.ndjson", "services"),
    ("mcp_servers.ndjson", "mcp_servers"),
    ("tools.ndjson", "tools"),
    ("agents.ndjson", "agents"),
    ("agent_versions.ndjson", "agent_versions"),
    ("relations.ndjson", "relations"),
)

_RELATION_MODELS: dict[str, Any] = {
    "owned_by": owned_by.OwnedByRelation,
    "uses_model": uses_model.UsesModelRelation,
    "invokes": invokes.InvokesRelation,
    "reads": reads.ReadsRelation,
    "writes": writes.WritesRelation,
    "depends_on": depends_on.DependsOnRelation,
    "grounded_by": grounded_by.GroundedByRelation,
    "delegates_to": delegates_to.DelegatesToRelation,
}


@dataclass(frozen=True, slots=True)
class UndeclaredAgent:
    """An agent that exists only in telemetry: it has an id and name but no catalog entity."""

    slug: str
    name: str
    agent_id: str
    domain_id: str
    model_id: str
    tool_ids: tuple[str, ...]
    service_ids: tuple[str, ...]


@dataclass(slots=True)
class DemoWorld:
    cloud: str
    customer: str
    epoch: str
    days: int
    domains: list[Doc] = field(default_factory=list)
    owners: list[Doc] = field(default_factory=list)
    persons: list[Doc] = field(default_factory=list)
    models: list[Doc] = field(default_factory=list)
    sources: list[Doc] = field(default_factory=list)
    services: list[Doc] = field(default_factory=list)
    mcp_servers: list[Doc] = field(default_factory=list)
    tools: list[Doc] = field(default_factory=list)
    agents: list[Doc] = field(default_factory=list)
    agent_versions: list[Doc] = field(default_factory=list)
    relations: list[Doc] = field(default_factory=list)
    undeclared_agents: tuple[UndeclaredAgent, ...] = ()
    outage_service_id: str = ""
    downstream_agent_ids: tuple[str, ...] = ()
    unrelated_agent_ids: tuple[str, ...] = ()
    delegations: tuple[tuple[str, str], ...] = ()
    """Curated (parent agent id, child agent id) hand-offs, sorted; also `delegates_to` edges."""

    def cid(self, type_: str, slug: str) -> str:
        return canonical_id(self.cloud, self.customer, CATALOG_SOURCE, type_, slug)

    @property
    def undeclared_agent_ids(self) -> tuple[str, ...]:
        return tuple(a.agent_id for a in self.undeclared_agents)

    def documents(self, attr: str) -> list[Doc]:
        result: list[Doc] = getattr(self, attr)
        return result


def _load(name: str) -> Any:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def _dump(model: Any) -> Doc:
    result: Doc = model.model_dump(mode="json", exclude_none=True)
    return result


def _etag(label: str) -> str:
    return '"sbx-' + hashlib.sha256(label.encode("utf-8")).hexdigest()[:16] + '"'


class _Builder:
    def __init__(self, cloud: str, customer: str, epoch: str, days: int) -> None:
        self.w = DemoWorld(cloud=cloud, customer=customer, epoch=epoch, days=days)
        self.epoch_ms = parse_epoch(epoch)
        self.end_ms = self.epoch_ms + days * DAY_MS
        self.region = REGIONS[cloud]
        self.domain_ids: dict[str, str] = {}
        self.team_ids: dict[str, str] = {}
        self.entity_domain: dict[str, str] = {}  # entity id -> domain id
        self.model_ids: dict[str, str] = {}
        self.source_ids: dict[str, str] = {}
        self.service_ids: dict[str, str] = {}
        self.tool_ids: dict[str, str] = {}
        self.mcp_ids: dict[str, str] = {}

    def common(self, ident: str, entity_type: str, status: str = "active") -> Doc:
        back_days = 30 + digest_int(f"demo-world:created:{ident}") % 270
        created = fmt_ts_s(self.epoch_ms - back_days * DAY_MS)
        return {
            "schema_version": SCHEMA_VERSION,
            "id": ident,
            "entity_type": entity_type,
            "version": 1,
            "etag": _etag(ident),
            "lifecycle_status": status,
            "created_at": created,
            "updated_at": created,
            "cloud": self.w.cloud,
            "customer_id": self.w.customer,
        }

    def build(self) -> DemoWorld:
        self._domains()
        self._teams()
        self._models()
        self._sources()
        self._services()
        self._mcp_servers()
        self._tools()
        self._agents()
        self._relations()
        self._undeclared()
        self._scenario()
        self._delegations()
        return self.w

    def _domains(self) -> None:
        for d in _load("domains.json"):
            ident = self.w.cid("domain", d["slug"])
            self.domain_ids[d["slug"]] = ident
            doc = self.common(ident, "domain")
            doc.update(display_name=d["name"], classification="internal")
            self.w.domains.append(_dump(domain.Domain.model_validate(doc)))

    def _teams(self) -> None:
        for t in _load("teams.json"):
            ident = self.w.cid("owner", t["slug"])
            self.team_ids[t["slug"]] = ident
            self.entity_domain[ident] = self.domain_ids[t["domain"]]
            doc = self.common(ident, "owner")
            doc.update(
                domain_id=self.domain_ids[t["domain"]],
                owner_kind="team",
                display_name=t["name"],
            )
            self.w.owners.append(_dump(owner.Owner.model_validate(doc)))

    def _models(self) -> None:
        first_domain = next(iter(self.domain_ids.values()))
        for m in _load("models.json"):
            ident = self.w.cid("model_deployment", m["slug"])
            self.model_ids[m["slug"]] = ident
            self.entity_domain[ident] = first_domain
            doc = self.common(ident, "model_deployment")
            doc.update(
                domain_id=first_domain,
                provider=m["provider"],
                model_name=m["model_name"],
                model_version=m["model_version"],
                deployment_name=m["deployment_name"],
                modalities=m["modalities"],
                context_window_tokens=128_000,
                max_output_tokens=8_192,
                supports_tool_calling=m["tool_calling"],
                region=self.region,
                sku="Standard",
                price_reference={
                    "price_version": PRICE_VERSION,
                    "price_effective_date": PRICE_EFFECTIVE_DATE,
                },
                tags=m["tags"],
                environment=m["environment"],
            )
            self.w.models.append(_dump(model_deployment.ModelDeployment.model_validate(doc)))

    def _sources(self) -> None:
        for s in _load("data_assets.json"):
            ident = self.w.cid("grounding_source", s["slug"])
            self.source_ids[s["slug"]] = ident
            self.entity_domain[ident] = self.domain_ids[s["domain"]]
            doc = self.common(ident, "grounding_source")
            doc.update(
                domain_id=self.domain_ids[s["domain"]],
                display_name=s["name"],
                asset_kind=s["kind"],
                source_id="sandbox-" + s["kind"].replace("_", "-"),
                classification=s["classification"],
                contains_personal_data=bool({"pii", "phi"} & set(s["sensitivity"])),
                sensitivity_categories=s["sensitivity"],
                residency_geography=s["residency"],
                tags=s["tags"],
                environment=s["environment"],
            )
            self.w.sources.append(_dump(grounding_source.GroundingSource.model_validate(doc)))

    def _services(self) -> None:
        for s in _load("services.json"):
            ident = self.w.cid("service", s["slug"])
            self.service_ids[s["slug"]] = ident
            self.entity_domain[ident] = self.domain_ids[s["domain"]]
            doc = self.common(ident, "service")
            doc.update(
                domain_id=self.domain_ids[s["domain"]],
                display_name=s["name"],
                service_kind=s["kind"],
                source_id="sandbox-registry",
                classification=s["classification"],
                residency_region=self.region,
                tags=s["tags"],
                environment=s["environment"],
            )
            if "azure_resource_type" in s:
                doc["azure_resource_type"] = s["azure_resource_type"]
            self.w.services.append(_dump(service.Service.model_validate(doc)))

    def _mcp_servers(self) -> None:
        for m in _load("mcp_servers.json"):
            ident = self.w.cid("mcp_server", m["slug"])
            self.mcp_ids[m["slug"]] = ident
            self.entity_domain[ident] = self.domain_ids[m["domain"]]
            doc = self.common(ident, "mcp_server")
            doc.update(
                domain_id=self.domain_ids[m["domain"]],
                display_name=m["name"],
                url=m["url"],
                transport="streamable_http",
                protocol_versions=["2025-06-18"],
                auth={"kind": "managed_identity"},
                publishable=False,
                owner_id=self.team_ids[m["team"]],
                provenance={
                    "method": "declared",
                    "source_id": "sandbox-registry",
                    "recorded_at": fmt_ts_s(self.epoch_ms),
                },
                classification=m["classification"],
                tags=m["tags"],
                environment=m["environment"],
            )
            self.w.mcp_servers.append(_dump(mcp_server.McpServer.model_validate(doc)))

    def _tools(self) -> None:
        for t in _load("tools.json"):
            ident = self.w.cid("tool", t["slug"])
            self.tool_ids[t["slug"]] = ident
            self.entity_domain[ident] = self.domain_ids[t["domain"]]
            doc = self.common(ident, "tool")
            doc.update(
                domain_id=self.domain_ids[t["domain"]],
                display_name=t["name"],
                tool_kind=t["kind"],
                side_effects=t["side_effects"],
                source_id="sandbox-registry",
                tags=t["tags"],
                capabilities=t["capabilities"],
                environment=t["environment"],
            )
            if "mcp_server" in t:
                doc["mcp_server_ref"] = self.mcp_ids[t["mcp_server"]]
            self.w.tools.append(_dump(tool.Tool.model_validate(doc)))

    def _agents(self) -> None:
        for a in _load("agents.json"):
            ident = self.w.cid("agent", a["slug"])
            dom = self.domain_ids[a["domain"]]
            self.entity_domain[ident] = dom
            versions: list[tuple[str, list[str], list[str], str]] = []
            if "previous" in a:
                p = a["previous"]
                versions.append((p["version"], p["capabilities"], p["tags"], "retired"))
            versions.append((a["version"], a["capabilities"], a["tags"], "active"))
            current_id = self.w.cid("agent_version", f"{a['slug']}-v{len(versions)}")
            doc = self.common(ident, "agent")
            doc.update(
                domain_id=dom,
                classification="internal",
                display_name=a["name"],
                description=a["description"],
                agent_kind=a["kind"],
                platform="foundry",
                source_id="sandbox-foundry",
                external_agent_id=f"ext-{a['slug']}",
                current_version_id=current_id,
                residency_region=self.region,
                tags=a["tags"],
                capabilities=a["capabilities"],
                environment=a["environment"],
            )
            self.w.agents.append(_dump(agent.Agent.model_validate(doc)))
            for n, (semver, caps, tags, status) in enumerate(versions, start=1):
                vid = self.w.cid("agent_version", f"{a['slug']}-v{n}")
                vdoc = self.common(vid, "agent_version", status)
                vdoc.update(
                    domain_id=dom,
                    agent_id=ident,
                    version_label=f"v{semver}",
                    semver=semver,
                    released_at=vdoc["created_at"],
                    config_hash="sha256:" + hashlib.sha256(vid.encode("utf-8")).hexdigest(),
                    tags=tags,
                    capabilities=caps,
                )
                self.w.agent_versions.append(_dump(agent_version.AgentVersion.model_validate(vdoc)))

    def _edge(self, relation: str, src_slug: str, tgt_slug: str, source: str, target: str) -> Doc:
        start = fmt_ts_s(self.epoch_ms)
        end = fmt_ts_s(self.end_ms)
        ident = self.w.cid(relation, f"{src_slug}.{tgt_slug}")
        doc: Doc = {
            "schema_version": SCHEMA_VERSION,
            "id": ident,
            "relation_type": relation,
            "version": 1,
            "etag": _etag(ident),
            "source_id": source,
            "target_id": target,
            "cloud": self.w.cloud,
            "customer_id": self.w.customer,
            "domain_id": self.entity_domain[source],
            "provenance": {
                "method": "declared",
                "source_id": "sandbox-foundry",
                "recorded_at": start,
            },
            "evidence_ids": [],
            "security_evidence_ids": [],
            "confidence": 1.0,
            "first_observed": start,
            "last_observed": end,
            "validity": {"valid_from": start},
            "status": "asserted",
            "lock": {"locked": False},
            "created_at": start,
            "updated_at": end,
        }
        return _dump(_RELATION_MODELS[relation].model_validate(doc))

    def _relations(self) -> None:
        out = self.w.relations
        for a in _load("agents.json"):
            slug = a["slug"]
            src = self.w.cid("agent", slug)
            out.append(self._edge("owned_by", slug, a["team"], src, self.team_ids[a["team"]]))
            out.append(self._edge("uses_model", slug, a["model"], src, self.model_ids[a["model"]]))
            for key, relation, ids in (
                ("tools", "invokes", self.tool_ids),
                ("services", "depends_on", self.service_ids),
                ("reads", "reads", self.source_ids),
                ("writes", "writes", self.source_ids),
                ("grounded_by", "grounded_by", self.source_ids),
            ):
                for target in a[key]:
                    out.append(self._edge(relation, slug, target, src, ids[target]))
        for t in _load("tools.json"):
            for svc in t["services"]:
                out.append(
                    self._edge(
                        "depends_on",
                        t["slug"],
                        svc,
                        self.tool_ids[t["slug"]],
                        self.service_ids[svc],
                    )
                )

    def _undeclared(self) -> None:
        items: list[UndeclaredAgent] = []
        for u in _load("undeclared_agents.json"):
            items.append(
                UndeclaredAgent(
                    slug=u["slug"],
                    name=u["name"],
                    agent_id=self.w.cid("agent", u["slug"]),
                    domain_id=self.domain_ids[u["domain"]],
                    model_id=self.model_ids[u["model"]],
                    tool_ids=tuple(self.tool_ids[t] for t in u["tools"]),
                    service_ids=tuple(self.service_ids[s] for s in u["services"]),
                )
            )
        self.w.undeclared_agents = tuple(items)

    def _scenario(self) -> None:
        outage = self.service_ids[_load("scenario.json")["outage_service"]]
        self.w.outage_service_id = outage
        agent_ids = [a["id"] for a in self.w.agents]
        down = sorted(
            r["source_id"]
            for r in self.w.relations
            if r["relation_type"] == "depends_on"
            and r["target_id"] == outage
            and r["source_id"] in set(agent_ids)
        )
        self.w.downstream_agent_ids = tuple(down)
        self.w.unrelated_agent_ids = tuple(sorted(set(agent_ids) - set(down)))

    def _delegations(self) -> None:
        """Load the curated hand-offs, enforce the incident-integrity rule, emit the edges.

        Rule: a parent outside the downstream set must never delegate to a downstream agent,
        or the incident would spread to an agent that does not depend on the outage service.
        """
        agents = {a["id"] for a in self.w.agents}
        down = set(self.w.downstream_agent_ids)
        pairs: set[tuple[str, str]] = set()
        for d in _load("scenario.json")["delegations"]:
            parent = self.w.cid("agent", d["parent"])
            child = self.w.cid("agent", d["child"])
            if parent not in agents or child not in agents:
                raise ValueError(f"delegation references an unknown agent: {d}")
            if parent == child:
                raise ValueError(f"agent cannot delegate to itself: {d}")
            if parent not in down and child in down:
                raise ValueError(f"delegation would spread the incident to a new agent: {d}")
            if (parent, child) in pairs:
                raise ValueError(f"duplicate delegation: {d}")
            pairs.add((parent, child))
            self.w.relations.append(
                self._edge("delegates_to", d["parent"], d["child"], parent, child)
            )
        self.w.delegations = tuple(sorted(pairs))


def build_demo_world(
    cloud: str,
    customer: str = DEFAULT_CUSTOMER,
    epoch: str = DEFAULT_EPOCH,
    days: int = DEFAULT_DAYS,
) -> DemoWorld:
    """Build the curated demo world for one cloud and customer; deterministic and offline."""
    if cloud not in REGIONS:
        raise ValueError(f"cloud must be one of {tuple(REGIONS)}")
    return _Builder(cloud, customer, epoch, days).build()


def write_demo_world(world: DemoWorld, out_dir: Path) -> dict[str, int]:
    """Write the catalog files in the generator NDJSON layout; return line counts per file."""
    out_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for name, attr in OUTPUT_FILES:
        with NdjsonWriter(out_dir / name) as writer:
            for doc in world.documents(attr):
                writer.write_doc(doc)
            counts[name] = writer.count
    return counts


def demo_manifest(world: DemoWorld) -> Doc:
    """Stable ids for the run manifest: telemetry-only agents and the outage scenario inputs."""
    return {
        "undeclared_agents": [
            {"agent_id": a.agent_id, "display_name": a.name} for a in world.undeclared_agents
        ],
        "outage_service_id": world.outage_service_id,
        "downstream_agent_ids": list(world.downstream_agent_ids),
        "delegations": [
            {"parent_agent_id": parent, "child_agent_id": child}
            for parent, child in world.delegations
        ],
    }


def write_demo_manifest(world: DemoWorld, path: Path) -> None:
    write_json(path, demo_manifest(world))
