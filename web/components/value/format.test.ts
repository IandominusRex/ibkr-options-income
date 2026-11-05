import { describe, expect, it } from "vitest";
import {
  approveSentence,
  ceilingSum,
  expiresWords,
  failureSentence,
  nextExitWords,
  reasonWords,
  rejectSentence,
} from "./format";
import type { ValueProposalLike } from "./types";

const buy: ValueProposalLike = {
  id: 5, kind: "buy", symbol: "AAPL", shares: 20, price: 182.4, cause: "python", status: "pending", fingerprint: "abc123def0",
};

describe("value format", () => {
  it("writes the ceiling as a sum and an unknown side as n/a, never $0", () => {
    expect(ceilingSum(7200, 30000)).toBe("$7,200 of $30,000");
    expect(ceilingSum(7200, null)).toBe("$7,200 of n/a");
    expect(ceilingSum(null, null)).toBe("n/a of n/a");
  });
  it("says the next exit in words", () => {
    expect(nextExitWords({ kind: "sell_half", level: 180 })).toBe("sell half at $180.00");
    expect(nextExitWords({ kind: "stop", level: 140.5 })).toBe("stop at $140.50");
    expect(nextExitWords(null)).toBeNull();
  });
  it("names what approving a buy may cause, including the wheel's puts it may close", () => {
    expect(approveSentence(buy, 2)).toContain(
      "Approving lets the system buy 20 shares of AAPL at its next check, sized at the close of $182.40, at the mid of a fresh quote. " +
        "If cash is short it may close up to 2 of your wheel's cash-secured puts at breakeven or better to fund it.",
    );
  });
  it("does not invent a price for a buy that has none, and says nothing of puts for a sale", () => {
    const noPrice = approveSentence({ ...buy, price: null }, 2);
    expect(noPrice).toContain("buy 20 shares of AAPL at its next check, at the mid of a fresh quote.");
    expect(noPrice).not.toContain("sized at");
    expect(noPrice).not.toContain("up to $");
    const sell = approveSentence({ ...buy, kind: "sell", shares: 10, price: null }, 2);
    expect(sell).toContain("sell 10 shares of AAPL at its next check");
    expect(sell).not.toContain("cash-secured");
  });
  it("says it outright when only Claude's number makes the sale", () => {
    const s = approveSentence({ ...buy, kind: "sell", cause: "claude", price: null }, 2);
    expect(s.startsWith("Only Claude's number makes this sale.")).toBe(true);
  });
  it("words a rejection and the reason codes", () => {
    expect(rejectSentence(buy)).toContain("will not buy 20 shares of AAPL");
    expect(reasonWords("tranche 2")).toBe("scaling in, tranche 2");
    expect(reasonWords("claude_no")).toContain("Claude");
    expect(reasonWords("something_new")).toBe("something new");
    expect(failureSentence("stale_proposal")).toBe("This card is out of date; refresh it.");
    expect(failureSentence("nobody_knows")).toBeNull();
  });
  it("counts down to an expiry in words", () => {
    const now = Date.parse("2026-11-05T12:00:00Z");
    expect(expiresWords("2026-11-05T17:00:00Z", now)).toBe("expires in 5h");
    expect(expiresWords("2026-11-05T12:40:00Z", now)).toBe("expires in 40m");
    expect(expiresWords("2026-11-05T11:00:00Z", now)).toBe("expired");
  });
});
