# Runbook: copilot (model endpoint, readiness and reason codes)

The copilot is the governed chat and report-drafting assistant. It answers read-only questions
through bounded tools and drafts changes that go through the same confirmation and approval path as
the buttons; it never executes a change by itself. It is **off by default** (`NS_COPILOT_MODE=disabled`).
With it off, chat that needs a model and drafting answer 503 `copilot_unconfigured`, and the rest of
the product is unaffected. Related: [runtime-composition.md](runtime-composition.md),
[hosted-demo.md](../deploy/hosted-demo.md).

## Choose a model, region and SKU

The model adapter is gated by the capability matrix
(`packages/core/neurosphere_core/capabilities/data/foundry.yaml`). The builder asks for
`foundry.<NS_COPILOT_MODEL_FEATURE>` with `NS_COPILOT_SKU` in the deployment cloud and
`NS_COPILOT_REGION`. A matching row with `availability: available` enables it. **No row, or an
unverified or unavailable row, means the adapter is disabled with a reason code** (see the table
below); it is never silently allowed.

Commercial rows that exist (documentation-derived, observed 2026-11-11, `model_gpt_4_1_mini`,
version 2025-04-14, quota not captured; availability only, no authorization claimed):

| SKU | Regions |
|---|---|
| Global Standard | brazilsouth, canadaeast, centralus, eastus, eastus2, northcentralus, southcentralus, westus, westus3 |
| Data Zone Standard | centralus, eastus, eastus2, northcentralus, southcentralus, westus, westus3 |

`canadacentral` has no Global Standard row for this model, so it stays disabled. Government rows
are separate (`foundry.model_*` under `usgov*` regions). To use another model, region or SKU, add a
dated row with a cited source first.

## Create the deployment and grant access

1. In the target Foundry or Azure OpenAI account, create a model deployment (for example
   `gpt-4.1-mini`, version 2025-04-14, SKU Global Standard) in a region from the table. Note the
   deployment name and the account endpoint (`https://<account>.openai.azure.com`).
2. Grant the identity the API runs as the **Cognitive Services OpenAI User** role on the account.
   Locally that identity is you (after `az login`); hosted it is the API's managed identity.
   There are no keys: the adapter uses a token credential only.

## Variables (`NS_COPILOT_*`)

Blank values are treated as unset. Never set a key, secret, password or connection-string variable:
the builder refuses any credential-shaped `NS_COPILOT_*` name at startup.

| Variable | Meaning |
|---|---|
| `NS_COPILOT_MODE` | `disabled` (default), `approved_endpoint` or `foundry_agent` |
| `NS_COPILOT_ENDPOINT` | https endpoint of the account; must belong to the deployment cloud |
| `NS_COPILOT_DEPLOYMENT` | deployment name (or agent name for `foundry_agent`) |
| `NS_COPILOT_API_VERSION` | optional API version |
| `NS_COPILOT_REGION` | region used to match the matrix row |
| `NS_COPILOT_MODEL_FEATURE` | matrix feature, for example `model_gpt_4_1_mini` |
| `NS_COPILOT_SKU` | matrix SKU, for example `Global Standard` |
| `NS_COPILOT_OAUTH_SCOPE` | optional token scope; Commercial and Government approved-endpoint have defaults |

`docker-compose.yml` passes all of these through to the API (`NS_COPILOT_MODE` defaults to
`disabled`, the rest to empty).

## Local real-model use

A containerized API has **no `az login`** and no managed identity, so it cannot reach a real model.
Run the API on the host instead, after `az login` (DefaultAzureCredential picks up the Azure CLI
when `NS_ENV=local`). Use the same emulator stack, then start the API from the host with the
variables set:

```bash
az login
docker compose up -d --wait            # emulators only
export NS_COPILOT_MODE=approved_endpoint
export NS_COPILOT_ENDPOINT=https://<account>.openai.azure.com
export NS_COPILOT_DEPLOYMENT=<deployment-name>
export NS_COPILOT_REGION=centralus
export NS_COPILOT_MODEL_FEATURE=model_gpt_4_1_mini
export NS_COPILOT_SKU="Global Standard"
# then start the API on the host as in docs/runbooks/install.md
```

