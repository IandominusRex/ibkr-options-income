import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { ImportView } from "./ImportView";

vi.mock("next/navigation", () => ({ usePathname: () => "/ledger/import" }));

const ISO = new Date().toISOString();
const IMPORTS = {
  as_of: ISO,
  runs: [{ id: 1, source: "csv", filename: "stmt.csv", started_at: ISO, finished_at: ISO, status: "ok", reason: null, counts: { new: 15, duplicate: 0 }, errors: [] }],
  flex: { configured: false, last_run: null, last_status: null, last_error: null },
  sheets: { configured: true, last_run: ISO, last_status: null, last_error: null },
  corporate_actions: [{ id: 4, event_date: "2025-11-18", underlying: "OPEN", description: "Spinoff OPENW", quantity: 30, proceeds: 0, reviewed: false }],
};
const PENDING = { id: 9, kind: "ledger_import", status: "pending", result: null, needs_confirmation: false, confirm_token: null, created_at: ISO, applied_at: null, as_of: ISO, created: true };

function file(name: string, text: string) {
  return new File([text], name, { type: name.endsWith(".pdf") ? "application/pdf" : "text/csv" });
}

describe("ImportView", () => {
  it("lists import runs, feed status and corporate actions", async () => {
    renderWithQuery(<ImportView />, { "/ledger/imports": IMPORTS });
    expect(await screen.findByText("stmt.csv")).toBeInTheDocument();
    expect(screen.getByText(/Flex pull: not set up/)).toBeInTheDocument();
    expect(screen.getByText("Spinoff OPENW")).toBeInTheDocument();
  });

  it("rejects a PDF in the browser with a pointer to the CSV", async () => {
    renderWithQuery(<ImportView />, { "/ledger/imports": IMPORTS });
    fireEvent.change(await screen.findByLabelText("Activity Statement CSV"), { target: { files: [file("s.pdf", "%PDF")] } });
    expect(await screen.findByText(/PDF statements are not supported/)).toBeInTheDocument();
    expect(apiFetchMock.mock.calls.some((c) => c[0] === "/commands")).toBe(false);
  });

  it("uploads a CSV as a ledger_import command", async () => {
    renderWithQuery(<ImportView />, { "/commands/9": { ...PENDING, status: "applied", result: { counts: { new: 3 } } }, "/ledger/imports": IMPORTS, "/commands": PENDING });
    fireEvent.change(await screen.findByLabelText("Activity Statement CSV"), { target: { files: [file("s.csv", "Statement,Header\n")] } });
    await waitFor(() => {
      const post = apiFetchMock.mock.calls.find((c) => c[0] === "/commands");
      expect(post).toBeTruthy();
      expect(JSON.parse((post![1] as RequestInit).body as string)).toMatchObject({ kind: "ledger_import", payload: { filename: "s.csv" } });
    });
    expect(await screen.findByText(/Imported: 3 new/)).toBeInTheDocument();
  });

  it("rejects an over-size file in the browser without posting", async () => {
    renderWithQuery(<ImportView />, { "/ledger/imports": IMPORTS });
    const before = apiFetchMock.mock.calls.filter((c) => c[0] === "/commands").length;
    const big = file("big.csv", "a");
    Object.defineProperty(big, "size", { value: 6 * 1024 * 1024 });
    fireEvent.change(await screen.findByLabelText("Activity Statement CSV"), { target: { files: [big] } });
    expect(await screen.findByText(/over 5 MB/)).toBeInTheDocument();
    expect(apiFetchMock.mock.calls.filter((c) => c[0] === "/commands").length).toBe(before);
  });

  it("shows the error message of a failed import command", async () => {
    renderWithQuery(<ImportView />, { "/commands/9": { ...PENDING, status: "failed", result: { reason: "not_an_activity_statement" } }, "/ledger/imports": IMPORTS, "/commands": PENDING });
    fireEvent.change(await screen.findByLabelText("Activity Statement CSV"), { target: { files: [file("s.csv", "x")] } });
    expect(await screen.findByText(/Import failed: not_an_activity_statement/)).toBeInTheDocument();
  });

  it("shows n/a, not zero, when counts are missing", async () => {
    renderWithQuery(<ImportView />, { "/commands/9": { ...PENDING, status: "applied", result: {} }, "/ledger/imports": IMPORTS, "/commands": PENDING });
    fireEvent.change(await screen.findByLabelText("Activity Statement CSV"), { target: { files: [file("s.csv", "x")] } });
    expect(await screen.findByText(/Imported: n\/a new/)).toBeInTheDocument();
  });

  it("marks a corporate action reviewed: disabled while pending, list refreshed after applied", async () => {
    let cmdStatus = "pending";
    let reviewed = false;
    renderWithQuery(<ImportView />, { "/ledger/imports": IMPORTS });
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === "/ledger/imports") return { ...IMPORTS, corporate_actions: [{ ...IMPORTS.corporate_actions[0], reviewed }] };
      if (path === "/commands") return { ...PENDING, kind: "ledger_ca_reviewed" };
      if (path === "/commands/9") return { ...PENDING, status: cmdStatus, result: null };
      return {};
    });
    fireEvent.click(await screen.findByRole("button", { name: "Mark reviewed" }));
    await waitFor(() => {
      const post = apiFetchMock.mock.calls.filter((c) => c[0] === "/commands").at(-1);
      expect(JSON.parse((post![1] as RequestInit).body as string)).toEqual({ kind: "ledger_ca_reviewed", payload: { corporate_action_id: 4 } });
    });
    expect(await screen.findByRole("button", { name: "Marking" })).toBeDisabled();
    cmdStatus = "applied";
    reviewed = true;
    await waitFor(() => expect(screen.queryByRole("button", { name: /Mark/ })).toBeNull(), { timeout: 4000 });
    expect(screen.getByText("reviewed")).toBeInTheDocument();
  });
});
