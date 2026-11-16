# AWS Bedrock reference connector (PRP-62)

A seventh reference connector built on the connector SDK. It reads **metadata only** for one AWS
account and one region: the Bedrock inventory, hourly CloudWatch usage per model, daily Cost
Explorer cost for the Bedrock service, and whether model invocation logging is configured.

It is read-only (`advisory=true`, no write support), **Commercial only** (a Government NeuroSphere
deployment, or a GovCloud or China region, is refused with the typed `capability_unavailable`
error, reason `aws_bedrock_government_unsupported`, before any request), and holds **no credential
at rest**. It never invokes a model and never reads a prompt, a response, a log or an object.

Status: **built (PRP-62), not live-tested.** It passes the contract kit with fakes and botocore
stubs. No AWS account has been read, so gate G04 stays OPEN; the live run is handed to PRP-64.
Nothing here claims AWS GovCloud, FedRAMP or compliance coverage.

## What it returns

| Method | Source (boto3 client, operation) | Output |
|---|---|---|
| `inventory()` | `bedrock` `ListFoundationModels`, `ListCustomModels`, `ListProvisionedModelThroughputs`, `ListGuardrails`; `bedrock-agent` `ListAgents` | `BedrockInventory`: id, name, status, provider, modality names, created time. Each list is capped (`max_items`), sets `truncated` and partial coverage at the cap, and is `None` when its call failed, never `[]`. |
| `usage(window, model_ids)` | `cloudwatch` `GetMetricData`, namespace `AWS/Bedrock`, metrics `Invocations`, `InputTokenCount`, `OutputTokenCount`, dimension `ModelId`, `Sum` over 3600 s | `BedrockUsageResult`: one point per model, metric and hour of the explicit window. A missing datapoint is `None`, not 0. |
| `cost(window)` | `ce` `GetCostAndUsage`, `DAILY`, `UnblendedCost`, filter and group on `SERVICE` = `Amazon Bedrock` | `BedrockCostResult`: amount, currency, and `amount_kind` `estimated` or `invoiced` exactly as the API's `Estimated` flag reports. A service-day with no row is `None`. No price is computed. |
| `logging_state()` | `bedrock` `GetModelInvocationLoggingConfiguration` | `InvocationLoggingState`: `configured`, `cloudwatch`, `s3` booleans. Bucket and log-group names are dropped inside the reader. |

Third-party models sold through Bedrock can be billed under other Cost Explorer `SERVICE` names.
Only `Amazon Bedrock` is read by default; pass `cost_services=` to add others after checking them
in your account (not verified here).

## Verified API surface (observed 2026-11-16)

Every operation and IAM action was read in the PRP-62 session, not taken from memory:

- Operation names, parameters and response shapes: the botocore 1.44.3 service models for
  `bedrock`, `bedrock-agent`, `cloudwatch` and `ce` (this is the contract boto3 enforces; the
  tests build real botocore clients with `Stubber`, so requests and responses are validated
  against these models offline).
- IAM action names and read-only classification: the AWS Service Reference
  (`https://servicereference.us-east-1.amazonaws.com/v1/{bedrock,ce,cloudwatch}/{bedrock,ce,cloudwatch}.json`),
  all eight actions present with `IsWrite` false.
- CloudWatch metrics and dimensions:
  <https://docs.aws.amazon.com/bedrock/latest/userguide/monitoring-cw.html>
  (`Invocations`, `InputTokenCount`, `OutputTokenCount`; `ModelId` dimension; the page notes that
  metrics for a request that fails before the model is known are published without `ModelId`, so
  per-model sums can undercount errors).
- Cost Explorer request and response:
  <https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_GetCostAndUsage.html>
  (`Granularity` `DAILY`, `Metrics` including `UnblendedCost`, `NextPageToken`,
  `ResultsByTime[].Estimated`, end date exclusive).

## Least-privilege read-only IAM policy

