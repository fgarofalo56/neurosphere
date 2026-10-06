# NeuroSphere — Product Requirements Prompt (PRP) / Implementation Plan

## 1. Architecture Overview

### 1.1 Graph Backend: Neo4j vs. Cosmos DB (Gremlin API)

| Dimension | Neo4j (AuraDB / self-managed) | Azure Cosmos DB (Gremlin API) |
|---|---|---|
| Native graph model | Native property graph engine, purpose-built for traversal | Multi-model store with a Gremlin API layered on top; not a native graph engine [source: Medium, "Neo4j vs CosmosDB, when used as a graph database", ondrej-kvasnovsky.medium.com] |
| Query language | Cypher (expressive, widely adopted for graph-native querying) | Gremlin (TinkerPop traversal API) |
| Multi-hop traversal performance | Strong for deep/variable-length traversals | Performs well for short, predictable 1-2 hop traversals aligned to a good partition key; degrades on deep/unbounded traversals [source: PuppyGraph, "Cosmos DB vs Neo4j: How to Choose for Graph Workloads", puppygraph.com/blog/cosmosdb-vs-neo4j] |
| Operability / ease of setup | Reviewers rate Neo4j easier to set up and administer than Cosmos DB for graph workloads [source: G2, "Azure Cosmos DB vs Neo4j Graph Database Comparison", g2.com/compare/azure-cosmos-db-vs-neo4j-graph-database] |
| Global distribution / multi-region writes | Requires Neo4j Fabric/clustering configuration | Native turnkey multi-region read/write replication (Cosmos DB platform feature) |
| Managed-service fit on Azure | AuraDB is a separate managed service (not native Azure) | Native first-party Azure PaaS service, fits directly into existing Azure landing zones |
| Recommendation for NeuroSphere | **Primary recommendation for v1**: Neo4j (AuraDB or self-hosted) for the core relationship graph, given deep multi-hop traversal needs (agent → data asset → downstream consumer chains) and Cypher's better fit for ad-hoc copilot-generated queries. | Offer Cosmos DB Gremlin as the **Azure-native alternative** in the multi-cloud deployment profile for customers who want a single-vendor Azure stack and whose traversals are shallow. |

**Decision:** Abstract the graph layer behind a internal Graph Service interface (nodes/edges/traversal operations) so either backend can be swapped per deployment profile; ship Neo4j as default, Cosmos DB Gremlin as an Azure-native option.

### 1.2 Analytics / Lakehouse Layer

| Option | Strengths | Trade-offs | Best fit |
|---|---|---|---|
| **ClickHouse** | Purpose-built for real-time, sub-second analytical queries on event data; 50-70% cost savings vs. Snowflake/BigQuery for single-table aggregations [source: Improvado, "7 Best Snowflake Alternatives", improvado.io/blog/snowflake-competitors-and-alternatives] | Less suited to complex ML/feature-engineering workflows; no native lakehouse table format story out of the box | Hot-path telemetry aggregation, dashboards, near-real-time metrics feeding the visual map |
| **Databricks** | Lakehouse model (Delta Lake) designed for code-first ML workflows and open architecture [source: Fivetran, "Data Warehouse Comparison Guide", fivetran.com/learn/snowflake-competitors] | Higher operational complexity/cost for simple real-time aggregation use cases | Training/retraining the recommendation engine, historical trend analytics, data science workbench |
| **Microsoft Fabric** | Unified SaaS suite within the Azure ecosystem; integrates OneLake, Power BI, Data Factory natively [source: Improvado, same article] | Newer platform, less open (more Azure-centric lock-in) | Customers standardized on Microsoft 365/Power BI who want a single-vendor Azure analytics surface |
| **Azure Synapse** | Serverless SQL pools, integrates with Azure Data Factory and Azure ML [source: Microsoft Q&A, "choosing the right azure data platform", learn.microsoft.com] | Being gradually superseded in Microsoft's roadmap by Fabric | Existing Synapse-invested customers; not recommended as default for new builds |

