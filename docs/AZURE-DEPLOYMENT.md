# Azure deployment requirements — v1.1
Authoritative plan: PRP.md and docs/ARCHITECTURE.md. This is a design, not a deployed environment.
Choose Commercial/Government, approved regions, AKS or smaller App Service profile and available Fabric/Synapse/Azure Databricks adapter. Disable unsupported choices with sourced reasons; no blanket Fabric ban or cross-cloud fallback.
Read-only consented resource scan uses authorized subscription visibility. Preview reuse/create/skip for APIM, model endpoints, storage, Event Hubs, analytics, Key Vault and monitoring. Validate owner, network/DNS, permissions, quota, SKU, residency and lifecycle before reuse. Plan approval precedes provisioning.
Use Bicep modules and supported workspace/capacity provisioning adapter where ARM is insufficient. Shared-resource ownership register prevents uninstall/modification of enterprise assets. Private endpoints/managed identities where supported; exceptions reviewed.
Cloud authorities/audiences/endpoints and capabilities are configuration, not naive string replacements. Actual Government service/feature/authorization evidence required by G01/G02 in RESEARCH-AND-GATES.md.
DR includes secondary networking/identity/capacity, data replication or durable replay and backup restore. Metadata-only Event Hubs geo-DR cannot satisfy event-data RPO. Measure failover/failback targets.
