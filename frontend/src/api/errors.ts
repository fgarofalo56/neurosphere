import type { ProblemDetails } from "@neurosphere/contracts";

/** Taxonomy code names, taken from the generated contract (PRP.md section 3). */
export type ApiErrorCode = ProblemDetails["code"];

export const CORRELATION_HEADER = "x-correlation-id";

const TAXONOMY_CODES: readonly ApiErrorCode[] = [
  "unauthorized",
  "forbidden",
  "capability_unavailable",
  "stale_version",
  "rate_limited",
  "invalid_schema",
  "dependency_transient",
];

export interface ApiErrorInit {
  status: number;
  retryable: boolean;
  correlationId: string;
  message?: string | undefined;
  retryAfterSeconds?: number | undefined;
  problem?: ProblemDetails | undefined;
}

/** Base class for every error the client throws for a non-2xx or unusable response. */
export class ApiError extends Error {
  readonly code: ApiErrorCode | "unexpected_response";
  readonly status: number;
  readonly retryable: boolean;
  readonly correlationId: string;
  readonly retryAfterSeconds: number | undefined;
  readonly problem: ProblemDetails | undefined;

  constructor(code: ApiErrorCode | "unexpected_response", init: ApiErrorInit) {
    super(init.message ?? `${code} (HTTP ${init.status})`);
    this.name = new.target.name;
    this.code = code;
    this.status = init.status;
    this.retryable = init.retryable;
    this.correlationId = init.correlationId;
    this.retryAfterSeconds = init.retryAfterSeconds;
    this.problem = init.problem;
  }
}

export class UnauthorizedError extends ApiError {
  constructor(init: ApiErrorInit) {
    super("unauthorized", init);
  }
}

export class ForbiddenError extends ApiError {
  constructor(init: ApiErrorInit) {
    super("forbidden", init);
  }
}

export class CapabilityUnavailableError extends ApiError {
  readonly reason: string | undefined;
  constructor(init: ApiErrorInit) {
    super("capability_unavailable", init);
    this.reason = init.problem?.reason;
  }
}

/** ETag/version mismatch. Never auto-retried: the caller must re-read and re-confirm. */
export class StaleVersionError extends ApiError {
  constructor(init: ApiErrorInit) {
    super("stale_version", init);
  }
}

export class RateLimitedError extends ApiError {
  constructor(init: ApiErrorInit) {
    super("rate_limited", init);
  }
}

export class InvalidSchemaError extends ApiError {
  constructor(init: ApiErrorInit) {
    super("invalid_schema", init);
  }
}

/** Also covers 503 policy-store outage (fail closed) and network failures (status 0). */
export class DependencyTransientError extends ApiError {
  constructor(init: ApiErrorInit) {
    super("dependency_transient", init);
  }
}

/** A response outside the taxonomy (for example a 404 or an unparseable 2xx body). */
export class UnexpectedResponseError extends ApiError {
  constructor(init: ApiErrorInit) {
    super("unexpected_response", init);
  }
}

/** Thrown before sending when a caller tries to scope a request client-side. */
export class ScopeParameterError extends Error {
  readonly parameter: string;
  constructor(parameter: string) {
    super(`"${parameter}" must not be sent by the client; scope is derived server-side`);
    this.name = "ScopeParameterError";
    this.parameter = parameter;
  }
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError;
}

function isTaxonomyCode(value: unknown): value is ApiErrorCode {
  return typeof value === "string" && (TAXONOMY_CODES as readonly string[]).includes(value);
}

function asProblem(body: unknown): Partial<ProblemDetails> | undefined {
  return typeof body === "object" && body !== null && !Array.isArray(body)
    ? (body as Partial<ProblemDetails>)
    : undefined;
}

/** Parses a Retry-After header: delta-seconds or an HTTP-date. Returns seconds or undefined. */
export function parseRetryAfter(
  value: string | null,
  now: number = Date.now(),
): number | undefined {
  if (value === null || value.trim() === "") return undefined;
  const trimmed = value.trim();
  if (/^\d+$/.test(trimmed)) return Number(trimmed);
  const at = Date.parse(trimmed);
  if (Number.isNaN(at)) return undefined;
  return Math.max(0, Math.ceil((at - now) / 1000));
}

function codeForStatus(status: number): ApiErrorCode | undefined {
  switch (status) {
    case 401:
      return "unauthorized";
    case 403:
      return "forbidden";
    case 409:
      return "stale_version";
    case 422:
      return "invalid_schema";
    case 429:
      return "rate_limited";
    default:
      return status >= 500 ? "dependency_transient" : undefined;
  }
}

export interface ErrorSource {
  status: number;
  body: unknown;
  retryAfterHeader: string | null;
  correlationId: string;
}

/**
 * Maps an HTTP failure to a typed error. The HTTP status decides the class; the problem body
 * supplies the contract `retryable` flag, `retry_after_seconds`, `reason` and correlation id.
 */
export function errorFromResponse(source: ErrorSource): ApiError {
  const { status } = source;
  const problem = asProblem(source.body);
  const bodyCode = problem?.code;
  const code = codeForStatus(status) ?? (isTaxonomyCode(bodyCode) ? bodyCode : undefined);
  const bodyRetryable = typeof problem?.retryable === "boolean" ? problem.retryable : undefined;
  const bodyRetryAfter =
    typeof problem?.retry_after_seconds === "number" ? problem.retry_after_seconds : undefined;
  const init: ApiErrorInit = {
    status,
    // A 5xx with no contract flag: gateway-style failures are transient, a bare 500 is not.
    retryable: bodyRetryable ?? [502, 503, 504].includes(status),
    correlationId:
      typeof problem?.correlation_id === "string" && problem.correlation_id !== ""
        ? problem.correlation_id
        : source.correlationId,
    message: typeof problem?.title === "string" ? problem.title : undefined,
    retryAfterSeconds: parseRetryAfter(source.retryAfterHeader) ?? bodyRetryAfter,
    problem: problem as ProblemDetails | undefined,
  };
  switch (code) {
    case "unauthorized":
      return new UnauthorizedError({ ...init, retryable: false });
    case "forbidden":
      return new ForbiddenError({ ...init, retryable: false });
    case "capability_unavailable":
      return new CapabilityUnavailableError({ ...init, retryable: false });
    case "stale_version":
      return new StaleVersionError({ ...init, retryable: false });
    case "rate_limited":
      return new RateLimitedError({ ...init, retryable: bodyRetryable ?? true });
    case "invalid_schema":
      return new InvalidSchemaError({ ...init, retryable: false });
    case "dependency_transient":
      return new DependencyTransientError(init);
    default:
      return new UnexpectedResponseError({ ...init, retryable: false });
  }
}
