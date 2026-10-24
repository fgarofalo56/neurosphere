/// <reference types="vite/client" />
import { describe, expect, it } from "vitest";
import { defaultPack } from "./index";
import type { ThemePack } from "./index";

// Theme is presentation, never permission enforcement (NS-10).
const FORBIDDEN_SPECIFIER =
  /(^|\/)(api|auth|roles|useRoles|permissions?|authz|rbac|routes?)(\/|$|\.)|useRoles/i;

function specifiers(source: string): string[] {
  const out: string[] = [];
  const re = /(?:from\s+|import\s*\(\s*|import\s+|require\s*\(\s*)["']([^"']+)["']/g;
  for (const m of source.matchAll(re)) out.push(m[1] ?? "");
  return out;
}

describe("themes/ import boundary", () => {
  const sources = import.meta.glob(["./**/*.ts", "./**/*.tsx", "!./**/*.test.*"], {
    query: "?raw",
    import: "default",
    eager: true,
  }) as Record<string, string>;

  it("scans real source files", () => {
    expect(Object.keys(sources).length).toBeGreaterThan(3);
  });

  it("imports nothing from api, auth, roles or permission helpers", () => {
    const offenders: string[] = [];
    for (const [path, src] of Object.entries(sources)) {
      for (const spec of specifiers(src)) {
        if (FORBIDDEN_SPECIFIER.test(spec)) offenders.push(`${path}: ${spec}`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it("the import scanner catches forbidden specifiers", () => {
    const bad = [
      'import x from "../../api/client";',
      'import { y } from "../../auth";',
      'import { useRoles } from "../app/useRoles";',
      'const z = await import("../../api");',
    ];
    for (const line of bad) {
      expect(specifiers(line).some((s) => FORBIDDEN_SPECIFIER.test(s))).toBe(true);
    }
    expect(specifiers('import a from "../tokens";').some((s) => FORBIDDEN_SPECIFIER.test(s))).toBe(
      false,
    );
  });
});

describe("ThemePack shape", () => {
  // Compile-time exhaustive: adding a field to ThemePack fails typecheck here until reviewed.
  const FIELDS: Record<keyof ThemePack, true> = {
    id: true,
    displayName: true,
    brandRamp: true,
    overrides: true,
    logos: true,
  };

  it("has no permission, role or route related field", () => {
    const names = [...Object.keys(FIELDS), ...Object.keys(defaultPack)];
    expect(names.filter((n) => /perm|role|route|scope|authz|auth|access|api/i.test(n))).toEqual([]);
  });
});