**Decision:** Use **ClickHouse** as the default real-time analytics layer for telemetry aggregation (cost + latency optimal for the event volume NeuroSphere expects), with **Databricks** (or Fabric, on the Azure-native deployment profile) as the batch/ML layer for recommendation-engine model training and long-horizon analytics. Azure Synapse supported only for brownfield Azure customers already invested in it.

### 1.3 Event-Driven Telemetry Pipeline: Kafka / Event Hubs / Pub/Sub

| Option | Strengths | Trade-offs |
|---|---|---|
| **Apache Kafka** (self-managed or Confluent) | Open, portable across any cloud/on-prem; largest ecosystem of connectors/stream processors (Kafka Streams, Flink) | Requires cluster provisioning/ops, or a managed Confluent bill |
| **Azure Event Hubs** | Fully managed, Kafka-protocol-compatible endpoint, scales via throughput units/processing units, native Capture feature writes straight to storage for replay [source: Branch Boston, "AWS Kinesis vs Azure Event Hub vs Google Pub/Sub for Stream Processing", branchboston.com] | Azure-specific; event size capped at 1 MB [source: ProjectPro, "azure event hubs vs google cloud pub sub", projectpro.io/compare/azure-event-hubs-vs-google-cloud-pub-sub] |
| **Google Cloud Pub/Sub** | Fully managed, scales automatically with no capacity provisioning required [source: ProjectPro, same article] | GCP-specific; different delivery/ordering semantics than Kafka |

**Decision:** Define telemetry events in **CloudEvents** schema and use a pluggable broker adapter: **Kafka** as the cloud-agnostic default (also the on-prem option), **Azure Event Hubs** (Kafka-protocol-compatible) for the Azure-native profile, **Pub/Sub** for the GCP profile, and Kinesis for AWS if needed later. Because Event Hubs exposes a Kafka-compatible endpoint, the same Kafka client/consumer code can target either broker with configuration only — minimizing code fork across deployment profiles.

### 1.4 AI Copilot Integration: RAG over Graph + Vector Store, Tool-Calling

**Vector store options considered:**

| Option | Strengths | Trade-offs |
|---|---|---|
| **Azure AI Search** | Native hybrid search (BM25 + vector + semantic ranker) in a single query; integrates directly with Azure OpenAI/Foundry [source: Technspire, "Vector Search 2026: Azure AI Search vs pgvector vs Pinecone", technspire.com] | Azure-specific; less portable to multi-cloud profiles |
| **Pinecone** | Managed, zero-ops, strong for high-dimensional vectors at enterprise scale [source: dasroot.net, "Vector Stores Comparison"; iternal.ai, "Best Vector Databases 2026"] | Separate vendor/billing relationship; portability of exported vectors is good but still adds an integration | 
| **Qdrant** | Performance-critical workloads, open-source, portable across clouds and on-prem [source: Gennoor Tech, "Vector Databases for Enterprise", gennoor.com/resources/blog/vector-databases-enterprise-comparison] | Requires self-hosting/ops unless using Qdrant Cloud |

**Decision:** Default to **Azure AI Search** for the Azure-native deployment profile (tight integration, built-in hybrid ranking), **Qdrant** as the portable/open-source default for the cloud-agnostic and on-prem profiles. Both are behind a common VectorStore interface.

**RAG + tool-calling design:**
1. User question → copilot orchestrator (e.g., built on Azure AI Foundry Agent Service, Semantic Kernel, or LangGraph — ⚠ needs verification on final framework choice pending a dedicated framework bake-off) classifies intent.
2. Retrieval step: hybrid vector + keyword search over indexed documentation/telemetry summaries AND a templated graph query (Cypher/Gremlin) scoped to the entities mentioned.
3. Tool-calling: the LLM can invoke `graph_query`, `catalog_lookup`, `telemetry_metric`, and `recommendation_lookup` tools; each tool call result is attached as a citation.
4. Response assembled with inline citations back to graph node IDs / telemetry record IDs; if retrieval returns nothing, the copilot must say so rather than answer from parametric memory.

