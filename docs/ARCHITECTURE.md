# NeuroSphere — Architecture Diagrams

All diagrams below are valid Mermaid syntax (verified for balanced brackets/quotes and correct directive keywords).

## 1. C4-Style System Context Diagram

```mermaid
flowchart TB
    User["Operator / SRE / Compliance Officer"]
    Copilot["NeuroSphere Platform\n(Agent Observability & Copilot)"]
    Agents["Customer AI Agent Fleet\n(LangChain / Semantic Kernel / Foundry agents)"]
    DataSystems["Enterprise Data Systems\n(DBs, SaaS APIs, Data Lakes)"]
    CloudProviders["Cloud Providers\n(Azure / AWS / GCP / On-Prem)"]
    IdP["Identity Provider\n(Entra ID / Okta / IAM)"]

    User -->|"Asks questions, views map, manages catalog"| Copilot
    Agents -->|"Emits telemetry events"| Copilot
    Copilot -->|"Queries / observes"| DataSystems
    Copilot -->|"Deploys onto"| CloudProviders
    Copilot -->|"Authenticates via"| IdP
    Copilot -->|"Recommends agent/tool for task"| User
```

## 2. Component Diagram

```mermaid
flowchart LR
    subgraph Ingestion["Telemetry Ingestion Layer"]
        SDK["Agent SDK / Webhook"]
        Broker["Event Broker\n(Kafka / Event Hubs / Pub-Sub)"]
        Normalizer["Schema Normalizer\n(CloudEvents)"]
    end

    subgraph Core["Core Platform"]
        GraphSvc["Graph Service\n(Neo4j / Cosmos DB Gremlin)"]
        Catalog["Agent Catalog Service"]
        RecEngine["Recommendation Engine"]
        Analytics["Analytics Layer\n(ClickHouse + Databricks/Fabric)"]
    end

    subgraph AI["AI Copilot Layer"]
        VectorStore["Vector Store\n(Azure AI Search / Qdrant)"]
        Orchestrator["Copilot Orchestrator\n(RAG + Tool-Calling)"]
        LLM["LLM\n(Azure OpenAI / Foundry)"]
    end

    subgraph UX["Experience Layer"]
        Map["Real-Time Visual Map UI"]
        ChatUI["Copilot Chat UI"]
        CatalogUI["Catalog / Admin UI"]
    end

    SDK --> Broker --> Normalizer --> GraphSvc
    Normalizer --> Analytics
    GraphSvc --> Catalog
    GraphSvc --> RecEngine
    Analytics --> RecEngine
    GraphSvc --> VectorStore
    Analytics --> VectorStore
    Orchestrator --> VectorStore
    Orchestrator --> GraphSvc
    Orchestrator --> RecEngine
    Orchestrator --> LLM
    GraphSvc --> Map
    Orchestrator --> ChatUI
    Catalog --> CatalogUI
```

## 3. Event-Driven Telemetry Pipeline Sequence Diagram

```mermaid
sequenceDiagram
    participant Agent as Customer Agent
    participant SDK as NeuroSphere SDK
    participant Broker as Event Broker
    participant Consumer as Ingestion Consumer
    participant Graph as Graph Service
    participant Analytics as Analytics Layer (ClickHouse)

    Agent->>SDK: emit invocation/error/latency event
    SDK->>Broker: publish CloudEvent
    Broker-->>Consumer: deliver event (at-least-once)
    Consumer->>Consumer: validate schema
    alt schema valid
        Consumer->>Graph: upsert node/edge (rolled-up)
        Consumer->>Analytics: write raw event row
        Graph-->>Consumer: ack
    else schema invalid
        Consumer->>Broker: route to Dead Letter Queue
    end
    Consumer-->>Broker: commit offset
```

## 4. Recommendation Engine Data Flow

```mermaid
flowchart TD
    TaskInput["Task Description / Workflow Context"]
    Embed["Embed Task Text"]
    TagMatch["Capability Tag Matching\n(Catalog Service)"]
    GraphProximity["Graph Proximity Scoring\n(Graph Service)"]
    HistPerf["Historical Performance Signals\n(Analytics Layer)"]
    Ranker["Ranking Model\n(weighted scoring, ML-assisted in later phases)"]
    Results["Ranked Agent/Tool Recommendations\n+ Explanation"]
    Feedback["Operator Accept/Reject Feedback"]

    TaskInput --> Embed
    Embed --> TagMatch
    Embed --> GraphProximity
    TagMatch --> Ranker
    GraphProximity --> Ranker
    HistPerf --> Ranker
    Ranker --> Results
    Results --> Feedback
    Feedback -->|"retrain / reweight"| Ranker
```

