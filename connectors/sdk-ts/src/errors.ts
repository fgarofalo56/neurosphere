// Connector error taxonomy (mirrors the codes the Python SDK maps by). Messages are value-free:
// they may name a credential or a JSON pointer, never a secret or a submitted value.

export class ConnectorError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = new.target.name;
    this.code = code;
  }
}

export class RateLimitedError extends ConnectorError {
  readonly retryAfterSeconds: number | null;

  constructor(retryAfterSeconds: number | null = null) {
    super("rate_limited", "the source rate limited this call");
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

export class CapabilityUnavailableError extends ConnectorError {
  constructor(reason: string, message: string) {
    super("capability_unavailable", `${message} (${reason})`);
  }
}

export class DependencyTransientError extends ConnectorError {
  readonly reason: string;

  constructor(message: string, reason: string) {
    super("dependency_transient", message);
    this.reason = reason;
  }
}

/** One manifest problem: an RFC 6901 pointer and a message that never echoes a value. */
export interface ManifestIssue {
  readonly pointer: string;
  readonly detail: string;
}

export class InvalidManifestError extends ConnectorError {
  readonly issues: readonly ManifestIssue[];

  constructor(issues: readonly ManifestIssue[]) {
    super("invalid_schema", "connector manifest is invalid");
    this.issues = issues;
  }
}