## 2. Data Model Sketch (Graph)

**Node types:**
- `Agent` (id, name, version, owner, status, capability_tags[], deployment_env)
- `Service` (id, name, type, owner, deployment_env)
- `DataAsset` (id, name, classification [public/internal/PII/PHI/CUI], residency_region)
- `Tool` (id, name, provider, version)
- `Team` (id, name, owner_contact)
- `TelemetryEvent` (id, type, timestamp, latency_ms, status) — windowed/rolled up, not retained indefinitely as graph nodes (raw events live in the analytics layer; the graph holds summarized edges/recent-state)
- `ComplianceControl` (id, framework [SOC2/ISO27001/GDPR/FedRAMP], control_id)

**Edge types:**
- `(Agent)-[:INVOKES]->(Agent|Tool|Service)`
- `(Agent)-[:OWNED_BY]->(Team)`
- `(Agent)-[:ACCESSES {mode: read|write}]->(DataAsset)`
- `(Agent)-[:DEPENDS_ON]->(Service|Tool)`
- `(Agent)-[:HAS_VERSION]->(Agent)` (version chain)
- `(Agent)-[:EMITTED]->(TelemetryEvent)` (recent window only)
- `(DataAsset)-[:GOVERNED_BY]->(ComplianceControl)`
- `(Agent)-[:RECOMMENDED_FOR {task_embedding_ref, score}]->(Task)`

## 3. Dependencies and Third-Party Services

- Graph: Neo4j AuraDB/self-hosted, or Azure Cosmos DB (Gremlin API)
- Streaming: Kafka / Azure Event Hubs / GCP Pub/Sub
- Analytics: ClickHouse, Databricks (or Microsoft Fabric on Azure profile)
- Vector store: Azure AI Search or Qdrant
- LLM/agent orchestration: Azure OpenAI / Azure AI Foundry Agent Service, or portable equivalent (⚠ needs verification — final framework TBD)
- IaC: Terraform (cloud-agnostic) + Bicep (Azure-native templates)
- Secrets: Azure Key Vault / AWS Secrets Manager / GCP Secret Manager / HashiCorp Vault (on-prem)
- Identity: Entra ID / IAM / federated OIDC
- Observability: OpenTelemetry collectors feeding both the analytics layer and NeuroSphere's own self-telemetry

## 4. Assumptions and Risks

| Assumption/Risk | Mitigation |
|---|---|
| Assumes agent owners will consistently instrument telemetry via SDK/webhook | Provide a lightweight SDK + auto-instrumentation wrapper; reconciliation job flags undeclared "shadow agents" from telemetry source IP/identity even without full metadata |
| Risk: graph write contention at high event volume (hot nodes) | Batch/aggregate high-frequency telemetry into rolled-up edges rather than one edge per event; use write-behind queue |
| Risk: copilot hallucination despite RAG grounding | Enforce citation-required response format; automated eval harness testing groundedness before each release |
| Risk: multi-cloud abstraction adds engineering overhead vs. single-cloud focus | Phase cloud support — Azure-native first (Phase 1-2), AWS/GCP/on-prem adapters added once core abstractions are proven (Phase 3+) |
| Risk: FedRAMP/compliance claims overstated | Explicitly scope v1 messaging to "FedRAMP-aligned architecture," not authorization; legal/compliance review gate before any customer-facing compliance claim |
| Assumes recommendation engine has enough historical usage data to be useful | Cold-start fallback: rank by capability-tag match + graph proximity only until sufficient feedback signal accumulates |

## 5. Phased Development Plan

