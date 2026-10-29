// Grant, McpServer and GRANTS_ACCESS_TO against the generated TypeScript types (PRP-33 item 5).
//
// roundtrip.test.ts already type-checks every catalog example; this file pins the new
// contracts explicitly: the golden fixtures round-trip as JSON and type-check as their root
// type, and shape violations the TS types can express (closed objects, closed enums) fail
// tsc. Cross-field conditionals (MCP grants are call-limited only, token_quota needs
// quota_period, publishable false for sse/api_key) are JSON Schema only (ADR-0004) and are
// covered by tests/contracts/test_grant_and_mcp_server.py.
//
// Run with: pnpm --filter ./packages/contracts/ts test
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { beforeAll, describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "..", "..", "..");
const examples = join(repoRoot, "packages", "contracts", "schemas", "catalog", "v1", "examples");
const tsPackage = join(repoRoot, "packages", "contracts", "ts");
const srcDir = join(tsPackage, "src");
const posix = (p: string): string => p.split(sep).join("/");
const readJson = (rel: string): any => JSON.parse(readFileSync(join(examples, rel), "utf8"));

const GOLDEN: [string, string][] = [
  ["valid/grant.user-model-deployment-token-limits.json", "Grant"],
  ["valid/grant.entra-group-mcp-calls.json", "Grant"],
  ["valid/mcp_server.entra-streamable-http.json", "McpServer"],
  ["valid/mcp_server.api-key-not-publishable.json", "McpServer"],
  ["valid/grants_access_to.asserted.json", "GrantsAccessToRelation"],
];

type Mutation = [id: string, type: string, base: string, mutate: (doc: any) => void];

const SHAPE_VIOLATIONS: Mutation[] = [
  ["grant: unknown limits member", "Grant", GOLDEN[0]![0], (d) => (d.limits.tokens_per_hour = 1)],
  ["grant: unknown principal kind", "Grant", GOLDEN[0]![0], (d) => (d.principal.kind = "sp")],
  ["grant: unknown target kind", "Grant", GOLDEN[1]![0], (d) => (d.target.kind = "agent")],
  ["grant: unknown quota period", "Grant", GOLDEN[0]![0], (d) => (d.limits.quota_period = "q")],
  ["grant: enabled as string", "Grant", GOLDEN[0]![0], (d) => (d.enabled = "true")],
  ["mcp: credential in auth", "McpServer", GOLDEN[3]![0], (d) => (d.auth.api_key = "x")],
  ["mcp: unknown transport", "McpServer", GOLDEN[2]![0], (d) => (d.transport = "stdio")],
  ["mcp: camelCase annotation", "McpServer", GOLDEN[2]![0], (d) => (d.tools[0].annotations.readOnlyHint = true)],
];

describe("Grant and McpServer golden fixtures", () => {
  it.each(GOLDEN)("JSON round trip: %s", (rel) => {
    const raw = readFileSync(join(examples, rel), "utf8");
    const parsed = JSON.parse(raw);
    expect(JSON.parse(JSON.stringify(parsed))).toStrictEqual(parsed);
  });

  it("MCP grant fixture is call-limited only", () => {
    const grant = readJson(GOLDEN[1]![0]);
    expect(grant.target.kind).toBe("mcp_server");
    expect(grant.limits).toStrictEqual({ mcp_calls_per_minute: 60 });
  });
});

describe("Grant and McpServer against the generated types (tsc, strict)", () => {
  const require = createRequire(join(tsPackage, "package.json"));
  const ts = require("typescript") as typeof import("typescript");
  const virtualFile = join(here, "__grant_mcp_typecheck__.ts");
  const ranges: { id: string; start: number; end: number; valid: boolean }[] = [];
  let diagnostics: { line: number; text: string }[] = [];

  beforeAll(() => {
    const indexImport = posix(relative(here, join(srcDir, "index.js")));
    const lines = [`import type { Grant, GrantsAccessToRelation, McpServer } from "${indexImport}";`, ""];
    const add = (id: string, type: string, doc: unknown, valid: boolean, i: number) => {
      const statement = `export const case_${i}: ${type} = ${JSON.stringify(doc, null, 2)};`;
      const start = lines.length;
      lines.push(...statement.split("\n"));
      ranges.push({ id, start, end: lines.length - 1, valid });
    };
    let i = 0;
    for (const [rel, type] of GOLDEN) add(rel, type, readJson(rel), true, i++);
    for (const [id, type, base, mutate] of SHAPE_VIOLATIONS) {
      const doc = readJson(base);
      mutate(doc);
      add(id, type, doc, false, i++);
    }
    const text = lines.join("\n") + "\n";

    const config = ts.readConfigFile(join(tsPackage, "tsconfig.json"), ts.sys.readFile);
    const parsed = ts.parseJsonConfigFileContent(config.config, ts.sys, tsPackage);
    const options = { ...parsed.options, noEmit: true };
    const host = ts.createCompilerHost(options, true);
    const same = (f: string) => resolve(f).toLowerCase() === virtualFile.toLowerCase();
    const getSourceFile = host.getSourceFile.bind(host);
    host.getSourceFile = (fileName, languageVersion, onError, shouldCreate) =>
      same(fileName)
        ? ts.createSourceFile(fileName, text, languageVersion, true)
        : getSourceFile(fileName, languageVersion, onError, shouldCreate);
    const fileExists = host.fileExists.bind(host);
    host.fileExists = (f) => same(f) || fileExists(f);
    const readFile = host.readFile.bind(host);
    host.readFile = (f) => (same(f) ? text : readFile(f));

    const program = ts.createProgram([virtualFile], options, host);
    const all = [
      ...program.getSyntacticDiagnostics(),
      ...program.getSemanticDiagnostics(),
      ...program.getGlobalDiagnostics(),
    ];
    diagnostics = all.map((d) => ({
      line: d.file && d.start !== undefined ? d.file.getLineAndCharacterOfPosition(d.start).line : -1,
      text: ts.flattenDiagnosticMessageText(d.messageText, "\n"),
    }));
  }, 120_000);

  const owner = (line: number) => ranges.find((r) => line >= r.start && line <= r.end);

  it("resolves the three root types from the package index", () => {
    expect(diagnostics.filter((d) => owner(d.line) === undefined)).toEqual([]);
  });

  it("type-checks every golden fixture", () => {
    const failures = diagnostics
      .filter((d) => owner(d.line)?.valid)
      .map((d) => `${owner(d.line)!.id}: ${d.text.split("\n")[0]}`);
    expect(failures).toEqual([]);
    expect(ranges.filter((r) => r.valid).length).toBe(GOLDEN.length);
  });

  it("rejects every shape violation", () => {
    const rejected = new Set(diagnostics.map((d) => owner(d.line)?.id));
    const accepted = ranges.filter((r) => !r.valid && !rejected.has(r.id)).map((r) => r.id);
    expect(accepted).toEqual([]);
  });
});
