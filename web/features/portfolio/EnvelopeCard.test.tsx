import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { EnvelopeCard } from "./EnvelopeCard";

const now = () => new Date().toISOString();

const snapshot = (over: Record<string, unknown> = {}) => ({
  captured_at: now(),
  source: "stored",
  measured: true,
  enforce: "record",
  s10: 18.4,
  s10_net: 15.2,
  s10_vol10: 21.9,
  s10_vol10_net: 18.7,
  s20: 33.1,
  s20_net: 29.5,
  g10: 24.6,
  g10_net: 21.0,
  p20: 31.2,
  p20_net: 27.8,
  t20: 23.7,
  t20_net: 20.4,
  s_smh: 19.9,
  s_smh_net: 17.3,
  uew: 1.36,
  nlv: 125_000,
  unmeasured: [],
  reasons: [],
  ...over,
});

const DEFAULTS: Record<string, string> = {
  envelope_enforce: "record",
  spreads_paper: "off",
  spxw_ready: "off",
  hedge_instrument: "none",
  bridge: "off",
  tech_cap: "off",
  stacking_rule: "off",
  index_1x: "off",
  leveraged_sleeve: "off",
  leveraged_cc_auto: "off",
  t20_limit: "off",
  slow_breaker: "off",
  cc_basis_floor: "1.00",
  hedge_monetisation: "none",
  leveraged_entry: "record",
};

const switches = (over: Record<string, string> = {}) =>
  Object.entries({ ...DEFAULTS, ...over }).map(([name, value]) => ({
    name,
    value,
    default: DEFAULTS[name],
    source: value === DEFAULTS[name] ? "default" : "cli",
    set_at: null,
  }));

const reading = (over: Record<string, unknown> = {}) => {
  const snap = snapshot();
  return {
    as_of: now(),
    snapshot: snap,
    live: null,
    stored: snap,
    limits: { s10: 22.0, uew: 1.36, t20: null, s10_target: 15.0, uew_target: 1.25 },
    enforce: "record",
    glide: {
      start: "2026-11-17",
      end: "2027-02-16",
      week: 3,
      weeks: 13,
      s10_start: 22.0,
      uew_start: 1.36,
      s10_today: 20.5,
      uew_today: 1.33,
    },
    switches: switches(),
    cash_after_itm_assignment: 41_250,
    les: [],
    ...over,
  };
};

const empty = () =>
  reading({
    snapshot: null,
    stored: null,
    limits: { s10: null, uew: null, t20: null, s10_target: 15.0, uew_target: 1.25 },
    glide: null,
    cash_after_itm_assignment: null,
  });

const serve = (body: unknown) => renderWithQuery(<EnvelopeCard />, { "/envelope": body });

