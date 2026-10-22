# Inheritance and responsibility matrix (Azure Government)

Status: evidence aid, not an assessment. NeuroSphere is not FedRAMP authorized; the authorizing official decides. No certification or authorization deadline is promised.

Evidence for each dependency lives in the dated register at `docs/evidence/G02/register.yaml` (feature, region, SKU, availability, GA or preview, authorization-boundary status, source and retrieval date). This matrix says who is responsible for what; the register says what was observed and when.

## Ground rules

- Availability, GA/preview status and authorization are separate facts. A service being available in a region says nothing about its authorization, and a listing in an audit scope is not an authorization of this application.
- Controls inherited from an Azure service's audit-scope listing do not automatically authorize NeuroSphere. They are inputs to the customer's own assessment.
- Azure Government, GCC, GCC High and DoD are different environments. They are not interchangeable and no row in the register is an alias of another. Fabric in GCC High, for example, says nothing about GCC or DoD.
- Government data is never bridged to Commercial to fill a feature gap. A feature that is unavailable or `not_verified` in the target environment is disabled, not substituted.
- NeuroSphere's own controls are customer-assessed: NeuroSphere supplies the implementation and evidence, and the customer's security team and authorizing official decide whether they are sufficient.
- SSP narratives, control-by-control mappings and the POA&M are out of scope here (PRP-23).

## Responsibility by control area

| Control area | Microsoft | Customer | NeuroSphere (customer-assessed) |
|---|---|---|---|
| Physical and infrastructure | Datacenter, hardware, host and hypervisor, regional operations of Azure Government | Choose region and environment; confirm the region set fits the workload | Documents the allowed region set and the features each region lacks; does not select a region silently |
| Platform service controls inherited via audit scope | Operates the services; maintains the audit-scope listings (FedRAMP High, DoD IL levels as listed per service) | Reads the listings for the services in use; decides what, if anything, it may inherit; handles extra IL5 configuration where required | Records the listing per dependency in the register as `audit_scope_listed`, never as authorized; flags previews and SaaS |
| Identity and tenant configuration | Operates Microsoft Entra ID in the Government cloud | Tenant, Conditional Access, MFA policy, role assignments, privileged-access process | Uses Entra and managed identity; enforces authorization on every query, tool, export, push and action path; privileged users get scoped permissions |
| Network isolation and private endpoints | Provides private endpoint, DNS and virtual network capabilities | Network design, private DNS, firewall and egress policy, connectivity to agency networks | Ships Government egress allowlist and network policy; no Commercial endpoint in Government profiles; in-cluster proof of no Commercial egress is OPEN |
| Data classification and residency | Keeps service data in the selected cloud and region as documented per service | Classifies data, picks the environment and region, owns the privacy policy for real ingestion | Synthetic sandbox is isolated; real ingestion only through authorized connectors; never bridges Government data to Commercial |
| Key management | Operates Key Vault and the encryption options each service offers | Key custody, rotation, customer-managed key decisions (some services lack them, for example Fabric in GCC High) | Holds no secrets in files, prompts or logs; uses a vault and managed identity in production; disables CMK-dependent options where unsupported |
| Logging and monitoring | Operates Azure Monitor, Log Analytics and Application Insights | Retention, SIEM integration, alerting, incident response | Emits audit events for actions and approvals; uses the Government connection-string endpoint override; log retention policy is the customer's |
| Application controls of NeuroSphere itself | Not responsible | Assesses NeuroSphere against its own control baseline; accepts or rejects residual risk | Implements the durable action executor, approvals, audit and verification; bounded structured tools only, no arbitrary generated SQL, Cypher or JavaScript |
| SSP and ATO | Provides inheritable documentation for its own services | Owns the system security plan, assessment, ATO decision and continuous monitoring through its authorizing official | Supplies evidence, the register and the responsibility split; makes no claim of authorization, ATO, or equivalence between environments |

## What remains open

- The agency authorizing-official determination is customer-owned and cannot be closed by this repository.
- Government AKS and App Service live profile runs need an approved Government subscription and `NS_LIVE_APPROVED=1`; none has run.
- The in-cluster proof of no Commercial egress has not run.
- Cosmos DB, AI Search and Event Hubs Government token audiences are unverified.
- Fabric availability in GCC and DoD is unverified; Fabric in GCC High has a FedRAMP High assessment in progress, which is not an authorization.
- Foundry agent feature availability in Government has conflicting first-party sources, recorded as `not_verified` in the register.
