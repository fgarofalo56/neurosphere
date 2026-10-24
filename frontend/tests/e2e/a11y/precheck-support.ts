import { mkdirSync, readdirSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { stripVTControlCharacters } from "node:util";
import type { Page } from "@playwright/test";

// PRP-24 item 3b: shared plumbing for the automated keyboard and accessibility-tree pre-check.
// This is a machine pre-check that lets a human tester confirm faster. It is NOT a human test and
// does not replace the signed checklists (docs/accessibility/automated-precheck-2026-10-24.md).

export type Verdict = "pass" | "fail" | "note";

export interface CheckRecord {
  /** "keyboard-flow" | "keyboard-route" | "sr-flow" | "sr-route". */
  readonly scope: string;
  /** Checklist row: a flow slug, or a route pattern. */
  readonly id: string;
  /** Variant the check ran under (theme mode), empty when not applicable. */
  readonly variant: string;
  readonly check: string;
  readonly verdict: Verdict;
  readonly detail: string;
}

const OUT_DIR = join(process.cwd(), "test-results", "a11y");
const RECORD_DIR = join(OUT_DIR, "precheck-records");
export const PRECHECK_FILE = join(OUT_DIR, "precheck-results.json");

function writeRecord(rec: CheckRecord): void {
  mkdirSync(RECORD_DIR, { recursive: true });
  const key = [rec.scope, rec.id, rec.variant, rec.check]
    .join("__")
    .replace(/[^A-Za-z0-9_.-]+/g, "-")
    .slice(0, 180);
  writeFileSync(join(RECORD_DIR, `${key}.json`), JSON.stringify(rec));
}

/**
 * Collects named checks for one row. A failed check is recorded and remembered; `finish()` throws
 * one error listing every failure, so a single run reports all defects of the row (not just the
 * first). Later checks of a row may depend on earlier state; use `must` to stop at a failure.
 */
export class Recorder {
  private readonly failures: string[] = [];

  constructor(
    private readonly scope: string,
    private readonly id: string,
    private readonly variant = "",
  ) {}

  /** Runs `fn`; records pass (or fail with the assertion message) and continues. */
  async check(check: string, fn: () => Promise<void> | void, passDetail = ""): Promise<boolean> {
    try {
      await fn();
      writeRecord({
        scope: this.scope,
        id: this.id,
        variant: this.variant,
        check,
        verdict: "pass",
        detail: passDetail,
      });
      return true;
    } catch (error) {
      const detail = stripVTControlCharacters(
        error instanceof Error ? error.message : String(error),
      )
        .split("\n")
        .slice(0, 6)
        .join(" | ")
        .slice(0, 600);
      writeRecord({
        scope: this.scope,
        id: this.id,
        variant: this.variant,
        check,
        verdict: "fail",
        detail,
      });
      this.failures.push(`${check}: ${detail}`);
      return false;
    }
  }

  /** Like check, but throws immediately on failure (later steps need the state it establishes). */
  async must(check: string, fn: () => Promise<void> | void): Promise<void> {
    if (!(await this.check(check, fn))) this.finish();
  }

  /** Records an informational finding that is not a pass/fail verdict (for example wording). */
  note(check: string, detail: string): void {
    writeRecord({
      scope: this.scope,
      id: this.id,
      variant: this.variant,
      check,
      verdict: "note",
      detail,
    });
  }

  finish(): void {
    if (this.failures.length > 0) {
      throw new Error(`${this.scope} ${this.id}: ${this.failures.join(" || ")}`);
    }
  }
}

/** Folds every per-check record into `test-results/a11y/precheck-results.json` (atomic rename). */
export function writePrecheckAggregate(): void {
  let files: string[];
  try {
    files = readdirSync(RECORD_DIR).filter((f) => f.endsWith(".json"));
  } catch {
    return;
  }
  const records = files
    .flatMap((f): CheckRecord[] => {
      try {
        return [JSON.parse(readFileSync(join(RECORD_DIR, f), "utf8")) as CheckRecord];
      } catch {
        return []; // another worker is mid-write; its own afterAll writes the full aggregate
      }
    })
    .sort((a, b) =>
      `${a.scope}|${a.id}|${a.variant}|${a.check}`.localeCompare(
        `${b.scope}|${b.id}|${b.variant}|${b.check}`,
      ),
    );
  const totals = { pass: 0, fail: 0, note: 0 };
  for (const r of records) totals[r.verdict] += 1;
  const summary = {
    generatedAt: new Date().toISOString(),
    disclaimer:
      "Automated pre-check only. Not a human test; does not replace the signed keyboard and screen reader checklists.",
    totals: { checks: records.length, ...totals },
    records,
  };
  mkdirSync(OUT_DIR, { recursive: true });
  const tmp = join(OUT_DIR, `precheck-results.${process.pid}.tmp`);
  writeFileSync(tmp, JSON.stringify(summary, null, 2));
  try {
    renameSync(tmp, PRECHECK_FILE);
  } catch {
    // Windows refuses a rename while another worker holds the target; every worker writes the same
    // aggregate of the shared record files, so losing this race loses nothing.
    rmSync(tmp, { force: true });
  }
}

/** Tab until `done` holds for the focused element; bounded so a regression cannot hang. */
export async function tabUntil(
  page: Page,
  done: () => Promise<boolean>,
  limit = 80,
  key = "Tab",
): Promise<void> {
  for (let i = 0; i < limit; i += 1) {
    await page.keyboard.press(key);
    if (await done()) return;
  }
  throw new Error(
    `focus never reached the expected element within ${String(limit)} ${key} presses`,
  );
}

/** Accessible-ish label of the focused element for failure messages. */
export function focusedLabel(page: Page): Promise<string> {
  return page.evaluate(() => {
    const el = document.activeElement;
    if (el === null) return "(none)";
    const text = (el.getAttribute("aria-label") ?? el.textContent ?? "").trim().slice(0, 50);
    return `${el.tagName.toLowerCase()}${el.getAttribute("role") ? `[role=${el.getAttribute("role")}]` : ""} "${text}"`;
  });
}
