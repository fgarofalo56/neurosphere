import { expect, test, type ConsoleMessage, type Page } from "@playwright/test";

const HARNESS = "/src/features/charts/harness/index.html";

/** Chromium reports CSP violations in any frame as console errors; collect them all. */
function watch(page: Page) {
  const problems: string[] = [];
  page.on("pageerror", (error) => problems.push(`pageerror: ${error.message}`));
  page.on("console", (msg: ConsoleMessage) => {
    const text = msg.text();
    if (msg.type() === "error" || /content security policy|refused to|securitypolicy/i.test(text)) {
      problems.push(`console ${msg.type()}: ${text}`);
    }
  });
  return problems;
}

async function status(page: Page): Promise<string> {
  return page.evaluate(
    () => (window as unknown as { __chart?: { status: string } }).__chart?.status ?? "none",
  );
}

for (const [plan, markClass] of [
  ["bar", ".mark-rect"],
  ["line", ".mark-line"],
  ["area", ".mark-area"],
  ["point", ".mark-symbol"],
] as const) {
  test(`renders a ${plan} chart in the sandbox with no CSP violations`, async ({ page }) => {
    const problems = watch(page);
    await page.goto(`${HARNESS}?plan=${plan}`);

    await expect.poll(() => status(page), { timeout: 30_000 }).toBe("rendered");

    const frameHandle = page.locator("iframe");
    await expect(frameHandle).toHaveAttribute("sandbox", "allow-scripts");
    const frame = page.frameLocator("iframe");
    await expect(frame.locator(`svg ${markClass}`).first()).toBeAttached();
    expect(await frame.locator("svg path, svg rect").count()).toBeGreaterThan(0);
    expect(problems).toEqual([]);
  });
}

test("a container-width chart renders with the interpreter", async ({ page }) => {
  const problems = watch(page);
  await page.goto(`${HARNESS}?plan=bar&width=container`);
  await expect.poll(() => status(page), { timeout: 30_000 }).toBe("rendered");
  await expect(page.frameLocator("iframe").locator("svg .mark-rect").first()).toBeAttached();
  expect(problems).toEqual([]);
});

test("the sandboxed document has an opaque origin and cannot reach the parent", async ({
  page,
}) => {
  const problems = watch(page);
  await page.goto(`${HARNESS}?plan=bar`);
  await expect.poll(() => status(page), { timeout: 30_000 }).toBe("rendered");

  const handle = await page.locator("iframe").elementHandle();
  const frame = await handle?.contentFrame();
  expect(frame).toBeTruthy();
  expect(await frame?.evaluate(() => window.origin)).toBe("null");
  const parentAccess = await frame?.evaluate(() => {
    try {
      return String(window.parent.document.title);
    } catch {
      return "blocked";
    }
  });
  expect(parentAccess).toBe("blocked");
  const storage = await frame?.evaluate(() => {
    try {
      return String(window.localStorage.length);
    } catch {
      return "blocked";
    }
  });
  expect(storage).toBe("blocked");
  expect(problems).toEqual([]);
});

test("the sandbox CSP forbids eval and inline script other than its own hash", async ({ page }) => {
  await page.goto(`${HARNESS}?plan=bar`);
  await expect.poll(() => status(page), { timeout: 30_000 }).toBe("rendered");
  const handle = await page.locator("iframe").elementHandle();
  const frame = await handle?.contentFrame();
  const csp = await frame?.evaluate(
    () =>
      document
        .querySelector('meta[http-equiv="Content-Security-Policy"]')
        ?.getAttribute("content") ?? "",
  );
  expect(csp).toMatch(/default-src 'none'/);
  expect(csp).toMatch(/script-src 'sha256-[A-Za-z0-9+/=]+'/);
  expect(csp).toMatch(/connect-src 'none'/);
  expect(csp).not.toMatch(/unsafe-eval|unsafe-inline/);
  // An injected inline script must be blocked by the CSP (devtools evaluation bypasses the CSP,
  // a script element does not).
  const violations: string[] = [];
  page.on("console", (msg) => {
    if (/content security policy/i.test(msg.text())) violations.push(msg.text());
  });
  const ran = await frame?.evaluate(() => {
    const el = document.createElement("script");
    el.textContent = "window.__injected = 1";
    document.body.append(el);
    return (window as unknown as { __injected?: number }).__injected ?? 0;
  });
  expect(ran).toBe(0);
  await expect.poll(() => violations.length).toBeGreaterThan(0);
});

test("a plan carrying expr never reaches render", async ({ page }) => {
  await page.goto(`${HARNESS}?plan=expr`);
  await expect.poll(() => status(page)).toBe("rejected");
  await expect(page.locator("iframe")).toHaveCount(0);
  await expect(page.getByRole("alert")).toContainText("blocked");
  // The data stays reachable through the accessible table.
  await expect(page.getByRole("table", { name: "Cost by month" })).toBeVisible();
});
