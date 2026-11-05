import type { StubLineData } from "@/components/ui/Stub";
import { formatMoneyCell } from "@/lib/money";
import { STRATEGY_EYEBROW } from "@/lib/strategy";
import type { DayTrade, DayTradeAction } from "./types";

/** Words, not colour: the card says what happened before it says anything else. */
export const ACTION_LABEL: Record<DayTradeAction, string> = {
  opened: "Opened",
  closed: "Closed",
  rolled: "Rolled",
};

const SHORT_DATE = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
const CLOCK = new Intl.DateTimeFormat("en-US", {
  hour: "numeric",
  minute: "2-digit",
  timeZone: "America/New_York",
});

const dollars = (v: number) => `$${v.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
/** A subtracted amount: unknown stays unknown, and a real zero is 0, not -0. */
const minus = (v: number | null): number | null => (v === null ? null : v === 0 ? 0 : -v);
const wordOf = (t: DayTrade) => (t.right === "P" ? "put" : t.right === "C" ? "call" : "option");

function spreadName(t: DayTrade): string {
  return `${t.strike}/${t.long_strike} ${t.right === "C" ? "call" : "put"} spread`;
}

/**
 * A value-book fill is a share trade in the option card's shape (src/reporting/day.py): `strike` is
 * the fill price, `contracts` the share count, `expiry` the fill's date, a buy is "opened" and a
 * sale "closed". Nothing about an option applies to it.
 */
const isValue = (t: DayTrade) => t.kind === "value";
const valueVerb = (t: DayTrade) => (t.action === "opened" ? "Bought" : "Sold");

export function tradeEyebrow(t: DayTrade): string {
  if (isValue(t)) return `${valueVerb(t)} · ${STRATEGY_EYEBROW.value}`;
  const kind = t.kind === "other" ? "Option" : STRATEGY_EYEBROW[t.kind];
  return `${ACTION_LABEL[t.action]} · ${kind}`;
}

export function tradeTitle(t: DayTrade): string {
  if (isValue(t)) return `${valueVerb(t)} ${t.contracts} ${t.underlying}`;
  const isSpread = t.kind === "spread" && t.long_strike !== null;
  const contract = isSpread ? spreadName(t) : `$${t.strike} ${wordOf(t)}`;
  if (t.action === "opened") return `${t.underlying} · Sold ${contract}`;
  if (t.action === "rolled") {
    const to = t.rolled_to ? ` to $${t.rolled_to.strike}` : "";
    return `${t.underlying} · Rolled ${contract}${to}`;
  }
  switch (t.how) {
    case "expired":
      return `${t.underlying} · ${contract} expired`;
    case "assigned":
      return `${t.underlying} · ${contract} assigned`;
    case "called_away":
      return `${t.underlying} · ${contract} called away`;
    default:
      return `${t.underlying} · ${isSpread ? "Closed" : "Bought back"} ${contract}`;
  }
}

export function tradeSentence(t: DayTrade): string {
  if (isValue(t)) return t.reason ?? `${valueVerb(t)} ${t.contracts} ${t.underlying} at ${formatMoneyCell(t.strike)}.`;
  if (t.action !== "opened") return t.reason ?? "Closed.";
  const collect = t.premium === null ? "Premium not recorded." : `You collected ${formatMoneyCell(t.premium)}.`;
  if (t.kind === "spread") {
    return t.capital === null ? collect : `${collect} The most you can lose is ${formatMoneyCell(t.capital)}.`;
  }
  const shares = 100 * t.contracts;
  const when = SHORT_DATE.format(new Date(`${t.expiry}T00:00:00Z`));
  if (t.kind === "cc") {
    return `${collect} If ${t.underlying} closes over ${dollars(t.strike)} on ${when}, your ${shares} shares are sold at ${dollars(t.strike)}.`;
  }
  return `${collect} If ${t.underlying} closes under ${dollars(t.strike)} on ${when}, you buy ${shares} shares at ${dollars(t.strike)}.`;
}

function perShare(total: number | null, contracts: number): string | null {
  return total === null || contracts <= 0 ? null : dollars(total / (100 * contracts));
}

export function tradeStub(t: DayTrade): StubLineData[] {
  if (isValue(t)) {
    // No commission line: value.db records none, and a made-up $0 would be a lie.
    const price: StubLineData = { label: "Price a share", value: t.strike, format: "money" };
    return t.action === "opened"
      ? [
          price,
          {
            label: "Cost",
            value: t.capital,
            format: "money",
            total: true,
            explain: "The shares times the fill price. Commissions are not recorded for the value book.",
          },
        ]
      : [
          price,
          {
            label: "Realised P&L",
            value: t.net_pnl,
            format: "signed-money",
            total: true,
            explain:
              "The proceeds less the average cost of what was held. Commissions are not recorded for the value book.",
          },
        ];
  }
  const n = t.contracts;
  const contractsWord = `${n} contract${n === 1 ? "" : "s"}`;
  const feeLabel = (word: string) => (t.commissions_complete ? word : `${word} (incomplete)`);
  const feeExplain = t.commissions_complete
    ? "What IBKR charged on the fills."
    : "Some fills have no commission recorded yet, so this is a lower bound.";

  if (t.action === "opened") {
    const price = perShare(t.premium, n);
    const held =
      t.capital === null || t.roc_pct === null
        ? "Return"
        : t.kind === "spread"
          ? `On ${formatMoneyCell(t.capital)} at risk`
          : t.kind === "cc"
            ? `On ${formatMoneyCell(t.capital)} of shares at the strike`
            : `On ${formatMoneyCell(t.capital)} held`;
    return [
      {
        label: "Premium",
        value: t.premium,
        format: "signed-money",
        explain: price === null ? undefined : `${contractsWord} sold at ${price} a share × 100.`,
      },
      { label: feeLabel("Commission"), value: minus(t.commissions), format: "signed-money", explain: feeExplain },
      {
        label: held,
        value: t.roc_pct,
        format: "percent",
        explain: "The premium divided by what is held against it. A yardstick, not a forecast.",
      },
      {
        label: "A year",
        value: t.annualized_pct,
        format: "percent",
        total: true,
        explain: "The return scaled to 365 days from the day it was sold.",
      },
    ];
  }

  const back = perShare(t.bought_back, n);
  return [
    {
      label: "Premium collected",
      value: t.premium,
      format: "signed-money",
      explain: `The credit when it was sold (${contractsWord}).`,
    },
    {
      label: "Bought back",
      value: minus(t.bought_back),
      format: "signed-money",
      explain:
        t.how === "expired"
          ? "Nothing to buy back: it expired worthless."
          : back === null
            ? undefined
            : `Bought back at ${back} a share × 100.`,
    },
    { label: feeLabel("Commissions"), value: minus(t.commissions), format: "signed-money", explain: feeExplain },
    {
      label: t.action === "rolled" ? "Net on this leg" : "Net P&L",
      value: t.net_pnl,
      format: "signed-money",
      total: true,
      explain: "The premium, less the buy-back and every commission. Realised: it is final.",
    },
  ];
}

export function timeLabel(t: DayTrade): string {
  if (t.how === "expired" || t.how === "assigned" || t.how === "called_away") return "At expiry";
  const d = new Date(t.at);
  return Number.isNaN(d.getTime()) ? "" : `${CLOCK.format(d)} ET`;
}

const ET_DAY = new Intl.DateTimeFormat("en-US", {
  weekday: "short",
  month: "short",
  day: "numeric",
  timeZone: "America/New_York",
});

/** "Fri, Oct 3": the New York day a trade happened, for places that show more than today. */
export function dateLabel(t: DayTrade): string {
  const d = new Date(t.at);
  return Number.isNaN(d.getTime()) ? "" : ET_DAY.format(d);
}

export function countByAction(trades: DayTrade[]): Record<DayTradeAction, number> {
  const out: Record<DayTradeAction, number> = { opened: 0, closed: 0, rolled: 0 };
  for (const t of trades) out[t.action] += 1;
  return out;
}
