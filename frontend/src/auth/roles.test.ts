import { describe, expect, it } from "vitest";
import { NO_ROLES_LABEL, parseRoles, rolesLabel } from "./roles";

describe("parseRoles (display only)", () => {
  it("recognises the five NS-08 roles in canonical order", () => {
    expect(parseRoles(["Auditor", "Admin", "Steward", "Analyst", "Viewer"])).toEqual([
      "Viewer",
      "Analyst",
      "Steward",
      "Admin",
      "Auditor",
    ]);
  });

  it("maps claim value aliases", () => {
    expect(parseRoles(["Security.Auditor", "domain_steward", "PRO"])).toEqual([
      "Analyst",
      "Steward",
      "Auditor",
    ]);
  });

  it("ignores unknown and non-string values", () => {
    expect(parseRoles(["Root", 7, null, "GlobalAdmin"])).toEqual([]);
  });

  it("accepts a single string claim", () => {
    expect(parseRoles("Viewer")).toEqual(["Viewer"]);
  });

  it.each([undefined, null, [], {}, 5])("shows 'no roles' for %j", (claim) => {
    const roles = parseRoles(claim);
    expect(roles).toEqual([]);
    expect(rolesLabel(roles)).toBe(NO_ROLES_LABEL);
    expect(NO_ROLES_LABEL).toBe("no roles");
  });
});
