### Added
- `neurosphere_core.classification` (PRP-101, PR #407): a pure, dependency-free library that
  finds structured sensitive identifiers and credentials in text and replaces them with typed
  PRP-99 placeholders (`[[ns-redacted:<category>]]`), carrying no hash, length or partial value.
  Detectors: private keys, JWTs, bearer tokens, cloud access keys, verified vendor key formats,
  Azure Storage / Event Hubs / Service Bus connection strings and SAS signatures, URLs with
  userinfo, credential assignments (including chained labels, `:=`/`=>` style operators, CLI flags
  and JSON-escaped text), long opaque runs, payment cards (Luhn), IBAN (mod 97), US SSN
  (structure rules), email, phone, IPv4/IPv6, MAC and GUID, plus customer dictionaries and
  bounded customer regex patterns (static safety check, refused shapes reported as
  `pattern_unsafe`). Credentials are always replaced; other categories follow a per-category
  redact/keep configuration (default redact).
- `redact(...)` engine: NFKC and default-ignorable-character normalization, credential-first
  overlap resolution, findings with placeholder offsets and the PRP-70 `sensitivity_category`,
  a time and size budget, a post-redaction self-check, and a fail-closed `RedactionFailed`
  result (`detector_error`, `budget_exhausted`, `pattern_unsafe`, `input_too_large`) that never
  returns input text. Versioned detector set (`ns-detectors-1.0.0`) with a configuration digest.
- A seeded synthetic corpus with per-detector precision and recall; CI gates the eight credential
  categories and Luhn-valid payment cards at recall 1.0. Runbook:
  `docs/runbooks/content-classification.md` (coverage: structured identifiers only). No caller
  yet: PRP-103 wires it into opt-in interaction capture.

### Security
- Security suite `tests/security/content_redaction` proves no matched text reaches logs,
  exceptions, `repr` or output (including hashes, encodings and length hints) and that every
  injected fault fails closed.
