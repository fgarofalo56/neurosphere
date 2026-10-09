import { describe, expect, it } from "vitest";
import { FRONTEND_PACKAGE } from "./index";

describe("frontend toolchain smoke", () => {
  it("resolves the package entry", () => {
    expect(FRONTEND_PACKAGE).toBe("@neurosphere/frontend");
  });
});
