### Added
- Encrypted interaction content store (PRP-102): AES-256-GCM envelope encryption with a fresh
  data key per interaction, wrapped by an Azure Key Vault key over REST (`RSA-OAEP-256`, vault
  host checked against the deployment cloud) or, under `NS_ENV=local` only, a local file key.
  Nothing calls the store yet: content capture arrives with PRP-103 and stays off by default.
- The store accepts only redacted, secret-free content validated against the `RedactedContent`
  JSON Schema, and refuses every write unless the customer retention policy sets
  `retain_prompt_response_bodies` and has an `interaction_content` rule.
- Lifecycle data class `interaction_content`: legal holds keep content, expiry purges the blob
  and the index document together, an interrupted purge completes on the next run, export is
  metadata only and pseudonymize deletes the content.
- Cosmos containers `interaction_index`, `interaction_capture_policies`, `policy_definitions`,
  `policy_violations`, `policy_exceptions` and `notification_outbox`.
- Runbook `docs/runbooks/interaction-audit.md` with the verified Key Vault and `cryptography`
  facts.

### Changed
- The lifecycle engine honours a per-record `expires_at` when it is earlier than the class
  rule's maximum retention; minimum retention and legal holds still win.
- `cryptography` and `jsonschema` are direct dependencies of `packages/core`.
