import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { NewsTickerPage } from "./NewsTickerPage";

const ISO = new Date().toISOString();
const empty = { as_of: ISO, available: true, symbol: "TSM", latest_brief: null, clusters: [], next_earnings: null, request: null };

describe("NewsTickerPage", () => {
  it("is titled by the ticker, with a back link to News and a link to the stock page", () => {
    renderWithQuery(<NewsTickerPage symbol="tsm" />, { "/news/ticker/TSM": empty, "/options/controls": { drain_healthy: true } });
    expect(screen.getByRole("heading", { level: 1, name: "TSM" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "News" })).toHaveAttribute("href", "/news");
    expect(screen.getByRole("link", { name: "Stock page" })).toHaveAttribute("href", "/stock/TSM");
    expect(screen.getByRole("button", { name: "Refresh TSM news" })).toBeInTheDocument();
  });

  it("asks for a fresh brief with the secondary button, which submits a news_brief command for the symbol", async () => {
    renderWithQuery(<NewsTickerPage symbol="tsm" />, {
      "/news/ticker/TSM": empty,
      "/commands": {
        id: 7, kind: "news_brief", status: "pending", result: null, needs_confirmation: false, confirm_token: null,
        created_at: ISO, applied_at: null, as_of: ISO, created: true,
      },
      "/options/controls": { drain_healthy: true },
    });
    expect(await screen.findByText(/no brief yet/i)).toBeInTheDocument();
    const button = screen.getByRole("button", { name: /request fresh brief/i });
    expect(button).toHaveAttribute("data-variant", "secondary");
    fireEvent.click(button);
    await vi.waitFor(() =>
      expect(
        apiFetchMock.mock.calls.some(
          (c) => c[0] === "/commands" && JSON.parse(String((c[1] as RequestInit).body)).kind === "news_brief"
            && JSON.parse(String((c[1] as RequestInit).body)).payload.symbol === "TSM",
        ),
      ).toBe(true),
    );
    await vi.waitFor(() => expect(screen.getByRole("button", { name: /request fresh brief/i })).toBeDisabled());
  });

  it("says a refused request in words, never in red", async () => {
    renderWithQuery(<NewsTickerPage symbol="TSM" />, { "/news/ticker/TSM": empty, "/options/controls": { drain_healthy: true } });
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === "/commands") throw new Error("boom");
      if (path.startsWith("/news/ticker")) return empty;
      return { drain_healthy: true };
    });
    fireEvent.click(screen.getByRole("button", { name: /request fresh brief/i }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The request could not be created.");
    expect(alert.className).not.toMatch(/text-loss/);
  });
});
