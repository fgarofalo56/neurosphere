import { describe, expect, it } from "vitest";
import {
  CapabilityUnavailableError,
  DependencyTransientError,
  ForbiddenError,
  InvalidSchemaError,
  RateLimitedError,
  StaleVersionError,
  UnauthorizedError,
  UnexpectedResponseError,
  errorFromResponse,
  parseRetryAfter,
  type ApiError,
} from "./errors.js";

function problem(code: string, status: number, extra: Record<string, unknown> = {}) {
  return {
    schema_version: "1.0.0",
    type: "about:blank",
    title: `title-${code}`,
    status,
    code,
    retryable: false,
    correlation_id: "srv-corr",
    ...extra,
  };
}

interface Row {
  name: string;
  status: number;
  body: unknown;
  header?: string | null;
  cls: new (...args: never[]) => ApiError;
  code: string;
  retryable: boolean;
  retryAfter?: number | undefined;
}

const rows: Row[] = [
  {
    name: "401",
    status: 401,
    body: problem("unauthorized", 401),
    cls: UnauthorizedError,
    code: "unauthorized",
    retryable: false,
  },
  {
    name: "403",
    status: 403,
    body: problem("forbidden", 403),
    cls: ForbiddenError,
    code: "forbidden",
    retryable: false,
  },
  {
    name: "409",
    status: 409,
    body: problem("stale_version", 409),
    cls: StaleVersionError,
    code: "stale_version",
    retryable: false,
  },
  {
    name: "422",
    status: 422,
    body: problem("invalid_schema", 422),
    cls: InvalidSchemaError,
    code: "invalid_schema",
    retryable: false,
  },
  {
    name: "429 with header",
    status: 429,
    body: problem("rate_limited", 429, { retryable: true, retry_after_seconds: 9 }),
    header: "4",
    cls: RateLimitedError,
    code: "rate_limited",
    retryable: true,
    retryAfter: 4,
  },
  {
    name: "429 body only",
    status: 429,
    body: problem("rate_limited", 429, { retryable: true, retry_after_seconds: 9 }),
    cls: RateLimitedError,
    code: "rate_limited",
    retryable: true,
    retryAfter: 9,
  },
  {
    name: "429 no body",
    status: 429,
    body: undefined,
    cls: RateLimitedError,
    code: "rate_limited",
    retryable: true,
  },
  {
    name: "503 retryable per contract",
    status: 503,
    body: problem("dependency_transient", 503, { retryable: true }),
    cls: DependencyTransientError,
    code: "dependency_transient",
    retryable: true,
  },
  {
    name: "502 non-retryable per contract flag",
    status: 502,
    body: problem("dependency_transient", 502, { retryable: false }),
    cls: DependencyTransientError,
    code: "dependency_transient",
    retryable: false,
  },
  {
    name: "unknown 500 no body",
    status: 500,
    body: undefined,
    cls: DependencyTransientError,
    code: "dependency_transient",
    retryable: false,
  },
  {
    name: "unknown 504 no body",
    status: 504,
    body: "oops",
    cls: DependencyTransientError,
    code: "dependency_transient",
    retryable: true,
  },
  {
    name: "capability_unavailable by body code",
    status: 400,
    body: problem("capability_unavailable", 400, { reason: "not_available_in_cloud" }),
    cls: CapabilityUnavailableError,
    code: "capability_unavailable",
    retryable: false,
  },
  {
    name: "404 outside taxonomy",
    status: 404,
    body: undefined,
    cls: UnexpectedResponseError,
    code: "unexpected_response",
    retryable: false,
  },
];

describe("errorFromResponse", () => {
  it.each(rows)("$name", (row) => {
    const err = errorFromResponse({
      status: row.status,
      body: row.body,
      retryAfterHeader: row.header ?? null,
      correlationId: "client-corr",
    });
    expect(err).toBeInstanceOf(row.cls);
    expect(err.code).toBe(row.code);
    expect(err.status).toBe(row.status);
    expect(err.retryable).toBe(row.retryable);
    expect(err.retryAfterSeconds).toBe(row.retryAfter);
  });

  it("prefers the server correlation id, falls back to the client one", () => {
    expect(
      errorFromResponse({
        status: 403,
        body: problem("forbidden", 403),
        retryAfterHeader: null,
        correlationId: "c",
      }).correlationId,
    ).toBe("srv-corr");
    expect(
      errorFromResponse({
        status: 403,
        body: undefined,
        retryAfterHeader: null,
        correlationId: "c",
      }).correlationId,
    ).toBe("c");
  });

  it("keeps the capability reason", () => {
    const err = errorFromResponse({
      status: 400,
      body: problem("capability_unavailable", 400, { reason: "preview_only" }),
      retryAfterHeader: null,
      correlationId: "c",
    });
    expect(err).toBeInstanceOf(CapabilityUnavailableError);
    expect((err as CapabilityUnavailableError).reason).toBe("preview_only");
  });
});

describe("parseRetryAfter", () => {
  it.each([
    ["7", 7],
    [" 0 ", 0],
    [null, undefined],
    ["", undefined],
    ["garbage", undefined],
  ])("parses %j", (input, expected) => {
    expect(parseRetryAfter(input)).toBe(expected);
  });

  it("parses an HTTP-date relative to now", () => {
    const now = Date.parse("2026-01-01T00:00:00Z");
    expect(parseRetryAfter("Thu, 01 Jan 2026 00:00:30 GMT", now)).toBe(30);
    expect(parseRetryAfter("Wed, 31 Dec 2025 23:00:00 GMT", now)).toBe(0);
  });
});
