// PRP-27 local capture: Playwright screenshots of the local sandbox UI (mock API, no cloud).
// Usage: node capture.mjs <frontendDir> <outDir> <appPort> <apiPort> [sceneId ...]
// shots.json lists, per scene, the shots. A shot is one 1280x720 PNG; the storyboard on-screen
// text is overlaid as a lower strip. The persona only selects the fake e2e token that the mock
// API reads (the stub sign-in itself is Viewer-only).
import { createRequire } from "node:module";
import path from "node:path";
import fs from "node:fs";

const [frontendDir, outDir, appPort, apiPort, ...only] = process.argv.slice(2);
const require = createRequire(path.join(path.resolve(frontendDir), "package.json"));
const { chromium } = require("@playwright/test");
const appOrigin = `http://127.0.0.1:${appPort}`;
const apiOrigin = `http://127.0.0.1:${apiPort}`;
const PREFIX = "ns-e2e-fake-token.";

const SHOTS = JSON.parse(
  fs.readFileSync(path.join(import.meta.dirname, "shots.json"), "utf8"),
);

const config = {
  cloud: "commercial",
  tenantId: "00000000-0000-0000-0000-000000000000",
  clientId: "00000000-0000-0000-0000-000000000000",
  apiBaseUrl: apiOrigin,
  apiScope: "api://neurosphere-e2e/access_as_user",
};

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1280, height: 720 } });
const page = await context.newPage();
let persona = "Viewer";
await page.route("**/config.json", (route) => route.fulfill({ json: config }));
await page.route("**/api/v1/**", (route) =>
  route.continue({
    headers: { ...route.request().headers(), authorization: `Bearer ${PREFIX}${persona}` },
  }),
);

async function sandboxOn() {
  const toggle = page.getByRole("switch", { name: "Sandbox mode" }).first();
  await toggle.waitFor({ timeout: 30000 });
  if (!(await toggle.isChecked())) await toggle.check();
  await page.getByTestId("sandbox-banner").waitFor({ timeout: 10000 });
}

async function overlay(text) {
  await page.evaluate((t) => {
    document.getElementById("ns-video-overlay")?.remove();
    const el = document.createElement("div");
    el.id = "ns-video-overlay";
    el.textContent = t;
    el.style.cssText =
      "position:fixed;left:0;right:0;bottom:0;padding:14px 24px;background:rgba(20,24,32,.92);" +
      "color:#fff;font:600 24px Segoe UI,Arial,sans-serif;z-index:2147483647;text-align:center";
    document.body.appendChild(el);
  }, text);
}

const results = {};
for (const [sceneId, shots] of Object.entries(SHOTS)) {
  if (only.length > 0 && !only.includes(sceneId)) continue;
  results[sceneId] = [];
  let index = 0;
  for (const shot of shots) {
    index += 1;
    const file = path.join(outDir, `${sceneId}_${index}.png`);
    persona = shot.persona ?? "Viewer";
    if (shot.card) {
      const card = await context.newPage();
      const body = shot.card.map((l) => `<p style="margin:12px">${l}</p>`).join("");
      await card.setContent(
        `<html><body style="margin:0;background:#1f2937;color:#f9fafb;display:flex;` +
          `flex-direction:column;align-items:center;justify-content:center;height:720px;` +
          `font:600 44px Segoe UI,Arial,sans-serif;text-align:center">${body}</body></html>`,
      );
      await card.screenshot({ path: file });
      await card.close();
    } else {
      await page.goto(`${appOrigin}${shot.path}`, { waitUntil: "load" });
      await sandboxOn();
      if (shot.wait) await page.locator(shot.wait).first().waitFor({ timeout: 30000 });
      if (shot.click) await page.locator(shot.click).first().click();
      if (shot.wait2) await page.locator(shot.wait2).first().waitFor({ timeout: 30000 });
      await page.waitForTimeout(shot.settle ?? 1500);
      if (shot.text) await overlay(shot.text);
      await page.screenshot({ path: file });
    }
    results[sceneId].push(path.basename(file));
  }
}
await browser.close();
fs.writeFileSync(path.join(outDir, "shots-result.json"), JSON.stringify(results, null, 2));
console.log(JSON.stringify(results));
