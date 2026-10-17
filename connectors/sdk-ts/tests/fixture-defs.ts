// Definitions of the TS-produced interop manifests. tests/manifest.interop.test.ts rebuilds them
// with buildManifest and diff-checks tests/fixtures/manifests/*.json; run with
// UPDATE_INTEROP_FIXTURES=1 to rewrite the committed files.

import { type ConnectorManifest, buildManifest } from "../src/index.js";

export const TS_FIXTURES: Readonly<Record<string, () => ConnectorManifest>> = {
  "ts-vault-reference-both-clouds": () =>
    buildManifest({
      name: "ts-vault-demo",
      version: "1.2.3",
      capabilities: ["usage_reports", "health_reporting"],
      supportedClouds: ["commercial", "government"],
      granularity: { time_grain: "hour", subject_level: "deployment" },
      freshness: { typical_delay_ms: 300000, max_delay_ms: 3600000 },
      scopes: ["Reports.Read.All"],
      rateLimits: [{ limit_scope: "per_credential", max_requests: 100, window_ms: 60000 }],
      credentialRefs: [
        { name: "api_key", vault_ref: "https://demo-vault.vault.azure.net/secrets/api-key" },
        {
          name: "gov_key",
          vault_ref:
            "https://demo-gov.vault.usgovcloudapi.net/secrets/gov-key/0123456789abcdef0123456789abcdef",
        },
      ],
      documentationUrl: "https://docs.example.com/connectors/ts-vault-demo",
    }),
  "ts-managed-identity-unknowns": () =>
    buildManifest({
      name: "ts-mi-demo",
      version: "0.1.0",
      capabilities: ["telemetry_ingest"],
      supportedClouds: ["commercial"],
      granularity: { time_grain: "unknown", subject_level: "unknown" },
    }),
  "ts-workload-identity-no-limits": () =>
    buildManifest({
      name: "ts-wif-demo",
      version: "2.0.0-rc.1",
      capabilities: ["cost_ingest", "catalog_discovery"],
      supportedClouds: ["government"],
      granularity: { time_grain: "day", subject_level: "tenant" },
      freshness: { typical_delay_ms: null, max_delay_ms: 86400000 },
      rateLimits: [],
      authMode: "workload_identity_federation",
    }),
};