Attach this to the role (web identity) or user (static key). The test
`tests/test_aws_bedrock_live_check.py` keeps this block equal to
`neurosphere_connector_aws_bedrock.iam.IAM_POLICY`.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "NeuroSphereBedrockMetadataRead",
      "Effect": "Allow",
      "Action": [
        "bedrock:GetModelInvocationLoggingConfiguration",
        "bedrock:ListAgents",
        "bedrock:ListCustomModels",
        "bedrock:ListFoundationModels",
        "bedrock:ListGuardrails",
        "bedrock:ListProvisionedModelThroughputs",
        "ce:GetCostAndUsage",
        "cloudwatch:GetMetricData"
      ],
      "Resource": "*"
    }
  ]
}
```

Deliberately absent: every `bedrock:Invoke*` and `Converse*` action, `logs:*`, `s3:*`, `iam:*`
and any write or tagging action. `Resource` is `*`; the Service Reference lists resource types
for three of the actions (`guardrail`, `billingview`, `dataset`), and scoping to them is up to the
operator and not verified here.

## Credentials

The SDK client is built **per call** from explicit credentials and an explicit region. The host's
`~/.aws` files and profiles are never used, botocore's own retries are off, and no key is stored on
the connector, logged or put in an exception (the AWS error message is never copied; only the error
code and HTTP status are read).

1. **Web identity (preferred, no secret at rest).** `WebIdentityProvider` takes a callable that
   returns a short-lived OIDC token (a Microsoft Entra token in the intended deployment) and
   exchanges it through STS `AssumeRoleWithWebIdentity` (an unsigned request) for session
   credentials cached only until five minutes before expiry. The role's trust policy must name your
   OIDC provider and the exact `aud` and `sub` of the NeuroSphere workload; do not use a wildcard
   `sub`. The role carries only the policy above. The manifest declares
   `auth_mode: workload_identity_federation` and no credential reference.
2. **Static access key held in Key Vault.** `StaticKeyProvider` asks a `CredentialBroker` for the
   secret on every call, so `notify_rotated` takes effect on the next request. The secret is a JSON
   document with `access_key_id`, `secret_access_key` and an optional `session_token`. Prefer a
   key for a dedicated IAM user that has only the policy above, and rotate it. The manifest
   declares `auth_mode: vault_reference` and the Key Vault reference only.

## Resilience

AWS throttling (including Cost Explorer's `LimitExceededException`) maps to `rate_limited`;
HTTP 5xx and connection failures map to `dependency_transient`; access denied to `forbidden`;
rejected credentials to `unauthorized`. The reader retries rate-limited and transient failures at
most three times with capped exponential backoff, applies a page budget to every list (default 5
pages) and stops on a repeated pagination cursor. Health reflects only the last error class.

## Cost Explorer request cost

Each Cost Explorer API request costs 0.01 USD on the primary billing view
(<https://docs.aws.amazon.com/cost-management/latest/userguide/ce-api.html>, observed 2026-11-16).
`cost()` makes one request per page of results, capped by the reader's page budget; a one-day
window is normally a single request. Do not poll it on a tight loop.

## Live check (operator-run, OPEN until run)

`scripts/live_check.py` refuses with exit 2 unless `NS_LIVE_APPROVED=1` (no SDK import, no network)
and otherwise performs one bounded read of each source and writes a whitelisted evidence JSON
(counts and booleans only) to `docs/evidence/G04/aws-bedrock-<stamp>.json`.

Expected request count at `--max-pages 2`: at most 10 inventory requests (5 lists), 1 CloudWatch
request, at most 2 Cost Explorer requests (about 0.02 USD) and 1 logging request. Web identity:

```bash
NS_LIVE_APPROVED=1 uv run python connectors/reference/aws-bedrock/scripts/live_check.py \
  --region us-east-1 --auth web-identity --role-arn <role-arn> --token-file <oidc-token-file> \
  --budget-cap-usd 1 --max-pages 2
```

Static key (the operator exports `NS_AWS_BEDROCK_KEY_JSON` in their own shell; never put it in a
file or a chat):

```bash
NS_LIVE_APPROVED=1 uv run python connectors/reference/aws-bedrock/scripts/live_check.py \
  --region us-east-1 --auth static-key --budget-cap-usd 1 --max-pages 2
```

Exit codes: 2 refused (nothing ran), 3 OPEN (a prerequisite is missing or AWS refused), 1 the
connector failed the contract or a source failed, 0 every source answered.

## Not built here

A stored connector configuration and a worker role (needs a new `ConnectorConfig.connector_kind`
value in the contracts and a role in `services/workers/**`; follow-up), mapping Bedrock usage into
`TelemetryEvent` or ledger entries, AWS GovCloud, any write action on AWS, shadow-AI discovery on
AWS, and the live run itself.
