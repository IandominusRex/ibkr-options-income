import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderWithQuery } from "@/lib/test-query";
import { THEME_STORAGE_KEY } from "@/lib/theme";
import MorePage from "./page";

const status = { as_of: new Date().toISOString(), rows: [] };

const controls = {
  as_of: new Date().toISOString(),
  autonomy: { level: "approve", label: "Approve each trade" },
  rungs: [{ level: "approve", label: "Approve each trade" }],
  halted: false,
  halt_reason: null,
  halted_at: null,
  mode: "paper",
  drain_healthy: true,
  drain_last_seen: null,
  pending_commands: 0,
};

const target = { as_of: new Date().toISOString(), source: "none", target: { mode: "off", amount: null, pct: null, base: null } };
const month = { as_of: new Date().toISOString(), book: "paper", spreads_available: true, pay: { month: "2026-10-01", month_start_value: null } };
const served = { "/system/status": status, "/options/controls": controls, "/pnl/target": target, "/pnl/month": month };

describe("More page", () => {
  it("offers light, dark and follow-OS themes and persists the choice", () => {
    renderWithQuery(<MorePage />, served);
    const group = screen.getByRole("group", { name: "Theme" });
    expect(group).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Follow OS" }));
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("system");
  });
  it("links to the pages that have no tab on a phone", () => {
    renderWithQuery(<MorePage />, served);
    expect(screen.getByRole("link", { name: /How it works/ })).toHaveAttribute("href", "/explain");
    expect(screen.getByRole("link", { name: /Research/ })).toHaveAttribute("href", "/research");
    expect(screen.getByRole("link", { name: /News/ })).toHaveAttribute("href", "/news");
    expect(screen.getByRole("link", { name: /Import a statement/ })).toHaveAttribute("href", "/ledger/import");
  });
  it("links to What Claude knows, the page that shows the market picture and what each call reads", () => {
    renderWithQuery(<MorePage />, served);
    expect(screen.getByRole("link", { name: /What Claude knows/ })).toHaveAttribute("href", "/more/claude");
  });
  it("links to Universe, and to the Ledger view on Activity", () => {
    renderWithQuery(<MorePage />, served);
    expect(screen.getByRole("link", { name: /^Universe/ })).toHaveAttribute("href", "/research/universe");
    expect(screen.getByRole("link", { name: /^Ledger/ })).toHaveAttribute("href", "/activity?view=ledger");
  });
  it("is where the monthly income target is set", async () => {
    renderWithQuery(<MorePage />, served);
    expect(await screen.findByRole("heading", { name: "Monthly income target" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Target type" })).toBeInTheDocument();
  });
  it("carries the chart library's licence link, which is no longer on the chart", () => {
    renderWithQuery(<MorePage />, served);
    const link = screen.getByRole("link", { name: /TradingView/ });
    expect(link).toHaveAttribute("href", "https://www.tradingview.com/");
    expect(screen.getByRole("heading", { name: "Credits" })).toBeInTheDocument();
  });
  it("reaches the bot controls on a phone, where the rail is hidden", async () => {
    renderWithQuery(<MorePage />, served);
    expect(await screen.findByRole("button", { name: /Bot running/ })).toBeInTheDocument();
  });
});