### Phase 0 — Foundations (6-8 weeks)
- **Scope:** Core graph schema design, Graph Service abstraction (Neo4j default), basic CloudEvents schema, single-broker ingestion (Kafka), minimal catalog CRUD API.
- **Exit criteria:** Can register an agent, emit a telemetry event, see it land as a graph edge within 5s, in a dev environment.
- **Rough effort:** 2 backend engineers, 1 platform engineer — ~1.5 person-months.

### Phase 1 — Telemetry Pipeline + Catalog GA (8-10 weeks)
- **Scope:** Production-grade ingestion with DLQ/backpressure, full agent catalog with versioning, reconciliation job for shadow-agent detection, ClickHouse analytics sink.
- **Exit criteria:** Meets NFR targets (p95 ingestion <5s at 10k events/sec in staging load test); catalog metadata completeness >95% in pilot environment.
- **Rough effort:** 3 backend engineers, 1 data engineer — ~3 person-months.

### Phase 2 — Visual Map + Recommendation Engine v1 (8-10 weeks)
- **Scope:** Real-time topology visualization (WebSocket push), initial recommendation engine (capability-tag + graph-proximity ranking, no ML yet).
- **Exit criteria:** Map renders 50k-node graphs with <200ms interaction latency; recommendation API live with feedback capture.
- **Rough effort:** 2 frontend engineers, 2 backend engineers — ~3.5 person-months.

### Phase 3 — AI Copilot + Vector/RAG Layer (8-12 weeks)
- **Scope:** Vector store integration (Azure AI Search + Qdrant adapters), RAG pipeline, tool-calling orchestration, citation-enforced responses, groundedness eval harness.
- **Exit criteria:** Copilot answers a benchmark set of 100 operator questions with >90% groundedness pass rate; no hallucinated answers in eval set.
- **Rough effort:** 2 ML/AI engineers, 1 backend engineer — ~4 person-months.

### Phase 4 — Multi-Cloud + Compliance Hardening (10-12 weeks)
- **Scope:** AWS/GCP/on-prem IaC adapters, Cosmos DB Gremlin alternative graph backend, full audit logging, SOC 2 control mapping, data residency controls, encryption hardening.
- **Exit criteria:** Reference deployment succeeds on all 4 target environments; SOC 2 Type II readiness assessment passed (pre-audit); GDPR data-subject-request workflow functional.
- **Rough effort:** 2 platform/infra engineers, 1 security engineer, 1 compliance SME — ~5 person-months.

### Phase 5 — GA Hardening & Launch (4-6 weeks)
- **Scope:** Load/chaos testing at target scale (1M nodes/10M edges), documentation, customer onboarding playbooks, pricing/metering integration.
- **Exit criteria:** All PRD success metrics met in a production-representative environment; GA sign-off.
- **Rough effort:** Full team, ~2 person-months focused effort.

---
*Sources: PuppyGraph (puppygraph.com/blog/cosmosdb-vs-neo4j), Medium/ondrej-kvasnovsky (ondrej-kvasnovsky.medium.com/neo4j-vs-cosmosdb-when-used-as-a-graph-database-dde8c1dd577e), G2 (g2.com/compare/azure-cosmos-db-vs-neo4j-graph-database), Improvado (improvado.io/blog/snowflake-competitors-and-alternatives), Fivetran (fivetran.com/learn/snowflake-competitors), Microsoft Q&A (learn.microsoft.com/en-us/answers/questions/2258999), Branch Boston (branchboston.com/aws-kinesis-vs-azure-event-hub-vs-google-pub-sub-for-stream-processing), ProjectPro (projectpro.io/compare/azure-event-hubs-vs-google-cloud-pub-sub), Technspire (technspire.com/en/blog/vector-search-2026-azure-pgvector-managed), Gennoor Tech (gennoor.com/resources/blog/vector-databases-enterprise-comparison), dasroot.net, iternal.ai. [source: web_search]*
