import { describe, expect, it } from "vitest";
import config from "./next.config";

describe("redirects", () => {
  it("keeps every old URL working", async () => {
    const redirects = await config.redirects!();
    const map = Object.fromEntries(redirects.map((r) => [r.source, r]));
    expect(map["/options"].destination).toBe("/trades");
    expect(map["/options/:approvalId"].destination).toBe("/trades/:approvalId");
    expect(map["/pnl"].destination).toBe("/activity");
    expect(map["/ledger"].destination).toBe("/activity?view=ledger");
    expect(map["/universe"].destination).toBe("/research/universe");
  });
  it("uses temporary redirects while the overhaul is in flight", async () => {
    const redirects = await config.redirects!();
    expect(redirects.every((r) => r.permanent === false)).toBe(true);
  });
});
