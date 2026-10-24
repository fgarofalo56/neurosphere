import type { Page } from "@playwright/test";
import { expect, test } from "../../e2e-support/fixtures.ts";
import { openSample, seedPreferences, type Mode } from "./axe-support.ts";
import { Recorder, writePrecheckAggregate } from "./precheck-support.ts";
import { ROUTE_SAMPLES } from "./route-samples.ts";

// PRP-24 item 3b: per-route keyboard sweep for every route in route-manifest.json (one sample per
// manifest pattern, shared with the axe spec). Tab through up to MAX_STOPS stops and assert that
// every stop is a visible element with a visible focus indicator, that focus is never stuck, and
// that the page has an h1. This is an automated PRE-CHECK; it does not judge whether the focus
// ORDER is logical (a human decides that) and it does not replace the signed checklist.
//
// Focus-indicator method (robust to Fluent UI v9, which draws its ring on a ::after pseudo-element,
// and on a wrapper for inputs): the focused element passes when ANY of these hold, evaluated by
// getComputedStyle while the element has keyboard focus (:focus-visible):
//   1. the element itself, or an ancestor within 3 levels that matches :focus-within, has a real
//      outline (outline-style != none and outline-width > 0) or a non-"none" box-shadow;
//   2. the same nodes' ::after or ::before pseudo-element (only when it generates content) has an
//      outline, a non-"none" box-shadow or a border with width > 0.
//   3. a descendant up to 2 levels down has a real outline (Fluent Tree items paint the ring on
//      their layout child).
// A bare Fluent attribute (data-fui-focus-visible) is NOT accepted on its own: it only proves the
// library flagged the element, not that a ring is painted.

const MAX_STOPS = 80;
const MAX_PRESSES = 140;
const SWEEP_MODES: readonly Mode[] = ["light", "high-contrast"];

interface Stop {
  readonly kind: "body" | "sentinel" | "element";
  readonly label: string;
  readonly signature: number;
  readonly visible: boolean;
  readonly indicator: string | null;
  readonly tabbable: number;
}

async function probe(page: Page): Promise<Stop> {
  return page.evaluate((): Stop => {
    const el = document.activeElement;
    const empty = { label: "", signature: -1, visible: false, indicator: null, tabbable: 0 };
    if (el === null || el === document.body || el === document.documentElement) {
      return { kind: "body", ...empty };
    }
    if (el.hasAttribute("data-tabster-dummy")) return { kind: "sentinel", ...empty };

    const label = `${el.tagName.toLowerCase()}${el.getAttribute("role") ? `[role=${el.getAttribute("role")}]` : ""} "${(el.getAttribute("aria-label") ?? el.textContent ?? "").trim().replace(/\s+/g, " ").slice(0, 40)}"`;
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    const inViewport =
      rect.bottom > 0 &&
      rect.right > 0 &&
      rect.top < window.innerHeight &&
      rect.left < window.innerWidth;
    const visible =
      rect.width > 0 &&
      rect.height > 0 &&
      style.visibility !== "hidden" &&
      style.display !== "none" &&
      inViewport;

    const painted = (s: CSSStyleDeclaration, pseudo: boolean): string | null => {
      if (s.outlineStyle !== "none" && parseFloat(s.outlineWidth) > 0) return "outline";
      if (s.boxShadow !== "" && s.boxShadow !== "none") return "box-shadow";
      if (pseudo && s.borderStyle !== "none" && parseFloat(s.borderWidth) > 0) return "border";
      return null;
    };
    let indicator: string | null = null;
    let node: Element | null = el;
    for (let depth = 0; depth < 4 && node !== null && indicator === null; depth += 1) {
      if (node === el || node.matches(":focus-within")) {
        indicator = painted(getComputedStyle(node), false);
        for (const pseudo of ["::after", "::before"] as const) {
          if (indicator !== null) break;
          const ps = getComputedStyle(node, pseudo);
          if (ps.content !== "none" && ps.content !== "normal") {
            const found = painted(ps, true);
            if (found !== null) indicator = `${pseudo} ${found}`;
          }
        }
      }
      node = node.parentElement;
    }
    // Composite widgets (Fluent Tree items) paint the ring on their layout child, not the focused
    // node: accept a real outline on a descendant up to 2 levels down.
    if (indicator === null) {
      for (const child of el.querySelectorAll(":scope > *, :scope > * > *")) {
        const s = getComputedStyle(child);
        if (s.outlineStyle !== "none" && parseFloat(s.outlineWidth) > 0) {
          indicator = "descendant outline";
          break;
        }
      }
    }

    const tabbable = [
      ...document.querySelectorAll(
        "a[href],button:not([disabled]),input:not([disabled]):not([type=hidden]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex='-1']),iframe",
      ),
    ].filter((n) => {
      const r = n.getBoundingClientRect();
      return r.width > 0 && r.height > 0 && !n.hasAttribute("data-tabster-dummy");
    }).length;

    return {
      kind: "element",
      label,
      signature: [...document.querySelectorAll("*")].indexOf(el),
      visible,
      indicator,
      tabbable,
    };
  });
}

