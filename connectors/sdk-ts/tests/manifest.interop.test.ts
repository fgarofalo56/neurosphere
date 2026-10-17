import { mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { InvalidManifestError, manifestIssues, validateManifest } from "../src/index.js";
import { TS_FIXTURES } from "./fixture-defs.js";

const TS_DIR = fileURLToPath(new URL("./fixtures/manifests/", import.meta.url));
const PY_DIR = fileURLToPath(
  new URL("../../sdk-python/tests/interop/fixtures/", import.meta.url),
);

function jsonFiles(dir: string): string[] {
  return readdirSync(dir)
    .filter((f) => f.endsWith(".json"))
    .sort();
}

const read = (dir: string, file: string): string => readFileSync(`${dir}${file}`, "utf-8");

describe("TS-produced fixtures", () => {
  it("match what buildManifest produces (UPDATE_INTEROP_FIXTURES=1 rewrites)", () => {
    mkdirSync(TS_DIR, { recursive: true });
    for (const [name, make] of Object.entries(TS_FIXTURES)) {
      const text = `${JSON.stringify(make(), null, 2)}\n`;
      if (process.env["UPDATE_INTEROP_FIXTURES"] === "1") {
        writeFileSync(`${TS_DIR}${name}.json`, text);
      }
      expect(read(TS_DIR, `${name}.json`)).toBe(text);
    }
    expect(jsonFiles(TS_DIR)).toEqual(Object.keys(TS_FIXTURES).map((n) => `${n}.json`).sort());
  });
});

describe("Python-produced fixtures validate with the TS validator", () => {
  const files = jsonFiles(PY_DIR);

  it("exist (no vacuous pass)", () => {
    expect(files.length).toBeGreaterThan(0);
  });

  it.each(files)("%s", (file) => {
    const text = read(PY_DIR, file);
    expect(manifestIssues(text)).toEqual([]);
    expect(validateManifest(text).name).toBe((JSON.parse(text) as { name: string }).name);
  });
});

describe("shared invalid fixtures are rejected", () => {
  const invalid = jsonFiles(`${TS_DIR}invalid/`);

  it("exist in both fixture trees", () => {
    expect(invalid.length).toBeGreaterThan(0);
    expect(jsonFiles(`${PY_DIR}invalid/`)).toEqual(invalid);
  });

  it.each(invalid)("%s", (file) => {
    for (const dir of [`${TS_DIR}invalid/`, `${PY_DIR}invalid/`]) {
      const text = read(dir, file);
      expect(manifestIssues(text).length).toBeGreaterThan(0);
      expect(() => validateManifest(text)).toThrow(InvalidManifestError);
    }
  });
});