Each model call is a paid call: get operator approval first.

## Hosted use

`scripts/gates/hosted_demo.py` takes `--copilot-mode approved_endpoint` with `--copilot-endpoint`
and `--copilot-deployment`; `plan` and `deploy` pass every template parameter from their own flags.
The API's managed identity needs the role above. See
[hosted-demo.md](../deploy/hosted-demo.md).

## Status and readiness

`GET /api/v1/copilot/status` returns the copilot state (`ready`, `disabled` or `failed`) and a
`reason_code` when it is not ready. A `failed` copilot also appears in `/readyz`. Disabled by
choice (`NS_COPILOT_MODE=disabled`) is not a failure.

## Reason codes

| Code | Cause | Fix |
|---|---|---|
| `copilot_unconfigured` | No copilot collaborator is composed (mode disabled, or the app has none); chat/drafting answer 503 | Set `NS_COPILOT_MODE` and the variables above, restart |
| `misconfigured` | Mode set but endpoint, deployment, region or model feature missing, or a value fails validation | Set all of `NS_COPILOT_ENDPOINT`, `_DEPLOYMENT`, `_REGION`, `_MODEL_FEATURE`; check the deployment-name pattern |
| `endpoint_missing` | No endpoint configured | Set `NS_COPILOT_ENDPOINT` |
| `endpoint_invalid` | Endpoint is not https, has no host, or embeds credentials | Use `https://<account>.openai.azure.com` with no userinfo |
| `endpoint_cloud_mismatch` | Endpoint host belongs to the other cloud (Commercial host in Government, or the reverse) | Use an endpoint from the deployment's own cloud; Government never uses Commercial |
| `endpoint_not_approved` | Commercial host is not an approved Azure AI suffix (`.openai.azure.com`, `.services.ai.azure.com`, `.cognitiveservices.azure.com`) | Use an approved host |
| `endpoint_refused` | The builder could not accept the endpoint and no more specific code applied | Check the endpoint against the two rows above |
| `model_feature_missing` | `NS_COPILOT_MODEL_FEATURE` unset, so availability is unverified | Set it to a matrix feature |
| `not_verified` | No matrix row (or an unverified row) for the model, cloud, region and SKU | Pick a region and SKU with a row, or add a dated row with a cited source |
| `not_available_in_region` / `not_available_in_cloud` | The matrix row says the model is unavailable there | Choose another region or SKU |
| `preview_only` | The row is preview and preview is not allowed | Use a GA model or region |
| `not_configured` | That adapter kind has no configuration | Configure it, or ignore if unused |
| `capability_unavailable` | Generic matrix refusal, or an adapter created while disabled | Read the `reason` on `/api/v1/copilot/status` |
| `credential_required` | A REST adapter was built without a token credential | Internal; check the credential wiring at startup |
| `token_scope_required` | `foundry_agent` in Government has no default scope | Set `NS_COPILOT_OAUTH_SCOPE` |
| `copilot_conversation_store_invalid` | The conversation store override has the wrong type | Fix the store wiring |
| `model_adapter_invalid` | The adapter override has the wrong type | Fix the adapter wiring |

## Government

Government deployments accept Government endpoints only (`.azure.us`, `.usgovcloudapi.net`). A
Commercial endpoint is refused with `endpoint_cloud_mismatch` and Government data is never routed to
Commercial. Commercial matrix rows are never consulted for a Government deployment. The Foundry
Agent adapter stays disabled in Government until `foundry.agent_function_calling` is verified.

## Open gate

A live answer from a real model has **not** been run: it needs an operator-approved environment and
`NS_LIVE_APPROVED=1`. The Foundry Responses wire shape is documentation-derived. Matrix rows state
availability only; they are not an authorization or compliance claim. Tracked under G01 and G05 in
[RESEARCH-AND-GATES.md](../RESEARCH-AND-GATES.md).
