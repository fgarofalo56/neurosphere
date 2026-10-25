import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { build, defineConfig, type Plugin } from "vite";
// @ts-expect-error plain ESM script without type declarations
import { writeBundleReport } from "./scripts/bundle-report.mjs";

const distDir = fileURLToPath(new URL("./dist", import.meta.url));
const rootDir = fileURLToPath(new URL(".", import.meta.url));
const SANDBOX_PAGE = "chart-sandbox.html";
const SANDBOX_ENTRY = fileURLToPath(
  new URL("./src/features/charts/sandbox/main.ts", import.meta.url),
);

/** Writes dist/bundle-report.json after every production build. */
function bundleReport(): Plugin {
  return {
    name: "ns-bundle-report",
    apply: "build",
    closeBundle: {
      order: "post",
      handler() {
        writeBundleReport(distDir);
      },
    },
  };
}

/**
 * Chart sandbox document (PRP-19 item 4). The sandboxed iframe has an opaque origin, so an
 * external module script would need CORS and a `script-src 'self'` match. Instead the sandbox
 * entry is bundled to one IIFE, inlined, and allowed by a sha256 hash in the CSP meta tag:
 * `script-src 'sha256-...'` with no 'unsafe-inline' and no 'unsafe-eval'. The same page is
 * served by `vite dev` and emitted by `vite build`.
 */
function chartSandbox(): Plugin {
  let cached: Promise<string> | null = null;

  async function renderPage(): Promise<string> {
    const result = await build({
      root: rootDir,
      configFile: false,
      logLevel: "silent",
      define: { "process.env.NODE_ENV": '"production"' },
      build: {
        write: false,
        minify: true,
        lib: { entry: SANDBOX_ENTRY, formats: ["iife"], name: "NsChartSandbox" },
      },
    });
    const outputs = (Array.isArray(result) ? result : [result]).flatMap((r) =>
      "output" in r ? r.output : [],
    );
    const chunk = outputs.find((o) => o.type === "chunk");
    if (chunk === undefined || chunk.type !== "chunk") throw new Error("sandbox bundle failed");
    const script = chunk.code.replaceAll("</script", "<\\/script").replaceAll("<!--", "<\\!--");
    const template = readFileSync(`${rootDir}${SANDBOX_PAGE}`, "utf8");
    // The hash covers the exact text between the script tags, whatever the template whitespace.
    const openParts = template.split("<script>");
    const closeParts = template.split("</script>");
    if (openParts.length !== 2 || closeParts.length !== 2) {
      throw new Error("sandbox template must contain exactly one inline script");
    }
    const body = (openParts[1] ?? "").split("</script>")[0] ?? "";
    const inlineScript = body.replace("%NS_SANDBOX_SCRIPT%", () => script);
    const hash = createHash("sha256").update(inlineScript).digest("base64");
    const csp = [
      "default-src 'none'",
      `script-src 'sha256-${hash}'`,
      "connect-src 'none'",
      "img-src 'none'",
      "font-src 'none'",
      "style-src 'none'",
      "frame-src 'none'",
      "object-src 'none'",
      "base-uri 'none'",
      "form-action 'none'",
    ].join("; ");
    return template
      .replace("%NS_SANDBOX_SCRIPT%", () => script)
      .replace("%NS_SANDBOX_CSP%", () => csp);
  }

  return {
    name: "ns-chart-sandbox",
    configureServer(server) {
      server.watcher.on("change", (file) => {
        if (file.replaceAll("\\", "/").includes("/src/features/charts/")) cached = null;
      });
      server.middlewares.use(`/${SANDBOX_PAGE}`, (_req, res, next) => {
        cached ??= renderPage();
        cached.then(
          (page) => {
            res.setHeader("Content-Type", "text/html; charset=utf-8");
            res.setHeader("Cache-Control", "no-store");
            res.end(page);
          },
          (error: unknown) => next(error),
        );
      });
    },
    async generateBundle() {
      this.emitFile({ type: "asset", fileName: SANDBOX_PAGE, source: await renderPage() });
    },
  };
}

const DEV_API_TARGET = process.env["NS_DEV_API_TARGET"] ?? "http://127.0.0.1:8000";

// No `define` block on purpose: nothing from the environment is inlined except
// the non-secret VITE_NS_* local-dev defaults Vite exposes via import.meta.env.
export default defineConfig(({ command, mode }) => ({
  plugins: [react(), chartSandbox(), bundleReport()],
  // Same-origin dev proxy (PRP-29 item 5): only for a plain `vite` dev server. The e2e/demo
  // modes talk to the mock API and vitest (mode "test") never needs a proxy.
  server:
    command === "serve" && !["e2e", "demo", "test"].includes(mode)
      ? {
          proxy: {
            "/api": { target: DEV_API_TARGET, changeOrigin: true, ws: true },
            "/readyz": { target: DEV_API_TARGET, changeOrigin: true },
            "/healthz": { target: DEV_API_TARGET, changeOrigin: true },
          },
        }
      : {},
  test: {
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}", "tests/**/*.test.{ts,tsx}"],
  },
}));
