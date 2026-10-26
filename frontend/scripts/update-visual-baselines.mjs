/* global process, console */
// Generates or checks the Playwright visual baselines inside the official Playwright image, so
// they are byte-comparable with what CI renders (PRP-30 item 10, clarification 14).
//
//   node scripts/update-visual-baselines.mjs           rewrite tests/e2e/visual/__screenshots__
//   node scripts/update-visual-baselines.mjs --check   compare only (no --update-snapshots)
//
// Why a copy: the host node_modules hold native binaries for the host OS (Windows), which must
// neither be used inside a Linux container nor be overwritten from it. The container therefore
// gets the repo mounted read-only, copies the workspace sources (without node_modules) to /work,
// installs its own dependencies there, runs the `visual` project and, in update mode, copies only
// the screenshots back to the host through a second mount.
//
// Windows Git Bash: docker is spawned with an argument array and `--mount` (not `-v`), so no shell
// and no MSYS path conversion is involved. Needs Docker running; no network beyond the image pull
// and the package registry for `pnpm install`.
import { spawnSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const frontendDir = resolve(here, "..");
const repoRoot = resolve(frontendDir, "..");
const shotsDir = join(frontendDir, "tests", "e2e", "visual", "__screenshots__");

const check = process.argv.includes("--check");
const unknown = process.argv.slice(2).filter((a) => a !== "--check");
if (unknown.length > 0) {
  console.error(`unknown argument(s): ${unknown.join(" ")} (only --check is supported)`);
  process.exit(2);
}

// The image tag must equal the installed @playwright/test, or browser builds differ.
const require = createRequire(join(frontendDir, "package.json"));
const { version } = require("@playwright/test/package.json");
const image = `mcr.microsoft.com/playwright:v${version}-noble`;

mkdirSync(shotsDir, { recursive: true });

// Runs inside the container. Only fixed text: nothing from the host is interpolated into it.
const containerScript = [
  "set -euo pipefail",
  "mkdir -p /work",
  "cd /repo",
  "tar --exclude=node_modules --exclude=test-results --exclude=playwright-report -cf - " +
    "package.json pnpm-workspace.yaml pnpm-lock.yaml tsconfig.base.json .node-version " +
    "frontend packages/contracts connectors/sdk-ts | tar -xf - -C /work",
  "cd /work",
  "corepack enable",
  "pnpm install --frozen-lockfile",
  "cd /work/frontend",
  'if [ "$NS_VISUAL_MODE" = "check" ]; then',
  "  pnpm exec playwright test --project=visual --reporter=line --update-snapshots=none",
  "else",
  "  pnpm exec playwright test --project=visual --reporter=line --update-snapshots",
  "  mkdir -p /out",
  "  cp -R tests/e2e/visual/__screenshots__/. /out/",
  "fi",
].join("\n");

const args = [
  "run",
  "--rm",
  "--init",
  "--ipc=host",
  "-e",
  `NS_VISUAL_MODE=${check ? "check" : "update"}`,
  "-e",
  "NS_VISUAL=1",
  "--mount",
  `type=bind,source=${repoRoot},target=/repo,readonly`,
  "--mount",
  `type=bind,source=${shotsDir},target=/out`,
  image,
  "bash",
  "-c",
  containerScript,
];

console.log(`${check ? "Checking" : "Updating"} visual baselines in ${image}`);
const result = spawnSync("docker", args, { stdio: "inherit", env: process.env });
if (result.error) {
  console.error(`could not start docker: ${result.error.message}`);
  process.exit(2);
}
process.exit(result.status ?? 1);
