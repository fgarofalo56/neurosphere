// TypeScript round trip of the generated contract types against the golden examples
// (PRP-01 item 7, ADR-0004 "test the generated Python and TS against the same golden
// fixtures; do not trust codegen output by inspection").
//
// Run with: pnpm --filter ./packages/contracts/ts test
//
// 1. Every schema has a generated module and a named root type exported from src/index.ts.
// 2. Every valid example survives a JSON round trip unchanged.
// 3. Every valid example type-checks against its generated type under the package's own
//    strict compiler options (TypeScript compiler API over an in-memory program).
// 4. Invalid examples that add an undeclared root member must fail the type check
//    (excess-property check on a closed object type).
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { beforeAll, describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "..", "..", "..");
const schemaRoot = join(repoRoot, "packages", "contracts", "schemas");
const tsPackage = join(repoRoot, "packages", "contracts", "ts");
const srcDir = join(tsPackage, "src");
const SUFFIX = ".schema.json";
const LIBRARY_SCHEMAS = new Set(["catalog/v1/common.schema.json"]);
const MANIFEST_NAMES = ["index.json", "manifest.json", "expectations.json"];

type Json = null | boolean | number | string | Json[] | { [key: string]: Json };

interface ExampleCase {
  schema: string; // area/v1/name.schema.json
  file: string; // absolute path
  valid: boolean;
  keyword?: string;
  instancePath?: string;
}

const posix = (p: string): string => p.split(sep).join("/");
const readJson = (p: string): any => JSON.parse(readFileSync(p, "utf8"));
const relSchema = (absolute: string): string => posix(relative(schemaRoot, resolve(absolute)));

function schemaFiles(): string[] {
  const out: string[] = [];
  for (const area of readdirSync(schemaRoot)) {
    const areaDir = join(schemaRoot, area);
    if (!statSync(areaDir).isDirectory()) continue;
    for (const major of readdirSync(areaDir)) {
      if (!/^v[1-9][0-9]*$/.test(major)) continue;
      for (const name of readdirSync(join(areaDir, major))) {
        if (name.endsWith(SUFFIX)) out.push(`${area}/${major}/${name}`);
      }
    }
  }
  return out.sort();
}

function listJson(dir: string): string[] {
  return existsSync(dir)
    ? readdirSync(dir)
        .filter((n) => n.endsWith(".json"))
        .sort()
        .map((n) => join(dir, n))
    : [];
}

// Mirrors tests/contracts/contract_support.py::example_cases (five manifest layouts).
function exampleCases(): ExampleCase[] {
  const cases: ExampleCase[] = [];
  const areas = new Set(schemaFiles().map((s) => s.split("/").slice(0, 2).join("/")));
  for (const area of [...areas].sort()) {
    const examplesDir = join(schemaRoot, area, "examples");
    if (!existsSync(examplesDir)) continue;
    const manifestName = MANIFEST_NAMES.find((n) => existsSync(join(examplesDir, n)));
    const v1 = join(schemaRoot, area);
    if (manifestName === undefined) {
      for (const [bucket, valid] of [["valid", true], ["invalid", false]] as const) {
        for (const file of listJson(join(examplesDir, bucket))) {
          const stem = file.split(sep).pop()!.split(".")[0];
          cases.push({ schema: relSchema(join(v1, `${stem}${SUFFIX}`)), file, valid });
        }
      }
      continue;
    }
    const data = readJson(join(examplesDir, manifestName));
    if (Array.isArray(data.examples)) {
      for (const e of data.examples) {
        const valid = "valid" in e ? Boolean(e.valid) : e.expect === "valid";
        const expected = e.expected_error ?? e;
        cases.push({
          schema: relSchema(join(v1, e.schema)),
          file: join(examplesDir, e.file),
          valid,
          keyword: valid ? undefined : expected.keyword,
          instancePath: valid ? undefined : expected.instance_path,
        });
      }
    } else if (Array.isArray(data.cases)) {
      for (const e of data.cases) {
        cases.push({
          schema: relSchema(join(examplesDir, e.schema)),
          file: join(examplesDir, e.file),
          valid: Boolean(e.valid),
          keyword: e.expected_error?.keyword,
          instancePath: e.expected_error?.instance_path,
        });
      }
    } else {
      for (const [bucket, valid] of [["valid", true], ["invalid", false]] as const) {
        for (const [name, e] of Object.entries<any>(data[bucket])) {
          cases.push({
            schema: relSchema(join(v1, e.schema)),
            file: join(examplesDir, bucket, name),
            valid,
            keyword: e.keyword,
            instancePath: e.instance_path,
          });
        }
      }
    }
  }
  return cases.sort((a, b) => a.file.localeCompare(b.file));
}

const pascal = (text: string): string =>
  text
    .split(/[^A-Za-z0-9]+/)
    .filter(Boolean)
    .map((p) => p[0]!.toUpperCase() + p.slice(1))
    .join("");

