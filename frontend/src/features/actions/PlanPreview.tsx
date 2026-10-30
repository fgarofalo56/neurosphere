import type { ReactElement } from "react";
import { StatusPill } from "../../design-system";
import { STRINGS } from "./strings";
import type { ProposedDiff } from "./types";

/** The connector binds the reviewed plan digest into the diff as `test /plan_digest`. */
export const PLAN_DIGEST_PATH = "/plan_digest";
const RESOURCES_PREFIX = "/resources/";
const DIGEST_PREFIX_LENGTH = 12;

export type PlanExpected = "create" | "found";

/** A planned step with the expected outcome, when the API reports one. */
export interface PlanStepView {
  readonly resource_type: string;
  readonly name: string;
  readonly expected: PlanExpected;
}

export interface PlanRow {
  readonly resourceType: string;
  readonly name: string;
  readonly operation: string;
  readonly expected: PlanExpected | null;
}

export interface ParsedPlan {
  readonly digest: string | null;
  readonly rows: readonly PlanRow[];
}

const RESOURCE_TYPES: readonly (readonly [string, RegExp])[] = [
  ["named_value", /^namedValues\/[^/]+$/],
  ["backend", /^backends\/[^/]+$/],
  ["policy_fragment", /^policyFragments\/[^/]+$/],
  ["api_operation", /^apis\/[^/]+\/operations\/[^/]+$/],
  ["api_policy", /^apis\/[^/]+\/policies\/policy$/],
  ["api", /^apis\/[^/]+$/],
  ["product_policy", /^products\/[^/]+\/policies\/policy$/],
  ["product_api_link", /^products\/[^/]+\/apiLinks\/[^/]+$/],
  ["product", /^products\/[^/]+$/],
  ["subscription", /^subscriptions\/[^/]+$/],
];

function unescapeToken(token: string): string {
  return token.replaceAll("~1", "/").replaceAll("~0", "~");
}

function classify(path: string): string {
  return RESOURCE_TYPES.find(([, pattern]) => pattern.test(path))?.[0] ?? "resource";
}

/**
 * Reads the plan out of a proposed diff: the `test /plan_digest` operation and one row per
 * `/resources/{path}` operation (the generic gateway grammar of the APIM connector). Nothing is
 * derived beyond what the diff states, so `expected` stays null unless `steps` supplies it.
 */
export function parsePlan(
  diff: ProposedDiff,
  steps: readonly PlanStepView[] | undefined = undefined,
): ParsedPlan {
  let digest: string | null = null;
  const rows: PlanRow[] = [];
  for (const op of diff.operations) {
    if (op.path === PLAN_DIGEST_PATH) {
      if (op.op === "test" && typeof op.value === "string") digest = op.value;
      continue;
    }
    if (!op.path.startsWith(RESOURCES_PREFIX)) continue;
    const name = unescapeToken(op.path.slice(RESOURCES_PREFIX.length));
    const reported = steps?.find((s) => s.name === name);
    rows.push({
      resourceType: reported?.resource_type ?? classify(name),
      name,
      operation: op.op,
      expected: reported?.expected ?? null,
    });
  }
  return { digest, rows };
}

export function digestPrefix(digest: string): string {
  const hex = digest.startsWith("sha256:") ? digest.slice("sha256:".length) : digest;
  return hex.slice(0, DIGEST_PREFIX_LENGTH);
}

/**
 * APIM plan preview for the confirmation dialog: the digest prefix and the planned resource
 * steps, read from the diff. Renders nothing for a change with no plan (a Foundry model swap).
 * Rendered as a `dt`/`dd` pair so it sits inside the dialog's definition list.
 */
export function PlanPreview({
  diff,
  steps,
}: {
  readonly diff: ProposedDiff;
  readonly steps?: readonly PlanStepView[] | undefined;
}): ReactElement | null {
  const plan = parsePlan(diff, steps);
  if (plan.digest === null && plan.rows.length === 0) return null;
  const P = STRINGS.plan;
  return (
    <>
      <dt>{P.title}</dt>
      <dd data-testid="plan-preview">
        <p data-testid="plan-digest">
          {P.digest}:{" "}
          {plan.digest === null ? (
            P.noDigest
          ) : (
            <code title={P.digestHelp}>{digestPrefix(plan.digest)}</code>
          )}
        </p>
        {plan.rows.length > 0 ? (
          <ol aria-label={P.title} data-testid="plan-steps">
            {plan.rows.map((row, index) => (
              // Step order is significant (dependency order), so the index is part of the key.
              <li key={`${index}|${row.name}`} data-testid="plan-step">
                <code data-testid="plan-step-type">{row.resourceType}</code>{" "}
                <code data-testid="plan-step-name">{row.name}</code> ({row.operation}):{" "}
                {row.expected === null ? (
                  <span data-testid="plan-step-expected">{P.notReported}</span>
                ) : (
                  <span data-testid="plan-step-expected">
                    <StatusPill
                      label={row.expected === "create" ? P.create : P.found}
                      tone={row.expected === "create" ? "info" : "neutral"}
                    />
                  </span>
                )}
              </li>
            ))}
          </ol>
        ) : null}
      </dd>
    </>
  );
}
