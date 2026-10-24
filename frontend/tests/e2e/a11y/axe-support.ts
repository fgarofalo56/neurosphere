import { mkdirSync, readdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { expect } from "../../e2e-support/fixtures.ts";
import type { RouteSample } from "./route-samples.ts";

// PRP-24 item 3: shared axe plumbing. Automated axe is necessary, not sufficient: it proves the
// absence of the machine-detectable failures below, nothing about conformance. See
// docs/accessibility/README.md.

export const A11Y_TAGS = [
  "wcag2a",
  "wcag2aa",
  "wcag21a",
  "wcag21aa",
  "wcag22aa",
  "section508",
] as const;

/**
 * Fluent UI's Tabster injects 1px aria-hidden focus sentinels (`<i tabindex="0" aria-hidden>`)
 * that axe reports as aria-hidden-focus, intermittently, on any page with a focus mover or menu.
 * This is the same, narrowly scoped exclusion overview.spec.ts, shell.spec.ts and copilot.spec.ts
 * already use. Nothing else is excluded. Recorded in docs/accessibility/remediation-log.md.
 */
export const TABSTER_SENTINEL = "[data-tabster-dummy]";

export const MODES = ["light", "dark", "high-contrast"] as const;
export type Mode = (typeof MODES)[number];
export const PACKS = ["default", "sample-agency"] as const;

export type Impact = "critical" | "serious" | "moderate" | "minor";

export interface ViolationRecord {
  readonly id: string;
  readonly impact: string;
  readonly help: string;
  readonly nodes: number;
  readonly targets: readonly string[];
}

export interface AxeRecord {
  readonly kind: "route" | "sandbox" | "theme" | "special";
  readonly pattern: string;
  readonly name: string;
  readonly url: string;
  readonly mode: string;
  readonly packId: string;
  readonly sandboxMode: boolean;
  readonly counts: Record<Impact, number>;
  readonly violations: readonly ViolationRecord[];
  readonly note?: string;
}

const OUT_DIR = join(process.cwd(), "test-results", "a11y");
const RECORD_DIR = join(OUT_DIR, "records");
export const RESULTS_FILE = join(OUT_DIR, "axe-results.json");

export const ALL_IMPACTS: readonly Impact[] = ["critical", "serious", "moderate", "minor"];

/** Seeds the persisted theme and sandbox preferences before any page script runs. */
export async function seedPreferences(
  page: Page,
  opts: { mode: Mode; packId?: string; sandbox?: boolean },
): Promise<void> {
  await page.addInitScript(
    (p) => {
      window.localStorage.setItem(
        "ns.theme",
        JSON.stringify({ packId: p.packId, themeName: p.mode }),
      );
      if (p.sandbox) {
        window.localStorage.setItem(
          "ns.sandbox-mode",
          JSON.stringify({ state: { enabled: true }, version: 0 }),
        );
      }
    },
    { mode: opts.mode, packId: opts.packId ?? "default", sandbox: opts.sandbox ?? false },
  );
}

/** Opens the sample and waits for the state the page settles in. */
export async function openSample(page: Page, sample: RouteSample): Promise<void> {
  await page.goto(sample.url);
  await expect(page.locator(sample.ready).first()).toBeVisible({ timeout: 30_000 });
  await page.waitForLoadState("networkidle");
}

export interface AnalyzeOutcome {
  readonly violations: ViolationRecord[];
  readonly counts: Record<Impact, number>;
  /** True when axe reached nodes inside an iframe (multi-part targets). */
  readonly analyzedFrames: boolean;
}

export async function analyze(page: Page): Promise<AnalyzeOutcome> {
  const results = await new AxeBuilder({ page })
    .withTags([...A11Y_TAGS])
    .exclude(TABSTER_SENTINEL)
    .analyze();
  const counts: Record<Impact, number> = { critical: 0, serious: 0, moderate: 0, minor: 0 };
  const violations = results.violations.map((v): ViolationRecord => {
    const impact = (v.impact ?? "minor") as Impact;
    counts[impact] += 1;
    return {
      id: v.id,
      impact,
      help: v.help,
      nodes: v.nodes.length,
      targets: v.nodes.map((n) => n.target.map(String).join(" >>> ")),
    };
  });
  const analyzedFrames = [...results.passes, ...results.violations, ...results.incomplete].some(
    (r) => r.nodes.some((n) => n.target.length > 1),
  );
  return { violations, counts, analyzedFrames };
}

export function record(rec: AxeRecord): void {
  mkdirSync(RECORD_DIR, { recursive: true });
  const key = [rec.kind, rec.pattern, rec.name, rec.mode, rec.packId, rec.sandboxMode]
    .join("__")
    .replace(/[^A-Za-z0-9_.-]+/g, "-");
  writeFileSync(join(RECORD_DIR, `${key}.json`), JSON.stringify(rec));
}

/** Folds every per-test record of this run into one machine-readable file (atomic rename). */
export function writeAggregate(): void {
  let files: string[];
  try {
    files = readdirSync(RECORD_DIR).filter((f) => f.endsWith(".json"));
  } catch {
    return;
  }
  const records = files
    .map((f) => JSON.parse(readFileSync(join(RECORD_DIR, f), "utf8")) as AxeRecord)
    .sort((a, b) =>
      `${a.kind}${a.pattern}${a.mode}${a.packId}${a.sandboxMode}`.localeCompare(
        `${b.kind}${b.pattern}${b.mode}${b.packId}${b.sandboxMode}`,
      ),
    );
  const byImpact: Record<Impact, number> = { critical: 0, serious: 0, moderate: 0, minor: 0 };
  const rules: Record<string, number> = {};
  for (const r of records) {
    for (const i of ALL_IMPACTS) byImpact[i] += r.counts[i];
    for (const v of r.violations) rules[v.id] = (rules[v.id] ?? 0) + 1;
  }
  const summary = {
    generatedAt: new Date().toISOString(),
    tags: A11Y_TAGS,
    modes: MODES,
    packs: PACKS,
    totals: {
      checks: records.length,
      routes: new Set(records.filter((r) => r.kind === "route").map((r) => r.pattern)).size,
      byImpact,
      ruleIds: rules,
    },
    records,
  };
  const tmp = join(OUT_DIR, `axe-results.${process.pid}.tmp`);
  writeFileSync(tmp, JSON.stringify(summary, null, 2));
  renameSync(tmp, RESULTS_FILE);
}

export function blocking(violations: readonly ViolationRecord[]): ViolationRecord[] {
  return violations.filter((v) => v.impact === "serious" || v.impact === "critical");
}

/** Readable failure text: rule id, impact and the target selectors. */
export function describeBlocking(violations: readonly ViolationRecord[]): string {
  return blocking(violations)
    .map((v) => `${v.impact} ${v.id}: ${v.help}\n    ${v.targets.slice(0, 6).join("\n    ")}`)
    .join("\n");
}
