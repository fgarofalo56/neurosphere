import { createQueryHook } from "../../api/index.js";
import { sandboxStatusPath } from "./paths";
import type { SandboxSummary } from "./types";

export const useSandboxStatus = createQueryHook<Record<string, never>, SandboxSummary>({
  key: "sandbox-status",
  fetcher: (client, _params, signal) =>
    client.get<SandboxSummary>(sandboxStatusPath(), undefined, signal),
});
