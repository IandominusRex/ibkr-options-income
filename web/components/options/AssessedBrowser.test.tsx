import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { AssessedBrowser } from "./AssessedBrowser";

function withClient(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}));

describe("AssessedBrowser", () => {
  it("renders one line of text for an empty run", async () => {
    const { apiFetch } = await import("@/lib/api");
    (apiFetch as any).mockResolvedValue({
      as_of: "x",
      run_id: "r1",
      computed_at: null,
      groups: [],
    });
    withClient(<AssessedBrowser />);
    expect(await screen.findByText(/No assessed contracts/i)).toBeDefined();
  });

  it("groups by symbol with per-stage counts in the header", async () => {
    const { apiFetch } = await import("@/lib/api");
    (apiFetch as any).mockResolvedValue({
      as_of: "x",
      run_id: "r1",
      computed_at: "x",
      groups: [
        {
          as_of: "x",
          symbol: "NVDA",
          contracts: [
            {
              as_of: "x",
              candidate_id: "a",
              symbol: "NVDA",
              strategy: "cash_secured_put",
              strike: 190.0,
              expiry: null,
              stage: "passed",
              reasons: [],
              reasons_text: [],
              blended_score: 72.0,
              premium: 3.25,
              ideal: null,
              promotable: false,
              promote_note: "Already surfaced for approval.",
            },
            {
              as_of: "x",
              candidate_id: "b",
              symbol: "NVDA",
              strategy: "cash_secured_put",
              strike: 185.0,
              expiry: null,
              stage: "risk_gate",
              reasons: ["delta_out_of_range"],
              reasons_text: ["delta outside target band"],
              blended_score: 50.0,
              premium: 2.5,
              ideal: null,
              promotable: false,
              promote_note: "The Rules Engine rejected this contract.",
            },
          ],
          counts: { passed: 1, risk_gate: 1 },
        },
      ],
    });
    withClient(<AssessedBrowser />);
    expect(await screen.findByText("NVDA")).toBeDefined();
    expect(screen.getByText(/passed: 1/i)).toBeDefined();
  });

  it("renders a non-promotable row's promote_note as plain text and no promote control", async () => {
    const { apiFetch } = await import("@/lib/api");
    (apiFetch as any).mockResolvedValue({
      as_of: "x",
      run_id: "r1",
      computed_at: null,
      groups: [
        {
          as_of: "x",
          symbol: "NVDA",
          contracts: [
            {
              as_of: "x",
              candidate_id: "b",
              symbol: "NVDA",
              strategy: "cash_secured_put",
              strike: 185.0,
              expiry: null,
              stage: "risk_gate",
              reasons: [],
              reasons_text: [],
              blended_score: 50.0,
              premium: null,
              ideal: null,
              promotable: false,
              promote_note: "The Rules Engine rejected this contract.",
            },
          ],
          counts: { risk_gate: 1 },
        },
      ],
    });
    withClient(<AssessedBrowser />);
    expect(await screen.findByText(/Rules Engine rejected/i)).toBeDefined();
    // No promote control, disabled or otherwise.
    const promote = screen.queryAllByRole("button", { name: /promote/i });
    expect(promote).toHaveLength(0);
  });

  it("stage is never communicated by colour alone - a text label is present", async () => {
    const { apiFetch } = await import("@/lib/api");
    (apiFetch as any).mockResolvedValue({
      as_of: "x",
      run_id: "r1",
      computed_at: null,
      groups: [
        {
          as_of: "x",
          symbol: "NVDA",
          contracts: [
            {
              as_of: "x",
              candidate_id: "a",
              symbol: "NVDA",
              strategy: "cash_secured_put",
              strike: 190.0,
              expiry: null,
              stage: "generator",
              reasons: [],
              reasons_text: [],
              blended_score: 0,
              premium: null,
              ideal: null,
              promotable: false,
              promote_note: null,
            },
          ],
          counts: { generator: 1 },
        },
      ],
    });
    withClient(<AssessedBrowser />);
    // The StageBadge renders a text label for every stage.
    expect(await screen.findByText("Filtered")).toBeDefined();
  });
});