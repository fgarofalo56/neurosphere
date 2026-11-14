# @neurosphere/connector-sdk

TypeScript connector SDK (PRP-09): base connector, manifest builder and validator, health,
rate-limit, coverage and freshness reporting, and vault credential references. It has no write
surface; write-capable connectors use the Python SDK.

## Tests

```
pnpm --filter ./connectors/sdk-ts test
pnpm --filter ./connectors/sdk-ts exec tsc --noEmit
```

## Interop fixtures

`tests/fixtures/manifests/*.json` are manifests produced by `buildManifest` (definitions in
`tests/fixture-defs.ts`). The Python SDK validates them, and this package validates the
Python-produced fixtures under `connectors/sdk-python/tests/interop/fixtures/`. Files under
`invalid/` must exist with the same names in both trees and be rejected by both validators.

After changing `fixture-defs.ts` or `buildManifest`, regenerate the committed files:

```
UPDATE_INTEROP_FIXTURES=1 pnpm --filter ./connectors/sdk-ts test
```

The Python side has the same switch for its own fixtures
(`UPDATE_INTEROP_FIXTURES=1 uv run pytest connectors/sdk-python/tests/interop`). Review the diff
before committing.

## Notes

- `validateManifest` returns a deep-frozen copy; the input is not modified or frozen.
- `SecretValue.equals` is a best-effort comparison, not a guaranteed constant-time one.
- Async rotation hooks queued by a `RotationSource` signal run only when the host calls
  `CredentialBroker.drainRotationHooks()`.
