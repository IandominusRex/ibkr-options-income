import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { AutonomyControl } from "./AutonomyControl";

function withClient(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

const submitCommand = vi.fn();
const confirmCommand = vi.fn();
vi.mock("@/lib/commands", async () => {
  const actual = await vi.importActual("@/lib/commands");
  return {
    ...(actual as object),
    submitCommand: (...args: unknown[]) => submitCommand(...args),
    confirmCommand: (...args: unknown[]) => confirmCommand(...args),
  };
});

const RUNGS = [
  { level: "observe", label: "Observe" },
  { level: "manual", label: "Manual" },
  { level: "whitelist", label: "Whitelist" },
  { level: "full", label: "Full" },
];

afterEach(cleanup);
afterEach(() => {
  submitCommand.mockReset();
  confirmCommand.mockReset();
});

function appliedCommand(overrides: Record<string, unknown> = {}) {
  return {
    id: 5,
    kind: "set_autonomy",
    status: "applied",
    result: { level: "manual", previous: "observe" },
    needs_confirmation: false,
    confirm_token: null,
    created_at: "2026-09-07T10:00:00Z",
    applied_at: "2026-09-07T10:00:02Z",
    as_of: "2026-09-07T10:00:02Z",
    ...overrides,
  };
}

describe("AutonomyControl", () => {
  it("renders the four rungs from the API's rungs array, never hardcoded", () => {
    const rungs = RUNGS.slice(0, 2); // a subset proves the options come from the prop
    withClient(<AutonomyControl autonomy={RUNGS[0]} rungs={rungs} />);
    const select = screen.getByTestId("autonomy-select") as HTMLSelectElement;
    const rendered = Array.from(select.options).map((o) => o.value);
    expect(rendered).toEqual(["observe", "manual"]);
  });

  it("a rung change is click-through confirmed, showing the current and target rungs", async () => {
    submitCommand.mockResolvedValue(appliedCommand());
    withClient(<AutonomyControl autonomy={RUNGS[0]} rungs={RUNGS} />);

    fireEvent.change(screen.getByTestId("autonomy-select"), {
      target: { value: "manual" },
    });

    const dialog = screen.getByTestId("confirm-dialog");
    expect(dialog.textContent).toContain("Observe");
    expect(dialog.textContent).toContain("Manual");

    fireEvent.click(screen.getByRole("button", { name: "Set Manual" }));
    await waitFor(() =>
      expect(submitCommand).toHaveBeenCalledWith("set_autonomy", { level: "manual" }),
    );
  });

  it("selecting the current rung sends nothing", () => {
    withClient(<AutonomyControl autonomy={RUNGS[0]} rungs={RUNGS} />);
    fireEvent.change(screen.getByTestId("autonomy-select"), {
      target: { value: "observe" },
    });
    expect(screen.queryByTestId("confirm-dialog")).toBeNull();
    expect(submitCommand).not.toHaveBeenCalled();
  });

  it("cancelling the dialog sends nothing", () => {
    withClient(<AutonomyControl autonomy={RUNGS[0]} rungs={RUNGS} />);
    fireEvent.change(screen.getByTestId("autonomy-select"), {
      target: { value: "full" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(submitCommand).not.toHaveBeenCalled();
  });

  it("the control is disabled while its command is in flight and shows a receipt", async () => {
    submitCommand.mockResolvedValue(
      appliedCommand({ status: "pending", applied_at: null }),
    );
    withClient(<AutonomyControl autonomy={RUNGS[0]} rungs={RUNGS} />);
    fireEvent.change(screen.getByTestId("autonomy-select"), {
      target: { value: "manual" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Set Manual" }));

    await waitFor(() => expect(screen.getByTestId("command-receipt")).toBeTruthy());
    expect(
      (screen.getByTestId("autonomy-select") as HTMLSelectElement).disabled,
    ).toBe(true);
  });

  it("a refused promotion renders the blockers in words through the receipt", async () => {
    submitCommand.mockResolvedValue(
      appliedCommand({
        status: "failed",
        result: {
          reason: "promotion_refused",
          detail: {
            blockers: ["needs >=20 fills, has 3", "fill rate 40% is below the 60% gate"],
          },
        },
      }),
    );
    withClient(<AutonomyControl autonomy={RUNGS[0]} rungs={RUNGS} />);
    fireEvent.change(screen.getByTestId("autonomy-select"), {
      target: { value: "full" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Set Full" }));

    await waitFor(() =>
      expect(screen.getByTestId("command-receipt").getAttribute("data-state")).toBe(
        "failed",
      ),
    );
    // The humanised reason AND the actual blockers are both visible as text —
    // not just the top-level "refused" verdict with the reason silently dropped.
    const text = screen.getByTestId("command-receipt").textContent ?? "";
    expect(text).toContain("promotion refused");
    expect(text).toContain("needs >=20 fills, has 3");
    expect(text).toContain("fill rate 40% is below the 60% gate");
  });

  it("a 403 renders a permission message, not a generic failure", async () => {
    submitCommand.mockRejectedValue(new ApiError(403, "forbidden"));
    withClient(<AutonomyControl autonomy={RUNGS[0]} rungs={RUNGS} />);
    fireEvent.change(screen.getByTestId("autonomy-select"), {
      target: { value: "manual" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Set Manual" }));
    await waitFor(() =>
      expect(screen.getByTestId("command-error").textContent).toContain(
        "do not have permission",
      ),
    );
  });

  it("disables the select while the live confirmation dialog is open, before it is released", async () => {
    // Regression: `inFlight` used to ignore `liveStep`, leaving the select
    // clickable during the window between the first confirm and the live
    // release — there is no command id to poll yet in that window.
    submitCommand.mockResolvedValue(
      appliedCommand({ status: "pending", needs_confirmation: true, confirm_token: "tok" }),
    );
    withClient(<AutonomyControl autonomy={RUNGS[0]} rungs={RUNGS} />);
    fireEvent.change(screen.getByTestId("autonomy-select"), {
      target: { value: "manual" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Set Manual" }));
    await waitFor(() => expect(screen.getByTestId("confirm-dialog").textContent).toContain("LIVE"));
    expect(
      (screen.getByTestId("autonomy-select") as HTMLSelectElement).disabled,
    ).toBe(true);
  });
});

describe("AutonomyControl — reload persistence (localStorage)", () => {
  it("restores an in-flight receipt from localStorage on a fresh mount", async () => {
    const { savePersistedCommand } = await import("@/lib/commands");
    savePersistedCommand("autonomy", appliedCommand({ status: "pending" }));
    withClient(<AutonomyControl autonomy={RUNGS[0]} rungs={RUNGS} />);
    expect(await screen.findByTestId("command-receipt")).toBeDefined();
    expect(
      (screen.getByTestId("autonomy-select") as HTMLSelectElement).disabled,
    ).toBe(true);
  });

  it("restores the live second-confirmation dialog from localStorage on a fresh mount", async () => {
    const { savePersistedCommand } = await import("@/lib/commands");
    savePersistedCommand(
      "autonomy",
      appliedCommand({ status: "pending", needs_confirmation: true, confirm_token: "tok" }),
    );
    withClient(<AutonomyControl autonomy={RUNGS[0]} rungs={RUNGS} />);
    const dialog = await screen.findByTestId("confirm-dialog");
    expect(dialog.textContent).toContain("LIVE");
  });
});