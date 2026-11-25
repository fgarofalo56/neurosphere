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

Measured on a labelled synthetic corpus (`packages/core/tests/content_detectors/corpus.py`):
every value is generated at runtime from the seed, no real data and no generated corpus file is
committed. Positives are every credential kind in `synth.py`, Luhn-valid cards (13 to 19 digits,
grouped and ungrouped, major-brand prefixes), IBANs (several countries, mod 97 valid), US SSNs,
emails, phones (E.164 and national), IPv4 and IPv6, MACs and GUIDs (also inside Azure resource
IDs). Hard negatives label nothing: credential lookalikes, Luhn-invalid card runs, invalid IBAN
checksums, excluded-area SSNs, dates, times, versions, order numbers, git SHAs, sha256 digests,
base64 ids and blobs, data URIs, SRI hashes, file paths, Python slices and `max_tokens` /
`prompt_tokens` / `token_count` lines. Each kind is placed in prose, JSON, YAML, env files, HTTP
headers, log lines, code, markdown tables and mixed rows, at text start and end and next to
punctuation.

The precision and recall below apply to that corpus only, within the
[coverage statement](#content-classification-and-typed-redaction) above (structured
identifiers only); they are not a claim about real traffic.

Gate (GD-19, Clarification 6): every credential category and Luhn-valid payment cards must
reach recall 1.0 end to end through `redact` (CI runs
`packages/core/tests/content_detectors/test_corpus_quality.py`). All other detectors are
measured and reported without a threshold. `opaque_secret` (category `other`) is not gated
(Clarification 9).

Regenerate the table after any detector change (the test fails when the table names another
detector-set version):

```bash
uv run python packages/core/tests/content_detectors/report_quality.py
```

<!-- quality-table:start -->
Detector set `ns-detectors-1.0.0`, digest `6baa0848db10974d24719376a657708beeb650c605ef0a3d3bb8ba554c7b3579`; corpus seed `20261124`, 1456 samples; measured 2026-11-25 with `report_quality.py`.

Per detector (each detector run alone on every sample):

| detector_id | category | support | precision | recall | gated | notes |
| --- | --- | ---: | ---: | ---: | --- | --- |
| `private_key` | `private_key` | 52 | 1.000 | 1.000 | yes | PEM blocks, truncated blocks spanned to end of text |
| `jwt` | `jwt` | 26 | 1.000 | 1.000 | yes |  |
| `bearer_token` | `bearer_token` | 26 | 1.000 | 0.923 | yes |  |
| `cloud_access_key` | `cloud_access_key` | 26 | 1.000 | 1.000 | yes |  |
| `vendor_api_key` | `vendor_api_key` | 260 | 1.000 | 1.000 | yes | includes api-key / subscription-key header and query values |
| `connection_string` | `connection_string` | 182 | 1.000 | 1.000 | yes | includes AccountKey=, SharedAccessKey=, SAS sig= and SAS URLs |
| `url_with_credentials` | `url_with_credentials` | 52 | 1.000 | 1.000 | yes |  |
| `password_assignment` | `password_assignment` | 52 | 1.000 | 0.981 | yes | chained labels leak (strict xfail, item 2 fix lane) |
| `opaque_secret` | `other` | 26 | 0.915 | 0.962 | no | category other; not gated (Clarification 9); over-redacts base64 |
| `payment_card` | `payment_card` | 70 | 1.000 | 1.000 | yes | Luhn-valid only |
| `iban` | `iban` | 79 | 1.000 | 1.000 | no | mod 97 checked |
| `us_ssn` | `us_ssn` | 57 | 1.000 | 1.000 | no | separated forms only |
| `email_address` | `email_address` | 57 | 0.528 | 1.000 | no |  |
| `phone_number` | `phone_number` | 52 | 1.000 | 1.000 | no | low precision by design |
| `ip_address` | `ip_address` | 82 | 0.512 | 1.000 | no | 4-part versions read as IPv4; `a::b` slices read as IPv6 |
| `mac_address` | `mac_address` | 26 | 1.000 | 1.000 | no |  |
| `guid` | `guid` | 85 | 1.000 | 1.000 | no | includes GUIDs inside Azure resource IDs |

End to end through `redact` with the default configuration (a span counts as redacted when no 6-character fragment of its secret survives; the gate excludes the `chained_label` context, shown separately):

| category | support | redacted | recall | gated | chained-label support | chained-label recall |
| --- | ---: | ---: | ---: | --- | ---: | ---: |
| `bearer_token` | 26 | 24 | 0.923 | yes | 0 | n/a |
| `cloud_access_key` | 26 | 26 | 1.000 | yes | 0 | n/a |
| `connection_string` | 182 | 182 | 1.000 | yes | 0 | n/a |
| `jwt` | 26 | 26 | 1.000 | yes | 0 | n/a |
| `other` | 26 | 25 | 0.962 | no | 0 | n/a |
| `password_assignment` | 40 | 39 | 0.975 | yes | 12 | 0.417 |
| `payment_card` | 70 | 70 | 1.000 | yes | 0 | n/a |
| `private_key` | 52 | 52 | 1.000 | yes | 0 | n/a |
| `url_with_credentials` | 52 | 52 | 1.000 | yes | 0 | n/a |
| `vendor_api_key` | 260 | 260 | 1.000 | yes | 0 | n/a |

`opaque_secret` matches on hard-negative samples: 79 (`base64_blob` 25, `data_uri` 26, `sha256_hex` 2, `sri_hash` 26).
<!-- quality-table:end -->

Precision counts a match as correct when it overlaps a labelled span of a compatible category
(credential categories and `other` are compatible with each other). Recall is the share of
labelled spans of the detector's category that one of its matches overlaps.

Known limits (declared, not bugs):

- US SSNs are found only with `-` or single-space separators; bare 9-digit runs are not.
- Phone numbers are low precision: separated digit groups such as reference numbers can match.
- A 4-part version string is a valid IPv4 address and is reported as `ip_address`; Python
  slices such as `x[a::b]` read as IPv6.
- A card number directly followed by a separated digit group can be missed (the groups merge
  into one candidate that fails Luhn).
- An IPv6 address directly after a colon (no space) is not found.
- Only ASCII digits are recognised (input is NFKC-normalised first).
- An email detector match inside a URL with credentials counts against email precision (the
  engine still replaces the whole URL span as `url_with_credentials`).

`opaque_secret` false-positive classes (over-redaction, accepted): long base64 payloads, data
URIs, SRI hashes, and a hex digest glued to an uppercase env label (`NOTE=<sha256>`: `=` is a
key-material character, so the label joins the run). Base64 ids under 40 characters, git SHAs,
standalone sha256 digests, paths and slugs are not matched.

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
