# Configuration detections and shadow-AI discovery

The `detections` worker role reads platform configuration metadata and stores what it finds as
recommendations that stewards review. It answers three narrow questions and nothing else.

Status: NeuroSphere is not FedRAMP authorized; the authorizing official decides. A finding says a
configuration differs from what the operator declared. It never says a deployment is safe, adequate
or approved, and no finding means only that nothing differed in what was read.

## What it checks

| Rule (generator id) | Question | Finding kind |
|---|---|---|
| `detect.content_filter_policy` | Does each Foundry model deployment of the listed accounts have a content-filter policy name inside the acceptable list? | `configuration_finding` |
| `detect.content_filter_policy.unset_only` | The same rule when no acceptable list is declared: only a deployment with no policy name at all is reported. | `configuration_finding` |
| `detect.gateway_policy_fragment` | Does each registered APIM gateway's latest inventory list every required policy-fragment name? | `configuration_finding` |
| `detect.shadow_ai_account` | Does Azure Resource Graph show an AI account that no catalog entity or configured discovery target names? | `unregistered_ai_resource` |

Metadata only. The role reads deployment names and content-filter policy names, policy-fragment
names, and for AI accounts the name, location, tag keys and a digest of the ARM resource id. It
never captures prompts, responses or request bodies, never reads policy XML, and never reads keys
or tag values.

## What a finding means and does not mean

- `configuration_finding`: one deployment or gateway differs from the declared expectation. The
  recommendation's subject is the deployment's catalog id (`...:foundry:model_deployment:<name>`)
  or the gateway (`...:apim:gateway:<id>`). The observed value (policy name or `unset`, or the
  missing fragment names) is carried as evidence ids.
- `unregistered_ai_resource`: Resource Graph shows an AI account that is not referenced. The
  subject is a synthetic id (`...:azure_resource_graph:ai_account:<name>-<digest>`) because the
  account has no catalog entity. It does not mean the account is unauthorized or unsafe; it means
  nobody has told NeuroSphere about it.
- Every finding is advisory, rule based, has an unresolved owner (so it routes to stewards) and
  carries no score. There is no write and no auto-remediation; changing a deployment goes through
  the shared action executor.
- A read that failed is coverage `unknown` and emits nothing. A rule with nothing declared to
  compare against is `not_evaluated`. Where the capability matrix says a read does not exist in
  the cloud, the coverage is `capability_unavailable` and nothing is emitted.

## How matching works (shadow AI)

An account is known when its name, case-insensitive, equals the resource part of the
`foundry_project` attribute (`resource/project`) of a catalog `model_deployment` entity, which is
how the `foundry_discovery` role writes it, or a resource name from the `foundry_discovery`
targets, or an account listed in `NS_WORKER_DETECT_FOUNDRY_ACCOUNTS`. This is an assumption about
how catalog entities are populated: an estate that curates deployment entities without that
attribute will see its accounts reported until they are listed explicitly. If the catalog read
fails or is cut off by the item cap, the rule reports `unknown` rather than guess.

## Settings

All prefixed `NS_WORKER_DETECT_`. Add `detections` to `NS_WORKER_ROLES` (hosted role wiring comes
with PRP-58 and PRP-63). With `ENABLED` unset the role idles with one info log, so `all` is safe.

| Variable | Meaning |
|---|---|
| `ENABLED` | `true` to run. Anything else idles. |
| `DOMAIN_ID` | Canonical domain id that receives findings whose subject has no catalog domain (required when enabled). |
| `INTERVAL_SECONDS` | Seconds between passes (60 to 86400, default 3600). Findings expire after two intervals unless the next pass re-stores them. |
| `FOUNDRY_ACCOUNTS` | Comma list of `[cloud:]subscription_id/resource_group/account/location`. Enables the content-filter rule. |
| `ACCEPTABLE_RAI_POLICIES` | Comma list of acceptable content-filter policy names. Empty means only `unset` is reported. |
| `REQUIRED_APIM_FRAGMENTS` | Comma list of policy-fragment names every registered gateway of the domain must have. Enables the gateway rule. |
| `SUBSCRIPTIONS` | Comma list of `[cloud:]subscription_id` for the Resource Graph read. Enables the shadow-AI rule. |
| `MAX_ITEMS` | Per-list cap per pass (1 to 5000, default 500). A cut-off read is reported as partial. |

A bad value fails this role (not the process) with a machine reason such as
`detections_domain_id_invalid`, `detections_foundry_accounts_invalid`,
`detections_subscription_cloud_mismatch` or `detections_no_rules_configured`.

Government deployments use the Government ARM and Resource Graph hosts from the cloud profile and
never a Commercial host. A subscription or account tagged with another cloud is refused.

## Where findings appear

`GET /api/v1/recommendations/domains/{domain}?kind=configuration_finding` and
`?kind=unregistered_ai_resource`, for a principal whose scope includes the domain, and the
recommendations page. Findings are also counted by the `configuration_findings` compliance
evidence source (open findings per kind) for the monitoring and inventory controls it is mapped
to; see the compliance evidence runbook for how to read a bundle.

## Operator checklist for the live read (OPEN)

Not run in the build session. It needs an operator, approval for a live read and read-only access
(Reader) on a Commercial subscription the operator names. Government stays OPEN.

1. Grant the worker identity Reader on the named accounts and subscriptions; no write role.
2. Set the variables above with one known account and one account you expect to be reported.
3. Run one pass and confirm the expected findings appear and the known account does not.
4. Check the worker log shows counts and reason codes only.
5. Record what `raiPolicyName` looked like on real accounts and whether the Resource Graph columns
   matched; both were taken from documentation and the connector contract, not a live account.
