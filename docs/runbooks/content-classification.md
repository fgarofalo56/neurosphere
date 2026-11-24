# Content classification and typed redaction

`neurosphere_core.classification` (PRP-101) is a pure core library that finds structured
sensitive identifiers and credentials in text and replaces each one with a typed placeholder
`[[ns-redacted:<detected_category>]]` (the PRP-99 grammar), so the opt-in interaction capture
path can redact content at the ingest edge before anything is encrypted or stored. It makes no
I/O and reads no settings; findings carry a category, counts and placeholder offsets, never the
matched text, and any detector or engine error fails the whole part closed (`RedactionFailed`
with a reason code and no text). Credentials and secrets are always redacted; payment card
numbers are redacted by default; other detected types are redacted or kept per capture policy,
default redact.

Coverage: structured identifiers only: names, postal addresses and free-text health or legal
content are not detected.

## Detectors

_Placeholder: filled by PRP-101 items 2-5 (detector list, kinds, confidence, detector-set
version)._

## Configuration

_Placeholder: filled by PRP-101 items 5 and 8 (redaction modes, budget, chunking)._

## Measured precision and recall

_Placeholder: filled by PRP-101 item 6 (measured table per detector with the detector-set
version)._

## Adding customer dictionaries and patterns

_Placeholder: filled by PRP-101 items 4 and 8 (dictionary limits, pattern safety check, reason
codes)._

## Sources

Only formats listed here are coded. A format that could not be verified against vendor
documentation is not added. External sources were retrieved on 2026-11-24.

### Repo-carried formats (no external source)

- `packages/core/neurosphere_core/copilot/models/redaction.py` lines 64-65: `sk`, `pk`, `ghp`,
  `gho`, `xoxb`, `xoxa` and `xoxp` prefixed keys (prefix, then `-` or `_`, then 16 or more
  characters), and AWS access key ids (`AKIA` plus 16 uppercase letters or digits).
- `tests/contracts/validators.py` `SECRET_TEXT_PATTERNS` (mirrors the PRP-99 `RedactedContent`
  `secret_free_text` rule): private key block (`-----BEGIN ... PRIVATE KEY-----`), JWT
  (`eyJ` header, three dot-separated base64url segments), bearer token (`Bearer` plus 8 or more
  token characters), AWS access key id (`AKIA` or `ASIA` plus 16), GitHub token (`gh[pousr]_`
  plus 20 or more, `github_pat_` plus 20 or more), `sk-` key (20 or more), Azure storage or
  Service Bus key assignment (`AccountKey=` or `SharedAccessKey=` plus 8 or more base64
  characters), SAS signature (`sig=` plus 20 or more), URL with userinfo
  (`scheme://user:password@`).

### Verified external formats

| # | Format | Source (retrieved 2026-11-24) | Exact format |
|---|--------|-------------------------------|--------------|
| 1 | Azure Storage connection string | <https://learn.microsoft.com/azure/storage/common/storage-configure-connection-string> | `DefaultEndpointsProtocol=<protocol>;AccountName=<name>;AccountKey=<key>[;EndpointSuffix=<suffix>]` where `<protocol>` is `http` or `https`; explicit-endpoint variants `BlobEndpoint=...;QueueEndpoint=...;FileEndpoint=...;TableEndpoint=...`; the SAS connection string variant ends `SharedAccessSignature=<sas>` |
| 2 | Azure Storage account key | <https://learn.microsoft.com/purview/sit-defn-azure-storage-account-key> | 86 characters of `[A-Za-z0-9/+]` followed by `==` (88 in total), after `AccountKey` with 0 to 2 spaces around `=` |
| 3 | Event Hubs / Service Bus connection string | <https://learn.microsoft.com/azure/event-hubs/event-hubs-get-connection-string> | `Endpoint=sb://<Namespace>.servicebus.windows.net/;SharedAccessKeyName=<KeyName>;SharedAccessKey=<KeyValue>[;EntityPath=<EventHubName>]` |
| 4 | Event Hubs SAS token | <https://learn.microsoft.com/azure/event-hubs/authenticate-shared-access-signature> | `SharedAccessSignature sr=<uri>&sig=<signature>&se=<expiry>&skn=<keyname>`; `sig` is a URL-encoded base64 HMAC-SHA256 |
| 5 | Azure Storage SAS | <https://learn.microsoft.com/rest/api/storageservices/create-account-sas> and <https://learn.microsoft.com/azure/storage/common/storage-sas-overview> | query parameters `sv`, `ss`, `srt`, `sp`, `se`, `st`, `spr`, `sig`; `sig` is a base64 HMAC-SHA256, URL-encoded in the URI |
| 6 | Azure OpenAI / Foundry and Azure AI services keys | <https://learn.microsoft.com/azure/foundry/openai/reference#authentication>, <https://learn.microsoft.com/azure/ai-services/authentication>, <https://learn.microsoft.com/azure/api-management/api-management-subscriptions>, <https://learn.microsoft.com/purview/sit-defn-azure-cognitive-service-key> | key sent in the `api-key` HTTP header; Azure AI services and API Management keys in the `Ocp-Apim-Subscription-Key` header and the `subscription-key` query parameter; key shape 32 hex characters. Detected only with the header or assignment context, never bare |
| 7 | Microsoft Entra client secret | <https://learn.microsoft.com/purview/sit-defn-azure-ad-client-secret> | up to 40 characters of `[A-Za-z0-9-_.~]`; context only (for example `AppSecret=`, `client_secret=`), handled by credential phrasing |
| 8 | GitHub token prefixes | <https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/about-authentication-to-github> | `ghp_` (personal access token, classic), `github_pat_` (fine-grained personal access token), `gho_` (OAuth), `ghu_` (GitHub App user-to-server), `ghs_` (GitHub App installation), `ghr_` (GitHub App refresh). A stateless installation-token format `ghs_APPID_JWT` is rolling out: no fixed 40-character length is assumed |

### Source to category mapping

| Category | Fed by |
|----------|--------|
| `private_key` | private key block (repo-carried) |
| `jwt` | JWT (repo-carried) |
| `bearer_token` | bearer token (repo-carried) |
| `cloud_access_key` | AWS access key ids, `AKIA` and `ASIA` (repo-carried) |
| `vendor_api_key` | GitHub tokens (source 8 and repo-carried); `sk-`, `sk_`, `pk_` and `xox*` keys (repo-carried); `api-key` and `Ocp-Apim-Subscription-Key` header values and `subscription-key` parameter values (source 6) |
| `connection_string` | Azure Storage connection strings and account keys (sources 1 and 2); Event Hubs and Service Bus connection strings (source 3); `AccountKey=` and `SharedAccessKey=` assignments (repo-carried); SAS `sig=` signatures and SAS tokens (sources 4 and 5; Clarification 10) |
| `url_with_credentials` | URL with userinfo (repo-carried) |
| `password_assignment` | credential phrasing such as `password=` and `client_secret:`, including Entra client secrets (source 7) |
| `other` | long opaque runs, detector `opaque_secret`, low confidence, always replaced (Clarification 9) |
