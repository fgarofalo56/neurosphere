import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";
// @ts-expect-error plain ESM script without type declarations
import { writeBundleReport } from "./scripts/bundle-report.mjs";

const distDir = fileURLToPath(new URL("./dist", import.meta.url));

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

// No `define` block on purpose: nothing from the environment is inlined except
// the non-secret VITE_NS_* local-dev defaults Vite exposes via import.meta.env.
export default defineConfig({
  plugins: [react(), bundleReport()],
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}", "tests/**/*.test.{ts,tsx}"],
  },
});
