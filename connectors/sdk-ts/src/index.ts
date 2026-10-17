// NeuroSphere TypeScript connector SDK (PRP-09 item 2). Read side only: no write surface
// (PRP-09 clarification 7); the WriteConnector interface lives in the Python SDK.
export { BaseConnector } from "./connector.js";
export type { BaseConnectorOptions, GuardedCallOptions } from "./connector.js";
export { checkConnectorContract } from "./contract-kit.js";
export type { Violation } from "./contract-kit.js";
export {
  CapabilityUnavailableError,
  ConnectorError,
  DependencyTransientError,
  InvalidManifestError,
  RateLimitedError,
} from "./errors.js";
export type { ManifestIssue } from "./errors.js";
export {
  HealthTracker,
  coverageFraction,
  makeCoverage,
  unknownCoverage,
  unknownFreshness,
  utcNow,
} from "./health.js";
export type {
  Clock,
  CoverageReport,
  FreshnessReport,
  HealthReport,
  HealthState,
  HealthTrackerOptions,
  RateLimitStatus,
} from "./health.js";
export { buildManifest, manifestIssues, validateManifest } from "./manifest.js";
export type { BuildManifestOptions, Capability, Cloud, Freshness, Granularity } from "./manifest.js";
export { CredentialBroker, SecretValue, StaticCredentialResolver } from "./vault.js";
export type {
  CredentialLogger,
  CredentialRef,
  CredentialResolver,
  RotationCallback,
  RotationSource,
} from "./vault.js";
export type { ConnectorManifest } from "@neurosphere/contracts";
