# Azure deployment path (reference)

The local POC promotes to Azure by swapping each open-source / local
component for its managed equivalent. CI does **not** require an Azure
subscription — `infra/azure/` (Bicep) and this doc are reference
material.

## Component swaps

| POC (local) | Azure managed target | Notes |
|---|---|---|
| Gateway OSS | **Azure API Management** | Same JWT / rate-limit / metering policies. |
| Local OIDC / JWT issuer | **Microsoft Entra ID** | `validate-azure-ad-token`. |
| Data API Builder (container) | **Data API Builder on Azure Container Apps** | OData v4 + `$metadata` discovery. |
| PostgreSQL | **Azure Database for PostgreSQL Flexible Server** | The system of record. |
| `classification.yml` | **Microsoft Purview** | Catalog, classification, lineage. |
| Prometheus / Grafana | **Azure Monitor / Application Insights** | Per-consumer metrics + tracing. |

## Constraint

**Microsoft Fabric and OneLake are excluded** — not available in Azure
Government / GCC. Do not introduce them.

> _Fill in the Bicep specifics under `infra/azure/` during the build._
