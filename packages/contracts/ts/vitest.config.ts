// The TypeScript round-trip tests for the generated contract types live with the other
// contract tests in tests/contracts/ (PRP-01 item 7 owns them); this package only runs them.
// Until they land, `vitest run --passWithNoTests` reports "no test files" and exits 0.
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    dir: "../../../tests/contracts",
    include: ["**/*.test.ts"],
    environment: "node",
  },
});
