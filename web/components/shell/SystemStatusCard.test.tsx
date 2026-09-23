import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderWithQuery } from "@/lib/test-query";
import { SystemStatusCard } from "./SystemStatusCard";

const ISO = new Date().toISOString();

function statusResponse(rows: Array<Record<string, unknown>>) {
  return { as_of: ISO, rows };
}

describe("SystemStatusCard", () => {
  it("renders one row per system with its label", async () => {
    renderWithQuery(<SystemStatusCard />, {
      "/system/status": statusResponse([
        {
          key: "trading_db",
          label: "Trading DB",
          state: "ok",
          detail: "reachable",
          log_key: null,
        },
        {
          key: "command_drain",
          label: "Command drain (approval_service)",
          state: "unknown",
          detail: "not yet reporting",
          log_key: "approval",
        },
      ]),
    });
    expect(await screen.findByText("Trading DB")).toBeDefined();
    expect(screen.getByText("Command drain (approval_service)")).toBeDefined();
  });

  it("renders an ok row's dot with the ok state", async () => {
    renderWithQuery(<SystemStatusCard />, {
      "/system/status": statusResponse([
        { key: "trading_db", label: "Trading DB", state: "ok", detail: "reachable", log_key: null },
      ]),
    });
    const dot = await screen.findByTestId("status-dot");
    expect(dot.getAttribute("data-state")).toBe("ok");
  });

  it("renders a down row's dot distinctly from ok", async () => {
    renderWithQuery(<SystemStatusCard />, {
      "/system/status": statusResponse([
        {
          key: "research_db",
          label: "Research DB",
          state: "down",
          detail: "unreachable",
          log_key: null,
        },
      ]),
    });
    const dot = await screen.findByTestId("status-dot");
    expect(dot.getAttribute("data-state")).toBe("down");
  });

  it("disables a row with no log_key", async () => {
    renderWithQuery(<SystemStatusCard />, {
      "/system/status": statusResponse([
        { key: "trading_db", label: "Trading DB", state: "ok", detail: "reachable", log_key: null },
      ]),
    });
    const button = await screen.findByRole("button", { name: /trading db/i });
    expect(button.hasAttribute("disabled")).toBe(true);
  });

  it("renders a degraded fallback line when the fetch fails", async () => {
    renderWithQuery(<SystemStatusCard />, {});
    expect(await screen.findByText("Status unavailable")).toBeDefined();
  });
});
