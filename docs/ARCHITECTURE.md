# NeuroSphere — Architecture baseline v1.1
## Decisions and retained trade-offs
Azure Commercial/Government are deployment boundaries; third-party providers are approved connector targets. Start modular API plus ingestion/action/evaluation workers. API and domain contracts are independent of analytics vendor or optional managed agent orchestration.
| Layer | Baseline | Retained alternative / gate |
|---|---|---|
| Catalog/relationships | Cosmos DB NoSQL versioned documents and adjacency, bounded query service | Neo4j for justified deep graph workloads; residency/license/operations benchmark required. Gremlin considered but not baseline due traversal/partition limits. No unverified Cosmos PostgreSQL/Apache AGE dependency. |
| Analytics | Deployment-selected Fabric, Synapse or Azure Databricks | Capability manifests and equivalent query results; availability/security approval per cloud/region/feature. ClickHouse is historical, not a default. |
| Events | Azure Event Hubs plus durable quarantine and redacted archive | Local fixture transport; standalone Kafka/PubSub/Kinesis are historical comparisons, not supported hosting promises. |
| Search | Azure AI Search with server-side scope filters | Offline fixture index; Pinecone/Qdrant are historical options, not required deployment dependencies. |
| Copilot | Application-owned authorized query/action tools; approved model endpoint | Foundry Agent Service adapter only for validated features/regions; same action contract on fallback. |
| Compute | AKS enterprise, App Service smaller supported profile | No assumption App Service runs Helm; same container/domain code, different IaC modules. |
Operational graph stores entities/edge evidence references and rollups; raw events/traces/cost ledger live outside it. Indexes and projections are rebuildable. Domain/shard partitioning, precomputed cross-domain summaries and bounded fan-out avoid whole-enterprise traversal on each request.
## 1. Component and trust-boundary flow
```mermaid
flowchart TB
  U[User] --> I[Entra authentication]
  I --> UI[Fluent-inspired UI and copilot chat]
  UI --> G[APIM reused or provisioned]
  G --> P[API authorization and policy]
  P --> C[Catalog and scoped graph queries]
  P --> Q[Bounded analytics query service]
  P --> O[Copilot orchestrator]
  C --> DB[Cosmos NoSQL entities and adjacency]
  Q --> A[Fabric or Synapse or Azure Databricks]
  O --> T[Authorized tools and safe chart plans]
  T --> C
  T --> Q
  O --> M[Approved model endpoint or Foundry adapter]
  T --> X[Durable action and HITL service]
  X --> Z[Supported target write connectors]
  X --> AU[Append-only audit evidence]
```
## 2. Telemetry projections and live view
```mermaid
flowchart LR
  S[OTel SDK and authorized provider connectors] --> R[Redact and authenticate]
  R --> H[Event Hubs]
  H --> N[Validate normalize deduplicate]
  N --> B[Redacted archive and replay]
  N --> K[Explicit quarantine]
  N --> A[Analytics adapter and cost ledger]
  N --> C[Catalog evidence projection]
  N --> V[Bounded hot aggregates]
  V --> W[Scoped WebSocket gateway]
  W --> UI[Clustered map viewport]
  B --> E[Sampled evaluation workers]
  E --> REC[Evidence-backed recommendations]
  A --> REC
  C --> REC
```
Offset/checkpoint advancement follows durable acceptance or quarantine. Separate sink checkpoints/idempotent projection reconcile partial writes; no fictional cross-store transaction. Source billing freshness differs from instrumented trace freshness. Hot aggregates remain operational if batch analytics is delayed; UI shows lag and coverage.
## 3. Governed action from chat, button or MCP
```mermaid
sequenceDiagram
  participant U as User or external client
  participant API as Shared action API
  participant P as Current policy
  participant W as Approval workflow
  participant X as Target connector
  participant A as Audit
  U->>API: Request model swap with target version
  API->>P: Check actor scope and prerequisites
  API->>U: Show exact diff and expiring confirmation
  U->>API: Confirm bound intent
  API->>W: Request reviewer approval if required
  W->>API: Approve or reject
  API->>P: Recheck current permission and target version
  API->>A: Persist intent and execution state
  API->>X: Idempotent canary change
  X-->>API: Verify actual outcome
  API->>A: Record result and rollback evidence
  API-->>U: Verified result or explicit failure
```
## 4. Deployment intelligence and sovereign profiles
```mermaid
flowchart TD
  D[Choose cloud and approved region] --> S[Consented read-only resource scan]
  S --> V[Validate access network SKU quota residency and owner]
  V --> R[Reuse create skip deployment plan]
  R --> C[Operator approval]
  C --> CAP[Service feature authorization capability matrix]
  CAP --> OK[Supported profile]
  CAP --> NO[Disable unavailable option with reason]
  OK --> I[IaC and workspace provisioning adapters]
  I --> SM[Connectivity policy and smoke tests]
  SM --> E[Evidence manifest and ownership register]
```
Commercial and Government deploy separate identity endpoints, model/search/storage/event services and analytics resources; no automatic cross-cloud data flow. Fabric/Synapse/Databricks choices are evaluated individually. Resource discovery is visibility-limited, not an unrestricted tenant inventory.
## 5. Federation and disaster recovery
```mermaid
flowchart LR
  subgraph Boundary[Approved cloud and geographic boundary]
    D1[Domain cell A] --> S[Authorized aggregate summaries]
    D2[Domain cell B] --> S
    S --> E[Enterprise view]
    P[Primary regional services] --> R[Approved secondary and durable replay]
    R --> T[Restore failover and failback tests]
  end
  Public[Public docs-only assistant] --> Docs[Published documentation corpus]
```
Domain cells publish permitted aggregates, not unrestricted identities/prompts. Replication locations require approval and actual service support; paired-region assumptions are insufficient. Event Hubs metadata geo-DR does not replicate event data or RBAC. Data geo-replication availability/tier must be checked; otherwise implement approved archive/replay strategy and publish measured RPO limitations. Foundry does not supply automatic application failover.
## 6. Data model and query safety
Entities carry canonical ID, customer/domain/cloud, version, lifecycle, owner, classification and residency. Models include deployment/version/modality/context/tool capability and price-reference metadata. Relations carry asserted/inferred/curated status, confidence/provenance, validity, evidence references and override lock. Runs/spans are referenced rather than indefinitely replicated into graph nodes.
GraphQuery supports scoped get/search/neighbors/bounded impact paths; RecommendationCompute handles analytical graph/similarity jobs away from the interactive path. Copilot uses structured tools rather than unrestricted Cypher/SQL. Search and push paths enforce the same policy as REST.
The five Mermaid sources above are the diagram of record. They were rendered and parser-validated on 2026-10-08 to docs/diagrams/01..05-*.svg (gate G10 closed). Re-render after any source change; PRP-00 adds the script and CI check that keeps the SVGs in sync.