## 5. AI Copilot Request/Response Sequence (Retrieval + Tool Calls)

```mermaid
sequenceDiagram
    participant User as Operator
    participant UI as Copilot Chat UI
    participant Orch as Copilot Orchestrator
    participant Vec as Vector Store
    participant Graph as Graph Service
    participant Rec as Recommendation Engine
    participant LLM as LLM

    User->>UI: "Which agents touch EU customer data?"
    UI->>Orch: forward question + session context
    Orch->>LLM: classify intent / plan retrieval
    LLM-->>Orch: plan: graph_query + vector_search
    Orch->>Vec: hybrid search (docs/telemetry summaries)
    Vec-->>Orch: relevant passages + citations
    Orch->>Graph: query DataAsset nodes WHERE residency_region = EU
    Graph-->>Orch: matching Agent/DataAsset edges
    Orch->>LLM: generate grounded answer (context + citations)
    alt sufficient grounding
        LLM-->>Orch: answer with inline citations
    else insufficient grounding
        LLM-->>Orch: "insufficient information" response
    end
    Orch->>UI: deliver answer + citation links
    UI->>User: render answer
    opt follow-up action
        User->>UI: "recommend a replacement agent"
        UI->>Orch: forward follow-up
        Orch->>Rec: recommendation_lookup(context)
        Rec-->>Orch: ranked candidates
        Orch->>UI: present recommendations
    end
```

## 6. Multi-Cloud Deployment Topology

```mermaid
flowchart TB
    subgraph Azure["Azure Deployment Profile"]
        AzEventHubs["Azure Event Hubs"]
        AzCosmos["Cosmos DB (Gremlin) or Neo4j AuraDB"]
        AzFabric["Microsoft Fabric / Synapse"]
        AzSearch["Azure AI Search"]
        AzAKS["AKS"]
    end

    subgraph AWS["AWS Deployment Profile"]
        AwsKinesis["MSK (Kafka) / Kinesis"]
        AwsNeo4j["Neo4j (self-managed on EKS)"]
        AwsAnalytics["ClickHouse on EC2 + Databricks on AWS"]
        AwsVector["Qdrant (self-hosted)"]
        AwsEKS["EKS"]
    end

    subgraph GCP["GCP Deployment Profile"]
        GcpPubSub["Pub/Sub"]
        GcpNeo4j["Neo4j (self-managed on GKE)"]
        GcpAnalytics["ClickHouse on GCE + Databricks on GCP"]
        GcpVector["Qdrant (self-hosted)"]
        GcpGKE["GKE"]
    end

    subgraph OnPrem["On-Prem / Air-Gapped Profile"]
        OpKafka["Self-managed Kafka"]
        OpNeo4j["Neo4j (self-managed)"]
        OpClickHouse["ClickHouse (self-managed)"]
        OpQdrant["Qdrant (self-hosted)"]
        OpK8s["Kubernetes (bare-metal / VMware)"]
    end

    CommonCore["NeuroSphere Core Services\n(Graph Service abstraction, Catalog, Recommendation Engine, Copilot Orchestrator)"]

    Azure --> CommonCore
    AWS --> CommonCore
    GCP --> CommonCore
    OnPrem --> CommonCore
```

## 7. Phased Roadmap (Gantt Chart)

```mermaid
gantt
    title NeuroSphere Phased Roadmap
    dateFormat  YYYY-MM-DD
    axisFormat  %b %Y

    section Phase 0 - Foundations
    Graph schema + ingestion skeleton      :p0, 2026-01-05, 42d

    section Phase 1 - Telemetry + Catalog GA
    Production ingestion + catalog         :p1, after p0, 63d

    section Phase 2 - Visual Map + Rec Engine v1
    Live topology map + recommendations    :p2, after p1, 63d

    section Phase 3 - AI Copilot
    RAG + tool-calling + eval harness       :p3, after p2, 70d

    section Phase 4 - Multi-Cloud + Compliance
    AWS/GCP/on-prem + SOC2/ISO27001 prep    :p4, after p3, 77d

    section Phase 5 - GA Hardening
    Load/chaos testing + launch             :p5, after p4, 35d
```

---
*All architecture/technology choices reflected here (Neo4j, Cosmos DB Gremlin, ClickHouse, Databricks, Fabric, Azure AI Search, Qdrant, Kafka, Event Hubs, Pub/Sub) are grounded in the cited sources in NeuroSphere-PRP.md. Framework choice for the Copilot Orchestrator (Azure AI Foundry Agent Service vs. Semantic Kernel vs. LangGraph) is marked ⚠ needs verification pending a dedicated bake-off.*
