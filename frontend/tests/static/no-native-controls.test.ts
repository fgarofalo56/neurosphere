import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve, sep } from "node:path";
import ts from "typescript";
import { describe, expect, it } from "vitest";

/**
 * PRP-28 items 4-7: feature and app pages use Fluent controls, never native form controls.
 * The scan walks the TypeScript AST (JsxOpeningElement and JsxSelfClosingElement tag names), so
 * multi-line tags are found and no HTML is parsed with a regular expression.
 */

const NATIVE_TAGS: ReadonlySet<string> = new Set(["input", "select", "button", "textarea"]);

// Vitest runs with the frontend package as cwd (pnpm --filter / cd frontend).
const FRONTEND_ROOT = resolve(process.cwd());
const SCAN_DIRS = ["src/features", "src/app"];

/** One allowed native control: file (posix, relative to `frontend/`), tag and exact count. */
interface Allowed {
  readonly file: string;
  readonly tag: string;
  readonly count: number;
  readonly reason: string;
}

const ALLOWLIST: readonly Allowed[] = [
  {
    file: "src/app/ErrorBoundary.tsx",
    tag: "button",
    count: 1,
    reason:
      'crash fallback "Try again" button; kept native and dependency-free so the fallback still renders when the Fluent provider or theme is what failed',
  },
  {
    file: "src/features/map-table/MapGrid.tsx",
    tag: "button",
    count: 1,
    reason:
      'native "Load more in <parent>" button inside a PRP-18 treegrid cell; kept native for the treegrid roving-focus keyboard model',
  },
];

function findNativeControls(source: string, fileName = "fixture.tsx"): string[] {
  const sf = ts.createSourceFile(fileName, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const found: string[] = [];
  const visit = (node: ts.Node): void => {
    if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
      const tag = node.tagName.getText(sf);
      if (NATIVE_TAGS.has(tag)) found.push(tag);
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  return found;
}

function isScanned(path: string): boolean {
  return path.endsWith(".tsx") && !/\.(test|spec)\.tsx$/.test(path) && !path.includes("__tests__");
}

function listFiles(dir: string): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) {
      if (name === "__tests__" || name === "__fixtures__" || name === "node_modules") continue;
      out.push(...listFiles(full));
    } else if (isScanned(full)) {
      out.push(full);
    }
  }
  return out;
}

function scanTree(): Map<string, Map<string, number>> {
  const byFile = new Map<string, Map<string, number>>();
  for (const dir of SCAN_DIRS) {
    for (const file of listFiles(join(FRONTEND_ROOT, dir))) {
      const tags = findNativeControls(readFileSync(file, "utf8"), file);
      if (tags.length === 0) continue;
      const counts = new Map<string, number>();
      for (const tag of tags) counts.set(tag, (counts.get(tag) ?? 0) + 1);
      byFile.set(relative(FRONTEND_ROOT, file).split(sep).join("/"), counts);
    }
  }
  return byFile;
}

describe("no native form controls in features and app", () => {
  it("scanner finds a multi-line <button> and the other native tags", () => {
    const src = [
      "export const A = () => (",
      "  <div>",
      "    <button",
      '      type="button"',
      "      onClick={() => undefined}",
      "    >",
      "      go",
      "    </button>",
      '    <input value="x" readOnly />',
      "    <select><option>a</option></select>",
      "    <textarea />",
      "    <Button>fluent</Button>",
      "  </div>",
      ");",
    ].join("\n");
    expect(findNativeControls(src).sort()).toEqual(["button", "input", "select", "textarea"]);
  });

  it("scanner ignores Fluent components and tags named in strings or comments", () => {
    const src = [
      'const s = "<button>";',
      "// <input />",
      "export const A = () => <Input><Button>x</Button></Input>;",
    ].join("\n");
    expect(findNativeControls(src)).toEqual([]);
  });

  it("scans real files (guards against an empty walk)", () => {
    expect(listFiles(join(FRONTEND_ROOT, "src/features")).length).toBeGreaterThan(10);
    expect(listFiles(join(FRONTEND_ROOT, "src/app")).length).toBeGreaterThan(3);
  });

  it("finds only the allowlisted native controls, by file, tag and count", () => {
    const actual = new Map<string, number>();
    for (const [file, counts] of scanTree()) {
      for (const [tag, n] of counts) actual.set(`${file}::${tag}`, n);
    }
    const allowed = new Map(ALLOWLIST.map((a) => [`${a.file}::${a.tag}`, a.count]));
    expect(Object.fromEntries(actual)).toEqual(Object.fromEntries(allowed));
  });

  it("documents a reason for every allowlist entry", () => {
    for (const entry of ALLOWLIST) expect(entry.reason.length).toBeGreaterThan(20);
  });
});