test.afterAll(() => {
  writePrecheckAggregate();
});

for (const mode of SWEEP_MODES) {
  for (const sample of ROUTE_SAMPLES) {
    test(`keyboard sweep: ${sample.pattern} (${sample.name}) in ${mode}`, async ({ page }) => {
      const r = new Recorder("keyboard-route", sample.pattern, mode);
      await seedPreferences(page, { mode });
      await openSample(page, sample);

      const notVisible: string[] = [];
      const noIndicator: string[] = [];
      const seen = new Map<number, number>();
      let stops = 0;
      let presses = 0;
      let stuck: string | null = null;
      let cycle: string | null = null;
      let wrapped = false;
      let previous = -2;
      let same = 0;

      while (stops < MAX_STOPS && presses < MAX_PRESSES) {
        await page.keyboard.press("Tab");
        presses += 1;
        const stop = await probe(page);
        if (stop.kind === "body") {
          wrapped = true;
          break;
        }
        if (stop.kind === "sentinel") continue;
        stops += 1;
        if (!stop.visible) notVisible.push(stop.label);
        if (stop.indicator === null) noIndicator.push(stop.label);
        same = stop.signature === previous ? same + 1 : 0;
        previous = stop.signature;
        if (same >= 2 && stuck === null) stuck = stop.label;
        if (seen.has(stop.signature) && !wrapped && cycle === null && same === 0) {
          // Revisiting an element before ever leaving the page: a trap unless the page truly has
          // only this many tab stops.
          if (seen.size < stop.tabbable * 0.5) {
            cycle = `${stop.label} revisited after ${String(seen.size)} unique stops of ~${String(stop.tabbable)} tabbable`;
          }
        }
        seen.set(stop.signature, stops);
        if (stuck !== null || cycle !== null) break;
      }

      const summary = `${String(stops)} stops${wrapped ? ", focus left the page" : `, capped at ${String(MAX_STOPS)}`}`;
      await r.check("Tab sweep reaches at least one stop", () => {
        expect(stops, summary).toBeGreaterThan(0);
      });
      await r.check(
        "focus always lands on a visible element",
        () => {
          expect(notVisible.length, `focused but not visible: ${notVisible.join("; ")}`).toBe(0);
        },
        summary,
      );
      await r.check(
        "every focused element shows a focus indicator",
        () => {
          expect(
            noIndicator.length,
            `no outline, box-shadow or ring pseudo-element on: ${noIndicator.join("; ")}`,
          ).toBe(0);
        },
        summary,
      );
      await r.check("no keyboard trap (focus changes or leaves the page)", () => {
        expect(stuck, "focus stuck on one element").toBeNull();
        expect(cycle, "focus cycles inside a subset of the page").toBeNull();
      });
      await r.check("the page has a visible h1", async () => {
        await expect(page.locator("h1:visible").first()).toBeVisible();
      });
      r.finish();
    });
  }
}
