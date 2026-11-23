### Added
- Governance contracts (PRP-99), all additive inside `v1`. These are wire contracts only:
  nothing stores, routes or enforces them until PRP-100 to PRP-109 ship, and content
  capture stays off by default.
- Opt-in content channel: a transient `ContentEnvelope` and a secret-free `RedactedContent`
  whose text is rejected when it contains a known credential format; the telemetry
  `payload_ref` gains metadata-only capture fields (`schema_version` 1.2.0).
- `interactions/v1` contract area: detection findings, the metadata-only interaction record,
  capture policies (redact by default, 90-day retention by default), access purpose and
  export manifest.
- `policy/v1` contract area: policy definitions with nine typed rule kinds and no expression
  language, violations, exceptions, the policy decision request and response, and
  enforcement bindings (audit mode by default).
- `notifications/v1` contract area: channels (endpoints held only as Key Vault secret
  references), subscriptions and delivery records with no recipient address or body.
- Agent-version approval state, the `approval_state` query field, six governance write
  actions on connector manifests, eleven estate connector kinds, three admin config kinds,
  three system settings and the privileged, time-bound `interaction_investigator` role (no
  permissions until PRP-104).

### Changed
- The additive-only contract baseline was refreshed and its exception list is empty.
