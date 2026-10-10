// GENERATOR DRIVER, not generated output. Invoked by generate.py; do not run directly.
//
// Reads a JSON job from stdin:
//   {"schemaRoot": "<abs dir>", "outDir": "<abs dir>", "banner": "<comment>",
//    "files": ["<area>/v1/<name>.json", ...], "expectedVersion": "<pin>"}
// (staged copies, see generate.py stage_schemas) and writes one TypeScript module per
// schema to <outDir>/<area>/v1/<name>.ts.
//
// json-schema-to-typescript is resolved from packages/contracts/ts/node_modules so the
// version pinned in packages/contracts/ts/package.json (and pnpm-lock.yaml) is the one used.
// $ref resolution is file-only: the HTTP resolver is disabled, so a remote $ref fails the
// run instead of fetching (PRP-01 gotcha: no network, relative file refs only).
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { createRequire } = require("node:module");

const tsPackageJson = path.resolve(__dirname, "..", "ts", "package.json");
const requireFromTs = createRequire(tsPackageJson);
const { compileFromFile } = requireFromTs("json-schema-to-typescript");
const generatorVersion = requireFromTs("json-schema-to-typescript/package.json").version;

async function main() {
  const job = JSON.parse(fs.readFileSync(0, "utf8"));
  if (job.expectedVersion !== generatorVersion) {
    throw new Error(
      `json-schema-to-typescript ${generatorVersion} is installed but ${job.expectedVersion} ` +
        "is pinned; run pnpm install --frozen-lockfile",
    );
  }
  const files = [...job.files].sort();
  for (const rel of files) {
    const abs = path.join(job.schemaRoot, ...rel.split("/"));
    const ts = await compileFromFile(abs, {
      cwd: path.dirname(abs),
      bannerComment: job.banner,
      additionalProperties: false,
      declareExternallyReferenced: true,
      enableConstEnums: false,
      format: true,
      // Cardinality bounds stay in JSON Schema; tuple unions for minItems/maxItems are noise.
      maxItems: -1,
      strictIndexSignatures: true,
      unknownAny: true,
      unreachableDefinitions: true,
      style: {
        printWidth: 100,
        singleQuote: false,
        semi: true,
        trailingComma: "all",
        endOfLine: "lf",
        tabWidth: 2,
        useTabs: false,
      },
      $refOptions: {
        resolve: { http: false, external: true },
      },
    });
    if (!rel.endsWith(".json")) {
      throw new Error(`unexpected staged schema name: ${rel}`);
    }
    const outPath = path.join(job.outDir, ...rel.replace(/\.json$/, ".ts").split("/"));
    fs.mkdirSync(path.dirname(outPath), { recursive: true });
    fs.writeFileSync(outPath, ts.replace(/\r\n/g, "\n"), { encoding: "utf8" });
  }
}

main().catch((err) => {
  process.stderr.write(`json2ts driver failed: ${err && err.stack ? err.stack : err}\n`);
  process.exit(1);
});
