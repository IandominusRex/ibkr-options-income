import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderWithQuery } from "@/lib/test-query";
import { SystemLogPanel } from "./SystemLogPanel";
import type { SystemRow } from "./SystemStatusCard";

const ISO = new Date().toISOString();

const row: SystemRow = {
  key: "command_drain",
  label: "Command drain (approval_service)",
  state: "ok",
  detail: "last heartbeat 4s ago",
  log_key: "approval",
};

function logResponse(lines: string[], level: "warn" | "info" = "warn", fileExists = true) {
  return { as_of: ISO, name: "approval", level, lines, file_exists: fileExists };
}

describe("SystemLogPanel", () => {
  it("fetches and renders the tailed log lines on open", async () => {
    renderWithQuery(<SystemLogPanel row={row} onClose={() => {}} />, {
      "/system/approval/log?level=warn": logResponse(["2026-09-23 | WARNING | x | boom"]),
    });
    expect(await screen.findByText(/boom/)).toBeDefined();
  });

  it("shows 'No log file yet' when the log file does not exist", async () => {
    renderWithQuery(<SystemLogPanel row={row} onClose={() => {}} />, {
      "/system/approval/log?level=warn": logResponse([], "warn", false),
    });
    expect(await screen.findByText("No log file yet")).toBeDefined();
  });

  it("shows 'No matching lines at this level' when the file exists but has no matches", async () => {
    renderWithQuery(<SystemLogPanel row={row} onClose={() => {}} />, {
      "/system/approval/log?level=warn": logResponse([], "warn", true),
    });
    expect(await screen.findByText("No matching lines at this level")).toBeDefined();
  });

  it("shows an error message when the log fetch fails", async () => {
    renderWithQuery(<SystemLogPanel row={row} onClose={() => {}} />, {});
    expect(await screen.findByText("Could not load the log")).toBeDefined();
  });

  it("switching to Info+ refetches at the info level", async () => {
    renderWithQuery(<SystemLogPanel row={row} onClose={() => {}} />, {
      "/system/approval/log?level=warn": logResponse(["only a warning line"]),
      "/system/approval/log?level=info": logResponse(["an info line", "a warning line"]),
    });
    await screen.findByText("only a warning line");
    fireEvent.click(screen.getByRole("button", { name: /info\+/i }));
    expect(await screen.findByText(/an info line/)).toBeDefined();
  });

  it("Escape calls onClose", async () => {
    let closed = false;
    renderWithQuery(<SystemLogPanel row={row} onClose={() => (closed = true)} />, {
      "/system/approval/log?level=warn": logResponse([]),
    });
    await screen.findByText("No matching lines at this level");
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(closed).toBe(true));
  });

  it("the Close button calls onClose", async () => {
    let closed = false;
    renderWithQuery(<SystemLogPanel row={row} onClose={() => (closed = true)} />, {
      "/system/approval/log?level=warn": logResponse([]),
    });
    await screen.findByText("No matching lines at this level");
    fireEvent.click(screen.getByRole("button", { name: /close/i }));
    expect(closed).toBe(true);
  });
});
