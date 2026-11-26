### Added
- Opt-in interaction capture at the ingest edge (PRP-103). Off by default at four levels: the
  `interaction_capture` stored setting, the retention opt-in, an approved active capture policy,
  and a match on the producer's registered source and the event's domain. When all hold, the
  body fields the guard drops are detected and redacted (credentials always, payment cards
  unless kept), encrypted and stored; the event carries only a metadata `payload_ref`. Failures
  store nothing and mark the event `redaction_failed`; capture is shed before telemetry under
  load.
- Capture policy store and matcher with distinct off reasons, and the
  `apply_capture_policy_change` and `read_back_capture_policy` functions for PRP-108's executor.
  No API route creates or changes a policy.
- Read-only admin routes `GET /api/v1/admin/interactions/capture-policies`,
  `GET /api/v1/admin/interactions/capture-policies/{policy_id}` and
  `GET /api/v1/admin/interactions/capture-status` (`config.manage`), the `Admin > Capture`
  page and the optional readiness component `interaction_capture`.
- The worker registers the `interaction_content` lifecycle target when the interaction index
  and content container are configured.
- A negative test per metadata-only guard with capture on.
- Settings `NS_INTERACTION_CAPTURE_QUEUE_CAPACITY` (default 64) and
  `NS_INTERACTION_CAPTURE_MAX_ITEMS_PER_REQUEST` (default 100) on the API, and
  `NS_INTERACTION_CONTENT_CONTAINER` and `NS_INTERACTION_CONTENT_STORAGE_ACCOUNT` on the worker
  (must match the `interaction_capture` stored setting).

### Changed
- The ingest router passes the request correlation id to the traces and events ingest paths.
