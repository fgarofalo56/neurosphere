# Connector SDK reference (TypeScript)

> Generated file. Do not edit; run `uv run python docs/reference/generate.py`.
> Source commit: `af98026372dc6eac945813edae61912c4a5d2961`. Generated: 2026-11-04.
> Sources: `connectors/sdk-ts/src/`.

Package `@neurosphere/connector-sdk`. Read side only: there is no write surface in the TypeScript SDK; the `WriteConnector` interface lives in the Python SDK. Symbols are the exports of `src/index.ts`, with declaration headers and the first doc-comment paragraph extracted from source.

| Symbol | Kind | Module |
|---|---|---|
| `BaseConnector` | class | `./connector.js` |
| `BaseConnectorOptions` | interface | `./connector.js` |
| `BuildManifestOptions` | interface | `./manifest.js` |
| `Capability` | type | `./manifest.js` |
| `CapabilityUnavailableError` | class | `./errors.js` |
| `Clock` | type | `./health.js` |
| `Cloud` | type | `./manifest.js` |
| `ConnectorError` | class | `./errors.js` |
| `ConnectorManifest` | type | `@neurosphere/contracts` |
| `CoverageReport` | interface | `./health.js` |
| `CredentialBroker` | class | `./vault.js` |
| `CredentialLogger` | interface | `./vault.js` |
| `CredentialRef` | type | `./vault.js` |
| `CredentialResolver` | interface | `./vault.js` |
| `DependencyTransientError` | class | `./errors.js` |
| `Freshness` | type | `./manifest.js` |
| `FreshnessReport` | interface | `./health.js` |
| `Granularity` | type | `./manifest.js` |
| `GuardedCallOptions` | interface | `./connector.js` |
| `HealthReport` | interface | `./health.js` |
| `HealthState` | type | `./health.js` |
| `HealthTracker` | class | `./health.js` |
| `HealthTrackerOptions` | interface | `./health.js` |
| `InvalidManifestError` | class | `./errors.js` |
| `ManifestIssue` | interface | `./errors.js` |
| `RateLimitStatus` | interface | `./health.js` |
| `RateLimitedError` | class | `./errors.js` |
| `RotationCallback` | type | `./vault.js` |
| `RotationSource` | interface | `./vault.js` |
| `SecretValue` | class | `./vault.js` |
| `StaticCredentialResolver` | class | `./vault.js` |
| `Violation` | interface | `./contract-kit.js` |
| `buildManifest` | function | `./manifest.js` |
| `checkConnectorContract` | export | `./contract-kit.js` |
| `coverageFraction` | function | `./health.js` |
| `makeCoverage` | function | `./health.js` |
| `manifestIssues` | function | `./manifest.js` |
| `unknownCoverage` | const | `./health.js` |
| `unknownFreshness` | const | `./health.js` |
| `utcNow` | const | `./health.js` |
| `validateManifest` | function | `./manifest.js` |

## Symbols

### `BaseConnector`

```ts
export abstract class BaseConnector
```

### `BaseConnectorOptions`

```ts
export interface BaseConnectorOptions
```

### `BuildManifestOptions`

```ts
export interface BuildManifestOptions
```

### `Capability`

```ts
export type Capability
```

### `CapabilityUnavailableError`

```ts
export class CapabilityUnavailableError extends ConnectorError
```

### `Clock`

```ts
export type Clock
```

### `Cloud`

```ts
export type Cloud
```

### `ConnectorError`

```ts
export class ConnectorError extends Error
```

### `ConnectorManifest`

```ts
re-export from @neurosphere/contracts
```

### `CoverageReport`

```ts
export interface CoverageReport
```

What fraction of expected sources answered. Unknown counts are null. */

### `CredentialBroker`

```ts
export class CredentialBroker
```

Resolves the connector's declared credential refs at call time, with rotation. */

### `CredentialLogger`

```ts
export interface CredentialLogger
```

Minimal logger seam; fields hold the credential name only. */

### `CredentialRef`

```ts
export type CredentialRef
```

### `CredentialResolver`

```ts
export interface CredentialResolver
```

Injected by the host; resolves a vault reference (managed identity) to its value. */

### `DependencyTransientError`

```ts
export class DependencyTransientError extends ConnectorError
```

### `Freshness`

```ts
export type Freshness
```

### `FreshnessReport`

```ts
export interface FreshnessReport
```

Observed data lag. lagMs is null when unknown (never 0). */

### `Granularity`

```ts
export type Granularity
```

### `GuardedCallOptions`

```ts
export interface GuardedCallOptions<T>
```

### `HealthReport`

```ts
export interface HealthReport
```

### `HealthState`

```ts
export type HealthState
```

### `HealthTracker`

```ts
export class HealthTracker
```

Accumulates call outcomes and renders a HealthReport. */

### `HealthTrackerOptions`

```ts
export interface HealthTrackerOptions
```

### `InvalidManifestError`

```ts
export class InvalidManifestError extends ConnectorError
```

### `ManifestIssue`

```ts
export interface ManifestIssue
```

One manifest problem: an RFC 6901 pointer and a message that never echoes a value. */

### `RateLimitStatus`

```ts
export interface RateLimitStatus
```

### `RateLimitedError`

```ts
export class RateLimitedError extends ConnectorError
```

### `RotationCallback`

```ts
export type RotationCallback
```

Receives the logical credential name (never a value); may be sync or async. */

### `RotationSource`

```ts
export interface RotationSource
```

Optional resolver capability: pushes rotation signals to the broker. */

### `SecretValue`

```ts
export class SecretValue
```

A secret string that cannot leak through toString, JSON, template strings or inspect. */

### `StaticCredentialResolver`

```ts
export class StaticCredentialResolver implements CredentialResolver, RotationSource
```

In-memory resolver for tests and local sandboxes; values keyed by vault_ref. */

### `Violation`

```ts
export interface Violation
```

One contract failure. `code` is stable; `message` never contains secret values. */

### `buildManifest`

```ts
export function buildManifest(options: BuildManifestOptions): ConnectorManifest
```

Assemble and validate a read-only manifest. Derives auth mode and the advisory/write_support block (always advisory: this SDK has no write surface). Unknown freshness is null/null and unknown rate limits stay null, never 0.

### `checkConnectorContract`

```ts
checkConnectorContract
```

### `coverageFraction`

```ts
export function coverageFraction(report: CoverageReport): number | null
```

answered / expected; null when unknown or nothing was expected. */

### `makeCoverage`

```ts
export function makeCoverage(init: Partial<CoverageReport>): CoverageReport
```

Validating constructor: answered may not exceed expected. */

### `manifestIssues`

```ts
export function manifestIssues(data: unknown): ManifestIssue[]
```

Every contract violation for a manifest object or JSON text (empty array means valid). */

### `unknownCoverage`

```ts
export const unknownCoverage
```

### `unknownFreshness`

```ts
export const unknownFreshness
```

### `utcNow`

```ts
export const utcNow: Clock
```

### `validateManifest`

```ts
export function validateManifest(data: unknown): ConnectorManifest
```

Return the validated manifest or throw InvalidManifestError listing the issues. */

