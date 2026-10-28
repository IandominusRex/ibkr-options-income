import { describe, expect, it } from "vitest";
import { consequenceSentence, daysLeft, entryTitle, expiryLabel } from "./calendar";

describe("calendar words", () => {
  it("says how long is left", () => {
    expect(daysLeft(0)).toBe("today");
    expect(daysLeft(1)).toBe("1 day left");
    expect(daysLeft(28)).toBe("28 days left");
  });
  it("writes each consequence as a sentence, and keeps unknown a named state", () => {
    expect(consequenceSentence("assigned")).toBe("Assigned: shares change hands");
    expect(consequenceSentence("called_away")).toBe("Called away: shares are sold");
    expect(consequenceSentence("expires_worthless")).toBe("Expires worthless");
    expect(consequenceSentence("unknown")).toBe("Consequence unknown");
  });
  it("titles a contract by its ticker, strike and side", () => {
    expect(entryTitle({ underlying: "AAPL", strike: 180, right: "P" } as never)).toBe("AAPL $180 put");
    expect(entryTitle({ underlying: "KO", strike: 72.5, right: "C" } as never)).toBe("KO $72.5 call");
  });
  it("reads an expiry as written, in the weekday form", () => {
    expect(expiryLabel("2026-11-20")).toBe("Fri, Nov 20");
  });
});