describe("EnvelopeCard", () => {
  it("puts S10 gross beside its limit and its target, and net beside gross", async () => {
    serve(reading());
    const block = await screen.findByRole("group", { name: "S10 gross" });
    expect(within(block).getByText("18.4%")).toBeInTheDocument();
    expect(within(block).getByText("Limit today")).toBeInTheDocument();
    expect(within(block).getByText("22.0%")).toBeInTheDocument();
    expect(within(block).getByText("Target")).toBeInTheDocument();
    expect(within(block).getByText("15.0%")).toBeInTheDocument();
    expect(within(block).getByText("Net of long options")).toBeInTheDocument();
    expect(within(block).getByText("15.2%")).toBeInTheDocument();
    expect(within(block).queryByText("Over limit")).toBeNull();
  });

  it("puts U_ew beside its limit and its target", async () => {
    serve(reading());
    const block = await screen.findByRole("group", { name: "U_ew" });
    expect(within(block).getByText("Limit today")).toBeInTheDocument();
    expect(within(block).getAllByText("1.36x")).toHaveLength(2); // the reading and its limit
    expect(within(block).getByText("1.25x")).toBeInTheDocument();
  });

  it("says Over limit in words when a measure is past its limit", async () => {
    serve(reading({ limits: { s10: 16.0, uew: 1.2, t20: null, s10_target: 15.0, uew_target: 1.25 } }));
    const s10 = await screen.findByRole("group", { name: "S10 gross" });
    expect(within(s10).getByText("Over limit")).toBeInTheDocument();
    const uew = screen.getByRole("group", { name: "U_ew" });
    expect(within(uew).getByText("Over limit")).toBeInTheDocument();
  });

  it("lists the other measures compactly with net beside gross", async () => {
    serve(reading());
    const list = await screen.findByRole("group", { name: "Other scenarios, gross and net of long options" });
    const row = (label: string) => within(list).getByText(label).closest("div") as HTMLElement;
    expect(row("S10 at +10 vol points")).toHaveTextContent("21.9% / 18.7%");
    expect(row("S20, SPY down 20%")).toHaveTextContent("33.1% / 29.5%");
    expect(row("G10, one-day index gap of 10%")).toHaveTextContent("24.6% / 21.0%");
    expect(row("P20, index down 20% over 10 sessions")).toHaveTextContent("31.2% / 27.8%");
    expect(row("T20, tech names down 20%")).toHaveTextContent("23.7% / 20.4%");
    expect(row("S-SMH, SMH down 30%")).toHaveTextContent("19.9% / 17.3%");
    expect(list).toHaveClass("tabular", "font-mono");
  });

  it("shows cash after every ITM put is assigned, and the T20 limit only when one is set", async () => {
    serve(reading({ limits: { s10: 22.0, uew: 1.36, t20: 25.0, s10_target: 15.0, uew_target: 1.25 } }));
    expect(await screen.findByText("Cash after every ITM put is assigned")).toBeInTheDocument();
    expect(screen.getByText("$41,250")).toBeInTheDocument();
    expect(screen.getByText("T20 limit")).toBeInTheDocument();
    expect(screen.getByText("25.0%")).toBeInTheDocument();
  });

  it("says which week of the glide it is, and when the glide ends", async () => {
    serve(reading());
    expect(await screen.findByText("Glide week 3 of 13")).toBeInTheDocument();
    expect(screen.getByText(/ends Feb 16, 2027/)).toBeInTheDocument();
  });

  it("says Not enforced yet while the switch is record, and Enforced when it is on", async () => {
    const first = serve(reading());
    expect(await screen.findByText("Not enforced yet")).toBeInTheDocument();
    first.unmount();
    serve(reading({ enforce: "on", switches: switches({ envelope_enforce: "on" }) }));
    expect(await screen.findByText("Enforced")).toBeInTheDocument();
    expect(screen.queryByText("Not enforced yet")).toBeNull();
  });

  it("labels stored IV as stored, and live IV as live", async () => {
    const first = serve(reading());
    expect(await screen.findByText(/Stored IV/)).toBeInTheDocument();
    expect(screen.getByText(/last end-of-day volatility, not live quotes/)).toBeInTheDocument();
    first.unmount();
    serve(reading({ snapshot: snapshot({ source: "live" }) }));
    expect(await screen.findByText(/Live IV/)).toBeInTheDocument();
    expect(screen.queryByText(/Stored IV/)).toBeNull();
  });

  it("is a hatched n/a, never a zero, with no measurement yet", async () => {
    serve(empty());
    const s10 = await screen.findByRole("group", { name: "S10 gross" });
    expect(within(s10).getAllByText("n/a").length).toBeGreaterThanOrEqual(3);
    expect(s10.querySelector(".hatch")).not.toBeNull();
    expect(screen.getByText("No measurement has been recorded yet.")).toBeInTheDocument();
    const uew = screen.getByRole("group", { name: "U_ew" });
    expect(uew.querySelector(".hatch")).not.toBeNull();
    expect(screen.queryByText(/^0(\.0+)?%$/)).toBeNull();
    expect(screen.queryByText("$0")).toBeNull();
    const list = screen.getByRole("group", { name: "Other scenarios, gross and net of long options" });
    expect(list.querySelectorAll(".hatch").length).toBe(6);
    expect(screen.getByText("Glide not started")).toBeInTheDocument();
  });

  it("names a symbol it could not value and says the reading is partial", async () => {
    serve(reading({ snapshot: snapshot({ measured: false, unmeasured: ["TQQQ", "SOXL"], reasons: ["iv missing"] }) }));
    expect(await screen.findByText("Unmeasured")).toBeInTheDocument();
    expect(screen.getByText(/Could not value TQQQ, SOXL/)).toBeInTheDocument();
  });

  it("writes each switch's state in words", async () => {
    serve(
      reading({
        switches: switches({
          envelope_enforce: "record",
          slow_breaker: "10",
          cc_basis_floor: "0.95",
          bridge: "ended",
          hedge_instrument: "XND",
          tech_cap: "on",
          spxw_ready: "stay",
        }),
      }),
    );
    const list = await screen.findByRole("group", { name: "Switches", hidden: true });
    const row = (label: string) => within(list).getByText(label).closest("div") as HTMLElement;
    expect(row("Envelope limits")).toHaveTextContent("Recording only");
    expect(row("Slow drawdown breaker")).toHaveTextContent("Trips at 10% drawdown");
    expect(row("Covered-call floor")).toHaveTextContent("Down to 95% of cost basis");
    expect(row("Bridge hedge")).toHaveTextContent("Ended");
    expect(row("Hedge instrument")).toHaveTextContent("XND");
    expect(row("Tech-linked cap")).toHaveTextContent("On");
    expect(row("Tech-linked cap")).toHaveTextContent("from cli");
    expect(row("Stacking rule")).toHaveTextContent("Off");
    expect(row("SPXW cutover")).toHaveTextContent("Stay on SPY");
    expect(row("Leveraged entry signal")).toHaveTextContent("Recording only");
    expect(within(list).getAllByRole("term", { hidden: true })).toHaveLength(15);
  });

  it("says plainly when it could not load, and reads without writing", async () => {
    serve(reading());
    await screen.findByRole("group", { name: "S10 gross" });
    // The page only reads: every call was the one GET and nothing else.
    expect(apiFetchMock.mock.calls.every((c) => c[0] === "/envelope" && c.length === 1)).toBe(true);
  });

  it("says it could not load the envelope when the read fails", async () => {
    const { unmount } = renderWithQuery(<EnvelopeCard />, {});
    await waitFor(() => expect(screen.getByText("Could not load the risk envelope.")).toBeInTheDocument());
    unmount();
  });
});
