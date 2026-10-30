import { describe, expect, it } from "vitest";
import { handle as audit } from "./audit.ts";
import { handle as catalog } from "./catalog.ts";
import type { FeatureMockContext, FeatureMockHandler } from "./context.ts";
import { handle as curation } from "./curation.ts";
import { handle as deploy } from "./deploy.ts";
import { handle as evaluations } from "./evaluations.ts";
import { handle as executionControl } from "./execution-control.ts";
import { handle as federation } from "./federation.ts";
import { handle as finops } from "./finops.ts";
import { FEATURE_HANDLERS, dispatchFeatureMocks } from "./index.ts";

// Placeholders never touch the context, so an empty object stands in for a request.
const ctx = {} as unknown as FeatureMockContext;

describe("feature mock registry", () => {
  it("lists every feature once, curation before catalog", () => {
    expect(FEATURE_HANDLERS).toEqual([
      curation,
      catalog,
      audit,
      finops,
      federation,
      deploy,
      evaluations,
      executionControl,
    ]);
    expect(new Set(FEATURE_HANDLERS).size).toBe(FEATURE_HANDLERS.length);
    expect(FEATURE_HANDLERS.indexOf(curation)).toBeLessThan(FEATURE_HANDLERS.indexOf(catalog));
  });

  it("placeholder modules return false", () => {
    for (const handler of FEATURE_HANDLERS) expect(handler(ctx)).toBe(false);
    expect(dispatchFeatureMocks(ctx)).toBe(false);
  });

  it("dispatches in order and stops at the first handler that answers", () => {
    const calls: string[] = [];
    const make =
      (name: string, answers: boolean): FeatureMockHandler =>
      () => {
        calls.push(name);
        return answers;
      };
    const handled = dispatchFeatureMocks(ctx, [make("a", false), make("b", true), make("c", true)]);
    expect(handled).toBe(true);
    expect(calls).toEqual(["a", "b"]);
  });
});
