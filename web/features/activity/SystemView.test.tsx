import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { SystemView } from "./SystemView";

const READONLY_NOTE =
  "Read-only: re-derive scoring_weights.yaml from this evidence by hand (the fence forbids any automatic feedback into the engine).";
const system = {
  as_of: "", since: null, until: null,
  report: {
    n_closed: 12, period_start: null, period_end: null, blended_score_buckets: [], component_buckets: [],
    signal_correlations: [], notes: ["Closed (executed+settled) trades only.", READONLY_NOTE],
  },
  agreement: { n_closed: 12, n_agreed: 9, agreement_rate: 0.75, claude_win_rate: 0.7, baseline_win_rate: 0.55 },
};
const world = (over: Record<string, unknown> = {}) => ({
  "/pnl/system": system,
  "/pnl/sizing": { as_of: "", since: null, groups: [] },
  "/claude/context": { available: false },
  ...over,
});

describe("SystemView", () => {
  it("puts the sizing record above the score against outcome", async () => {
    renderWithQuery(<SystemView />, world());
    const sizing = await screen.findByRole("heading", { name: "Sizing record" });
    const score = await screen.findByRole("heading", { name: "Score against outcome" });
    expect(sizing.compareDocumentPosition(score) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("keeps the read-only sentence and offers no control but the two dates", async () => {
    const { container } = renderWithQuery(<SystemView />, world());
    expect(await screen.findByText(READONLY_NOTE)).toBeInTheDocument();
    const controls = container.querySelectorAll("button, input, select, textarea");
    expect(controls).toHaveLength(2);
    controls.forEach((c) => expect(c).toHaveAttribute("data-role", "window-control"));
  });

  it("sends Since to both requests and Until to the score only", async () => {
    renderWithQuery(<SystemView />, world());
    await screen.findByRole("heading", { name: "Score against outcome" });
    fireEvent.change(screen.getByLabelText("since"), { target: { value: "2026-10-01" } });
    fireEvent.change(screen.getByLabelText("until"), { target: { value: "2026-10-20" } });
    const calls = () => apiFetchMock.mock.calls.map((c) => String(c[0]));
    await waitFor(() => expect(calls()).toContain("/pnl/system?since=2026-10-01&until=2026-10-20"));
    expect(calls()).toContain("/pnl/sizing?since=2026-10-01");
    expect(calls().some((c) => c.startsWith("/pnl/sizing") && c.includes("until"))).toBe(false);
  });

  it("says the score report could not load and still shows the sizing record", async () => {
    renderWithQuery(<SystemView />, {
      "/pnl/sizing": { as_of: "", since: null, groups: [] },
      "/claude/context": { available: false },
    });
    expect(await screen.findByText("Could not load the score-vs-outcome report.")).toBeInTheDocument();
    expect(await screen.findByText("No sizing actions on record yet.")).toBeInTheDocument();
  });
});