const schemas = schemaFiles();
const cases = exampleCases();
const typeOf = (schema: string): string => pascal(readJson(join(schemaRoot, schema)).title);
const caseId = (c: ExampleCase): string => posix(relative(schemaRoot, c.file));

describe("generated TypeScript bindings", () => {
  it("discovers the same corpus as the Python suite", () => {
    expect(schemas.length).toBeGreaterThanOrEqual(40);
    expect(cases.filter((c) => c.valid).length).toBeGreaterThanOrEqual(schemas.length - 1);
    for (const schema of schemas) {
      if (LIBRARY_SCHEMAS.has(schema)) continue;
      expect(cases.some((c) => c.schema === schema && c.valid), `${schema} valid`).toBe(true);
      expect(cases.some((c) => c.schema === schema && !c.valid), `${schema} invalid`).toBe(true);
    }
  });

  it("exports a module and a root type for every schema", () => {
    const index = readFileSync(join(srcDir, "index.ts"), "utf8");
    for (const schema of schemas) {
      const [area, major, name] = schema.split("/");
      const stem = name!.slice(0, -SUFFIX.length);
      expect(existsSync(join(srcDir, area!, major!, `${stem}.ts`)), schema).toBe(true);
      const line = `export type { ${typeOf(schema)} } from "./${area}/${major}/${stem}.js";`;
      expect(index.includes(line), line).toBe(true);
    }
  });

  it.each(cases.filter((c) => c.valid).map((c) => [caseId(c), c] as const))(
    "JSON round trip: %s",
    (_id, c) => {
      const raw = readFileSync(c.file, "utf8");
      const parsed = JSON.parse(raw) as Json;
      expect(JSON.parse(JSON.stringify(parsed))).toStrictEqual(parsed);
    },
  );
});

describe("examples against the generated types (tsc, strict)", () => {
  const require = createRequire(join(tsPackage, "package.json"));
  const ts = require("typescript") as typeof import("typescript");
  const virtualFile = join(here, "__contracts_typecheck__.ts");
  const ranges: { id: string; start: number; end: number; valid: boolean; mustFail: boolean }[] = [];
  let diagnostics: { line: number; text: string }[] = [];

  beforeAll(() => {
    const typed = cases.filter((c) => !LIBRARY_SCHEMAS.has(c.schema));
    const names = [...new Set(typed.map((c) => typeOf(c.schema)))].sort();
    const indexImport = posix(relative(here, join(srcDir, "index.js")));
    const lines = [`import type { ${names.join(", ")} } from "${indexImport}";`, ""];
    typed.forEach((c, i) => {
      const statement = `export const example_${i}: ${typeOf(c.schema)} = ${JSON.stringify(readJson(c.file), null, 2)};`;
      const start = lines.length; // zero-based line of the statement's first line
      lines.push(...statement.split("\n"));
      // A closed root object type must reject an undeclared top-level member.
      const mustFail = !c.valid && c.keyword === "additionalProperties" && c.instancePath === "";
      ranges.push({ id: caseId(c), start, end: lines.length - 1, valid: c.valid, mustFail });
    });
    const text = lines.join("\n") + "\n";

    const configPath = join(tsPackage, "tsconfig.json");
    const config = ts.readConfigFile(configPath, ts.sys.readFile);
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
    const all = [...program.getSyntacticDiagnostics(), ...program.getSemanticDiagnostics(), ...program.getGlobalDiagnostics()];
    diagnostics = all.map((d) => ({
      line: d.file && d.start !== undefined ? d.file.getLineAndCharacterOfPosition(d.start).line : -1,
      text: ts.flattenDiagnosticMessageText(d.messageText, "\n"),
    }));
  }, 120_000);

  const owner = (line: number) => ranges.find((r) => line >= r.start && line <= r.end);

  it("produces no diagnostics outside example bodies (imports resolve)", () => {
    const stray = diagnostics.filter((d) => owner(d.line) === undefined);
    expect(stray).toEqual([]);
  });

  it("type-checks every valid example", () => {
    const failures = diagnostics
      .filter((d) => owner(d.line)?.valid)
      .map((d) => `${owner(d.line)!.id}: ${d.text.split("\n")[0]}`);
    expect(failures).toEqual([]);
    expect(ranges.filter((r) => r.valid).length).toBeGreaterThan(80);
  });

  it("rejects invalid examples with an undeclared root member", () => {
    const required = ranges.filter((r) => r.mustFail);
    expect(required.length).toBeGreaterThanOrEqual(5);
    const rejected = new Set(diagnostics.map((d) => owner(d.line)?.id));
    const accepted = required.filter((r) => !rejected.has(r.id)).map((r) => r.id);
    expect(accepted).toEqual([]);
    const invalid = ranges.filter((r) => !r.valid);
    const caught = invalid.filter((r) => rejected.has(r.id)).length;
    console.log(`tsc rejects ${caught} of ${invalid.length} invalid examples (JSON Schema rejects all)`);
  });
});
