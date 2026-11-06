import { describe, expect, it, vi } from "vitest";

// The root layout loads fonts through next/font, which only exists inside the Next build.
vi.mock("next/font/google", () => ({
  Hanken_Grotesk: () => ({ variable: "--font-sans" }),
  Red_Hat_Mono: () => ({ variable: "--font-mono" }),
}));
vi.mock("@/components/shell/HaltedBanner", () => ({ HaltedBanner: () => null }));
vi.mock("@/components/shell/Rail", () => ({ Rail: () => null }));
vi.mock("@/components/shell/TabBar", () => ({ TabBar: () => null }));
vi.mock("@/app/providers", () => ({ Providers: () => null }));

import type { Metadata } from "next";
import { metadata as root } from "./layout";
import { metadata as activity } from "./activity/page";
import { metadata as explain } from "./explain/page";
import { metadata as ledgerImport } from "./ledger/import/page";
import { metadata as ledgerTrades } from "./ledger/trades/page";
import { metadata as news } from "./news/page";
import { metadata as portfolio } from "./portfolio/page";
import { metadata as trades } from "./trades/page";
import * as home from "./page";
import { metadata as more } from "./more/layout";
import { metadata as claude } from "./more/claude/layout";
import { metadata as research } from "./research/layout";
import { metadata as universe } from "./research/universe/layout";
import { generateMetadata as stock } from "./stock/[symbol]/layout";
import { generateMetadata as newsTicker } from "./news/[symbol]/layout";
import { generateMetadata as ledgerTicker } from "./ledger/ticker/[symbol]/layout";
import { generateMetadata as position } from "./positions/[underlying]/[slug]/layout";
import { generateMetadata as proposal } from "./trades/[approvalId]/layout";

describe("route titles (web overhaul Part 4, ruling 23)", () => {
  it("the root sets a default and a template", () => {
    expect(root.title).toEqual({ default: "IBKR Income", template: "%s · IBKR Income" });
  });

  it("Home sets none, so it keeps the default", () => {
    expect("metadata" in home).toBe(false);
  });

  it.each([
    ["Trades", trades],
    ["Portfolio", portfolio],
    ["Activity", activity],
    ["How it works", explain],
    ["News", news],
    ["Ledger trades", ledgerTrades],
    ["Import a statement", ledgerImport],
    ["More", more],
    ["What Claude knows", claude],
    ["Research", research],
    ["Universe", universe],
  ] as [string, Metadata][])("a static page is titled %s", (title, meta) => {
    expect(meta.title).toBe(title);
  });

  it("a stock page is titled by its upper-cased symbol", async () => {
    expect((await stock({ params: Promise.resolve({ symbol: "aapl" }) })).title).toBe("AAPL");
  });

  it("a ticker's news page is titled 'AAPL news'", async () => {
    expect((await newsTicker({ params: Promise.resolve({ symbol: "aapl" }) })).title).toBe("AAPL news");
  });

  it("a ticker's ledger page is titled 'AAPL ledger'", async () => {
    expect((await ledgerTicker({ params: Promise.resolve({ symbol: "aapl" }) })).title).toBe("AAPL ledger");
  });

  it("a position page is titled 'AAPL position'", async () => {
    const meta = await position({ params: Promise.resolve({ underlying: "AAPL", slug: "x" }) });
    expect(meta.title).toBe("AAPL position");
  });

  it("a position page upper-cases and decodes the underlying", async () => {
    const meta = await position({ params: Promise.resolve({ underlying: "brk%2Eb", slug: "x" }) });
    expect(meta.title).toBe("BRK.B position");
  });

  it("a proposal page is titled 'Proposal 42'", async () => {
    expect((await proposal({ params: Promise.resolve({ approvalId: "42" }) })).title).toBe("Proposal 42");
  });

  // A stray "%" in a hand-typed URL is a malformed escape: the title falls back to the raw segment
  // instead of throwing (web overhaul Part 6).
  it.each([
    ["stock", () => stock({ params: Promise.resolve({ symbol: "ab%zz" }) }), "AB%ZZ"],
    ["news ticker", () => newsTicker({ params: Promise.resolve({ symbol: "ab%zz" }) }), "AB%ZZ news"],
    ["ledger ticker", () => ledgerTicker({ params: Promise.resolve({ symbol: "ab%zz" }) }), "AB%ZZ ledger"],
    ["position", () => position({ params: Promise.resolve({ underlying: "ab%zz", slug: "x" }) }), "AB%ZZ position"],
    ["proposal", () => proposal({ params: Promise.resolve({ approvalId: "4%2" }) }), "Proposal 4%2"],
  ] as [string, () => Promise<Metadata>, string][])(
    "a %s title survives a malformed escape and keeps the raw segment",
    async (_name, meta, title) => {
      expect((await meta()).title).toBe(title);
    },
  );

  it("no title carries an em dash", async () => {
    const all = [activity, explain, ledgerImport, ledgerTrades, news, portfolio, trades, more, claude, research, universe];
    for (const m of all) expect(String(m.title)).not.toContain("—");
  });
});
